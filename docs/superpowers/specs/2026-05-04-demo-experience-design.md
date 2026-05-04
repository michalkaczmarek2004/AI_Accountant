# Design — Ready-to-run demo experience for AI Accountant

**Status:** Approved (brainstorm), pending implementation plan
**Author:** Brainstormed with user, 2026-05-04
**Audience:** Auditors and firms doing pilot evaluations of the project
**Scope:** v1 demo — synthetic data only; live wallet mode is explicitly out of scope

---

## 1. Goal

Make it possible to evaluate the AI Accountant audit pipeline without writing Python. Today the pipeline lives in `examples/audit_demo.py` and `examples/legal_grounding.py` as illustrative scaffolds invoked by `python examples/<file>.py` and dumped to stdout. After this work the same pipeline ships as a small CLI plus a local web UI:

```
$ pip install ai-accountant[demo]
$ audit demo                         # one command -> report on disk
$ audit serve                        # one command -> local web UI
```

The deliverable is the same audit pipeline, surfaced through two entrypoints, producing one structured report in three formats (HTML, JSON, CSV), with the existing `BLOCKING_VERIFICATION_GATE` from `legal_grounding.py` rendered front-and-centre.

## 2. Audience and what they need

The primary user is an auditor or firm evaluating the project — not a developer paste-and-run user, and not a non-technical wallet owner. Concretely they need:

- A defensible, structured report whose every assumption is documented.
- Prominent display of the `[UNVERIFIED]` legal-citation warnings — the safety rail is the credibility signal.
- Both human-facing (HTML) and machine-readable (JSON, CSV) artifacts so the report can be reviewed in a browser, re-ingested into other tools, and inspected in Excel.
- Confidence that the demo will not silently emit a wrong-looking number — the synthetic fixture must produce reproducible output, and any limitation (static stub prices, single-wallet scope, US/FIFO defaults) must be visible in the report itself, not buried in code.

## 3. Scope

### In scope (v1)

- New `ai_accountant.demo` sub-package containing the audit pipeline, legal grounding, report renderers, CLI, and Flask app.
- Two CLI subcommands: `audit demo` and `audit serve`.
- Local Flask web UI bound to `127.0.0.1` by default.
- Report renderers for HTML, JSON, and two CSV files (`transactions.csv`, `lots.csv`).
- Always-on legal grounding with the verification gate visibly active.
- Reproducible synthetic fixture lifted from the current `audit_demo.py`.
- Per-run output directories (`./reports/demo-<timestamp>/` for CLI, `.ai_accountant/runs/<run_id>/` for the server).
- Test suite under `tests/demo/` mirroring the new modules.
- Rewritten `examples/audit_demo.py` and `examples/legal_grounding.py` as thin wrappers importing from the new sub-package.

### Out of scope (v1)

- **Live wallet mode.** No `audit wallet <ADDRESS>` command. Live mode requires a real price oracle (CoinGecko / Pyth / Birdeye) and a mint→symbol mapping layer; both are their own multi-day projects. Adding a live command that silently zeroes out USD figures would make the demo *look broken* in the very moment it should be most impressive.
- **Real price oracle.** `prices.py` is intentionally a static stub. The single-file abstraction exists so that swapping in a real oracle later is a one-file change.
- **PDF generation.** The HTML report opens in a browser; auditors who need a file can save-as-PDF. WeasyPrint or similar is premature dependency weight for v1.
- **Multi-wallet correlation.** The `legal_grounding.py` single-wallet limitation is preserved and surfaced in the report's findings, not "fixed."
- **SPA frontend (React/Vue/etc.).** No JS build pipeline in this project today and none added by this work.
- **Server-side persistence beyond the filesystem.** No database, no in-memory cache. Filesystem (`.ai_accountant/runs/`) is the source of truth.
- **Authentication / multi-user.** Loopback-only Flask; the user is the only person reaching `localhost`.

## 4. Architecture

### 4.1 Package layout

