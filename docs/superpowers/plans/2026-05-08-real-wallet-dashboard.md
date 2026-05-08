# Real-Wallet Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `ai_accountant.dashboard/` — a local Flask web dashboard for live Solana wallet activity with multi-wallet paste-form, filesystem cache, server-side filtering, hand-rolled SVG charts, per-tx detail page, and CSV/JSON export.

**Architecture:** New sibling sub-package to (future) `ai_accountant.demo`. Separation of concerns: `cache.py` / `filters.py` / `charts.py` / `views.py` / `fetcher.py` are plain Python (no Flask); `server/` and `cli.py` are the only Flask/argparse entry points. Reuses `report.py` builders for KPI/asset/mix/risk/tx panels — same parser-level views, two surfaces.

**Tech Stack:** Python 3.10+, Flask 3, Jinja 3, pandas (existing), stdlib `pickle` for cache, hand-rolled SVG, vanilla JS. Tests use stdlib `unittest` (project convention) + `pytest` runner.

**Spec:** [`docs/superpowers/specs/2026-05-08-real-wallet-dashboard-design.md`](../specs/2026-05-08-real-wallet-dashboard-design.md)

---

## File map

| Path | Responsibility |
|---|---|
| `src/ai_accountant/dashboard/__init__.py` | Public exports for the sub-package |
| `src/ai_accountant/dashboard/cache.py` | Filesystem cache (read/write/list/forget) |
| `src/ai_accountant/dashboard/filters.py` | `FilterSpec` querystring → DataFrame filter |
| `src/ai_accountant/dashboard/charts.py` | `render_line_svg`, `render_bar_svg` |
| `src/ai_accountant/dashboard/views.py` | Template context builders |
| `src/ai_accountant/dashboard/fetcher.py` | `DashboardError`, `run_fetch`, lockfile |
| `src/ai_accountant/dashboard/server/__init__.py` | Flask app factory `create_app` |
| `src/ai_accountant/dashboard/server/routes.py` | All HTTP routes |
| `src/ai_accountant/dashboard/server/static/dashboard.css` | Local CSS |
| `src/ai_accountant/dashboard/server/static/dashboard.js` | Submit-on-change JS (~20 lines) |
| `src/ai_accountant/dashboard/templates/base.html.j2` | Page shell |
| `src/ai_accountant/dashboard/templates/landing.html.j2` | Paste form + recent wallets |
| `src/ai_accountant/dashboard/templates/wallet.html.j2` | Main dashboard page |
| `src/ai_accountant/dashboard/templates/transaction.html.j2` | Per-tx detail page |
| `src/ai_accountant/dashboard/templates/error.html.j2` | Fetch-error / 4xx / 5xx page |
| `src/ai_accountant/dashboard/cli.py` | argparse: `dashboard {serve,fetch}` |
| `tests/dashboard/__init__.py` | Test package marker |
| `tests/dashboard/conftest.py` | Shared fixtures (synthetic_df, fake_fetcher) |
| `tests/dashboard/test_cache.py` | Cache layer |
| `tests/dashboard/test_filters.py` | FilterSpec |
| `tests/dashboard/test_charts.py` | SVG renderers |
| `tests/dashboard/test_views.py` | View builders + KPI parity |
| `tests/dashboard/test_fetcher.py` | run_fetch + DashboardError translation |
| `tests/dashboard/test_routes.py` | All Flask routes |
| `tests/dashboard/test_cli.py` | CLI argparse + subprocess invocations |
| `pyproject.toml` | Add `[dashboard]` extra + console script |
| `CLAUDE.md` | Document the new sub-package |
| `examples/real_wallet_report.py` | Add one-line note pointing to dashboard |

---

## Task 1: Project skeleton + pyproject

**Files:**
- Create: `src/ai_accountant/dashboard/__init__.py`
- Create: `tests/dashboard/__init__.py`
- Modify: `pyproject.toml`

**Goal:** Land an empty but importable sub-package, register the optional extra and the console script. Verify `pip install -e ".[dev,dashboard]"` succeeds.

- [ ] **Step 1: Create the empty sub-package**

Create `src/ai_accountant/dashboard/__init__.py` with this exact content:

```python
"""Local web dashboard for real Solana wallet activity (parser-level views)."""

from __future__ import annotations

__all__: list[str] = []
```

- [ ] **Step 2: Create the empty test package**

Create `tests/dashboard/__init__.py` (empty file — zero bytes is fine, but to keep diffs clean write a single newline):

```
```

- [ ] **Step 3: Add the optional extra and console script to pyproject.toml**

In `pyproject.toml`, locate the `[project.optional-dependencies]` table (currently has `dev = [...]`). Add a sibling `dashboard` entry, then append a new `[project.scripts]` table at the bottom of the `[project.*]` block.

Replace lines 15-19 of `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.6.0",
]
```

with:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.6.0",
]
dashboard = [
    "flask>=3.0",
    "jinja2>=3.1",
]

[project.scripts]
dashboard = "ai_accountant.dashboard.cli:main"
```

- [ ] **Step 4: Install with the new extra**

Run: `pip install -e ".[dev,dashboard]"`
Expected: installs `flask` and `jinja2`, exits 0.

- [ ] **Step 5: Verify the sub-package imports**

Run: `python -c "import ai_accountant.dashboard; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 6: Verify existing test suite still passes**

Run: `pytest`
Expected: all existing tests pass; the new empty `tests/dashboard/` collects zero tests but does not error.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/ai_accountant/dashboard/__init__.py tests/dashboard/__init__.py
git commit -m "feat(dashboard): scaffold sub-package, add [dashboard] extra and console script"
```

---

## Task 2: cache.py

**Files:**
- Create: `src/ai_accountant/dashboard/cache.py`
- Create: `tests/dashboard/test_cache.py`

**Goal:** Filesystem cache layer. Read/write a wallet's `(DataFrame, meta)` to disk atomically, list cached wallets sorted by `fetched_at` desc, forget a wallet by deleting its directory. `schema_version` mismatch on read returns `None`. Path construction always validates the address.

### Module contract

```python
# cache.py public surface
SCHEMA_VERSION = 1

@dataclass(frozen=True)
class CachedWallet:
    address: str
    fetched_at: str            # ISO 8601 UTC
    row_count: int
    earliest_tx: str           # "YYYY-MM-DD" or "" if no tx
    latest_tx: str             # "YYYY-MM-DD" or "" if no tx
    pages_fetched: int
    max_pages_at_fetch: int

def read(address: str, *, cache_root: Path) -> tuple[pd.DataFrame, dict] | None: ...
def write(address: str, df: pd.DataFrame, meta: dict, *, cache_root: Path) -> None: ...
def list_wallets(*, cache_root: Path) -> list[CachedWallet]: ...
def forget(address: str, *, cache_root: Path) -> bool: ...   # True if removed
```

- [ ] **Step 1: Write failing tests**

Create `tests/dashboard/test_cache.py`:

```python
from __future__ import annotations

import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS, InvalidSolanaAddressError
from ai_accountant.dashboard import cache as cache_mod

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
WALLET2 = "FduuYSbVSJojJL3RjL4QyZsoxtYdqoanZ9whCkQjPCAm"


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=DATAFRAME_COLUMNS)


def _decimal_df() -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {col: None for col in DATAFRAME_COLUMNS},
            {col: None for col in DATAFRAME_COLUMNS},
        ]
    )
    df["signature"] = ["sig-A", "sig-B"]
    df["fee_sol"] = [Decimal("0.000005"), Decimal("0.0000123")]
    df["timestamp_unix"] = [1_700_000_000, 1_700_000_500]
    df["timestamp"] = ["2023-11-14T22:13:20+00:00", "2023-11-14T22:21:40+00:00"]
    return df


def _meta(address: str = WALLET, **overrides) -> dict:
    base = {
        "schema_version": cache_mod.SCHEMA_VERSION,
        "address": address,
        "fetched_at": "2026-05-08T14:33:21Z",
        "pages_fetched": 5,
        "max_pages_at_fetch": 5,
        "row_count": 0,
        "earliest_tx": "",
        "latest_tx": "",
        "ai_accountant_version": "0.1.0",
    }
    base.update(overrides)
    return base


class CacheReadWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(self.id().replace(".", "_") + "_tmp")
        self._tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_read_returns_none_when_no_cache(self) -> None:
        self.assertIsNone(cache_mod.read(WALLET, cache_root=self._tmp))

    def test_write_then_read_round_trip_preserves_decimals(self) -> None:
        df = _decimal_df()
        cache_mod.write(WALLET, df, _meta(row_count=2), cache_root=self._tmp)
        result = cache_mod.read(WALLET, cache_root=self._tmp)
        self.assertIsNotNone(result)
        out_df, out_meta = result
        self.assertEqual(out_df["fee_sol"].tolist(), df["fee_sol"].tolist())
        self.assertEqual(out_meta["row_count"], 2)
        self.assertEqual(out_meta["address"], WALLET)

    def test_schema_version_mismatch_returns_none(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(), cache_root=self._tmp)
        meta_path = self._tmp / WALLET / "meta.json"
        bumped = json.loads(meta_path.read_text())
        bumped["schema_version"] = 99
        meta_path.write_text(json.dumps(bumped))
        self.assertIsNone(cache_mod.read(WALLET, cache_root=self._tmp))

    def test_corrupt_pickle_returns_none(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(), cache_root=self._tmp)
        (self._tmp / WALLET / "transactions.pkl").write_bytes(b"not a pickle")
        self.assertIsNone(cache_mod.read(WALLET, cache_root=self._tmp))

    def test_missing_meta_returns_none(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(), cache_root=self._tmp)
        (self._tmp / WALLET / "meta.json").unlink()
        self.assertIsNone(cache_mod.read(WALLET, cache_root=self._tmp))

    def test_atomic_write_does_not_clobber_on_partial_failure(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(row_count=1), cache_root=self._tmp)
        # Simulate a half-finished new write by leaving a stale .tmp file.
        stale_pkl = self._tmp / WALLET / "transactions.pkl.tmp"
        stale_pkl.write_bytes(b"interrupted")
        # A fresh read must still succeed using the canonical files.
        result = cache_mod.read(WALLET, cache_root=self._tmp)
        self.assertIsNotNone(result)
        self.assertEqual(result[1]["row_count"], 1)


class CacheListWalletsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(self.id().replace(".", "_") + "_tmp")
        self._tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_list_wallets_empty(self) -> None:
        self.assertEqual(cache_mod.list_wallets(cache_root=self._tmp), [])

    def test_list_wallets_sorted_by_fetched_at_desc(self) -> None:
        cache_mod.write(
            WALLET,
            _empty_df(),
            _meta(address=WALLET, fetched_at="2026-05-01T10:00:00Z"),
            cache_root=self._tmp,
        )
        cache_mod.write(
            WALLET2,
            _empty_df(),
            _meta(address=WALLET2, fetched_at="2026-05-08T10:00:00Z"),
            cache_root=self._tmp,
        )
        wallets = cache_mod.list_wallets(cache_root=self._tmp)
        self.assertEqual([w.address for w in wallets], [WALLET2, WALLET])

    def test_list_wallets_skips_invalid_directories(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(), cache_root=self._tmp)
        # A bare directory without a valid meta.json must be skipped, not crashed on.
        (self._tmp / "not-a-real-wallet").mkdir()
        wallets = cache_mod.list_wallets(cache_root=self._tmp)
        self.assertEqual([w.address for w in wallets], [WALLET])


class CacheForgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(self.id().replace(".", "_") + "_tmp")
        self._tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_forget_removes_wallet_directory(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(), cache_root=self._tmp)
        self.assertTrue(cache_mod.forget(WALLET, cache_root=self._tmp))
        self.assertIsNone(cache_mod.read(WALLET, cache_root=self._tmp))

    def test_forget_returns_false_when_no_cache(self) -> None:
        self.assertFalse(cache_mod.forget(WALLET, cache_root=self._tmp))


class CacheAddressValidationTests(unittest.TestCase):
    def test_read_with_invalid_address_raises(self) -> None:
        with self.assertRaises(InvalidSolanaAddressError):
            cache_mod.read("not-a-wallet", cache_root=Path("."))

    def test_write_with_invalid_address_raises(self) -> None:
        with self.assertRaises(InvalidSolanaAddressError):
            cache_mod.write("not-a-wallet", _empty_df(), _meta(), cache_root=Path("."))

    def test_forget_with_invalid_address_raises(self) -> None:
        with self.assertRaises(InvalidSolanaAddressError):
            cache_mod.forget("../etc", cache_root=Path("."))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/dashboard/test_cache.py -v`
Expected: every test errors out with `ModuleNotFoundError: No module named 'ai_accountant.dashboard.cache'`.

- [ ] **Step 3: Implement cache.py**

Create `src/ai_accountant/dashboard/cache.py`:

```python
"""Filesystem cache for fetched wallet DataFrames."""

from __future__ import annotations

import json
import os
import pickle
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..addresses import validate_address

SCHEMA_VERSION = 1
_ADDRESS_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


@dataclass(frozen=True)
class CachedWallet:
    address: str
    fetched_at: str
    row_count: int
    earliest_tx: str
    latest_tx: str
    pages_fetched: int
    max_pages_at_fetch: int


def _wallet_dir(address: str, *, cache_root: Path) -> Path:
    validated = validate_address(address)
    if not _ADDRESS_PATTERN.match(validated):
        # validate_address already enforces this; the regex is belt-and-braces.
        from ..exceptions import InvalidSolanaAddressError

        raise InvalidSolanaAddressError(f"Address fails directory-name regex: {validated!r}")
    return Path(cache_root) / validated


