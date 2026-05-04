# Fetcher Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose `solana_data_fetcher.py` into focused modules, extract `_build_transaction_row` into a public `TransactionParser` class, fix the token-flow collision vector, add a streaming iterator with cursor callback, tighten payload/header parsing, fix the demo's slippage logic and the legal layer's substring conflict detector, and add project hygiene.

**Architecture:** Six new modules under `src/ai_accountant/` (`exceptions`, `addresses`, `transport`, `parser`, `dataframe`, `client`) replace the single 770-line file. `solana_data_fetcher.py` becomes a one-release re-export shim. Public API at `ai_accountant.__init__` is preserved and gains `TransactionParser`, `validate_address`, `DATAFRAME_COLUMNS`. Token-flow aggregation key changes from `(symbol, mint)` tuple to full `mint` string; truncated labels are removed.

**Tech Stack:** Python ≥ 3.10, stdlib only (`urllib`, `email.utils`, `decimal`, `typing.Protocol`), pandas (existing), pytest (existing), ruff (new dev dep).

**Note on commits:** The project is not currently under git. Task 0 initializes a repo so the per-task commits in subsequent tasks work. If the user runs this plan in an already-initialized repo, skip Task 0.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `.gitignore` | Create | Standard Python ignores + ruff/pytest caches + `*.stackdump` |
| `README.md` | Replace | ~40-line minimal: install, quick example, pointers |
| `pyproject.toml` | Modify | Add `ruff>=0.6.0` to `dev`; add `[tool.ruff]` config block |
| `bash.exe.stackdump` | Delete | Cygwin crash artifact |
| `src/ai_accountant/exceptions.py` | Create | Exception hierarchy (single source of truth) |
| `src/ai_accountant/addresses.py` | Create | `validate_address`, `_decode_base58`, BASE58 alphabet |
| `src/ai_accountant/transport.py` | Create | `SessionProtocol`, `ResponseProtocol`, `_SimpleResponse`, `_UrllibSession`, `_CaseInsensitiveHeaders`, `TransportError`, `_parse_retry_after` |
| `src/ai_accountant/parser.py` | Create | `TransactionParser` class + private helpers; mint-keyed aggregation; full-mint labels; explicit-None failure check |
| `src/ai_accountant/dataframe.py` | Create | `DATAFRAME_COLUMNS` constant + `to_dataframe(parser, transactions)` |
| `src/ai_accountant/client.py` | Create | `SolanaDataFetcher` orchestrator, `iter_transactions` generator with `on_cursor_advance`, tightened payload validation |
| `src/ai_accountant/solana_data_fetcher.py` | Replace | One-release re-export shim |
| `src/ai_accountant/__init__.py` | Replace | Re-export new public surface |
| `tests/test_solana_data_fetcher.py` | Rename → `tests/test_client.py`, modify | Update mint-keyed assertions; add iter/callback/payload/HTTP-date tests |
| `tests/test_addresses.py` | Create | Address validation tests |
| `tests/test_transport.py` | Create | `_parse_retry_after` + `_CaseInsensitiveHeaders` tests |
| `tests/test_parser.py` | Create | `TransactionParser` tests including collision, missing mint, status semantics |
| `tests/test_dataframe.py` | Create | DataFrame schema tests |
| `tests/test_compat_shim.py` | Create | One assertion that `from ai_accountant.solana_data_fetcher import ...` still works |
| `examples/audit_demo.py` | Modify | Replace slippage check with implied-price-vs-oracle |
| `examples/legal_grounding.py` | Modify | Add `taxable_event: bool \| None`; replace substring conflict detector |
| `docs/superpowers/specs/2026-05-03-sentinel-core-design.md` | Modify | Append one-line note to §13 about the pre-Sprint-2 task being complete |

---

## Task 0: Initialize git repository (skip if already initialized)

**Files:**
- Modify: working tree

- [ ] **Step 1: Check whether git is initialized**

Run: `git -C "C:/Users/USER/Desktop/Praca/Solana/AI_Accountant" rev-parse --is-inside-work-tree`
Expected: prints `true` (skip Task 0 entirely) OR fails with `not a git repository` (continue).

- [ ] **Step 2: Initialize repo if needed**

Run: `git -C "C:/Users/USER/Desktop/Praca/Solana/AI_Accountant" init -b main`
Expected: `Initialized empty Git repository in .../AI_Accountant/.git/`

- [ ] **Step 3: Initial commit of the existing tree (so refactor diffs are visible)**

Run:
```
git -C "C:/Users/USER/Desktop/Praca/Solana/AI_Accountant" add -A -- ":!bash.exe.stackdump"
git -C "C:/Users/USER/Desktop/Praca/Solana/AI_Accountant" commit -m "chore: snapshot before fetcher refactor"
```
Expected: commit succeeds; `bash.exe.stackdump` excluded.

---

## Task 1: Project hygiene — `.gitignore`, README, ruff config, stackdump removal

**Files:**
- Create: `.gitignore`
- Replace: `README.md`
- Modify: `pyproject.toml`
- Delete: `bash.exe.stackdump`

- [ ] **Step 1: Write `.gitignore`**

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

- [ ] **Step 2: Replace `README.md`**

```markdown
# AI Accountant

Python utilities for retrieving and normalizing Solana on-chain activity (via the
Helius Enhanced API) into accounting-grade Pandas DataFrames. Financial values are
preserved as `Decimal` end-to-end.

## Install

```bash
pip install -e ".[dev]"
```

## Quick example

```python
from ai_accountant import SolanaDataFetcher, TransactionParser

fetcher = SolanaDataFetcher(api_key="<HELIUS_KEY>")
df = fetcher.fetch_transactions_dataframe("<WALLET>", max_pages=1)

# Or stream lazily for large wallets, with resumable cursor checkpoints:
parser = TransactionParser("<WALLET>")
for raw_tx in fetcher.iter_transactions(
    "<WALLET>", on_cursor_advance=lambda c: open("cursor", "w").write(c),
):
    row = parser.parse(raw_tx)
    ...
```

## Layout

- `src/ai_accountant/` — `client`, `parser`, `transport`, `addresses`, `dataframe`, `exceptions`
- `examples/` — illustrative scaffolds (audit pipeline, legal grounding); not part of the public API
- `docs/superpowers/specs/` — design documents
- `tests/` — `pytest` suite

## Development

```bash
pytest                    # tests
ruff check .              # lint
ruff format .             # format
```
```

- [ ] **Step 3: Modify `pyproject.toml`**

Replace the `[project.optional-dependencies]` block and append a `[tool.ruff]` block.

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

Keep all other sections (`[build-system]`, `[project]`, `[tool.setuptools]`, `[tool.pytest.ini_options]`) unchanged.

- [ ] **Step 4: Delete `bash.exe.stackdump`**

Run: `rm "C:/Users/USER/Desktop/Praca/Solana/AI_Accountant/bash.exe.stackdump"`
Expected: file removed; no error.

- [ ] **Step 5: Install ruff into the dev env**

Run: `pip install -e ".[dev]"`
Expected: ruff installed; pytest still installed.

- [ ] **Step 6: Verify pytest still passes (baseline before refactor)**

Run: `pytest -q`
Expected: 4 passed (existing tests).

- [ ] **Step 7: Commit**

```
git add .gitignore README.md pyproject.toml
git rm --ignore-unmatch bash.exe.stackdump
git commit -m "chore: project hygiene — gitignore, README, ruff config"
```

---

## Task 2: Extract `exceptions.py`

**Files:**
- Create: `src/ai_accountant/exceptions.py`
- Modify: `src/ai_accountant/solana_data_fetcher.py` (re-import from exceptions)

- [ ] **Step 1: Write a placeholder failing test**

Create file `tests/test_compat_shim.py`:

```python
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
```

- [ ] **Step 2: Run the new test, expect ImportError on `ai_accountant.exceptions`**

Run: `pytest tests/test_compat_shim.py -v`
Expected: `test_exceptions_module_is_publicly_importable` FAILS with `ModuleNotFoundError: No module named 'ai_accountant.exceptions'`.