```
src/ai_accountant/
├── __init__.py            # unchanged
├── addresses.py           # unchanged
├── client.py              # unchanged
├── dataframe.py           # unchanged
├── exceptions.py          # unchanged
├── parser.py              # unchanged
├── transport.py           # unchanged
├── solana_data_fetcher.py # unchanged (compat shim)
└── demo/                  # NEW — all demo code lives here
    ├── __init__.py        # exports run_audit, render, AuditResult
    ├── fixtures.py        # synthetic Helius transactions (lifted from audit_demo.py)
    ├── classifier.py      # classify(row) -> category
    ├── ledger.py          # FIFO ledger, Lot dataclass
    ├── prices.py          # static stub PRICE_USD + price_usd()
    ├── legal.py           # LegalSource, LEGAL_CORPUS, verification gate
    ├── pipeline.py        # run_audit() + AuditResult + AuditMetadata + ReportWarning
    ├── renderer/
    │   ├── __init__.py    # render(result, fmt) dispatcher
    │   ├── html.py        # Jinja-driven render_html()
    │   ├── json.py        # render_json()
    │   ├── csv.py         # render_csv() — writes transactions.csv + lots.csv
    │   └── templates/
    │       └── report.html.j2
    ├── cli.py             # argparse entrypoint: `audit demo`, `audit serve`
    └── server/
        ├── __init__.py
        ├── app.py         # Flask app factory
        ├── routes.py      # GET /, POST /audit, GET /report/<run_id>, GET /report/<run_id>/<fmt>
        └── static/        # vanilla CSS + minimal JS (no CDN)

examples/
├── audit_demo.py          # rewritten: imports run_audit + render from ai_accountant.demo
└── legal_grounding.py     # rewritten: thin wrapper (legal grounding is now always-on)

tests/demo/
├── __init__.py
├── test_classifier.py
├── test_ledger.py
├── test_legal.py
├── test_pipeline.py
├── test_renderer_html.py
├── test_renderer_json.py
├── test_renderer_csv.py
├── test_cli.py
└── test_server.py

docs/superpowers/specs/
└── 2026-05-04-demo-experience-design.md   # this file

pyproject.toml             # adds:
                           #   [project.optional-dependencies] demo = ["flask>=3.0", "jinja2>=3.1"]
                           #   [project.scripts] audit = "ai_accountant.demo.cli:main"
```

### 4.2 Architectural choices

- **One sub-package, not three.** `ai_accountant.demo` keeps related code colocated and discoverable. Splitting into `audit`, `legal`, `report` would create three new public-API surfaces for code that is explicitly scaffold-quality. The `demo` namespace is itself part of the message: "wired up enough to demo, not stable enough to depend on."
- **Demo deps are an extra.** Core `ai_accountant` keeps its current single-dep footprint (pandas). `pip install ai-accountant[demo]` pulls Flask + Jinja.
- **Examples become thin wrappers.** Anyone with `python examples/audit_demo.py` muscle memory still gets output. The wrapper imports from `ai_accountant.demo` and prints the rendered HTML path. Public API of the core package (`SolanaDataFetcher`, `TransactionParser`, `validate_address`, `DATAFRAME_COLUMNS`, exception hierarchy) is untouched.
- **`prices.py` exists even though it's just a stub.** A single import point makes the future swap to a real oracle a one-file change instead of a grep-and-replace across the pipeline.
- **Legal grounding is always on.** Per the auditor audience, hiding the verification gate by default would send the opposite signal to the credibility we're trying to establish. The gate is the demo's strongest trust signal, not a wart to tuck away.

## 5. The `AuditResult` data model

The pipeline's contract with everything downstream is one typed dataclass:

```python
# ai_accountant/demo/pipeline.py
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import pandas as pd
from .ledger import Ledger
from .legal import GroundedClassification

@dataclass(frozen=True)
class AuditMetadata:
    wallet: str
    period_start: str          # "YYYY-MM-DD"
    period_end: str            # "YYYY-MM-DD"
    jurisdiction: str          # "US federal"
    method: str                # "FIFO, single-wallet, base fiat USD"
    price_source: str          # "static stub (NOT a real oracle)"
    generated_at: str          # ISO 8601 UTC
    pipeline_version: str      # ai_accountant.__version__
    fixture_name: str          # "synthetic-2024-12-to-2025-05"

@dataclass(frozen=True)
class ReportWarning:
    severity: str              # "info" | "warning" | "blocking"
    code: str                  # stable, machine-readable
    message: str               # human-readable, full sentence

@dataclass
class AuditResult:
    metadata: AuditMetadata
    classified: pd.DataFrame
    grounded: list[GroundedClassification]
    ledger: Ledger
    findings: list[dict[str, Any]]
    consistency_checks: list[str]
    totals: dict[str, Decimal]               # income_usd, gain_usd, fee_usd
    unverified_citation_count: int
    report_warnings: list[ReportWarning]
```

