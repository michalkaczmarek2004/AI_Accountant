"""Tax classification and aggregation for the Tax Assistant dashboard module."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pandas as pd

from .explainer import _classify, _is_source_unknown, _safe_decimal, _safe_str

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CASE_TO_CATEGORY: dict[str, str] = {
    "sol_in": "Income",
    "token_in": "Income",
    "nft_received": "Income",
    "sol_out": "Expense",
    "token_out": "Expense",
    "swap": "Swap",
    "nft_bought": "Swap",
    "nft_sold": "Swap",
    "lp": "Swap",
    "perp": "Swap",
    "staking_deposit": "Transfer",
    "bridge": "Transfer",
    "mint_burn": "Transfer",
    "staking_withdrawal": "Staking / Needs review",
    "airdrop": "Airdrop",
    "unknown": "Unknown / Needs review",
}

TAXABLE_CATEGORIES: frozenset[str] = frozenset({"Income", "Swap", "Airdrop"})

REVIEW_REQUIRED_CATEGORIES: frozenset[str] = frozenset({
    "Swap",
    "Airdrop",
    "Staking / Needs review",
    "Unknown / Needs review",
})

LARGE_FLOW_THRESHOLD: Decimal = Decimal("0.5")

TAX_DISCLAIMER = (
    "This is not financial or tax advice. "
    "Always consult a qualified tax professional."
)

# Category → review queue tier (lower = higher priority)
_CATEGORY_TIER: dict[str, int] = {
    "Unknown / Needs review": 1,
    "Swap": 2,
    "Airdrop": 3,
    "Staking / Needs review": 4,
}

# ---------------------------------------------------------------------------
# Public API — category
# ---------------------------------------------------------------------------


def tax_category(row: pd.Series) -> str:
    """Map a DataFrame row to one of the eight tax category labels."""
    case = _classify(row)
    return _CASE_TO_CATEGORY.get(case, "Unknown / Needs review")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _review_tier(row: pd.Series, category: str) -> int | None:
    """Return the priority tier (1–7) for the review queue, or None if not queued."""
    if category in _CATEGORY_TIER:
        return _CATEGORY_TIER[category]
    # Income, Expense, Transfer — only exceptional conditions enter the queue
    status = _safe_str(row.get("status"), "")
    if status == "failed":
        return 5
    net = _safe_decimal(row.get("native_net_sol"))
    if net.copy_abs() > LARGE_FLOW_THRESHOLD:
        return 6
    if _is_source_unknown(row):
        return 7
    return None


def _review_count(df: pd.DataFrame) -> int:
    """Count review-queue candidates without building the full queue (no explain_row calls)."""
    count = 0
    for _, row in df.iterrows():
        cat = tax_category(row)
        if _review_tier(row, cat) is not None:
            count += 1
    return count


def _row_date(row: pd.Series) -> str:
    ts = row.get("timestamp_unix")
    if ts is None:
        return "Unknown"
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d")
    except (OSError, TypeError, ValueError):
        return "Unknown"


def _fmt(d: Decimal, *, signed: bool = False) -> str:
    if not d:
        return "+0" if signed else "0"
    try:
        s = f"{d:+f}" if signed else f"{d:f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s
    except Exception:
        return "+0" if signed else "0"


# ---------------------------------------------------------------------------
# Public API — aggregation
# ---------------------------------------------------------------------------


def tax_summary(df: pd.DataFrame, address: str) -> dict[str, Any]:
    """Return aggregate tax metrics over the full (unfiltered) DataFrame."""
    zero = Decimal("0")
    if df.empty:
        return {
            "total_income_sol": zero,
            "total_expense_sol": zero,
            "total_fees_sol": zero,
            "net_sol": zero,
            "taxable_count": 0,
            "review_count": 0,
        }

    income = zero
    expense = zero
    fees = zero
    taxable_count = 0

    for _, row in df.iterrows():
        if _safe_str(row.get("status"), "") != "succeeded":
            continue
        cat = tax_category(row)
        net = _safe_decimal(row.get("native_net_sol"))
        if cat == "Income":
            income += net
        elif cat == "Expense":
            expense += net.copy_abs()
        if cat in TAXABLE_CATEGORIES:
            taxable_count += 1
        if bool(row.get("fee_paid_by_wallet")):
            fees += _safe_decimal(row.get("fee_sol"))

    return {
        "total_income_sol": income,
        "total_expense_sol": expense,
        "total_fees_sol": fees,
        "net_sol": income - expense,
        "taxable_count": taxable_count,
        "review_count": _review_count(df),
    }


def tax_review_queue(df: pd.DataFrame, *, limit: int = 100) -> list[dict]:
    """Return priority-sorted review queue items, each enriched with explain_row() output."""
    from .explainer import explain_row

    if df.empty:
        return []

    qualified: list[tuple[int, int, dict]] = []

    for _, row in df.iterrows():
        cat = tax_category(row)
        tier = _review_tier(row, cat)
        if tier is None:
            continue

        exp = explain_row(row)
        ts = int(row.get("timestamp_unix") or 0)
        sig = _safe_str(row.get("signature"), "")

        item = {
            "date": _row_date(row),
            "signature": sig,
            "sig_short": (sig[:8] + "…") if len(sig) > 8 else sig,
            "category": cat,
            "sol_net": _fmt(_safe_decimal(row.get("native_net_sol")), signed=True),
            "short_explanation": exp.short_explanation,
            "known_facts": exp.known_facts,
            "unknown_facts": exp.unknown_facts,
            "suggested_actions": exp.suggested_actions,
            "expanded_explanation": exp.expanded_explanation,
            "review_label": exp.review_label,
            "status": _safe_str(row.get("status"), ""),
            "source": _safe_str(row.get("source"), ""),
            "tag_protocol": _safe_str(row.get("tag_protocol"), ""),
            "tier": tier,
        }
        qualified.append((tier, -ts, item))

    qualified.sort(key=lambda x: (x[0], x[1]))
    return [item for _, _, item in qualified[:limit]]


def tax_classification_rows(df: pd.DataFrame) -> list[dict]:
    """Return one dict per tax category present, sorted by count (Unknown always last)."""
    if df.empty:
        return []

    buckets: dict[str, dict] = {}
    for _, row in df.iterrows():
        case = _classify(row)
        cat = _CASE_TO_CATEGORY.get(case, "Unknown / Needs review")
        if cat not in buckets:
            buckets[cat] = {"count": 0, "sol_net": Decimal("0"), "case_keys": set()}
        buckets[cat]["count"] += 1
        buckets[cat]["sol_net"] += _safe_decimal(row.get("native_net_sol"))
        buckets[cat]["case_keys"].add(case)

    unknown_bucket = buckets.pop("Unknown / Needs review", None)

    rows = [
        {
            "category": cat,
            "case_keys": sorted(data["case_keys"]),
            "count": data["count"],
            "sol_net": _fmt(data["sol_net"], signed=True),
            "flagged": cat in REVIEW_REQUIRED_CATEGORIES,
        }
        for cat, data in buckets.items()
    ]
    rows.sort(key=lambda r: -r["count"])

    if unknown_bucket is not None:
        rows.append({
            "category": "Unknown / Needs review",
            "case_keys": sorted(unknown_bucket["case_keys"]),
            "count": unknown_bucket["count"],
            "sol_net": _fmt(unknown_bucket["sol_net"], signed=True),
            "flagged": True,
        })

    return rows


def yearly_summary(df: pd.DataFrame) -> list[dict]:
    """Return per-year tax aggregates, sorted year descending."""
    if df.empty:
        return []

    years: dict[int, dict] = {}
    for _, row in df.iterrows():
        ts = row.get("timestamp_unix")
        if ts is None:
            continue
        try:
            year = datetime.fromtimestamp(int(ts), timezone.utc).year
        except (OSError, TypeError, ValueError):
            continue
        if _safe_str(row.get("status"), "") != "succeeded":
            continue

        cat = tax_category(row)
        net = _safe_decimal(row.get("native_net_sol"))

        if year not in years:
            years[year] = {
                "year": year,
                "_income": Decimal("0"),
                "_expense": Decimal("0"),
                "_fees": Decimal("0"),
                "taxable_count": 0,
            }
        if cat == "Income":
            years[year]["_income"] += net
        elif cat == "Expense":
            years[year]["_expense"] += net.copy_abs()
        if cat in TAXABLE_CATEGORIES:
            years[year]["taxable_count"] += 1
        if bool(row.get("fee_paid_by_wallet")):
            years[year]["_fees"] += _safe_decimal(row.get("fee_sol"))

    result = []
    for data in sorted(years.values(), key=lambda r: r["year"], reverse=True):
        result.append({
            "year": data["year"],
            "income_sol": _fmt(data["_income"], signed=True),
            "expense_sol": _fmt(data["_expense"]),
            "fees_sol": _fmt(data["_fees"]),
            "taxable_count": data["taxable_count"],
        })
    return result


_TAX_EXPORT_COLUMNS = [
    "date", "signature", "status", "tax_category", "case_key", "tag_type",
    "sol_net", "token_summary", "fee_sol", "is_potentially_taxable",
    "review_label", "notes",
]


_EXPORT_TAXABLE: frozenset[str] = TAXABLE_CATEGORIES & REVIEW_REQUIRED_CATEGORIES


def tax_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a flat DataFrame suitable for CSV export with full traceability columns."""
    from .explainer import explain_row

    if df.empty:
        return pd.DataFrame(columns=_TAX_EXPORT_COLUMNS)

    sorted_df = df.sort_values("timestamp_unix", ascending=False, kind="stable").reset_index(drop=True)
    rows = []
    for _, row in sorted_df.iterrows():
        case = _classify(row)
        cat = _CASE_TO_CATEGORY.get(case, "Unknown / Needs review")
        exp = explain_row(row)
        rows.append({
            "date": _row_date(row),
            "signature": _safe_str(row.get("signature"), ""),
            "status": _safe_str(row.get("status"), ""),
            "tax_category": cat,
            "case_key": case,
            "tag_type": _safe_str(row.get("tag_type"), ""),
            "sol_net": _fmt(_safe_decimal(row.get("native_net_sol")), signed=True),
            "token_summary": _safe_str(row.get("net_flow_summary"), ""),
            "fee_sol": _fmt(_safe_decimal(row.get("fee_sol"))),
            "is_potentially_taxable": "yes" if cat in _EXPORT_TAXABLE else "no",
            "review_label": exp.review_label,
            "notes": exp.short_explanation[:200],
        })
    return pd.DataFrame(rows, columns=_TAX_EXPORT_COLUMNS)


_YEARLY_EXPORT_COLUMNS = [
    "year", "income_sol", "expense_sol", "fees_sol", "potentially_taxable_count",
]


def tax_yearly_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return yearly_summary() as a flat DataFrame for CSV export."""
    if df.empty:
        return pd.DataFrame(columns=_YEARLY_EXPORT_COLUMNS)

    rows = [
        {
            "year": ys["year"],
            "income_sol": ys["income_sol"],
            "expense_sol": ys["expense_sol"],
            "fees_sol": ys["fees_sol"],
            "potentially_taxable_count": ys["taxable_count"],
        }
        for ys in yearly_summary(df)
    ]
    return pd.DataFrame(rows, columns=_YEARLY_EXPORT_COLUMNS)