- [ ] **Step 3: Create `src/ai_accountant/exceptions.py`**

```python
"""Exception hierarchy for ai_accountant.

Single source of truth. Both `client.py` and external callers import from here.
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
```

- [ ] **Step 4: Update `solana_data_fetcher.py` to re-import from `exceptions`**

Replace the existing exception class block (the six classes) with a single import:

```python
from .exceptions import (
    HeliusAPIError,
    HeliusAuthenticationError,
    HeliusPermissionError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
    SolanaDataFetcherError,
)
```

Place this near the top of `solana_data_fetcher.py`, after the existing `import` block. Delete the in-file class definitions.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: 6 passed (4 existing + 2 new compat tests).

- [ ] **Step 6: Commit**

```
git add src/ai_accountant/exceptions.py src/ai_accountant/solana_data_fetcher.py tests/test_compat_shim.py
git commit -m "refactor: extract exceptions into ai_accountant.exceptions"
```

---

## Task 3: Extract `addresses.py`

**Files:**
- Create: `src/ai_accountant/addresses.py`
- Create: `tests/test_addresses.py`
- Modify: `src/ai_accountant/solana_data_fetcher.py` (re-import; `validate_address` becomes delegating wrapper)

- [ ] **Step 1: Write `tests/test_addresses.py`**

```python
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant import InvalidSolanaAddressError
from ai_accountant.addresses import _decode_base58, validate_address


VALID_WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


class AddressesTests(unittest.TestCase):
    def test_validate_address_accepts_valid_base58(self):
        self.assertEqual(validate_address(VALID_WALLET), VALID_WALLET)

    def test_validate_address_strips_whitespace(self):
        self.assertEqual(validate_address(f"  {VALID_WALLET}  "), VALID_WALLET)

    def test_validate_address_rejects_wrong_length(self):
        with self.assertRaises(InvalidSolanaAddressError):
            validate_address("11111111")

    def test_validate_address_rejects_non_base58_characters(self):
        with self.assertRaises(InvalidSolanaAddressError):
            validate_address("0OIl" + VALID_WALLET[4:])

    def test_validate_address_rejects_non_string(self):
        with self.assertRaises(InvalidSolanaAddressError):
            validate_address(12345)  # type: ignore[arg-type]

    def test_validate_address_rejects_empty_string(self):
        with self.assertRaises(InvalidSolanaAddressError):
            validate_address("   ")

    def test_decode_base58_round_trip_length(self):
        decoded = _decode_base58(VALID_WALLET)
        self.assertEqual(len(decoded), 32)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test, expect ImportError on `ai_accountant.addresses`**

Run: `pytest tests/test_addresses.py -v`
Expected: ImportError / ModuleNotFoundError.

- [ ] **Step 3: Create `src/ai_accountant/addresses.py`**

```python
"""Solana address validation. Stdlib-only Base58 decode."""
from __future__ import annotations

from .exceptions import InvalidSolanaAddressError

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {character: index for index, character in enumerate(BASE58_ALPHABET)}


def validate_address(address: str) -> str:
    """Validate a Solana public key and return the stripped value."""
    if not isinstance(address, str):
        raise InvalidSolanaAddressError("Wallet address must be a string.")

    normalized = address.strip()
    if not normalized:
        raise InvalidSolanaAddressError("Wallet address cannot be empty.")

    decoded = _decode_base58(normalized)
    if len(decoded) != 32:
        raise InvalidSolanaAddressError(
            "Wallet address must decode to a 32-byte Solana public key."
        )
    return normalized


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
```

- [ ] **Step 4: Update `solana_data_fetcher.py`**

Replace the in-file `_decode_base58` static method, the `BASE58_*` constants, and the `validate_address` body with delegation:

In the imports near the top:
```python
from .addresses import validate_address as _validate_address
```

Inside `class SolanaDataFetcher`, replace `validate_address`:
```python
@staticmethod
def validate_address(address: str) -> str:
    """Validate a Solana public key and return the stripped value."""
    return _validate_address(address)
```

Delete the now-orphaned `_decode_base58` static method and the `BASE58_*` module-level constants.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: all tests pass (existing + 7 new address tests).

- [ ] **Step 6: Commit**

```
git add src/ai_accountant/addresses.py src/ai_accountant/solana_data_fetcher.py tests/test_addresses.py
git commit -m "refactor: extract address validation into ai_accountant.addresses"
```

---

## Task 4: Extract `transport.py` with new protocols, case-insensitive headers, HTTP-date Retry-After

**Files:**
- Create: `src/ai_accountant/transport.py`
- Create: `tests/test_transport.py`
- Modify: `src/ai_accountant/solana_data_fetcher.py` (re-import transport; remove inlined `_UrllibSession`, `_SimpleResponse`, `TransportError`)

- [ ] **Step 1: Write `tests/test_transport.py`**

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant.transport import (
    _CaseInsensitiveHeaders,
    _parse_retry_after,
)


class ParseRetryAfterTests(unittest.TestCase):
    def test_numeric_seconds(self):
        self.assertEqual(_parse_retry_after("5"), 5.0)
        self.assertEqual(_parse_retry_after("0.25"), 0.25)
        self.assertEqual(_parse_retry_after("0"), 0.0)

    def test_negative_returns_none(self):
        self.assertIsNone(_parse_retry_after("-1"))

    def test_garbage_returns_none(self):
        self.assertIsNone(_parse_retry_after("not-a-date"))

    def test_none_or_empty_returns_none(self):
        self.assertIsNone(_parse_retry_after(None))
        self.assertIsNone(_parse_retry_after(""))
        self.assertIsNone(_parse_retry_after("   "))

    def test_http_date(self):
        fixed_now = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
        future_value = "Mon, 04 May 2026 12:00:30 GMT"
        delay = _parse_retry_after(future_value, now=lambda: fixed_now)
        self.assertEqual(delay, 30.0)

    def test_http_date_in_past_returns_zero(self):
        fixed_now = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
        past_value = "Mon, 04 May 2026 11:59:00 GMT"
        delay = _parse_retry_after(past_value, now=lambda: fixed_now)
        self.assertEqual(delay, 0.0)


class CaseInsensitiveHeadersTests(unittest.TestCase):
    def setUp(self):
        self.headers = _CaseInsensitiveHeaders([
            ("Retry-After", "10"),
            ("Content-Type", "application/json"),
        ])

    def test_lookup_lowercase(self):
        self.assertEqual(self.headers["retry-after"], "10")

    def test_lookup_mixed_case(self):
        self.assertEqual(self.headers["RETRY-after"], "10")

    def test_get_with_default(self):
        self.assertEqual(self.headers.get("missing", "fallback"), "fallback")

    def test_iteration_preserves_original_case(self):
        self.assertEqual(set(self.headers), {"Retry-After", "Content-Type"})

    def test_membership_case_insensitive(self):
        self.assertIn("retry-after", self.headers)
        self.assertIn("Retry-After", self.headers)
        self.assertNotIn("missing", self.headers)

    def test_len(self):
        self.assertEqual(len(self.headers), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test; expect ImportError**

Run: `pytest tests/test_transport.py -v`
Expected: ModuleNotFoundError on `ai_accountant.transport`.

- [ ] **Step 3: Create `src/ai_accountant/transport.py`**

```python
"""HTTP transport for the Helius client.

Defines the structural `SessionProtocol` test doubles can implement, the
`_UrllibSession` default, case-insensitive header normalization, and
RFC-7231-compliant `Retry-After` parsing.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from typing import Any, Callable, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class TransportError(Exception):
    """Raised by the internal HTTP transport when a request cannot be completed."""


class _CaseInsensitiveHeaders(Mapping[str, str]):
    """Case-insensitive HTTP header mapping that preserves original-case keys on iteration."""

    def __init__(self, items: Iterable[tuple[str, str]]) -> None:
        self._store: dict[str, tuple[str, str]] = {}
        for key, value in items:
            self._store[key.lower()] = (key, value)

    def __getitem__(self, key: str) -> str:
        return self._store[key.lower()][1]

    def __iter__(self) -> Iterator[str]:
        return (original for original, _ in self._store.values())

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._store

    def get(self, key: str, default: Any = None) -> Any:
        entry = self._store.get(key.lower())
        return entry[1] if entry is not None else default


@runtime_checkable
class ResponseProtocol(Protocol):
    status_code: int
    text: str
    headers: Mapping[str, str]

    def json(self) -> Any: ...


@runtime_checkable
class SessionProtocol(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> ResponseProtocol: ...

    def close(self) -> None: ...


class _SimpleResponse:
    def __init__(
        self,
        status_code: int,
        body: str,
        headers: Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = body
        if headers is None:
            self.headers: Mapping[str, str] = _CaseInsensitiveHeaders([])
        elif isinstance(headers, _CaseInsensitiveHeaders):
            self.headers = headers
        elif isinstance(headers, Mapping):
            self.headers = _CaseInsensitiveHeaders(headers.items())
        else:
            self.headers = _CaseInsensitiveHeaders(headers)

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
        request = Request(full_url, headers={"Accept": "application/json"}, method="GET")
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
            headers = dict(exc.headers.items()) if exc.headers else {}
            return _SimpleResponse(status_code=exc.code, body=body, headers=headers)
        except URLError as exc:
            raise TransportError(str(exc)) from exc

    def close(self) -> None:
        return None


def _parse_retry_after(
    value: str | None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> float | None:
    """Parse `Retry-After` per RFC 7231: numeric seconds OR HTTP-date.

    Returns the wait in seconds (clamped at 0), or `None` if the value cannot be
    interpreted. Negative numeric values are treated as `None` (caller falls back
    to its own backoff).
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None

    try:
        n = float(stripped)
    except ValueError:
        pass
    else:
        return n if n >= 0 else None

    try:
        target = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    delta = (target - now()).total_seconds()
    return max(delta, 0.0)
