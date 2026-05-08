from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant import DATAFRAME_COLUMNS, SolanaDataFetcher

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


class DataFrameModuleTests(unittest.TestCase):
    def test_columns_constant_publicly_importable(self):
        self.assertIsInstance(DATAFRAME_COLUMNS, list)
        self.assertIn("signature", DATAFRAME_COLUMNS)
        self.assertIn("net_flow", DATAFRAME_COLUMNS)

    def test_columns_match_class_attr_for_back_compat(self):
        self.assertEqual(SolanaDataFetcher.DATAFRAME_COLUMNS, DATAFRAME_COLUMNS)

    def test_to_dataframe_empty_returns_empty_with_schema(self):
        from ai_accountant.dataframe import to_dataframe
        from ai_accountant.parser import TransactionParser

        parser = TransactionParser(WALLET)
        df = to_dataframe(parser, [])
        self.assertEqual(list(df.columns), DATAFRAME_COLUMNS)
        self.assertEqual(len(df), 0)
        self.assertIsInstance(df, pd.DataFrame)


class DataFrameNewColumnsTests(unittest.TestCase):
    def test_new_columns_present_in_dataframe_columns(self) -> None:
        for col in (
            "program_ids", "tag_type", "tag_protocol", "tag_assets",
            "tag_amount_display", "tag_usd_estimate", "tag_confidence",
        ):
            self.assertIn(col, DATAFRAME_COLUMNS, f"missing: {col}")

    def test_new_columns_after_existing_columns(self) -> None:
        idx_signature = DATAFRAME_COLUMNS.index("signature")
        idx_tag = DATAFRAME_COLUMNS.index("tag_type")
        self.assertGreater(idx_tag, idx_signature)


if __name__ == "__main__":
    unittest.main()