def read(address: str, *, cache_root: Path) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    wallet_dir = _wallet_dir(address, cache_root=cache_root)
    pkl_path = wallet_dir / "transactions.pkl"
    meta_path = wallet_dir / "meta.json"
    if not pkl_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if meta.get("schema_version") != SCHEMA_VERSION:
        return None
    try:
        with pkl_path.open("rb") as fh:
            df = pickle.load(fh)
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ImportError):
        return None
    if not isinstance(df, pd.DataFrame):
        return None
    return df, meta


def write(
    address: str,
    df: pd.DataFrame,
    meta: dict[str, Any],
    *,
    cache_root: Path,
) -> None:
    wallet_dir = _wallet_dir(address, cache_root=cache_root)
    wallet_dir.mkdir(parents=True, exist_ok=True)

    pkl_path = wallet_dir / "transactions.pkl"
    meta_path = wallet_dir / "meta.json"
    pkl_tmp = pkl_path.with_suffix(".pkl.tmp")
    meta_tmp = meta_path.with_suffix(".json.tmp")

    payload = dict(meta)
    payload["schema_version"] = SCHEMA_VERSION

    with pkl_tmp.open("wb") as fh:
        pickle.dump(df, fh, protocol=5)
    meta_tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    os.replace(pkl_tmp, pkl_path)
    os.replace(meta_tmp, meta_path)


def forget(address: str, *, cache_root: Path) -> bool:
    wallet_dir = _wallet_dir(address, cache_root=cache_root)
    if not wallet_dir.exists():
        return False
    shutil.rmtree(wallet_dir)
    return True


def list_wallets(*, cache_root: Path) -> list[CachedWallet]:
    root = Path(cache_root)
    if not root.exists():
        return []
    out: list[CachedWallet] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if not _ADDRESS_PATTERN.match(child.name):
            continue
        meta_path = child / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("schema_version") != SCHEMA_VERSION:
            continue
        out.append(
            CachedWallet(
                address=str(meta.get("address") or child.name),
                fetched_at=str(meta.get("fetched_at") or ""),
                row_count=int(meta.get("row_count") or 0),
                earliest_tx=str(meta.get("earliest_tx") or ""),
                latest_tx=str(meta.get("latest_tx") or ""),
                pages_fetched=int(meta.get("pages_fetched") or 0),
                max_pages_at_fetch=int(meta.get("max_pages_at_fetch") or 0),
            )
        )
    out.sort(key=lambda w: w.fetched_at, reverse=True)
    return out


__all__ = ["SCHEMA_VERSION", "CachedWallet", "read", "write", "forget", "list_wallets"]
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/dashboard/test_cache.py -v`
Expected: all 12 tests pass.

- [ ] **Step 5: Run lint**

Run: `ruff check src/ai_accountant/dashboard/cache.py tests/dashboard/test_cache.py`
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add src/ai_accountant/dashboard/cache.py tests/dashboard/test_cache.py
git commit -m "feat(dashboard): filesystem cache (read/write/list/forget) with atomic writes"
```

---

## Task 3: filters.py

**Files:**
- Create: `src/ai_accountant/dashboard/filters.py`
- Create: `tests/dashboard/test_filters.py`

**Goal:** `FilterSpec` dataclass that parses a `werkzeug.datastructures.MultiDict`-shaped object (or any `Mapping`) into a typed filter, applies the filter to a DataFrame, and round-trips back to a querystring. Total: never raises on malformed input.

### Module contract

```python
@dataclass(frozen=True)
class FilterSpec:
    date_from: date | None
    date_to: date | None
    token: str | None      # mint string or "SOL"
    type: str | None
    status: str | None     # "succeeded" | "failed" | None
    source: str | None
    q: str | None
    page: int              # >= 1, default 1

    @classmethod
    def from_querystring(cls, params: Mapping[str, str]) -> FilterSpec: ...
    def apply(self, df: pd.DataFrame) -> pd.DataFrame: ...
    def to_querystring(self) -> str: ...
    def is_active(self) -> bool: ...      # True if any filter narrows the data
```

- [ ] **Step 1: Write failing tests**

Create `tests/dashboard/test_filters.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/dashboard/test_filters.py -v`
Expected: every test errors with `ModuleNotFoundError`.

- [ ] **Step 3: Implement filters.py**

Create `src/ai_accountant/dashboard/filters.py`:

```python
"""Querystring -> typed filter -> DataFrame mask."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from urllib.parse import urlencode

import pandas as pd

_VALID_STATUSES = ("succeeded", "failed")


@dataclass(frozen=True)
class FilterSpec:
    date_from: date | None = None
    date_to: date | None = None
    token: str | None = None
    type: str | None = None
    status: str | None = None
    source: str | None = None
    q: str | None = None
    page: int = 1

    @classmethod
    def from_querystring(cls, params: Mapping[str, Any]) -> "FilterSpec":
        get = lambda k: _clean(params.get(k))  # noqa: E731

        date_from = _parse_date(get("from"))
        date_to = _parse_date(get("to"))
        status = get("status")
        if status not in _VALID_STATUSES:
            status = None
        page_raw = get("page") or "1"
        try:
            page = int(page_raw)
            if page < 1:
                page = 1
        except (TypeError, ValueError):
            page = 1
        return cls(
            date_from=date_from,
            date_to=date_to,
            token=get("token"),
            type=get("type"),
            status=status,
            source=get("source"),
            q=get("q"),
            page=page,
        )

    def is_active(self) -> bool:
        return any(
            v is not None
            for v in (self.date_from, self.date_to, self.token, self.type, self.status, self.source, self.q)
        )

    def to_querystring(self) -> str:
        out: list[tuple[str, str]] = []
        if self.date_from:
            out.append(("from", self.date_from.isoformat()))
        if self.date_to:
            out.append(("to", self.date_to.isoformat()))
        if self.token:
            out.append(("token", self.token))
        if self.type:
            out.append(("type", self.type))
        if self.status:
            out.append(("status", self.status))
        if self.source:
            out.append(("source", self.source))
        if self.q:
            out.append(("q", self.q))
        if self.page > 1:
            out.append(("page", str(self.page)))
        return urlencode(out)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()

        mask = pd.Series([True] * len(df), index=df.index)

        if self.date_from is not None:
            cutoff = int(datetime.combine(self.date_from, time.min, timezone.utc).timestamp())
            mask &= df["timestamp_unix"].fillna(0).astype("int64") >= cutoff
        if self.date_to is not None:
            cutoff = int(datetime.combine(self.date_to, time.max, timezone.utc).timestamp())
            mask &= df["timestamp_unix"].fillna(0).astype("int64") <= cutoff
        if self.status is not None:
            mask &= df["status"] == self.status
        if self.type is not None:
            mask &= df["transaction_type"] == self.type
        if self.source is not None:
            mask &= df["source"] == self.source
        if self.token is not None:
            mask &= df["net_flow"].apply(lambda nf: _net_flow_has_key(nf, self.token))
        if self.q is not None:
            needle = self.q.casefold()
            mask &= df.apply(lambda row: _row_matches_q(row, needle), axis=1)
        return df[mask].reset_index(drop=True)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _net_flow_has_key(net_flow: Any, key: str) -> bool:
    if not isinstance(net_flow, Mapping):
        return False
    return key in net_flow


def _row_matches_q(row: pd.Series, needle: str) -> bool:
    for col in ("description", "source", "transaction_type"):
        value = row.get(col)
        if value is None:
            continue
        if needle in str(value).casefold():
            return True
    return False


__all__ = ["FilterSpec"]
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/dashboard/test_filters.py -v`
Expected: all 17 tests pass.

- [ ] **Step 5: Run lint**

Run: `ruff check src/ai_accountant/dashboard/filters.py tests/dashboard/test_filters.py`
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add src/ai_accountant/dashboard/filters.py tests/dashboard/test_filters.py
git commit -m "feat(dashboard): FilterSpec — querystring parse / apply / round-trip"
```

---

## Task 4: charts.py

**Files:**
- Create: `src/ai_accountant/dashboard/charts.py`
- Create: `tests/dashboard/test_charts.py`

**Goal:** Two pure SVG renderers. No DataFrame coupling, no Jinja coupling. Both functions return well-formed `<svg>` strings; both gracefully handle empty / degenerate input.

### Module contract

Already shown in spec §6.1.

- [ ] **Step 1: Write failing tests**

Create `tests/dashboard/test_charts.py`:

```python
from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant.dashboard.charts import render_bar_svg, render_line_svg


def _parse_svg(svg: str) -> ET.Element:
    """Parse an SVG string, raising if it's not well-formed XML."""
    return ET.fromstring(svg)


class LineChartTests(unittest.TestCase):
    def test_empty_returns_well_formed_svg_with_message(self) -> None:
        svg = render_line_svg([])
        root = _parse_svg(svg)
        self.assertEqual(root.tag.rsplit("}", 1)[-1], "svg")
        self.assertIn("No data in range.", svg)

    def test_custom_empty_message_used(self) -> None:
        svg = render_line_svg([], empty_message="Pick a wider window.")
        self.assertIn("Pick a wider window.", svg)

    def test_happy_path_contains_path_elements(self) -> None:
        points = [
            (date(2025, 1, 1), Decimal("0.5")),
            (date(2025, 1, 2), Decimal("0.7")),
            (date(2025, 1, 3), Decimal("0.6")),
        ]
        svg = render_line_svg(points, y_label="SOL")
        root = _parse_svg(svg)
        self.assertEqual(root.tag.rsplit("}", 1)[-1], "svg")
        # exactly one path for the line and one for the area fill
        path_count = sum(1 for el in root.iter() if el.tag.endswith("path"))
        self.assertGreaterEqual(path_count, 2)

    def test_single_point_does_not_raise(self) -> None:
        svg = render_line_svg([(date(2025, 1, 1), Decimal("1"))])
        _parse_svg(svg)  # well-formed

    def test_negative_values_keep_zero_baseline_visible(self) -> None:
        points = [(date(2025, 1, 1), Decimal("-5")), (date(2025, 1, 2), Decimal("-2"))]
        svg = render_line_svg(points)
        # Zero baseline must appear as a horizontal line; just check the SVG renders.
        _parse_svg(svg)


class BarChartTests(unittest.TestCase):
    def test_empty_returns_well_formed_svg_with_message(self) -> None:
        svg = render_bar_svg([])
        _parse_svg(svg)
        self.assertIn("No transactions in range.", svg)

    def test_bar_count_matches_bins_with_data(self) -> None:
        buckets = [
            (date(2025, 1, 1), {"succeeded": 3, "failed": 1}),
            (date(2025, 1, 2), {"succeeded": 0, "failed": 0}),  # skipped
            (date(2025, 1, 3), {"succeeded": 5, "failed": 0}),
        ]
        svg = render_bar_svg(buckets)
        root = _parse_svg(svg)
        rect_count = sum(1 for el in root.iter() if el.tag.endswith("rect"))
        # 2 non-empty bins * 2 stack segments + 2 legend swatches = 6
        self.assertGreaterEqual(rect_count, 4)
        self.assertIn("succeeded", svg)
        self.assertIn("failed", svg)

    def test_all_zero_buckets_renders_empty_message(self) -> None:
        buckets = [(date(2025, 1, 1), {"succeeded": 0, "failed": 0})]
        svg = render_bar_svg(buckets)
        self.assertIn("No transactions in range.", svg)


