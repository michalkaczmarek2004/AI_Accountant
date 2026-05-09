"""Human-readable HTML and CSV reports for normalized wallet activity."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd

EXPORT_COLUMNS = [
    "date",
    "signature",
    "status",
    "transaction_type",
    "source",
    "description",
    "fee_sol",
    "native_in_sol",
    "native_out_sol",
    "native_net_sol",
    "token_in_summary",
    "token_out_summary",
    "net_flow_summary",
]


def render_html_report(
    transactions: pd.DataFrame,
    wallet_address: str,
    *,
    max_transactions: int = 250,
    generated_at: datetime | None = None,
) -> str:
    """Render a self-contained HTML report from an AI Accountant DataFrame."""
    generated_at = generated_at or datetime.now(timezone.utc)
    frame = _sorted_transactions(transactions)
    metrics = _wallet_metrics(frame, wallet_address, generated_at)
    asset_rows = _asset_flow_rows(frame)
    type_rows = _transaction_type_rows(frame)
    risk_rows = _risk_rows(frame)
    tx_rows = _transaction_rows(frame, limit=max_transactions)

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>AI Accountant Report - {_short(wallet_address, 8)}</title>",
            f"  <style>{_stylesheet()}</style>",
            "</head>",
            "<body>",
            '  <main class="page">',
            _hero(metrics),
            _kpi_grid(metrics),
            _notice(),
            _section("Asset Flow", _asset_table(asset_rows)),
            _section("Transaction Mix", _type_bars(type_rows)),
            _section("Review Queue", _risk_table(risk_rows)),
            _section("Transactions", _transactions_table(tx_rows, len(frame), max_transactions)),
            "  </main>",
            "</body>",
            "</html>",
        ]
    )


def write_wallet_report(
    transactions: pd.DataFrame,
    wallet_address: str,
    output_dir: str | Path = "reports",
    *,
    max_transactions: int = 250,
) -> dict[str, Path]:
    """Write HTML and CSV report files and return their paths."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    wallet_prefix = _filename_token(wallet_address[:12] or "wallet")
    base = f"ai_accountant_{wallet_prefix}_{stamp}"

    html_path = target / f"{base}.html"
    csv_path = target / f"{base}_transactions.csv"

    html_path.write_text(
        render_html_report(
            transactions,
            wallet_address,
            max_transactions=max_transactions,
        ),
        encoding="utf-8",
    )
    transaction_export_frame(transactions).to_csv(csv_path, index=False)

    return {"html": html_path, "csv": csv_path}


def transaction_export_frame(transactions: pd.DataFrame) -> pd.DataFrame:
    """Return a flat CSV-friendly transaction table."""
    frame = _sorted_transactions(transactions)
    if frame.empty:
        return pd.DataFrame(columns=EXPORT_COLUMNS)

    export = pd.DataFrame(
        {
            "date": frame.apply(_row_date, axis=1),
            "signature": frame.get("signature"),
            "status": frame.get("status"),
            "transaction_type": frame.get("transaction_type"),
            "source": frame.get("source"),
            "description": frame.get("description"),
            "fee_sol": frame.get("fee_sol").map(_format_decimal),
            "native_in_sol": frame.get("native_in_sol").map(_format_decimal),
            "native_out_sol": frame.get("native_out_sol").map(_format_decimal),
            "native_net_sol": frame.get("native_net_sol").map(_format_decimal),
            "token_in_summary": frame.get("token_in_summary"),
            "token_out_summary": frame.get("token_out_summary"),
            "net_flow_summary": frame.get("net_flow_summary"),
        }
    )
    return export[EXPORT_COLUMNS]


def _sorted_transactions(transactions: pd.DataFrame) -> pd.DataFrame:
    if transactions.empty:
        return transactions.copy()
    if "timestamp_unix" not in transactions.columns:
        return transactions.copy().reset_index(drop=True)
    return (
        transactions.sort_values("timestamp_unix", ascending=False, kind="stable")
        .reset_index(drop=True)
        .copy()
    )


