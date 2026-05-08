# Design — Real-wallet web dashboard for AI Accountant

**Status:** Approved (brainstorm), pending implementation plan
**Author:** Brainstormed with user, 2026-05-08
**Audience:** Wallet owners, accountants reviewing a single client's activity, anyone who today runs `examples/real_wallet_report.py`
**Scope:** v1 dashboard — live wallet via Helius, parser-level views only; USD valuation deferred

---

## 1. Goal, audience, scope

### 1.1 Goal

Ship a polished, browseable, multi-wallet web dashboard for **real on-chain Solana activity**. Run as a local Flask app; user pastes a wallet address; first paste fetches via Helius and caches to disk; subsequent visits load instantly from cache; filters re-render server-side without re-fetching. Lives at `ai_accountant.dashboard/`, side-by-side with the unbuilt `audit serve` (synthetic) so each product is honest about what it is.

### 1.2 Audience

Wallet owners, accountants reviewing a single client's activity, and anyone who today runs `examples/real_wallet_report.py` and wants to live in a UI instead of regenerating an HTML file. Same operator model as the demo spec: **localhost only, single operator on the machine, server holds the Helius key**.

### 1.3 In scope (v1)

- New `ai_accountant.dashboard/` sub-package + `dashboard` console script with two subcommands: `dashboard serve`, `dashboard fetch <addr>` (CLI-only fetch for headless cache-warming).
- Flask app, loopback by default. Routes: landing page (paste form + recent wallets), `/wallet/<addr>` (the dashboard), `/wallet/<addr>/tx/<sig>` (per-tx detail), `/wallet/<addr>/refresh` (POST → fetch + redirect), `/wallet/<addr>/export.csv` and `.json`, `/wallet/<addr>/forget` (POST → cache delete).
- Filesystem cache: `.ai_accountant/wallets/<addr>/transactions.pkl` + `meta.json`. Pickle (not parquet) — DataFrame schema stable enough, no `pyarrow` weight, `meta.json` carries a schema version for invalidation.
- Server-side filtering via querystring (`from`, `to`, `token`, `type`, `status`, `source`, `q`). Filter form on the wallet page; submit re-renders.
- Hand-rolled SVG charts in Python: balance-over-time (line, daily SOL closing balance), activity-over-time (stacked bar — succeeded vs failed tx per day or per week, auto-binned).
- Per-tx detail page: full row contents, all movements expanded, raw description, explorer link.
- CSV + JSON export buttons honoring current filter state.

### 1.4 Out of scope (v1)

- USD valuation / price oracle (deferred follow-up).
- Multi-user, auth, non-localhost binding (`--host 0.0.0.0` allowed but warns, like demo spec).
- Counterparty analysis, search-by-address, per-token drill-down page.
- Sharing code with the unbuilt `demo/` work; refactor signposts noted, refactor itself happens when `demo/` is implemented.
- Background fetch jobs; refresh is synchronous with a hard page cap (`--max-pages` default 5, configurable at startup).

## 2. Architecture and package layout

```
src/ai_accountant/
├── (existing modules, unchanged)
└── dashboard/                      # NEW
    ├── __init__.py                 # re-exports run_fetch, load_cached, DashboardError
    ├── cli.py                      # argparse entrypoint: `dashboard {serve, fetch}`
    ├── cache.py                    # filesystem cache: read/write pickle + meta.json
    ├── fetcher.py                  # thin wrapper around SolanaDataFetcher: fetch -> DataFrame -> cache
    ├── filters.py                  # querystring -> FilterSpec; FilterSpec.apply(df) -> df
    ├── charts.py                   # render_line_svg(...), render_bar_svg(...) — pure functions
    ├── views.py                    # builds template context dicts from a (filtered) DataFrame
    ├── server/
    │   ├── __init__.py             # Flask app factory create_app(config)
    │   ├── routes.py               # all routes registered here
    │   └── static/
    │       ├── dashboard.css       # local CSS, no CDN
    │       └── dashboard.js        # ~20 lines: submit-on-change for the filter form
    └── templates/
        ├── base.html.j2            # shell: header, nav, footer
        ├── landing.html.j2         # paste-form + recent wallets list
        ├── wallet.html.j2          # main dashboard page
        └── transaction.html.j2     # per-tx detail page

tests/dashboard/                    # NEW — mirrors the sub-package
├── __init__.py
├── conftest.py                     # tmp_cache_dir, synthetic_df, fake_fetcher
├── test_cache.py
├── test_filters.py
├── test_charts.py
├── test_views.py
├── test_fetcher.py
├── test_routes.py
└── test_cli.py

pyproject.toml                      # adds [dashboard] extra and `dashboard` console script
```

### 2.1 Module responsibilities

