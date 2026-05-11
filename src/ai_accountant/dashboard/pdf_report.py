"""Small dependency-free PDF report renderer for the dashboard export."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from textwrap import wrap
from typing import Any

import pandas as pd

from ..report import (
    _asset_flow_rows,
    _format_decimal,
    _risk_rows,
    _short,
    _to_decimal,
    _transaction_type_rows,
    _wallet_metrics,
)
from ..tax_assistant import (
    TAX_DISCLAIMER,
    normalize_tax_country,
    tax_classification_rows,
    tax_country_profile,
    tax_review_queue,
    tax_summary,
    yearly_summary,
)

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN_X = 54
MARGIN_TOP = 56
MARGIN_BOTTOM = 54


@dataclass(frozen=True)
class _Block:
    text: str
    size: int = 10
    bold: bool = False
    gap_before: int = 0
    gap_after: int = 4


def build_wallet_pdf_report(
    transactions: pd.DataFrame,
    wallet_address: str,
    *,
    meta: dict[str, Any] | None = None,
    tax_country: str | None = None,
    generated_at: datetime | None = None,
) -> bytes:
    """Return a compact PDF report for a wallet dashboard export."""
    generated_at = generated_at or datetime.now(timezone.utc)
    frame = transactions if transactions is not None else pd.DataFrame()
    country = normalize_tax_country(tax_country)
    profile = tax_country_profile(country)

    metrics = _wallet_metrics(frame, wallet_address, generated_at)
    tax = tax_summary(frame, wallet_address)
    asset_flow = _asset_flow_rows(frame)
    tx_mix = _transaction_type_rows(frame)
    dashboard_review = _risk_rows(frame)
    tax_review = tax_review_queue(frame, country=country, limit=20)
    classifications = tax_classification_rows(frame)
    yearly = yearly_summary(frame)

    blocks: list[_Block] = []
    _heading(blocks, "AI Accountant PDF Report", size=18)
    _line(blocks, f"Wallet summary: {_short(wallet_address, 10)}", bold=True)
    _line(blocks, f"Wallet address: {wallet_address}")
    _line(blocks, f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
    _line(blocks, f"Date range: {metrics['period']}")
    if meta:
        dataset = meta.get("dataset_label")
        fetched = str(meta.get("fetched_at") or "").replace("T", " ")[:16]
        if dataset:
            _line(blocks, f"Dataset: {dataset}")
        if fetched:
            _line(blocks, f"Last refreshed: {fetched} UTC")

    _heading(blocks, "Portfolio Overview")
    for label, value in (
        ("Transactions", metrics["total"]),
        ("Succeeded", metrics["succeeded"]),
        ("Failed", metrics["failed"]),
        ("Unique counterparties", metrics["sources"]),
    ):
        _line(blocks, f"{label}: {value}")

    _heading(blocks, "Balance Summary")
    balance = _balance_summary(frame)
    _line(blocks, "Dashboard balance starts at 0 SOL for the selected report window.")
    _line(blocks, f"Native SOL in: {balance['native_in']} SOL")
    _line(blocks, f"Native SOL out: {balance['native_out']} SOL")
    _line(blocks, f"Net change: {balance['native_net']} SOL")

    _heading(blocks, "Fees Summary")
    _line(blocks, f"Fees paid by this wallet: {metrics['fee_wallet']}")
    _line(blocks, f"Total network fees observed: {metrics['fee_total']}")

    _heading(blocks, "Asset Flow")
    if asset_flow:
        for row in asset_flow[:14]:
            _line(
                blocks,
                f"{row['asset']}: in {row['in']}, out {row['out']}, net {row['net']}",
            )
        _overflow_note(blocks, asset_flow, shown=14)
    else:
        _line(blocks, "No wallet movements were parsed.")

    _heading(blocks, "Transaction Mix")
    if tx_mix:
        for row in tx_mix:
            _line(blocks, f"{row['name']}: {row['count']} transactions, {row['pct']}%")
    else:
        _line(blocks, "No transaction types found.")

    _heading(blocks, "Review Queue")
    if dashboard_review:
        for row in dashboard_review[:16]:
            sig = _short(row.get("signature", ""), 8)
            _line(blocks, f"{row['severity']}: {row['title']} ({sig})", bold=True)
            _line(blocks, row["detail"])
        _overflow_note(blocks, dashboard_review, shown=16)
    else:
        _line(blocks, "No obvious review items in the parsed data.")

    _heading(blocks, "Transactions Requiring Review")
    if tax_review:
        for item in tax_review[:16]:
            sig = _short(item.get("signature", ""), 8)
            _line(
                blocks,
                f"{item['date']} - {item['category_label']} - {item['review_reason']} ({sig})",
                bold=True,
            )
            _line(blocks, item["suggested_tax_action"])
        _overflow_note(blocks, tax_review, shown=16)
    else:
        _line(blocks, "No transactions are currently flagged for tax review.")

    _heading(blocks, "Tax Assistant Summary")
    _line(blocks, f"Tax country: {profile['label']}")
    _line(blocks, str(profile["summary"]))
    _line(blocks, f"Income: {_fmt_sol(tax['total_income_sol'], signed=True)}")
    _line(blocks, f"Expense: {_fmt_sol(tax['total_expense_sol'])}")
    _line(blocks, f"Fees: {_fmt_sol(tax['total_fees_sol'])}")
    _line(blocks, f"Net change: {_fmt_sol(tax['net_sol'], signed=True)}")
    _line(blocks, f"Potentially taxable events: {tax['taxable_count']}")
    _line(blocks, f"Review needed: {tax['review_count']}")

    _heading(blocks, "Tax Classification")
    if classifications:
        for row in classifications:
            flag = "review" if row["flagged"] else "usually no queue"
            _line(
                blocks,
                f"{row['category_label']}: {row['count']} tx, SOL net {row['sol_net']} ({flag})",
            )
    else:
        _line(blocks, "No transaction categories found.")

    _heading(blocks, "Yearly Summary")
    if yearly:
        for row in yearly:
            _line(
                blocks,
                (
                    f"{row['year']}: income {row['income_sol']} SOL, "
                    f"expense {row['expense_sol']} SOL, fees {row['fees_sol']} SOL, "
                    f"potentially taxable {row['taxable_count']}"
                ),
            )
    else:
        _line(blocks, "No yearly data available.")

    _heading(blocks, "Disclaimer")
    _line(blocks, TAX_DISCLAIMER)
    _line(blocks, "This report is not financial advice, tax advice, or a final tax filing.")

    return _render_pdf(blocks)


def _balance_summary(frame: pd.DataFrame) -> dict[str, str]:
    native_in = _sum_decimal(frame, "native_in_sol")
    native_out = _sum_decimal(frame, "native_out_sol")
    native_net = _sum_decimal(frame, "native_net_sol")
    return {
        "native_in": _format_decimal(native_in),
        "native_out": _format_decimal(native_out),
        "native_net": _format_decimal(native_net, signed=True),
    }


def _sum_decimal(frame: pd.DataFrame, column: str) -> Decimal:
    if frame.empty or column not in frame.columns:
        return Decimal("0")
    return sum((_to_decimal(value) for value in frame.get(column, [])), Decimal("0"))


def _fmt_sol(value: Any, *, signed: bool = False) -> str:
    return f"{_format_decimal(value, signed=signed)} SOL"


def _heading(blocks: list[_Block], text: str, *, size: int = 14) -> None:
    blocks.append(_Block(text=text, size=size, bold=True, gap_before=14, gap_after=7))


def _line(blocks: list[_Block], text: str, *, bold: bool = False) -> None:
    blocks.append(_Block(text=text, bold=bold))


def _overflow_note(blocks: list[_Block], rows: list[Any], *, shown: int) -> None:
    hidden = max(0, len(rows) - shown)
    if hidden:
        _line(blocks, f"... plus {hidden} more rows in the dashboard export.")


def _render_pdf(blocks: list[_Block]) -> bytes:
    pages = _layout(blocks)
    if not pages:
        pages = [[]]

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    }

    kids: list[str] = []
    next_id = 5
    for page in pages:
        page_id = next_id
        content_id = next_id + 1
        next_id += 2
        kids.append(f"{page_id} 0 R")
        content = _page_content(page)
        objects[content_id] = (
            f"<< /Length {len(content)} >>\nstream\n".encode("latin-1")
            + content
            + b"\nendstream"
        )
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("latin-1")

    objects[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode(
        "latin-1"
    )

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = len(pdf)
        pdf.extend(f"{obj_id} 0 obj\n".encode("latin-1"))
        pdf.extend(objects[obj_id])
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    max_id = max(objects)
    pdf.extend(f"xref\n0 {max_id + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for obj_id in range(1, max_id + 1):
        pdf.extend(f"{offsets[obj_id]:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(
        (
            f"trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("latin-1")
    )
    return bytes(pdf)


def _layout(blocks: list[_Block]) -> list[list[tuple[int, int, bool, int, str]]]:
    pages: list[list[tuple[int, int, bool, int, str]]] = [[]]
    y = PAGE_HEIGHT - MARGIN_TOP
    max_width = PAGE_WIDTH - (2 * MARGIN_X)

    for block in blocks:
        if block.gap_before:
            y -= block.gap_before
        approx_chars = max(24, int(max_width / (block.size * 0.54)))
        lines = wrap(_clean_text(block.text), width=approx_chars) or [""]
        for line in lines:
            line_height = block.size + 4
            if y - line_height < MARGIN_BOTTOM:
                pages.append([])
                y = PAGE_HEIGHT - MARGIN_TOP
            pages[-1].append((MARGIN_X, y, block.bold, block.size, line))
            y -= line_height
        y -= block.gap_after
    return pages


def _page_content(page: list[tuple[int, int, bool, int, str]]) -> bytes:
    ops = []
    for x, y, bold, size, text in page:
        font = "F2" if bold else "F1"
        ops.append(f"BT /{font} {size} Tf {x} {y} Td ({_pdf_escape(text)}) Tj ET")
    return "\n".join(ops).encode("latin-1")


def _clean_text(value: str) -> str:
    text = str(value)
    replacements = {
        "\u2192": "->",
        "\u2014": "-",
        "\u2013": "-",
        "\u2026": "...",
        "\u00b7": "-",
        "\xa0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = unicodedata.normalize("NFKD", text)
    return text.encode("latin-1", "ignore").decode("latin-1")


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


__all__ = ["build_wallet_pdf_report"]
