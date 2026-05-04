"""Helius client: HTTP orchestration, retry/pagination, DataFrame helper."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

import pandas as pd

from .addresses import validate_address
from .dataframe import DATAFRAME_COLUMNS, to_dataframe
from .exceptions import (
    HeliusAPIError,
    HeliusAuthenticationError,
    HeliusPermissionError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
)
from .parser import TransactionParser
from .transport import (
    SessionProtocol,
    TransportError,
    _parse_retry_after,
    _UrllibSession,
)

DEFAULT_BASE_URL = "https://api-mainnet.helius-rpc.com"


class SolanaDataFetcher:
    """Fetch and normalize Solana transaction history via the Helius Enhanced API."""

    DATAFRAME_COLUMNS = DATAFRAME_COLUMNS

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 5,
        backoff_factor: float = 1.5,
        session: SessionProtocol | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
        parser_factory: Callable[[str], TransactionParser] | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("A non-empty Helius API key is required.")
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0.")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative.")
        if backoff_factor < 0:
            raise ValueError("backoff_factor cannot be negative.")

        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.session: SessionProtocol = session or _UrllibSession()
        self._sleep = sleep_func
        self._parser_factory = parser_factory or TransactionParser

    def __enter__(self) -> SolanaDataFetcher:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        close_method = getattr(self.session, "close", None)
        if callable(close_method):
            close_method()

    @staticmethod
    def validate_address(address: str) -> str:
        return validate_address(address)

    # ---------------------------------------------------------------- pagination

    def iter_transactions(
        self,
        wallet_address: str,
        *,
        before: str | None = None,
        after: str | None = None,
        commitment: str = "finalized",
        token_accounts: str = "balanceChanged",
        sort_order: str = "desc",
        transaction_type: str | None = None,
        source: str | None = None,
        max_pages: int | None = None,
        on_cursor_advance: Callable[[str], None] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield transactions one at a time, paginated lazily.

        `on_cursor_advance(next_cursor)` is invoked once per page, AFTER yielding
        the page's transactions and BEFORE the next HTTP request. Callers can
        persist `next_cursor` to resume later via `before=`.
        """
        normalized = validate_address(wallet_address)
        self._validate_enum("commitment", commitment, {"finalized", "confirmed"})
        self._validate_enum("sort_order", sort_order, {"desc", "asc"})
        self._validate_enum(
            "token_accounts",
            token_accounts,
            {"none", "balanceChanged", "all"},
        )
        if max_pages is not None and max_pages <= 0:
            raise ValueError("max_pages must be greater than 0 when provided.")
        if before and after:
            raise ValueError("Provide only one cursor: before or after.")

        cursor_key = "after-signature" if sort_order == "asc" else "before-signature"
        cursor = after if sort_order == "asc" else before
        if sort_order == "asc" and before:
            raise ValueError('Use "after" with sort_order="asc".')
        if sort_order == "desc" and after:
            raise ValueError('Use "before" with sort_order="desc".')

        base_params: dict[str, Any] = {
            "api-key": self.api_key,
            "commitment": commitment,
            "token-accounts": token_accounts,
            "sort-order": sort_order,
        }
        if transaction_type:
            base_params["type"] = transaction_type
        if source:
            base_params["source"] = source

        seen_signatures: set[str] = set()
        cursor_history: set[str] = set()
        pages_fetched = 0

        while True:
            page_params = dict(base_params)
            if cursor:
                page_params[cursor_key] = cursor

            batch = self._request_transaction_page(normalized, page_params)
            if not batch:
                return

            for transaction in batch:
                signature = str(transaction.get("signature") or "").strip()
                if signature and signature not in seen_signatures:
                    seen_signatures.add(signature)
                    yield dict(transaction)

            pages_fetched += 1
            if max_pages is not None and pages_fetched >= max_pages:
                return

            next_cursor = str(batch[-1].get("signature") or "").strip()
            if not next_cursor or next_cursor == cursor or next_cursor in cursor_history:
                return

            cursor_history.add(next_cursor)
            cursor = next_cursor
            if on_cursor_advance is not None:
                on_cursor_advance(next_cursor)

    def fetch_transaction_history(
        self,
        wallet_address: str,
        *,
        before: str | None = None,
        after: str | None = None,
        commitment: str = "finalized",
        token_accounts: str = "balanceChanged",
        sort_order: str = "desc",
        transaction_type: str | None = None,
        source: str | None = None,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch the full enhanced transaction history for a wallet."""
        return list(
            self.iter_transactions(
                wallet_address,
                before=before,
                after=after,
                commitment=commitment,
                token_accounts=token_accounts,
                sort_order=sort_order,
                transaction_type=transaction_type,
                source=source,
                max_pages=max_pages,
            )
        )

    def fetch_transactions_dataframe(
        self,
        wallet_address: str,
        *,
        before: str | None = None,
        after: str | None = None,
        commitment: str = "finalized",
        token_accounts: str = "balanceChanged",
        sort_order: str = "desc",
        transaction_type: str | None = None,
        source: str | None = None,
        max_pages: int | None = None,
    ) -> pd.DataFrame:
        """Fetch transaction history and return a normalized DataFrame."""
        transactions = self.fetch_transaction_history(
            wallet_address,
            before=before,
            after=after,
            commitment=commitment,
            token_accounts=token_accounts,
            sort_order=sort_order,
            transaction_type=transaction_type,
            source=source,
            max_pages=max_pages,
        )
        return self.transactions_to_dataframe(wallet_address, transactions)

    def transactions_to_dataframe(
        self,
        wallet_address: str,
        transactions: Iterable[Mapping[str, Any]],
    ) -> pd.DataFrame:
        """Convert raw Helius transactions to a normalized DataFrame."""
        parser = self._parser_factory(wallet_address)
        return to_dataframe(parser, transactions)

    # ----------------------------------------------- back-compat private alias

    def _build_transaction_row(
        self,
        wallet_address: str,
        transaction: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Deprecated: use `TransactionParser(wallet_address).parse(transaction)`."""
        return self._parser_factory(wallet_address).parse(transaction)

    # ----------------------------------------------------------- HTTP internals

    @staticmethod
    def _validate_enum(name: str, value: str, allowed: set[str]) -> None:
        if value not in allowed:
            allowed_values = ", ".join(sorted(allowed))
            raise ValueError(f"{name} must be one of: {allowed_values}.")

    def _request_transaction_page(
        self,
        wallet_address: str,
        params: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        url = f"{self.base_url}/v0/addresses/{wallet_address}/transactions"

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except TransportError as exc:
                if attempt >= self.max_retries:
                    raise HeliusAPIError(f"Network error while contacting Helius: {exc}") from exc
                self._sleep(self._compute_backoff_delay(attempt))
                continue

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise HeliusAPIError(
                        "Helius returned a non-JSON response for transaction history.",
                        status_code=200,
                    ) from exc
                if not isinstance(payload, list):
                    raise HeliusAPIError(
                        "Unexpected Helius response shape; expected a list of transactions.",
                        status_code=200,
                    )
                validated: list[dict[str, Any]] = []
                for index, item in enumerate(payload):
                    if not isinstance(item, Mapping):
                        raise HeliusAPIError(
                            f"Helius transaction at index {index} is not a JSON "
                            f"object (got {type(item).__name__}).",
                            status_code=200,
                        )
                    validated.append(dict(item))
                return validated

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise HeliusRateLimitError(
                        self._build_error_message(
                            response,
                            default="Helius rate limit exceeded after all retries.",
                        ),
                        status_code=429,
                    )
                self._sleep(self._compute_retry_delay(response, attempt))
                continue

            if 500 <= response.status_code < 600:
                if attempt >= self.max_retries:
                    raise HeliusAPIError(
                        self._build_error_message(
                            response,
                            default="Helius server error after all retries.",
                        ),
                        status_code=response.status_code,
                    )
                self._sleep(self._compute_retry_delay(response, attempt))
                continue

            error_message = self._build_error_message(
                response,
                default="Helius returned an error while fetching transaction history.",
            )
            lowered = error_message.lower()

            if response.status_code == 400 and "address" in lowered:
                raise InvalidSolanaAddressError(error_message)
            if response.status_code == 401:
                raise HeliusAuthenticationError(error_message, status_code=401)
            if response.status_code == 403:
                raise HeliusPermissionError(error_message, status_code=403)
            raise HeliusAPIError(error_message, status_code=response.status_code)

        raise HeliusAPIError("Helius request exhausted retries unexpectedly.")

    @staticmethod
    def _build_error_message(response: Any, *, default: str) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text.strip() if response.text else ""

        message: str | None = None
        if isinstance(payload, Mapping):
            message = payload.get("error") or payload.get("message") or payload.get("details")
            if isinstance(message, Mapping):
                message = str(
                    message.get("message")
                    or message.get("error")
                    or message.get("details")
                    or message
                )
        elif isinstance(payload, list):
            message = "Unexpected list payload returned for an error response."
        elif payload:
            message = str(payload)

        if message:
            return f"{default} (status={response.status_code}): {message}"
        return f"{default} (status={response.status_code})."

    def _compute_retry_delay(self, response: Any, attempt: int) -> float:
        delay = _parse_retry_after(response.headers.get("Retry-After"))
        if delay is not None:
            return delay
        return self._compute_backoff_delay(attempt)

    def _compute_backoff_delay(self, attempt: int) -> float:
        return self.backoff_factor * (2**attempt)