- `cache.py` — single source of truth for the on-disk layout. `read(addr) -> (df, meta) | None`, `write(addr, df, meta)`, `list_wallets() -> list[CachedWallet]`, `forget(addr) -> bool`. No Flask, no Helius — pure filesystem.
- `fetcher.py` — orchestrates `SolanaDataFetcher` against an address with a hard page cap, then writes to `cache.py`. Returns `(df, meta)`. Translates `SolanaDataFetcherError` into `DashboardError` with a user-facing message and a category (`auth`, `rate_limit`, `bad_address`, `transport`, `cache_io`).
- `filters.py` — `FilterSpec.from_querystring(MultiDict) -> FilterSpec`, `FilterSpec.apply(df) -> df`, `FilterSpec.to_querystring() -> str`. Validates ranges, normalizes empty values, ignores unknown keys. Pure data class. **Total**: never raises on malformed input — invalid keys are dropped silently.
- `charts.py` — `render_line_svg(points, ...) -> str`, `render_bar_svg(buckets, ...) -> str`. Hand-built inline `<svg>` markup. No DataFrame coupling — takes plain lists.
- `views.py` — pulls everything together: takes the cached DataFrame and a `FilterSpec`, returns a `dict` ready for Jinja: `{kpis, asset_flow, transaction_mix, review_queue, transactions, balance_chart_svg, activity_chart_svg, filter, meta}`.
- `server/__init__.py` — `create_app(*, helius_api_key, max_pages, cache_root, fetcher_factory=None) -> Flask`. App factory pattern keeps it testable.
- `server/routes.py` — registers blueprints. Routes are the only place Flask types (`request`, `redirect`, `abort`) appear; everything underneath stays plain Python.
- `cli.py` — `argparse`. `dashboard serve` boots the app; `dashboard fetch <addr>` warms the cache without starting a server.

### 2.2 Boundary rules

- `fetcher.py`, `cache.py`, `filters.py`, `charts.py`, `views.py` import nothing from Flask. Unit-testable as plain Python.
- Only `server/` and `cli.py` know Flask exists. They are also the only places that touch `os.environ`.
- Templates only render; they do not compute. All formatting decisions belong in `views.py`.
- No circular imports: `routes` → `views` → (`cache`, `filters`, `charts`); `routes` → `fetcher` → `cache`.

## 3. Data lifecycle (fetch, cache, refresh)

### 3.1 Cache layout

```
.ai_accountant/
└── wallets/
    └── <address>/
        ├── transactions.pkl    # pandas.DataFrame, pickled, protocol=5
        └── meta.json           # provenance + schema version
```

`meta.json` shape:

```json
{
  "schema_version": 1,
  "address": "86xCnP...o2MMY",
  "fetched_at": "2026-05-08T14:33:21Z",
  "pages_fetched": 5,
  "max_pages_at_fetch": 5,
  "row_count": 412,
  "earliest_tx": "2024-12-15",
  "latest_tx": "2026-05-07",
  "ai_accountant_version": "0.x.y"
}
```

`schema_version` is the only invalidation lever. If the `DATAFRAME_COLUMNS` contract in `dataframe.py` ever changes, bump it; `cache.read()` returns `None` for stale versions and the next page load triggers a fresh fetch.

### 3.2 Address-as-directory-name validation

Validated through `addresses.validate_address` before any path is constructed. Reject anything that isn't a valid 32-byte Base58 wallet — no `..`, no slashes, no traversal vectors. A second belt-and-braces regex check (`^[1-9A-HJ-NP-Za-km-z]{32,44}$`) gates path construction.

### 3.3 Fetch flow

`fetcher.run_fetch(address, *, helius_api_key, max_pages, cache_root, fetcher_factory=None)`:

1. `addresses.validate_address(address)` — raises before any HTTP.
2. `SolanaDataFetcher(api_key=...).fetch_transactions_dataframe(address, max_pages=max_pages)` — via `fetcher_factory` if provided.
3. Build `meta` dict.
4. `cache.write(address, df, meta)` — atomic-ish: write to `transactions.pkl.tmp` + `meta.json.tmp`, then `os.replace` both. Survives a crash mid-write.
5. Return `(df, meta)`.

`SolanaDataFetcherError` subclasses are caught at the boundary and re-raised as `DashboardError(category, message)` so routes can branch on category for status codes.

### 3.4 Refresh semantics

- `POST /wallet/<addr>/refresh` is the **only** way to trigger a Helius call from the UI.
- Refresh is synchronous: the request hangs until `run_fetch` returns, then 303-redirects to `/wallet/<addr>` (preserving any querystring filters via the `Referer` header, falling back to no filter).
- Hard cap is whatever `--max-pages` was at server startup (default **5**, ~500 tx). For genuinely busy wallets, the operator restarts the server with a higher cap, or runs `dashboard fetch <addr> --max-pages N` headlessly.
- The wallet page shows `meta.fetched_at` and `meta.row_count` prominently in the header so staleness is never hidden.
- No background refresh, no scheduled jobs, no progress bar mid-fetch. The browser shows its own loading spinner; that's good enough for a localhost tool with bounded fetches.

