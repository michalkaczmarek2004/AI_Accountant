# Transaction Explanation Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `explainer.py` module that generates plain-English `TransactionExplanation` objects from DataFrame rows, wire it into the dashboard context, and replace the raw transactions table with expandable `<details>`/`<summary>` rows.

**Architecture:** A new `src/ai_accountant/explainer.py` reads the tag columns already present on each DataFrame row (produced by `tagger.py`) and returns a frozen `TransactionExplanation` dataclass. `dashboard/views.py` calls `explain_row()` for each row on the page slice and zips the results with the existing `tx_rows` list. The template loops over the paired list, rendering each transaction as a `<details>` element — no JavaScript required.

**Tech Stack:** Python 3.10, pandas, stdlib dataclasses, Jinja2, HTML `<details>`/`<summary>`

---

## File Map

| Action | File |
|---|---|
| Create | `src/ai_accountant/explainer.py` |
| Create | `tests/test_explainer.py` |
| Modify | `src/ai_accountant/dashboard/views.py` |
| Modify | `tests/dashboard/test_views.py` |
| Modify | `src/ai_accountant/dashboard/templates/wallet.html.j2` |
| Modify | `src/ai_accountant/dashboard/server/static/dashboard.css` |

---

## Task 1: Scaffold explainer.py with dataclass + helper utilities

**Files:**
- Create: `src/ai_accountant/explainer.py`
- Create: `tests/test_explainer.py`

- [ ] **Step 1: Write the failing tests for the two helper utilities**

Create `tests/test_explainer.py` with this exact content:

