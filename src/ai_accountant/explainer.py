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
