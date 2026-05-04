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


if __name__ == "__main__":
    unittest.main()
