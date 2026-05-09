"""Tax classification and aggregation for the Tax Assistant dashboard module."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

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
