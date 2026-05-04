# Fetcher Refactor — Module Decomposition, Parser Extraction, Hygiene

**Date:** 2026-05-04
**Status:** Approved
**Supersedes:** Pre-Sprint-2 tech-debt items in `2026-05-03-sentinel-core-design.md` §13

---

## 1. Context & Goal

`ai_accountant` ships as a single 770-line module (`solana_data_fetcher.py`) combining HTTP transport, retry/pagination, parsing, and DataFrame generation. A recent system audit identified high-impact issues:

- Token-flow aggregation uses truncated display labels as dictionary keys, creating a collision vector.
- Payload validation in `_request_transaction_page` leaks raw `TypeError` instead of `HeliusAPIError`.
- Failed-transaction detection relies on truthiness of `transactionError`, which misclassifies `{}` and `[]` as success.
- `fetch_transaction_history` buffers an entire wallet's history in memory before returning.
- HTTP `Retry-After` parsing only handles numeric seconds, ignoring the RFC-7231 HTTP-date variant.
- `audit_demo.py` slippage logic measures basis-vs-proceeds, which conflates underwater positions with execution slippage.
- `legal_grounding.py` conflict detector substring-matches `"NOT"` in human prose, producing false positives (e.g., MiCA).
- The Sentinel design (`2026-05-03-sentinel-core-design.md` §7, §13) reaches for `SolanaDataFetcher._build_transaction_row` — a private API.

The goal is to harden the existing parser and fetcher, decompose the single module into focused units, and extract `_build_transaction_row` into a public `TransactionParser` class so Sentinel has a clean, supported integration boundary. The public API surface at `ai_accountant.__init__` is preserved.

---

## 2. Scope

### In scope

- Decompose `solana_data_fetcher.py` into `exceptions`, `addresses`, `transport`, `parser`, `dataframe`, `client`.
- Extract `_build_transaction_row` and helpers into a new public `TransactionParser` class.
- Replace `(symbol, mint)` token-flow aggregation key with full mint string; eliminate truncated labels as dict keys.
- Add `iter_transactions` generator with `on_cursor_advance` callback for resumable pagination.
- Tighten `_request_transaction_page` payload validation; raise `HeliusAPIError` for shape failures.
- Tighten failed-transaction detection: explicit `transactionError is not None` check, not truthiness.
- Add `SessionProtocol`, `ResponseProtocol`, case-insensitive header wrapper, RFC-7231 HTTP-date `Retry-After` parsing.
- Fix `audit_demo.py` slippage to compare implied execution price to oracle reference (single-output swap only).
- Add `taxable_event: bool | None` to `LegalSource`; replace substring conflict detector with structured comparison.
- Project hygiene: `.gitignore`, replaced `README.md`, ruff config in `pyproject.toml`, removal of `bash.exe.stackdump`.
- Test coverage: one updated assertion in the existing test, plus new test files mirroring the module split.

### Explicitly out of scope