def _wallet_metrics(
    frame: pd.DataFrame,
    wallet_address: str,
    generated_at: datetime,
) -> dict[str, str]:
    total = len(frame)
    succeeded = int((frame["status"] == "succeeded").sum()) if total else 0
    failed = int((frame["status"] == "failed").sum()) if total else 0
    fees = sum((_to_decimal(v) for v in frame.get("fee_sol", [])), Decimal("0"))
    wallet_fees = sum(
        (
            _to_decimal(row.get("fee_sol"))
            for _, row in frame.iterrows()
            if bool(row.get("fee_paid_by_wallet"))
        ),
        Decimal("0"),
    )
    sources = {
        str(source)
        for source in frame.get("source", [])
        if source is not None and str(source).strip()
    }
    dates = [_row_date(row) for _, row in frame.iterrows() if _row_date(row) != "Unknown"]
    period = "No transactions"
    if dates:
        period = f"{min(dates)} to {max(dates)}"

    return {
        "wallet": wallet_address,
        "wallet_short": _short(wallet_address, 8),
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "period": period,
        "total": str(total),
        "succeeded": str(succeeded),
        "failed": str(failed),
        "fee_total": f"{_format_decimal(fees)} SOL",
        "fee_wallet": f"{_format_decimal(wallet_fees)} SOL",
        "sources": str(len(sources)),
    }


def _asset_flow_rows(frame: pd.DataFrame) -> list[dict[str, str]]:
    assets: dict[str, dict[str, Any]] = {}

    def ensure(key: str, label: str, mint: str | None = None) -> dict[str, Any]:
        if key not in assets:
            assets[key] = {
                "key": key,
                "label": label,
                "mint": mint,
                "in": Decimal("0"),
                "out": Decimal("0"),
                "net": Decimal("0"),
            }
        return assets[key]

    for _, row in frame.iterrows():
        sol = ensure("SOL", "SOL")
        sol["in"] += _to_decimal(row.get("native_in_sol"))
        sol["out"] += _to_decimal(row.get("native_out_sol"))
        sol["net"] += _to_decimal(row.get("native_net_sol"))

        for flow in _iter_flow_details(row.get("token_flow_details")):
            mint = str(flow.get("mint") or "")
            if not mint:
                continue
            symbol = str(flow.get("symbol") or "Token")
            asset = ensure(mint, f"{symbol} ({_short(mint, 6)})", mint)
            asset["in"] += _to_decimal(flow.get("in"))
            asset["out"] += _to_decimal(flow.get("out"))
            asset["net"] += _to_decimal(flow.get("net"))

    rows = []
    for asset in assets.values():
        if asset["in"] == 0 and asset["out"] == 0 and asset["net"] == 0:
            continue
        rows.append(
            {
                "asset": asset["label"],
                "mint": asset["mint"] or "",
                "in": _format_decimal(asset["in"]),
                "out": _format_decimal(asset["out"]),
                "net": _format_decimal(asset["net"], signed=True),
                "direction": _direction(asset["net"]),
            }
        )
    return sorted(rows, key=lambda r: (r["asset"] != "SOL", r["asset"]))


def _transaction_type_rows(frame: pd.DataFrame) -> list[dict[str, str]]:
    if frame.empty:
        return []
    counts = Counter(str(v or "Unknown") for v in frame.get("transaction_type", []))
    total = sum(counts.values()) or 1
    rows = []
    for name, count in counts.most_common():
        pct = (Decimal(count) / Decimal(total)) * Decimal("100")
        rows.append({"name": name, "count": str(count), "pct": _format_decimal(pct)})
    return rows


def _risk_rows(frame: pd.DataFrame) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for _, row in frame.iterrows():
        signature = str(row.get("signature") or "")
        tx_label = _tx_label(row)
        if row.get("status") == "failed":
            rows.append(
                {
                    "severity": "High",
                    "title": "Failed transaction",
                    "detail": f"{tx_label} failed. Review fees and intended action.",
                    "signature": signature,
                }
            )
        if _to_decimal(row.get("fee_sol")) >= Decimal("0.01"):
            rows.append(
                {
                    "severity": "Medium",
                    "title": "High network fee",
                    "detail": f"{tx_label} paid {_format_decimal(row.get('fee_sol'))} SOL in fees.",
                    "signature": signature,
                }
            )
        if row.get("status") == "succeeded" and row.get("net_flow_summary") == "No net movement":
            rows.append(
                {
                    "severity": "Low",
                    "title": "No net movement",
                    "detail": f"{tx_label} succeeded but has no parsed wallet movement.",
                    "signature": signature,
                }
            )
        if not str(row.get("transaction_type") or "").strip():
            rows.append(
                {
                    "severity": "Low",
                    "title": "Missing transaction type",
                    "detail": f"{tx_label} needs manual classification.",
                    "signature": signature,
                }
            )
    return rows[:50]