class SvgEscapingTests(unittest.TestCase):
    def test_y_label_is_escaped(self) -> None:
        svg = render_line_svg([], y_label="<script>alert(1)</script>")
        self.assertNotIn("<script>", svg)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/dashboard/test_charts.py -v`
Expected: every test errors with `ModuleNotFoundError`.

- [ ] **Step 3: Implement charts.py**

Create `src/ai_accountant/dashboard/charts.py`:

```python
"""Hand-rolled inline-SVG chart renderers (no JS, no third-party deps)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from html import escape

LINE_WIDTH = 880
LINE_HEIGHT = 220
BAR_WIDTH = 880
BAR_HEIGHT = 220
LEFT_MARGIN = 40
RIGHT_MARGIN = 8
TOP_MARGIN = 8
BOTTOM_MARGIN = 24


def render_line_svg(
    points: Sequence[tuple[date, Decimal]],
    *,
    width: int = LINE_WIDTH,
    height: int = LINE_HEIGHT,
    y_label: str = "",
    empty_message: str = "No data in range.",
) -> str:
    if not points:
        return _empty_svg(width, height, empty_message)

    sorted_points = sorted(points, key=lambda p: p[0])
    sorted_points = _decimate(sorted_points, max_points=400)

    xs = [p[0] for p in sorted_points]
    ys = [float(p[1]) for p in sorted_points]
    y_min = min(0.0, min(ys))
    y_max = max(0.0, max(ys))
    if y_min == y_max:
        y_max = y_min + 1.0  # avoid division by zero

    plot_w = width - LEFT_MARGIN - RIGHT_MARGIN
    plot_h = height - TOP_MARGIN - BOTTOM_MARGIN

    def project(i: int, y: float) -> tuple[float, float]:
        if len(sorted_points) == 1:
            x = LEFT_MARGIN + plot_w / 2
        else:
            x = LEFT_MARGIN + (i / (len(sorted_points) - 1)) * plot_w
        py = TOP_MARGIN + plot_h - ((y - y_min) / (y_max - y_min)) * plot_h
        return x, py

    line_points = [project(i, y) for i, y in enumerate(ys)]
    line_d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in line_points)

    base_y = TOP_MARGIN + plot_h - ((0.0 - y_min) / (y_max - y_min)) * plot_h
    area_d = (
        f"M {line_points[0][0]:.1f} {base_y:.1f} "
        + " L ".join(f"{x:.1f} {y:.1f}" for x, y in line_points)
        + f" L {line_points[-1][0]:.1f} {base_y:.1f} Z"
    )

    y_ticks = _line_y_ticks(y_min, y_max)
    y_tick_lines: list[str] = []
    for tv in y_ticks:
        ty = TOP_MARGIN + plot_h - ((tv - y_min) / (y_max - y_min)) * plot_h
        y_tick_lines.append(
            f'<text class="ai-chart-tick" x="{LEFT_MARGIN - 4:.1f}" y="{ty:.1f}" '
            f'text-anchor="end" dominant-baseline="middle">{escape(_fmt_y(tv))}</text>'
        )

    x_tick_count = min(5, len(sorted_points))
    x_tick_lines: list[str] = []
    if x_tick_count >= 2:
        for k in range(x_tick_count):
            idx = round(k * (len(sorted_points) - 1) / (x_tick_count - 1))
            tx, _ = project(idx, ys[idx])
            label = escape(xs[idx].isoformat())
            x_tick_lines.append(
                f'<text class="ai-chart-tick" x="{tx:.1f}" '
                f'y="{TOP_MARGIN + plot_h + 14:.1f}" text-anchor="middle">{label}</text>'
            )

    return _wrap_svg(
        width,
        height,
        title=f"{y_label or 'Series'} over time",
        body="\n".join(
            [
                f'<line class="ai-chart-baseline" x1="{LEFT_MARGIN}" y1="{base_y:.1f}" '
                f'x2="{width - RIGHT_MARGIN}" y2="{base_y:.1f}" />',
                f'<path class="ai-chart-area" d="{area_d}" />',
                f'<path class="ai-chart-line" d="{line_d}" />',
                *y_tick_lines,
                *x_tick_lines,
                _y_label_text(y_label, height),
            ]
        ),
        styles=_LINE_STYLES,
    )


def render_bar_svg(
    buckets: Sequence[tuple[date, dict[str, int]]],
    *,
    series_order: tuple[str, ...] = ("succeeded", "failed"),
    width: int = BAR_WIDTH,
    height: int = BAR_HEIGHT,
    empty_message: str = "No transactions in range.",
) -> str:
    if not buckets:
        return _empty_svg(width, height, empty_message)

    active = [b for b in buckets if sum(b[1].get(s, 0) for s in series_order) > 0]
    if not active:
        return _empty_svg(width, height, empty_message)

    plot_w = width - LEFT_MARGIN - RIGHT_MARGIN
    plot_h = height - TOP_MARGIN - BOTTOM_MARGIN
    n = len(active)
    band = plot_w / n
    bar_w = band * 0.8
    bar_pad = (band - bar_w) / 2

    max_total = max(sum(b[1].get(s, 0) for s in series_order) for b in active)
    if max_total == 0:
        return _empty_svg(width, height, empty_message)

    rects: list[str] = []
    label_lines: list[str] = []
    every_n = max(1, n // 8)
    for i, (bin_start, counts) in enumerate(active):
        x_left = LEFT_MARGIN + i * band + bar_pad
        accumulated = 0
        for series in series_order:
            value = int(counts.get(series, 0) or 0)
            if value <= 0:
                continue
            seg_h = (value / max_total) * plot_h
            top_y = TOP_MARGIN + plot_h - accumulated - seg_h
            rects.append(
                f'<rect class="ai-chart-bar ai-chart-bar-{escape(series)}" '
                f'x="{x_left:.1f}" y="{top_y:.1f}" '
                f'width="{bar_w:.1f}" height="{seg_h:.1f}" />'
            )
            accumulated += seg_h
        if i % every_n == 0:
            label_lines.append(
                f'<text class="ai-chart-tick" x="{x_left + bar_w / 2:.1f}" '
                f'y="{TOP_MARGIN + plot_h + 14:.1f}" text-anchor="middle">'
                f"{escape(bin_start.isoformat())}</text>"
            )

    legend_items: list[str] = []
    for j, series in enumerate(series_order):
        ly = TOP_MARGIN + 4 + j * 14
        legend_items.append(
            f'<rect class="ai-chart-bar-{escape(series)}" '
            f'x="{width - RIGHT_MARGIN - 80}" y="{ly}" width="10" height="10" />'
            f'<text class="ai-chart-legend" x="{width - RIGHT_MARGIN - 66}" '
            f'y="{ly + 9}">{escape(series)}</text>'
        )

    return _wrap_svg(
        width,
        height,
        title="Activity over time",
        body="\n".join([*rects, *label_lines, *legend_items]),
        styles=_BAR_STYLES,
    )


def _decimate(points: list[tuple[date, Decimal]], *, max_points: int) -> list[tuple[date, Decimal]]:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    return [points[int(i * step)] for i in range(max_points)]


def _fmt_y(value: float) -> str:
    if abs(value) < 1e-9:
        return "0"
    if abs(value) >= 1:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _line_y_ticks(y_min: float, y_max: float) -> list[float]:
    if y_max <= y_min:
        return [y_min]
    span = y_max - y_min
    return [y_min + span * k / 3 for k in range(4)]


def _y_label_text(y_label: str, height: int) -> str:
    if not y_label:
        return ""
    return (
        f'<text class="ai-chart-axis-label" x="6" y="{height / 2:.1f}" '
        f'transform="rotate(-90 6 {height / 2:.1f})" '
        f'text-anchor="middle" dominant-baseline="hanging">{escape(y_label)}</text>'
    )


def _empty_svg(width: int, height: int, message: str) -> str:
    return _wrap_svg(
        width,
        height,
        title="Empty chart",
        body=(
            f'<text class="ai-chart-empty" x="{width / 2:.1f}" y="{height / 2:.1f}" '
            f'text-anchor="middle" dominant-baseline="middle">{escape(message)}</text>'
        ),
        styles=_EMPTY_STYLES,
    )


def _wrap_svg(width: int, height: int, *, title: str, body: str, styles: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title>"
        f"<style>{styles}</style>"
        f"{body}"
        f"</svg>"
    )


_LINE_STYLES = (
    ".ai-chart-line { fill: none; stroke: #126a72; stroke-width: 2; }"
    ".ai-chart-area { fill: rgba(18, 106, 114, 0.15); stroke: none; }"
    ".ai-chart-baseline { stroke: #66737b; stroke-dasharray: 2 3; }"
    ".ai-chart-tick { fill: #66737b; font: 11px sans-serif; }"
    ".ai-chart-axis-label { fill: #172126; font: 11px sans-serif; }"
)
_BAR_STYLES = (
    ".ai-chart-bar { stroke: none; }"
    ".ai-chart-bar-succeeded { fill: #19734d; }"
    ".ai-chart-bar-failed { fill: #a83d31; }"
    ".ai-chart-tick { fill: #66737b; font: 11px sans-serif; }"
    ".ai-chart-legend { fill: #172126; font: 11px sans-serif; }"
)
_EMPTY_STYLES = ".ai-chart-empty { fill: #66737b; font: 13px sans-serif; }"


__all__ = ["render_line_svg", "render_bar_svg"]
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/dashboard/test_charts.py -v`
Expected: all 9 tests pass.

- [ ] **Step 5: Run lint**

Run: `ruff check src/ai_accountant/dashboard/charts.py tests/dashboard/test_charts.py`
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add src/ai_accountant/dashboard/charts.py tests/dashboard/test_charts.py
git commit -m "feat(dashboard): inline-SVG line and stacked-bar chart renderers"
```

---

## Task 5: views.py

**Files:**
- Create: `src/ai_accountant/dashboard/views.py`
- Create: `tests/dashboard/conftest.py`
- Create: `tests/dashboard/test_views.py`

**Goal:** Pure-Python builders that produce the dicts the Jinja templates render. Two public functions: `wallet_page(df, spec, meta) -> dict`, `transaction_detail(df, sig) -> dict`. Reuses `report.py` private builders for KPI / asset-flow / mix / risk / tx-table parity. Computes the chart data series.

### Module contract

```python
def wallet_page(
    df: pd.DataFrame,
    *,
    spec: FilterSpec,
    meta: dict | None,
    address: str,
) -> dict[str, Any]: ...

def transaction_detail(df: pd.DataFrame, signature: str, *, address: str) -> dict[str, Any]: ...
```

`wallet_page` returns:
```python
{
    "address": str,
    "address_short": str,
    "meta": dict | None,
    "filter": FilterSpec,
    "filter_active": bool,
    "kpis": dict[str, str],
    "asset_flow": list[dict],
    "transaction_mix": list[dict],
    "review_queue": list[dict],
    "transactions": list[dict],
    "transactions_total": int,
    "transactions_page": int,
    "transactions_pages": int,
    "transactions_page_size": int,
    "balance_chart_svg": str,
    "activity_chart_svg": str,
    "filter_options": {
        "tokens": list[tuple[str, str]],   # [(value, label)]
        "types": list[str],
        "sources": list[str],
    },
}
```

- [ ] **Step 1: Write the shared conftest**

Create `tests/dashboard/conftest.py`:

```python
"""Shared fixtures for dashboard tests."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@pytest.fixture
def synthetic_df() -> pd.DataFrame:
    rows = []
    for i, ts, status, ttype, source, fee in [
        (0, 1735689600, "succeeded", "swap", "JUPITER", Decimal("0.00018")),
        (1, 1736294400, "failed", "transfer", "SYSTEM", Decimal("0.000005")),
        (2, 1738972800, "succeeded", "swap", "RAYDIUM", Decimal("0.00012")),
    ]:
        row = {col: None for col in DATAFRAME_COLUMNS}
        row["signature"] = f"sig-{i}"
        row["slot"] = 1000 + i
        row["timestamp_unix"] = ts
        row["timestamp"] = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        row["transaction_type"] = ttype
        row["source"] = source
        row["description"] = f"Test transaction {i}"
        row["fee_lamports"] = int(fee * Decimal("1e9"))
        row["fee_sol"] = fee
        row["fee_paid_by_wallet"] = True
        row["fee_payer"] = WALLET
        row["status"] = status
        row["native_in_sol"] = Decimal("0") if i != 0 else Decimal("1")
        row["native_out_sol"] = Decimal("0.5") if i == 0 else Decimal("0")
        row["native_net_sol"] = (
            Decimal("0.5") if i == 0 else (Decimal("-0.000005") if i == 1 else Decimal("0"))
        )
        if i == 0:
            row["net_flow"] = {"SOL": Decimal("0.5"), USDC_MINT: Decimal("100")}
        elif i == 2:
            row["net_flow"] = {USDC_MINT: Decimal("-50")}
        else:
            row["net_flow"] = {"SOL": Decimal("-0.000005")}
        row["token_flow_details"] = []
        row["token_in_summary"] = "" if i == 1 else "100 USDC"
        row["token_out_summary"] = "" if i != 2 else "50 USDC"
        row["token_net_summary"] = ""
        row["net_flow_summary"] = "" if i == 1 else "0.5 SOL, 100 USDC (in)"
        row["movements_in"] = []
        row["movements_out"] = []
        row["raw_native_transfers"] = []
        row["raw_token_transfers"] = []
        row["transaction_error"] = None if status == "succeeded" else {"InstructionError": [0]}
        rows.append(row)
    df = pd.DataFrame(rows, columns=DATAFRAME_COLUMNS)
    return df


@pytest.fixture
def wallet_address() -> str:
    return WALLET
```

- [ ] **Step 2: Write failing view tests**

Create `tests/dashboard/test_views.py`:

```python
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS
from ai_accountant.dashboard.filters import FilterSpec
from ai_accountant.dashboard.views import transaction_detail, wallet_page

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _row(**overrides):
    row = {col: None for col in DATAFRAME_COLUMNS}
    row.update(
        signature="sig-x",
        slot=10,
        timestamp_unix=1735689600,
        timestamp=datetime.fromtimestamp(1735689600, timezone.utc).isoformat(),
        transaction_type="swap",
        source="JUPITER",
        description="example",
        fee_lamports=180_000,
        fee_sol=Decimal("0.00018"),
        fee_paid_by_wallet=True,
        fee_payer=WALLET,
        status="succeeded",
        native_in_sol=Decimal("1"),
        native_out_sol=Decimal("0.5"),
        native_net_sol=Decimal("0.5"),
        net_flow={"SOL": Decimal("0.5"), USDC_MINT: Decimal("100")},
        token_flow_details=[],
        token_in_summary="100 USDC",
        token_out_summary="",
        token_net_summary="",
        net_flow_summary="0.5 SOL, 100 USDC (in)",
        movements_in=[],
        movements_out=[],
        raw_native_transfers=[],
        raw_token_transfers=[],
        transaction_error=None,
    )
    row.update(overrides)
    return row


def _df(rows):
    return pd.DataFrame(rows, columns=DATAFRAME_COLUMNS)


def _meta():
    return {
        "address": WALLET,
        "fetched_at": "2026-05-08T14:33:21Z",
        "row_count": 1,
        "earliest_tx": "2025-01-01",
        "latest_tx": "2025-01-01",
        "pages_fetched": 5,
        "max_pages_at_fetch": 5,
        "schema_version": 1,
    }