- Sentinel implementation (Sprint 1 still proceeds against the existing Sentinel spec; this refactor merely satisfies its pre-Sprint-2 tech-debt item).
- Pre-commit hooks, GitHub Actions CI.
- Comprehensive README API reference (front-door pointer only).
- Library-managed cursor persistence (callback hook is provided; storage is the caller's choice).
- Real-time quote provider integration in `audit_demo.py` (callout comment only).
- Threat-intel feeds for `KNOWN_BAD_PROGRAM` (still in Sentinel Sprint 1).

---

## 3. Package Layout

### New layout

```
src/ai_accountant/
    __init__.py              # re-exports — public API surface unchanged
    exceptions.py            # SolanaDataFetcherError hierarchy
    addresses.py             # validate_address, _decode_base58, BASE58 alphabet
    transport.py             # SessionProtocol, ResponseProtocol, _SimpleResponse,
                             # _UrllibSession, _CaseInsensitiveHeaders, TransportError,
                             # _parse_retry_after
    parser.py                # TransactionParser (public class) + helpers
    dataframe.py             # DATAFRAME_COLUMNS, to_dataframe(parser, transactions)
    client.py                # SolanaDataFetcher (HTTP orchestration + pagination + retry)
    solana_data_fetcher.py   # one-release re-export shim: from .client import *
```

### `__init__.py` re-exports

```python
from .client import SolanaDataFetcher
from .parser import TransactionParser
from .addresses import validate_address
from .dataframe import DATAFRAME_COLUMNS
from .exceptions import (
    SolanaDataFetcherError,
    InvalidSolanaAddressError,
    HeliusAPIError,
    HeliusAuthenticationError,
    HeliusPermissionError,
    HeliusRateLimitError,
)

__all__ = [
    "SolanaDataFetcher",
    "TransactionParser",
    "validate_address",
    "DATAFRAME_COLUMNS",
    "SolanaDataFetcherError",
    "InvalidSolanaAddressError",
    "HeliusAPIError",
    "HeliusAuthenticationError",
    "HeliusPermissionError",
    "HeliusRateLimitError",
]
```

### `solana_data_fetcher.py` shim

Kept for one release. Contents:

```python
"""Backwards-compat shim. Import from `ai_accountant` directly. This module
will be removed in a future release."""
from .client import *           # noqa: F401,F403
from .parser import *           # noqa: F401,F403
from .exceptions import *       # noqa: F401,F403
from .addresses import *        # noqa: F401,F403
from .dataframe import DATAFRAME_COLUMNS  # noqa: F401
```

The shim ensures any external code that imported from `ai_accountant.solana_data_fetcher` (rather than from `ai_accountant`) keeps working.

---

## 4. `exceptions.py`

Single source of truth for the exception hierarchy. No behavioral change.

```python
class SolanaDataFetcherError(Exception): ...
class InvalidSolanaAddressError(SolanaDataFetcherError): ...
class HeliusAPIError(SolanaDataFetcherError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
class HeliusAuthenticationError(HeliusAPIError): ...
class HeliusPermissionError(HeliusAPIError): ...
class HeliusRateLimitError(HeliusAPIError): ...
```

---

## 5. `addresses.py`

```python
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {c: i for i, c in enumerate(BASE58_ALPHABET)}

def validate_address(address: str) -> str:
    """Validate a Solana public key and return the stripped value."""
    # ... existing logic moved verbatim from SolanaDataFetcher ...

def _decode_base58(value: str) -> bytes:
    # ... existing logic moved verbatim ...
```

`SolanaDataFetcher.validate_address` becomes a static method that delegates here. Public consumers can also `from ai_accountant import validate_address` without instantiating a fetcher.

---

## 6. `transport.py`

### Protocols

```python
from typing import Any, Mapping, Protocol, runtime_checkable

class ResponseProtocol(Protocol):
    status_code: int
    text: str
    headers: Mapping[str, str]
    def json(self) -> Any: ...

class SessionProtocol(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> ResponseProtocol: ...
    def close(self) -> None: ...
```

Both are structural (`typing.Protocol`) — existing test doubles (`FakeSession`, `FakeResponse`) continue to work without inheriting.

### `_SimpleResponse` wraps headers in case-insensitive mapping

```python
class _CaseInsensitiveHeaders(Mapping[str, str]):
    def __init__(self, items: Iterable[tuple[str, str]]) -> None:
        self._store: dict[str, tuple[str, str]] = {
            k.lower(): (k, v) for k, v in items
        }
    def __getitem__(self, key: str) -> str: return self._store[key.lower()][1]
    def __iter__(self): return (orig for orig, _ in self._store.values())
    def __len__(self): return len(self._store)
    def get(self, key: str, default=None):
        entry = self._store.get(key.lower())
        return entry[1] if entry else default
    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._store
```

`_SimpleResponse.headers` is built from `_CaseInsensitiveHeaders(items.items())`. Iteration preserves original-case keys for human-readable debugging.

### `_parse_retry_after`

```python
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

def _parse_retry_after(
    value: str | None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> float | None:
    if not value:
        return None
    stripped = value.strip()
    try:
        n = float(stripped)
        return n if n >= 0 else None
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(stripped)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        delta = (target - now()).total_seconds()
        return max(delta, 0.0)
    except (TypeError, ValueError):
        return None
```

The injected `now=` keeps the HTTP-date branch unit-testable.

### `_UrllibSession`

Logic moved from `solana_data_fetcher.py` verbatim, except:
- `headers` parameter passed to `_SimpleResponse` is wrapped in `_CaseInsensitiveHeaders`.

### `TransportError`

Internal exception, raised on `URLError`. Caller code in `client.py` translates to `HeliusAPIError` after retry exhaustion.

---

## 7. `parser.py`

### Public class

```python
class TransactionParser:
    """
    Parse Helius Enhanced transactions into accounting-grade row dicts.

    Each instance is bound to a single wallet address (the audit perspective).
    All financial values in returned rows are `Decimal`. The output schema
    matches `dataframe.DATAFRAME_COLUMNS` exactly.
    """

    LAMPORTS_PER_SOL = Decimal("1000000000")
    NATIVE_KEY = "SOL"  # net_flow dict key for native SOL; tokens use full mint

    def __init__(self, wallet_address: str) -> None:
        self.wallet_address = validate_address(wallet_address)

    def parse(self, transaction: Mapping[str, Any]) -> dict[str, Any]:
        ...

    def parse_many(self, transactions: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [self.parse(tx) for tx in transactions]
```

### Internal helpers (private methods on the class)

Moved from `solana_data_fetcher.py` and renamed without the `_build_transaction_row` outer wrapper:

- `_parse_wallet_movements(transaction)` — same logic, but token-flow aggregation key is now `mint` (string). Native SOL flows are tracked in their own `native_in_sol` / `native_out_sol` accumulators (unchanged) and merged into the row at the end; they do not enter the `token_flows` dict.
- `_flow_details_to_rows(token_flows)` — emits records sorted by mint.
- `_format_flow_summary`, `_format_net_flow_summary`, `_format_timestamp`, `_decimal_to_string` — unchanged in logic.
- `_coerce_decimal(value)` — unchanged; raises `HeliusAPIError` on parse failure.
- `_resolve_token_symbol(transfer)` — unchanged.
- `_asset_label(symbol, mint)` — **changed**: returns `f"{symbol} ({mint})"` (full mint, no truncation) when `mint and mint != symbol`; otherwise returns `symbol`.

### Token-flow aggregation key — collision fix

```python
token_flows: dict[str, dict[str, Any]] = {}  # mint → flow record

# Per token transfer:
mint = token_transfer.get("mint")
if not mint:
    # Without a mint we cannot disambiguate. Skip the transfer to avoid
    # collisions with other tokens that share a symbol.
    continue
flow_entry = token_flows.setdefault(
    mint,
    {
        "mint": mint,
        "symbol": symbol,
        "in": Decimal("0"),
        "out": Decimal("0"),
    },
)
```

A token transfer with a missing `mint` field is dropped. This is a strict departure from current behavior (which would key by symbol alone), and is the right semantics: without a mint, the transfer cannot be attributed to a specific asset.

### `_flow_details_to_rows` output

```python
{
    "mint":   "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "symbol": "USDC",
    "label":  "USDC (EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v)",
    "in":     Decimal("0"),
    "out":    Decimal("25"),
    "net":    Decimal("-25"),
}
```

`label` is for human display only. Sorting is by `mint` ascending.

### `_build_net_flow` change

```python
def _build_net_flow(
    self,
    native_net_sol: Decimal,
    token_flow_details: Iterable[Mapping[str, Any]],
) -> dict[str, Decimal]:
    net_flow: dict[str, Decimal] = {self.NATIVE_KEY: native_net_sol}
    for flow in token_flow_details:
        net_flow[str(flow["mint"])] = Decimal(flow["net"])
    return net_flow
```

`net_flow` keys are: literal `"SOL"` for native, full mint string for tokens. The truncated label is no longer used as a key anywhere.

### `_format_net_flow_summary` — display layer

Iterates the flow details (not the `net_flow` dict) so it can render `label` as the human-friendly identifier:

```python
def _format_net_flow_summary(
    self,
    native_net_sol: Decimal,
    token_flow_details: Iterable[Mapping[str, Any]],
) -> str:
    parts: list[str] = []
    if native_net_sol != 0:
        parts.append(f"SOL: {self._decimal_to_string(native_net_sol, signed=True)}")
    for flow in token_flow_details:
        net = Decimal(flow["net"])
        if net == 0:
            continue
        parts.append(f"{flow['label']}: {self._decimal_to_string(net, signed=True)}")
    return ", ".join(parts) if parts else "No net movement"
```

### Failed-transaction detection — explicit None check

```python
raw_error = transaction.get("transactionError")
status = "failed" if raw_error is not None else "succeeded"
```

Helius signals success by either omitting the key or sending `null`. Anything else (including `{}` or `[]`) is a failure. The `transaction_error` column carries the raw value verbatim.

---

## 8. `dataframe.py`

```python
import pandas as pd

DATAFRAME_COLUMNS: list[str] = [
    "signature", "slot", "timestamp_unix", "timestamp",
    "transaction_type", "description", "source",
    "fee_lamports", "fee_sol", "fee_paid_by_wallet", "fee_payer", "status",
    "native_in_sol", "native_out_sol", "native_transfer_net_sol", "native_net_sol",
    "token_in_summary", "token_out_summary", "token_net_summary",
    "net_flow_summary", "net_flow", "token_flow_details",
    "movements_in", "movements_out",
    "raw_native_transfers", "raw_token_transfers", "transaction_error",
]

def to_dataframe(
    parser: "TransactionParser",
    transactions: Iterable[Mapping[str, Any]],
) -> pd.DataFrame:
    rows = parser.parse_many(transactions)
    if not rows:
        return pd.DataFrame(columns=DATAFRAME_COLUMNS)
    return pd.DataFrame(rows, columns=DATAFRAME_COLUMNS).reset_index(drop=True)
```

`SolanaDataFetcher.DATAFRAME_COLUMNS` becomes a class attribute that aliases this constant for back-compat.

---

## 9. `client.py`

### `SolanaDataFetcher`

Same constructor signature. `session` is typed `SessionProtocol | None`. New: optional `parser_factory: Callable[[str], TransactionParser] | None` (defaults to `TransactionParser`) — gives callers a hook to inject custom parser subclasses without modifying the fetcher.

### Public methods preserved

```python
def fetch_transaction_history(self, wallet_address: str, *, ...) -> list[dict[str, Any]]:
    return list(self.iter_transactions(wallet_address, **kwargs))

def fetch_transactions_dataframe(self, wallet_address: str, *, ...) -> pd.DataFrame:
    transactions = self.fetch_transaction_history(wallet_address, **kwargs)
    return self.transactions_to_dataframe(wallet_address, transactions)

def transactions_to_dataframe(self, wallet_address: str, transactions: ...) -> pd.DataFrame:
    parser = self._parser_factory(wallet_address)
    return to_dataframe(parser, transactions)

DATAFRAME_COLUMNS = DATAFRAME_COLUMNS  # alias for back-compat

@staticmethod
def validate_address(address: str) -> str:
    return validate_address(address)
```

### New: `iter_transactions`

```python
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
    """
    Yield transactions one at a time, paginated lazily.

    `on_cursor_advance(next_cursor)` is invoked once per page after the page's
    transactions have been yielded and a new cursor is selected, but BEFORE the
    next HTTP request goes out. Callers can persist the cursor for resume.
    """
```

Semantics:
- Pagination/dedup/cursor-history loop logic unchanged.
- `yield from` happens transaction-by-transaction within each page.
- `on_cursor_advance` is called with the new cursor *after* yielding the current page's contents and *before* fetching the next page.
- The callback is **not** called when pagination terminates (no further fetch is going to happen).
- `max_pages` semantics unchanged: counted by pages fetched.

Resumability example for callers:

```python
last = load_cursor()
for tx in fetcher.iter_transactions(
    wallet, before=last, on_cursor_advance=save_cursor,
):
    process(tx)
```

### Tightened `_request_transaction_page` payload validation

```python
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
                f"Helius transaction at index {index} is not a JSON object "
                f"(got {type(item).__name__}).",
                status_code=200,
            )
        validated.append(dict(item))
    return validated
```

### `_compute_retry_delay` uses `_parse_retry_after`

```python
def _compute_retry_delay(self, response: ResponseProtocol, attempt: int) -> float:
    delay = _parse_retry_after(response.headers.get("Retry-After"))
    if delay is not None:
        return delay
    return self._compute_backoff_delay(attempt)
```

### Private alias for Sentinel back-compat

The Sentinel design's normalizer reaches for `SolanaDataFetcher._build_transaction_row`. Preserve it as a private alias on the class, delegating to the parser:

```python
def _build_transaction_row(
    self,
    wallet_address: str,
    transaction: Mapping[str, Any],
) -> dict[str, Any]:
    """Deprecated: use `TransactionParser(wallet_address).parse(transaction)`."""
    return self._parser_factory(wallet_address).parse(transaction)
```

A one-line note in `2026-05-03-sentinel-core-design.md` records that the pre-Sprint-2 task is complete and Sentinel should switch to `TransactionParser` when it lands.

---

## 10. Examples

### `audit_demo.py` — slippage fix

Replace the existing block in `run_pipeline` (the `slip = (basis_usd - proceeds_usd) / basis_usd` branch) with implied-execution-price-vs-oracle:

```python
# ILLUSTRATIVE — production needs a real quote provider (Jupiter, Birdeye)
# capturing the *expected* fill at swap-submit time. Comparing to a daily
# oracle close still confuses slippage with intra-day price drift, but it
# replaces the conceptually wrong basis-vs-proceeds check.
if (
    len(row["movements_in"]) == 1
    and len(row["movements_out"]) >= 1
    and proceeds_usd > 0
):
    out_units = Decimal(row["movements_in"][0]["amount"])
    out_symbol = row["movements_in"][0]["symbol"]
    oracle_px = price_usd(out_symbol, date)
    in_value_usd = Decimal("0")
    for m in row["movements_out"]:
        in_px = price_usd(m["symbol"], date)
        if in_px is None:
            in_value_usd = Decimal("0")
            break
        in_value_usd += Decimal(m["amount"]) * in_px
    if (
        oracle_px is not None
        and oracle_px > 0
        and out_units > 0
        and in_value_usd > 0
    ):
        implied_px = in_value_usd / out_units
        slip_pct = (oracle_px - implied_px) / oracle_px
        if slip_pct > Decimal("0.05"):
            findings.append({
                "sig": sig,
                "issue": "Possible high slippage (implied execution price below oracle reference)",
                "implied_slippage_pct": f"{(slip_pct * 100).quantize(TWO_PLACES)}%",
            })
```

The `len(...) == 1` guard scopes the check to single-output swaps so multi-leg swaps are skipped without false alarm.

### `legal_grounding.py` — `taxable_event` field + structured conflict detector

Add to `LegalSource`:

```python
@dataclass(frozen=True)
class LegalSource:
    # ... existing fields ...
    taxable_event: bool | None = None  # True/False = explicit; None = silent
```

Each existing corpus entry receives an explicit value:

| ID | `taxable_event` |
|---|---|
| `US-NOTICE-2014-21` | `True` |
| `US-REV-RUL-2019-24` | `True` |
| `US-REV-RUL-2023-14` | `True` |
| `US-IRC-1091` | `True` |
| `US-PROPOSAL-1091-DIGITAL-EXT` | `True` |
| `US-FORM-1099-DA` | `True` |
| `EU-MICA-2023-1114` | `None` |
| `INTL-OECD-CARF-2022` | `None` |
| `PL-PIT-ART-30B-1A` | `False` |
| `US-INTERP-INTERNAL-TRANSFER` | `False` |
| `US-INTERP-FAILED-TX-FEE` | `None` |
| `US-INTERP-MISSING-BASIS` | `None` |

The PL entry is `False` because its `holding_summary` says crypto-to-crypto swaps are not a taxable event under current Polish statute. The US-FED entry for swaps is `True`. The two together correctly fire `[CONFLICT]`.

Replace the substring detector:

```python
for s_sec in secondary_sources:
    for s_pri in primary_sources:
        if s_pri.jurisdiction == s_sec.jurisdiction:
            continue
        if s_pri.taxable_event is None or s_sec.taxable_event is None:
            continue
        if s_pri.taxable_event != s_sec.taxable_event:
            pri_label = "taxable" if s_pri.taxable_event else "non-taxable"
            sec_label = "taxable" if s_sec.taxable_event else "non-taxable"
            lines += [
                "",
                (f"    [CONFLICT] {s_pri.jurisdiction} treats this category "
                 f"as {pri_label}; {s_sec.jurisdiction} treats it as "
                 f"{sec_label}. Resolution depends on taxpayer's tax "
                 f"residence and treaty position."),
            ]
            break
```

Module-level docstring updated to clarify: `holding_summary` is paraphrase (display only); `taxable_event` is the structured legal signal; `verbatim_excerpt` is the only authoritative text.

---

## 11. Tests

### Updated existing test

`tests/test_solana_data_fetcher.py::SolanaDataFetcherTests::test_transactions_to_dataframe_parses_native_token_flows_and_fees`

Updates:

```python
self.assertEqual(
    row["token_flow_details"],
    [
        {
            "symbol": "BONK",
            "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW",
            "label": "BONK (DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW)",
            "in":  Decimal("1000"),
            "out": Decimal("0"),
            "net": Decimal("1000"),
        },
        {
            "symbol": "USDC",
            "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "label": "USDC (EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v)",
            "in":  Decimal("0"),
            "out": Decimal("25"),
            "net": Decimal("-25"),
        },
    ],
)

self.assertEqual(row["net_flow"]["SOL"], Decimal("-0.150005"))
self.assertEqual(
    row["net_flow"]["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"],
    Decimal("-25"),
)
self.assertEqual(
    row["net_flow"]["DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW"],
    Decimal("1000"),
)
```

Sorting is by mint ascending. `DezX...` sorts before `EPjF...`, so BONK comes first.

### New test files

`tests/test_addresses.py`
- `test_validate_address_accepts_valid_base58`
- `test_validate_address_rejects_wrong_length`
- `test_validate_address_rejects_non_base58_characters`
- `test_validate_address_rejects_non_string`
- `test_validate_address_rejects_empty_string`

`tests/test_transport.py`
- `test_parse_retry_after_numeric_seconds`
- `test_parse_retry_after_negative_returns_none`
- `test_parse_retry_after_garbage_returns_none`
- `test_parse_retry_after_http_date` (with injected `now=`)
- `test_parse_retry_after_http_date_in_past_returns_zero`
- `test_parse_retry_after_none_or_empty_returns_none`
- `test_case_insensitive_headers_lookup_lowercase`
- `test_case_insensitive_headers_lookup_mixed_case`
- `test_case_insensitive_headers_iteration_preserves_original_case`
- `test_case_insensitive_headers_membership`

`tests/test_parser.py`
- `test_parser_is_publicly_importable_from_ai_accountant`
- `test_parse_single_transaction_matches_dataframe_row_schema`
- `test_parse_many_returns_list_in_order`
- `test_token_collision_aggregated_by_mint_not_symbol` — two distinct mints sharing `tokenSymbol = "USDC"` produce two flow entries
- `test_token_transfer_without_mint_is_skipped`
- `test_failed_status_when_transaction_error_is_dict`
- `test_failed_status_when_transaction_error_is_empty_dict`
- `test_failed_status_when_transaction_error_is_empty_list`
- `test_succeeded_status_when_transaction_error_key_missing`
- `test_succeeded_status_when_transaction_error_key_explicitly_null`
- `test_self_transfers_ignored`
- `test_fee_subtracted_only_when_wallet_pays`
- `test_label_is_full_mint_not_truncated`
- `test_net_flow_keyed_by_mint_for_tokens_and_sol_for_native`
- `test_parser_validates_wallet_address_at_construction`

`tests/test_client.py` (renamed from `test_solana_data_fetcher.py`; existing tests preserved)
- existing: `test_transactions_to_dataframe_parses_native_token_flows_and_fees` (updated)
- existing: `test_fetch_transaction_history_uses_before_signature_pagination`
- existing: `test_fetch_transaction_history_retries_after_rate_limit`
- existing: `test_fetch_transaction_history_raises_rate_limit_after_retry_exhaustion`
- existing: `test_invalid_address_fails_fast_without_http_request`
- new: `test_iter_transactions_yields_one_at_a_time`
- new: `test_iter_transactions_invokes_cursor_callback_per_page`
- new: `test_iter_transactions_callback_not_invoked_after_terminal_page`
- new: `test_fetch_transaction_history_returns_concrete_list`
- new: `test_payload_validation_non_object_item_raises_helius_api_error`
- new: `test_payload_validation_non_list_top_level_raises_helius_api_error`
- new: `test_retry_after_http_date_header_respected`
- new: `test_retry_after_lowercase_header_respected` (case-insensitive lookup)

`tests/test_dataframe.py`
- `test_to_dataframe_empty_returns_empty_with_schema_columns`
- `test_to_dataframe_columns_match_constant_in_order`
- `test_dataframe_columns_constant_publicly_importable`

The shim `solana_data_fetcher.py` remains importable; one assertion in `test_addresses.py` (or a dedicated `test_compat.py` if needed) verifies `from ai_accountant.solana_data_fetcher import SolanaDataFetcher` continues to work for one release.

---

## 12. Hygiene

### `.gitignore`

```
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
.env
dist/
build/
*.egg-info/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/
*.stackdump
.idea/
.vscode/
```

### `pyproject.toml` additions

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.6.0",
]