```python
from __future__ import annotations

import unittest
from decimal import Decimal

from ai_accountant.explainer import _format_sol, _shorten_address


class ShortenAddressTests(unittest.TestCase):
    def test_long_address_truncated(self):
        self.assertEqual(_shorten_address("AbcDEFGH12345678abcdefgh"), "AbcD…efgh")

    def test_address_exactly_8_chars_unchanged(self):
        self.assertEqual(_shorten_address("Abcd1234"), "Abcd1234")

    def test_short_address_unchanged(self):
        self.assertEqual(_shorten_address("Ab12"), "Ab12")

    def test_empty_string(self):
        self.assertEqual(_shorten_address(""), "")


class FormatSolTests(unittest.TestCase):
    def test_positive_decimal(self):
        self.assertEqual(_format_sol(Decimal("1.5")), "1.5 SOL")

    def test_negative_uses_absolute_value(self):
        self.assertEqual(_format_sol(Decimal("-0.5")), "0.5 SOL")

    def test_zero(self):
        self.assertEqual(_format_sol(Decimal("0")), "0 SOL")

    def test_small_amount(self):
        self.assertEqual(_format_sol(Decimal("0.000005")), "0.000005 SOL")

    def test_none_treated_as_zero(self):
        self.assertEqual(_format_sol(None), "0 SOL")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they FAIL**

```
pytest tests/test_explainer.py -v
```

Expected: `ModuleNotFoundError: No module named 'ai_accountant.explainer'`

- [ ] **Step 3: Create explainer.py with the dataclass and helpers only**

Create `src/ai_accountant/explainer.py` with this exact content:

```python
"""Generate plain-English explanations for parsed Solana transaction rows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd


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
```

- [ ] **Step 4: Run tests to verify they PASS**

```
pytest tests/test_explainer.py -v
```

Expected: 9 passed

- [ ] **Step 5: Commit**

```
git add src/ai_accountant/explainer.py tests/test_explainer.py
git commit -m "feat(explainer): scaffold TransactionExplanation dataclass and helper utilities"
```

---

## Task 2: Implement explain_row with all classification cases

**Files:**
- Modify: `tests/test_explainer.py` (add 7 integration tests)
- Modify: `src/ai_accountant/explainer.py` (add all private helpers + explain_row)

- [ ] **Step 1: Add 7 integration tests to tests/test_explainer.py**

Append these imports and test class **after** the existing content in `tests/test_explainer.py`:

```python
import pandas as pd

from ai_accountant.explainer import TransactionExplanation, explain_row

_SIG = "AbcDEFGH12345678abcdefgh12345678abcdefgh12345678abcdefgh1234567"


def _base_row(**overrides) -> pd.Series:
    row: dict[str, Any] = {
        "tag_type": "Transfer",
        "tag_protocol": "Unknown",
        "tag_assets": "SOL",
        "tag_amount_display": "1 SOL",
        "tag_confidence": 0.8,
        "source": "UNKNOWN",
        "status": "succeeded",
        "fee_sol": Decimal("0.000005"),
        "native_net_sol": Decimal("1.0"),
        "token_flow_details": [],
        "date": "2024-01-01",
        "signature": _SIG,
        "description": "SOL transfer",
    }
    row.update(overrides)
    return pd.Series(row)


class ExplainRowTests(unittest.TestCase):
    def test_incoming_sol_source_unknown(self):
        row = _base_row(
            tag_type="Transfer", tag_protocol="Unknown", source="UNKNOWN",
            native_net_sol=Decimal("1.0"), tag_confidence=0.8,
        )
        exp = explain_row(row)
        self.assertIsInstance(exp, TransactionExplanation)
        self.assertEqual(exp.event_title, "Received SOL")
        self.assertEqual(exp.review_label, "Source unknown")
        self.assertEqual(exp.confidence_percent, 80)
        self.assertIn("source_unknown", exp.tags)
        self.assertIn("needs_label", exp.tags)
        self.assertIsInstance(exp.short_explanation, str)
        self.assertIsInstance(exp.known_facts, list)
        self.assertTrue(all(isinstance(f, str) for f in exp.known_facts))
        self.assertIsInstance(exp.unknown_facts, list)
        self.assertTrue(all(isinstance(f, str) for f in exp.unknown_facts))
        self.assertIsInstance(exp.suggested_actions, list)
        self.assertTrue(all(isinstance(a, str) for a in exp.suggested_actions))
        self.assertIsInstance(exp.expanded_explanation, str)
        self.assertIsInstance(exp.technical_summary, str)
        self.assertIsInstance(exp.tags, list)

    def test_outgoing_sol_known_source(self):
        row = _base_row(
            tag_type="Transfer", tag_protocol="Unknown", source="SYSTEM_PROGRAM",
            native_net_sol=Decimal("-0.5"), tag_confidence=0.8,
        )
        exp = explain_row(row)
        self.assertEqual(exp.event_title, "Sent SOL")
        self.assertEqual(exp.review_label, "No action needed")
        self.assertIn("outgoing", exp.tags)
        self.assertIn("sol", exp.tags)
        self.assertIsInstance(exp.confidence_percent, int)

    def test_swap(self):
        row = _base_row(
            tag_type="Swap", tag_protocol="Jupiter", source="JUPITER",
            tag_assets="SOL → USDC", tag_amount_display="1 SOL → 150 USDC",
            native_net_sol=Decimal("-1.0"), tag_confidence=0.95,
            token_flow_details=[{"symbol": "USDC", "net": Decimal("150"), "mint": "EPjF…"}],
        )
        exp = explain_row(row)
        self.assertEqual(exp.event_title, "Swapped tokens")
        self.assertEqual(exp.review_label, "Tax-relevant review")
        self.assertIn("swap", exp.tags)
        self.assertIn("tax_relevant", exp.tags)
        self.assertIsInstance(exp.suggested_actions, list)

    def test_unknown_program(self):
        row = _base_row(
            tag_type="Unknown", tag_protocol="Unknown", source="UNKNOWN",
            tag_assets="", tag_amount_display="",
            native_net_sol=Decimal("0"), tag_confidence=0.70,
            token_flow_details=[], description="",
        )
        exp = explain_row(row)
        self.assertEqual(exp.review_label, "Unknown program")
        self.assertIn("unknown_program", exp.tags)
        self.assertIsInstance(exp.suggested_actions, list)
        self.assertTrue(len(exp.suggested_actions) >= 1)

    def test_nft_received(self):
        row = _base_row(
            tag_type="NFT Buy/Sell", tag_protocol="Tensor", source="TENSOR",
            native_net_sol=Decimal("0"), tag_confidence=0.80,
        )
        exp = explain_row(row)
        self.assertEqual(exp.event_title, "Received NFT")
        self.assertEqual(exp.review_label, "Review NFT source")
        self.assertIn("nft", exp.tags)
        self.assertIn("incoming", exp.tags)

    def test_staked_sol(self):
        row = _base_row(
            tag_type="Stake/Unstake", tag_protocol="Marinade", source="MARINADE",
            native_net_sol=Decimal("-5.0"), tag_confidence=0.95,
        )
        exp = explain_row(row)
        self.assertEqual(exp.event_title, "Staked SOL")
        self.assertEqual(exp.review_label, "No action needed")
        self.assertIn("staking", exp.tags)

    def test_unknown_low_confidence(self):
        row = _base_row(
            tag_type="Unknown", tag_protocol="Unknown", source="UNKNOWN",
            tag_assets="", tag_amount_display="",
            native_net_sol=Decimal("0"), tag_confidence=0.30,
            token_flow_details=[], description="",
        )
        exp = explain_row(row)
        self.assertEqual(exp.event_title, "Unknown activity")
        self.assertEqual(exp.review_label, "Needs review")
        self.assertIn("low_confidence", exp.tags)
```

Also add `from typing import Any` to the top-level imports in `tests/test_explainer.py`.

- [ ] **Step 2: Run tests to verify the new cases FAIL**

```
pytest tests/test_explainer.py::ExplainRowTests -v
```

Expected: `AttributeError: module 'ai_accountant.explainer' has no attribute 'explain_row'`

- [ ] **Step 3: Replace explainer.py with the full implementation**

Overwrite `src/ai_accountant/explainer.py` with this complete content:

```python
"""Generate plain-English explanations for parsed Solana transaction rows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd


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


