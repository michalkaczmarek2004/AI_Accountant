from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant import DATAFRAME_COLUMNS
from ai_accountant.tax_assistant import (
    LARGE_FLOW_THRESHOLD,
    REVIEW_REQUIRED_CATEGORIES,
    TAXABLE_CATEGORIES,
    _fmt,
    _review_count,
    _review_tier,
    _row_date,
    tax_category,
    tax_classification_rows,
    tax_export_frame,
    tax_review_queue,
    tax_summary,
    tax_yearly_export_frame,
    yearly_summary,
)


def _row(**kwargs) -> pd.Series:
    base = {col: None for col in DATAFRAME_COLUMNS}
    base.update({
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
    base.update(kwargs)
    return pd.Series(base)


class TaxCategoryTests(unittest.TestCase):
    def test_swap_is_swap(self):
        self.assertEqual(tax_category(_row(tag_type="Swap", native_net_sol=Decimal("0.5"))), "Swap")

    def test_lp_deposit_is_swap(self):
        self.assertEqual(tax_category(_row(tag_type="LP Deposit/Withdraw")), "Swap")

    def test_perp_trade_is_swap(self):
        self.assertEqual(tax_category(_row(tag_type="Perpetual Trade")), "Swap")

    def test_nft_buy_is_swap(self):
        self.assertEqual(tax_category(_row(tag_type="NFT Buy/Sell", native_net_sol=Decimal("-1.0"))), "Swap")

    def test_transfer_inflow_is_income(self):
        self.assertEqual(tax_category(_row(tag_type="Transfer", native_net_sol=Decimal("1.0"))), "Income")

    def test_transfer_outflow_is_expense(self):
        self.assertEqual(tax_category(_row(tag_type="Transfer", native_net_sol=Decimal("-0.5"))), "Expense")

    def test_staking_withdrawal_is_staking_needs_review(self):
        self.assertEqual(
            tax_category(_row(tag_type="Stake/Unstake", native_net_sol=Decimal("1.0"))),
            "Staking / Needs review",
        )

    def test_staking_deposit_is_transfer(self):
        self.assertEqual(
            tax_category(_row(tag_type="Stake/Unstake", native_net_sol=Decimal("-1.0"))),
            "Transfer",
        )

    def test_airdrop_is_airdrop(self):
        self.assertEqual(tax_category(_row(tag_type="Airdrop")), "Airdrop")

    def test_bridge_is_transfer(self):
        self.assertEqual(tax_category(_row(tag_type="Bridge")), "Transfer")

    def test_mint_burn_is_transfer(self):
        self.assertEqual(tax_category(_row(tag_type="Mint/Burn")), "Transfer")

    def test_unknown_tag_is_unknown(self):
        self.assertEqual(tax_category(_row(tag_type=None)), "Unknown / Needs review")

    def test_taxable_categories_constant(self):
        self.assertIn("Income", TAXABLE_CATEGORIES)
        self.assertIn("Swap", TAXABLE_CATEGORIES)
        self.assertIn("Airdrop", TAXABLE_CATEGORIES)
        self.assertNotIn("Staking / Needs review", TAXABLE_CATEGORIES)
        self.assertNotIn("Unknown / Needs review", TAXABLE_CATEGORIES)
        self.assertNotIn("Transfer", TAXABLE_CATEGORIES)

    def test_review_required_categories_constant(self):
        self.assertIn("Swap", REVIEW_REQUIRED_CATEGORIES)
        self.assertIn("Airdrop", REVIEW_REQUIRED_CATEGORIES)
        self.assertIn("Staking / Needs review", REVIEW_REQUIRED_CATEGORIES)
        self.assertIn("Unknown / Needs review", REVIEW_REQUIRED_CATEGORIES)
        self.assertNotIn("Income", REVIEW_REQUIRED_CATEGORIES)
        self.assertNotIn("Transfer", REVIEW_REQUIRED_CATEGORIES)


class ReviewTierTests(unittest.TestCase):
    def test_unknown_is_tier_1(self):
        row = _row(tag_type=None)
        self.assertEqual(_review_tier(row, "Unknown / Needs review"), 1)

    def test_swap_is_tier_2(self):
        row = _row(tag_type="Swap")
        self.assertEqual(_review_tier(row, "Swap"), 2)

    def test_airdrop_is_tier_3(self):
        row = _row(tag_type="Airdrop")
        self.assertEqual(_review_tier(row, "Airdrop"), 3)

    def test_staking_needs_review_is_tier_4(self):
        row = _row(tag_type="Stake/Unstake", native_net_sol=Decimal("1.0"))
        self.assertEqual(_review_tier(row, "Staking / Needs review"), 4)

    def test_failed_income_is_tier_5(self):
        row = _row(tag_type="Transfer", native_net_sol=Decimal("0.1"), status="failed")
        self.assertEqual(_review_tier(row, "Income"), 5)

    def test_large_income_is_tier_6(self):
        row = _row(tag_type="Transfer", native_net_sol=Decimal("1.0"))
        self.assertEqual(_review_tier(row, "Income"), 6)

    def test_small_income_returns_none(self):
        row = _row(tag_type="Transfer", native_net_sol=Decimal("0.1"))
        self.assertIsNone(_review_tier(row, "Income"))

    def test_large_threshold_constant_is_half_sol(self):
        self.assertEqual(LARGE_FLOW_THRESHOLD, Decimal("0.5"))

    def test_swap_is_tier_2_even_when_failed(self):
        row = _row(tag_type="Swap", status="failed")
        self.assertEqual(_review_tier(row, "Swap"), 2)

    def test_missing_counterparty_transfer_is_tier_7(self):
        row = _row(
            tag_type="Transfer",
            native_net_sol=Decimal("0.1"),
            source="UNKNOWN",
            tag_protocol="Unknown",
        )
        self.assertEqual(_review_tier(row, "Income"), 7)


class UtilityHelperTests(unittest.TestCase):
    def test_review_count_counts_qualifying_rows(self):
        rows = [
            _row(tag_type="Swap"),          # tier 2 → qualifies
            _row(tag_type="Airdrop"),        # tier 3 → qualifies
            _row(tag_type="Transfer", native_net_sol=Decimal("0.1")),  # no tier → doesn't qualify
        ]
        df = pd.DataFrame(rows)
        self.assertEqual(_review_count(df), 2)

    def test_review_count_empty_df_returns_zero(self):
        from ai_accountant import DATAFRAME_COLUMNS
        df = pd.DataFrame(columns=DATAFRAME_COLUMNS)
        self.assertEqual(_review_count(df), 0)

    def test_row_date_valid_timestamp(self):
        row = _row(timestamp_unix=1735689600)
        self.assertEqual(_row_date(row), "2025-01-01")

    def test_row_date_none_returns_unknown(self):
        row = _row(timestamp_unix=None)
        self.assertEqual(_row_date(row), "Unknown")

    def test_fmt_strips_trailing_zeros(self):
        self.assertEqual(_fmt(Decimal("1.500")), "1.5")

    def test_fmt_zero_returns_zero(self):
        self.assertEqual(_fmt(Decimal("0")), "0")

    def test_fmt_signed_positive(self):
        self.assertEqual(_fmt(Decimal("1.5"), signed=True), "+1.5")

    def test_fmt_signed_zero(self):
        self.assertEqual(_fmt(Decimal("0"), signed=True), "+0")

    def test_fmt_signed_negative(self):
        self.assertEqual(_fmt(Decimal("-1.5"), signed=True), "-1.5")

    def test_fmt_integer_decimal_not_corrupted(self):
        self.assertEqual(_fmt(Decimal("100")), "100")


class TaxSummaryTests(unittest.TestCase):
    def test_empty_df_returns_zeros(self):
        df = pd.DataFrame(columns=DATAFRAME_COLUMNS)
        result = tax_summary(df, "wallet")
        self.assertEqual(result["total_income_sol"], Decimal("0"))
        self.assertEqual(result["total_expense_sol"], Decimal("0"))
        self.assertEqual(result["total_fees_sol"], Decimal("0"))
        self.assertEqual(result["net_sol"], Decimal("0"))
        self.assertEqual(result["taxable_count"], 0)
        self.assertEqual(result["review_count"], 0)

    def test_income_summed_for_succeeded_rows(self):
        rows = [
            _row(tag_type="Transfer", native_net_sol=Decimal("2.0")),
            _row(tag_type="Transfer", native_net_sol=Decimal("1.0")),
        ]
        df = pd.DataFrame(rows)
        result = tax_summary(df, "wallet")
        self.assertEqual(result["total_income_sol"], Decimal("3.0"))

    def test_failed_rows_excluded_from_income(self):
        rows = [
            _row(tag_type="Transfer", native_net_sol=Decimal("2.0")),
            _row(tag_type="Transfer", native_net_sol=Decimal("1.0"), status="failed"),
        ]
        df = pd.DataFrame(rows)
        result = tax_summary(df, "wallet")
        self.assertEqual(result["total_income_sol"], Decimal("2.0"))

    def test_expense_is_absolute_value(self):
        rows = [_row(tag_type="Transfer", native_net_sol=Decimal("-1.5"))]
        df = pd.DataFrame(rows)
        result = tax_summary(df, "wallet")
        self.assertEqual(result["total_expense_sol"], Decimal("1.5"))

    def test_taxable_count_excludes_staking_and_unknown(self):
        rows = [
            _row(tag_type="Swap"),
            _row(tag_type="Airdrop"),
            _row(tag_type="Stake/Unstake", native_net_sol=Decimal("1.0")),
            _row(tag_type=None),
        ]
        df = pd.DataFrame(rows)
        result = tax_summary(df, "wallet")
        self.assertEqual(result["taxable_count"], 2)

    def test_fees_summed_only_when_paid_by_wallet(self):
        rows = [
            _row(fee_sol=Decimal("0.001"), fee_paid_by_wallet=True),
            _row(fee_sol=Decimal("0.002"), fee_paid_by_wallet=False),
        ]
        df = pd.DataFrame(rows)
        result = tax_summary(df, "wallet")
        self.assertEqual(result["total_fees_sol"], Decimal("0.001"))

    def test_net_sol_is_income_minus_expense(self):
        rows = [
            _row(tag_type="Transfer", native_net_sol=Decimal("3.0")),
            _row(tag_type="Transfer", native_net_sol=Decimal("-1.0")),
        ]
        df = pd.DataFrame(rows)
        result = tax_summary(df, "wallet")
        self.assertEqual(result["net_sol"], Decimal("2.0"))

    def test_review_count_includes_swap_rows(self):
        rows = [_row(tag_type="Swap"), _row(tag_type="Swap")]
        df = pd.DataFrame(rows)
        result = tax_summary(df, "wallet")
        self.assertEqual(result["review_count"], 2)


class TaxClassificationRowsTests(unittest.TestCase):
    def test_empty_df_returns_empty(self):
        df = pd.DataFrame(columns=DATAFRAME_COLUMNS)
        self.assertEqual(tax_classification_rows(df), [])

    def test_unknown_always_last(self):
        rows = [
            _row(tag_type=None),
            _row(tag_type="Swap"),
            _row(tag_type="Swap"),
        ]
        df = pd.DataFrame(rows)
        result = tax_classification_rows(df)
        self.assertEqual(result[-1]["category"], "Unknown / Needs review")

    def test_rows_sorted_by_count_descending(self):
        rows = [
            _row(tag_type="Airdrop"),
            _row(tag_type="Swap"),
            _row(tag_type="Swap"),
            _row(tag_type="Swap"),
        ]
        df = pd.DataFrame(rows)
        result = [r for r in tax_classification_rows(df) if r["category"] != "Unknown / Needs review"]
        self.assertEqual(result[0]["category"], "Swap")

    def test_flagged_for_review_required_categories(self):
        rows = [_row(tag_type="Swap"), _row(tag_type="Transfer", native_net_sol=Decimal("0.1"))]
        df = pd.DataFrame(rows)
        by_cat = {r["category"]: r["flagged"] for r in tax_classification_rows(df)}
        self.assertTrue(by_cat["Swap"])
        self.assertFalse(by_cat["Income"])

    def test_case_keys_field_present(self):
        rows = [_row(tag_type="Swap")]
        df = pd.DataFrame(rows)
        result = tax_classification_rows(df)
        swap_row = next(r for r in result if r["category"] == "Swap")
        self.assertIn("swap", swap_row["case_keys"])

    def test_sol_net_is_string(self):
        rows = [_row(tag_type="Transfer", native_net_sol=Decimal("1.0"))]
        df = pd.DataFrame(rows)
        result = tax_classification_rows(df)
        income_row = next(r for r in result if r["category"] == "Income")
        self.assertIsInstance(income_row["sol_net"], str)


class TaxReviewQueueTests(unittest.TestCase):
    def test_empty_df_returns_empty(self):
        df = pd.DataFrame(columns=DATAFRAME_COLUMNS)
        self.assertEqual(tax_review_queue(df), [])

    def test_swap_appears_in_queue(self):
        rows = [_row(tag_type="Swap")]
        df = pd.DataFrame(rows)
        result = tax_review_queue(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "Swap")

    def test_small_income_not_in_queue(self):
        rows = [_row(
            tag_type="Transfer",
            native_net_sol=Decimal("0.1"),
            source="JUPITER",
            tag_protocol="Jupiter",
        )]
        df = pd.DataFrame(rows)
        self.assertEqual(tax_review_queue(df), [])

    def test_unknown_tier_1_sorted_before_swap_tier_2(self):
        rows = [
            _row(tag_type="Swap", timestamp_unix=2000),
            _row(tag_type=None, timestamp_unix=1000),
        ]
        df = pd.DataFrame(rows)
        result = tax_review_queue(df)
        self.assertEqual(result[0]["category"], "Unknown / Needs review")
        self.assertEqual(result[1]["category"], "Swap")

    def test_within_same_tier_sorted_by_timestamp_descending(self):
        rows = [
            _row(tag_type="Swap", timestamp_unix=1000, signature="A" * 87),
            _row(tag_type="Swap", timestamp_unix=2000, signature="B" * 87),
        ]
        df = pd.DataFrame(rows)
        result = tax_review_queue(df)
        self.assertEqual(result[0]["signature"], "B" * 87)

    def test_limit_caps_results(self):
        rows = [_row(tag_type="Swap") for _ in range(5)]
        df = pd.DataFrame(rows)
        result = tax_review_queue(df, limit=3)
        self.assertEqual(len(result), 3)

    def test_result_has_required_keys(self):
        rows = [_row(tag_type="Swap")]
        df = pd.DataFrame(rows)
        item = tax_review_queue(df)[0]
        for key in (
            "date", "signature", "sig_short", "category", "sol_net",
            "short_explanation", "known_facts", "unknown_facts",
            "suggested_actions", "expanded_explanation", "review_label",
            "status", "source", "tag_protocol", "tier",
        ):
            self.assertIn(key, item, msg=f"missing key: {key}")

    def test_large_income_is_in_queue_at_tier_6(self):
        rows = [_row(tag_type="Transfer", native_net_sol=Decimal("1.0"))]
        df = pd.DataFrame(rows)
        result = tax_review_queue(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tier"], 6)

    def test_sig_short_is_truncated(self):
        rows = [_row(tag_type="Swap", signature="A" * 87)]
        df = pd.DataFrame(rows)
        item = tax_review_queue(df)[0]
        self.assertTrue(item["sig_short"].endswith("…"))
        self.assertLessEqual(len(item["sig_short"]), 10)


class YearlySummaryTests(unittest.TestCase):
    def test_empty_df_returns_empty(self):
        df = pd.DataFrame(columns=DATAFRAME_COLUMNS)
        self.assertEqual(yearly_summary(df), [])

    def test_groups_by_year(self):
        rows = [
            _row(tag_type="Transfer", native_net_sol=Decimal("1.0"), timestamp_unix=1700000000),
            _row(tag_type="Transfer", native_net_sol=Decimal("2.0"), timestamp_unix=1735689600),
        ]
        df = pd.DataFrame(rows)
        result = yearly_summary(df)
        years = [r["year"] for r in result]
        self.assertEqual(len(set(years)), 2)

    def test_sorted_year_descending(self):
        rows = [
            _row(tag_type="Transfer", native_net_sol=Decimal("1.0"), timestamp_unix=1700000000),
            _row(tag_type="Transfer", native_net_sol=Decimal("2.0"), timestamp_unix=1735689600),
        ]
        df = pd.DataFrame(rows)
        result = yearly_summary(df)
        self.assertGreater(result[0]["year"], result[1]["year"])

    def test_failed_excluded_from_aggregates(self):
        rows = [
            _row(tag_type="Transfer", native_net_sol=Decimal("1.0"), timestamp_unix=1735689600),
            _row(tag_type="Transfer", native_net_sol=Decimal("5.0"), timestamp_unix=1735689600, status="failed"),
        ]
        df = pd.DataFrame(rows)
        result = yearly_summary(df)
        self.assertEqual(len(result), 1)
        self.assertNotIn("5", result[0]["income_sol"])

    def test_result_keys(self):
        rows = [_row(tag_type="Swap", timestamp_unix=1735689600)]
        df = pd.DataFrame(rows)
        result = yearly_summary(df)
        for key in ("year", "income_sol", "expense_sol", "fees_sol", "taxable_count"):
            self.assertIn(key, result[0])


class TaxExportFrameTests(unittest.TestCase):
    EXPECTED_COLUMNS = [
        "date", "signature", "status", "tax_category", "case_key", "tag_type",
        "sol_net", "token_summary", "fee_sol", "is_potentially_taxable",
        "review_label", "notes",
    ]

    def test_empty_df_returns_correct_columns(self):
        df = pd.DataFrame(columns=DATAFRAME_COLUMNS)
        result = tax_export_frame(df)
        self.assertEqual(list(result.columns), self.EXPECTED_COLUMNS)
        self.assertEqual(len(result), 0)

    def test_case_key_and_tag_type_both_present(self):
        rows = [_row(tag_type="Swap")]
        df = pd.DataFrame(rows)
        result = tax_export_frame(df)
        self.assertEqual(result["case_key"].iloc[0], "swap")
        self.assertEqual(result["tag_type"].iloc[0], "Swap")

    def test_is_potentially_taxable_values(self):
        rows = [
            _row(tag_type="Swap"),
            _row(tag_type="Transfer", native_net_sol=Decimal("0.1")),
        ]
        df = pd.DataFrame(rows)
        result = tax_export_frame(df)
        vals = set(result["is_potentially_taxable"].tolist())
        self.assertIn("yes", vals)
        self.assertIn("no", vals)

    def test_notes_truncated_to_200_chars(self):
        rows = [_row(tag_type="Swap")]
        df = pd.DataFrame(rows)
        result = tax_export_frame(df)
        self.assertLessEqual(len(result["notes"].iloc[0]), 200)

    def test_unknown_category_is_not_taxable(self):
        rows = [_row(tag_type=None)]
        df = pd.DataFrame(rows)
        result = tax_export_frame(df)
        self.assertEqual(result["is_potentially_taxable"].iloc[0], "no")


class TaxYearlyExportFrameTests(unittest.TestCase):
    def test_empty_df_returns_correct_columns(self):
        df = pd.DataFrame(columns=DATAFRAME_COLUMNS)
        result = tax_yearly_export_frame(df)
        self.assertEqual(
            list(result.columns),
            ["year", "income_sol", "expense_sol", "fees_sol", "potentially_taxable_count"],
        )

    def test_non_empty_df_has_rows(self):
        rows = [_row(tag_type="Swap", timestamp_unix=1735689600)]
        df = pd.DataFrame(rows)
        result = tax_yearly_export_frame(df)
        self.assertGreater(len(result), 0)


if __name__ == "__main__":
    unittest.main()
