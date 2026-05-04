"""Backwards-compat shim. Import from `ai_accountant` directly.

This module will be removed in a future release. New code should import from
`ai_accountant` (the package) or from the focused submodules (`client`,
`parser`, `transport`, `addresses`, `dataframe`, `exceptions`).
"""

from __future__ import annotations

from .addresses import BASE58_ALPHABET, BASE58_INDEX, validate_address  # noqa: F401
from .client import DEFAULT_BASE_URL, SolanaDataFetcher  # noqa: F401
from .dataframe import DATAFRAME_COLUMNS  # noqa: F401
from .exceptions import (  # noqa: F401
    HeliusAPIError,
    HeliusAuthenticationError,
    HeliusPermissionError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
    SolanaDataFetcherError,
)
from .parser import LAMPORTS_PER_SOL, TransactionParser  # noqa: F401
from .transport import (  # noqa: F401
    TransportError,
    _SimpleResponse,
    _UrllibSession,
)
