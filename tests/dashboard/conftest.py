"""Shared fixtures for dashboard tests."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@pytest.fixture
def synthetic_df() -> pd.DataFrame:
    rows = []
    for i, ts, status, ttype, source, fee in [
        (0, 1735689600, "succeeded", "swap", "JUPITER", Decimal("0.00018")),
        (1, 1736294400, "failed", "transfer", "SYSTEM", Decimal("0.000005")),
        (2, 1738972800, "succeeded", "swap", "RAYDIUM", Decimal("0.00012")),
    ]:
        row = {col: None for col in DATAFRAME_COLUMNS}
        row["signature"] = f"sig-{i}"
        row["slot"] = 1000 + i
        row["timestamp_unix"] = ts
        row["timestamp"] = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        row["transaction_type"] = ttype
        row["source"] = source
        row["description"] = f"Test transaction {i}"
        row["fee_lamports"] = int(fee * Decimal("1e9"))
        row["fee_sol"] = fee
        row["fee_paid_by_wallet"] = True
        row["fee_payer"] = WALLET
        row["status"] = status
        row["native_in_sol"] = Decimal("0") if i != 0 else Decimal("1")
        row["native_out_sol"] = Decimal("0.5") if i == 0 else Decimal("0")
        row["native_net_sol"] = (
            Decimal("0.5") if i == 0 else (Decimal("-0.000005") if i == 1 else Decimal("0"))
        )
        if i == 0:
            row["net_flow"] = {"SOL": Decimal("0.5"), USDC_MINT: Decimal("100")}
        elif i == 2:
            row["net_flow"] = {USDC_MINT: Decimal("-50")}
        else:
            row["net_flow"] = {"SOL": Decimal("-0.000005")}
        row["token_flow_details"] = []
        row["token_in_summary"] = "" if i == 1 else "100 USDC"
        row["token_out_summary"] = "" if i != 2 else "50 USDC"
        row["token_net_summary"] = ""
        row["net_flow_summary"] = "" if i == 1 else "0.5 SOL, 100 USDC (in)"
        row["movements_in"] = []
        row["movements_out"] = []
        row["raw_native_transfers"] = []
        row["raw_token_transfers"] = []
        row["transaction_error"] = None if status == "succeeded" else {"InstructionError": [0]}
        rows.append(row)
    df = pd.DataFrame(rows, columns=DATAFRAME_COLUMNS)
    return df


@pytest.fixture
def wallet_address() -> str:
    return WALLET
