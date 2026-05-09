"""Build template context dicts from a (filtered) DataFrame."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from html import escape
from typing import Any

import pandas as pd

from ..explainer import explain_row
from ..report import (
    _asset_flow_rows,
    _format_decimal,
    _risk_rows,
    _short,
    _to_decimal,
    _transaction_rows,
    _transaction_type_rows,
    _wallet_metrics,
)
from .charts import render_bar_svg, render_line_svg
from .filters import FilterSpec

PAGE_SIZE = 100
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def wallet_page(
    df: pd.DataFrame,
    *,
    spec: FilterSpec,
    meta: dict[str, Any] | None,
    address: str,
) -> dict[str, Any]:
    full_df = df if df is not None else pd.DataFrame()
    filtered = spec.apply(full_df) if not full_df.empty else full_df

    sorted_filtered = _sorted_desc(filtered)
    total = len(sorted_filtered)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(spec.page, pages)
    start = (page - 1) * PAGE_SIZE
    page_slice = sorted_filtered.iloc[start : start + PAGE_SIZE]

    kpis = _wallet_metrics(filtered, address, generated_at=datetime.now(timezone.utc))
    asset_flow = _asset_flow_rows(filtered)
    mix = _transaction_type_rows(filtered)
    risk = _risk_rows(filtered)
    tx_rows = _transaction_rows(page_slice, limit=PAGE_SIZE)
    tx_explanations = [explain_row(row) for _, row in page_slice.iterrows()]

    balance_points = _balance_points(filtered)
    activity_buckets = _activity_buckets(filtered)

    return {
        "address": address,
        "address_short": _short(address, 8),
        "meta": meta,
        "filter": spec,
        "filter_active": spec.is_active(),
        "kpis": kpis,
        "asset_flow": asset_flow,
        "transaction_mix": mix,
        "review_queue": risk,
        "transactions": list(zip(tx_rows, tx_explanations, strict=True)),
        "transactions_total": total,
        "transactions_page": page,
        "transactions_pages": pages,
        "transactions_page_size": PAGE_SIZE,
        "balance_chart_svg": render_line_svg(balance_points, y_label="SOL net"),
        "activity_chart_svg": render_bar_svg(activity_buckets),
        "filter_options": _filter_options(full_df),
    }


def transaction_detail(df: pd.DataFrame, signature: str, *, address: str) -> dict[str, Any]:
    if df is None or df.empty:
        raise KeyError(signature)
    matches = df[df["signature"] == signature]
    if matches.empty:
        raise KeyError(signature)
    row = matches.iloc[0]

    timestamp_unix = row.get("timestamp_unix")
    iso = ""
    if isinstance(timestamp_unix, (int, float)) and timestamp_unix:
        iso = datetime.fromtimestamp(int(timestamp_unix), timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    net_flow = row.get("net_flow") or {}
    net_flow_rows = []
    for key, value in net_flow.items() if isinstance(net_flow, dict) else []:
        net_flow_rows.append(
            {
                "key": str(key),
                "label": _flow_label(key, row.get("token_flow_details") or []),
                "amount": _format_decimal(value, signed=True),
            }
        )

    raw_pairs = [(c, _stringify(row.get(c))) for c in df.columns]

    return {
        "address": address,
        "address_short": _short(address, 8),
        "signature": str(row.get("signature") or ""),
        "signature_short": _short(str(row.get("signature") or ""), 8),
        "status": str(row.get("status") or "unknown"),
        "transaction_type": str(row.get("transaction_type") or "unknown"),
        "source": str(row.get("source") or "unknown"),
        "timestamp_iso": iso,
        "fee_sol": _format_decimal(row.get("fee_sol")),
        "fee_paid_by_wallet": bool(row.get("fee_paid_by_wallet")),
        "description": str(row.get("description") or ""),
        "net_flow_rows": net_flow_rows,
        "movements_in": list(row.get("movements_in") or []),
        "movements_out": list(row.get("movements_out") or []),
        "explorer_url": (
            f"https://explorer.solana.com/tx/{escape(str(row.get('signature') or ''))}"
        ),
        "raw_pairs": raw_pairs,
    }


def _sorted_desc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "timestamp_unix" not in df.columns:
        return df.copy() if not df.empty else df
    return df.sort_values("timestamp_unix", ascending=False, kind="stable").reset_index(drop=True)


def _balance_points(df: pd.DataFrame) -> list[tuple[date, Decimal]]:
    if df.empty or "native_net_sol" not in df.columns:
        return []
    asc = df.sort_values("timestamp_unix", ascending=True, kind="stable")
    daily: dict[date, Decimal] = {}
    for _, row in asc.iterrows():
        ts = row.get("timestamp_unix")
        if ts is None:
            continue
        try:
            day = datetime.fromtimestamp(int(ts), timezone.utc).date()
        except (OSError, TypeError, ValueError):
            continue
        daily[day] = daily.get(day, Decimal("0")) + _to_decimal(row.get("native_net_sol"))

    points: list[tuple[date, Decimal]] = []
    cumulative = Decimal("0")
    for day in sorted(daily):
        cumulative += daily[day]
        points.append((day, cumulative))
    return points


def _activity_buckets(df: pd.DataFrame) -> list[tuple[date, dict[str, int]]]:
    if df.empty or "timestamp_unix" not in df.columns:
        return []
    asc = df.sort_values("timestamp_unix", ascending=True, kind="stable")
    days: list[date] = []
    for ts in asc["timestamp_unix"]:
        if ts is None:
            continue
        try:
            days.append(datetime.fromtimestamp(int(ts), timezone.utc).date())
        except (OSError, TypeError, ValueError):
            continue
    if not days:
        return []
    span = (days[-1] - days[0]).days
    if span <= 60:

        def bin_fn(d: date) -> date:
            return d

    elif span <= 365:

        def bin_fn(d: date) -> date:
            iso = d.isocalendar()
            return date.fromisocalendar(iso.year, iso.week, 1)

    else:

        def bin_fn(d: date) -> date:
            return date(d.year, d.month, 1)

    buckets: dict[date, dict[str, int]] = {}
    for _, row in asc.iterrows():
        ts = row.get("timestamp_unix")
        if ts is None:
            continue
        try:
            d = datetime.fromtimestamp(int(ts), timezone.utc).date()
        except (OSError, TypeError, ValueError):
            continue
        key = bin_fn(d)
        slot = buckets.setdefault(key, {"succeeded": 0, "failed": 0})
        status = str(row.get("status") or "")
        if status in slot:
            slot[status] += 1
    return [(k, buckets[k]) for k in sorted(buckets)]


def _filter_options(df: pd.DataFrame) -> dict[str, list]:
    tokens: list[tuple[str, str]] = [("SOL", "SOL")]
    types: set[str] = set()
    sources: set[str] = set()
    tag_types: set[str] = set()
    if df.empty:
        return {"tokens": tokens, "types": [], "sources": [], "tag_types": []}

    seen_mints: set[str] = set()
    for _, row in df.iterrows():
        nf = row.get("net_flow")
        if isinstance(nf, dict):
            for key in nf:
                if key == "SOL":
                    continue
                if key in seen_mints:
                    continue
                seen_mints.add(key)
                label = _flow_label(key, row.get("token_flow_details") or [])
                tokens.append((str(key), label))
        ttype = row.get("transaction_type")
        if ttype:
            types.add(str(ttype))
        src = row.get("source")
        if src:
            sources.add(str(src))
        tt = row.get("tag_type")
        if tt:
            tag_types.add(str(tt))
    return {
        "tokens": tokens,
        "types": sorted(types),
        "sources": sorted(sources),
        "tag_types": sorted(tag_types),
    }


def _flow_label(key: str, token_flow_details: list) -> str:
    if key == "SOL":
        return "SOL"
    for entry in token_flow_details or []:
        if isinstance(entry, dict) and entry.get("mint") == key:
            symbol = entry.get("symbol") or "Token"
            return f"{symbol} ({_short(str(key), 6)})"
    return f"Token ({_short(str(key), 6)})"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return _format_decimal(value)
    return str(value)


def tax_page(
    df: pd.DataFrame,
    *,
    address: str,
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build template context for the Tax Assistant page."""
    from ..tax_assistant import (
        tax_classification_rows,
        tax_review_queue,
        tax_summary,
        yearly_summary,
    )

    no_data = df.empty or not (df["status"] == "succeeded").any()

    if no_data:
        return {
            "address": address,
            "address_short": _short(address, 4),
            "meta": meta,
            "summary": None,
            "classification": [],
            "review_queue": [],
            "yearly": [],
            "no_data": True,
        }

    raw = tax_summary(df, address)
    net_positive = raw["net_sol"] >= Decimal("0")
    summary = {
        "total_income_sol": f"+{_format_decimal(raw['total_income_sol'])} SOL",
        "total_expense_sol": f"-{_format_decimal(raw['total_expense_sol'])} SOL",
        "total_fees_sol": f"{_format_decimal(raw['total_fees_sol'])} SOL",
        "net_sol": f"{_format_decimal(raw['net_sol'], signed=True)} SOL",
        "net_positive": net_positive,
        "taxable_count": str(raw["taxable_count"]),
        "review_count": str(raw["review_count"]),
    }

    return {
        "address": address,
        "address_short": _short(address, 4),
        "meta": meta,
        "summary": summary,
        "classification": tax_classification_rows(df),
        "review_queue": tax_review_queue(df),
        "yearly": yearly_summary(df),
        "no_data": False,
    }


__all__ = ["wallet_page", "transaction_detail", "tax_page", "PAGE_SIZE"]
