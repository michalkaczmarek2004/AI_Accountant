"""Synthetic dashboard data for local verification."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pandas as pd

from ..dataframe import DATAFRAME_COLUMNS

DEMO_WALLET_ADDRESS = "11111111111111111111111111111111"
DEMO_SECOND_WALLET_ADDRESS = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
DEMO_DATASET_LABEL = "Synthetic demo data"

TEST_WALLET_ADDRESS = "5PjDJaGfSPJj4tFzMRCiuuAasKg5n8dJKXKenhuwZexx"
TEST_SECOND_WALLET_ADDRESS = "5TeWSsjg2gbxCyWVniXeCmwM7UtHTCK7svzJr5xYJzHf"
TEST_DATASET_LABEL = "Demo dataset: 2025 US taxpayer story"
TEST_SIGNATURES = {
    "exchange_sol": "G" * 88,
    "samo_large": "H" * 88,
    "samo_small": "J" * 88,
    "usdc_sale": "K" * 88,
    "airdrop": "M" * 88,
    "staking_deposit": "N" * 88,
    "self_transfer": "P" * 88,
    "confirmation_transfer": "Q" * 88,
    "staking_reward": "R" * 88,
    "nft_mint": "S" * 88,
    "nft_sale": "T" * 88,
    "bridge_wsol": "U" * 88,
    "lp_deposit": "V" * 88,
    "stablecoin_swap": "W" * 88,
    "failed_fee": "X" * 88,
    "missing_price": "Y" * 88,
    "missing_basis": "Z" * 88,
    "duplicate_candidate": "a" * 88,
    "bonk_long_sale": "b" * 88,
}

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY4hHUaHtdQJdN"
BONK_MINT = "DezXAZ8z7PnrnRJjz3B4xG9k5hYxjWzQm4xw3W5wW9"
SAMO_MINT = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgyd"
JUP_MINT = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
WSOL_MINT = "So11111111111111111111111111111111111111112"
NFT_MINT = "9mQe8kYq1xDemoNFT11111111111111111111111"


def build_demo_dataframe() -> pd.DataFrame:
    """Return a realistic synthetic wallet history for dashboard smoke testing."""
    rows = [
        _row(
            signature="2" * 88,
            when=datetime(2025, 1, 5, 10, 15, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="COINBASE",
            description="Received SOL from a Coinbase exchange account.",
            fee_sol="0.000005",
            native_in_sol="2.75",
            native_out_sol="0",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="Exchange",
            tag_assets="SOL",
            tag_amount_display="2.75 SOL",
            tag_confidence=0.94,
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
            description="Sent SOL to Ledger, another wallet owned by the taxpayer.",
            fee_sol="0.000005",
            native_in_sol="0",
            native_out_sol="0.42",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="System Program",
            tag_assets="SOL",
            tag_amount_display="0.42 SOL",
            tag_confidence=0.91,
            counterparty=DEMO_SECOND_WALLET_ADDRESS,
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
            description="Staking deposit; likely non-taxable if no receipt token was received.",
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
            signature="C" * 88,
            when=datetime(2025, 6, 14, 7, 35, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="SYSTEM",
            description="Failed transfer attempt; only the network fee was paid.",
            fee_sol="0.000005",
            native_in_sol="0",
            native_out_sol="0",
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
            transaction_type="TRANSFER",
            source="UNKNOWN",
            description="Sent SOL to an unlabeled address. Client needs to identify the destination.",
            fee_sol="0.000005",
            native_in_sol="0",
            native_out_sol="0.31",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="Unknown",
            tag_assets="SOL",
            tag_amount_display="0.31 SOL",
            tag_confidence=0.62,
        ),
        _row(
            signature="E" * 88,
            when=datetime(2025, 12, 3, 9, 40, tzinfo=timezone.utc),
            transaction_type="SWAP",
            source="JUPITER",
            description="Demo tax-loss harvesting candidate: swapped SOL into SAMO before a year-end drawdown.",
            fee_sol="0.00019",
            native_in_sol="0",
            native_out_sol="6.4",
            status="succeeded",
            token_flows=[_token_flow(SAMO_MINT, "SAMO", token_in="140000")],
            tag_type="Swap",
            tag_protocol="Jupiter",
            tag_assets="SOL, SAMO",
            tag_amount_display="6.4 SOL to 140000 SAMO",
            tag_confidence=0.93,
        ),
    ]
    return pd.DataFrame(rows, columns=DATAFRAME_COLUMNS)


def build_demo_secondary_dataframe() -> pd.DataFrame:
    """Return a second wallet history that pairs with the primary demo wallet."""
    rows = [
        _row(
            signature="4" * 88,
            when=datetime(2025, 2, 3, 9, 6, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="SYSTEM",
            description="Received SOL from Phantom main, another wallet owned by the taxpayer.",
            fee_sol="0.000005",
            native_in_sol="0.42",
            native_out_sol="0",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="System Program",
            tag_assets="SOL",
            tag_amount_display="0.42 SOL",
            tag_confidence=0.91,
            wallet_address=DEMO_SECOND_WALLET_ADDRESS,
            fee_paid_by_wallet=False,
            fee_payer=DEMO_WALLET_ADDRESS,
            counterparty=DEMO_WALLET_ADDRESS,
        ),
        _row(
            signature="F" * 88,
            when=datetime(2025, 3, 14, 12, 0, tzinfo=timezone.utc),
            transaction_type="TOKEN_TRANSFER",
            source="UNKNOWN",
            description="Received USDC from an unlabeled source.",
            fee_sol="0",
            native_in_sol="0",
            native_out_sol="0",
            status="succeeded",
            token_flows=[_token_flow(USDC_MINT, "USDC", token_in="25")],
            tag_type="Transfer",
            tag_protocol="Token Program",
            tag_assets="USDC",
            tag_amount_display="25 USDC",
            tag_confidence=0.84,
            wallet_address=DEMO_SECOND_WALLET_ADDRESS,
        ),
    ]
    return pd.DataFrame(rows, columns=DATAFRAME_COLUMNS)


def build_test_dataframe() -> pd.DataFrame:
    """Return the presentation-ready US demo wallet history."""
    rows = [
        _row(
            signature=TEST_SIGNATURES["exchange_sol"],
            when=datetime(2025, 1, 7, 15, 0, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="COINBASE",
            description="Bought SOL on Coinbase and moved it to the US demo wallet.",
            fee_sol="0",
            native_in_sol="220",
            native_out_sol="0",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="Exchange",
            tag_assets="SOL",
            tag_amount_display="220 SOL",
            tag_confidence=0.98,
            tag_usd_estimate="44000",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["bonk_long_sale"],
            when=datetime(2025, 1, 15, 10, 25, tzinfo=timezone.utc),
            transaction_type="SWAP",
            source="JUPITER",
            description="Sold a long-term BONK lot into USDC; demonstrates long-term capital gain treatment.",
            fee_sol="0.00008",
            native_in_sol="0",
            native_out_sol="0",
            status="succeeded",
            token_flows=[
                _token_flow(BONK_MINT, "BONK", token_out="1000000"),
                _token_flow(USDC_MINT, "USDC", token_in="500"),
            ],
            tag_type="Swap",
            tag_protocol="Jupiter",
            tag_assets="BONK, USDC",
            tag_amount_display="1000000 BONK to 500 USDC",
            tag_confidence=0.94,
            tag_usd_estimate="500",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["samo_large"],
            when=datetime(2025, 1, 20, 17, 15, tzinfo=timezone.utc),
            transaction_type="SWAP",
            source="JUPITER",
            description="Swapped SOL into SAMO; this lot creates the main US loss-harvesting opportunity.",
            fee_sol="0.0002",
            native_in_sol="0",
            native_out_sol="95",
            status="succeeded",
            token_flows=[_token_flow(SAMO_MINT, "SAMO", token_in="2100000")],
            tag_type="Swap",
            tag_protocol="Jupiter",
            tag_assets="SOL, SAMO",
            tag_amount_display="95 SOL to 2100000 SAMO",
            tag_confidence=0.97,
            tag_usd_estimate="19000",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["samo_small"],
            when=datetime(2025, 2, 11, 11, 45, tzinfo=timezone.utc),
            transaction_type="SWAP",
            source="JUPITER",
            description="Second SAMO acquisition lot for the tax optimization demo.",
            fee_sol="0.0002",
            native_in_sol="0",
            native_out_sol="42",
            status="succeeded",
            token_flows=[_token_flow(SAMO_MINT, "SAMO", token_in="900000")],
            tag_type="Swap",
            tag_protocol="Jupiter",
            tag_assets="SOL, SAMO",
            tag_amount_display="42 SOL to 900000 SAMO",
            tag_confidence=0.96,
            tag_usd_estimate="8400",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["usdc_sale"],
            when=datetime(2025, 3, 3, 14, 20, tzinfo=timezone.utc),
            transaction_type="SWAP",
            source="JUPITER",
            description="Sold SOL into USDC; this creates the taxable gain used in the US estimate.",
            fee_sol="0.00018",
            native_in_sol="0",
            native_out_sol="30",
            status="succeeded",
            token_flows=[_token_flow(USDC_MINT, "USDC", token_in="30000")],
            tag_type="Swap",
            tag_protocol="Jupiter",
            tag_assets="SOL, USDC",
            tag_amount_display="30 SOL to 30000 USDC",
            tag_confidence=0.95,
            tag_usd_estimate="30000",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["airdrop"],
            when=datetime(2025, 4, 14, 9, 30, tzinfo=timezone.utc),
            transaction_type="AIRDROP",
            source="PYTH",
            description="Received a small token reward with USD FMV already documented.",
            fee_sol="0",
            native_in_sol="0",
            native_out_sol="0",
            status="succeeded",
            token_flows=[_token_flow(BONK_MINT, "BONK", token_in="1000000")],
            tag_type="Airdrop",
            tag_protocol="Rewards",
            tag_assets="BONK",
            tag_amount_display="1000000 BONK",
            tag_confidence=0.9,
            tag_usd_estimate="1200",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["staking_deposit"],
            when=datetime(2025, 5, 8, 8, 10, tzinfo=timezone.utc),
            transaction_type="STAKE",
            source="STAKE_PROGRAM",
            description="Staked SOL; pre-reviewed as a non-taxable staking deposit for the demo.",
            fee_sol="0.000005",
            native_in_sol="0",
            native_out_sol="20",
            status="succeeded",
            tag_type="Stake/Unstake",
            tag_protocol="Solana Stake Program",
            tag_assets="SOL",
            tag_amount_display="20 SOL",
            tag_confidence=0.92,
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["staking_reward"],
            when=datetime(2025, 5, 22, 12, 15, tzinfo=timezone.utc),
            transaction_type="STAKE_REWARD",
            source="STAKE_PROGRAM",
            description="Solana staking reward with USD FMV documented for ordinary income review.",
            fee_sol="0",
            native_in_sol="0.6",
            native_out_sol="0",
            status="succeeded",
            tag_type="Staking Reward",
            tag_protocol="Solana Stake Program",
            tag_assets="SOL",
            tag_amount_display="0.6 SOL reward",
            tag_confidence=0.91,
            tag_usd_estimate="120",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["nft_mint"],
            when=datetime(2025, 5, 28, 18, 40, tzinfo=timezone.utc),
            transaction_type="NFT_MINT",
            source="MAGIC_EDEN",
            description="Minted a Solana NFT; basis includes mint price and network fees.",
            fee_sol="0.00021",
            native_in_sol="0",
            native_out_sol="2",
            status="succeeded",
            token_flows=[_token_flow(NFT_MINT, "NFT", token_in="1")],
            tag_type="NFT Buy/Sell",
            tag_protocol="Magic Eden",
            tag_assets="Demo NFT",
            tag_amount_display="2 SOL NFT mint",
            tag_confidence=0.88,
            tag_usd_estimate="400",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["nft_sale"],
            when=datetime(2025, 6, 4, 16, 20, tzinfo=timezone.utc),
            transaction_type="NFT_SALE",
            source="MAGIC_EDEN",
            description="Sold the demo NFT on Magic Eden; prepared for capital gain review.",
            fee_sol="0.00024",
            native_in_sol="4",
            native_out_sol="0",
            status="succeeded",
            token_flows=[_token_flow(NFT_MINT, "NFT", token_out="1")],
            tag_type="NFT Buy/Sell",
            tag_protocol="Magic Eden",
            tag_assets="Demo NFT",
            tag_amount_display="Demo NFT for 4 SOL",
            tag_confidence=0.87,
            tag_usd_estimate="800",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["self_transfer"],
            when=datetime(2025, 6, 10, 10, 0, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="SYSTEM",
            description="Moved SOL to the secondary wallet owned by the same taxpayer.",
            fee_sol="0.000005",
            native_in_sol="0",
            native_out_sol="25",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="System Program",
            tag_assets="SOL",
            tag_amount_display="25 SOL",
            tag_confidence=0.96,
            wallet_address=TEST_WALLET_ADDRESS,
            counterparty=TEST_SECOND_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["bridge_wsol"],
            when=datetime(2025, 8, 6, 13, 45, tzinfo=timezone.utc),
            transaction_type="WRAP_SOL",
            source="WORMHOLE",
            description="Wrapped SOL to wSOL for a bridge/workflow; marked for non-disposal review.",
            fee_sol="0.00011",
            native_in_sol="0",
            native_out_sol="3",
            status="succeeded",
            token_flows=[_token_flow(WSOL_MINT, "wSOL", token_in="3")],
            tag_type="Wrapped Token",
            tag_protocol="Solana Token Program",
            tag_assets="SOL, wSOL",
            tag_amount_display="3 SOL to 3 wSOL",
            tag_confidence=0.86,
            tag_usd_estimate="600",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["lp_deposit"],
            when=datetime(2025, 9, 5, 9, 10, tzinfo=timezone.utc),
            transaction_type="LP_DEPOSIT",
            source="ORCA",
            description="Deposited SOL and USDC into an Orca liquidity pool; CPA review required.",
            fee_sol="0.00016",
            native_in_sol="0",
            native_out_sol="5",
            status="succeeded",
            token_flows=[
                _token_flow(USDC_MINT, "USDC", token_out="1000"),
                _token_flow(JUP_MINT, "LP", token_in="25"),
            ],
            tag_type="LP Deposit/Withdraw",
            tag_protocol="Orca",
            tag_assets="SOL, USDC, LP",
            tag_amount_display="5 SOL + 1000 USDC to LP",
            tag_confidence=0.78,
            tag_usd_estimate="2000",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["confirmation_transfer"],
            when=datetime(2025, 9, 18, 19, 5, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="UNKNOWN",
            description="Incoming transfer that the client confirms as their own wallet during the demo.",
            fee_sol="0",
            native_in_sol="14",
            native_out_sol="0",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="Unknown",
            tag_assets="SOL",
            tag_amount_display="14 SOL",
            tag_confidence=0.7,
            tag_usd_estimate="2800",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["stablecoin_swap"],
            when=datetime(2025, 10, 11, 15, 30, tzinfo=timezone.utc),
            transaction_type="SWAP",
            source="JUPITER",
            description="Stablecoin swap USDC to USDT; low/no gain but still reviewed as an exchange.",
            fee_sol="0.00009",
            native_in_sol="0",
            native_out_sol="0",
            status="succeeded",
            token_flows=[
                _token_flow(USDC_MINT, "USDC", token_out="5000"),
                _token_flow(USDT_MINT, "USDT", token_in="4998.5"),
            ],
            tag_type="Swap",
            tag_protocol="Jupiter",
            tag_assets="USDC, USDT",
            tag_amount_display="5000 USDC to 4998.5 USDT",
            tag_confidence=0.93,
            tag_usd_estimate="4998.5",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["failed_fee"],
            when=datetime(2025, 11, 3, 22, 5, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="SYSTEM",
            description="Failed transaction; only the network fee was paid.",
            fee_sol="0.000005",
            native_in_sol="0",
            native_out_sol="0",
            status="failed",
            tag_type="Transfer",
            tag_protocol="System Program",
            tag_assets="SOL",
            tag_amount_display="0.000005 SOL fee",
            tag_confidence=0.8,
            transaction_error={"InstructionError": [0, "InsufficientFunds"]},
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["missing_price"],
            when=datetime(2025, 11, 17, 7, 50, tzinfo=timezone.utc),
            transaction_type="AIRDROP",
            source="UNKNOWN",
            description="Airdrop with missing historical price; should block final ordinary income amount.",
            fee_sol="0",
            native_in_sol="0",
            native_out_sol="0",
            status="succeeded",
            token_flows=[_token_flow(JUP_MINT, "JUP", token_in="250")],
            tag_type="Airdrop",
            tag_protocol="Unknown",
            tag_assets="JUP",
            tag_amount_display="250 JUP",
            tag_confidence=0.68,
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["missing_basis"],
            when=datetime(2025, 12, 6, 11, 35, tzinfo=timezone.utc),
            transaction_type="SWAP",
            source="JUPITER",
            description="Sold externally acquired JUP without acquisition history; missing cost basis review.",
            fee_sol="0.00012",
            native_in_sol="0",
            native_out_sol="0",
            status="succeeded",
            token_flows=[
                _token_flow(JUP_MINT, "JUP", token_out="400"),
                _token_flow(USDC_MINT, "USDC", token_in="1600"),
            ],
            tag_type="Swap",
            tag_protocol="Jupiter",
            tag_assets="JUP, USDC",
            tag_amount_display="400 JUP to 1600 USDC",
            tag_confidence=0.79,
            tag_usd_estimate="1600",
            wallet_address=TEST_WALLET_ADDRESS,
        ),
        _row(
            signature=TEST_SIGNATURES["duplicate_candidate"],
            when=datetime(2025, 12, 8, 8, 0, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="COINBASE",
            description="Imported Coinbase-style funding record that matches the January transfer support package.",
            fee_sol="0",
            native_in_sol="0",
            native_out_sol="0",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="Exchange import",
            tag_assets="SOL",
            tag_amount_display="Duplicate 1099-style import support row",
            tag_confidence=0.74,
            wallet_address=TEST_WALLET_ADDRESS,
        ),
    ]
    return pd.DataFrame(rows, columns=DATAFRAME_COLUMNS)


def build_test_secondary_dataframe() -> pd.DataFrame:
    """Return the secondary owned wallet for the US test demo."""
    rows = [
        _row(
            signature=TEST_SIGNATURES["self_transfer"],
            when=datetime(2025, 6, 10, 10, 1, tzinfo=timezone.utc),
            transaction_type="TRANSFER",
            source="SYSTEM",
            description="Received SOL from the primary demo wallet owned by the same taxpayer.",
            fee_sol="0.000005",
            native_in_sol="25",
            native_out_sol="0",
            status="succeeded",
            tag_type="Transfer",
            tag_protocol="System Program",
            tag_assets="SOL",
            tag_amount_display="25 SOL",
            tag_confidence=0.96,
            wallet_address=TEST_SECOND_WALLET_ADDRESS,
            fee_paid_by_wallet=False,
            fee_payer=TEST_WALLET_ADDRESS,
            counterparty=TEST_WALLET_ADDRESS,
        ),
    ]
    return pd.DataFrame(rows, columns=DATAFRAME_COLUMNS)


def build_demo_meta(df: pd.DataFrame | None = None, *, fetched_at: datetime | None = None) -> dict[str, Any]:
    """Return cache metadata for the synthetic demo wallet."""
    frame = df if df is not None else build_demo_dataframe()
    return _build_meta(frame, address=DEMO_WALLET_ADDRESS, fetched_at=fetched_at)


def build_demo_secondary_meta(
    df: pd.DataFrame | None = None,
    *,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """Return cache metadata for the second synthetic wallet."""
    frame = df if df is not None else build_demo_secondary_dataframe()
    return _build_meta(frame, address=DEMO_SECOND_WALLET_ADDRESS, fetched_at=fetched_at)


def build_test_meta(df: pd.DataFrame | None = None, *, fetched_at: datetime | None = None) -> dict[str, Any]:
    """Return cache metadata for the US presentation wallet."""
    frame = df if df is not None else build_test_dataframe()
    return _build_meta(
        frame,
        address=TEST_WALLET_ADDRESS,
        fetched_at=fetched_at,
        dataset_label=TEST_DATASET_LABEL,
    )


def build_test_secondary_meta(
    df: pd.DataFrame | None = None,
    *,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """Return cache metadata for the secondary US presentation wallet."""
    frame = df if df is not None else build_test_secondary_dataframe()
    return _build_meta(
        frame,
        address=TEST_SECOND_WALLET_ADDRESS,
        fetched_at=fetched_at,
        dataset_label=TEST_DATASET_LABEL,
    )


def _build_meta(
    frame: pd.DataFrame,
    *,
    address: str,
    fetched_at: datetime | None = None,
    dataset_label: str = DEMO_DATASET_LABEL,
) -> dict[str, Any]:
    dates = sorted(str(ts)[:10] for ts in frame["timestamp"] if ts)
    fetched = fetched_at or datetime.now(timezone.utc)
    return {
        "address": address,
        "fetched_at": fetched.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "row_count": int(len(frame)),
        "earliest_tx": dates[0] if dates else "",
        "latest_tx": dates[-1] if dates else "",
        "pages_fetched": 1,
        "max_pages_at_fetch": 1,
        "dataset_label": dataset_label,
    }


def build_demo_cache_payload() -> tuple[str, pd.DataFrame, dict[str, Any]]:
    """Return address, DataFrame and metadata ready for cache.write()."""
    df = build_demo_dataframe()
    return DEMO_WALLET_ADDRESS, df, build_demo_meta(df)


def build_demo_cache_payloads() -> list[tuple[str, pd.DataFrame, dict[str, Any]]]:
    """Return both demo wallets ready for cache.write()."""
    primary = build_demo_dataframe()
    secondary = build_demo_secondary_dataframe()
    return [
        (DEMO_WALLET_ADDRESS, primary, build_demo_meta(primary)),
        (DEMO_SECOND_WALLET_ADDRESS, secondary, build_demo_secondary_meta(secondary)),
    ]


def build_test_cache_payloads() -> list[tuple[str, pd.DataFrame, dict[str, Any]]]:
    """Return both US test demo wallets ready for cache.write()."""
    primary = build_test_dataframe()
    secondary = build_test_secondary_dataframe()
    return [
        (TEST_WALLET_ADDRESS, primary, build_test_meta(primary)),
        (TEST_SECOND_WALLET_ADDRESS, secondary, build_test_secondary_meta(secondary)),
    ]


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
    tag_usd_estimate: str | None = None,
    token_flows: list[dict[str, Any]] | None = None,
    transaction_error: dict[str, Any] | None = None,
    program_ids: list[str] | None = None,
    net_flow_summary: str | None = None,
    wallet_address: str = DEMO_WALLET_ADDRESS,
    fee_paid_by_wallet: bool | None = None,
    fee_payer: str | None = None,
    counterparty: str | None = None,
) -> dict[str, Any]:
    native_in = Decimal(native_in_sol)
    native_out = Decimal(native_out_sol)
    native_net = native_in - native_out
    flows = token_flows or []
    fee = Decimal(fee_sol)
    fee_paid = fee_paid_by_wallet if fee_paid_by_wallet is not None else fee > Decimal("0")
    payer = fee_payer or (wallet_address if fee_paid else None)
    wallet_native_net = native_net - (fee if fee_paid else Decimal("0"))
    movements_in, movements_out, raw_native_transfers = _native_transfer_rows(
        wallet_address=wallet_address,
        counterparty=counterparty,
        native_in=native_in,
        native_out=native_out,
    )
    net_flow: dict[str, Decimal] = {}
    if wallet_native_net:
        net_flow["SOL"] = wallet_native_net
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
            "fee_lamports": int(fee * Decimal("1000000000")),
            "fee_sol": fee,
            "fee_paid_by_wallet": fee_paid,
            "fee_payer": payer,
            "status": status,
            "native_in_sol": native_in,
            "native_out_sol": native_out,
            "native_transfer_net_sol": native_net,
            "native_net_sol": wallet_native_net,
            "token_in_summary": _token_summary(flows, direction="in"),
            "token_out_summary": _token_summary(flows, direction="out"),
            "token_net_summary": _token_net_summary(flows),
            "net_flow_summary": net_flow_summary or _net_flow_summary(wallet_native_net, flows),
            "net_flow": net_flow,
            "token_flow_details": flows,
            "movements_in": movements_in,
            "movements_out": movements_out,
            "raw_native_transfers": raw_native_transfers,
            "raw_token_transfers": [],
            "transaction_error": transaction_error,
            "program_ids": program_ids or [],
            "tag_type": tag_type,
            "tag_protocol": tag_protocol,
            "tag_assets": tag_assets,
            "tag_amount_display": tag_amount_display,
            "tag_usd_estimate": Decimal(tag_usd_estimate) if tag_usd_estimate is not None else None,
            "tag_confidence": tag_confidence,
        }
    )
    return row


def _native_transfer_rows(
    *,
    wallet_address: str,
    counterparty: str | None,
    native_in: Decimal,
    native_out: Decimal,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not counterparty:
        return [], [], []
    movements_in: list[dict[str, Any]] = []
    movements_out: list[dict[str, Any]] = []
    raw_native_transfers: list[dict[str, Any]] = []
    if native_in > 0:
        movements_in.append(
            {
                "asset_type": "native",
                "symbol": "SOL",
                "mint": None,
                "amount": native_in,
                "amount_lamports": int(native_in * Decimal("1000000000")),
                "from_user_account": counterparty,
                "to_user_account": wallet_address,
                "direction": "in",
                "counterparty": counterparty,
            }
        )
        raw_native_transfers.append(
            {
                "fromUserAccount": counterparty,
                "toUserAccount": wallet_address,
                "amount": int(native_in * Decimal("1000000000")),
            }
        )
    if native_out > 0:
        movements_out.append(
            {
                "asset_type": "native",
                "symbol": "SOL",
                "mint": None,
                "amount": native_out,
                "amount_lamports": int(native_out * Decimal("1000000000")),
                "from_user_account": wallet_address,
                "to_user_account": counterparty,
                "direction": "out",
                "counterparty": counterparty,
            }
        )
        raw_native_transfers.append(
            {
                "fromUserAccount": wallet_address,
                "toUserAccount": counterparty,
                "amount": int(native_out * Decimal("1000000000")),
            }
        )
    return movements_in, movements_out, raw_native_transfers


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
    "DEMO_SECOND_WALLET_ADDRESS",
    "DEMO_WALLET_ADDRESS",
    "TEST_DATASET_LABEL",
    "TEST_SECOND_WALLET_ADDRESS",
    "TEST_SIGNATURES",
    "TEST_WALLET_ADDRESS",
    "build_demo_cache_payload",
    "build_demo_cache_payloads",
    "build_demo_dataframe",
    "build_demo_meta",
    "build_demo_secondary_dataframe",
    "build_demo_secondary_meta",
    "build_test_cache_payloads",
    "build_test_dataframe",
    "build_test_meta",
    "build_test_secondary_dataframe",
    "build_test_secondary_meta",
]
