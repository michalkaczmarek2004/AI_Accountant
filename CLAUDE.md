# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Python utilities for retrieving and normalizing Solana on-chain activity (via the Helius Enhanced API) into accounting-grade Pandas DataFrames. Single package: `ai_accountant`.

## Commands

Install dev environment (core):

```powershell
pip install -e ".[dev]"
```

Install with the dashboard extra (required for `ai_accountant.dashboard`):

```powershell
pip install -e ".[dev,dashboard]"
```

Run tests (pytest is configured in `pyproject.toml` with `pythonpath = ["src"]` and `testpaths = ["tests"]`):

```powershell
pytest
pytest tests/test_client.py                                                # single file
pytest tests/test_client.py::SolanaDataFetcherTests::test_fetch_transaction_history_uses_before_signature_pagination  # single test
pytest tests/dashboard/                                                    # dashboard suite only
```

Tests use stdlib `unittest`, so they can also be run directly: `python -m unittest tests.test_client`.

Lint and format (ruff is configured in `pyproject.toml`; `line-length = 100`, `target-version = "py310"`):

```powershell
ruff check .
ruff format .
```

## Architecture

The package lives in `src/ai_accountant/` and is split into seven focused modules:

- **`exceptions.py`** — `SolanaDataFetcherError` hierarchy (`InvalidSolanaAddressError`, `HeliusAPIError`, `HeliusAuthenticationError`, `HeliusPermissionError`, `HeliusRateLimitError`).
- **`addresses.py`** — `validate_address` + `_decode_base58`. Does its own Base58 decode (no `solana`/`base58` dep); requires exactly 32 bytes — call sites rely on it raising `InvalidSolanaAddressError` *before* any HTTP request.
- **`transport.py`** — `SessionProtocol` / `ResponseProtocol` (structural `typing.Protocol`), `_SimpleResponse` with `_CaseInsensitiveHeaders`, `_UrllibSession` (wraps `urllib.request` — no `requests` dep), `_parse_retry_after` (handles both numeric seconds and RFC-7231 HTTP-date), `TransportError`.
- **`parser.py`** — `TransactionParser` (public class, bound to a single wallet address).
- **`dataframe.py`** — `DATAFRAME_COLUMNS` list + `to_dataframe(parser, transactions)`.
- **`client.py`** — `SolanaDataFetcher` (HTTP orchestration, retry/pagination, DataFrame helper).
- **`report.py`** — `render_html_report`, `transaction_export_frame`, `write_wallet_report`. Hand-written self-contained HTML + flat CSV over the parser-level DataFrame; no templating engine, no JS, no external assets. Operates on `DATAFRAME_COLUMNS` only — does not depend on the audit-pipeline scaffolds in `examples/`.
- **`dashboard/`** — local Flask web dashboard for live Helius data, gated behind the `[dashboard]` optional extra. Sub-modules: `cache.py` (filesystem cache at `.ai_accountant/wallets/<addr>/`, atomic pickle + JSON writes, schema versioning), `filters.py` (querystring → `FilterSpec` dataclass → DataFrame mask), `charts.py` (hand-rolled inline-SVG line + stacked bar renderers, no JS deps), `views.py` (template context builders; reuses `report.py` private helpers for KPI/asset/mix/risk/tx parity), `fetcher.py` (orchestrates Helius fetch + per-address lockfile + cache write; translates every `SolanaDataFetcherError` subclass into `DashboardError`), `server/` (Flask app factory `create_app` + routes), `cli.py` (`dashboard serve`, `dashboard fetch <addr>`). Launch with `python examples/open_dashboard.py` or `dashboard serve` after installing the extra.
- **`solana_data_fetcher.py`** — backwards-compat re-export shim; scheduled for removal in a future release.

`__init__.py` re-exports the full public surface and exposes `__version__ = "0.1.0"`. Public names: `SolanaDataFetcher`, `TransactionParser`, `validate_address`, `DATAFRAME_COLUMNS`, the exception hierarchy, and the report helpers (`render_html_report`, `transaction_export_frame`, `write_wallet_report`).

### HTTP transport and retry (`client.py`)

