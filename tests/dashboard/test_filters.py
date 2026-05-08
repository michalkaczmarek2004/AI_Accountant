from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS
from ai_accountant.dashboard.filters import FilterSpec

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _df_with(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([{c: None for c in DATAFRAME_COLUMNS} for _ in rows])
    for i, row in enumerate(rows):
        for k, v in row.items():
            df.at[i, k] = v
    return df


class FilterSpecParsingTests(unittest.TestCase):
    def test_empty_querystring_yields_inactive_spec(self) -> None:
        spec = FilterSpec.from_querystring({})
        self.assertFalse(spec.is_active())
        self.assertEqual(spec.page, 1)
        self.assertIsNone(spec.date_from)

    def test_parses_every_documented_key(self) -> None:
        spec = FilterSpec.from_querystring(
            {
                "from": "2025-01-01",
                "to": "2025-05-08",
                "token": USDC_MINT,
                "type": "swap",
                "status": "failed",
                "source": "JUPITER",
                "q": "USDC",
                "page": "3",
            }
        )
        self.assertTrue(spec.is_active())
        self.assertEqual(spec.date_from, date(2025, 1, 1))
        self.assertEqual(spec.date_to, date(2025, 5, 8))
        self.assertEqual(spec.token, USDC_MINT)
        self.assertEqual(spec.type, "swap")
        self.assertEqual(spec.status, "failed")
        self.assertEqual(spec.source, "JUPITER")
        self.assertEqual(spec.q, "USDC")
        self.assertEqual(spec.page, 3)

    def test_unknown_keys_are_ignored(self) -> None:
        spec = FilterSpec.from_querystring({"frobnicate": "yes", "from": "2025-01-01"})
        self.assertEqual(spec.date_from, date(2025, 1, 1))

    def test_malformed_dates_are_dropped_silently(self) -> None:
        spec = FilterSpec.from_querystring({"from": "2025-13-99", "to": "garbage"})
        self.assertIsNone(spec.date_from)
        self.assertIsNone(spec.date_to)

    def test_invalid_status_is_dropped(self) -> None:
        spec = FilterSpec.from_querystring({"status": "wat"})
        self.assertIsNone(spec.status)

    def test_invalid_page_falls_back_to_one(self) -> None:
        self.assertEqual(FilterSpec.from_querystring({"page": "0"}).page, 1)
        self.assertEqual(FilterSpec.from_querystring({"page": "-1"}).page, 1)
        self.assertEqual(FilterSpec.from_querystring({"page": "abc"}).page, 1)

    def test_empty_string_values_are_dropped(self) -> None:
        spec = FilterSpec.from_querystring({"token": "", "type": ""})
        self.assertIsNone(spec.token)
        self.assertIsNone(spec.type)


class FilterSpecApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.df = _df_with(
            [
                {
                    "signature": "a",
                    "timestamp_unix": 1736899200,  # 2025-01-15 UTC
                    "transaction_type": "swap",
                    "status": "succeeded",
                    "source": "JUPITER",
                    "description": "Swapped 1 SOL for USDC",
                    "net_flow": {"SOL": Decimal("-1"), USDC_MINT: Decimal("100")},
                },
                {
                    "signature": "b",
                    "timestamp_unix": 1740000000,  # 2025-02-19
                    "transaction_type": "transfer",
                    "status": "failed",
                    "source": "SYSTEM",
                    "description": "Plain SOL transfer",
                    "net_flow": {"SOL": Decimal("-0.5")},
                },
                {
                    "signature": "c",
                    "timestamp_unix": 1746000000,  # 2025-04-30
                    "transaction_type": "swap",
                    "status": "succeeded",
                    "source": "RAYDIUM",
                    "description": "Swapped USDC for BONK",
                    "net_flow": {USDC_MINT: Decimal("-50")},
                },
            ]
        )

    def test_apply_with_no_filters_returns_full_frame(self) -> None:
        spec = FilterSpec.from_querystring({})
        out = spec.apply(self.df)
        self.assertEqual(len(out), 3)

    def test_apply_status_filter(self) -> None:
        spec = FilterSpec.from_querystring({"status": "failed"})
        out = spec.apply(self.df)
        self.assertEqual(out["signature"].tolist(), ["b"])

    def test_apply_type_filter(self) -> None:
        spec = FilterSpec.from_querystring({"type": "swap"})
        out = spec.apply(self.df)
        self.assertEqual(sorted(out["signature"].tolist()), ["a", "c"])

    def test_apply_source_filter(self) -> None:
        spec = FilterSpec.from_querystring({"source": "RAYDIUM"})
        self.assertEqual(spec.apply(self.df)["signature"].tolist(), ["c"])

    def test_apply_token_filter_matches_mint_in_net_flow(self) -> None:
        spec = FilterSpec.from_querystring({"token": USDC_MINT})
        self.assertEqual(sorted(spec.apply(self.df)["signature"].tolist()), ["a", "c"])

    def test_apply_token_filter_sol_matches_native_flow(self) -> None:
        spec = FilterSpec.from_querystring({"token": "SOL"})
        self.assertEqual(sorted(spec.apply(self.df)["signature"].tolist()), ["a", "b"])

    def test_apply_q_is_case_insensitive_substring(self) -> None:
        spec = FilterSpec.from_querystring({"q": "usdc"})
        self.assertEqual(sorted(spec.apply(self.df)["signature"].tolist()), ["a", "c"])

    def test_apply_date_range_inclusive(self) -> None:
        spec = FilterSpec.from_querystring({"from": "2025-02-01", "to": "2025-04-30"})
        self.assertEqual(sorted(spec.apply(self.df)["signature"].tolist()), ["b", "c"])

    def test_apply_on_empty_frame_returns_empty(self) -> None:
        spec = FilterSpec.from_querystring({"status": "failed"})
        empty = pd.DataFrame(columns=DATAFRAME_COLUMNS)
        out = spec.apply(empty)
        self.assertEqual(len(out), 0)
        self.assertEqual(list(out.columns), DATAFRAME_COLUMNS)


class FilterSpecQuerystringRoundTripTests(unittest.TestCase):
    def test_to_querystring_omits_unset_keys(self) -> None:
        spec = FilterSpec.from_querystring({"status": "failed"})
        self.assertEqual(spec.to_querystring(), "status=failed")

    def test_round_trip_preserves_all_set_keys(self) -> None:
        params = {"from": "2025-01-01", "status": "succeeded", "q": "swap"}
        spec = FilterSpec.from_querystring(params)
        rebuilt = FilterSpec.from_querystring(
            dict(p.split("=", 1) for p in spec.to_querystring().split("&") if "=" in p)
        )
        self.assertEqual(rebuilt.date_from, spec.date_from)
        self.assertEqual(rebuilt.status, spec.status)
        self.assertEqual(rebuilt.q, spec.q)


if __name__ == "__main__":
    unittest.main()
