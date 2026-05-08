from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS
from ai_accountant.dashboard.filters import FilterSpec
from ai_accountant.dashboard.views import transaction_detail, wallet_page

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _row(**overrides):
    row = {col: None for col in DATAFRAME_COLUMNS}
    row.update(
        signature="sig-x",
        slot=10,
        timestamp_unix=1735689600,
        timestamp=datetime.fromtimestamp(1735689600, timezone.utc).isoformat(),
        transaction_type="swap",
        source="JUPITER",
        description="example",
        fee_lamports=180_000,
        fee_sol=Decimal("0.00018"),
        fee_paid_by_wallet=True,
        fee_payer=WALLET,
        status="succeeded",
        native_in_sol=Decimal("1"),
        native_out_sol=Decimal("0.5"),
        native_net_sol=Decimal("0.5"),
        net_flow={"SOL": Decimal("0.5"), USDC_MINT: Decimal("100")},
        token_flow_details=[],
        token_in_summary="100 USDC",
        token_out_summary="",
        token_net_summary="",
        net_flow_summary="0.5 SOL, 100 USDC (in)",
        movements_in=[],
        movements_out=[],
        raw_native_transfers=[],
        raw_token_transfers=[],
        transaction_error=None,
    )
    row.update(overrides)
    return row


def _df(rows):
    return pd.DataFrame(rows, columns=DATAFRAME_COLUMNS)


def _meta():
    return {
        "address": WALLET,
        "fetched_at": "2026-05-08T14:33:21Z",
        "row_count": 1,
        "earliest_tx": "2025-01-01",
        "latest_tx": "2025-01-01",
        "pages_fetched": 5,
        "max_pages_at_fetch": 5,
        "schema_version": 1,
    }


class WalletPageTests(unittest.TestCase):
    def test_returns_expected_top_level_keys(self) -> None:
        ctx = wallet_page(_df([_row()]), spec=FilterSpec(), meta=_meta(), address=WALLET)
        for key in (
            "address",
            "address_short",
            "meta",
            "filter",
            "filter_active",
            "kpis",
            "asset_flow",
            "transaction_mix",
            "review_queue",
            "transactions",
            "transactions_total",
            "transactions_page",
            "transactions_pages",
            "transactions_page_size",
            "balance_chart_svg",
            "activity_chart_svg",
            "filter_options",
        ):
            self.assertIn(key, ctx, f"missing key: {key}")

    def test_kpis_match_report_module_for_same_frame(self) -> None:
        from ai_accountant.report import _wallet_metrics

        df = _df([_row(), _row(signature="sig-y", status="failed")])
        ctx = wallet_page(df, spec=FilterSpec(), meta=_meta(), address=WALLET)
        report_metrics = _wallet_metrics(df, WALLET, generated_at=datetime.now(timezone.utc))
        self.assertEqual(ctx["kpis"]["total"], report_metrics["total"])
        self.assertEqual(ctx["kpis"]["succeeded"], report_metrics["succeeded"])
        self.assertEqual(ctx["kpis"]["failed"], report_metrics["failed"])

    def test_filter_active_flag_reflects_spec(self) -> None:
        ctx = wallet_page(_df([_row()]), spec=FilterSpec(), meta=_meta(), address=WALLET)
        self.assertFalse(ctx["filter_active"])

        ctx2 = wallet_page(
            _df([_row()]),
            spec=FilterSpec(status="failed"),
            meta=_meta(),
            address=WALLET,
        )
        self.assertTrue(ctx2["filter_active"])

    def test_filter_options_extracted_from_full_frame(self) -> None:
        df = _df([_row(), _row(signature="sig-y", source="RAYDIUM", transaction_type="transfer")])
        ctx = wallet_page(df, spec=FilterSpec(), meta=_meta(), address=WALLET)
        sources = ctx["filter_options"]["sources"]
        types = ctx["filter_options"]["types"]
        self.assertIn("JUPITER", sources)
        self.assertIn("RAYDIUM", sources)
        self.assertIn("swap", types)
        self.assertIn("transfer", types)

    def test_transactions_paginated(self) -> None:
        rows = [_row(signature=f"sig-{i}") for i in range(150)]
        ctx = wallet_page(_df(rows), spec=FilterSpec(page=2), meta=_meta(), address=WALLET)
        self.assertEqual(ctx["transactions_total"], 150)
        self.assertEqual(ctx["transactions_page"], 2)
        self.assertEqual(ctx["transactions_pages"], 2)
        self.assertEqual(ctx["transactions_page_size"], 100)
        self.assertEqual(len(ctx["transactions"]), 50)

    def test_balance_chart_present_even_when_empty(self) -> None:
        ctx = wallet_page(_df([]), spec=FilterSpec(), meta=_meta(), address=WALLET)
        self.assertIn("<svg", ctx["balance_chart_svg"])
        self.assertIn("<svg", ctx["activity_chart_svg"])

    def test_meta_none_yields_empty_state_friendly_context(self) -> None:
        ctx = wallet_page(_df([]), spec=FilterSpec(), meta=None, address=WALLET)
        self.assertIsNone(ctx["meta"])
        self.assertEqual(ctx["transactions_total"], 0)


class TransactionDetailTests(unittest.TestCase):
    def test_returns_row_dict_for_known_signature(self) -> None:
        ctx = transaction_detail(_df([_row()]), "sig-x", address=WALLET)
        self.assertEqual(ctx["signature"], "sig-x")
        self.assertEqual(ctx["address"], WALLET)
        self.assertEqual(ctx["status"], "succeeded")
        self.assertIn("explorer_url", ctx)

    def test_unknown_signature_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            transaction_detail(_df([_row()]), "nope", address=WALLET)


if __name__ == "__main__":
    unittest.main()