class WalletPageTests(unittest.TestCase):
    def test_returns_expected_top_level_keys(self) -> None:
        ctx = wallet_page(_df([_row()]), spec=FilterSpec(), meta=_meta(), address=WALLET)
        for key in (
            "address",
            "address_short",
            "meta",
            "filter",
            "filter_active",
            "kpis",
            "asset_flow",
            "transaction_mix",
            "review_queue",
            "transactions",
            "transactions_total",
            "transactions_page",
            "transactions_pages",
            "transactions_page_size",
            "balance_chart_svg",
            "activity_chart_svg",
            "filter_options",
        ):
            self.assertIn(key, ctx, f"missing key: {key}")

    def test_kpis_match_report_module_for_same_frame(self) -> None:
        from ai_accountant.report import _wallet_metrics

        df = _df([_row(), _row(signature="sig-y", status="failed")])
        ctx = wallet_page(df, spec=FilterSpec(), meta=_meta(), address=WALLET)
        report_metrics = _wallet_metrics(df, WALLET, generated_at=datetime.now(timezone.utc))
        self.assertEqual(ctx["kpis"]["total"], report_metrics["total"])
        self.assertEqual(ctx["kpis"]["succeeded"], report_metrics["succeeded"])
        self.assertEqual(ctx["kpis"]["failed"], report_metrics["failed"])

    def test_filter_active_flag_reflects_spec(self) -> None:
        ctx = wallet_page(_df([_row()]), spec=FilterSpec(), meta=_meta(), address=WALLET)
        self.assertFalse(ctx["filter_active"])

        ctx2 = wallet_page(
            _df([_row()]),
            spec=FilterSpec(status="failed"),
            meta=_meta(),
            address=WALLET,
        )
        self.assertTrue(ctx2["filter_active"])

    def test_filter_options_extracted_from_full_frame(self) -> None:
        df = _df([_row(), _row(signature="sig-y", source="RAYDIUM", transaction_type="transfer")])
        ctx = wallet_page(df, spec=FilterSpec(), meta=_meta(), address=WALLET)
        sources = ctx["filter_options"]["sources"]
        types = ctx["filter_options"]["types"]
        self.assertIn("JUPITER", sources)
        self.assertIn("RAYDIUM", sources)
        self.assertIn("swap", types)
        self.assertIn("transfer", types)

    def test_transactions_paginated(self) -> None:
        rows = [_row(signature=f"sig-{i}") for i in range(150)]
        ctx = wallet_page(_df(rows), spec=FilterSpec(page=2), meta=_meta(), address=WALLET)
        self.assertEqual(ctx["transactions_total"], 150)
        self.assertEqual(ctx["transactions_page"], 2)
        self.assertEqual(ctx["transactions_pages"], 2)
        self.assertEqual(ctx["transactions_page_size"], 100)
        self.assertEqual(len(ctx["transactions"]), 50)

    def test_balance_chart_present_even_when_empty(self) -> None:
        ctx = wallet_page(_df([]), spec=FilterSpec(), meta=_meta(), address=WALLET)
        self.assertIn("<svg", ctx["balance_chart_svg"])
        self.assertIn("<svg", ctx["activity_chart_svg"])

    def test_meta_none_yields_empty_state_friendly_context(self) -> None:
        ctx = wallet_page(_df([]), spec=FilterSpec(), meta=None, address=WALLET)
        self.assertIsNone(ctx["meta"])
        self.assertEqual(ctx["transactions_total"], 0)


class TransactionDetailTests(unittest.TestCase):
    def test_returns_row_dict_for_known_signature(self) -> None:
        ctx = transaction_detail(_df([_row()]), "sig-x", address=WALLET)
        self.assertEqual(ctx["signature"], "sig-x")
        self.assertEqual(ctx["address"], WALLET)
        self.assertEqual(ctx["status"], "succeeded")
        self.assertIn("explorer_url", ctx)

    def test_unknown_signature_raises_keyerror(self) -> None:
        with self.assertRaises(KeyError):
            transaction_detail(_df([_row()]), "nope", address=WALLET)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests to confirm they fail**

Run: `pytest tests/dashboard/test_views.py -v`
Expected: every test errors with `ModuleNotFoundError`.

- [ ] **Step 4: Implement views.py**

Create `src/ai_accountant/dashboard/views.py`:

```python
"""Build template context dicts from a (filtered) DataFrame."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from html import escape
from typing import Any

import pandas as pd

from ..report import (
    _asset_flow_rows,
    _format_decimal,
    _risk_rows,
    _short,
    _to_decimal,
    _transaction_rows,
    _transaction_type_rows,
    _wallet_metrics,
)
from .charts import render_bar_svg, render_line_svg
from .filters import FilterSpec

PAGE_SIZE = 100
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # for label fallback


def wallet_page(
    df: pd.DataFrame,
    *,
    spec: FilterSpec,
    meta: dict[str, Any] | None,
    address: str,
) -> dict[str, Any]:
    full_df = df if df is not None else pd.DataFrame()
    filtered = spec.apply(full_df) if not full_df.empty else full_df

    sorted_filtered = _sorted_desc(filtered)
    total = len(sorted_filtered)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(spec.page, pages)
    start = (page - 1) * PAGE_SIZE
    page_slice = sorted_filtered.iloc[start : start + PAGE_SIZE]

    kpis = _wallet_metrics(filtered, address, generated_at=datetime.now(timezone.utc))
    asset_flow = _asset_flow_rows(filtered)
    mix = _transaction_type_rows(filtered)
    risk = _risk_rows(filtered)
    tx_rows = _transaction_rows(page_slice, limit=PAGE_SIZE)

    balance_points = _balance_points(filtered)
    activity_buckets = _activity_buckets(filtered)

    return {
        "address": address,
        "address_short": _short(address, 8),
        "meta": meta,
        "filter": spec,
        "filter_active": spec.is_active(),
        "kpis": kpis,
        "asset_flow": asset_flow,
        "transaction_mix": mix,
        "review_queue": risk,
        "transactions": tx_rows,
        "transactions_total": total,
        "transactions_page": page,
        "transactions_pages": pages,
        "transactions_page_size": PAGE_SIZE,
        "balance_chart_svg": render_line_svg(balance_points, y_label="SOL net"),
        "activity_chart_svg": render_bar_svg(activity_buckets),
        "filter_options": _filter_options(full_df),
    }


def transaction_detail(df: pd.DataFrame, signature: str, *, address: str) -> dict[str, Any]:
    if df is None or df.empty:
        raise KeyError(signature)
    matches = df[df["signature"] == signature]
    if matches.empty:
        raise KeyError(signature)
    row = matches.iloc[0]

    timestamp_unix = row.get("timestamp_unix")
    iso = ""
    if isinstance(timestamp_unix, (int, float)) and timestamp_unix:
        iso = datetime.fromtimestamp(int(timestamp_unix), timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    net_flow = row.get("net_flow") or {}
    net_flow_rows = []
    for key, value in net_flow.items() if isinstance(net_flow, dict) else []:
        net_flow_rows.append(
            {
                "key": str(key),
                "label": _flow_label(key, row.get("token_flow_details") or []),
                "amount": _format_decimal(value, signed=True),
            }
        )

    raw_pairs = [(c, _stringify(row.get(c))) for c in df.columns]

    return {
        "address": address,
        "address_short": _short(address, 8),
        "signature": str(row.get("signature") or ""),
        "signature_short": _short(str(row.get("signature") or ""), 8),
        "status": str(row.get("status") or "unknown"),
        "transaction_type": str(row.get("transaction_type") or "unknown"),
        "source": str(row.get("source") or "unknown"),
        "timestamp_iso": iso,
        "fee_sol": _format_decimal(row.get("fee_sol")),
        "fee_paid_by_wallet": bool(row.get("fee_paid_by_wallet")),
        "description": str(row.get("description") or ""),
        "net_flow_rows": net_flow_rows,
        "movements_in": list(row.get("movements_in") or []),
        "movements_out": list(row.get("movements_out") or []),
        "explorer_url": (
            f"https://explorer.solana.com/tx/{escape(str(row.get('signature') or ''))}"
        ),
        "raw_pairs": raw_pairs,
    }


def _sorted_desc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "timestamp_unix" not in df.columns:
        return df.copy() if not df.empty else df
    return df.sort_values("timestamp_unix", ascending=False, kind="stable").reset_index(drop=True)


def _balance_points(df: pd.DataFrame) -> list[tuple[date, Decimal]]:
    if df.empty or "native_net_sol" not in df.columns:
        return []
    asc = df.sort_values("timestamp_unix", ascending=True, kind="stable")
    daily: dict[date, Decimal] = {}
    for _, row in asc.iterrows():
        ts = row.get("timestamp_unix")
        if ts is None:
            continue
        try:
            day = datetime.fromtimestamp(int(ts), timezone.utc).date()
        except (OSError, TypeError, ValueError):
            continue
        daily[day] = daily.get(day, Decimal("0")) + _to_decimal(row.get("native_net_sol"))

    points: list[tuple[date, Decimal]] = []
    cumulative = Decimal("0")
    for day in sorted(daily):
        cumulative += daily[day]
        points.append((day, cumulative))
    return points


def _activity_buckets(df: pd.DataFrame) -> list[tuple[date, dict[str, int]]]:
    if df.empty or "timestamp_unix" not in df.columns:
        return []
    asc = df.sort_values("timestamp_unix", ascending=True, kind="stable")
    days: list[date] = []
    for ts in asc["timestamp_unix"]:
        if ts is None:
            continue
        try:
            days.append(datetime.fromtimestamp(int(ts), timezone.utc).date())
        except (OSError, TypeError, ValueError):
            continue
    if not days:
        return []
    span = (days[-1] - days[0]).days
    if span <= 60:
        def bin_fn(d: date) -> date:
            return d
    elif span <= 365:
        def bin_fn(d: date) -> date:
            iso = d.isocalendar()
            return date.fromisocalendar(iso.year, iso.week, 1)
    else:
        def bin_fn(d: date) -> date:
            return date(d.year, d.month, 1)

    buckets: dict[date, dict[str, int]] = {}
    for _, row in asc.iterrows():
        ts = row.get("timestamp_unix")
        if ts is None:
            continue
        try:
            d = datetime.fromtimestamp(int(ts), timezone.utc).date()
        except (OSError, TypeError, ValueError):
            continue
        key = bin_fn(d)
        slot = buckets.setdefault(key, {"succeeded": 0, "failed": 0})
        status = str(row.get("status") or "")
        if status in slot:
            slot[status] += 1
    return [(k, buckets[k]) for k in sorted(buckets)]


def _filter_options(df: pd.DataFrame) -> dict[str, list]:
    tokens: list[tuple[str, str]] = [("SOL", "SOL")]
    types: set[str] = set()
    sources: set[str] = set()
    if df.empty:
        return {"tokens": tokens, "types": [], "sources": []}

    seen_mints: set[str] = set()
    for _, row in df.iterrows():
        nf = row.get("net_flow")
        if isinstance(nf, dict):
            for key in nf:
                if key == "SOL":
                    continue
                if key in seen_mints:
                    continue
                seen_mints.add(key)
                label = _flow_label(key, row.get("token_flow_details") or [])
                tokens.append((str(key), label))
        ttype = row.get("transaction_type")
        if ttype:
            types.add(str(ttype))
        src = row.get("source")
        if src:
            sources.add(str(src))
    return {
        "tokens": tokens,
        "types": sorted(types),
        "sources": sorted(sources),
    }


def _flow_label(key: str, token_flow_details: list) -> str:
    if key == "SOL":
        return "SOL"
    for entry in token_flow_details or []:
        if isinstance(entry, dict) and entry.get("mint") == key:
            symbol = entry.get("symbol") or "Token"
            return f"{symbol} ({_short(str(key), 6)})"
    return f"Token ({_short(str(key), 6)})"


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return _format_decimal(value)
    return str(value)


__all__ = ["wallet_page", "transaction_detail", "PAGE_SIZE"]
```

- [ ] **Step 5: Run tests to confirm they pass**

Run: `pytest tests/dashboard/test_views.py -v`
Expected: all 9 tests pass.

- [ ] **Step 6: Run lint**

Run: `ruff check src/ai_accountant/dashboard/views.py tests/dashboard/test_views.py tests/dashboard/conftest.py`
Expected: no issues.

- [ ] **Step 7: Commit**

```bash
git add src/ai_accountant/dashboard/views.py tests/dashboard/test_views.py tests/dashboard/conftest.py
git commit -m "feat(dashboard): template context builders + KPI parity with report module"
```

---

## Task 6: fetcher.py

**Files:**
- Create: `src/ai_accountant/dashboard/fetcher.py`
- Create: `tests/dashboard/test_fetcher.py`
- Modify: `src/ai_accountant/dashboard/__init__.py`

**Goal:** `DashboardError` (error category + http_status), `run_fetch(address, ..., fetcher_factory=None) -> (df, meta)` that orchestrates: validate → SolanaDataFetcher → cache.write. Lockfile ensures one refresh per address at a time. Translates every `SolanaDataFetcherError` subclass into `DashboardError`.

### Module contract