def _fallback_programs(row: Any) -> str:
    pids = row.get("program_ids")
    if not isinstance(pids, list) or not pids:
        return ""
    return ", ".join(str(p)[:8] + "…" for p in pids[:2])


def _transaction_rows(frame: pd.DataFrame, *, limit: int) -> list[dict[str, str]]:
    rows = []
    for _, row in frame.head(limit).iterrows():
        signature = str(row.get("signature") or "")
        rows.append(
            {
                "date": _row_date(row),
                "status": str(row.get("status") or "Unknown"),
                "type": str(row.get("transaction_type") or "Unknown"),
                "source": str(row.get("source") or "Unknown"),
                "flow": str(row.get("net_flow_summary") or "No parsed flow"),
                "fee": f"{_format_decimal(row.get('fee_sol'))} SOL",
                "description": str(row.get("description") or ""),
                "signature": signature,
                "signature_short": _short(signature, 8),
                "explorer_url": f"https://explorer.solana.com/tx/{escape(signature)}",
                "tag_type": str(row.get("tag_type") or "Unknown"),
                "tag_protocol": str(row.get("tag_protocol") or "Unknown"),
                "tag_assets": str(row.get("tag_assets") or ""),
                "tag_amount_display": str(row.get("tag_amount_display") or ""),
                "tag_usd_estimate": row.get("tag_usd_estimate") or None,
                "tag_confidence": float(row.get("tag_confidence") or 0.0),
                "tag_confidence_pct": str(round(float(row.get("tag_confidence") or 0.0) * 100)),
                "fallback_programs": _fallback_programs(row),
            }
        )
    return rows


def _hero(metrics: Mapping[str, str]) -> str:
    wallet = escape(metrics["wallet"])
    wallet_short = escape(metrics["wallet_short"])
    period = escape(metrics["period"])
    generated_at = escape(metrics["generated_at"])
    return f"""
    <section class="hero">
      <div>
        <p class="eyebrow">AI Accountant</p>
        <h1>Wallet activity report</h1>
        <p class="lead">Readable on-chain activity summary for wallet
          <code>{wallet_short}</code>.</p>
      </div>
      <dl class="hero-meta">
        <div><dt>Wallet</dt><dd title="{wallet}">{wallet_short}</dd></div>
        <div><dt>Period</dt><dd>{period}</dd></div>
        <div><dt>Generated</dt><dd>{generated_at}</dd></div>
      </dl>
    </section>
    """


def _kpi_grid(metrics: Mapping[str, str]) -> str:
    cards = [
        ("Transactions", metrics["total"]),
        ("Succeeded", metrics["succeeded"]),
        ("Failed", metrics["failed"]),
        ("Unique counterparties", metrics["sources"]),
        ("Fees paid by this wallet", metrics["fee_wallet"]),
        ("Total network fees observed", metrics["fee_total"]),
    ]
    body = "\n".join(
        f'<article class="kpi"><span>{escape(label)}</span><strong>{escape(value)}</strong></article>'
        for label, value in cards
    )
    return f'<section class="kpi-grid" aria-label="Wallet overview">{body}</section>'


def _notice() -> str:
    return """
    <section class="notice">
      <strong>What this report is:</strong> real on-chain activity fetched from Helius and
      normalized by AI Accountant. <strong>What it is not:</strong> a final tax filing.
      USD valuation, off-chain cost basis, CEX imports and legal citations still need to be
      connected before the output can be treated as an accounting conclusion.
    </section>
    """


def _section(title: str, body: str) -> str:
    return f"""
    <section class="report-section">
      <header><h2>{escape(title)}</h2></header>
      {body}
    </section>
    """


