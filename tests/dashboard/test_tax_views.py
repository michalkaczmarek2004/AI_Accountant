from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS
from ai_accountant.dashboard.views import tax_page

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


def _make_df(*rows: dict) -> pd.DataFrame:
    base = {col: None for col in DATAFRAME_COLUMNS}
    result = []
    for r in rows:
        row = dict(base)
        row.update({
            "status": "succeeded",
            "source": "JUPITER",
            "tag_protocol": "Jupiter",
            "fee_sol": Decimal("0.001"),
            "fee_paid_by_wallet": True,
            "timestamp_unix": 1735689600,
            "signature": "A" * 87,
            "token_flow_details": [],
            "native_net_sol": Decimal("0"),
            "native_in_sol": Decimal("0"),
            "native_out_sol": Decimal("0"),
            "tag_confidence": 0.9,
        })
        row.update(r)
        result.append(row)
    return pd.DataFrame(result, columns=DATAFRAME_COLUMNS)


class TaxPageContextTests(unittest.TestCase):
    def test_empty_df_sets_no_data_true(self):
        df = pd.DataFrame(columns=DATAFRAME_COLUMNS)
        ctx = tax_page(df, address=WALLET, meta=None)
        self.assertTrue(ctx["no_data"])

    def test_all_failed_sets_no_data_true(self):
        df = _make_df({"status": "failed"})
        ctx = tax_page(df, address=WALLET, meta=None)
        self.assertTrue(ctx["no_data"])

    def test_succeeded_rows_sets_no_data_false(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None)
        self.assertFalse(ctx["no_data"])

    def test_required_context_keys_present(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None)
        for key in ("address", "address_short", "meta", "summary",
                    "classification", "tax_advice", "review_queue", "yearly", "no_data",
                    "tax_country", "tax_country_profile", "tax_country_options",
                    "tax_deadlines"):
            self.assertIn(key, ctx)

    def test_address_short_truncated(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None)
        self.assertLessEqual(len(ctx["address_short"]), 12)

    def test_summary_keys_present(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None)
        for key in ("total_income_sol", "total_expense_sol", "total_fees_sol",
                    "net_sol", "net_positive", "taxable_count", "review_count"):
            self.assertIn(key, ctx["summary"])

    def test_summary_values_are_strings_except_net_positive(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None)
        s = ctx["summary"]
        for key in ("total_income_sol", "total_expense_sol", "total_fees_sol",
                    "net_sol", "taxable_count", "review_count"):
            self.assertIsInstance(s[key], str, msg=f"{key} should be str")
        self.assertIsInstance(s["net_positive"], bool)

    def test_classification_is_list(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None)
        self.assertIsInstance(ctx["classification"], list)

    def test_review_queue_is_list(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None)
        self.assertIsInstance(ctx["review_queue"], list)

    def test_tax_advice_is_list(self):
        df = _make_df({"tag_type": "Swap", "native_out_sol": Decimal("1.0")})
        ctx = tax_page(df, address=WALLET, meta=None, tax_country="US")
        self.assertIsInstance(ctx["tax_advice"], list)
        self.assertTrue(ctx["tax_advice"])

    def test_no_data_tax_advice_is_empty(self):
        df = pd.DataFrame(columns=DATAFRAME_COLUMNS)
        ctx = tax_page(df, address=WALLET, meta=None)
        self.assertEqual(ctx["tax_advice"], [])

    def test_yearly_is_list(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None)
        self.assertIsInstance(ctx["yearly"], list)

    def test_meta_passed_through(self):
        df = _make_df({"tag_type": "Swap"})
        meta = {"fetched_at": "2025-01-01T00:00:00Z", "pages_fetched": 1}
        ctx = tax_page(df, address=WALLET, meta=meta)
        self.assertEqual(ctx["meta"], meta)

    def test_swap_counted_as_taxable(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None)
        self.assertEqual(ctx["summary"]["taxable_count"], "1")

    def test_staking_withdrawal_not_counted_as_taxable(self):
        df = _make_df({"tag_type": "Stake/Unstake", "native_net_sol": Decimal("1.0")})
        ctx = tax_page(df, address=WALLET, meta=None)
        self.assertEqual(ctx["summary"]["taxable_count"], "0")

    def test_tax_country_defaults_and_passes_into_review_notes(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None, tax_country="US")
        self.assertEqual(ctx["tax_country"], "US")
        self.assertEqual(ctx["tax_country_profile"]["label"], "United States")
        self.assertIn("taxable disposal", ctx["review_queue"][0]["tax_treatment"])
        self.assertIn("Form 8949", ctx["review_queue"][0]["tax_forms"])
        self.assertTrue(ctx["tax_deadlines"])

    def test_poland_tax_country_uses_polish_profile(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None, tax_country="PL")
        self.assertEqual(ctx["tax_country"], "PL")
        self.assertEqual(ctx["tax_country_profile"]["label"], "Poland")
        self.assertIn("PIT-38", ctx["review_queue"][0]["tax_forms"])

    def test_unknown_tax_country_falls_back_to_us(self):
        df = _make_df({"tag_type": "Swap"})
        ctx = tax_page(df, address=WALLET, meta=None, tax_country="ZZ")
        self.assertEqual(ctx["tax_country"], "US")


if __name__ == "__main__":
    unittest.main()