```python
class DashboardError(Exception):
    def __init__(self, category: str, message: str, *, retryable: bool, http_status: int) -> None: ...

def run_fetch(
    address: str,
    *,
    helius_api_key: str,
    max_pages: int | None,
    cache_root: Path,
    fetcher_factory: Callable[[], SolanaDataFetcher] | None = None,
    lock_ttl_seconds: int = 1800,
) -> tuple[pd.DataFrame, dict]: ...

class RefreshLocked(DashboardError):
    """Raised when another refresh holds the lock for this address."""
```

- [ ] **Step 1: Write failing tests**

Create `tests/dashboard/test_fetcher.py`:

```python
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import (
    DATAFRAME_COLUMNS,
    HeliusAuthenticationError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
    SolanaDataFetcher,
)
from ai_accountant.dashboard import cache as cache_mod
from ai_accountant.dashboard.fetcher import (
    DashboardError,
    RefreshLocked,
    run_fetch,
)

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


class _FakeFetcher:
    def __init__(self, *, df: pd.DataFrame | None = None, raises: BaseException | None = None) -> None:
        self.df = df if df is not None else pd.DataFrame(columns=DATAFRAME_COLUMNS)
        self.raises = raises
        self.calls = 0
        self.last_args: tuple = ()

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None

    def fetch_transactions_dataframe(self, wallet_address, *, max_pages=None, **_kw):
        self.calls += 1
        self.last_args = (wallet_address, max_pages)
        if self.raises is not None:
            raise self.raises
        return self.df


class _Tmp(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.id().replace(".", "_") + "_tmp")
        self.tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class HappyPathTests(_Tmp):
    def test_run_fetch_writes_cache_and_returns_dataframe(self) -> None:
        fake = _FakeFetcher()
        df, meta = run_fetch(
            WALLET,
            helius_api_key="k",
            max_pages=5,
            cache_root=self.tmp,
            fetcher_factory=lambda: fake,
        )
        self.assertEqual(fake.calls, 1)
        self.assertEqual(fake.last_args, (WALLET, 5))
        self.assertEqual(meta["address"], WALLET)
        self.assertEqual(meta["max_pages_at_fetch"], 5)
        self.assertEqual(meta["row_count"], 0)
        # Cache files exist on disk.
        self.assertTrue((self.tmp / WALLET / "transactions.pkl").exists())
        self.assertTrue((self.tmp / WALLET / "meta.json").exists())

    def test_unbounded_max_pages_zero_means_none(self) -> None:
        fake = _FakeFetcher()
        run_fetch(
            WALLET,
            helius_api_key="k",
            max_pages=0,
            cache_root=self.tmp,
            fetcher_factory=lambda: fake,
        )
        self.assertEqual(fake.last_args, (WALLET, None))


class ErrorTranslationTests(_Tmp):
    def test_invalid_address_raises_before_fetcher_call(self) -> None:
        fake = _FakeFetcher()
        with self.assertRaises(InvalidSolanaAddressError):
            run_fetch(
                "not-a-wallet",
                helius_api_key="k",
                max_pages=1,
                cache_root=self.tmp,
                fetcher_factory=lambda: fake,
            )
        self.assertEqual(fake.calls, 0)

    def test_auth_error_translates_to_dashboard_error(self) -> None:
        fake = _FakeFetcher(raises=HeliusAuthenticationError("nope"))
        with self.assertRaises(DashboardError) as ctx:
            run_fetch(
                WALLET,
                helius_api_key="k",
                max_pages=1,
                cache_root=self.tmp,
                fetcher_factory=lambda: fake,
            )
        self.assertEqual(ctx.exception.category, "auth")
        self.assertEqual(ctx.exception.http_status, 502)
        self.assertFalse(ctx.exception.retryable)

    def test_rate_limit_translates_to_503(self) -> None:
        fake = _FakeFetcher(raises=HeliusRateLimitError("slow down"))
        with self.assertRaises(DashboardError) as ctx:
            run_fetch(
                WALLET,
                helius_api_key="k",
                max_pages=1,
                cache_root=self.tmp,
                fetcher_factory=lambda: fake,
            )
        self.assertEqual(ctx.exception.category, "rate_limit")
        self.assertEqual(ctx.exception.http_status, 503)
        self.assertTrue(ctx.exception.retryable)


class LockfileTests(_Tmp):
    def _hold_lock(self) -> Path:
        wallet_dir = self.tmp / WALLET
        wallet_dir.mkdir(parents=True, exist_ok=True)
        lock = wallet_dir / ".refresh.lock"
        lock.write_text("held")
        return lock

    def test_concurrent_refresh_raises_refresh_locked(self) -> None:
        self._hold_lock()
        fake = _FakeFetcher()
        with self.assertRaises(RefreshLocked):
            run_fetch(
                WALLET,
                helius_api_key="k",
                max_pages=1,
                cache_root=self.tmp,
                fetcher_factory=lambda: fake,
            )
        self.assertEqual(fake.calls, 0)

    def test_stale_lock_is_replaced(self) -> None:
        lock = self._hold_lock()
        # Backdate the lock to make it look stale.
        old = time.time() - 3600
        import os
        os.utime(lock, (old, old))
        fake = _FakeFetcher()
        run_fetch(
            WALLET,
            helius_api_key="k",
            max_pages=1,
            cache_root=self.tmp,
            fetcher_factory=lambda: fake,
            lock_ttl_seconds=1800,
        )
        self.assertEqual(fake.calls, 1)
        # Lock cleaned up after success.
        self.assertFalse(lock.exists())

    def test_lock_released_on_failure(self) -> None:
        fake = _FakeFetcher(raises=HeliusAuthenticationError("nope"))
        with self.assertRaises(DashboardError):
            run_fetch(
                WALLET,
                helius_api_key="k",
                max_pages=1,
                cache_root=self.tmp,
                fetcher_factory=lambda: fake,
            )
        lock = self.tmp / WALLET / ".refresh.lock"
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/dashboard/test_fetcher.py -v`
Expected: every test errors with `ModuleNotFoundError: No module named 'ai_accountant.dashboard.fetcher'`.

- [ ] **Step 3: Implement fetcher.py**

Create `src/ai_accountant/dashboard/fetcher.py`:

```python
"""Helius fetch orchestration with cache write and per-address lockfile."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from .. import __version__ as _AI_ACCOUNTANT_VERSION
except ImportError:  # pragma: no cover — defensive
    _AI_ACCOUNTANT_VERSION = "0.0.0"

from ..addresses import validate_address
from ..exceptions import (
    HeliusAPIError,
    HeliusAuthenticationError,
    HeliusPermissionError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
    SolanaDataFetcherError,
)
from ..client import SolanaDataFetcher
from . import cache as cache_mod

LOCK_FILENAME = ".refresh.lock"


class DashboardError(Exception):
    def __init__(
        self,
        category: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int = 500,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.retryable = retryable
        self.http_status = http_status


class RefreshLocked(DashboardError):
    def __init__(self, message: str = "Refresh already in progress for this wallet.") -> None:
        super().__init__("locked", message, retryable=True, http_status=409)


def run_fetch(
    address: str,
    *,
    helius_api_key: str,
    max_pages: int | None,
    cache_root: Path,
    fetcher_factory: Callable[[], Any] | None = None,
    lock_ttl_seconds: int = 1800,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    validated = validate_address(address)
    cache_root = Path(cache_root)
    wallet_dir = cache_root / validated
    wallet_dir.mkdir(parents=True, exist_ok=True)
    lock_path = wallet_dir / LOCK_FILENAME
    requested_pages = None if (max_pages is None or max_pages == 0) else int(max_pages)

    _acquire_lock(lock_path, ttl_seconds=lock_ttl_seconds)
    try:
        fetcher = (fetcher_factory or _default_factory(helius_api_key))()
        try:
            with fetcher:
                df = fetcher.fetch_transactions_dataframe(validated, max_pages=requested_pages)
        except InvalidSolanaAddressError:
            raise
        except HeliusAuthenticationError as exc:
            raise DashboardError("auth", str(exc), retryable=False, http_status=502) from exc
        except HeliusPermissionError as exc:
            raise DashboardError("auth", str(exc), retryable=False, http_status=502) from exc
        except HeliusRateLimitError as exc:
            raise DashboardError("rate_limit", str(exc), retryable=True, http_status=503) from exc
        except HeliusAPIError as exc:
            raise DashboardError("transport", str(exc), retryable=True, http_status=502) from exc
        except SolanaDataFetcherError as exc:
            raise DashboardError("transport", str(exc), retryable=False, http_status=502) from exc

        meta = _build_meta(df, validated, pages_fetched=requested_pages, max_pages=requested_pages)
        try:
            cache_mod.write(validated, df, meta, cache_root=cache_root)
        except OSError as exc:
            raise DashboardError(
                "cache_io", f"Could not write cache: {exc}", retryable=False, http_status=500
            ) from exc
        return df, meta
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _acquire_lock(lock_path: Path, *, ttl_seconds: int) -> None:
    if lock_path.exists():
        try:
            mtime = lock_path.stat().st_mtime
        except OSError:
            mtime = 0
        if (time.time() - mtime) > ttl_seconds:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
        else:
            raise RefreshLocked()
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError as exc:
        raise RefreshLocked() from exc


def _default_factory(api_key: str) -> Callable[[], SolanaDataFetcher]:
    return lambda: SolanaDataFetcher(api_key=api_key)


def _build_meta(
    df: pd.DataFrame,
    address: str,
    *,
    pages_fetched: int | None,
    max_pages: int | None,
) -> dict[str, Any]:
    earliest = ""
    latest = ""
    if not df.empty and "timestamp_unix" in df.columns and df["timestamp_unix"].notna().any():
        ts_series = df["timestamp_unix"].dropna().astype("int64")
        earliest = datetime.fromtimestamp(int(ts_series.min()), timezone.utc).strftime("%Y-%m-%d")
        latest = datetime.fromtimestamp(int(ts_series.max()), timezone.utc).strftime("%Y-%m-%d")

    pages = pages_fetched if pages_fetched is not None else 0
    return {
        "schema_version": cache_mod.SCHEMA_VERSION,
        "address": address,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pages_fetched": pages,
        "max_pages_at_fetch": pages,
        "row_count": int(len(df)),
        "earliest_tx": earliest,
        "latest_tx": latest,
        "ai_accountant_version": _safe_version(),
    }


def _safe_version() -> str:
    return _AI_ACCOUNTANT_VERSION


__all__ = ["DashboardError", "RefreshLocked", "run_fetch", "LOCK_FILENAME"]
```

- [ ] **Step 4: Add `__version__` to the package root**

Add `__version__` to `src/ai_accountant/__init__.py`. Open the file and insert this line at the very top of the module body (above the `from .addresses import ...` line):

```python
__version__ = "0.1.0"
```

Then add `"__version__"` as the first entry in the existing `__all__` list, so it sorts to the top alphabetically:

```python
__all__ = [
    "__version__",
    "DATAFRAME_COLUMNS",
    ...
]
```

If `__version__` is already present, leave the file as-is.

- [ ] **Step 5: Update sub-package `__init__` to re-export public names**

Replace the contents of `src/ai_accountant/dashboard/__init__.py`:

```python
"""Local web dashboard for real Solana wallet activity (parser-level views)."""

from __future__ import annotations

from .fetcher import DashboardError, RefreshLocked, run_fetch

__all__ = ["DashboardError", "RefreshLocked", "run_fetch"]
```

- [ ] **Step 6: Run tests to confirm they pass**

Run: `pytest tests/dashboard/test_fetcher.py -v`
Expected: all 8 tests pass.

- [ ] **Step 7: Run the full dashboard suite so far**

Run: `pytest tests/dashboard -v`
Expected: cache + filters + charts + views + fetcher tests all pass.

- [ ] **Step 8: Run lint**

Run: `ruff check src/ai_accountant/dashboard tests/dashboard`
Expected: no issues.

- [ ] **Step 9: Commit**

```bash
git add src/ai_accountant/dashboard/fetcher.py src/ai_accountant/dashboard/__init__.py src/ai_accountant/__init__.py tests/dashboard/test_fetcher.py
git commit -m "feat(dashboard): run_fetch + DashboardError translation + lockfile"
```

---

## Task 7: Templates + Flask app + routes

**Files:**
- Create: `src/ai_accountant/dashboard/templates/base.html.j2`
- Create: `src/ai_accountant/dashboard/templates/landing.html.j2`
- Create: `src/ai_accountant/dashboard/templates/wallet.html.j2`
- Create: `src/ai_accountant/dashboard/templates/transaction.html.j2`
- Create: `src/ai_accountant/dashboard/templates/error.html.j2`
- Create: `src/ai_accountant/dashboard/server/__init__.py`
- Create: `src/ai_accountant/dashboard/server/routes.py`
- Create: `src/ai_accountant/dashboard/server/static/dashboard.css`
- Create: `src/ai_accountant/dashboard/server/static/dashboard.js`
- Create: `tests/dashboard/test_routes.py`

**Goal:** Wire `views.py` and `fetcher.py` into HTTP. App factory accepts a `fetcher_factory` for testing. Routes exactly as in spec §4.2. Templates render the dicts from `views.py`.

- [ ] **Step 1: Write failing route tests**

Create `tests/dashboard/test_routes.py`:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS, HeliusAuthenticationError, HeliusRateLimitError
from ai_accountant.dashboard.server import create_app

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
WALLET_BAD = "not-a-wallet"


