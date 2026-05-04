"""DataFrame schema and conversion helpers for ai_accountant."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from .parser import TransactionParser


DATAFRAME_COLUMNS: list[str] = [
    "signature",
    "slot",
    "timestamp_unix",
    "timestamp",
    "transaction_type",
    "description",
    "source",
    "fee_lamports",
    "fee_sol",
    "fee_paid_by_wallet",
    "fee_payer",
    "status",
    "native_in_sol",
    "native_out_sol",
    "native_transfer_net_sol",
    "native_net_sol",
    "token_in_summary",
    "token_out_summary",
    "token_net_summary",
    "net_flow_summary",
    "net_flow",
    "token_flow_details",
    "movements_in",
    "movements_out",
    "raw_native_transfers",
    "raw_token_transfers",
    "transaction_error",
]


def to_dataframe(
    parser: "TransactionParser",
    transactions: Iterable[Mapping[str, Any]],
) -> pd.DataFrame:
    """Parse `transactions` with `parser` and return a DataFrame with the canonical schema."""
    rows = parser.parse_many(transactions)
    if not rows:
        return pd.DataFrame(columns=DATAFRAME_COLUMNS)
    return pd.DataFrame(rows, columns=DATAFRAME_COLUMNS).reset_index(drop=True)
