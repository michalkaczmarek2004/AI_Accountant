"""Exception hierarchy for ai_accountant.

Single source of truth. Both `solana_data_fetcher.py` and external callers import from here.
"""
from __future__ import annotations


class SolanaDataFetcherError(Exception):
    """Base exception for Solana data fetching errors."""


class InvalidSolanaAddressError(SolanaDataFetcherError):
    """Raised when a wallet address is not a valid Solana public key."""


class HeliusAPIError(SolanaDataFetcherError):
    """Raised when the Helius API returns an unrecoverable error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HeliusAuthenticationError(HeliusAPIError):
    """Raised when the provided API key is rejected by Helius."""


class HeliusPermissionError(HeliusAPIError):
    """Raised when the caller cannot access the requested Helius resource."""


class HeliusRateLimitError(HeliusAPIError):
    """Raised when the Helius rate limit is exceeded after all retries."""