class _FakeFetcher:
    def __init__(self, *, df=None, raises=None) -> None:
        self.df = df if df is not None else pd.DataFrame(columns=DATAFRAME_COLUMNS)
        self.raises = raises
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None

    def fetch_transactions_dataframe(self, wallet_address, *, max_pages=None, **_kw):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.df


class _RouteCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.id().replace(".", "_") + "_tmp")
        self.tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)
        self.fake = _FakeFetcher()
        self.app = create_app(
            helius_api_key="k",
            max_pages=5,
            cache_root=self.tmp,
            fetcher_factory=lambda: self.fake,
        )
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class LandingRouteTests(_RouteCase):
    def test_get_landing_renders(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Solana wallet address", resp.data)

    def test_post_invalid_address_returns_400_with_message(self) -> None:
        resp = self.client.post("/", data={"address": WALLET_BAD})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"address", resp.data.lower())

    def test_post_valid_address_fetches_and_redirects(self) -> None:
        resp = self.client.post("/", data={"address": WALLET})
        self.assertEqual(resp.status_code, 303)
        self.assertIn(WALLET, resp.headers["Location"])
        self.assertEqual(self.fake.calls, 1)


class WalletRouteTests(_RouteCase):
    def test_uncached_wallet_renders_empty_state(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No data cached", resp.data)
        self.assertEqual(self.fake.calls, 0)

    def test_filter_change_does_not_call_fetcher(self) -> None:
        # Pre-populate cache via POST /
        self.client.post("/", data={"address": WALLET})
        self.fake.calls = 0
        resp = self.client.get(f"/wallet/{WALLET}?status=failed")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.fake.calls, 0)

    def test_invalid_address_returns_404(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET_BAD}")
        self.assertEqual(resp.status_code, 404)

    def test_path_traversal_returns_404(self) -> None:
        resp = self.client.get("/wallet/..%2Fetc")
        self.assertEqual(resp.status_code, 404)


class RefreshRouteTests(_RouteCase):
    def test_refresh_calls_fetcher_once_and_redirects(self) -> None:
        self.client.post("/", data={"address": WALLET})
        self.fake.calls = 0
        resp = self.client.post(f"/wallet/{WALLET}/refresh")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(self.fake.calls, 1)

    def test_refresh_with_auth_error_renders_error_page(self) -> None:
        self.fake.raises = HeliusAuthenticationError("nope")
        resp = self.client.post(f"/wallet/{WALLET}/refresh")
        self.assertEqual(resp.status_code, 502)
        self.assertIn(b"nope", resp.data)

    def test_refresh_with_rate_limit_renders_503(self) -> None:
        self.fake.raises = HeliusRateLimitError("slow down")
        resp = self.client.post(f"/wallet/{WALLET}/refresh")
        self.assertEqual(resp.status_code, 503)


class ForgetRouteTests(_RouteCase):
    def test_forget_removes_cache_and_redirects(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.post(f"/wallet/{WALLET}/forget")
        self.assertEqual(resp.status_code, 303)
        self.assertFalse((self.tmp / WALLET / "transactions.pkl").exists())


class ExportRouteTests(_RouteCase):
    def test_export_csv_returns_200_with_csv_mimetype(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}/export.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.mimetype.startswith("text/csv"))

    def test_export_json_returns_200_with_json_mimetype(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}/export.json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.mimetype.startswith("application/json"))

    def test_empty_filter_export_returns_200_not_404(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}/export.csv?status=failed")
        self.assertEqual(resp.status_code, 200)


class TransactionDetailTests(_RouteCase):
    def test_unknown_signature_returns_404(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}/tx/" + "1" * 88)
        self.assertEqual(resp.status_code, 404)


class MalformedQuerystringTests(_RouteCase):
    def test_bad_date_in_querystring_returns_200(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}?from=2025-13-99")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/dashboard/test_routes.py -v`
Expected: every test errors with `ModuleNotFoundError: No module named 'ai_accountant.dashboard.server'`.

- [ ] **Step 3: Create `server/__init__.py` (Flask app factory)**

Create `src/ai_accountant/dashboard/server/__init__.py`:

```python
"""Flask app factory for the local wallet dashboard."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from flask import Flask

from .routes import register_routes


def create_app(
    *,
    helius_api_key: str,
    max_pages: int | None,
    cache_root: Path,
    fetcher_factory: Callable[[], Any] | None = None,
) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent.parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )
    app.config.update(
        AI_ACCOUNTANT_HELIUS_API_KEY=helius_api_key,
        AI_ACCOUNTANT_MAX_PAGES=max_pages,
        AI_ACCOUNTANT_CACHE_ROOT=Path(cache_root),
        AI_ACCOUNTANT_FETCHER_FACTORY=fetcher_factory,
    )
    register_routes(app)
    return app


__all__ = ["create_app"]
```

- [ ] **Step 4: Create the routes module**

Create `src/ai_accountant/dashboard/server/routes.py`:

```python
"""HTTP routes for the dashboard."""

from __future__ import annotations

import io
import json
import re
from decimal import Decimal
from pathlib import Path

import pandas as pd
from flask import (
    Flask,
    Response,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)

from ...exceptions import InvalidSolanaAddressError
from ...report import transaction_export_frame
from .. import cache as cache_mod
from ..fetcher import DashboardError, RefreshLocked, run_fetch
from ..filters import FilterSpec
from ..views import transaction_detail, wallet_page

ADDR_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
SIG_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{80,90}$")


def register_routes(app: Flask) -> None:
    @app.get("/")
    def landing() -> Response:
        wallets = cache_mod.list_wallets(cache_root=_cache_root())
        return render_template("landing.html.j2", wallets=wallets, error=None, address_input="")

    @app.post("/")
    def landing_submit() -> Response:
        address = (request.form.get("address") or "").strip()
        if not ADDR_RE.match(address):
            wallets = cache_mod.list_wallets(cache_root=_cache_root())
            return (
                render_template(
                    "landing.html.j2",
                    wallets=wallets,
                    error="That doesn't look like a Solana wallet address.",
                    address_input=address,
                ),
                400,
            )
        try:
            cached = cache_mod.read(address, cache_root=_cache_root())
        except InvalidSolanaAddressError:
            wallets = cache_mod.list_wallets(cache_root=_cache_root())
            return (
                render_template(
                    "landing.html.j2",
                    wallets=wallets,
                    error="That doesn't look like a Solana wallet address.",
                    address_input=address,
                ),
                400,
            )
        if cached is None:
            try:
                _do_fetch(address)
            except DashboardError as exc:
                return _render_error(exc), exc.http_status
        return redirect(url_for("wallet_page_route", address=address), code=303)

    @app.get("/wallet/<address>")
    def wallet_page_route(address: str) -> Response:
        if not ADDR_RE.match(address):
            abort(404)
        try:
            cached = cache_mod.read(address, cache_root=_cache_root())
        except InvalidSolanaAddressError:
            abort(404)
        spec = FilterSpec.from_querystring(request.args)
        if cached is None:
            empty = pd.DataFrame()
            ctx = wallet_page(empty, spec=spec, meta=None, address=address)
            return render_template("wallet.html.j2", **ctx, no_cache=True)
        df, meta = cached
        ctx = wallet_page(df, spec=spec, meta=meta, address=address)
        return render_template("wallet.html.j2", **ctx, no_cache=False)

    @app.post("/wallet/<address>/refresh")
    def refresh_route(address: str) -> Response:
        if not ADDR_RE.match(address):
            abort(404)
        try:
            _do_fetch(address)
        except RefreshLocked as exc:
            return _render_error(exc), exc.http_status
        except DashboardError as exc:
            return _render_error(exc), exc.http_status
        target = request.referrer or url_for("wallet_page_route", address=address)
        return redirect(target, code=303)

    @app.post("/wallet/<address>/forget")
    def forget_route(address: str) -> Response:
        if not ADDR_RE.match(address):
            abort(404)
        try:
            cache_mod.forget(address, cache_root=_cache_root())
        except InvalidSolanaAddressError:
            abort(404)
        return redirect(url_for("landing"), code=303)

    @app.get("/wallet/<address>/tx/<sig>")
    def tx_detail_route(address: str, sig: str) -> Response:
        if not ADDR_RE.match(address) or not SIG_RE.match(sig):
            abort(404)
        try:
            cached = cache_mod.read(address, cache_root=_cache_root())
        except InvalidSolanaAddressError:
            abort(404)
        if cached is None:
            abort(404)
        df, _meta = cached
        try:
            ctx = transaction_detail(df, sig, address=address)
        except KeyError:
            abort(404)
        return render_template("transaction.html.j2", **ctx)

    @app.get("/wallet/<address>/export.csv")
    def export_csv_route(address: str) -> Response:
        df = _filtered_or_404(address)
        export = transaction_export_frame(df)
        buf = io.StringIO()
        export.to_csv(buf, index=False)
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{address[:8]}_transactions.csv"',
            },
        )

    @app.get("/wallet/<address>/export.json")
    def export_json_route(address: str) -> Response:
        df = _filtered_or_404(address)
        export = transaction_export_frame(df)
        records = json.loads(
            export.to_json(orient="records", default_handler=str)
        )
        body = json.dumps(
            {"transactions": records, "meta": {"address": address, "count": len(records)}},
            indent=2,
            default=lambda v: str(v) if isinstance(v, Decimal) else v,
        )
        return Response(
            body,
            mimetype="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{address[:8]}_transactions.json"',
            },
        )


def _cache_root() -> Path:
    return current_app.config["AI_ACCOUNTANT_CACHE_ROOT"]


def _max_pages() -> int | None:
    return current_app.config["AI_ACCOUNTANT_MAX_PAGES"]


def _api_key() -> str:
    return current_app.config["AI_ACCOUNTANT_HELIUS_API_KEY"]


def _factory():
    return current_app.config.get("AI_ACCOUNTANT_FETCHER_FACTORY")


def _do_fetch(address: str) -> None:
    run_fetch(
        address,
        helius_api_key=_api_key(),
        max_pages=_max_pages(),
        cache_root=_cache_root(),
        fetcher_factory=_factory(),
    )


def _filtered_or_404(address: str) -> pd.DataFrame:
    if not ADDR_RE.match(address):
        abort(404)
    try:
        cached = cache_mod.read(address, cache_root=_cache_root())
    except InvalidSolanaAddressError:
        abort(404)
    if cached is None:
        abort(404)
    df, _meta = cached
    spec = FilterSpec.from_querystring(request.args)
    return spec.apply(df) if not df.empty else df


def _render_error(exc: DashboardError) -> str:
    return render_template(
        "error.html.j2",
        error_category=exc.category,
        error_message=exc.message,
        retryable=exc.retryable,
    )


__all__ = ["register_routes"]
```

- [ ] **Step 5: Create the base layout template**

Create `src/ai_accountant/dashboard/templates/base.html.j2`:

```jinja
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}AI Accountant Dashboard{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='dashboard.css') }}">
</head>
<body>
  <header class="topbar">
    <a class="brand" href="{{ url_for('landing') }}">AI Accountant</a>
    <nav>
      <a href="{{ url_for('landing') }}">Wallets</a>
    </nav>
  </header>
  <main class="page">
    {% block body %}{% endblock %}
  </main>
  <footer class="footer">
    <span>Local dashboard — data shown is cached on disk and refreshed on demand.</span>
  </footer>
  <script src="{{ url_for('static', filename='dashboard.js') }}" defer></script>
</body>
</html>
```

- [ ] **Step 6: Create the landing template**

Create `src/ai_accountant/dashboard/templates/landing.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}AI Accountant — Dashboard{% endblock %}
{% block body %}
<section class="hero">
  <h1>Wallet activity dashboard</h1>
  <p class="lead">Server-cached, filterable, exportable. Paste a Solana wallet address to begin.</p>
</section>

<section class="paste-form">
  <form method="post" action="{{ url_for('landing') }}">
    <label for="address">Solana wallet address</label>
    <input type="text" id="address" name="address" value="{{ address_input or '' }}"
           placeholder="86xCnPeV…" autocomplete="off" required>
    <button type="submit">Open</button>
    {% if error %}<p class="form-error">{{ error }}</p>{% endif %}
  </form>
</section>

<section class="recent">
  <h2>Recent wallets</h2>
  {% if wallets %}
  <table>
    <thead><tr><th>Address</th><th>Transactions</th><th>Range</th><th>Fetched</th><th></th></tr></thead>
    <tbody>
      {% for w in wallets %}
      <tr>
        <td><a href="{{ url_for('wallet_page_route', address=w.address) }}"><code>{{ w.address[:8] }}…{{ w.address[-6:] }}</code></a></td>
        <td>{{ w.row_count }}</td>
        <td>{{ w.earliest_tx or '—' }} → {{ w.latest_tx or '—' }}</td>
        <td>{{ w.fetched_at }}</td>
        <td>
          <form method="post" action="{{ url_for('forget_route', address=w.address) }}" style="display:inline">
            <button type="submit" class="link-button" title="Forget cache">⌫</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="empty">No wallets cached yet. Paste a Solana address above to fetch its activity.</p>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 7: Create the wallet page template**

Create `src/ai_accountant/dashboard/templates/wallet.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}Wallet {{ address_short }} — AI Accountant{% endblock %}
{% block body %}
<section class="wallet-header">
  <div>
    <p class="eyebrow">Wallet</p>
    <h1><code title="{{ address }}">{{ address_short }}</code></h1>
    {% if meta %}
    <p class="meta-line">
      {{ meta.row_count }} transactions • {{ meta.earliest_tx or '—' }} → {{ meta.latest_tx or '—' }} •
      Fetched {{ meta.fetched_at }} • Pages: {{ meta.pages_fetched }}/{{ meta.max_pages_at_fetch or '∞' }}
    </p>
    {% else %}
    <p class="meta-line">No data cached for this wallet yet.</p>
    {% endif %}
  </div>
  <div class="header-actions">
    <form method="post" action="{{ url_for('refresh_route', address=address) }}">
      <button type="submit" class="primary">{% if meta %}Refresh{% else %}Fetch{% endif %}</button>
    </form>
    {% if meta %}
    <form method="post" action="{{ url_for('forget_route', address=address) }}">
      <button type="submit" class="link-button">Forget</button>
    </form>
    {% endif %}
  </div>