### 5.1 Field-level rationale

- **`pd.DataFrame` stays in the result.** It is already the project's canonical row representation. Serializing a DataFrame for JSON/CSV is trivial; inventing a parallel "transaction model" dataclass would duplicate the parser's invariants for no gain.
- **`grounded` is parallel to `classified` (one entry per row, matched by signature).** Keeps the financial DataFrame untouched. If we ever want a "render without legal" mode, it is a one-line guard, not a refactor.
- **`unverified_citation_count` is a top-level integer.** Single source of truth for the gate's count. The HTML banner and JSON output both read this integer; the `VERIFICATION_GATE` warning's `message` interpolates it. No double-rendering.
- **`report_warnings` is the structured surface for report-level caveats.** Renderers iterate it in `severity` order. v1 always populates `SYNTHETIC_FIXTURE` (info) and `PRICE_STATIC_STUB` (warning); `VERIFICATION_GATE` (blocking) is added iff `unverified_citation_count > 0`.
- **All financial values are `Decimal`.** Matches the parser's invariant. `totals` is `dict[str, Decimal]`. JSON serialization stringifies Decimals (does not coerce to float) to preserve precision.
- **`AuditMetadata` is frozen; the rest is mutable.** Metadata is immutable provenance; the body is structured data renderers consume.
- **No "live mode" fields in v1.** When live mode lands, `AuditMetadata` gains a `data_source` field and the warnings list loses `SYNTHETIC_FIXTURE`. Nothing else changes.

### 5.2 The three v1 warnings

| code | severity | message |
|---|---|---|
| `SYNTHETIC_FIXTURE` | `info` | "This audit was run against a synthetic fixture; transactions are illustrative, not real on-chain activity." |
| `PRICE_STATIC_STUB` | `warning` | "USD figures derived from a static price stub, not a real oracle. Replace with a live oracle before relying on valuation." |
| `VERIFICATION_GATE` | `blocking` | "BLOCKING VERIFICATION GATE — {N} citations unverified. Report MUST NOT be relied upon as authoritative until citations are verified by a real RAG retriever." |

## 6. Pipeline shape

```python
def run_audit(fixture: list[dict]) -> AuditResult:
    df = _to_dataframe(fixture)                          # uses SolanaDataFetcher.transactions_to_dataframe
    classified, ledger, findings = _classify_and_book(df)
    grounded = attach_legal_grounding(classified)        # always-on
    checks = consistency_checks(classified, ledger)
    totals = _compute_totals(classified)
    unverified = sum(1 for g in grounded for c in g.citations if c.is_unverified)
    warnings = _build_warnings(unverified)
    return AuditResult(
        metadata=_build_metadata(...),
        classified=classified,
        grounded=grounded,
        ledger=ledger,
        findings=findings,
        consistency_checks=checks,
        totals=totals,
        unverified_citation_count=unverified,
        report_warnings=warnings,
    )
```

### 6.1 Failure semantics

- **Bad fixture (missing required keys)** → `ValueError` with the offending signature. Fail-fast, no partial result.
- **Per-row classification failures** never raise — they become `findings` entries with the signature attached. The audit completes and the report shows the gaps.
- **The verification gate never blocks `run_audit`**. It is a renderer-level visual signal driven by `unverified_citation_count`. Aborting on unverified would defeat the demo: the whole point is showing how the gate flags things.

## 7. CLI

One console-script entrypoint, two subcommands. Pure stdlib `argparse`.

