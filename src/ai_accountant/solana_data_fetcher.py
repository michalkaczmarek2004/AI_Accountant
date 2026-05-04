from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .exceptions import (
    HeliusAPIError,
    HeliusAuthenticationError,
    HeliusPermissionError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
    SolanaDataFetcherError,
)


LAMPORTS_PER_SOL = Decimal("1000000000")
DEFAULT_BASE_URL = "https://api-mainnet.helius-rpc.com"
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {character: index for index, character in enumerate(BASE58_ALPHABET)}


class TransportError(Exception):
    """Raised by the internal HTTP transport when a request cannot be completed."""


class _SimpleResponse:
    def __init__(
        self,
        status_code: int,
        body: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = body
        self.headers = dict(headers or {})

    def json(self) -> Any:
        return json.loads(self.text)


class _UrllibSession:
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> _SimpleResponse:
        query = urlencode(params or {}, doseq=True)
        full_url = f"{url}?{query}" if query else url
        request = Request(
            full_url,
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                return _SimpleResponse(
                    status_code=response.getcode(),
                    body=body,
                    headers=dict(response.headers.items()),
                )
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return _SimpleResponse(
                status_code=exc.code,
                body=body,
                headers=dict(exc.headers.items()) if exc.headers else {},
            )
        except URLError as exc:
            raise TransportError(str(exc)) from exc

    def close(self) -> None:
        return None


class SolanaDataFetcher:
    """
    Fetch and normalize Solana transaction history via the Helius Enhanced API.

    The fetcher uses the `/v0/addresses/{address}/transactions` endpoint, paginates
    backwards through history with Helius' `before-signature` cursor, and returns a
    transaction-level Pandas DataFrame suitable for audit and tax workflows.
    """

    DATAFRAME_COLUMNS = [
        "signature",
        "slot",
        "timestamp_unix",
        "timestamp",
        "transaction_type",
        "description",
        "source",
        "fee_lamports",
        "fee_sol",
        "fee_paid_by_wallet",
        "fee_payer",
        "status",
        "native_in_sol",
        "native_out_sol",
        "native_transfer_net_sol",
        "native_net_sol",
        "token_in_summary",
        "token_out_summary",
        "token_net_summary",
        "net_flow_summary",
        "net_flow",
        "token_flow_details",
        "movements_in",
        "movements_out",
        "raw_native_transfers",
        "raw_token_transfers",
        "transaction_error",
    ]

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 5,
        backoff_factor: float = 1.5,
        session: Any | None = None,
        sleep_func: Callable[[float], None] = time.sleep,
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
        self.session = session or _UrllibSession()
        self._sleep = sleep_func

    def __enter__(self) -> "SolanaDataFetcher":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP session."""
        close_method = getattr(self.session, "close", None)
        if callable(close_method):
            close_method()

    @staticmethod
    def validate_address(address: str) -> str:
        """Validate a Solana public key and return the stripped value."""
        if not isinstance(address, str):
            raise InvalidSolanaAddressError("Wallet address must be a string.")

        normalized_address = address.strip()
        if not normalized_address:
            raise InvalidSolanaAddressError("Wallet address cannot be empty.")

        decoded = SolanaDataFetcher._decode_base58(normalized_address)
        if len(decoded) != 32:
            raise InvalidSolanaAddressError(
                "Wallet address must decode to a 32-byte Solana public key."
            )

        return normalized_address

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
        """
        Fetch the full enhanced transaction history for a wallet.

        Parameters
        ----------
        wallet_address:
            Solana public key for the wallet being audited.
        before:
            Cursor used to backfill older history while `sort_order="desc"`. This
            is sent to Helius as the `before-signature` query parameter.
        after:
            Cursor used for chronological pagination while `sort_order="asc"`. This
            is sent to Helius as the `after-signature` query parameter.
        token_accounts:
            Defaults to `balanceChanged` so token-account activity owned by the
            wallet is included in the audit trail.
        """
        normalized_address = self.validate_address(wallet_address)
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

        request_params: dict[str, Any] = {
            "api-key": self.api_key,
            "commitment": commitment,
            "token-accounts": token_accounts,
            "sort-order": sort_order,
        }
        if transaction_type:
            request_params["type"] = transaction_type
        if source:
            request_params["source"] = source

        transactions: list[dict[str, Any]] = []
        seen_signatures: set[str] = set()
        cursor_history: set[str] = set()
        pages_fetched = 0

        while True:
            page_params = dict(request_params)
            if cursor:
                page_params[cursor_key] = cursor

            batch = self._request_transaction_page(normalized_address, page_params)
            if not batch:
                break

            for transaction in batch:
                signature = str(transaction.get("signature") or "").strip()
                if signature and signature not in seen_signatures:
                    seen_signatures.add(signature)
                    transactions.append(dict(transaction))

            pages_fetched += 1
            if max_pages is not None and pages_fetched >= max_pages:
                break

            next_cursor = str(batch[-1].get("signature") or "").strip()
            if not next_cursor or next_cursor == cursor or next_cursor in cursor_history:
                break

            cursor_history.add(next_cursor)
            cursor = next_cursor

        return transactions

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
        """Fetch transaction history and return a normalized transaction DataFrame."""
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
        """
        Convert raw Helius enhanced transactions into a structured DataFrame.

        The DataFrame keeps financial values as `Decimal` objects to preserve
        accounting precision when summing fees, native flows, and token flows.
        """
        normalized_address = self.validate_address(wallet_address)
        rows = [
            self._build_transaction_row(normalized_address, transaction)
            for transaction in transactions
        ]
        if not rows:
            return pd.DataFrame(columns=self.DATAFRAME_COLUMNS)

        frame = pd.DataFrame(rows, columns=self.DATAFRAME_COLUMNS)
        return frame.reset_index(drop=True)

    @staticmethod
    def _decode_base58(value: str) -> bytes:
        number = 0
        for character in value:
            if character not in BASE58_INDEX:
                raise InvalidSolanaAddressError(
                    f"Wallet address contains invalid Base58 character: {character!r}."
                )
            number = (number * 58) + BASE58_INDEX[character]

        decoded = b""
        if number:
            decoded = number.to_bytes((number.bit_length() + 7) // 8, "big")

        leading_zeroes = len(value) - len(value.lstrip("1"))
        return (b"\x00" * leading_zeroes) + decoded

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
                    raise HeliusAPIError(
                        f"Network error while contacting Helius: {exc}"
                    ) from exc
                self._sleep(self._compute_backoff_delay(attempt))
                continue

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise HeliusAPIError(
                        "Helius returned a non-JSON response for transaction history."
                    ) from exc
                if not isinstance(payload, list):
                    raise HeliusAPIError(
                        "Unexpected Helius response shape; expected a list of transactions."
                    )
                return [dict(item) for item in payload]

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
            lowered_message = error_message.lower()

            if response.status_code == 400 and "address" in lowered_message:
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
            payload = response.text.strip()

        message: str | None = None
        if isinstance(payload, Mapping):
            message = (
                payload.get("error")
                or payload.get("message")
                or payload.get("details")
            )
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
        retry_after_header = response.headers.get("Retry-After")
        if retry_after_header:
            try:
                retry_after = float(retry_after_header)
                if retry_after >= 0:
                    return retry_after
            except ValueError:
                pass
        return self._compute_backoff_delay(attempt)

    def _compute_backoff_delay(self, attempt: int) -> float:
        return self.backoff_factor * (2 ** attempt)

    def _build_transaction_row(
        self,
        wallet_address: str,
        transaction: Mapping[str, Any],
    ) -> dict[str, Any]:
        parsed_movements = self._parse_wallet_movements(wallet_address, transaction)
        fee_lamports = int(transaction.get("fee") or 0)
        fee_sol = Decimal(fee_lamports) / LAMPORTS_PER_SOL
        fee_payer = str(transaction.get("feePayer") or "")
        fee_paid_by_wallet = fee_payer == wallet_address

        native_in_sol = parsed_movements["native_in_sol"]
        native_out_sol = parsed_movements["native_out_sol"]
        native_transfer_net_sol = native_in_sol - native_out_sol
        native_net_sol = native_transfer_net_sol - (
            fee_sol if fee_paid_by_wallet else Decimal("0")
        )

        token_flow_details = self._flow_details_to_rows(parsed_movements["token_flows"])
        token_in_summary = self._format_flow_summary(token_flow_details, key="in")
        token_out_summary = self._format_flow_summary(token_flow_details, key="out")
        token_net_summary = self._format_flow_summary(
            token_flow_details,
            key="net",
            signed=True,
        )

        net_flow = self._build_net_flow(native_net_sol, token_flow_details)
        timestamp_unix = transaction.get("timestamp")
        transaction_error = transaction.get("transactionError")

        return {
            "signature": transaction.get("signature"),
            "slot": transaction.get("slot"),
            "timestamp_unix": timestamp_unix,
            "timestamp": self._format_timestamp(timestamp_unix),
            "transaction_type": transaction.get("type"),
            "description": transaction.get("description"),
            "source": transaction.get("source"),
            "fee_lamports": fee_lamports,
            "fee_sol": fee_sol,
            "fee_paid_by_wallet": fee_paid_by_wallet,
            "fee_payer": fee_payer or None,
            "status": "failed" if transaction_error else "succeeded",
            "native_in_sol": native_in_sol,
            "native_out_sol": native_out_sol,
            "native_transfer_net_sol": native_transfer_net_sol,
            "native_net_sol": native_net_sol,
            "token_in_summary": token_in_summary,
            "token_out_summary": token_out_summary,
            "token_net_summary": token_net_summary,
            "net_flow_summary": self._format_net_flow_summary(net_flow),
            "net_flow": net_flow,
            "token_flow_details": token_flow_details,
            "movements_in": parsed_movements["movements_in"],
            "movements_out": parsed_movements["movements_out"],
            "raw_native_transfers": list(transaction.get("nativeTransfers") or []),
            "raw_token_transfers": list(transaction.get("tokenTransfers") or []),
            "transaction_error": transaction_error,
        }

    def _parse_wallet_movements(
        self,
        wallet_address: str,
        transaction: Mapping[str, Any],
    ) -> dict[str, Any]:
        native_in_sol = Decimal("0")
        native_out_sol = Decimal("0")
        token_flows: dict[tuple[str, str | None], dict[str, Any]] = {}
        movements_in: list[dict[str, Any]] = []
        movements_out: list[dict[str, Any]] = []

        for native_transfer in transaction.get("nativeTransfers") or []:
            from_account = str(native_transfer.get("fromUserAccount") or "")
            to_account = str(native_transfer.get("toUserAccount") or "")
            if from_account == wallet_address and to_account == wallet_address:
                continue

            amount_lamports = self._coerce_decimal(native_transfer.get("amount"))
            if amount_lamports <= 0:
                continue

            amount_sol = amount_lamports / LAMPORTS_PER_SOL
            base_record = {
                "asset_type": "native",
                "symbol": "SOL",
                "mint": None,
                "amount": amount_sol,
                "amount_lamports": int(amount_lamports),
                "from_user_account": from_account or None,
                "to_user_account": to_account or None,
            }

            if to_account == wallet_address:
                native_in_sol += amount_sol
                movements_in.append(
                    {
                        **base_record,
                        "direction": "in",
                        "counterparty": from_account or None,
                    }
                )
            if from_account == wallet_address:
                native_out_sol += amount_sol
                movements_out.append(
                    {
                        **base_record,
                        "direction": "out",
                        "counterparty": to_account or None,
                    }
                )

        for token_transfer in transaction.get("tokenTransfers") or []:
            from_account = str(token_transfer.get("fromUserAccount") or "")
            to_account = str(token_transfer.get("toUserAccount") or "")
            if from_account == wallet_address and to_account == wallet_address:
                continue

            amount = self._coerce_decimal(token_transfer.get("tokenAmount"))
            if amount <= 0:
                continue

            mint = token_transfer.get("mint")
            symbol = self._resolve_token_symbol(token_transfer)
            flow_key = (symbol, mint)
            flow_entry = token_flows.setdefault(
                flow_key,
                {
                    "symbol": symbol,
                    "mint": mint,
                    "in": Decimal("0"),
                    "out": Decimal("0"),
                },
            )

            base_record = {
                "asset_type": "token",
                "symbol": symbol,
                "mint": mint,
                "amount": amount,
                "from_user_account": from_account or None,
                "to_user_account": to_account or None,
                "from_token_account": token_transfer.get("fromTokenAccount"),
                "to_token_account": token_transfer.get("toTokenAccount"),
            }

            if to_account == wallet_address:
                flow_entry["in"] += amount
                movements_in.append(
                    {
                        **base_record,
                        "direction": "in",
                        "counterparty": from_account or None,
                    }
                )
            if from_account == wallet_address:
                flow_entry["out"] += amount
                movements_out.append(
                    {
                        **base_record,
                        "direction": "out",
                        "counterparty": to_account or None,
                    }
                )

        return {
            "native_in_sol": native_in_sol,
            "native_out_sol": native_out_sol,
            "token_flows": token_flows,
            "movements_in": movements_in,
            "movements_out": movements_out,
        }

    @staticmethod
    def _coerce_decimal(value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise HeliusAPIError(f"Unable to parse numeric value from {value!r}.") from exc

    @staticmethod
    def _resolve_token_symbol(token_transfer: Mapping[str, Any]) -> str:
        candidates = (
            token_transfer.get("tokenSymbol"),
            token_transfer.get("symbol"),
            token_transfer.get("currencySymbol"),
            token_transfer.get("name"),
            token_transfer.get("mint"),
        )
        for candidate in candidates:
            if candidate:
                return str(candidate)
        return "UNKNOWN_TOKEN"

    def _flow_details_to_rows(
        self,
        token_flows: Mapping[tuple[str, str | None], Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for _, flow in sorted(
            token_flows.items(),
            key=lambda item: (str(item[0][0]), str(item[0][1] or "")),
        ):
            inflow = Decimal(flow["in"])
            outflow = Decimal(flow["out"])
            rows.append(
                {
                    "symbol": flow["symbol"],
                    "mint": flow["mint"],
                    "label": self._asset_label(flow["symbol"], flow["mint"]),
                    "in": inflow,
                    "out": outflow,
                    "net": inflow - outflow,
                }
            )
        return rows

    @staticmethod
    def _asset_label(symbol: str, mint: str | None) -> str:
        if mint and mint != symbol:
            return f"{symbol} ({mint[:4]}...{mint[-4:]})"
        return symbol

    def _build_net_flow(
        self,
        native_net_sol: Decimal,
        token_flow_details: Iterable[Mapping[str, Any]],
    ) -> dict[str, Decimal]:
        net_flow = {"SOL": native_net_sol}
        for flow in token_flow_details:
            net_flow[str(flow["label"])] = Decimal(flow["net"])
        return net_flow

    def _format_flow_summary(
        self,
        token_flow_details: Iterable[Mapping[str, Any]],
        *,
        key: str,
        signed: bool = False,
    ) -> str:
        parts: list[str] = []
        for flow in token_flow_details:
            amount = Decimal(flow[key])
            if amount == 0:
                continue
            rendered_amount = self._decimal_to_string(amount, signed=signed)
            parts.append(f"{flow['label']}: {rendered_amount}")
        return ", ".join(parts) if parts else "None"

    def _format_net_flow_summary(self, net_flow: Mapping[str, Decimal]) -> str:
        parts: list[str] = []
        for asset_label, amount in net_flow.items():
            if amount == 0:
                continue
            parts.append(f"{asset_label}: {self._decimal_to_string(amount, signed=True)}")
        return ", ".join(parts) if parts else "No net movement"

    @staticmethod
    def _format_timestamp(timestamp_unix: Any) -> str | None:
        if timestamp_unix in (None, ""):
            return None
        try:
            return datetime.fromtimestamp(
                int(timestamp_unix),
                tz=timezone.utc,
            ).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, TypeError, ValueError):
            return None

    @staticmethod
    def _decimal_to_string(value: Decimal, *, signed: bool = False) -> str:
        normalized = value.normalize()
        rendered = format(normalized, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        if rendered in {"", "-0"}:
            rendered = "0"
        if signed and not rendered.startswith("-") and rendered != "0":
            rendered = f"+{rendered}"
        return rendered