</section>

{% if no_cache %}
<section class="empty-cache"><p>No data cached for this wallet yet. Click <strong>Fetch</strong> to retrieve from Helius.</p></section>
{% else %}

<form class="filter-bar" method="get" action="{{ url_for('wallet_page_route', address=address) }}">
  <label>From <input type="date" name="from" value="{{ filter.date_from.isoformat() if filter.date_from else '' }}"></label>
  <label>To <input type="date" name="to" value="{{ filter.date_to.isoformat() if filter.date_to else '' }}"></label>
  <label>Token
    <select name="token">
      <option value="">Any</option>
      {% for value, label in filter_options.tokens %}
      <option value="{{ value }}" {% if filter.token == value %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Type
    <select name="type">
      <option value="">Any</option>
      {% for t in filter_options.types %}
      <option value="{{ t }}" {% if filter.type == t %}selected{% endif %}>{{ t }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Status
    <select name="status">
      <option value="">Any</option>
      <option value="succeeded" {% if filter.status == 'succeeded' %}selected{% endif %}>Succeeded</option>
      <option value="failed" {% if filter.status == 'failed' %}selected{% endif %}>Failed</option>
    </select>
  </label>
  <label>Source
    <select name="source">
      <option value="">Any</option>
      {% for s in filter_options.sources %}
      <option value="{{ s }}" {% if filter.source == s %}selected{% endif %}>{{ s }}</option>
      {% endfor %}
    </select>
  </label>
  <label>Search <input type="search" name="q" value="{{ filter.q or '' }}" placeholder="text"></label>
  <button type="submit">Apply</button>
  <a href="{{ url_for('wallet_page_route', address=address) }}" class="clear">Clear</a>
</form>

<section class="kpi-grid">
  <article class="kpi"><span>Transactions {% if filter_active %}(filtered){% else %}(all time){% endif %}</span><strong>{{ kpis.total }}</strong></article>
  <article class="kpi"><span>Succeeded</span><strong>{{ kpis.succeeded }}</strong></article>
  <article class="kpi"><span>Failed</span><strong>{{ kpis.failed }}</strong></article>
  <article class="kpi"><span>Sources</span><strong>{{ kpis.sources }}</strong></article>
  <article class="kpi"><span>Wallet fees</span><strong>{{ kpis.fee_wallet }}</strong></article>
  <article class="kpi"><span>All parsed fees</span><strong>{{ kpis.fee_total }}</strong></article>
</section>

<section class="report-section">
  <h2>Balance over time</h2>
  {% if filter_active %}<p class="muted">Filter active — chart shows balance change starting from zero within the filter window.</p>{% endif %}
  {{ balance_chart_svg | safe }}
</section>

<section class="report-section">
  <h2>Activity over time</h2>
  {{ activity_chart_svg | safe }}
</section>

<section class="report-section">
  <h2>Asset flow</h2>
  {% if asset_flow %}
  <table>
    <thead><tr><th>Asset</th><th>In</th><th>Out</th><th>Net</th></tr></thead>
    <tbody>
      {% for r in asset_flow %}
      <tr>
        <td><strong>{{ r.asset }}</strong><span class="muted">{{ r.mint }}</span></td>
        <td>{{ r.in }}</td>
        <td>{{ r.out }}</td>
        <td><mark class="{{ r.direction }}">{{ r.net }}</mark></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}<p class="empty">No wallet movements were parsed.</p>{% endif %}
</section>

<section class="report-section">
  <h2>Transaction mix</h2>
  {% if transaction_mix %}
  <div class="bars">
    {% for r in transaction_mix %}
    <div class="bar-row">
      <div class="bar-label"><strong>{{ r.name }}</strong><span class="muted">{{ r.count }} tx</span></div>
      <div class="bar-track"><i style="width: {{ r.pct }}%"></i></div>
      <span class="bar-pct">{{ r.pct }}%</span>
    </div>
    {% endfor %}
  </div>
  {% else %}<p class="empty">No transaction types found.</p>{% endif %}
</section>

<section class="report-section">
  <h2>Review queue</h2>
  {% if review_queue %}
  <table>
    <thead><tr><th>Severity</th><th>Item</th><th>Tx</th></tr></thead>
    <tbody>
      {% for r in review_queue %}
      <tr>
        <td><mark class="severity {{ r.severity|lower }}">{{ r.severity }}</mark></td>
        <td><strong>{{ r.title }}</strong><span class="muted">{{ r.detail }}</span></td>
        <td>
          {% if r.signature %}
          <a href="{{ url_for('tx_detail_route', address=address, sig=r.signature) }}">{{ r.signature[:8] }}…</a>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}<p class="empty">No obvious review items in the parsed data.</p>{% endif %}
</section>

<section class="report-section">
  <h2>Transactions</h2>
  {% if transactions %}
  <table>
    <thead>
      <tr><th>Date</th><th>Status</th><th>Type</th><th>Net flow</th><th>Fee</th><th>Tx</th></tr>
    </thead>
    <tbody>
      {% for r in transactions %}
      <tr>
        <td>{{ r.date }}</td>
        <td><mark class="{{ r.status }}">{{ r.status }}</mark></td>
        <td><strong>{{ r.type }}</strong><span class="muted">{{ r.source }}</span></td>
        <td>{{ r.flow }}</td>
        <td>{{ r.fee }}</td>
        <td><a href="{{ url_for('tx_detail_route', address=address, sig=r.signature) }}">{{ r.signature_short }}</a></td>
      </tr>
      <tr class="description-row"><td></td><td colspan="5" class="muted">{{ r.description }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
  <nav class="pagination">
    Page {{ transactions_page }} of {{ transactions_pages }}
    {% if transactions_page > 1 %}<a href="?{{ filter.to_querystring() }}{% if filter.to_querystring() %}&{% endif %}page={{ transactions_page - 1 }}">Prev</a>{% endif %}
    {% if transactions_page < transactions_pages %}<a href="?{{ filter.to_querystring() }}{% if filter.to_querystring() %}&{% endif %}page={{ transactions_page + 1 }}">Next</a>{% endif %}
  </nav>
  {% else %}<p class="empty">No transactions match the current filter.</p>{% endif %}
</section>

<section class="export-bar">
  <a href="{{ url_for('export_csv_route', address=address) }}?{{ filter.to_querystring() }}">Download CSV (filtered)</a>
  <a href="{{ url_for('export_json_route', address=address) }}?{{ filter.to_querystring() }}">Download JSON (filtered)</a>
</section>

{% endif %}
{% endblock %}
```

- [ ] **Step 8: Create the transaction detail template**

Create `src/ai_accountant/dashboard/templates/transaction.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}Transaction {{ signature_short }} — AI Accountant{% endblock %}
{% block body %}
<p><a href="{{ url_for('wallet_page_route', address=address) }}">← Back to wallet {{ address_short }}</a></p>

<section class="tx-header">
  <h1>Transaction {{ signature_short }}</h1>
  <p class="muted">{{ timestamp_iso }}</p>
  <p>
    <mark class="{{ status }}">{{ status }}</mark>
    <mark class="neutral">{{ transaction_type }}</mark>
    <mark class="neutral">{{ source }}</mark>
  </p>
  <p>Signature: <code>{{ signature }}</code> · <a href="{{ explorer_url }}" target="_blank" rel="noreferrer">view on explorer</a></p>
  <p>Fee: {{ fee_sol }} SOL ({% if fee_paid_by_wallet %}paid by wallet{% else %}paid by another account{% endif %})</p>
</section>

<section class="report-section">
  <h2>Net flow</h2>
  {% if net_flow_rows %}
  <table>
    <thead><tr><th>Asset</th><th>Net</th></tr></thead>
    <tbody>
      {% for r in net_flow_rows %}
      <tr><td>{{ r.label }}</td><td>{{ r.amount }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}<p class="empty">No net wallet movement.</p>{% endif %}
</section>

<section class="report-section">
  <h2>Description</h2>
  <p>{{ description or '—' }}</p>
</section>

<section class="report-section">
  <h2>Movements</h2>
  <h3>In</h3>
  {% if movements_in %}<pre>{{ movements_in }}</pre>{% else %}<p class="empty muted">None.</p>{% endif %}
  <h3>Out</h3>
  {% if movements_out %}<pre>{{ movements_out }}</pre>{% else %}<p class="empty muted">None.</p>{% endif %}
</section>

<details class="report-section">
  <summary>Raw row</summary>
  <dl>
    {% for key, value in raw_pairs %}
    <dt>{{ key }}</dt><dd><code>{{ value }}</code></dd>
    {% endfor %}
  </dl>
</details>
{% endblock %}
```

- [ ] **Step 9: Create the error template**

Create `src/ai_accountant/dashboard/templates/error.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}Error — AI Accountant{% endblock %}
{% block body %}
<section class="report-section">
  <h1>Something went wrong</h1>
  <p><strong>Category:</strong> {{ error_category }}</p>
  <p>{{ error_message }}</p>
  {% if retryable %}<p class="muted">This may resolve itself if you retry.</p>{% endif %}
  <p><a href="{{ url_for('landing') }}">Back to dashboard</a></p>
</section>
{% endblock %}
```

- [ ] **Step 10: Create the static CSS**

Create `src/ai_accountant/dashboard/server/static/dashboard.css`:

```css
:root {
  --bg: #f5f7f8;
  --ink: #172126;
  --muted: #66737b;
  --line: #d9e0e4;
  --surface: #ffffff;
  --accent: #126a72;
  --accent-soft: #d9eef0;
  --good: #19734d;
  --bad: #a83d31;
  --warn: #996a13;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.45;
}
.topbar {
  display: flex;
  gap: 24px;
  align-items: center;
  padding: 12px 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}