```
$ audit --help
usage: audit {demo,serve} ...

Run an AI Accountant audit over Solana on-chain activity.

subcommands:
  demo     Run the audit pipeline against the synthetic fixture and write a report.
  serve    Start the local Flask web UI for interactive demos.

$ audit demo --help
usage: audit demo [-h] [--out DIR] [--open] [--quiet] [--debug]

options:
  --out DIR    output directory (default: ./reports/demo-<timestamp>/)
  --open       open report.html in the default browser when done
  --quiet      suppress the stdout summary
  --debug      print full tracebacks on error (default: one-line stderr)

$ audit serve --help
usage: audit serve [-h] [--host HOST] [--port PORT]

options:
  --host HOST  bind address (default: 127.0.0.1)
  --port PORT  port (default: 8765)
```

### 7.1 `audit demo` behavior

1. Loads `ai_accountant.demo.fixtures.SYNTHETIC_TRANSACTIONS` and `WALLET`.
2. Calls `run_audit(SYNTHETIC_TRANSACTIONS)`.
3. Calls `render(result, fmt='html')`, `'json'`, `'csv'` — each writes into `--out`.
4. Prints a one-screen stdout summary unless `--quiet`:
   ```
   AI Accountant — synthetic audit
   Wallet:        86xCnPeV…o2MMY
   Period:        2024-12-15 → 2025-05-03
   Income:        $ 33.50
   Net gain:      $ 110.00
   Findings:      N
   Missing basis: M
   Checks:        PASS
   Citations:     K unverified  ⚠  BLOCKING_VERIFICATION_GATE active

   Wrote reports/demo-20260504-141233/
     report.html        (open with --open)
     report.json
     transactions.csv
     lots.csv
   ```
   (Numbers above are illustrative — actual values are whatever the synthetic
   fixture produces. The summary distinguishes `findings` (risk flags) from
   `missing basis` (entries in `ledger.missing_basis`) since they are
   structurally different and an auditor will want both visible at a glance.)

### 7.2 `audit serve` behavior

1. Spins up the Flask app on `127.0.0.1:8765` by default.
2. Prints `Open http://127.0.0.1:8765 in your browser. Ctrl-C to stop.`
3. Does not auto-open a browser by default (CI / headless safe).

### 7.3 Exit codes

- **`0`** — audit completed and all artifacts written. The verification-gate count, findings list, and consistency-check failures are *content* of the report, not CLI errors. The auditor sees them in the report; the shell sees success.
- **`1`** — `run_audit` raised, a renderer raised, or writing the output directory failed (permission denied, disk full). Stderr carries a one-line explanation; the full traceback only prints with `--debug`.
- **`2`** — argparse-level errors (unknown subcommand, bad flag). Default argparse behavior, untouched.

### 7.4 CLI design rationale

- **Two subcommands, not two scripts.** Single entrypoint = single PATH addition, single help surface.
- **No `audit wallet` stub.** Out of scope; a "coming soon" stub creates confusing UX. When live mode is built, `wallet` joins the subcommand list and the rest of the CLI is unchanged.
- **Default output directory is timestamped** so re-running never silently overwrites a prior run. Filenames inside the directory are stable so tooling stays simple.
- **`argparse` over `click`** because the project today has zero CLI deps. A demo extra picking up Flask + Jinja is justifiable; adding Click on top is not.

## 8. Web UI

Spartan Flask app. Three routes, no JS framework, no build step.

### 8.1 Routes

```
GET  /                            landing page — short blurb + "Run synthetic audit" button + recent runs list
POST /audit                       runs run_audit() against the synthetic fixture, redirects to /report/<run_id>
GET  /report/<run_id>             renders the AuditResult as HTML (same template as `audit demo` writes)
GET  /report/<run_id>/<fmt>       raw download:
                                    fmt ∈ {"html", "json", "transactions.csv", "lots.csv"}
                                    strict whitelist; anything else returns 404
GET  /static/<path>               local CSS + minimal JS (no CDN)
```

### 8.2 Run lifecycle

- Each `POST /audit` produces a fresh `run_id` (timestamp + 6 hex chars).
- The `AuditResult` is persisted to disk at `<project_root>/.ai_accountant/runs/<run_id>/` — same directory layout the CLI uses for `--out`.
- The Flask app keeps no in-memory cache and holds no database. Filesystem is the source of truth. Restarting the server preserves all prior runs.
- The CLI and web UI are interchangeable: `audit demo --out .ai_accountant/runs/foo/` produces a directory `audit serve` will happily serve at `/report/foo`.

