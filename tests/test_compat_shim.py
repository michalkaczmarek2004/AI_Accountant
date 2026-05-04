"""Verifies the back-compat shim and re-exports stay intact during refactor."""

from __future__ import annotations

import unittest


class CompatShimTests(unittest.TestCase):
    def test_exceptions_are_publicly_importable_from_package(self):
        from ai_accountant import (
            HeliusAPIError,
            HeliusAuthenticationError,
            HeliusPermissionError,
            HeliusRateLimitError,
            InvalidSolanaAddressError,
            SolanaDataFetcherError,
        )

        self.assertTrue(issubclass(HeliusAPIError, SolanaDataFetcherError))
        self.assertTrue(issubclass(HeliusAuthenticationError, HeliusAPIError))
        self.assertTrue(issubclass(HeliusPermissionError, HeliusAPIError))
        self.assertTrue(issubclass(HeliusRateLimitError, HeliusAPIError))
        self.assertTrue(issubclass(InvalidSolanaAddressError, SolanaDataFetcherError))

    def test_exceptions_module_is_publicly_importable(self):
        from ai_accountant.exceptions import (
            HeliusAPIError,
            SolanaDataFetcherError,
        )

        self.assertTrue(issubclass(HeliusAPIError, SolanaDataFetcherError))

    def test_solana_data_fetcher_submodule_still_importable(self):
        from ai_accountant.solana_data_fetcher import (
            HeliusAPIError,
            SolanaDataFetcher,
            TransactionParser,
            validate_address,
        )

        self.assertTrue(callable(SolanaDataFetcher))
        self.assertTrue(callable(TransactionParser))
        self.assertTrue(callable(validate_address))
        self.assertTrue(issubclass(HeliusAPIError, Exception))

    def test_build_transaction_row_back_compat_alias(self):
        from ai_accountant import SolanaDataFetcher

        wallet = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
        fetcher = SolanaDataFetcher(api_key="test-key")
        row = fetcher._build_transaction_row(
            wallet,
            {
                "signature": "s",
                "slot": 1,
                "timestamp": 1_700_000_000,
                "fee": 0,
                "feePayer": "",
                "nativeTransfers": [],
                "tokenTransfers": [],
            },
        )
        self.assertEqual(row["signature"], "s")
        self.assertEqual(row["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