.topbar .brand { font-weight: 700; color: var(--accent); text-decoration: none; }
.topbar nav a { color: var(--ink); text-decoration: none; margin-right: 12px; }
.page { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }
.footer { padding: 18px 24px; color: var(--muted); border-top: 1px solid var(--line); background: var(--surface); }
h1 { font-size: clamp(28px, 4vw, 44px); margin: 0 0 8px; }
h2 { margin: 0 0 12px; font-size: 20px; }
.eyebrow { color: var(--accent); text-transform: uppercase; font-weight: 700; font-size: 12px; margin: 0; }
.lead { color: var(--muted); font-size: 17px; }
.muted, .empty { color: var(--muted); }
.report-section, .paste-form, .recent, .wallet-header, .filter-bar, .kpi-grid, .export-bar {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
  margin: 16px 0;
}
.wallet-header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-end; }
.header-actions form { display: inline; }
.kpi-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; padding: 12px; }
.kpi { padding: 10px; background: var(--surface); border: 1px solid var(--line); border-radius: 6px; }
.kpi span { display: block; color: var(--muted); font-size: 11px; text-transform: uppercase; }
.kpi strong { display: block; margin-top: 6px; font-size: 22px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { color: var(--muted); font-size: 12px; text-transform: uppercase; }
td span { display: block; color: var(--muted); font-size: 12px; }
mark { display: inline-flex; padding: 2px 8px; border-radius: 999px; background: #eef1f2; color: var(--ink); font-weight: 700; }
.succeeded, .positive { background: #dff3e9; color: var(--good); }
.failed, .negative, .high { background: #f8dfdc; color: var(--bad); }
.medium { background: #f8edd7; color: var(--warn); }
.low { background: #e4edf7; color: #245b86; }
.neutral { background: #eef1f2; color: var(--muted); }
.filter-bar { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
.filter-bar label { font-size: 12px; color: var(--muted); display: flex; flex-direction: column; gap: 4px; }
.filter-bar input, .filter-bar select { padding: 6px 8px; border: 1px solid var(--line); border-radius: 4px; }
.filter-bar button { padding: 8px 14px; background: var(--accent); color: white; border: 0; border-radius: 4px; cursor: pointer; }
.filter-bar .clear { color: var(--muted); text-decoration: none; }
.paste-form form { display: flex; gap: 8px; align-items: end; }
.paste-form input { flex: 1; padding: 8px; border: 1px solid var(--line); border-radius: 4px; }
.paste-form button { padding: 8px 16px; background: var(--accent); color: white; border: 0; border-radius: 4px; cursor: pointer; }
.form-error { color: var(--bad); }
.bars { display: grid; gap: 12px; }
.bar-row { display: grid; grid-template-columns: minmax(180px, 260px) minmax(160px, 1fr) 64px; gap: 14px; align-items: center; }
.bar-track { height: 12px; overflow: hidden; border-radius: 999px; background: #e4e9ec; }
.bar-track i { display: block; height: 100%; background: linear-gradient(90deg, #126a72, #3f8f6f); }
.bar-pct { color: var(--muted); text-align: right; }
.description-row td { padding-top: 0; color: var(--muted); }
.export-bar { display: flex; gap: 12px; }
.export-bar a { color: var(--accent); font-weight: 700; text-decoration: none; }
.pagination { margin-top: 12px; display: flex; gap: 12px; align-items: center; color: var(--muted); }
.pagination a { color: var(--accent); text-decoration: none; }
.link-button { background: none; border: 0; color: var(--muted); cursor: pointer; }
.tx-header h1 { font-size: 24px; }
.empty-cache { padding: 32px; text-align: center; color: var(--muted); background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }
@media (max-width: 900px) {
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .wallet-header { flex-direction: column; align-items: flex-start; }
  .bar-row { grid-template-columns: 1fr; }
}
```

- [ ] **Step 11: Create the static JS**

Create `src/ai_accountant/dashboard/server/static/dashboard.js`:

```javascript
(function () {
  "use strict";
  const form = document.querySelector("form.filter-bar");
  if (!form) return;
  const submit = () => form.submit();
  form.querySelectorAll("select").forEach((el) => el.addEventListener("change", submit));
  let qTimer = null;
  const qInput = form.querySelector('input[name="q"]');
  if (qInput) {
    qInput.addEventListener("input", () => {
      clearTimeout(qTimer);
      qTimer = setTimeout(submit, 400);
    });
  }
})();
```

- [ ] **Step 12: Run tests to confirm they pass**

Run: `pytest tests/dashboard/test_routes.py -v`
Expected: all 13 tests pass.

- [ ] **Step 13: Run the full dashboard suite**

Run: `pytest tests/dashboard -v`
Expected: every dashboard test passes; the existing `tests/test_*.py` (run with `pytest`) also still pass.

- [ ] **Step 14: Run lint**

Run: `ruff check src/ai_accountant/dashboard tests/dashboard`
Expected: no issues.

- [ ] **Step 15: Commit**

```bash
git add src/ai_accountant/dashboard/server src/ai_accountant/dashboard/templates tests/dashboard/test_routes.py
git commit -m "feat(dashboard): Flask app factory, routes, templates, static CSS/JS"
```

---

## Task 8: cli.py

**Files:**
- Create: `src/ai_accountant/dashboard/cli.py`
- Create: `tests/dashboard/test_cli.py`

**Goal:** `dashboard {serve, fetch}` argparse entry point. `serve` boots Flask via `create_app`. `fetch` warms the cache headlessly. Missing API key → exit 2 with stderr; bad max-pages → exit 2.

- [ ] **Step 1: Write failing tests**

Create `tests/dashboard/test_cli.py`:

```python
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


class CliHelpTests(unittest.TestCase):
    def test_help_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "ai_accountant.dashboard.cli", "--help"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": "src"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("serve", result.stdout)
        self.assertIn("fetch", result.stdout)

    def test_serve_help_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "ai_accountant.dashboard.cli", "serve", "--help"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONPATH": "src"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--max-pages", result.stdout)


class CliMissingKeyTests(unittest.TestCase):
    def test_serve_without_api_key_exits_2(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "HELIUS_API_KEY"}
        env["PYTHONPATH"] = "src"
        result = subprocess.run(
            [sys.executable, "-m", "ai_accountant.dashboard.cli", "serve"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("HELIUS_API_KEY", result.stderr)


class CliFetchProgrammaticTests(unittest.TestCase):
    """In-process invocation of the fetch subcommand using a fake fetcher_factory."""

    def setUp(self) -> None:
        self.tmp = Path(self.id().replace(".", "_") + "_tmp")
        self.tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fetch_writes_cache(self) -> None:
        from ai_accountant.dashboard import cli

        class _FakeFetcher:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_a):
                return None

            def fetch_transactions_dataframe(self_inner, _wallet, *, max_pages=None, **_kw):
                return pd.DataFrame(columns=DATAFRAME_COLUMNS)

        rc = cli.main(
            [
                "fetch",
                WALLET,
                "--api-key",
                "k",
                "--max-pages",
                "1",
                "--cache-dir",
                str(self.tmp),
            ],
            fetcher_factory=lambda: _FakeFetcher(),
        )
        self.assertEqual(rc, 0)
        self.assertTrue((self.tmp / WALLET / "transactions.pkl").exists())

    def test_fetch_with_negative_max_pages_exits_2(self) -> None:
        from ai_accountant.dashboard import cli

        rc = cli.main(
            [
                "fetch",
                WALLET,
                "--api-key",
                "k",
                "--max-pages",
                "-1",
                "--cache-dir",
                str(self.tmp),
            ]
        )
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `pytest tests/dashboard/test_cli.py -v`
Expected: every test errors with `ModuleNotFoundError` for `ai_accountant.dashboard.cli`.

- [ ] **Step 3: Implement cli.py**

Create `src/ai_accountant/dashboard/cli.py`:

```python
"""argparse entry point: `dashboard {serve, fetch}`."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8770
DEFAULT_HOST = "127.0.0.1"
DEFAULT_MAX_PAGES = 5
DEFAULT_CACHE_DIR = ".ai_accountant/wallets"


def main(argv: list[str] | None = None, *, fetcher_factory: Callable[[], Any] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return _run_serve(args)
    if args.command == "fetch":
        return _run_fetch(args, fetcher_factory=fetcher_factory)
    parser.print_help(sys.stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dashboard", description="AI Accountant local dashboard.")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Start the local Flask web UI.")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--api-key", default=None)
    serve.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    serve.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)

    fetch = sub.add_parser("fetch", help="Fetch one wallet into the cache without starting a server.")
    fetch.add_argument("address")
    fetch.add_argument("--api-key", default=None)
    fetch.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    fetch.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    return parser


def _resolve_api_key(args: argparse.Namespace) -> str | None:
    return (args.api_key or os.environ.get("HELIUS_API_KEY") or "").strip() or None


def _ensure_cache_dir(path: Path) -> int | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Cannot write to {path}: {exc}", file=sys.stderr)
        return 1
    return None


def _run_serve(args: argparse.Namespace) -> int:
    api_key = _resolve_api_key(args)
    if not api_key:
        print(
            "Missing Helius API key. Set HELIUS_API_KEY or pass --api-key.",
            file=sys.stderr,
        )
        return 2
    if args.max_pages < 0:
        print("--max-pages must be 0 or greater.", file=sys.stderr)
        return 2

    cache_dir = Path(args.cache_dir).resolve()
    rc = _ensure_cache_dir(cache_dir)
    if rc is not None:
        return rc

    if args.host != DEFAULT_HOST:
        print(
            "Binding to non-loopback exposes wallet activity to your local network.",
            file=sys.stderr,
        )

    try:
        from .server import create_app
    except ImportError as exc:
        print(
            "This feature requires the 'dashboard' extra. "
            "Install with: pip install ai-accountant[dashboard]",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 1

    app = create_app(
        helius_api_key=api_key,
        max_pages=args.max_pages,
        cache_root=cache_dir,
    )
    print(f"Open http://{args.host}:{args.port} in your browser. Ctrl-C to stop.")
    try:
        app.run(host=args.host, port=args.port, debug=False)
    except OSError as exc:
        print(f"Could not bind {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    return 0


def _run_fetch(args: argparse.Namespace, *, fetcher_factory: Callable[[], Any] | None = None) -> int:
    api_key = _resolve_api_key(args)
    if not api_key:
        print(
            "Missing Helius API key. Set HELIUS_API_KEY or pass --api-key.",
            file=sys.stderr,
        )
        return 2
    if args.max_pages < 0:
        print("--max-pages must be 0 or greater.", file=sys.stderr)
        return 2

    cache_dir = Path(args.cache_dir).resolve()
    rc = _ensure_cache_dir(cache_dir)
    if rc is not None:
        return rc

    from .fetcher import DashboardError, run_fetch

    try:
        df, meta = run_fetch(
            args.address,
            helius_api_key=api_key,
            max_pages=args.max_pages,
            cache_root=cache_dir,
            fetcher_factory=fetcher_factory,
        )
    except DashboardError as exc:
        print(f"Fetch failed [{exc.category}]: {exc.message}", file=sys.stderr)
        return 1
    print(f"Fetched {len(df)} transactions for {args.address} (pages={meta['pages_fetched']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/dashboard/test_cli.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Sanity-check the console-script registration**

Run: `dashboard --help`
Expected: prints the same help as `python -m ai_accountant.dashboard.cli --help`. (If the entrypoint isn't found, run `pip install -e ".[dev,dashboard]"` again to refresh the script.)

- [ ] **Step 6: Run the full test suite**

Run: `pytest`
Expected: every test passes (existing core suite + new dashboard suite).

- [ ] **Step 7: Run lint**

Run: `ruff check src/ai_accountant/dashboard tests/dashboard`
Expected: no issues.

- [ ] **Step 8: Commit**

```bash
git add src/ai_accountant/dashboard/cli.py tests/dashboard/test_cli.py
git commit -m "feat(dashboard): CLI — `dashboard serve` and `dashboard fetch <addr>`"
```

---

## Task 9: Documentation updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `examples/real_wallet_report.py`

**Goal:** Document the new sub-package in `CLAUDE.md` so future contributors find it. Add a single-line pointer in `examples/real_wallet_report.py` so users see the dashboard is an option.

- [ ] **Step 1: Add a Dashboard section to CLAUDE.md Architecture**

In `CLAUDE.md`, locate the line that ends the bullet list of modules under "Architecture" — specifically the line that reads:

```
- **`solana_data_fetcher.py`** — backwards-compat re-export shim; scheduled for removal in a future release.
```

Insert the following bullet immediately after the `report.py` bullet and before the `solana_data_fetcher.py` bullet:

```
- **`dashboard/`** — local Flask web dashboard for live Helius data, gated behind the `[dashboard]` optional extra. Sub-modules: `cache.py` (filesystem cache `.ai_accountant/wallets/<addr>/`), `filters.py` (querystring → `FilterSpec`), `charts.py` (hand-rolled inline-SVG line + bar), `views.py` (template context builders, reuses `report.py` helpers), `fetcher.py` (orchestrates Helius fetch + lockfile + cache write, translates `SolanaDataFetcherError` → `DashboardError`), `server/` (Flask app factory + routes), `cli.py` (`dashboard serve`, `dashboard fetch`). Entry point: `pip install -e ".[dashboard]"` then `dashboard serve`. Parallel to (unbuilt) `demo/`; refactor signposts in code mark candidates for promotion to a shared module when `audit serve` lands.
```

- [ ] **Step 2: Add the dashboard test file row to the Tests table in CLAUDE.md**

Locate the Tests table in `CLAUDE.md` (the table starting with `| File | Covers |`). Append these rows below the existing `tests/test_compat_shim.py` row:

```
| `tests/dashboard/test_cache.py` | filesystem cache layer |
| `tests/dashboard/test_filters.py` | `FilterSpec` querystring parsing + apply |
| `tests/dashboard/test_charts.py` | SVG line + bar renderers |
| `tests/dashboard/test_views.py` | template context builders, KPI parity |
| `tests/dashboard/test_fetcher.py` | `run_fetch`, `DashboardError`, lockfile |
| `tests/dashboard/test_routes.py` | Flask routes via `app.test_client()` |
| `tests/dashboard/test_cli.py` | `dashboard {serve,fetch}` argparse |
```

- [ ] **Step 3: Add a one-line note to `examples/real_wallet_report.py`**

Insert this line at the very top of the docstring inside `examples/real_wallet_report.py`, immediately after the `"""Fetch real Helius wallet data and write a readable HTML/CSV report.` line:

Replace:

```python
"""Fetch real Helius wallet data and write a readable HTML/CSV report.

Required:
```

with:

```python
"""Fetch real Helius wallet data and write a readable HTML/CSV report.

For an interactive multi-wallet view, install the dashboard extra:
    pip install -e ".[dashboard]" && dashboard serve

Required:
```

- [ ] **Step 4: Verify CLAUDE.md still parses cleanly (no broken markdown)**

Run: `python -c "from pathlib import Path; print(Path('CLAUDE.md').read_text()[:500])"`
Expected: prints the first 500 chars of CLAUDE.md without errors.

- [ ] **Step 5: Final full test suite + lint**

Run these in sequence:

```
pytest
ruff check .
ruff format --check .
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md examples/real_wallet_report.py
git commit -m "docs(dashboard): document new sub-package in CLAUDE.md and example header"
```

---

## Spec coverage check

Each spec section maps to at least one task:

| Spec section | Task(s) |
|---|---|
| §1 Goal/scope | Task 1 (skeleton + extra) — ensures the surface exists |
| §2 Architecture / package layout | Task 1 (dirs), Tasks 2–8 (each module) |
| §3 Data lifecycle (cache + refresh) | Task 2 (cache), Task 6 (lockfile + run_fetch) |
| §4 HTTP surface (CLI + routes) | Task 7 (routes), Task 8 (CLI) |
| §5 Page composition | Task 7 (templates) + Task 5 (views.py builders) |
| §6 SVG charts | Task 4 |
| §7 Error handling | Task 6 (DashboardError translation), Task 7 (route-level branching) |
| §8 Testing | Tasks 2, 3, 4, 5, 6, 7, 8 — each module's tests |
| §9 Dependencies + refactor signposts | Task 1 (pyproject), Task 9 (CLAUDE.md docs) |
| §10 Open questions deferred | Documented in spec; no implementation needed |

No spec gaps detected.
