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


if __name__ == "__main__":
    unittest.main()