### 3.5 Concurrent refresh of the same address

- A simple per-address advisory file lock at `.ai_accountant/wallets/<addr>/.refresh.lock` (created with `O_EXCL`, deleted on success or failure).
- Second concurrent refresh sees the lock, returns 409 Conflict with a brief message: "Refresh already in progress for this wallet."
- Stale lock cleanup: if the lockfile is older than **30 minutes** it's considered abandoned and removed before the new refresh starts. Flat TTL — does not depend on `--max-pages`, since `--max-pages=0` (unbounded) would otherwise yield a zero TTL.

### 3.6 `dashboard fetch <addr>` (CLI-only)

Same code path as the route, but prints a one-line summary on success and exits non-zero on failure. Useful for cron-warming caches before someone opens the dashboard.

### 3.7 Cache invalidation contract

If the operator deletes `.ai_accountant/wallets/<addr>/`, the next `/wallet/<addr>` returns the empty-cache state. That, plus `schema_version`, are the only invalidation paths. No best-effort migration; no out-of-process invalidation hook.

## 4. HTTP surface

### 4.1 CLI

```
$ dashboard --help
usage: dashboard {serve, fetch} ...

subcommands:
  serve    Start the local Flask web UI.
  fetch    Fetch one wallet into the cache without starting a server.

$ dashboard serve --help
usage: dashboard serve [-h] [--host HOST] [--port PORT]
                       [--api-key KEY] [--max-pages N]
                       [--cache-dir DIR]

options:
  --host HOST       bind address (default: 127.0.0.1; 0.0.0.0 emits a stderr warning)
  --port PORT       port (default: 8770)
  --api-key KEY     Helius API key (default: $HELIUS_API_KEY)
  --max-pages N     Helius pages per fetch (default: 5; 0 = until exhausted)
  --cache-dir DIR   cache root (default: ./.ai_accountant/wallets/)

$ dashboard fetch <addr> --help
usage: dashboard fetch [-h] [--api-key KEY] [--max-pages N]
                       [--cache-dir DIR] address
```

Port `8770` is used to avoid collision with the demo spec's planned `audit serve` on `8765`. Missing `--api-key` and unset `$HELIUS_API_KEY` → exit 2 with a one-line stderr message. Both subcommands share the same key/cache resolution helper.

### 4.2 Flask routes

```
GET  /                                      landing — paste form + recent wallets list
POST /                                      wallet form submit; validates address; 303 -> /wallet/<addr>
                                            (if no cache yet, also fires fetch synchronously before redirect)
GET  /wallet/<addr>                         dashboard page (filtered via querystring)
POST /wallet/<addr>/refresh                 fetches via Helius; 303 -> Referer or /wallet/<addr>
POST /wallet/<addr>/forget                  removes the cache directory; 303 -> /
GET  /wallet/<addr>/tx/<sig>                per-tx detail page
GET  /wallet/<addr>/export.csv              CSV of currently-filtered tx (querystring respected)
GET  /wallet/<addr>/export.json             JSON of currently-filtered tx (Decimals as strings)
GET  /static/<path>                         local CSS + JS, no CDN
```

`<addr>` is validated against `^[1-9A-HJ-NP-Za-km-z]{32,44}$` *and* `addresses.validate_address` before any cache lookup. `<sig>` is validated against `^[1-9A-HJ-NP-Za-km-z]{80,90}$`. Failures → 404 (not 400 — same posture as the demo spec to avoid leaking information).

### 4.3 Querystring filter schema

Handled by `filters.FilterSpec`. Empty / missing keys are dropped (no filter applied). Unknown keys are ignored, not 400'd, so old bookmarks survive future filter additions.

| key | type | example | semantics |
|---|---|---|---|
| `from` | `YYYY-MM-DD` | `2025-01-01` | inclusive lower bound on `timestamp_unix` |
| `to` | `YYYY-MM-DD` | `2025-05-08` | inclusive upper bound (interpreted as end-of-day UTC) |
| `token` | mint string | `EPjFWdd5...Dt1v` | rows where `net_flow` references this mint, or `SOL` for native |
| `type` | string | `swap` | exact match on `transaction_type` |
| `status` | `succeeded`\|`failed` | `failed` | exact match on `status` |
| `source` | string | `JUPITER` | exact match on `source` |
| `q` | substring | `usdc` | case-insensitive substring across `description`, `source`, `transaction_type` |
| `page` | integer ≥ 1 | `2` | pagination of the transactions table; `page_size=100` fixed |

### 4.4 Filter form UX