```

- [ ] **Step 4: Run `tests/test_transport.py`, expect all pass**

Run: `pytest tests/test_transport.py -v`
Expected: all pass.

- [ ] **Step 5: Update `solana_data_fetcher.py` to re-import transport**

Add to imports:
```python
from .transport import (
    TransportError,
    _SimpleResponse,
    _UrllibSession,
    _parse_retry_after,
)
```

Delete the in-file definitions of `TransportError`, `_SimpleResponse`, `_UrllibSession` (about lines 22–76 of the original file). Also delete the now-unused module-level imports: `Iterable`, `json`, `urllib.error.HTTPError`, `urllib.error.URLError`, `urllib.parse.urlencode`, `urllib.request.Request`, `urllib.request.urlopen` (only if no longer used; verify before removing).

Update `_compute_retry_delay` in `SolanaDataFetcher` to use `_parse_retry_after`:
```python
def _compute_retry_delay(self, response: Any, attempt: int) -> float:
    delay = _parse_retry_after(response.headers.get("Retry-After"))
    if delay is not None:
        return delay
    return self._compute_backoff_delay(attempt)
```

- [ ] **Step 6: Run full test suite**

Run: `pytest -q`
Expected: all tests pass (including 11 transport tests + existing + address + compat).

- [ ] **Step 7: Commit**

```
git add src/ai_accountant/transport.py src/ai_accountant/solana_data_fetcher.py tests/test_transport.py
git commit -m "refactor: extract transport with case-insensitive headers and RFC-7231 Retry-After"
```

---

## Task 5: Create `dataframe.py` with `DATAFRAME_COLUMNS` constant and `to_dataframe`

**Files:**
- Create: `src/ai_accountant/dataframe.py`
- Create: `tests/test_dataframe.py`
- Modify: `src/ai_accountant/solana_data_fetcher.py` (alias `DATAFRAME_COLUMNS` from new module)

- [ ] **Step 1: Write `tests/test_dataframe.py`**

```python
from __future__ import annotations

from pathlib import Path
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test; expect ImportError on `ai_accountant.dataframe` and `ai_accountant.parser`**

Run: `pytest tests/test_dataframe.py -v`
Expected: ImportError on `ai_accountant.dataframe` (and on `ai_accountant.parser` later — that comes in Task 6).

- [ ] **Step 3: Create `src/ai_accountant/dataframe.py`**

```python
"""DataFrame schema and conversion helpers for ai_accountant."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from .parser import TransactionParser


DATAFRAME_COLUMNS: list[str] = [
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


def to_dataframe(
    parser: "TransactionParser",
    transactions: Iterable[Mapping[str, Any]],
) -> pd.DataFrame:
    """Parse `transactions` with `parser` and return a DataFrame with the canonical schema."""
    rows = parser.parse_many(transactions)
    if not rows:
        return pd.DataFrame(columns=DATAFRAME_COLUMNS)
    return pd.DataFrame(rows, columns=DATAFRAME_COLUMNS).reset_index(drop=True)
```

- [ ] **Step 4: Update `solana_data_fetcher.py` to alias `DATAFRAME_COLUMNS`**

Replace the in-file `DATAFRAME_COLUMNS` class attribute with an import + alias. Add to imports near the top:
```python
from .dataframe import DATAFRAME_COLUMNS as _DATAFRAME_COLUMNS
```

Inside `class SolanaDataFetcher`, replace the existing `DATAFRAME_COLUMNS = [...]` block with:
```python
DATAFRAME_COLUMNS = _DATAFRAME_COLUMNS
```

- [ ] **Step 5: Update `__init__.py` to re-export `DATAFRAME_COLUMNS`**

Replace `src/ai_accountant/__init__.py` with:

```python
from .dataframe import DATAFRAME_COLUMNS
from .exceptions import (
    HeliusAPIError,
    HeliusAuthenticationError,
    HeliusPermissionError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
    SolanaDataFetcherError,
)
from .solana_data_fetcher import SolanaDataFetcher

__all__ = [
    "DATAFRAME_COLUMNS",
    "HeliusAPIError",
    "HeliusAuthenticationError",
    "HeliusPermissionError",
    "HeliusRateLimitError",
    "InvalidSolanaAddressError",
    "SolanaDataFetcher",
    "SolanaDataFetcherError",
]
```

(Note: `TransactionParser` and `validate_address` will be added to `__init__.py` later, in Task 7 and after parser/client extraction.)