def _asset_table(rows: Iterable[Mapping[str, str]]) -> str:
    rows = list(rows)
    if not rows:
        return '<p class="empty">No wallet movements were parsed.</p>'
    body = "\n".join(
        f"""
        <tr>
          <td><strong>{escape(row["asset"])}</strong><span>{escape(row["mint"])}</span></td>
          <td>{escape(row["in"])}</td>
          <td>{escape(row["out"])}</td>
          <td><mark class="{escape(row["direction"])}">{escape(row["net"])}</mark></td>
        </tr>
        """
        for row in rows
    )
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>Asset</th><th>In</th><th>Out</th><th>Net</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def _type_bars(rows: Iterable[Mapping[str, str]]) -> str:
    rows = list(rows)
    if not rows:
        return '<p class="empty">No transaction types found.</p>'
    bars = "\n".join(
        f"""
        <div class="bar-row">
          <div class="bar-label"><strong>{escape(row["name"])}</strong><span>{escape(row["count"])} tx</span></div>
          <div class="bar-track"><i style="width: {escape(row["pct"])}%"></i></div>
          <span class="bar-pct">{escape(row["pct"])}%</span>
        </div>
        """
        for row in rows
    )
    return f'<div class="bars">{bars}</div>'


def _risk_table(rows: Iterable[Mapping[str, str]]) -> str:
    rows = list(rows)
    if not rows:
        return '<p class="empty">No obvious review items in the parsed data.</p>'
    body = "\n".join(
        f"""
        <tr>
          <td><mark class="severity {escape(row["severity"].lower())}">{escape(row["severity"])}</mark></td>
          <td><strong>{escape(row["title"])}</strong><span>{escape(row["detail"])}</span></td>
          <td>{_signature_link(row["signature"])}</td>
        </tr>
        """
        for row in rows
    )
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>Severity</th><th>Item</th><th>Transaction</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def _transactions_table(rows: list[Mapping[str, str]], total: int, max_transactions: int) -> str:
    if not rows:
        return '<p class="empty">No transactions to display.</p>'
    note = ""
    if total > max_transactions:
        note = f'<p class="muted">Showing newest {max_transactions} of {total} transactions.</p>'
    body = "\n".join(
        f"""
        <tr>
          <td>{escape(row["date"])}</td>
          <td><mark class="{escape(row["status"])}">{escape(row["status"])}</mark></td>
          <td><strong>{escape(row["type"])}</strong><span>{escape(row["source"])}</span></td>
          <td>{escape(row["flow"])}</td>
          <td>{escape(row["fee"])}</td>
          <td>{_signature_link(row["signature"])}</td>
        </tr>
        <tr class="description-row"><td></td><td colspan="5">{escape(row["description"])}</td></tr>
        """
        for row in rows
    )
    return f"""
    {note}
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>Date</th><th>Status</th><th>Type</th><th>Net flow</th><th>Fee</th><th>Tx</th></tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def _signature_link(signature: str) -> str:
    if not signature:
        return ""
    safe_sig = escape(signature)
    return (
        f'<a href="https://explorer.solana.com/tx/{safe_sig}" '
        f'target="_blank" rel="noreferrer">{escape(_short(signature, 8))}</a>'
    )


def _row_date(row: Any) -> str:
    timestamp = row.get("timestamp", None)
    if isinstance(timestamp, str) and timestamp:
        return timestamp[:10]
    timestamp_unix = row.get("timestamp_unix", None)
    if timestamp_unix in (None, ""):
        return "Unknown"
    try:
        return datetime.fromtimestamp(int(timestamp_unix), timezone.utc).strftime("%Y-%m-%d")
    except (OSError, TypeError, ValueError):
        return "Unknown"


def _tx_label(row: Any) -> str:
    date = _row_date(row)
    tx_type = str(row.get("transaction_type") or "Unknown")
    sig = _short(str(row.get("signature") or ""), 8)
    return f"{date} {tx_type} {sig}".strip()


def _iter_flow_details(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _to_decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _format_decimal(value: Any, *, signed: bool = False) -> str:
    number = _to_decimal(value)
    if number == 0:
        return "0"
    rendered = format(number.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if signed and number > 0:
        return f"+{rendered}"
    return rendered


def _short(value: str, width: int = 6) -> str:
    if len(value) <= (width * 2) + 3:
        return value
    return f"{value[:width]}...{value[-width:]}"


def _direction(value: Decimal) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def _filename_token(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"}) or "wallet"


def _stylesheet() -> str:
    return """
    :root {
      color-scheme: light;
      --bg: #f5f7f8;
      --ink: #172126;
      --muted: #66737b;
      --line: #d9e0e4;
      --surface: #ffffff;
      --accent: #126a72;
      --accent-soft: #d9eef0;
      --good: #19734d;
      --bad: #a83d31;
      --warn: #996a13;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    .page {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 48px;
    }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 420px);
      gap: 28px;
      align-items: end;
      padding: 28px 0 18px;
      border-bottom: 1px solid var(--line);
    }
    .eyebrow {
      margin: 0 0 8px;
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    h1, h2, p { margin-top: 0; }
    h1 {
      max-width: 760px;
      margin-bottom: 12px;
      font-size: clamp(36px, 6vw, 66px);
      line-height: 1;
      letter-spacing: 0;
    }
    h2 {
      margin-bottom: 14px;
      font-size: 22px;
      letter-spacing: 0;
    }
    .lead {
      max-width: 720px;
      color: var(--muted);
      font-size: 18px;
    }
    code {
      padding: 2px 6px;
      border-radius: 6px;
      background: var(--accent-soft);
      color: var(--accent);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.92em;
    }
    .hero-meta {
      display: grid;
      gap: 10px;
      margin: 0;
    }
    .hero-meta div,
    .kpi,
    .notice,
    .report-section {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .hero-meta div {
      padding: 12px 14px;
    }
    dt, .kpi span {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    dd {
      margin: 2px 0 0;
      overflow-wrap: anywhere;
      font-weight: 650;
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      margin: 18px 0;
    }
    .kpi {
      min-height: 96px;
      padding: 14px;
    }
    .kpi strong {
      display: block;
      margin-top: 12px;
      overflow-wrap: anywhere;
      font-size: 25px;
      line-height: 1.1;
    }
    .notice {
      margin-bottom: 18px;
      padding: 14px 16px;
      color: #344047;
    }
    .report-section {
      margin-top: 18px;
      padding: 18px;
    }
    .table-wrap {
      width: 100%;
      overflow-x: auto;
    }
    table {
      width: 100%;
      min-width: 760px;
      border-collapse: collapse;
      font-size: 14px;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      text-align: left;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    th, td {
      padding: 11px 10px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }
    td span {
      display: block;
      margin-top: 3px;
      color: var(--muted);
      overflow-wrap: anywhere;
      font-size: 12px;
    }
    a {
      color: var(--accent);
      font-weight: 700;
      text-decoration: none;
    }
    mark {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #eef1f2;
      color: var(--ink);
      font-weight: 700;
    }
    .positive, .succeeded { background: #dff3e9; color: var(--good); }
    .negative, .failed, .high { background: #f8dfdc; color: var(--bad); }
    .medium { background: #f8edd7; color: var(--warn); }
    .low { background: #e4edf7; color: #245b86; }
    .neutral { background: #eef1f2; color: var(--muted); }
    .bars {
      display: grid;
      gap: 12px;
    }
    .bar-row {
      display: grid;
      grid-template-columns: minmax(180px, 260px) minmax(160px, 1fr) 64px;
      gap: 14px;
      align-items: center;
    }
    .bar-label span,
    .muted,
    .empty {
      color: var(--muted);
    }
    .bar-track {
      height: 12px;
      overflow: hidden;
      border-radius: 999px;
      background: #e4e9ec;
    }
    .bar-track i {
      display: block;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, #126a72, #3f8f6f);
    }
    .bar-pct {
      color: var(--muted);
      font-variant-numeric: tabular-nums;
      text-align: right;
    }
    .description-row td {
      padding-top: 0;
      color: var(--muted);
      font-size: 13px;
    }
    @media (max-width: 900px) {
      .hero { grid-template-columns: 1fr; }
      .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .bar-row { grid-template-columns: 1fr; gap: 6px; }
      .bar-pct { text-align: left; }
    }
    """


__all__ = [
    "EXPORT_COLUMNS",
    "render_html_report",
    "transaction_export_frame",
    "write_wallet_report",
]