### 8.3 Landing page

A single screen explaining what the demo is, what the synthetic fixture represents, and a "Run synthetic audit" button. Below it, a **"Recent local demo runs"** list (most recent first, max ~50). The label deliberately reinforces that this is filesystem state on the user's machine, not server-side data. No paste-a-wallet-address form — live mode is out of scope, and a non-functional input would mislead.

### 8.4 Report page

Renders the same HTML template the CLI writes. The template is a single `report.html.j2` that produces a self-contained file (inline CSS, no external assets, no JS) so:

- The CLI's `report.html` can be opened directly from disk with no server.
- The Flask version uses the same template, wrapped in a thin layout that adds a top nav (`← Recent local demo runs`, download links).

### 8.5 Verification-gate banner

Always-visible top banner driven by `result.unverified_citation_count`. Three states:

| condition | banner |
|---|---|
| `unverified_citation_count == 0` | green: "All citations verified against retrieved sources." |
| `unverified_citation_count > 0` | red: "BLOCKING VERIFICATION GATE — N citations unverified. Report MUST NOT be relied upon as authoritative until citations are verified by a real RAG retriever." |
| `grounded` is empty (defensive) | grey: "Legal grounding did not run for this report." |

The red state is the *expected* default for v1 since the demo ships with placeholders. That is the point.

### 8.6 Security posture

- **Binds `127.0.0.1` only by default.** `--host 0.0.0.0` exists but emits a stderr warning: "Binding to non-loopback exposes audit reports to your local network. Press Ctrl-C if this was unintended."
- **No auth.** The audit data is synthetic; the user is the only person reaching `localhost`.
- **`Flask DEBUG=False` always.** No debugger PIN, no auto-reload, no JS injection vectors.
- **Templates use Jinja autoescape** (default for `.html.j2`).
- **`run_id` validated against `^[0-9a-f-]+$`** before any disk lookup — no path traversal.
- **`fmt` whitelist** strictly limits downloadable filenames.

## 9. Output formats

### 9.1 `report.html`

Self-contained, inline CSS, no JS, no external assets. Can be opened from disk or served by Flask. Contains, in order:

1. Header: wallet, period, jurisdiction, method, price source, generated_at, pipeline_version, fixture_name.
2. Verification-gate banner (driven by `unverified_citation_count`).
3. Report caveats panel (rendered from `report_warnings`, ordered `blocking → warning → info`).
4. Executive summary (totals).
5. Breakdown by category.
6. Per-transaction detail table.
7. Remaining open lots (FIFO order).
8. Risk findings.
9. Missing-basis flags.
10. Internal-check failures (only present when non-empty).
11. Strategic-moves block (the existing `_strategic_moves` text).
12. Footer: "ILLUSTRATIVE OUTPUT — NOT TAX OR LEGAL ADVICE."

### 9.2 `report.json`

Single JSON document containing the entire `AuditResult`. Decimals serialized as strings (preserves precision). Schema:

```json
{
  "metadata": { "wallet": "...", "period_start": "...", ... },
  "totals": { "income_usd": "33.50", "gain_usd": "110.00", "fee_usd": "0.06" },
  "unverified_citation_count": 6,
  "report_warnings": [
    { "severity": "blocking", "code": "VERIFICATION_GATE", "message": "..." },
    { "severity": "warning",  "code": "PRICE_STATIC_STUB",  "message": "..." },
    { "severity": "info",     "code": "SYNTHETIC_FIXTURE",  "message": "..." }
  ],
  "classified": [ { "signature": "...", "date": "...", "category": "...", "income_usd": "...", ... } ],
  "grounded": [ { "signature": "...", "category": "...", "citations": [ ... ] } ],
  "ledger": {
    "open_lots": [ { "asset": "...", "units": "...", "basis_usd_per_unit": "...", "acquired": "...", "source": "..." } ],
    "missing_basis": [ { "asset": "...", "units_unbacked": "...", "signature": "...", "date": "...", "reason": "..." } ]
  },
  "findings": [ { "sig": "...", "issue": "...", ... } ],
  "consistency_checks": []
}
```

