from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from ai_accountant import SolanaDataFetcher
from ai_accountant.report import EXPORT_COLUMNS, render_html_report, transaction_export_frame

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
OTHER = "ExternalCounterparty111111111111111111111111111"


def _frame():
    fetcher = SolanaDataFetcher(api_key="demo-not-used")
    return fetcher.transactions_to_dataframe(
        WALLET,
        [
            {
                "signature": "demo-001-inbound",
                "slot": 1,
                "timestamp": 1_704_067_200,
                "type": "TRANSFER",
                "source": "SYSTEM_PROGRAM",
                "description": "Inbound SOL transfer",
                "fee": 5_000,
                "feePayer": OTHER,
                "nativeTransfers": [
                    {
                        "fromUserAccount": OTHER,
                        "toUserAccount": WALLET,
                        "amount": 1_000_000_000,
                    }
                ],
                "tokenTransfers": [],
            },
            {
                "signature": "demo-002-failed",
                "slot": 2,
                "timestamp": 1_704_153_600,
                "type": "SWAP",
                "source": "JUPITER",
                "description": "Failed swap",
                "fee": 15_000_000,
                "feePayer": WALLET,
                "nativeTransfers": [],
                "tokenTransfers": [],
                "transactionError": {"InstructionError": [0, "Custom 1"]},
            },
        ],
    )


class ReportTests(unittest.TestCase):
    def test_render_html_report_contains_readable_sections(self):
        html = render_html_report(
            _frame(),
            WALLET,
            generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        self.assertIn("Wallet activity report", html)
        self.assertIn("Asset Flow", html)
        self.assertIn("Review Queue", html)
        self.assertIn("Failed transaction", html)
        self.assertIn("SOL", html)
        self.assertIn("demo-002-failed", html)

    def test_transaction_export_frame_is_flat_and_ordered_newest_first(self):
        export = transaction_export_frame(_frame())

        self.assertEqual(list(export.columns), EXPORT_COLUMNS)
        self.assertEqual(export.iloc[0]["signature"], "demo-002-failed")
        self.assertEqual(export.iloc[0]["date"], "2024-01-02")
        self.assertIsInstance(export.iloc[0]["fee_sol"], str)

    def test_write_wallet_report_creates_html_and_csv(self):
        from ai_accountant import write_wallet_report

        with (
            patch("pathlib.Path.mkdir") as mkdir,
            patch("pathlib.Path.write_text") as write_text,
            patch("pandas.DataFrame.to_csv") as to_csv,
        ):
            paths = write_wallet_report(_frame(), WALLET, "reports")

        mkdir.assert_called_once()
        write_text.assert_called_once()
        to_csv.assert_called_once()
        self.assertEqual(paths["html"].suffix, ".html")
        self.assertEqual(paths["csv"].suffix, ".csv")


if __name__ == "__main__":
    unittest.main()
