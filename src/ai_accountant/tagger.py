"""Classify parsed Solana transactions into human-readable labels."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pandas as pd

_HELIUS_TYPE_MAP: dict[str, str] = {
    "SWAP": "Swap",
    "TRANSFER": "Transfer",
    "SEND": "Transfer",
    "RECEIVE": "Transfer",
    "NFT_SALE": "NFT Buy/Sell",
    "NFT_LISTING": "NFT Buy/Sell",
    "NFT_BID": "NFT Buy/Sell",
    "NFT_BID_CANCELLED": "NFT Buy/Sell",
    "NFT_CANCEL_LISTING": "NFT Buy/Sell",
    "STAKE_SOL": "Stake/Unstake",
    "UNSTAKE_SOL": "Stake/Unstake",
    "STAKE_TOKEN": "Stake/Unstake",
    "ADD_LIQUIDITY": "LP Deposit/Withdraw",
    "REMOVE_LIQUIDITY": "LP Deposit/Withdraw",
    "AIRDROP": "Airdrop",
    "BURN": "Mint/Burn",
    "TOKEN_MINT": "Mint/Burn",
    "BRIDGE": "Bridge",
    "PERPETUAL_TRADE": "Perpetual Trade",
    "PERP_OPEN": "Perpetual Trade",
    "PERP_CLOSE": "Perpetual Trade",
}

_HELIUS_SOURCE_MAP: dict[str, str] = {
    "JUPITER": "Jupiter",
    "RAYDIUM": "Raydium",
    "METEORA": "Meteora",
    "PUMP_FUN": "Pump.fun",
    "TENSOR": "Tensor",
    "DRIFT": "Drift",
    "MARGIN_FI": "MarginFi",
    "MARINADE": "Marinade",
    "SANCTUM": "Sanctum",
}

KNOWN_PROGRAMS: dict[str, tuple[str, str]] = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": ("Swap", "Jupiter"),
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB": ("Swap", "Jupiter"),
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": ("Swap", "Raydium"),
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1": ("Swap", "Raydium"),
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EkAW7vAV": ("LP Deposit/Withdraw", "Meteora"),
    "LBUZKhRxPF3XUpBCjp4YzTKgLLjgzAkT3S3jT7hCwJ3": ("LP Deposit/Withdraw", "Meteora"),
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": ("Swap", "Pump.fun"),
    "TCMPhJdwDryooaGtiocG1u3xcYbRpiJzb283XoqBBnN": ("NFT Buy/Sell", "Tensor"),
    "dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH": ("Perpetual Trade", "Drift"),
    "MFv2hWf31Z9kbCa1snEPdcgKDBQwGHaRN1eJZ7QC2WL": ("Transfer", "MarginFi"),
    "MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD": ("Stake/Unstake", "Marinade"),
    "stkJF5aBBKFzHFHQoFeMHSvBPBbZu43k7hVz5cXnFqT": ("Stake/Unstake", "Sanctum"),
}


@dataclass
class TagResult:
    tag_type: str
    tag_protocol: str
    tag_assets: str
    tag_amount_display: str
    tag_usd_estimate: str | None
    tag_confidence: float


def _nan_safe(v: Any, default: Any) -> Any:
    if v is None:
        return default
    if isinstance(v, float) and math.isnan(v):
        return default
    return v


def _fmt_amount(symbol: str, amount: Decimal) -> str:
    if not amount.is_finite():
        return f"? {symbol}"
    normalized = amount.normalize()
    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    parts = rendered.split(".")
    try:
        int_part = f"{int(parts[0]):,}"
    except ValueError:
        int_part = parts[0]
    rendered = f"{int_part}.{parts[1]}" if len(parts) > 1 else int_part
    return f"{rendered} {symbol}"


def _build_assets(
    tag_type: str,
    net_flow: dict,
    token_flow_details: list,
    net_flow_summary: str,
) -> tuple[str, str]:
    if tag_type == "Swap":
        out_parts: list[tuple[str, Decimal]] = []
        in_parts: list[tuple[str, Decimal]] = []
        sol_net = net_flow.get("SOL")
        if sol_net is not None:
            sol_dec = Decimal(str(sol_net))
            if sol_dec < 0:
                out_parts.append(("SOL", abs(sol_dec)))
            elif sol_dec > 0:
                in_parts.append(("SOL", sol_dec))
        for flow in token_flow_details:
            if not isinstance(flow, dict):
                continue
            net = Decimal(str(flow.get("net", 0)))
            sym = str(flow.get("symbol") or "Token")
            if net < 0:
                out_parts.append((sym, abs(net)))
            elif net > 0:
                in_parts.append((sym, net))
        if out_parts and in_parts:
            assets_out = " + ".join(s for s, _ in out_parts)
            assets_in = " + ".join(s for s, _ in in_parts)
            amt_out = " + ".join(_fmt_amount(s, a) for s, a in out_parts)
            amt_in = " + ".join(_fmt_amount(s, a) for s, a in in_parts)
            return f"{assets_out} → {assets_in}", f"{amt_out} → {amt_in}"
        # else fall through to best-effort block below

    elif tag_type == "Transfer":
        candidates: list[tuple[str, Decimal]] = []
        sol_net = net_flow.get("SOL")
        if sol_net is not None:
            sol_dec = Decimal(str(sol_net))
            if sol_dec != 0:
                candidates.append(("SOL", abs(sol_dec)))
        for flow in token_flow_details:
            if not isinstance(flow, dict):
                continue
            net = Decimal(str(flow.get("net", 0)))
            sym = str(flow.get("symbol") or "Token")
            if net != 0:
                candidates.append((sym, abs(net)))
        if candidates:
            sym, amt = candidates[0]
            return sym, _fmt_amount(sym, amt)
        # else fall through to best-effort block below

    elif tag_type == "NFT Buy/Sell":
        nft_sym = "NFT"
        for flow in token_flow_details:
            if isinstance(flow, dict) and flow.get("symbol"):
                nft_sym = str(flow["symbol"])
                break
        sol_net = net_flow.get("SOL")
        if sol_net is not None:
            return nft_sym, _fmt_amount("SOL", abs(Decimal(str(sol_net))))
        return nft_sym, nft_sym

    # Best-effort for Stake/Unstake, LP, Airdrop, Mint/Burn, Bridge, Perpetual Trade,
    # and Swap/Transfer when structured flow data is insufficient.
    if tag_type != "Unknown":
        # Try to extract assets from flows
        moving = []
        sol_net = net_flow.get("SOL")
        if sol_net is not None:
            sol_dec = Decimal(str(sol_net))
            if sol_dec != 0:
                moving.append(("SOL", abs(sol_dec)))
        for flow in token_flow_details:
            if not isinstance(flow, dict):
                continue
            net = Decimal(str(flow.get("net", 0)))
            sym = str(flow.get("symbol") or "Token")
            if net != 0:
                moving.append((sym, abs(net)))
        if moving:
            assets = " + ".join(s for s, _ in moving)
            amounts = " + ".join(_fmt_amount(s, a) for s, a in moving)
            return assets, amounts
        # Fall back to net_flow_summary from parser
        if net_flow_summary:
            return net_flow_summary, net_flow_summary

    return "", ""


def _layer2_lookup(program_ids: list) -> tuple[str | None, str | None]:
    for pid in program_ids:
        match = KNOWN_PROGRAMS.get(str(pid))
        if match:
            return match[0], match[1]
    return None, None


def _layer3_heuristic(
    net_flow: dict,
    token_flow_details: list,
    movements_in: list,
    movements_out: list,
) -> tuple[str, float]:
    has_token_out = any(
        Decimal(str(f.get("net", 0))) < 0 for f in token_flow_details if isinstance(f, dict)
    )
    has_token_in = any(
        Decimal(str(f.get("net", 0))) > 0 for f in token_flow_details if isinstance(f, dict)
    )
    sol_net = Decimal(str(net_flow.get("SOL", 0)))

    if (has_token_out and (has_token_in or sol_net > 0)) or (has_token_in and sol_net < 0):
        return "Swap", 0.50

    all_movements = list(movements_in) + list(movements_out)
    counterparties = {
        str(m.get("counterparty"))
        for m in all_movements
        if isinstance(m, dict) and m.get("counterparty")
    }
    # parser always includes "SOL" key (may be zero); count only non-zero asset values
    nonzero_assets = sum(1 for v in net_flow.values() if Decimal(str(v)) != 0)

    # Transfer: single asset, single counterparty, no swap
    if (
        nonzero_assets >= 1
        and nonzero_assets <= 1
        and len(all_movements) >= 1
        and len(counterparties) == 1
        and not (has_token_out and has_token_in)
    ):
        return "Transfer", 0.55

    # Airdrop: token received, no token/SOL outflow, no identifiable counterparty
    if has_token_in and sol_net >= 0 and not has_token_out and not counterparties:
        return "Airdrop", 0.45

    return "Unknown", 0.10


def _tag_row(row: dict[str, Any]) -> TagResult:
    tx_type = _nan_safe(row.get("transaction_type"), None)
    source = _nan_safe(row.get("source"), None)
    program_ids = _nan_safe(row.get("program_ids"), [])
    net_flow = _nan_safe(row.get("net_flow"), {})
    token_flow_details = _nan_safe(row.get("token_flow_details"), [])
    movements_in = _nan_safe(row.get("movements_in"), [])
    movements_out = _nan_safe(row.get("movements_out"), [])
    net_flow_summary = _nan_safe(row.get("net_flow_summary"), "") or ""

    if not isinstance(program_ids, list):
        program_ids = []
    if not isinstance(net_flow, dict):
        net_flow = {}
    if not isinstance(token_flow_details, list):
        token_flow_details = []
    if not isinstance(movements_in, list):
        movements_in = []
    if not isinstance(movements_out, list):
        movements_out = []

    l1_type = _HELIUS_TYPE_MAP.get((tx_type or "").upper())
    l1_protocol = _HELIUS_SOURCE_MAP.get((source or "").upper())

    if l1_type:
        tag_type = l1_type
        if l1_protocol:
            tag_protocol, confidence = l1_protocol, 0.95
        else:
            _, l2_protocol = _layer2_lookup(program_ids)
            tag_protocol = l2_protocol or "Unknown"
            confidence = 0.80
    else:
        l2_type, l2_protocol = _layer2_lookup(program_ids)
        if l2_type:
            tag_type = l2_type
            tag_protocol = l1_protocol or l2_protocol or "Unknown"
            confidence = 0.70
        else:
            tag_type, confidence = _layer3_heuristic(
                net_flow, token_flow_details, movements_in, movements_out
            )
            tag_protocol = l1_protocol or "Unknown"

    tag_assets, tag_amount_display = _build_assets(
        tag_type, net_flow, token_flow_details, net_flow_summary
    )

    return TagResult(
        tag_type=tag_type,
        tag_protocol=tag_protocol,
        tag_assets=tag_assets,
        tag_amount_display=tag_amount_display,
        tag_usd_estimate=None,
        tag_confidence=confidence,
    )


def enrich(
    df: pd.DataFrame,
    *,
    price_provider: Callable[[str], Decimal | None] | None = None,
) -> pd.DataFrame:
    """Return df with tag columns appended. Input DataFrame is not modified."""
    tag_cols = [
        "tag_type",
        "tag_protocol",
        "tag_assets",
        "tag_amount_display",
        "tag_usd_estimate",
        "tag_confidence",
    ]
    out = df.copy()
    if df.empty:
        for c in tag_cols:
            if c not in out.columns:
                out[c] = pd.Series(dtype=object)
        return out
    results = [_tag_row(row) for row in df.to_dict(orient="records")]
    out["tag_type"] = [r.tag_type for r in results]
    out["tag_protocol"] = [r.tag_protocol for r in results]
    out["tag_assets"] = [r.tag_assets for r in results]
    out["tag_amount_display"] = [r.tag_amount_display for r in results]
    out["tag_usd_estimate"] = [r.tag_usd_estimate for r in results]
    out["tag_confidence"] = [r.tag_confidence for r in results]
    return out


__all__ = ["TagResult", "enrich"]