_TAX_DISCLAIMER = (
    "This may be relevant for tax or portfolio reporting depending on your country. "
    "This is not a legal or tax conclusion."
)

# (event_title, base_review_label, base_tags)
_CASE_MAP: dict[str, tuple[str, str, list[str]]] = {
    "sol_in":             ("Received SOL",       "No action needed",    ["incoming", "sol"]),
    "sol_out":            ("Sent SOL",            "No action needed",    ["outgoing", "sol"]),
    "token_in":           ("Received token",      "No action needed",    ["incoming", "token"]),
    "token_out":          ("Sent token",          "No action needed",    ["outgoing", "token"]),
    "swap":               ("Swapped tokens",      "Tax-relevant review", ["swap", "tax_relevant"]),
    "nft_bought":         ("Bought NFT",          "Tax-relevant review", ["nft", "tax_relevant"]),
    "nft_sold":           ("Sold NFT",            "Tax-relevant review", ["nft", "tax_relevant"]),
    "nft_received":       ("Received NFT",        "Review NFT source",   ["nft", "incoming"]),
    "staking_deposit":    ("Staked SOL",          "No action needed",    ["staking"]),
    "staking_withdrawal": ("Unstaked SOL",        "No action needed",    ["staking"]),
    "airdrop":            ("Received airdrop",    "Tax-relevant review", ["airdrop", "tax_relevant"]),
    "lp":                 ("LP interaction",      "Tax-relevant review", ["lp", "tax_relevant"]),
    "mint_burn":          ("Token mint/burn",     "No action needed",    ["mint_burn"]),
    "bridge":             ("Bridge transfer",     "No action needed",    ["bridge"]),
    "perp":               ("Perpetual trade",     "Tax-relevant review", ["perp", "tax_relevant"]),
    "unknown":            ("Unknown activity",    "Needs review",        ["unknown"]),
}

_TAX_CASES: frozenset[str] = frozenset({"swap", "nft_bought", "nft_sold", "airdrop", "lp", "perp"})
_INCOMING_CASES: frozenset[str] = frozenset({"sol_in", "token_in", "nft_received"})
_OUTGOING_CASES: frozenset[str] = frozenset({"sol_out", "token_out"})