### 9.3 `transactions.csv` and `lots.csv`

Pure rectangular data. Fixed headers. No comment lines.

`transactions.csv` columns:
```
signature, date, category, income_usd, proceeds_usd, basis_usd, gain_usd, fee_usd
```

`lots.csv` columns:
```
asset, units, basis_usd_per_unit, acquired, source
```

Decimals stringified, not floated. Empty fields are empty (no `null`, no `0` placeholders).

## 10. Error handling

| Layer | Failure | Behavior |
|---|---|---|
| `run_audit()` | bad fixture (missing required keys) | `ValueError` with offending signature |
| `run_audit()` | per-row classification issue | added to `findings`; audit completes |
| `run_audit()` | unverified citations | recorded in `unverified_citation_count` and `report_warnings`; audit completes |
| `render()` | unknown `fmt` | `ValueError` listing supported formats |
| `render_html()` | Jinja undefined-variable / template error | propagates (caught at CLI/server boundary) |
| `render_json()` | non-Decimal numeric in financial path | `TypeError` (this is a real bug, not a runtime variant) |
| `render_csv()` | DataFrame schema drift | `KeyError` with the missing column name |
| CLI | any of the above | exit `1`, one-line stderr, full traceback only with `--debug` |
| Flask `POST /audit` | run_audit raises | 500 + a minimal HTML page showing the exception class and message; full traceback in server logs only |
| Flask `GET /report/<run_id>` | run_id not in `.ai_accountant/runs/` | 404 |
| Flask `GET /report/<run_id>/<fmt>` | `fmt` not in whitelist | 404 |

## 11. Testing

Tests live under `tests/demo/`, mirroring the new sub-package. Existing tests are untouched.

### 11.1 Test files

| file | covers |
|---|---|
| `test_classifier.py` | category dispatch, edge cases (failed tx, internal-only, etc.) |
| `test_ledger.py` | FIFO acquire / dispose_fifo, missing-basis log, Decimal exactness |
| `test_prices.py` | `price_usd()` exact-key hits, `"*"` wildcard fallback, miss returns `None` |
| `test_legal.py` | LEGAL_CORPUS shape, taxable_event-based conflict detection, PLACEHOLDER → unverified counter |
| `test_pipeline.py` | run_audit() end-to-end on the synthetic fixture |
| `test_renderer_html.py` | template renders without raising; gate banner color matches state; warnings rendered ordered by severity; autoescape on; no external network references |
| `test_renderer_json.py` | round-trips; Decimals as strings (not floats); warnings serialized as list-of-dicts |
| `test_renderer_csv.py` | both files have stable headers; no comment lines; Decimals stringified |
| `test_cli.py` | subprocess `python -m ai_accountant.demo.cli demo --out tmp` writes all 4 files; exit codes 0/1/2; --quiet suppresses stdout |
| `test_server.py` | Flask test client: routes, run_id pattern validation, fmt whitelist, DEBUG False |

### 11.2 Key invariants pinned by tests

1. **Decimal exactness** in `AuditResult.totals`, `transactions.csv`, and the JSON output. No float in the financial path. HTML may format with `.quantize(TWO_PLACES)` for display; structured outputs preserve full precision.
2. **`unverified_citation_count` is non-zero by default.** Contract that `BLOCKING_VERIFICATION_GATE` is genuinely active for the demo. A regression that accidentally "verified" all placeholders fails immediately.
3. **The synthetic fixture is reproducible.** Two runs of `run_audit(SYNTHETIC_TRANSACTIONS)` produce equal `totals`, `consistency_checks`, and `unverified_citation_count`. `generated_at` is the only non-stable field.
4. **JSON output schema is documented in `test_renderer_json.py`** as a typed dict the test asserts against. Schema changes require the test to change → forces conscious decisions.
5. **Template rendering is offline.** Test asserts the rendered HTML contains no `http://` or `https://` outside legal-corpus URLs and `mailto:`. Rules out an accidental CDN dependency.
6. **Zero new test deps.** Flask provides `app.test_client()`; no pytest-flask, selenium, or playwright. Server tests run in-process.
7. **Existing tests keep passing.** The `examples/` rewrite must not regress anything. `tests/test_compat_shim.py` already covers the public API; nothing in `examples/` is in `pytest testpaths` so the rewrite is functionally invisible to CI.