- Single `<form method="get">` on the wallet page wraps a date-range pair, a token `<select>` (populated from the cached DataFrame's distinct mints + `SOL`), a type `<select>` (distinct transaction_types), a status `<select>` (`Any`/`Succeeded`/`Failed`), a source `<select>`, and a free-text `q` input.
- Submit re-renders. A "Clear filters" link is a plain `<a href="/wallet/<addr>">` — no JS needed.
- The ~20 lines of JS in `static/dashboard.js` simply attach `change` listeners to every `<select>` so the form auto-submits on dropdown change, plus `input` debounce on `q`. Form still works fully without JS.

### 4.5 Recent-wallets list on landing page

- Source: `cache.list_wallets()` reading directories under `.ai_accountant/wallets/`, sorted by `meta.fetched_at` desc, capped at 50.
- Each row: shortened address (clickable), `fetched_at`, `row_count`, `earliest_tx → latest_tx`.
- A trash-can icon → `POST /wallet/<addr>/forget` removes the cache directory.

## 5. Page composition

### 5.1 Landing page (`GET /`)

```
+----------------------------------------------------------+
| AI Accountant — Dashboard                                |
+----------------------------------------------------------+
| Wallet activity dashboard for real Solana wallets.       |
| Server-cached, filterable, exportable.                   |
|                                                          |
| [ Solana wallet address............................. ]   |
|                                              [ Open ]    |
|                                                          |
| Recent wallets                                           |
| ┌─────────────────────────────────────────────────────┐  |
| │ 86xCnPe…o2MMY  412 tx  2024-12-15 → 2026-05-07  ⌫  │  |
| │ FduuYSb…kQjPC  88 tx   2025-03-02 → 2026-04-30  ⌫  │  |
| │ ...                                                │  |
| └─────────────────────────────────────────────────────┘  |
+----------------------------------------------------------+
```

Empty-state copy when the recent-wallets list is empty: "No wallets cached yet. Paste a Solana address above to fetch its activity."

### 5.2 Wallet page (`GET /wallet/<addr>`)

Vertical sections, in order. All driven by the **filtered** DataFrame except the header (which always reflects the full cache).

1. **Header bar** — wallet (full + short), `meta.fetched_at`, `meta.row_count`, `meta.pages_fetched / max_pages_at_fetch`, **Refresh** button (POST form), **Forget wallet** link.
2. **Filter bar** — `<form method="get">` with the controls from §4.3. Persisted via querystring.
3. **KPI grid** — same six cards as the existing `report.py` (`Transactions`, `Succeeded`, `Failed`, `Sources`, `Wallet fees`, `All parsed fees`), all computed against the filtered DataFrame. KPI labels under each show "(filtered)" if any filter is active, else "(all time)".
4. **Balance over time** — line chart, SOL on Y, time on X. Computed by sorting the filtered DataFrame asc, walking `native_net_sol`, plotting daily closing balance. Zero-baseline X-axis. **Caveat:** when filters are active, the chart shows balance *change within the filter window* starting from zero, with a footnote explaining this. If users want absolute balance, they clear filters.
5. **Activity over time** — stacked bar chart, time on X (daily, weekly, or monthly auto-bin so there are 20–60 bars), Y is tx count split into `succeeded` / `failed` stacks.
6. **Asset flow** — existing `_asset_table` from `report.py`, fed the filtered DataFrame.
7. **Transaction mix** — existing `_type_bars` from `report.py`, filtered.
8. **Review queue** — existing `_risk_rows`, filtered.
9. **Transactions table** — existing `_transactions_table` shape, but each row's signature is a link to `/wallet/<addr>/tx/<sig>` instead of (or alongside) the explorer link. Pagination via `?page=N&page_size=100`, default 100. Filter querystring + `page` are mutually preserved.
10. **Export bar** — sticky at bottom: `Download CSV (filtered)` and `Download JSON (filtered)` buttons. Both forward the current querystring.

The five existing `report.py` panels (KPI, asset flow, mix, review queue, tx table) are reused as-is — the dashboard imports their builder functions. The wrapping HTML is different (Jinja templates, not the string-concat in `report.py`), but the row/dict contracts are shared. This is the bridge between the static report and the dashboard: same parser-level views, two surfaces.

### 5.3 Per-transaction detail page (`GET /wallet/<addr>/tx/<sig>`)

```
< back to wallet 86xCnPe…o2MMY

[Status: succeeded]  [Type: swap]  [Source: JUPITER]
2026-04-30 14:22:11 UTC

Signature: 3kJp...MfQz                          [view on explorer →]
Fee: 0.00018 SOL  (paid by wallet: yes)

Net flow
  SOL                       -0.5
  USDC (EPjF...Dt1v)        +98.42

Movements (in)
  USDC (EPjF...Dt1v)        +98.42  from JUPITER aggregator

Movements (out)
  SOL                       -0.5    to JUPITER aggregator

Description
  > Swapped 0.5 SOL for 98.42 USDC via Jupiter

Raw row (collapsed by default)
  v expand
```

The detail page is one Jinja template (`transaction.html.j2`) reading a dict produced by `views.transaction_detail(df, sig) -> dict`. If `<sig>` doesn't appear in the cached DataFrame for `<addr>`, return 404. The "Raw row" expander is a `<details>` tag — zero JS — that dumps the DataFrame row as a definition list, all `Decimal`s stringified.

### 5.4 Empty / not-yet-cached states

- `GET /wallet/<addr>` with no cache: render the wallet page shell (header, refresh button) and an empty-state body: "No data cached for this wallet yet. Click **Fetch** to retrieve from Helius." The refresh button is reused (rendered as **Fetch** when `meta` is missing).
- `GET /wallet/<addr>/tx/<sig>` with no cache: 404 (same as unknown sig — don't leak).
- `GET /wallet/<addr>` with empty filtered DataFrame (filters too narrow): all panels show their existing empty-state messages from `report.py`. Filter bar stays populated so the user can adjust.

### 5.5 Visual identity

Reuse the CSS variables and overall typography from the existing `report.py` stylesheet (`--accent: #126a72`, `--good`, `--bad`, `--warn`, etc.). Lift the relevant rules into `static/dashboard.css`. Templates add the dashboard-specific layout (sticky filter bar, two-column header, navigation), but the look-and-feel of panels matches the existing static report so users moving between the two products feel one tool, not two.

## 6. SVG charts

Two charts, both rendered server-side as inline SVG strings. No JS, no third-party. Pure functions in `charts.py`, fed plain Python lists by `views.py`.

### 6.1 Public contract

```python
# charts.py

def render_line_svg(
    points: list[tuple[date, Decimal]],
    *,
    width: int = 880,
    height: int = 220,
    y_label: str = "",
    empty_message: str = "No data in range.",
) -> str:
    """Inline <svg> string. Always returns valid SVG; empty-state if points is empty."""

def render_bar_svg(
    buckets: list[tuple[date, dict[str, int]]],   # [(bin_start, {"succeeded": N, "failed": M})]
    *,
    series_order: tuple[str, ...] = ("succeeded", "failed"),
    width: int = 880,
    height: int = 220,
    empty_message: str = "No transactions in range.",
) -> str:
    """Stacked vertical bars."""
```

Both functions:

- take **plain types** (`date`, `Decimal`, `int`, `str`) — no DataFrame coupling, no Jinja coupling.
- return a single `<svg viewBox="0 0 W H" ...>...</svg>` string. No external CSS, no external JS. Inline `<style>` block scoped via a class prefix (`ai-chart-…`) so the chart styles can't bleed into the page.
- escape every text node via `html.escape`.
- never raise on degenerate input (single point, empty list, all-zero bars). Empty input → centered `<text>` with `empty_message`.

### 6.2 Layout

Fixed pixel dimensions chosen to fit comfortably inside the wallet page's main column (max ~1100px), with a 40px left margin for Y-axis labels, 24px bottom margin for X-axis labels, 8px top/right padding. Numbers are not configurable per call — fixed in the module — so all charts on the page line up.

### 6.3 Line chart algorithm (balance over time)

Input is an asc-sorted list of `(date, cumulative_balance)` points. The Y-axis range is `[min(0, min(y)), max(0, max(y))]` — so the zero line is always visible and so a wallet that drained below zero (impossible for SOL but possible for `native_net_sol` within a filter window) doesn't clip. Y-axis ticks: 4 evenly spaced values, formatted via the same `_format_decimal` helper from `report.py`. X-axis ticks: 5 evenly spaced dates.

Path is a single `<path d="M ... L ...">` with `stroke="var(--accent, #126a72)"`, `fill="none"`, `stroke-width="2"`. A second `<path>` filled with a translucent accent provides the area under the line. A horizontal `<line>` at y=0 styled muted gives the zero baseline.

For very long ranges (>500 points) the path is decimated by binning to ~400 evenly-spaced points before rendering. The SVG stays small.

### 6.4 Bar chart algorithm (activity over time)

Input is a list of bins from `views.py`. Bin width is auto-chosen by total span:

- ≤ 60 days → daily bins
- ≤ 365 days → weekly bins (ISO week, Monday-start)
- > 365 days → monthly bins

`views.py` computes the bins and labels; `charts.py` only renders. Each bar is two stacked `<rect>` elements (succeeded green, failed red, using the existing `--good` / `--bad` palette). Bars are 80% of bin width, centered. Bin start labels render under every Nth bar so the X axis reads cleanly.

The legend is a single inline `<g>` near the top right with two `<rect>` swatches and `<text>` labels.

### 6.5 What the charts deliberately do NOT have

- No tooltips (no JS).
- No animation.
- No interactive zoom.
- No multi-series toggling.
- No accessibility deep dive beyond `<title>` and `<desc>` on the root `<svg>` and `aria-label="Balance over time"` set by the calling template.

These are conscious tradeoffs — adding any one of them drags JS in. If interactive charts become desired, that's a separate spec deciding which JS library and accepting the dependency.

## 7. Error handling

The dashboard sits between three error sources: Helius (network/auth/rate), bad inputs (address, signature, querystring), and disk (cache I/O). Each has a deterministic surface.

### 7.1 The `DashboardError` translation layer

`fetcher.py` is the only module that catches `SolanaDataFetcherError`. It re-raises a `DashboardError(category, message, *, retryable: bool, http_status: int)` so the route layer can branch on `category` instead of importing exception types from the core package.

| `SolanaDataFetcherError` subclass | `DashboardError.category` | `http_status` | `retryable` |
|---|---|---|---|
| `InvalidSolanaAddressError` | `bad_address` | 400 | False |
| `HeliusAuthenticationError` | `auth` | 502 | False |
| `HeliusPermissionError` | `auth` | 502 | False |
| `HeliusRateLimitError` | `rate_limit` | 503 | True |
| `HeliusAPIError` (other) | `transport` | 502 | True |
| any `OSError` from disk write | `cache_io` | 500 | False |

`http_status` is `502/503` for upstream failures (not `5xx` blanket) so an operator reading server logs sees that the issue is with Helius, not the dashboard itself.

### 7.2 Route-level handling

| Route | Failure | Behavior |
|---|---|---|
| `POST /` | invalid address (regex / `validate_address`) | 400, re-render landing with form-level error message and the invalid input preserved |
| `POST /` | valid address, no cache, fetch raises | render an error page with the `DashboardError.message`, a Retry button (POST again), and a "Continue without fetching" link to `/wallet/<addr>` (which then shows the empty-cache state) |
| `POST /wallet/<addr>/refresh` | fetch raises | render the same error page; the cache is *not* deleted on failure, so prior data stays browseable |
| `GET /wallet/<addr>` | cache read fails (corrupt pickle, schema_version mismatch, missing meta.json) | log the cause, treat as no-cache, render empty-cache state with a "Cache was invalid and was discarded — click Refresh" notice |
| `GET /wallet/<addr>/tx/<sig>` | sig not in cached DataFrame, or cache empty | 404 |
| `GET /wallet/<addr>/export.{csv,json}` | filtered DataFrame empty | 200 with empty file (CSV header row only; JSON `{"transactions": [], "meta": {...}}`). Not an error — empty filter is a valid result |
| any route | malformed querystring (e.g. `from=2025-13-99`) | log and ignore the bad key; treat the rest of the filter as valid; render normally. `FilterSpec.from_querystring` is total |
| any route | `addr`/`sig` regex fails | 404 (not 400; matches demo spec posture) |
| any route | unhandled exception | 500 with a minimal HTML page: exception class + message; full traceback only in server logs |

### 7.3 Concurrent-refresh contention

`POST /wallet/<addr>/refresh` while another refresh holds the lockfile → 409 Conflict with a friendly inline page: "A refresh for this wallet is already in progress. [Wait and reload]." No retry-after header. The waiting tab can simply hit Refresh again once the in-flight one finishes.

### 7.4 Startup / configuration errors

These are detected before Flask binds:

| Cause | Behavior |
|---|---|
| `--api-key` missing and `$HELIUS_API_KEY` unset | exit 2, stderr: "Missing Helius API key. Set HELIUS_API_KEY or pass --api-key." |
| `--max-pages` negative | exit 2 with the same one-line stderr |
| `--port` already in use | Flask raises `OSError`; CLI catches, exits 1, prints "Port N already in use. Try --port N+1." |
| `--host 0.0.0.0` requested | bind succeeds, but a stderr warning prints first: "Binding to non-loopback exposes wallet activity to your local network." (matches demo spec) |
| `--cache-dir` not writable | exit 1, "Cannot write to <dir>: <reason>". Detected by attempting to create the directory at startup |

### 7.5 What's deliberately NOT handled

- **Helius API contract changes** — if Helius starts returning a new shape, the parser raises and the dashboard raises 502. We don't try to render partial data.
- **DataFrame schema drift across `ai_accountant` upgrades** — handled by `meta.schema_version` invalidation, not by best-effort migration. Stale caches just re-fetch.
- **Browser storage** — no cookies, no `localStorage`. Filter state is only in URLs.
- **Multi-process safety** — the lockfile handles same-machine concurrent refreshes; nothing else (the dashboard is single-operator localhost).

## 8. Testing

Tests live under `tests/dashboard/`, mirroring the new sub-package. Existing `tests/test_*.py` are untouched. The suite runs with the existing `pytest` config (no new test deps).

### 8.1 Test files

| file | covers |
|---|---|
| `tests/dashboard/__init__.py` | empty marker |
| `tests/dashboard/conftest.py` | shared fixtures: `tmp_cache_dir`, `synthetic_df` (small DataFrame fixture lifted from existing `test_dataframe.py`), `fake_fetcher` (a `SolanaDataFetcher` substitute that returns a fixed DataFrame and counts calls) |
| `tests/dashboard/test_cache.py` | `cache.read` / `cache.write` round-trip; atomic write (kill mid-write does not corrupt prior cache); `schema_version` mismatch returns `None`; `list_wallets` ordering; `forget` removes the directory; address validation gates path construction |
| `tests/dashboard/test_filters.py` | `FilterSpec.from_querystring` parses every documented key; unknown keys ignored; malformed `from`/`to` dropped silently; `apply(df)` is total (returns a DataFrame even on empty input); `to_querystring` round-trips; substring `q` is case-insensitive |
| `tests/dashboard/test_charts.py` | both renderers return parseable XML on empty + happy input; bar count matches input; line empty-state text appears; SVG snapshot test for one happy-path input each (stdlib `xml.etree` parse + tiny diff helper) |
| `tests/dashboard/test_views.py` | `views.wallet_page(df, filter_spec)` returns dicts with the expected keys; KPIs match `report.py` output for the same DataFrame (parity test); `views.transaction_detail(df, sig)` raises `KeyError` for missing sig |
| `tests/dashboard/test_fetcher.py` | `run_fetch` calls injected fetcher exactly once; writes both files atomically; on `HeliusRateLimitError` raises `DashboardError(category='rate_limit', http_status=503)`; on bad address raises before any HTTP call; on disk error raises `DashboardError(category='cache_io')` |
| `tests/dashboard/test_routes.py` | Flask `app.test_client()` walks every route: landing, paste-form happy path, paste-form validation error, `/wallet/<addr>` cached / uncached / corrupt-cache states, `/wallet/<addr>/tx/<sig>` 200 / 404, refresh happy path, refresh while locked → 409, export.csv + export.json honor querystring, malformed querystring is ignored not 400'd, unknown `<addr>` regex → 404 |
| `tests/dashboard/test_cli.py` | subprocess `python -m ai_accountant.dashboard.cli serve --help` exits 0; missing api key exits 2 with stderr message; `dashboard fetch <addr>` with injected fetcher writes the cache; bad `--max-pages` exits 2 |

### 8.2 Fake-Helius seam

The dashboard never calls the real Helius API in tests. Two seams:

1. `SolanaDataFetcher` is already injected via its `session=` kwarg in core tests. The dashboard's `fetcher.run_fetch` accepts a `fetcher_factory: Callable[[], SolanaDataFetcher] | None = None` for the same reason. Production passes `None` (default factory uses `--api-key`); tests pass a factory that returns a `SolanaDataFetcher(session=FakeSession(...))`.
2. The Flask app factory accepts the `fetcher_factory` so route tests don't have to patch globals: `create_app(helius_api_key=..., max_pages=..., cache_root=..., fetcher_factory=fake)`.

This keeps `unittest.mock` out of the dashboard tests entirely — same posture as the rest of the codebase.

### 8.3 Key invariants pinned by tests

1. **Filtering never re-fetches.** `test_routes.py::test_filter_change_does_not_call_fetcher` — navigating `/wallet/<addr>?from=...` uses the cached DataFrame; the injected fake fetcher's call count stays at zero.
2. **Refresh is the only thing that calls Helius.** `test_routes.py::test_refresh_calls_fetcher_once` — `POST /wallet/<addr>/refresh` calls the injected fetcher exactly once and returns 303.
3. **Decimal exactness preserved through cache.** `test_cache.py::test_decimal_round_trip` — write a DataFrame with `Decimal` values, read it back, assert equality with `==` (not `pytest.approx`).
4. **Schema drift forces a fresh fetch.** `test_cache.py::test_schema_version_mismatch_returns_none` — write cache with `schema_version: 99`, `cache.read` returns `None`.
5. **Address validation runs before any HTTP.** `test_fetcher.py::test_invalid_address_raises_before_session_call` — fake fetcher's call count is zero when the address is malformed.
6. **Path traversal is impossible.** `test_routes.py::test_addr_with_slash_returns_404` — `GET /wallet/..%2Fetc/` returns 404, never touches the filesystem.
7. **Empty filter result is a 200, not a 404.** `test_routes.py::test_empty_filter_renders_empty_state` — overly narrow filters return 200 with empty-state copy, exports return 200 with empty payloads.
8. **Existing `report.py` outputs unchanged.** Reuse of `_kpi_grid` etc. is import-only; `tests/test_report.py` keeps passing untouched.

### 8.4 What tests deliberately do NOT cover

- **Real Helius.** Same posture as the existing test suite.
- **Browser-rendered visuals.** SVG correctness is asserted at the XML level + snapshot. We do not headless-render.
- **CSS regressions.** No visual snapshot of HTML pages.
- **Multi-process safety beyond the lockfile.** Concurrency tests exercise the lockfile path in-process; we do not spawn worker processes.
- **Performance.** Helius pagination performance is the core package's concern, not this layer's.

### 8.5 TDD order

`cache.py` first (smallest dependency surface), then `filters.py`, `charts.py`, `views.py` (each independent). Then `fetcher.py` (depends on `cache`). Then `server/` routes (depends on all). Then `cli.py` last. Each module's contract test is written first; integration tests in `test_routes.py` go last.

## 9. Dependencies and refactor signposts

### 9.1 Dependencies

Added to `pyproject.toml`:

```toml
[project.optional-dependencies]
dashboard = [
    "flask>=3.0",
    "jinja2>=3.1",
]

[project.scripts]
dashboard = "ai_accountant.dashboard.cli:main"
```

**Identical version pins as the future `[demo]` extra.** Both will end up sharing Flask + Jinja, so when `demo/` is implemented the spec there should pick the same pins. This makes the eventual consolidation a non-issue.

**Core package deps unchanged.** Without the `dashboard` extra installed, `import ai_accountant.dashboard` raises `ImportError` at the Flask/Jinja import sites. `cli.py` detects the missing extra at top-of-file and emits a friendly message (`"This feature requires the 'dashboard' extra. Install with: pip install ai-accountant[dashboard]"`) before argparse runs.

**No `pyarrow` / `fastparquet`.** The cache uses `pickle` (stdlib), with `meta.schema_version` for invalidation. Saves ~30MB of dependency weight; cost is "cache files aren't human-readable," which matters less than "the package stays small."

**No charting library.** SVG is hand-rolled in `charts.py`. ~150 lines of Python total for both renderers.

**No JS framework.** `static/dashboard.js` is hand-written, ~20 lines, optional (the form works without JS).

**No test deps added.** Flask provides `app.test_client()`, snapshot diffing uses stdlib `xml.etree`, fakes are plain Python classes.

### 9.2 Refactor signposts (deferred to demo-implementation work)

These are flagged in the code with comments like `# DEMO_REFACTOR: candidate for shared module when audit serve lands`:

- **`server/__init__.py:create_app`** — app factory pattern. Will likely share its `cache_root` resolution and lockfile primitives with the demo's `runs/` directory.
- **`server/static/dashboard.css`** — base layout / typography / palette will be deduplicated against the demo's static CSS.
- **`server/templates/base.html.j2`** — the shell (`<head>`, top nav, footer) is the prime candidate to migrate into a shared `web/templates/base.html.j2` once both products exist.
- **Recent-X list pattern** — `cache.list_wallets()` here and the demo spec's "Recent local demo runs" list are structurally identical (read directories, sort by mtime, render a list). Worth promoting to a small shared helper.
- **Lockfile + atomic-write helpers** — `cache.py` will land them locally; same pattern needed in demo's run directory.

These are notes for whoever picks up the demo plan — not refactors to do now. The point is to land the dashboard cleanly before paying the abstraction cost.

### 9.3 Documentation updates

- `CLAUDE.md` — add a section under "Architecture" describing the `dashboard/` sub-package, the cache layout, the route table, and the optional-extra install command. Add a `tests/dashboard/` row to the test-files table. Mention the demo-spec relationship in one sentence.
- `examples/real_wallet_report.py` — add a one-line note at the top: `# For an interactive multi-wallet view, see: pip install ai-accountant[dashboard] && dashboard serve`.
- No README changes proposed in this spec — README is out of date relative to the modular split already; updating it is a separate housekeeping pass.

### 9.4 Versioning posture

- The `dashboard/` sub-package is **not** part of the package's public API guarantee, same as `demo/` will be. The namespace itself signals "wired up enough to ship, not stable enough to depend on programmatically." External callers should stick to `SolanaDataFetcher`, `TransactionParser`, `validate_address`, `DATAFRAME_COLUMNS`, the exception hierarchy, and the `report.*` helpers.
- Cache layout (`schema_version`) is the only thing future versions of the dashboard owe backward-compat to: a bump triggers a fresh fetch, never silent migration.

## 10. Open questions deferred to follow-up work

These are intentionally not part of v1:

- **USD valuation / price oracle integration.** Adds a real dependency on CoinGecko / Pyth / Birdeye and a mint→symbol mapping layer. Same reasoning as the demo spec.
- **Counterparty analysis panel.** Extracting `from`/`to` addresses across `movements_in/out` and surfacing the most-frequent ones.
- **Per-token drill-down page.** Filter bar + asset-flow table covers most of the use case; a dedicated page is sugar.
- **Search by address or signature** beyond the `q` substring filter.
- **Background fetch jobs.** Long fetches block the request. If desired, a separate spec adds a job queue, polling, and a progress indicator.
- **Sharing infrastructure with the unbuilt `demo/`.** Refactor signposts in §9.2 are the input to that work, not its design.
- **Multi-wallet correlation.** A single dashboard page covering several wallets at once.