[tool.ruff]
line-length = 100
target-version = "py310"
src = ["src", "tests", "examples"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
```

### `README.md`

Replaced with a ~40-line minimal pointer:

- One-paragraph description.
- Install snippet (`pip install -e ".[dev]"`).
- Eight-line code example using `SolanaDataFetcher` + `TransactionParser`.
- Pointer to `examples/` and `docs/superpowers/specs/` for deeper reading.
- Pointer to `pytest` / `ruff` commands for contributors.

No API reference duplication. Docstrings carry that.

### Files removed

- `bash.exe.stackdump` — Cygwin crash artifact, not source.

---

## 13. Sentinel Spec Annotation

Append a one-line note to `docs/superpowers/specs/2026-05-03-sentinel-core-design.md` near the §13 tech-debt table:

> **Update 2026-05-04:** Pre-Sprint-2 task complete. Use
> `TransactionParser(wallet_address).parse(raw_tx)` from `ai_accountant`.
> The private `SolanaDataFetcher._build_transaction_row` alias is preserved
> for one release; new code should not use it.

The Sentinel implementation plan body is **not** edited — it is an executable artifact and the alias is still in place for one release.

---

## 14. Migration & Compatibility Matrix

| Caller import | Today | After refactor |
|---|---|---|
| `from ai_accountant import SolanaDataFetcher` | works | works |
| `from ai_accountant import TransactionParser` | n/a | new, supported |
| `from ai_accountant import validate_address` | n/a | new, supported |
| `from ai_accountant import DATAFRAME_COLUMNS` | n/a | new, supported |
| `from ai_accountant.solana_data_fetcher import SolanaDataFetcher` | works | works (shim, one release) |
| `SolanaDataFetcher.DATAFRAME_COLUMNS` | works | works (class attr alias) |
| `SolanaDataFetcher.validate_address(addr)` | works | works (delegates) |
| `SolanaDataFetcher._build_transaction_row(wallet, tx)` | works | works (delegates to TransactionParser; deprecated) |
| `fetcher.fetch_transaction_history(wallet)` | returns list | returns list (now via `list(self.iter_transactions(...))`) |
| `fetcher.iter_transactions(wallet)` | n/a | new, generator |
| `row["net_flow"]["USDC (EPjF...Dt1v)"]` | works | **breaks** — keys are now mints |
| `row["token_flow_details"][0]["label"]` | `"USDC (EPjF...Dt1v)"` | `"USDC (EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v)"` (no truncation) |

The two **breaks** are intentional and were the audit's flagged collision risk. Existing callers of `transactions_to_dataframe` who introspect `net_flow` or `token_flow_details` (e.g., `audit_demo.py` does not) need to switch to mint-keyed lookup.

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| Token transfers without `mint` are silently dropped | Documented in `TransactionParser` docstring; covered by `test_token_transfer_without_mint_is_skipped`; matches the audit's "mint as canonical identity" position. |
| Sentinel currently calls `_build_transaction_row` directly | Private alias preserved on `SolanaDataFetcher` for one release; spec annotation directs Sentinel team to switch. |
| External callers of `ai_accountant.solana_data_fetcher` submodule | Shim preserves submodule import path for one release; deletion is a separate future change. |
| Ruff added as dev dep may surface lint failures across legacy code | `select` list is conservative (E/F/W/I/B/UP/SIM); any unfixable warnings can be `# noqa`-ed inline rather than blocking the refactor. |
| HTTP-date `Retry-After` requires `now` injection in tests to be deterministic | `_parse_retry_after(now=...)` parameter is explicitly designed for this. |

---

## 16. Summary

The refactor:
1. Splits one 770-line module into six focused modules without changing the `ai_accountant` public API.
2. Promotes `_build_transaction_row` to a public `TransactionParser` class, satisfying Sentinel's pre-Sprint-2 tech-debt item.
3. Replaces truncated-label collision-prone dict keys with full mint strings; labels remain for display only.
4. Adds `iter_transactions` with a cursor-advance callback for memory-efficient streaming and resumable pagination.
5. Tightens payload validation, failed-transaction detection, and `Retry-After` header parsing.
6. Replaces the buggy slippage check in `audit_demo.py` and the false-positive substring conflict detector in `legal_grounding.py` with structured equivalents.
7. Adds project hygiene (`.gitignore`, README rewrite, ruff config) and removes the Cygwin crash artifact.