### 11.3 Tests added specifically for `report_warnings`

- `test_pipeline.py::test_run_audit_populates_static_warnings` — `SYNTHETIC_FIXTURE` and `PRICE_STATIC_STUB` always present after `run_audit(SYNTHETIC_TRANSACTIONS)`.
- `test_pipeline.py::test_run_audit_populates_verification_gate_warning_when_unverified` — `VERIFICATION_GATE` present iff `unverified_citation_count > 0`; message contains the count as a string.
- `test_renderer_html.py::test_warnings_rendered_near_top_ordered_by_severity` — all warning messages appear in the rendered HTML, ordered `blocking → warning → info`, before the executive-summary section.
- `test_renderer_json.py::test_warnings_serialized_as_list_of_dicts` — `report_warnings` round-trips as `[{"severity": "...", "code": "...", "message": "..."}, ...]`.
- `test_renderer_csv.py` does **not** test for warnings — CSV is pure data.

### 11.4 What the tests deliberately do not cover

- Real Helius — out of scope.
- Real prices — out of scope.
- Browser-rendered visuals — Flask test client is the boundary. We test that the template renders and the right text appears; we do not render with a headless browser.
- PDF generation — explicitly rejected.
- Multi-wallet correlation — `legal_grounding.py` already documents this single-wallet limitation; tests do not promise more.

### 11.5 TDD order

For each new module: write the smallest meaningful contract test first, see it fail, implement until it passes, then move to the next assertion. The pipeline-level test (`test_pipeline.py::test_run_audit_on_synthetic_fixture`) is written *last*, once components are stable, to pin integrated behavior.

## 12. Dependencies

Added to `pyproject.toml`:

```toml
[project.optional-dependencies]
demo = [
    "flask>=3.0",
    "jinja2>=3.1",
]

[project.scripts]
audit = "ai_accountant.demo.cli:main"
```

Core package dependencies are unchanged. Without the `demo` extra, `import ai_accountant.demo` raises `ImportError` at the Flask/Jinja import sites with a helpful message: `"This feature requires the 'demo' extra. Install with: pip install ai-accountant[demo]"`. The CLI subcommands and renderers detect missing extras at the top of `cli.py` and emit the same message before argparse runs.

## 13. Migration of the existing examples

`examples/audit_demo.py` and `examples/legal_grounding.py` are rewritten as thin wrappers that delegate to the CLI:

```python
# examples/audit_demo.py (rewritten)
"""Compat wrapper — see ai_accountant.demo for the real implementation.

This file exists so that `python examples/audit_demo.py` keeps working.
For new usage, prefer the CLI: `audit demo`.
"""
from ai_accountant.demo.cli import main

if __name__ == "__main__":
    main(["demo"])
```

The `legal_grounding.py` wrapper is structurally identical (legal grounding is now part of `run_audit`).

**Install requirements:** the rewritten wrappers import from the installed package, so they require `pip install -e ".[demo]"`. The current examples use a `sys.path.insert` hack to run from a clean checkout; that hack is dropped because the wrappers now also need Flask/Jinja for the renderer. The README is updated accordingly.

These wrappers exist so existing `python examples/audit_demo.py` invocations continue to work. They are *not* covered by tests (per the existing `pytest testpaths` config) and should be removed in a future release once the CLI is the obvious entrypoint.

## 14. Open questions deferred to follow-up work

These are intentionally not part of v1:

- Live wallet mode (`audit wallet <ADDRESS>`).
- Real price oracle integration.
- Multi-wallet correlation.
- PDF output.
- Comparing two audit runs side-by-side.
- Promoting any of `classifier.py`, `ledger.py`, `legal.py` from `demo/` to first-class `ai_accountant.audit` / `ai_accountant.legal` modules with stable API guarantees.

Each of these is its own spec.
