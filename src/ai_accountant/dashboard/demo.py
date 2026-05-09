"""Synthetic dashboard data for local verification."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pandas as pd

from ..dataframe import DATAFRAME_COLUMNS

DEMO_WALLET_ADDRESS = "11111111111111111111111111111111"
DEMO_DATASET_LABEL = "Synthetic demo data"

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BONK_MINT = "DezXAZ8z7PnrnRJjz3B4xG9k5hYxjWzQm4xw3W5wW9"
NFT_MINT = "9mQe8kYq1xDemoNFT11111111111111111111111"


def build_demo_dataframe() -> pd.DataFrame:
    """Return a realistic synthetic wallet history for dashboard smoke testing."""
    rows = [
        _row(
            signature="2" * 88,
            when=datetime(2025, 1, 5, 10, 15, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="UNKNOWN",
            description="Initial deposit from an unlabeled external wallet.",
            fee_sol="0.000005",
            native_in_sol="2.75",
            native_out_sol="0",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="Unknown",
            tag_assets="SOL",
            tag_amount_display="2.75 SOL",
            tag_confidence=0.78,
        ),
        _row(
            signature="3" * 88,
            when=datetime(2025, 1, 12, 14, 30, tzinfo=timezone.utc),
            transaction_type="SWAP",
            source="JUPITER",
            description="Swapped SOL into USDC through Jupiter.",
            fee_sol="0.00018",
            native_in_sol="0",
            native_out_sol="1.25",
            status="succeeded",
            token_flows=[_token_flow(USDC_MINT, "USDC", token_in="245.10")],
            tag_type="Swap",
            tag_protocol="Jupiter",
            tag_assets="SOL, USDC",
            tag_amount_display="1.25 SOL to 245.10 USDC",
            tag_confidence=0.96,
        ),
        _row(
            signature="4" * 88,
            when=datetime(2025, 2, 3, 9, 5, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="SYSTEM",
            description="Sent SOL to a known exchange deposit wallet.",
            fee_sol="0.000005",
            native_in_sol="0",
            native_out_sol="0.42",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="System Program",
            tag_assets="SOL",
            tag_amount_display="0.42 SOL",
            tag_confidence=0.91,
        ),
        _row(
            signature="5" * 88,
            when=datetime(2025, 2, 20, 18, 45, tzinfo=timezone.utc),
            transaction_type="AIRDROP",
            source="UNKNOWN",
            description="Received BONK from an airdrop campaign.",
            fee_sol="0",
            native_in_sol="0",
            native_out_sol="0",
            status="succeeded",
            token_flows=[_token_flow(BONK_MINT, "BONK", token_in="120000")],
            tag_type="Airdrop",
            tag_protocol="Unknown",
            tag_assets="BONK",
            tag_amount_display="120000 BONK",
            tag_confidence=0.72,
        ),
        _row(
            signature="6" * 88,
            when=datetime(2025, 3, 2, 16, 10, tzinfo=timezone.utc),
            transaction_type="NFT_SALE",
            source="MAGIC_EDEN",
            description="Sold a demo NFT on Magic Eden and received SOL.",
            fee_sol="0.00021",
            native_in_sol="3.2",
            native_out_sol="0",
            status="succeeded",
            token_flows=[_token_flow(NFT_MINT, "NFT", token_out="1")],
            tag_type="NFT Buy/Sell",
            tag_protocol="Magic Eden",
            tag_assets="Demo NFT",
            tag_amount_display="Demo NFT for 3.2 SOL",
            tag_confidence=0.88,
        ),
        _row(
            signature="7" * 88,
            when=datetime(2025, 3, 17, 11, 25, tzinfo=timezone.utc),
            transaction_type="STAKE",
            source="STAKE_PROGRAM",
            description="Delegated SOL to a validator.",
            fee_sol="0.000005",
            native_in_sol="0",
            native_out_sol="5.0",
            status="succeeded",
            tag_type="Stake/Unstake",
            tag_protocol="Solana Stake Program",
            tag_assets="SOL",
            tag_amount_display="5 SOL",
            tag_confidence=0.86,
        ),
        _row(
            signature="8" * 88,
            when=datetime(2025, 4, 5, 12, 40, tzinfo=timezone.utc),
            transaction_type="UNSTAKE",
            source="STAKE_PROGRAM",
            description="Withdrew SOL from staking; principal versus reward is unknown.",
            fee_sol="0.000005",
            native_in_sol="5.4",
            native_out_sol="0",
            status="succeeded",
            tag_type="Stake/Unstake",
            tag_protocol="Solana Stake Program",
            tag_assets="SOL",
            tag_amount_display="5.4 SOL",
            tag_confidence=0.83,
        ),
        _row(
            signature="9" * 88,
            when=datetime(2025, 4, 22, 20, 15, tzinfo=timezone.utc),
            transaction_type="LP",
            source="RAYDIUM",
            description="Added liquidity to a SOL/USDC pool.",
            fee_sol="0.00024",
            native_in_sol="0",
            native_out_sol="0.8",
            status="succeeded",
            token_flows=[_token_flow(USDC_MINT, "USDC", token_out="150")],
            tag_type="LP Deposit/Withdraw",
            tag_protocol="Raydium",
            tag_assets="SOL, USDC",
            tag_amount_display="0.8 SOL and 150 USDC",
            tag_confidence=0.89,
        ),
        _row(
            signature="A" * 88,
            when=datetime(2025, 5, 7, 8, 50, tzinfo=timezone.utc),
            transaction_type="PERP",
            source="DRIFT",
            description="Closed a profitable perpetual futures position.",
            fee_sol="0.00031",
            native_in_sol="0.33",
            native_out_sol="0",
            status="succeeded",
            tag_type="Perpetual Trade",
            tag_protocol="Drift",
            tag_assets="SOL-PERP",
            tag_amount_display="0.33 SOL PnL",
            tag_confidence=0.81,
        ),
        _row(
            signature="B" * 88,
            when=datetime(2025, 6, 1, 19, 0, tzinfo=timezone.utc),
            transaction_type="UNKNOWN",
            source="UNKNOWN",
            description="Unknown program interaction with no parsed wallet movement.",
            fee_sol="0.000013",
            native_in_sol="0",
            native_out_sol="0",
            status="succeeded",
            tag_type="Unknown",
            tag_protocol="Unknown",
            tag_assets="",
            tag_amount_display="",
            tag_confidence=0.31,
            program_ids=["Unknown1111111111111111111111111111111111"],
            net_flow_summary="No net movement",
        ),
        _row(
            signature="C" * 88,
            when=datetime(2025, 6, 14, 7, 35, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="SYSTEM",
            description="Failed transfer attempt; only the network fee was paid.",
            fee_sol="0.000005",
            native_in_sol="0",
            native_out_sol="0.000005",
            status="failed",
            tag_type="Transfer",
            tag_protocol="System Program",
            tag_assets="SOL",
            tag_amount_display="0.000005 SOL fee",
            tag_confidence=0.76,
            transaction_error={"InstructionError": [0, "InsufficientFunds"]},
        ),
        _row(
            signature="D" * 88,
            when=datetime(2025, 7, 9, 13, 20, tzinfo=timezone.utc),
            transaction_type="BRIDGE",
            source="WORMHOLE",
            description="Bridged SOL out to another chain.",
            fee_sol="0.00017",
            native_in_sol="0",
            native_out_sol="0.75",
            status="succeeded",
            tag_type="Bridge",
            tag_protocol="Wormhole",
            tag_assets="SOL",
            tag_amount_display="0.75 SOL",
            tag_confidence=0.84,
        ),
        _row(
            signature="E" * 88,
            when=datetime(2025, 8, 1, 17, 55, tzinfo=timezone.utc),
            transaction_type="TOKEN_TRANSFER",
            source="COINBASE",
            description="Received USDC from an exchange account.",
            fee_sol="0",
            native_in_sol="0",
            native_out_sol="0",
            status="succeeded",
            token_flows=[_token_flow(USDC_MINT, "USDC", token_in="50")],
            tag_type="Transfer",
            tag_protocol="Token Program",
            tag_assets="USDC",
            tag_amount_display="50 USDC",
            tag_confidence=0.93,
        ),
    ]
    return pd.DataFrame(rows, columns=DATAFRAME_COLUMNS)


def build_demo_meta(df: pd.DataFrame | None = None, *, fetched_at: datetime | None = None) -> dict[str, Any]:
    """Return cache metadata for the synthetic demo wallet."""
    frame = df if df is not None else build_demo_dataframe()
    dates = sorted(str(ts)[:10] for ts in frame["timestamp"] if ts)
    fetched = fetched_at or datetime.now(timezone.utc)
    return {
        "address": DEMO_WALLET_ADDRESS,
        "fetched_at": fetched.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "row_count": int(len(frame)),
        "earliest_tx": dates[0] if dates else "",
        "latest_tx": dates[-1] if dates else "",
        "pages_fetched": 1,
        "max_pages_at_fetch": 1,
        "dataset_label": DEMO_DATASET_LABEL,
    }


def build_demo_cache_payload() -> tuple[str, pd.DataFrame, dict[str, Any]]:
    """Return address, DataFrame and metadata ready for cache.write()."""
    df = build_demo_dataframe()
    return DEMO_WALLET_ADDRESS, df, build_demo_meta(df)


def _row(
    *,
    signature: str,
    when: datetime,
    transaction_type: str,
    source: str,
    description: str,
    fee_sol: str,
    native_in_sol: str,
    native_out_sol: str,
    status: str,
    tag_type: str,
    tag_protocol: str,
    tag_assets: str,
    tag_amount_display: str,
    tag_confidence: float,
    token_flows: list[dict[str, Any]] | None = None,
    transaction_error: dict[str, Any] | None = None,
    program_ids: list[str] | None = None,
    net_flow_summary: str | None = None,
) -> dict[str, Any]:
    native_in = Decimal(native_in_sol)
    native_out = Decimal(native_out_sol)
    native_net = native_in - native_out
    flows = token_flows or []
    net_flow: dict[str, Decimal] = {}
    if native_net:
        net_flow["SOL"] = native_net
    for flow in flows:
        mint = str(flow["mint"])
        net_flow[mint] = Decimal(str(flow["net"]))

    row = {col: None for col in DATAFRAME_COLUMNS}
    row.update(
        {
            "signature": signature,
            "slot": int(when.timestamp()) // 2,
            "timestamp_unix": int(when.timestamp()),
            "timestamp": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "transaction_type": transaction_type,
            "description": description,
            "source": source,
            "fee_lamports": int(Decimal(fee_sol) * Decimal("1000000000")),
            "fee_sol": Decimal(fee_sol),
            "fee_paid_by_wallet": Decimal(fee_sol) > Decimal("0"),
            "fee_payer": DEMO_WALLET_ADDRESS,
            "status": status,
            "native_in_sol": native_in,
            "native_out_sol": native_out,
            "native_transfer_net_sol": native_net,
            "native_net_sol": native_net,
            "token_in_summary": _token_summary(flows, direction="in"),
            "token_out_summary": _token_summary(flows, direction="out"),
            "token_net_summary": _token_net_summary(flows),
            "net_flow_summary": net_flow_summary or _net_flow_summary(native_net, flows),
            "net_flow": net_flow,
            "token_flow_details": flows,
            "movements_in": [],
            "movements_out": [],
            "raw_native_transfers": [],
            "raw_token_transfers": [],
            "transaction_error": transaction_error,
            "program_ids": program_ids or [],
            "tag_type": tag_type,
            "tag_protocol": tag_protocol,
            "tag_assets": tag_assets,
            "tag_amount_display": tag_amount_display,
            "tag_usd_estimate": None,
            "tag_confidence": tag_confidence,
        }
    )
    return row


def _token_flow(
    mint: str,
    symbol: str,
    *,
    token_in: str = "0",
    token_out: str = "0",
) -> dict[str, Any]:
    incoming = Decimal(token_in)
    outgoing = Decimal(token_out)
    return {
        "mint": mint,
        "symbol": symbol,
        "in": incoming,
        "out": outgoing,
        "net": incoming - outgoing,
    }


def _token_summary(flows: list[dict[str, Any]], *, direction: str) -> str:
    key = "in" if direction == "in" else "out"
    parts = [
        f"{_fmt(flow[key])} {flow['symbol']}"
        for flow in flows
        if Decimal(str(flow.get(key) or "0")) > 0
    ]
    return ", ".join(parts)


def _token_net_summary(flows: list[dict[str, Any]]) -> str:
    parts = []
    for flow in flows:
        net = Decimal(str(flow.get("net") or "0"))
        if net:
            parts.append(f"{_fmt(net, signed=True)} {flow['symbol']}")
    return ", ".join(parts)


def _net_flow_summary(native_net: Decimal, flows: list[dict[str, Any]]) -> str:
    parts = []
    if native_net:
        parts.append(f"{_fmt(native_net, signed=True)} SOL")
    token_summary = _token_net_summary(flows)
    if token_summary:
        parts.append(token_summary)
    return ", ".join(parts) if parts else "No net movement"


def _fmt(value: Decimal, *, signed: bool = False) -> str:
    rendered = format(value.normalize(), "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if signed and value > 0:
        return f"+{rendered}"
    return rendered


__all__ = [
    "DEMO_DATASET_LABEL",
    "DEMO_WALLET_ADDRESS",
    "build_demo_cache_payload",
    "build_demo_dataframe",
    "build_demo_meta",
]