- [ ] **Step 6: Run full test suite (parser test will still fail — that's expected)**

Run: `pytest -q --ignore=tests/test_dataframe.py`
Expected: all non-dataframe tests pass.

Run: `pytest tests/test_dataframe.py::DataFrameModuleTests::test_columns_constant_publicly_importable tests/test_dataframe.py::DataFrameModuleTests::test_columns_match_class_attr_for_back_compat -v`
Expected: both pass. The third test (`test_to_dataframe_empty_returns_empty_with_schema`) still fails because `TransactionParser` does not exist yet.

- [ ] **Step 7: Commit**

```
git add src/ai_accountant/dataframe.py src/ai_accountant/solana_data_fetcher.py src/ai_accountant/__init__.py tests/test_dataframe.py
git commit -m "refactor: extract DATAFRAME_COLUMNS and to_dataframe into ai_accountant.dataframe"
```

---

## Task 6: Create `parser.py` with `TransactionParser` (mint-keying, full-mint labels, explicit-None status)

**Files:**
- Create: `src/ai_accountant/parser.py`
- Create: `tests/test_parser.py`
- Modify: `src/ai_accountant/solana_data_fetcher.py` (delegate `_build_transaction_row` and helpers to parser)

- [ ] **Step 1: Write `tests/test_parser.py`**

```python
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant import InvalidSolanaAddressError, TransactionParser


WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW"
COUNTERPARTY = "Pool1111111111111111111111111111111111111"


def _swap_tx(token_transfers):
    return {
        "signature": "sig-test",
        "slot": 1,
        "timestamp": 1_700_000_000,
        "type": "SWAP",
        "source": "JUPITER",
        "fee": 5_000,
        "feePayer": WALLET,
        "nativeTransfers": [],
        "tokenTransfers": token_transfers,
    }


class TransactionParserConstructionTests(unittest.TestCase):
    def test_parser_validates_wallet_address_at_construction(self):
        with self.assertRaises(InvalidSolanaAddressError):
            TransactionParser("not-a-valid-address")

    def test_parser_stores_normalized_wallet(self):
        parser = TransactionParser(f"  {WALLET}  ")
        self.assertEqual(parser.wallet_address, WALLET)


class TransactionParserMintKeyingTests(unittest.TestCase):
    def test_token_collision_aggregated_by_mint_not_symbol(self):
        # Two distinct mints share the symbol "USDC" — they MUST aggregate as
        # two separate flows, not be collapsed by symbol.
        fake_usdc_mint = "FAKE5555555555555555555555555555555555555555"
        parser = TransactionParser(WALLET)
        row = parser.parse(_swap_tx([
            {
                "fromUserAccount": COUNTERPARTY,
                "toUserAccount": WALLET,
                "tokenAmount": "100",
                "mint": USDC_MINT,
                "tokenSymbol": "USDC",
            },
            {
                "fromUserAccount": COUNTERPARTY,
                "toUserAccount": WALLET,
                "tokenAmount": "200",
                "mint": fake_usdc_mint,
                "tokenSymbol": "USDC",
            },
        ]))
        flow_mints = sorted(d["mint"] for d in row["token_flow_details"])
        self.assertEqual(flow_mints, sorted([USDC_MINT, fake_usdc_mint]))
        self.assertEqual(len(row["token_flow_details"]), 2)
        self.assertEqual(row["net_flow"][USDC_MINT], Decimal("100"))
        self.assertEqual(row["net_flow"][fake_usdc_mint], Decimal("200"))

    def test_token_transfer_without_mint_is_skipped(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(_swap_tx([
            {
                "fromUserAccount": COUNTERPARTY,
                "toUserAccount": WALLET,
                "tokenAmount": "100",
                "mint": None,
                "tokenSymbol": "USDC",
            },
        ]))
        self.assertEqual(row["token_flow_details"], [])
        self.assertEqual(row["movements_in"], [])

    def test_label_is_full_mint_not_truncated(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(_swap_tx([
            {
                "fromUserAccount": COUNTERPARTY,
                "toUserAccount": WALLET,
                "tokenAmount": "1",
                "mint": BONK_MINT,
                "tokenSymbol": "BONK",
            },
        ]))
        self.assertEqual(
            row["token_flow_details"][0]["label"],
            f"BONK ({BONK_MINT})",
        )

    def test_net_flow_keyed_by_full_mint_for_tokens_and_SOL_for_native(self):
        parser = TransactionParser(WALLET)
        tx = {
            "signature": "sig-x",
            "slot": 1,
            "timestamp": 1_700_000_000,
            "type": "TRANSFER",
            "fee": 5_000,
            "feePayer": WALLET,
            "nativeTransfers": [
                {"fromUserAccount": "ExtSender1111111111111111111111111111111",
                 "toUserAccount": WALLET,
                 "amount": 1_000_000_000},
            ],
            "tokenTransfers": [
                {"fromUserAccount": COUNTERPARTY, "toUserAccount": WALLET,
                 "tokenAmount": "5", "mint": USDC_MINT, "tokenSymbol": "USDC"},
            ],
        }
        row = parser.parse(tx)
        self.assertIn("SOL", row["net_flow"])
        self.assertIn(USDC_MINT, row["net_flow"])
        self.assertEqual(row["net_flow"][USDC_MINT], Decimal("5"))


class TransactionParserStatusTests(unittest.TestCase):
    def _ok_tx(self, **overrides):
        base = {
            "signature": "sig-x",
            "slot": 1,
            "timestamp": 1_700_000_000,
            "type": "TRANSFER",
            "fee": 5_000,
            "feePayer": WALLET,
            "nativeTransfers": [],
            "tokenTransfers": [],
        }
        base.update(overrides)
        return base

    def test_failed_when_transaction_error_is_dict(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(self._ok_tx(transactionError={"InstructionError": [0, "Custom 6000"]}))
        self.assertEqual(row["status"], "failed")

    def test_failed_when_transaction_error_is_empty_dict(self):
        # Empty dict is FALSY but PRESENT — we want explicit-None semantics.
        parser = TransactionParser(WALLET)
        row = parser.parse(self._ok_tx(transactionError={}))
        self.assertEqual(row["status"], "failed")

    def test_failed_when_transaction_error_is_empty_list(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(self._ok_tx(transactionError=[]))
        self.assertEqual(row["status"], "failed")

    def test_succeeded_when_transaction_error_key_missing(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(self._ok_tx())
        self.assertEqual(row["status"], "succeeded")

    def test_succeeded_when_transaction_error_explicitly_null(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(self._ok_tx(transactionError=None))
        self.assertEqual(row["status"], "succeeded")


class TransactionParserSchemaTests(unittest.TestCase):
    def test_parse_many_returns_list_in_order(self):
        parser = TransactionParser(WALLET)
        rows = parser.parse_many([
            {"signature": "sig-1", "slot": 1, "timestamp": 1_700_000_000,
             "fee": 0, "feePayer": "", "nativeTransfers": [], "tokenTransfers": []},
            {"signature": "sig-2", "slot": 2, "timestamp": 1_700_000_001,
             "fee": 0, "feePayer": "", "nativeTransfers": [], "tokenTransfers": []},
        ])
        self.assertEqual([r["signature"] for r in rows], ["sig-1", "sig-2"])

    def test_self_transfers_ignored(self):
        parser = TransactionParser(WALLET)
        row = parser.parse({
            "signature": "self",
            "slot": 1,
            "timestamp": 1_700_000_000,
            "fee": 0,
            "feePayer": WALLET,
            "nativeTransfers": [
                {"fromUserAccount": WALLET, "toUserAccount": WALLET, "amount": 1_000_000_000},
            ],
            "tokenTransfers": [],
        })
        self.assertEqual(row["movements_in"], [])
        self.assertEqual(row["movements_out"], [])

    def test_fee_subtracted_only_when_wallet_pays(self):
        parser = TransactionParser(WALLET)
        row_paid = parser.parse({
            "signature": "p",
            "slot": 1,
            "timestamp": 1_700_000_000,
            "fee": 5_000,
            "feePayer": WALLET,
            "nativeTransfers": [],
            "tokenTransfers": [],
        })
        self.assertTrue(row_paid["fee_paid_by_wallet"])
        self.assertEqual(row_paid["native_net_sol"], Decimal("-0.000005"))

        row_other = parser.parse({
            "signature": "o",
            "slot": 1,
            "timestamp": 1_700_000_000,
            "fee": 5_000,
            "feePayer": "Other11111111111111111111111111111111111",
            "nativeTransfers": [],
            "tokenTransfers": [],
        })
        self.assertFalse(row_other["fee_paid_by_wallet"])
        self.assertEqual(row_other["native_net_sol"], Decimal("0"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test, expect ImportError on `ai_accountant.TransactionParser`**

Run: `pytest tests/test_parser.py -v`
Expected: ImportError.

- [ ] **Step 3: Create `src/ai_accountant/parser.py`**

```python
"""Parse Helius Enhanced transactions into accounting-grade row dicts.

Each `TransactionParser` is bound to a single wallet address (the audit
perspective). Output rows match the schema in `dataframe.DATAFRAME_COLUMNS`.

Token flows are aggregated by full mint string. Display labels are rendered
from `(symbol, mint)` and used only in the rendered summary fields; they are
never used as dictionary keys.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .addresses import validate_address
from .exceptions import HeliusAPIError


LAMPORTS_PER_SOL = Decimal("1000000000")


class TransactionParser:
    """Parse Helius transactions from a single wallet's perspective."""

    NATIVE_KEY = "SOL"  # net_flow dict key for native SOL; tokens use full mint.

    def __init__(self, wallet_address: str) -> None:
        self.wallet_address = validate_address(wallet_address)

    def parse(self, transaction: Mapping[str, Any]) -> dict[str, Any]:
        movements = self._parse_wallet_movements(transaction)

        fee_lamports = int(transaction.get("fee") or 0)
        fee_sol = Decimal(fee_lamports) / LAMPORTS_PER_SOL
        fee_payer = str(transaction.get("feePayer") or "")
        fee_paid_by_wallet = fee_payer == self.wallet_address

        native_in_sol = movements["native_in_sol"]
        native_out_sol = movements["native_out_sol"]
        native_transfer_net_sol = native_in_sol - native_out_sol
        native_net_sol = native_transfer_net_sol - (
            fee_sol if fee_paid_by_wallet else Decimal("0")
        )

        token_flow_details = self._flow_details_to_rows(movements["token_flows"])
        token_in_summary = self._format_flow_summary(token_flow_details, key="in")
        token_out_summary = self._format_flow_summary(token_flow_details, key="out")
        token_net_summary = self._format_flow_summary(
            token_flow_details, key="net", signed=True,
        )

        net_flow = self._build_net_flow(native_net_sol, token_flow_details)
        net_flow_summary = self._format_net_flow_summary(
            native_net_sol, token_flow_details,
        )

        timestamp_unix = transaction.get("timestamp")
        raw_error = transaction.get("transactionError")
        status = "failed" if raw_error is not None else "succeeded"

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
            "status": status,
            "native_in_sol": native_in_sol,
            "native_out_sol": native_out_sol,
            "native_transfer_net_sol": native_transfer_net_sol,
            "native_net_sol": native_net_sol,
            "token_in_summary": token_in_summary,
            "token_out_summary": token_out_summary,
            "token_net_summary": token_net_summary,
            "net_flow_summary": net_flow_summary,
            "net_flow": net_flow,
            "token_flow_details": token_flow_details,
            "movements_in": movements["movements_in"],
            "movements_out": movements["movements_out"],
            "raw_native_transfers": list(transaction.get("nativeTransfers") or []),
            "raw_token_transfers": list(transaction.get("tokenTransfers") or []),
            "transaction_error": raw_error,
        }

    def parse_many(
        self, transactions: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return [self.parse(tx) for tx in transactions]

    # ------------------------------------------------------------------ helpers

    def _parse_wallet_movements(
        self, transaction: Mapping[str, Any],
    ) -> dict[str, Any]:
        wallet = self.wallet_address
        native_in_sol = Decimal("0")
        native_out_sol = Decimal("0")
        token_flows: dict[str, dict[str, Any]] = {}
        movements_in: list[dict[str, Any]] = []
        movements_out: list[dict[str, Any]] = []

        for native_transfer in transaction.get("nativeTransfers") or []:
            from_account = str(native_transfer.get("fromUserAccount") or "")
            to_account = str(native_transfer.get("toUserAccount") or "")
            if from_account == wallet and to_account == wallet:
                continue

            amount_lamports = self._coerce_decimal(native_transfer.get("amount"))
            if amount_lamports <= 0:
                continue

            amount_sol = amount_lamports / LAMPORTS_PER_SOL
            base = {
                "asset_type": "native",
                "symbol": "SOL",
                "mint": None,
                "amount": amount_sol,
                "amount_lamports": int(amount_lamports),
                "from_user_account": from_account or None,
                "to_user_account": to_account or None,
            }

            if to_account == wallet:
                native_in_sol += amount_sol
                movements_in.append({**base, "direction": "in",
                                     "counterparty": from_account or None})
            if from_account == wallet:
                native_out_sol += amount_sol
                movements_out.append({**base, "direction": "out",
                                      "counterparty": to_account or None})

        for token_transfer in transaction.get("tokenTransfers") or []:
            from_account = str(token_transfer.get("fromUserAccount") or "")
            to_account = str(token_transfer.get("toUserAccount") or "")
            if from_account == wallet and to_account == wallet:
                continue

            amount = self._coerce_decimal(token_transfer.get("tokenAmount"))
            if amount <= 0:
                continue

            mint = token_transfer.get("mint")
            if not mint:
                # Without a mint we cannot disambiguate this asset from any other
                # token sharing the same symbol. Drop the transfer.
                continue
            mint_str = str(mint)
            symbol = self._resolve_token_symbol(token_transfer)

            flow_entry = token_flows.setdefault(
                mint_str,
                {
                    "mint": mint_str,
                    "symbol": symbol,
                    "in": Decimal("0"),
                    "out": Decimal("0"),
                },
            )

            base = {
                "asset_type": "token",
                "symbol": symbol,
                "mint": mint_str,
                "amount": amount,
                "from_user_account": from_account or None,
                "to_user_account": to_account or None,
                "from_token_account": token_transfer.get("fromTokenAccount"),
                "to_token_account": token_transfer.get("toTokenAccount"),
            }

            if to_account == wallet:
                flow_entry["in"] += amount
                movements_in.append({**base, "direction": "in",
                                     "counterparty": from_account or None})
            if from_account == wallet:
                flow_entry["out"] += amount
                movements_out.append({**base, "direction": "out",
                                      "counterparty": to_account or None})

        return {
            "native_in_sol": native_in_sol,
            "native_out_sol": native_out_sol,
            "token_flows": token_flows,
            "movements_in": movements_in,
            "movements_out": movements_out,
        }

    def _flow_details_to_rows(
        self, token_flows: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for mint in sorted(token_flows):
            flow = token_flows[mint]
            inflow = Decimal(flow["in"])
            outflow = Decimal(flow["out"])
            rows.append({
                "symbol": flow["symbol"],
                "mint": mint,
                "label": self._asset_label(flow["symbol"], mint),
                "in": inflow,
                "out": outflow,
                "net": inflow - outflow,
            })
        return rows

    def _build_net_flow(
        self,
        native_net_sol: Decimal,
        token_flow_details: Iterable[Mapping[str, Any]],
    ) -> dict[str, Decimal]:
        net_flow: dict[str, Decimal] = {self.NATIVE_KEY: native_net_sol}
        for flow in token_flow_details:
            net_flow[str(flow["mint"])] = Decimal(flow["net"])
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
            rendered = self._decimal_to_string(amount, signed=signed)
            parts.append(f"{flow['label']}: {rendered}")
        return ", ".join(parts) if parts else "None"

    def _format_net_flow_summary(
        self,
        native_net_sol: Decimal,
        token_flow_details: Iterable[Mapping[str, Any]],
    ) -> str:
        parts: list[str] = []
        if native_net_sol != 0:
            parts.append(
                f"SOL: {self._decimal_to_string(native_net_sol, signed=True)}"
            )
        for flow in token_flow_details:
            net = Decimal(flow["net"])
            if net == 0:
                continue
            parts.append(
                f"{flow['label']}: {self._decimal_to_string(net, signed=True)}"
            )
        return ", ".join(parts) if parts else "No net movement"

    @staticmethod
    def _asset_label(symbol: str, mint: str | None) -> str:
        if mint and mint != symbol:
            return f"{symbol} ({mint})"
        return symbol

    @staticmethod
    def _coerce_decimal(value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise HeliusAPIError(
                f"Unable to parse numeric value from {value!r}."
            ) from exc

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

    @staticmethod
    def _format_timestamp(timestamp_unix: Any) -> str | None:
        if timestamp_unix in (None, ""):
            return None
        try:
            return datetime.fromtimestamp(
                int(timestamp_unix), tz=timezone.utc,
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
```

- [ ] **Step 4: Add `TransactionParser` to `__init__.py`**

Edit `src/ai_accountant/__init__.py`. Add the import and add `"TransactionParser"` to `__all__`:

```python
from .dataframe import DATAFRAME_COLUMNS
from .exceptions import (
    HeliusAPIError,
    HeliusAuthenticationError,
    HeliusPermissionError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
    SolanaDataFetcherError,
)
from .parser import TransactionParser
from .solana_data_fetcher import SolanaDataFetcher

__all__ = [
    "DATAFRAME_COLUMNS",
    "HeliusAPIError",
    "HeliusAuthenticationError",
    "HeliusPermissionError",
    "HeliusRateLimitError",
    "InvalidSolanaAddressError",
    "SolanaDataFetcher",
    "SolanaDataFetcherError",
    "TransactionParser",
]
```

- [ ] **Step 5: Update `solana_data_fetcher.py` to delegate parsing to the new class**

In `solana_data_fetcher.py`:

1. Add to imports: `from .dataframe import to_dataframe as _to_dataframe` and `from .parser import TransactionParser as _TransactionParser`.

2. Replace the `_build_transaction_row` method body with a delegation:
```python
def _build_transaction_row(
    self,
    wallet_address: str,
    transaction: Mapping[str, Any],
) -> dict[str, Any]:
    """Deprecated: use `TransactionParser(wallet_address).parse(transaction)`."""
    return _TransactionParser(wallet_address).parse(transaction)
```

3. Replace the `transactions_to_dataframe` body:
```python
def transactions_to_dataframe(
    self,
    wallet_address: str,
    transactions: Iterable[Mapping[str, Any]],
) -> pd.DataFrame:
    """Convert raw Helius enhanced transactions into a structured DataFrame."""
    parser = _TransactionParser(wallet_address)
    return _to_dataframe(parser, transactions)
```

4. Delete the now-orphaned helpers from `SolanaDataFetcher`: `_parse_wallet_movements`, `_flow_details_to_rows`, `_asset_label`, `_format_flow_summary`, `_format_net_flow_summary`, `_format_timestamp`, `_decimal_to_string`, `_coerce_decimal`, `_resolve_token_symbol`, `_build_net_flow`. Also delete the module-level `LAMPORTS_PER_SOL` if no other call site uses it (it is now in `parser.py`).

Verify the module still imports without error: `python -c "from ai_accountant import SolanaDataFetcher, TransactionParser"` — expected to print nothing and exit 0.

- [ ] **Step 6: Run the parser test suite**

Run: `pytest tests/test_parser.py -v`
Expected: all parser tests pass.

- [ ] **Step 7: Run the full suite — the existing dataframe test will fail**

Run: `pytest -q`
Expected: `test_transactions_to_dataframe_parses_native_token_flows_and_fees` FAILS (label/key shape changed). Everything else passes.

This failing test gets fixed in Task 7. Do not commit until Task 7 is also done — the working tree must be coherent at every commit boundary.

- [ ] **Step 8: Commit (parser only)**

```
git add src/ai_accountant/parser.py src/ai_accountant/solana_data_fetcher.py src/ai_accountant/__init__.py tests/test_parser.py
git commit -m "refactor: extract TransactionParser; fix mint-keyed aggregation and explicit-None status"
```

It is acceptable for this commit to leave one failing assertion in the legacy test — the fix lands in Task 7 and is reviewed together. Add `[WIP]` to the commit message if you want to flag it, otherwise the next commit fixes it within the same task batch.

---

## Task 7: Update existing fetcher test for new mint-keyed assertions

**Files:**
- Modify: `tests/test_solana_data_fetcher.py`

- [ ] **Step 1: Update the assertion block**

Open `tests/test_solana_data_fetcher.py`. Find the `self.assertEqual(row["token_flow_details"], [...])` assertion in `test_transactions_to_dataframe_parses_native_token_flows_and_fees` and replace the expected list with:

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
```

After the existing `self.assertEqual(row["net_flow"]["SOL"], Decimal("-0.150005"))` assertion, add two more:

```python
self.assertEqual(
    row["net_flow"]["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"],
    Decimal("-25"),
)
self.assertEqual(
    row["net_flow"]["DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW"],
    Decimal("1000"),
)
```

- [ ] **Step 2: Run the updated test, expect pass**

Run: `pytest tests/test_solana_data_fetcher.py::SolanaDataFetcherTests::test_transactions_to_dataframe_parses_native_token_flows_and_fees -v`
Expected: PASS.

- [ ] **Step 3: Run full test suite, expect pass**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```
git add tests/test_solana_data_fetcher.py
git commit -m "test: update fetcher assertions for full-mint labels and mint-keyed net_flow"
```

---

## Task 8: Create `client.py` with `SolanaDataFetcher`, `iter_transactions`, tightened payload validation

**Files:**
- Create: `src/ai_accountant/client.py`
- Replace: `src/ai_accountant/solana_data_fetcher.py` with shim
- Modify: `src/ai_accountant/__init__.py` (re-import `SolanaDataFetcher` from `client`)
- Modify: `tests/test_solana_data_fetcher.py` (rename to `tests/test_client.py`; add new tests)

- [ ] **Step 1: Add new tests to `tests/test_solana_data_fetcher.py`**

Append these test methods to the existing `SolanaDataFetcherTests` class:

```python
    def test_iter_transactions_yields_one_at_a_time(self):
        session = FakeSession([
            FakeResponse(200, payload=[
                {"signature": "sig-3"},
                {"signature": "sig-2"},
            ]),
            FakeResponse(200, payload=[{"signature": "sig-1"}]),
            FakeResponse(200, payload=[]),
        ])
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        seen: list[str] = []
        for tx in fetcher.iter_transactions(WALLET_ADDRESS):
            seen.append(tx["signature"])
        self.assertEqual(seen, ["sig-3", "sig-2", "sig-1"])

    def test_iter_transactions_invokes_cursor_callback_per_page(self):
        session = FakeSession([
            FakeResponse(200, payload=[{"signature": "sig-3"}, {"signature": "sig-2"}]),
            FakeResponse(200, payload=[{"signature": "sig-1"}]),
            FakeResponse(200, payload=[]),
        ])
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        cursors: list[str] = []
        list(fetcher.iter_transactions(
            WALLET_ADDRESS, on_cursor_advance=cursors.append,
        ))
        # Callback fires after each page that produced a NEW cursor for the
        # NEXT request. After page 1 cursor advances to "sig-2", after page 2
        # cursor advances to "sig-1". Page 3 is empty — no further advance.
        self.assertEqual(cursors, ["sig-2", "sig-1"])

    def test_iter_transactions_callback_not_invoked_after_terminal_page(self):
        session = FakeSession([FakeResponse(200, payload=[])])
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        cursors: list[str] = []
        list(fetcher.iter_transactions(
            WALLET_ADDRESS, on_cursor_advance=cursors.append,
        ))
        self.assertEqual(cursors, [])

    def test_fetch_transaction_history_returns_concrete_list(self):
        session = FakeSession([
            FakeResponse(200, payload=[{"signature": "sig-1"}]),
            FakeResponse(200, payload=[]),
        ])
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        result = fetcher.fetch_transaction_history(WALLET_ADDRESS)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [{"signature": "sig-1"}])

    def test_payload_validation_non_object_item_raises_helius_api_error(self):
        from ai_accountant import HeliusAPIError
        session = FakeSession([
            FakeResponse(200, payload=[{"signature": "ok"}, "not-an-object"]),
        ])
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        with self.assertRaises(HeliusAPIError) as ctx:
            fetcher.fetch_transaction_history(WALLET_ADDRESS)
        self.assertIn("not a JSON object", str(ctx.exception))

    def test_payload_validation_non_list_top_level_raises_helius_api_error(self):
        from ai_accountant import HeliusAPIError
        session = FakeSession([
            FakeResponse(200, payload={"unexpected": "shape"}),
        ])
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        with self.assertRaises(HeliusAPIError):
            fetcher.fetch_transaction_history(WALLET_ADDRESS)

    def test_retry_after_lowercase_header_respected(self):
        session = FakeSession([
            FakeResponse(429, payload={"message": "slow down"},
                         headers={"retry-after": "0"}),
            FakeResponse(200, payload=[]),
        ])
        sleep_calls: list[float] = []
        fetcher = SolanaDataFetcher(
            api_key="test-key", session=session,
            sleep_func=sleep_calls.append,
        )
        result = fetcher.fetch_transaction_history(WALLET_ADDRESS)
        self.assertEqual(result, [])
        self.assertEqual(sleep_calls, [0.0])

    def test_retry_after_http_date_header_respected(self):
        from datetime import datetime, timezone
        # The HTTP-date branch is tested directly in test_transport.py with a
        # mocked `now`. Here we just verify the integration: a syntactically
        # valid HTTP-date is accepted (parsed without raising) and a retry
        # actually happens.
        session = FakeSession([
            FakeResponse(429, payload={"message": "slow"},
                         headers={"Retry-After": "Mon, 04 May 2026 12:00:00 GMT"}),
            FakeResponse(200, payload=[]),
        ])
        sleep_calls: list[float] = []
        fetcher = SolanaDataFetcher(
            api_key="test-key", session=session,
            sleep_func=sleep_calls.append,
        )
        result = fetcher.fetch_transaction_history(WALLET_ADDRESS)
        self.assertEqual(result, [])
        self.assertEqual(len(sleep_calls), 1)
        # Delay clamped at 0 if date is in the past relative to wall clock.
        self.assertGreaterEqual(sleep_calls[0], 0.0)
```

- [ ] **Step 2: Run new tests; expect failures (`iter_transactions` not implemented; payload validation lax)**

Run: `pytest tests/test_solana_data_fetcher.py -v`
Expected: 5 new tests fail (no `iter_transactions`, payload doesn't raise the right error, etc.).

- [ ] **Step 3: Create `src/ai_accountant/client.py`**

```python
"""Helius client: HTTP orchestration, retry/pagination, DataFrame helper."""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from decimal import Decimal
import time
from typing import Any, Callable

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
    _UrllibSession,
    _parse_retry_after,
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

    def __enter__(self) -> "SolanaDataFetcher":
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
            "token_accounts", token_accounts, {"none", "balanceChanged", "all"},
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
            if (not next_cursor
                    or next_cursor == cursor
                    or next_cursor in cursor_history):
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
        return list(self.iter_transactions(
            wallet_address,
            before=before,
            after=after,
            commitment=commitment,
            token_accounts=token_accounts,
            sort_order=sort_order,
            transaction_type=transaction_type,
            source=source,
            max_pages=max_pages,
        ))

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
            before=before, after=after, commitment=commitment,
            token_accounts=token_accounts, sort_order=sort_order,
            transaction_type=transaction_type, source=source,
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
        delay = _parse_retry_after(response.headers.get("Retry-After"))
        if delay is not None:
            return delay
        return self._compute_backoff_delay(attempt)

    def _compute_backoff_delay(self, attempt: int) -> float:
        return self.backoff_factor * (2 ** attempt)
```

- [ ] **Step 4: Replace `src/ai_accountant/solana_data_fetcher.py` with shim**

Replace the entire file contents with:

```python
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
```

- [ ] **Step 5: Update `__init__.py` to import `SolanaDataFetcher` from `client` and add `validate_address`**

Replace `src/ai_accountant/__init__.py`:

```python
from .addresses import validate_address
from .client import SolanaDataFetcher
from .dataframe import DATAFRAME_COLUMNS
from .exceptions import (
    HeliusAPIError,
    HeliusAuthenticationError,
    HeliusPermissionError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
    SolanaDataFetcherError,
)
from .parser import TransactionParser

__all__ = [
    "DATAFRAME_COLUMNS",
    "HeliusAPIError",
    "HeliusAuthenticationError",
    "HeliusPermissionError",
    "HeliusRateLimitError",
    "InvalidSolanaAddressError",
    "SolanaDataFetcher",
    "SolanaDataFetcherError",
    "TransactionParser",
    "validate_address",
]
```

- [ ] **Step 6: Rename test file**

Run:
```
git mv "tests/test_solana_data_fetcher.py" "tests/test_client.py"
```

(If `git mv` is unavailable because Task 0 was skipped and there's no repo, do a regular `mv` followed by manual reference cleanup.)

- [ ] **Step 7: Add a compat-shim assertion**

Append to `tests/test_compat_shim.py` inside `CompatShimTests`:

```python
    def test_solana_data_fetcher_submodule_still_importable(self):
        from ai_accountant.solana_data_fetcher import (
            SolanaDataFetcher,
            TransactionParser,
            validate_address,
            HeliusAPIError,
        )
        self.assertTrue(callable(SolanaDataFetcher))
        self.assertTrue(callable(TransactionParser))
        self.assertTrue(callable(validate_address))
        self.assertTrue(issubclass(HeliusAPIError, Exception))

    def test_build_transaction_row_back_compat_alias(self):
        from ai_accountant import SolanaDataFetcher
        wallet = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
        fetcher = SolanaDataFetcher(api_key="test-key")
        row = fetcher._build_transaction_row(wallet, {
            "signature": "s",
            "slot": 1,
            "timestamp": 1_700_000_000,
            "fee": 0,
            "feePayer": "",
            "nativeTransfers": [],
            "tokenTransfers": [],
        })
        self.assertEqual(row["signature"], "s")
        self.assertEqual(row["status"], "succeeded")
```

- [ ] **Step 8: Run full test suite**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 9: Lint with ruff**

Run: `ruff check src tests`
Expected: clean (or only warnings that can be fixed inline). If errors appear, fix them — typical fixes will be import ordering (`I001`) or unused imports (`F401`) on the shim — for the latter add `# noqa: F401` if not already there.

Run: `ruff format src tests`
Expected: applies formatting. Stage the changes.

- [ ] **Step 10: Commit**

```
git add src/ai_accountant/client.py src/ai_accountant/solana_data_fetcher.py src/ai_accountant/__init__.py tests/test_client.py tests/test_compat_shim.py
git commit -m "refactor: split client.py with iter_transactions, on_cursor_advance, strict payload validation"
```

---

## Task 9: Fix `audit_demo.py` slippage logic

**Files:**
- Modify: `examples/audit_demo.py`

- [ ] **Step 1: Locate the existing slippage block**

Open `examples/audit_demo.py`. In `run_pipeline`, find the block under `elif category == "Swap (capital event)":` that reads:

```python
if basis_usd > 0:
    slip = (basis_usd - proceeds_usd) / basis_usd
    if slip > Decimal("0.05"):
        findings.append({
            "sig": sig,
            "issue": "Possible high slippage / unfavorable fill",
            "estimated_loss_pct":
                f"{(slip * 100).quantize(TWO_PLACES)}%",
        })
```

- [ ] **Step 2: Replace with implied-price slippage check**

Replace those lines with:

```python
# Slippage detection — compare implied execution price (in_value_usd / out_units)
# to the oracle reference price for the out-asset on the swap date.
# ILLUSTRATIVE — production needs a real quote provider (e.g. Jupiter quote
# API at swap-submit time). A daily oracle close still confuses true slippage
# with intra-day price drift, but it removes the basis-vs-proceeds confusion
# that the previous check had.
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
    if (oracle_px is not None
            and oracle_px > 0
            and out_units > 0
            and in_value_usd > 0):
        implied_px = in_value_usd / out_units
        slip_pct = (oracle_px - implied_px) / oracle_px
        if slip_pct > Decimal("0.05"):
            findings.append({
                "sig": sig,
                "issue": "Possible high slippage (implied execution price below oracle reference)",
                "implied_slippage_pct": f"{(slip_pct * 100).quantize(TWO_PLACES)}%",
            })
```

- [ ] **Step 3: Run the demo end-to-end**

Run: `python "C:/Users/USER/Desktop/Praca/Solana/AI_Accountant/examples/audit_demo.py"`
Expected: prints the report without raising. The `RISK FINDINGS` section should mention the implied-slippage finding for `demo-005-swap-sol-bonk-slip` (the demo's high-slippage swap was designed to trigger this).

- [ ] **Step 4: Commit**

```
git add examples/audit_demo.py
git commit -m "fix(examples): replace basis-vs-proceeds slippage check with implied-price-vs-oracle"
```

---

## Task 10: Add `taxable_event` field and structured conflict detector to `legal_grounding.py`

**Files:**
- Modify: `examples/legal_grounding.py`

- [ ] **Step 1: Add the field to `LegalSource`**

In `examples/legal_grounding.py`, modify the `LegalSource` dataclass to add the field. Replace the dataclass block:

```python
@dataclass(frozen=True)
class LegalSource:
    id: str
    jurisdiction: str
    kind: str
    tier: str
    effective_date: str | None
    title: str
    holding_summary: str
    verbatim_excerpt: str
    source_url: str
    applies_to: tuple[str, ...]
    taxable_event: bool | None = None  # True/False = explicit; None = silent
```

- [ ] **Step 2: Set explicit `taxable_event` values for every existing entry**

For each entry in `LEGAL_CORPUS`, append `taxable_event=<value>` to the constructor arguments per this table:

| ID | Value |
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

Example:
```python
LegalSource(
    id="PL-PIT-ART-30B-1A",
    # ... existing args ...
    applies_to=("Swap (capital event)",),
    taxable_event=False,
),
```

- [ ] **Step 3: Replace the substring conflict detector**

In `render_legal_report`, find the block that reads:

```python
for s_sec in secondary_sources:
    for s_pri in primary_sources:
        if (s_pri.jurisdiction != s_sec.jurisdiction
                and "NOT" in s_sec.holding_summary
                and "NOT" not in s_pri.holding_summary):
            lines += [
                "",
                ("    [CONFLICT] Secondary jurisdiction "
                 f"{s_sec.jurisdiction} appears to NEGATE the "
                 f"taxable-event treatment in "
                 f"{s_pri.jurisdiction}. Resolution depends on "
                 f"taxpayer's tax residence and treaty position."),
            ]
            break
```

Replace with:

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
                (f"    [CONFLICT] {s_pri.jurisdiction} treats this category as "
                 f"{pri_label}; {s_sec.jurisdiction} treats it as {sec_label}. "
                 f"Resolution depends on taxpayer's tax residence and treaty position."),
            ]
            break
```

- [ ] **Step 4: Update module docstring**

Open the docstring at the top of `legal_grounding.py`. After the existing `DESIGN CONSTRAINT` paragraph, add:

```
STRUCTURED LEGAL SIGNAL:
    `LegalSource.taxable_event` is the structured tri-state signal used by the
    conflict detector. `holding_summary` is a paraphrase intended for human
    display; it is NOT used as authority and is NOT scanned for keywords.
    `verbatim_excerpt` (when populated by a real RAG retriever) is the only
    text treated as authoritative.
```

- [ ] **Step 5: Run the demo end-to-end**

Run: `python "C:/Users/USER/Desktop/Praca/Solana/AI_Accountant/examples/legal_grounding.py"`
Expected: prints the report without raising. The PL-PIT vs US-IRC-1091 pair should now produce a `[CONFLICT]` line for the `Swap (capital event)` category. The MiCA entry (now `taxable_event=None`) should NOT trigger a conflict line for any category.

- [ ] **Step 6: Commit**

```
git add examples/legal_grounding.py
git commit -m "fix(examples): structured taxable_event field replaces substring conflict detector"
```

---

## Task 11: Annotate Sentinel spec with pre-Sprint-2 task completion

**Files:**
- Modify: `docs/superpowers/specs/2026-05-03-sentinel-core-design.md`

- [ ] **Step 1: Add the annotation**

Open the file. Find the table heading `## 13. Tech Debt & Extension Points`. Immediately above the table (between the heading and the `| Item | Target |` row), insert:

```markdown
> **Update 2026-05-04:** The pre-Sprint-2 task to extract `_build_transaction_row`
> is complete. New code should call
> `TransactionParser(wallet_address).parse(raw_tx)` from `ai_accountant`. The
> `SolanaDataFetcher._build_transaction_row(wallet, tx)` alias remains for one
> release as a deprecated delegating wrapper — the Sentinel normalizer can
> switch to `TransactionParser` whenever convenient.

```

- [ ] **Step 2: Commit**

```
git add docs/superpowers/specs/2026-05-03-sentinel-core-design.md
git commit -m "docs(sentinel): note pre-Sprint-2 TransactionParser extraction is complete"
```

---

## Task 12: Final verification — pytest + ruff + manual import smoke test

**Files:** none.

- [ ] **Step 1: Run the full test suite verbose**

Run: `pytest -v`
Expected: all tests pass, no skips, no warnings of substance.

- [ ] **Step 2: Run ruff check + format on the entire tree**

Run: `ruff check src tests examples`
Expected: clean. If anything fires, fix and re-run before continuing.

Run: `ruff format --check src tests examples`
Expected: clean. If formatting drift is reported, run `ruff format src tests examples` and re-stage.

- [ ] **Step 3: Smoke-test the public surface**

Run:
```
python -c "from ai_accountant import (SolanaDataFetcher, TransactionParser, validate_address, DATAFRAME_COLUMNS, HeliusAPIError, HeliusAuthenticationError, HeliusPermissionError, HeliusRateLimitError, InvalidSolanaAddressError, SolanaDataFetcherError); print('OK')"
```
Expected: prints `OK`.

Run:
```
python -c "from ai_accountant.solana_data_fetcher import SolanaDataFetcher, TransactionParser; print('shim OK')"
```
Expected: prints `shim OK`.

- [ ] **Step 4: Smoke-test both examples**

Run: `python "C:/Users/USER/Desktop/Praca/Solana/AI_Accountant/examples/audit_demo.py"`
Expected: report prints without raising.

Run: `python "C:/Users/USER/Desktop/Praca/Solana/AI_Accountant/examples/legal_grounding.py"`
Expected: report prints without raising; `[CONFLICT]` appears for the PL-vs-US swap category.

- [ ] **Step 5: Final commit (only if any cleanup landed)**

If `ruff format` modified files in Step 2, commit:
```
git add -A
git commit -m "style: apply ruff format across the tree"
```
Otherwise, no commit needed.

---

## Self-Review Notes

**Spec coverage (against `docs/superpowers/specs/2026-05-04-fetcher-refactor-design.md`):**

| Spec section | Implementing task(s) |
|---|---|
| §3 Package layout | Tasks 2–8 (one task per new module) |
| §4 `exceptions.py` | Task 2 |
| §5 `addresses.py` | Task 3 |
| §6 `transport.py` (protocols, headers, Retry-After) | Task 4 |
| §7 `parser.py` (mint-keying, full-mint label, explicit-None status) | Task 6 |
| §8 `dataframe.py` | Task 5 |
| §9 `client.py` (`iter_transactions`, payload validation, deprecated alias) | Task 8 |
| §10 audit_demo slippage | Task 9 |
| §10 legal_grounding `taxable_event` + conflict detector | Task 10 |
| §11 Tests | Tasks 2–8 (per-module) + Task 7 (existing test update) |
| §12 Hygiene | Task 1 |
| §13 Sentinel annotation | Task 11 |
| §14 Compatibility matrix | Verified by Task 8 step 7 (compat-shim assertions) and Task 12 step 3 (smoke test) |

**Type/name consistency check:**
- `TransactionParser` — defined in Task 6, used in Task 8 (client) and Task 5 (test_dataframe). Consistent.
- `validate_address` — defined in Task 3, called from Task 6 (parser constructor) and Task 8 (client). Consistent.
- `_parse_retry_after`, `_CaseInsensitiveHeaders` — defined in Task 4, used in Task 8. Consistent.
- `DATAFRAME_COLUMNS` — defined in Task 5, aliased on `SolanaDataFetcher` in Task 8. Consistent.
- `to_dataframe` — defined in Task 5, called in Task 8's `transactions_to_dataframe`. Consistent.
- `HeliusAPIError(message, *, status_code=None)` — signature defined in Task 2, used the same way everywhere. Consistent.
- `iter_transactions(... on_cursor_advance: Callable[[str], None] | None = None ...)` — signature defined in Task 8, called from `fetch_transaction_history` in same task. Consistent.

**Risk: Test-state coherence between tasks 6 and 7.** Task 6 leaves the legacy `test_transactions_to_dataframe_parses_native_token_flows_and_fees` failing because its assertions assume the old truncated-label shape. Task 7 fixes that test in the very next commit. Acceptable per "two commits in one logical batch" — the ruff/pytest gates run at the end of Task 8, not between Tasks 6 and 7.

**Risk: Token-transfer-without-mint behavior change.** Tested explicitly in Task 6 step 1 (`test_token_transfer_without_mint_is_skipped`). Documented in `parser.py` docstring. Acceptable.

**Risk: `SOL` literal collision with a token mint.** Solana mints are 32-byte Base58, so a literal `"SOL"` (3 characters) cannot collide. Safe.

**Placeholder scan:** No "TBD", no "TODO", no "implement later". Every code step shows the actual code.
