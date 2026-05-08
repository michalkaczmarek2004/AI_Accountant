"""Generate plain-English explanations for parsed Solana transaction rows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class TransactionExplanation:
    event_title: str
    short_explanation: str
    review_label: str
    confidence_percent: int
    known_facts: list[str]
    unknown_facts: list[str]
    suggested_actions: list[str]
    expanded_explanation: str
    technical_summary: str
    tags: list[str]


def _safe_decimal(value: Any) -> Decimal:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return Decimal("0")
    try:
        d = Decimal(str(value))
        return d if d.is_finite() else Decimal("0")
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _shorten_address(addr: str) -> str:
    s = str(addr or "")
    if len(s) <= 8:
        return s
    return f"{s[:4]}…{s[-4:]}"


def _format_sol(amount: Any) -> str:
    d = _safe_decimal(amount).copy_abs()
    return f"{d.normalize():f} SOL"