`_UrllibSession` always returns a `_SimpleResponse` (even for HTTP errors) so retry logic can branch on `status_code`. Network failures raise `TransportError` (internal, translated to `HeliusAPIError` after retry exhaustion). Tests substitute a `FakeSession` via the `session=` constructor kwarg — keep that injection seam intact.

Retries cover only `429` and `5xx`. `Retry-After` (numeric seconds or HTTP-date) overrides exponential backoff (`backoff_factor * 2**attempt`). Sleep is injected via `sleep_func=` so tests don't actually wait. Status-code mapping: `401 → HeliusAuthenticationError`, `403 → HeliusPermissionError`, `429 (exhausted) → HeliusRateLimitError`, `400` mentioning "address" → `InvalidSolanaAddressError`, else → `HeliusAPIError`.

### Pagination (`client.py`)

`fetch_transaction_history` delegates to `iter_transactions`, a lazy generator. Helius paginates by signature cursor (not page number): `sort_order="desc"` uses `before-signature`; `sort_order="asc"` uses `after-signature`. Mixing them raises `ValueError`. The loop deduplicates by signature and breaks when the cursor stops advancing. `on_cursor_advance(cursor)` callback fires per-page after yielding and before the next fetch — callers use it for resumable pagination. The callback is **not** called when pagination terminates.

### Normalization (`parser.py`, `dataframe.py`)

`TransactionParser` is instantiated per wallet address. Its `parse(transaction)` method produces a row dict matching `DATAFRAME_COLUMNS` exactly. Two critical invariants:

- **All financial values are `Decimal`** (lamports → SOL via `LAMPORTS_PER_SOL = Decimal("1e9")`, token amounts via `_coerce_decimal`). Do not introduce `float` arithmetic into fee/flow paths — tests assert exact `Decimal` equality.
- **Token-flow aggregation keys are full mint strings** (not truncated display labels). `net_flow` keys: literal `"SOL"` for native, full mint address for tokens. `token_flow_details` entries contain `"label"` (e.g. `"USDC (EPjF...full...Dt1v)"`) for display only — never use `label` as a dict key.

**Wallet-perspective parsing**: movements are split into `movements_in` / `movements_out` from the audited wallet's point of view, ignoring self-transfers. `native_net_sol` subtracts the fee only when `feePayer == wallet_address`. Failed-transaction detection uses an explicit `transactionError is not None` check (not truthiness) — `{}` and `[]` are failures.

A `parser_factory: Callable[[str], TransactionParser] | None` kwarg on `SolanaDataFetcher` lets callers inject custom parser subclasses.

### Tests

Test files mirror the module split:

| File | Covers |
|---|---|
| `tests/test_addresses.py` | `validate_address`, Base58 decode |
| `tests/test_transport.py` | `_parse_retry_after`, `_CaseInsensitiveHeaders` |
| `tests/test_parser.py` | `TransactionParser.parse`, collision/mint-key invariants |
| `tests/test_dataframe.py` | `to_dataframe`, `DATAFRAME_COLUMNS` |
| `tests/test_client.py` | `SolanaDataFetcher`, pagination, retry, `iter_transactions` |
| `tests/test_report.py` | `render_html_report`, `transaction_export_frame`, `write_wallet_report` |
| `tests/test_compat_shim.py` | `from ai_accountant.solana_data_fetcher import ...` still works |
| `tests/dashboard/test_cache.py` | filesystem cache layer |
| `tests/dashboard/test_filters.py` | `FilterSpec` querystring parsing + apply |
| `tests/dashboard/test_charts.py` | SVG line + bar renderers |
| `tests/dashboard/test_views.py` | template context builders, KPI parity with `report.py` |
| `tests/dashboard/test_fetcher.py` | `run_fetch`, `DashboardError` translation, lockfile |
| `tests/dashboard/test_routes.py` | Flask routes via `app.test_client()` |
| `tests/dashboard/test_cli.py` | `dashboard {serve,fetch}` argparse |

`tests/dashboard/conftest.py` provides shared pytest fixtures (`synthetic_df`, `wallet_address`).

