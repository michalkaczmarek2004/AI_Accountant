# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Python utilities for retrieving and normalizing Solana on-chain activity (via the Helius Enhanced API) into accounting-grade Pandas DataFrames. Single package: `ai_accountant`.

## Commands

Install dev environment:

```powershell
pip install -e ".[dev]"
```

Run tests (pytest is configured in `pyproject.toml` with `pythonpath = ["src"]` and `testpaths = ["tests"]`):

```powershell
pytest
pytest tests/test_solana_data_fetcher.py                                   # single file
pytest tests/test_solana_data_fetcher.py::SolanaDataFetcherTests::test_fetch_transaction_history_uses_before_signature_pagination  # single test
```

Tests use stdlib `unittest`, so they can also be run directly: `python -m unittest tests.test_solana_data_fetcher`.

There is no linter or formatter configured.

## Architecture

The whole library is one module: `src/ai_accountant/solana_data_fetcher.py`. `__init__.py` only re-exports the public surface (`SolanaDataFetcher` plus the exception hierarchy).

`SolanaDataFetcher` is the single entry point and combines three concerns that need to stay coordinated:

1. **HTTP transport** — `_UrllibSession` wraps `urllib.request` to avoid a `requests` dependency. It always returns a `_SimpleResponse` (even for HTTP errors) so the retry logic can branch on `status_code`. Network-level failures raise `TransportError` (internal). Tests substitute a `FakeSession` via the `session=` constructor kwarg — keep that injection seam intact.

2. **Pagination + retry loop** (`fetch_transaction_history` → `_request_transaction_page`) — Helius paginates by signature cursor, not page number:
   - `sort_order="desc"` (default) walks backward using `before-signature`; `sort_order="asc"` uses `after-signature`. Mixing `before`/`after` with the wrong `sort_order` raises `ValueError`.
   - The loop deduplicates by signature and breaks when the cursor stops advancing or repeats, so a misbehaving Helius response can't cause an infinite loop.
   - Retries cover only `429` and `5xx`. `Retry-After` (when numeric and ≥ 0) overrides the exponential backoff (`backoff_factor * 2**attempt`). Sleep is injected via `sleep_func=` so tests don't actually wait.
   - Status-code mapping: `401 → HeliusAuthenticationError`, `403 → HeliusPermissionError`, `429 (exhausted) → HeliusRateLimitError`, `400` mentioning "address" → `InvalidSolanaAddressError`, everything else → `HeliusAPIError` (with `status_code`). All inherit from `SolanaDataFetcherError`.

3. **Normalization to DataFrame** (`transactions_to_dataframe` → `_build_transaction_row` → `_parse_wallet_movements`) — produces a row per transaction with the fixed schema in `SolanaDataFetcher.DATAFRAME_COLUMNS`. Two non-obvious invariants:
   - **All financial values are `Decimal`** (lamports → SOL via `LAMPORTS_PER_SOL = Decimal("1e9")`, token amounts via `_coerce_decimal`). Do not introduce `float` arithmetic into fee/flow paths — the tests assert exact `Decimal` equality and the whole point is accounting precision.
   - **Wallet-perspective parsing**: `_parse_wallet_movements` splits each transfer into `movements_in` / `movements_out` from the audited wallet's point of view, ignoring self-transfers. `native_net_sol` subtracts the fee only when `feePayer == wallet_address` (`fee_paid_by_wallet`). Token flows are aggregated by `(symbol, mint)` and rendered with `_asset_label` (e.g. `USDC (EPjF...Dt1v)`).

`validate_address` does its own Base58 decode (no `solana`/`base58` dep) and requires the result to be exactly 32 bytes — call sites rely on it raising `InvalidSolanaAddressError` *before* any HTTP request is made.

## Examples

`examples/` holds **illustrative scaffolds, not API surface**. They exist to show how a downstream pipeline can be built on top of `SolanaDataFetcher`. Both run offline (no Helius key needed) and depend only on `pandas` + the package itself. Run with `python examples/<file>.py`.

- **`examples/audit_demo.py`** — synthetic Helius-shaped transactions → `SolanaDataFetcher.transactions_to_dataframe(...)` → FIFO cost-basis ledger → classifier → printed advisory report. Uses an `_OfflineSession` whose `.get()` raises, proving the `transactions_to_dataframe` path makes no HTTP calls. Prices come from a static `PRICE_USD` stub; assumes US federal / FIFO / USD.
- **`examples/legal_grounding.py`** — wraps `audit_demo` (direct import via `sys.path` manipulation, so the two files are coupled) with a RAG-style retrieval layer that attaches statute citations to every classification. Tier-aware (`CONFIRMED` / `DRAFT` / `PROPOSED` / `INTERPRETATION`).

Two design points in `legal_grounding.py` to preserve if you extend it:

1. **The `BLOCKING_VERIFICATION_GATE`** is intentional. Every `LegalSource.verbatim_excerpt` defaults to a `PLACEHOLDER` token and the report counts how many citations are still unverified. The gate is the structural anti-hallucination guard — in production the retriever populates `verbatim_excerpt`, the count drops to zero, and only then is the report authoritative. Do not weaken or default this away.
2. **`holding_summary` is metadata, not authority.** It's a paraphrase to make the report readable; only `verbatim_excerpt` is treated as a citation. Don't conflate them.

Known limitation worth fixing if you build on this: the `[CONFLICT]` detector in `render_legal_report` does substring matching on `holding_summary` for `"NOT"`, which produces false positives (e.g., MiCA "does NOT itself impose income-tax characterization" trips it even though MiCA isn't negating anything). A structured `taxable_event: bool` field on `LegalSource`, or an LLM-judge step, is the right replacement.

There are no tests for `examples/` and the directory is intentionally outside the `pytest testpaths` config.
