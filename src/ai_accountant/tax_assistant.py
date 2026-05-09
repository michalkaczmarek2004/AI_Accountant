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