### Dashboard sub-package (`dashboard/`)

The dashboard is a separate concern from the core data pipeline and must be kept that way. Key design constraints:

**Dependency direction**: `dashboard/` imports from `..report` (private helpers like `_wallet_metrics`, `_asset_flow_rows`, etc.) and `..client`/`..exceptions`. Nothing in the core modules imports from `dashboard/`. If `report.py` private helpers are renamed, `views.py` will break — check both sides.

**`fetcher_factory` injection seam**: `run_fetch` and `create_app` both accept a `fetcher_factory: Callable[[], Any] | None` kwarg. This is the test seam — all route and fetcher tests pass a `_FakeFetcher` via it. Do not remove it or make it keyword-only-without-default.

**Cache schema versioning**: `SCHEMA_VERSION = 1` in `cache.py`. Any change to the pickle schema or `meta.json` keys must bump this constant; `read()` returns `None` on mismatch rather than crashing. The `meta.json` file is human-readable; the `transactions.pkl` is not (protocol 5 pickle).

**Lockfile**: `.refresh.lock` inside the wallet directory prevents concurrent refreshes for the same address. A lock older than `lock_ttl_seconds` (default 1800 s) is considered stale and replaced. The lock is always removed in a `finally` block — including on error.

**`views.py` reuse**: `wallet_page` calls `_wallet_metrics`, `_asset_flow_rows`, `_transaction_type_rows`, `_risk_rows`, `_transaction_rows` from `report.py` directly — same builders used by the static HTML report — so the two surfaces stay in sync without duplicating logic.

**SVG charts are self-contained**: `charts.py` has no Flask or pandas coupling. It takes plain Python sequences and returns `<svg>` strings. Keep it that way.

## Examples

`examples/` holds two categories of scripts. Neither is covered by the test suite — the directory is intentionally outside `pytest testpaths`. Run any of them with `python examples/<file>.py`.

### Public-API consumers

These call the package's public surface and double as documentation for downstream callers. Do not change their contract without considering downstream impact.

- **`examples/demo_html_report.py`** — runs `write_wallet_report` over the synthetic dataset from `audit_demo.py`. No Helius key needed.
- **`examples/real_wallet_report.py`** — fetches via `SolanaDataFetcher`, then renders with `write_wallet_report`. Requires `HELIUS_API_KEY` (env var or `--api-key`) and a wallet (`SOLANA_WALLET` or `--wallet`).
- **`examples/open_dashboard.py`** — starts the Flask dashboard and opens it in the browser. Reads `HELIUS_API_KEY` from env (or `--api-key`); optionally pre-fetches a wallet with `--wallet`. Requires the `[dashboard]` extra.

### Illustrative scaffolds

Not part of the public API. Both run offline (no Helius key needed).

- **`examples/audit_demo.py`** — synthetic Helius-shaped transactions → `TransactionParser` / `transactions_to_dataframe` → FIFO cost-basis ledger → classifier → report. Slippage is measured as implied execution price vs. oracle reference (single-output swaps only). Prices come from a static `PRICE_USD` stub; assumes US federal / FIFO / USD.
- **`examples/legal_grounding.py`** — wraps `audit_demo` with a RAG-style legal citation layer. `LegalSource` carries a `taxable_event: bool | None` field; conflict detection compares this field across jurisdictions (not substring matching on prose).

Two design points in `legal_grounding.py` to preserve:

1. **The `BLOCKING_VERIFICATION_GATE`** is intentional. Every `LegalSource.verbatim_excerpt` defaults to a `PLACEHOLDER` token; the report counts unverified citations. Do not weaken or default this away — it is the anti-hallucination guard.
2. **`holding_summary` is metadata, not authority.** Only `verbatim_excerpt` is treated as a citation; only `taxable_event` is a structured legal signal.

## Design docs

Specs and implementation plans live under `docs/superpowers/`:

- `docs/superpowers/specs/` — feature design specs (what + why; no code).
- `docs/superpowers/plans/` — TDD-ordered implementation plans, each referencing a spec.

Both are checked-in. Significant new work should land as a spec → plan → implementation, not as direct code.