def _safe_decimal(value: Any) -> Decimal:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return Decimal("0")
    try:
        d = Decimal(str(value))
        return d if d.is_finite() else Decimal("0")
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _safe_str(value: Any, default: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    return str(value)


def _safe_float(value: Any) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _shorten_address(addr: str) -> str:
    s = str(addr or "")
    if len(s) <= 8:
        return s
    return f"{s[:4]}…{s[-4:]}"


def _format_sol(amount: Any) -> str:
    d = _safe_decimal(amount).copy_abs()
    return f"{d.normalize():f} SOL"


def _token_flows(row: pd.Series) -> list[dict]:
    flows = row.get("token_flow_details")
    if flows is None or (isinstance(flows, float) and math.isnan(flows)):
        return []
    return [f for f in flows if isinstance(f, dict)] if isinstance(flows, list) else []


def _classify(row: pd.Series) -> str:
    tag_type = _safe_str(row.get("tag_type"), "Unknown")
    native_net = _safe_decimal(row.get("native_net_sol"))
    flows = _token_flows(row)

    if tag_type == "Transfer":
        if native_net > 0:
            return "sol_in"
        if native_net < 0:
            return "sol_out"
        token_net = sum(_safe_decimal(f.get("net")) for f in flows)
        if token_net > 0:
            return "token_in"
        if token_net < 0:
            return "token_out"
        return "unknown"
    if tag_type == "Swap":
        return "swap"
    if tag_type == "NFT Buy/Sell":
        if native_net < 0:
            return "nft_bought"
        if native_net > 0:
            return "nft_sold"
        return "nft_received"
    if tag_type == "Stake/Unstake":
        return "staking_deposit" if native_net <= 0 else "staking_withdrawal"
    if tag_type == "Airdrop":
        return "airdrop"
    if tag_type == "LP Deposit/Withdraw":
        return "lp"
    if tag_type == "Mint/Burn":
        return "mint_burn"
    if tag_type == "Bridge":
        return "bridge"
    if tag_type == "Perpetual Trade":
        return "perp"
    return "unknown"


def _is_source_unknown(row: pd.Series) -> bool:
    source = _safe_str(row.get("source"), "").upper()
    protocol = _safe_str(row.get("tag_protocol"), "")
    return source in ("UNKNOWN", "") and protocol == "Unknown"


def _has_unknown_token(row: pd.Series) -> bool:
    return any(
        not f.get("symbol") or f.get("symbol") == "Token"
        for f in _token_flows(row)
    )


def _build_review_label(row: pd.Series, case: str, base: str) -> str:
    status = _safe_str(row.get("status"), "")
    confidence = _safe_float(row.get("tag_confidence"))
    if status == "failed":
        return "Failed transaction"
    if confidence < 0.7:
        return "Needs review"
    if case in _INCOMING_CASES and _is_source_unknown(row):
        return "Source unknown"
    if case == "unknown" and _safe_str(row.get("tag_protocol"), "") == "Unknown":
        return "Unknown program"
    return base


def _build_tags(row: pd.Series, case: str, base_tags: list[str]) -> list[str]:
    tags = list(base_tags)
    status = _safe_str(row.get("status"), "")
    confidence = _safe_float(row.get("tag_confidence"))
    if status == "failed":
        tags.append("failed")
    if confidence < 0.7:
        tags.append("low_confidence")
    if case in _INCOMING_CASES and _is_source_unknown(row):
        tags.extend(["source_unknown", "needs_label"])
    if _has_unknown_token(row):
        tags.append("unknown_token")
    if case == "unknown" and _safe_str(row.get("tag_protocol"), "") == "Unknown":
        tags.append("unknown_program")
    return tags


def _build_known_facts(row: pd.Series) -> list[str]:
    facts: list[str] = []
    status = _safe_str(row.get("status"), "unknown")
    facts.append(f"The transaction {status}.")
    tag_assets = _safe_str(row.get("tag_assets"), "")
    tag_amount = _safe_str(row.get("tag_amount_display"), "")
    if tag_assets and tag_amount:
        facts.append(f"Assets involved: {tag_assets} ({tag_amount}).")
    elif tag_assets:
        facts.append(f"Assets involved: {tag_assets}.")
    fee = _safe_decimal(row.get("fee_sol"))
    if fee > 0:
        facts.append(f"The network fee was {_format_sol(fee)}.")
    protocol = _safe_str(row.get("tag_protocol"), "Unknown")
    if protocol not in ("Unknown", ""):
        facts.append(f"Program: {protocol}.")
    return facts


def _build_unknown_facts(row: pd.Series, case: str) -> list[str]:
    facts: list[str] = []
    if case in _INCOMING_CASES and _is_source_unknown(row):
        facts.append("The source of the funds is not known.")
        facts.append(
            "The agent cannot determine whether this came from your own wallet, "
            "an exchange, another person, a reward, or an airdrop."
        )
    if case in _OUTGOING_CASES and not _safe_str(row.get("description"), "").strip():
        facts.append("The recipient address is not available in the parsed data.")
    if _has_unknown_token(row):
        facts.append("One or more token symbols could not be identified.")
    if case == "unknown" and _safe_str(row.get("tag_protocol"), "") == "Unknown":
        facts.append("The program that processed this transaction is not recognized.")
        facts.append("The purpose of this transaction is unclear.")
    if case in _TAX_CASES:
        facts.append(
            "Your tax country is not set — whether this event is taxable "
            "depends on your jurisdiction."
        )
    return facts


def _build_suggested_actions(row: pd.Series, case: str, tags: list[str]) -> list[str]:
    actions: list[str] = []
    if "source_unknown" in tags:
        actions.append("Label the source of this transfer.")
    if case == "unknown" and "unknown_program" in tags:
        actions.append("Review this unknown program interaction.")
    if case in _TAX_CASES:
        actions.append("Add cost basis for this asset.")
    if "low_confidence" in tags:
        actions.append("Mark this transaction as reviewed.")
    return actions[:3] if actions else ["No action needed."]


def _build_short_explanation(row: pd.Series, case: str) -> str:
    tag_amount = _safe_str(row.get("tag_amount_display"), "")
    tag_assets = _safe_str(row.get("tag_assets"), "")
    if case == "sol_in":
        base = f"Your wallet received {tag_amount or 'SOL'}."
        if _is_source_unknown(row):
            base += " The source of the funds is not known."
        return base
    if case == "sol_out":
        return f"Your wallet sent {tag_amount or 'SOL'} to another address."
    if case == "token_in":
        return f"Your wallet received {tag_amount or tag_assets or 'a token'}."
    if case == "token_out":
        return f"Your wallet sent {tag_amount or tag_assets or 'a token'}."
    if case == "swap":
        return f"Your wallet swapped {tag_amount or tag_assets or 'tokens'}."
    if case == "nft_bought":
        return f"Your wallet purchased an NFT ({tag_assets or 'unknown'})."
    if case == "nft_sold":
        return f"Your wallet sold an NFT ({tag_assets or 'unknown'})."
    if case == "nft_received":
        base = f"Your wallet received an NFT ({tag_assets or 'unknown'})."
        if _is_source_unknown(row):
            base += " The source is not known."
        return base
    if case == "staking_deposit":
        return f"Your wallet moved {tag_amount or 'SOL'} into staking."
    if case == "staking_withdrawal":
        return f"Your wallet withdrew {tag_amount or 'SOL'} from staking."
    if case == "airdrop":
        return f"Your wallet received {tag_amount or 'tokens'} as an airdrop."
    if case == "lp":
        return f"Your wallet interacted with a liquidity pool ({tag_assets or 'assets involved'})."
    if case == "mint_burn":
        return f"A token mint or burn was detected ({tag_assets or 'unknown'})."
    if case == "bridge":
        suffix = f" of {tag_amount}" if tag_amount else ""
        return f"Your wallet performed a bridge transfer{suffix}."
    if case == "perp":
        suffix = f" ({tag_amount})" if tag_amount else ""
        return f"Your wallet made a perpetual trade{suffix}."
    return "Your wallet had activity that the agent could not clearly classify."


def _build_expanded_explanation(row: pd.Series, case: str) -> str:
    protocol = _safe_str(row.get("tag_protocol"), "Unknown")
    status = _safe_str(row.get("status"), "")
    parts: list[str] = []

    if case == "sol_in":
        parts.append("This transaction increased your SOL balance.")
        if protocol not in ("Unknown", ""):
            parts.append(f"It was processed via {protocol}.")
        if _is_source_unknown(row):
            parts.append(
                "Because the sender is not recognized, label this transfer manually "
                "if you need accurate portfolio or accounting records."
            )
    elif case == "sol_out":
        parts.append("This transaction decreased your SOL balance.")
        if protocol not in ("Unknown", ""):
            parts.append(f"It was processed via {protocol}.")
    elif case == "token_in":
        parts.append("This transaction added tokens to your wallet.")
        if _is_source_unknown(row):
            parts.append("The sender is not recognized — label this transfer if needed.")
    elif case == "token_out":
        parts.append("This transaction removed tokens from your wallet.")
    elif case == "swap":
        via = f" via {protocol}" if protocol not in ("Unknown", "") else ""
        parts.append(f"Your wallet exchanged assets{via}.")
        parts.append(_TAX_DISCLAIMER)
    elif case == "nft_bought":
        parts.append("Your wallet paid for and received an NFT.")
        parts.append(_TAX_DISCLAIMER)
    elif case == "nft_sold":
        parts.append("Your wallet transferred an NFT and received payment.")
        parts.append(_TAX_DISCLAIMER)
    elif case == "nft_received":
        parts.append("Your wallet received an NFT. The source is not confirmed.")
        parts.append(
            "Review the NFT before interacting with it — "
            "some NFTs carry malicious links."
        )
    elif case == "staking_deposit":
        via = f" via {protocol}" if protocol not in ("Unknown", "") else ""
        parts.append(f"Your wallet delegated SOL to a staking pool{via}.")
    elif case == "staking_withdrawal":
        parts.append("Your wallet withdrew SOL from a staking position.")
    elif case == "airdrop":
        parts.append("Your wallet received tokens without sending payment.")
        parts.append(_TAX_DISCLAIMER)
    elif case == "lp":
        parts.append("Your wallet deposited or withdrew assets from a liquidity pool.")
        parts.append(_TAX_DISCLAIMER)
    elif case == "mint_burn":
        parts.append("A token creation or burn was detected in this transaction.")
    elif case == "bridge":
        parts.append("Assets were moved across blockchain networks via a bridge.")
    elif case == "perp":
        parts.append("A perpetual futures trade was recorded.")
        parts.append(_TAX_DISCLAIMER)
    else:
        parts.append("The agent could not classify this transaction from the available data.")
        parts.append("Manual review is recommended before relying on it for records.")

    if status == "failed":
        parts.append("Note: this transaction failed and no state change occurred on-chain.")

    return " ".join(parts)


def _build_technical_summary(row: pd.Series) -> str:
    sig = _safe_str(row.get("signature"), "")
    sig_short = _shorten_address(sig)
    status = _safe_str(row.get("status"), "unknown")
    tag_amount = _safe_str(row.get("tag_amount_display"), "")
    tag_assets = _safe_str(row.get("tag_assets"), "")
    description = _safe_str(row.get("description"), "").strip()

    if description:
        return f"{description} Transaction {sig_short}. Status: {status}."
    asset_str = tag_amount or tag_assets
    if asset_str:
        return f"Transaction {sig_short}: {asset_str}. Status: {status}."
    return f"Transaction {sig_short}. Status: {status}."


def explain_row(row: pd.Series) -> TransactionExplanation:
    """Return a TransactionExplanation for one parsed transaction row."""
    case = _classify(row)
    event_title, base_review_label, base_tags = _CASE_MAP[case]
    confidence_raw = _safe_float(row.get("tag_confidence"))
    confidence_percent = max(0, min(100, round(confidence_raw * 100)))
    review_label = _build_review_label(row, case, base_review_label)
    tags = _build_tags(row, case, base_tags)
    return TransactionExplanation(
        event_title=event_title,
        short_explanation=_build_short_explanation(row, case),
        review_label=review_label,
        confidence_percent=confidence_percent,
        known_facts=_build_known_facts(row),
        unknown_facts=_build_unknown_facts(row, case),
        suggested_actions=_build_suggested_actions(row, case, tags),
        expanded_explanation=_build_expanded_explanation(row, case),
        technical_summary=_build_technical_summary(row),
        tags=tags,
    )
```

- [ ] **Step 4: Run tests to verify all cases PASS**

```
pytest tests/test_explainer.py -v
```

Expected: 16 passed (9 helper tests + 7 integration tests)

- [ ] **Step 5: Commit**

```
git add src/ai_accountant/explainer.py tests/test_explainer.py
git commit -m "feat(explainer): implement explain_row with full classification and override rules"
```

---

## Task 3: Wire explain_row into views.py

**Files:**
- Modify: `src/ai_accountant/dashboard/views.py`
- Modify: `tests/dashboard/test_views.py`

- [ ] **Step 1: Add integration test to tests/dashboard/test_views.py**

Add this test method inside the existing `WalletPageTests` class in `tests/dashboard/test_views.py`:

```python
def test_transactions_contains_paired_explanation_tuples(self) -> None:
    from ai_accountant.explainer import TransactionExplanation

    ctx = wallet_page(_df([_row()]), spec=FilterSpec(), meta=_meta(), address=WALLET)
    txs = ctx["transactions"]
    self.assertEqual(len(txs), 1)
    row_dict, exp = txs[0]
    self.assertIsInstance(row_dict, dict)
    self.assertIsInstance(exp, TransactionExplanation)
    self.assertIsInstance(exp.event_title, str)
    self.assertIsInstance(exp.tags, list)
    self.assertIsInstance(exp.confidence_percent, int)
```

- [ ] **Step 2: Run the new test to verify it FAILS**

```
pytest tests/dashboard/test_views.py::WalletPageTests::test_transactions_contains_paired_explanation_tuples -v
```

Expected: `ValueError: not enough values to unpack` (transactions is still a list of dicts, not tuples)

- [ ] **Step 3: Update views.py to import explain_row and pair the lists**

In `src/ai_accountant/dashboard/views.py`:

Add the import at the top of the file alongside the existing imports:

```python
from ..explainer import explain_row
```

Then in `wallet_page()`, find this line (line 50):

```python
    tx_rows = _transaction_rows(page_slice, limit=PAGE_SIZE)
```

Add directly after it:

```python
    tx_explanations = [explain_row(row) for _, row in page_slice.iterrows()]
```

Then in the `return` dict, change:

```python
        "transactions": tx_rows,
```

to:

```python
        "transactions": list(zip(tx_rows, tx_explanations)),
```

- [ ] **Step 4: Run the new test to verify it PASSES**

```
pytest tests/dashboard/test_views.py::WalletPageTests::test_transactions_contains_paired_explanation_tuples -v
```

Expected: 1 passed

- [ ] **Step 5: Run the full dashboard test suite to verify no regressions**

```
pytest tests/dashboard/ -v
```

Expected: all previously passing tests still pass. The `test_transactions_paginated` test checks `len(ctx["transactions"]) == 50` — this still holds because `zip` returns a list of 50 tuples.

- [ ] **Step 6: Commit**

```
git add src/ai_accountant/dashboard/views.py tests/dashboard/test_views.py
git commit -m "feat(dashboard): wire explain_row into wallet_page context as paired tx list"
```

---

## Task 4: Update template and CSS for expandable transaction rows

**Files:**
- Modify: `src/ai_accountant/dashboard/server/static/dashboard.css`
- Modify: `src/ai_accountant/dashboard/templates/wallet.html.j2`

- [ ] **Step 1: Add CSS for the expandable rows to dashboard.css**

Append these rules to the end of `src/ai_accountant/dashboard/server/static/dashboard.css` (after the existing `@media` block):

```css
/* Expandable transaction rows */
.tx-list { display: flex; flex-direction: column; }
.tx-list-header {
  display: grid;
  grid-template-columns: 100px 1fr 1fr 90px 1fr 80px;
  gap: 8px;
  padding: 8px 10px;
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
  border-bottom: 2px solid var(--line);
}
details.tx-row { border-bottom: 1px solid var(--line); }
details.tx-row:last-child { border-bottom: none; }
.tx-summary {
  display: grid;
  grid-template-columns: 100px 1fr 1fr 90px 1fr 80px;
  gap: 8px;
  padding: 10px;
  cursor: pointer;
  list-style: none;
  align-items: center;
  font-size: 14px;
}
.tx-summary::-webkit-details-marker { display: none; }
.tx-summary::marker { display: none; }
details[open] > .tx-summary { background: var(--accent-soft); }
.tx-expanded {
  padding: 12px 16px 16px 16px;
  background: #f9fafb;
  border-top: 1px solid var(--line);
  font-size: 14px;
}
.tx-expanded h4 {
  margin: 10px 0 4px;
  font-size: 11px;
  text-transform: uppercase;
  color: var(--muted);
  letter-spacing: 0.05em;
}
.tx-expanded ul { margin: 0 0 4px; padding-left: 20px; }
.tx-expanded li { margin: 2px 0; }
.tx-expanded p { margin: 4px 0 8px; }
.tx-technical { margin-top: 10px; }
.tx-technical code {
  display: block;
  padding: 6px 8px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 12px;
  color: var(--muted);
  word-break: break-all;
}
@media (max-width: 900px) {
  .tx-list-header { display: none; }
  .tx-summary { grid-template-columns: 1fr 1fr; grid-template-rows: auto auto auto; }
}
```

- [ ] **Step 2: Replace the transactions section in wallet.html.j2**

In `src/ai_accountant/dashboard/templates/wallet.html.j2`, locate and replace the entire transactions section (currently lines 156–204, from `<section class="report-section">` with `<h2>Transactions</h2>` through the closing `{% endif %}` of that section) with:

```html
<section class="report-section">
  <h2>Transactions</h2>
  {% if transactions %}
  <div class="tx-list">
    <div class="tx-list-header">
      <span>Date</span>
      <span>Event</span>
      <span>Change</span>
      <span>Status</span>
      <span>Review</span>
      <span>Confidence</span>
    </div>
    {% for r, exp in transactions %}
    <details class="tx-row">
      <summary class="tx-summary">
        <span>{{ r.date }}</span>
        <span><strong>{{ exp.event_title }}</strong></span>
        <span>{{ r.tag_assets or r.tag_amount_display or '—' }}</span>
        <span><mark class="{{ r.status }}">{{ r.status }}</mark></span>
        <span>{{ exp.review_label }}</span>
        <span>
          {% set conf = exp.confidence_percent %}
          <mark class="confidence {% if conf >= 80 %}high{% elif conf >= 50 %}medium{% else %}low{% endif %}">{{ conf }}%</mark>
        </span>
      </summary>
      <div class="tx-expanded">
        <p>{{ exp.short_explanation }}</p>
        {% if exp.known_facts %}
        <h4>Known</h4>
        <ul>{% for f in exp.known_facts %}<li>{{ f }}</li>{% endfor %}</ul>
        {% endif %}
        {% if exp.unknown_facts %}
        <h4>Unknown</h4>
        <ul>{% for f in exp.unknown_facts %}<li>{{ f }}</li>{% endfor %}</ul>
        {% endif %}
        {% if exp.suggested_actions %}
        <h4>Suggested actions</h4>
        <ul>{% for a in exp.suggested_actions %}<li>{{ a }}</li>{% endfor %}</ul>
        {% endif %}
        {% if exp.expanded_explanation %}
        <p class="muted">{{ exp.expanded_explanation }}</p>
        {% endif %}
        <div class="tx-technical"><code>{{ exp.technical_summary }}</code></div>
        <p><a href="{{ url_for('tx_detail_route', address=address, sig=r.signature) }}" class="muted">View raw details →</a></p>
      </div>
    </details>
    {% endfor %}
  </div>
  <nav class="pagination">
    Page {{ transactions_page }} of {{ transactions_pages }}
    {% if transactions_page > 1 %}<a href="?{{ filter.to_querystring() }}{% if filter.to_querystring() %}&{% endif %}page={{ transactions_page - 1 }}">Prev</a>{% endif %}
    {% if transactions_page < transactions_pages %}<a href="?{{ filter.to_querystring() }}{% if filter.to_querystring() %}&{% endif %}page={{ transactions_page + 1 }}">Next</a>{% endif %}
  </nav>
  {% else %}<p class="empty">No transactions match the current filter.</p>{% endif %}
</section>
```

- [ ] **Step 3: Run the full test suite**

```
pytest -v
```

Expected: all tests pass. Template changes are not covered by unit tests; the dashboard route tests in `tests/dashboard/test_routes.py` exercise template rendering and will catch Jinja2 syntax errors.

- [ ] **Step 4: Manual smoke test**

Start the dashboard and verify the new layout:

```
python examples/open_dashboard.py --api-key YOUR_KEY
```

Or if you have cached data:

```
python examples/open_dashboard.py --api-key dummy
```

Open the wallet page and verify:
- The transactions section shows a header row: Date / Event / Change / Status / Review / Confidence
- Each transaction row is collapsed by default
- Clicking a row expands it and shows: short explanation, known facts, unknown facts, suggested actions, expanded explanation, technical summary, and a "View raw details" link
- The `<details>` open/close toggle works without JavaScript
- The confidence badge uses the correct colour class (green ≥ 80%, amber ≥ 50%, blue < 50%)

- [ ] **Step 5: Commit**

```
git add src/ai_accountant/dashboard/server/static/dashboard.css
git add src/ai_accountant/dashboard/templates/wallet.html.j2
git commit -m "feat(dashboard): replace transactions table with expandable details/summary rows"
```
