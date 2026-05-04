# Design — Structured scope-warnings panel for the HTML report

**Status:** Approved (brainstorm), pending implementation plan
**Author:** Brainstormed with user, 2026-05-04
**Audience:** Anyone consuming `ai_accountant.report.render_html_report` or `write_wallet_report`
**Scope:** Add a typed, always-on `ReportWarning` panel to the top of the rendered HTML; replace the existing prose `_notice()` block

**Relationship to the larger demo spec.** This is the option-C/2 narrowing of `2026-05-04-demo-experience-design.md`. That spec describes a full `ai_accountant.demo` sub-package (CLI, Flask UI, classifier, FIFO ledger, legal grounding, JSON/HTML/CSV outputs). This design takes only the *credibility-rail banner* idea from it and applies it to the existing parser-level `report.py`. The larger spec remains a reference for future work.

---

## 1. Goal

Add a structured, always-on scope-warning panel to the top of `render_html_report`'s output. The panel replaces today's prose `_notice()` block with a typed list of `ReportWarning`s — always anchored by a `NOT_AN_AUDIT` blocking banner, with caller-supplied additions appended and rendered ordered by severity. The two example scripts pass their context-specific warnings (`SYNTHETIC_FIXTURE`, `LIVE_UNVERIFIED_DATA`, optionally `NO_PRICE_DATA`).

The credibility signal becomes explicit, testable, and easy to extend without pretending the report has the full audit pipeline. The warning panel is an honest scope guardrail, not a fake audit layer.

## 2. Data model

In `src/ai_accountant/report.py`:

```python
SEVERITY_ORDER = ("blocking", "warning", "info")  # rendering order; unknown → last

@dataclass(frozen=True)
class ReportWarning:
    severity: str   # "blocking" | "warning" | "info"
    code: str       # stable, machine-readable, SHOUTY_SNAKE_CASE
    title: str      # short human-readable label, e.g. "Not an audit"
    message: str    # full sentence explaining scope/limitation
```

The dataclass is `frozen` so it's hashable and safe to share as module-level constants.

### 2.1 The built-in anchor

```python
NOT_AN_AUDIT = ReportWarning(
    severity="blocking",
    code="NOT_AN_AUDIT",
    title="Not an audit",
    message=(
        "This report summarizes parsed on-chain wallet activity. It does not "
        "include cost basis, USD valuation, legal citations, or tax/accounting "
        "conclusions."
    ),
)
```

`NOT_AN_AUDIT` is *always* prepended by the renderer (see §3). It cannot be suppressed by callers in v1.

### 2.2 Convenience constants

Three additional `ReportWarning` constants live alongside `NOT_AN_AUDIT` so example scripts (and downstream callers) don't have to hand-construct repeated boilerplate:

| code                 | severity   | title                  | message |
|----------------------|------------|------------------------|---------|
| `SYNTHETIC_FIXTURE`  | `info`     | Synthetic data         | "Transactions in this report come from a hand-built fixture, not real on-chain activity. Useful for evaluating the report layout, not for verifying real wallet behavior." |
| `LIVE_UNVERIFIED_DATA` | `warning` | Live, unverified data | "Transactions were pulled directly from an upstream data source without a reconciliation step. Cross-check against an independent source before using these figures." |
| `NO_PRICE_DATA`      | `warning`  | No fiat valuation      | "Token and native amounts are shown in their on-chain units. No USD or other fiat valuation has been applied." |

`LIVE_UNVERIFIED_DATA` is provider-neutral on purpose — `report.py` does not depend on Helius and the warning shouldn't either. Callers using a non-Helius source still get accurate language.

These are convenience constants, not magic — callers can freely construct their own `ReportWarning` instances.

### 2.3 Public surface

`__init__.py` re-exports the new names so callers can `from ai_accountant import ...`:

```
ReportWarning
NOT_AN_AUDIT
SYNTHETIC_FIXTURE
LIVE_UNVERIFIED_DATA
NO_PRICE_DATA
```

These join the existing `__all__` alphabetically.

## 3. API changes

`render_html_report` and `write_wallet_report` gain a `report_warnings` keyword:

```python
def render_html_report(
    transactions: pd.DataFrame,
    wallet_address: str,
    *,
    max_transactions: int = 250,
    generated_at: datetime | None = None,
    report_warnings: Sequence[ReportWarning] = (),
) -> str: ...

def write_wallet_report(
    transactions: pd.DataFrame,
    wallet_address: str,
    output_dir: str | Path = "reports",
    *,
    max_transactions: int = 250,
    report_warnings: Sequence[ReportWarning] = (),
) -> dict[str, Path]: ...
```

Default `()` (empty tuple, immutable — safe as a default). With no caller additions, the renderer **always** prepends `NOT_AN_AUDIT`. Existing callers pre-this-change get the same panel as a brand-new caller passing no warnings.

`transaction_export_frame` is unchanged — CSV is pure data and gets no warnings column.

### 3.1 Internal resolver

```python
def _resolve_warnings(extras: Sequence[ReportWarning]) -> list[ReportWarning]:
    """Prepend NOT_AN_AUDIT, append caller extras, sort stable by severity."""
    combined = [NOT_AN_AUDIT, *extras]
    rank = {sev: i for i, sev in enumerate(SEVERITY_ORDER)}
    return sorted(combined, key=lambda w: rank.get(w.severity, len(SEVERITY_ORDER)))
```

Stable sort preserves caller order within a severity. Unknown severities sort last (defensive — a caller-defined `"urgent"` doesn't crash the renderer).

No deduplication is attempted. Duplicate caller warnings render as passed, after the built-in `NOT_AN_AUDIT`. (YAGNI; silently dropping a caller's warning is a worse failure mode than showing two.)

## 4. HTML rendering

The new `_warnings_panel(warnings)` block replaces `_notice()` at the same position in `render_html_report` (after the KPI grid, before "Asset Flow"). The call site swaps `_notice()` for `_warnings_panel(_resolve_warnings(report_warnings))`. `_notice()` is deleted.

### 4.1 Markup

One card per warning:

```html
<section class="warnings-panel" aria-label="Report scope and limitations">
  <article class="warning-card warning-blocking">
    <header>
      <span class="severity-badge blocking">Blocking</span>
      <code class="warning-code">NOT_AN_AUDIT</code>
    </header>
    <h3>Not an audit</h3>
    <p>This report summarizes parsed on-chain wallet activity. …</p>
  </article>
  …
</section>
```

The panel always renders with at least the `NOT_AN_AUDIT` card. There is no empty-state branch.

### 4.2 Styling

Three card variants `.warning-blocking` / `.warning-warning` / `.warning-info` are added to the existing inline stylesheet (no new file). They reuse existing palette tokens:

- `.warning-blocking` — `var(--bad)` accent
- `.warning-warning` — `var(--warn)` accent
- `.warning-info` — `var(--accent)` accent (info-blue)

Severity badges reuse the existing `mark` pill convention (`.severity-badge.blocking`, `.severity-badge.warning`, `.severity-badge.info`).

### 4.3 Order

Order is enforced by `_resolve_warnings`, not by CSS. The rendered HTML is already in `blocking → warning → info` order so screen readers and "view source" both match the visual order.

### 4.4 Escaping

All four `ReportWarning` fields are passed through `html.escape()` in the renderer. A warning whose message contains `<script>` shows up as text, not as a script tag.

## 5. Examples

### 5.1 `examples/demo_html_report.py`

Adds `SYNTHETIC_FIXTURE` (synthetic dataset) and `NO_PRICE_DATA` (no fiat valuation):

```python
from ai_accountant import NO_PRICE_DATA, SYNTHETIC_FIXTURE, write_wallet_report

paths = write_wallet_report(
    frame, WALLET, "reports",
    report_warnings=[SYNTHETIC_FIXTURE, NO_PRICE_DATA],
)
```

### 5.2 `examples/real_wallet_report.py`

Adds `LIVE_UNVERIFIED_DATA` (real upstream pull, no reconciliation/sanity layer) and `NO_PRICE_DATA` (no fiat):

```python
from ai_accountant import LIVE_UNVERIFIED_DATA, NO_PRICE_DATA

paths = write_wallet_report(
    frame, args.wallet, args.output_dir,
    max_transactions=args.max_transactions,
    report_warnings=[LIVE_UNVERIFIED_DATA, NO_PRICE_DATA],
)
```

### 5.3 Out-of-scope examples

`examples/audit_demo.py` and `examples/legal_grounding.py` are **not** touched — they're separate scaffolds with their own design points (the `BLOCKING_VERIFICATION_GATE` in `legal_grounding.py` is the anti-hallucination guard documented in CLAUDE.md and stays as-is).

## 6. Tests

New tests added to `tests/test_report.py` (no new file; the surface change is small enough to live with the existing tests):

| test | asserts |
|---|---|
| `test_warnings_panel_always_includes_not_an_audit` | rendering with `report_warnings=()` (and with the kwarg omitted) emits the `NOT_AN_AUDIT` code, title, message, and `severity-badge blocking` class |
| `test_warnings_panel_appends_caller_warnings` | passing `[SYNTHETIC_FIXTURE]` produces both `NOT_AN_AUDIT` and `SYNTHETIC_FIXTURE` cards in the rendered HTML |
| `test_warnings_panel_orders_by_severity` | passing `[SYNTHETIC_FIXTURE, LIVE_UNVERIFIED_DATA]` renders in `blocking → warning → info` order regardless of input order; verified by `html.index()` of each code |
| `test_warnings_panel_preserves_caller_order_within_severity` | two warnings of the same severity appear in caller order |
| `test_warnings_panel_unknown_severity_sorts_last` | a `ReportWarning("urgent", ...)` renders after the three known severities (regression guard for the rank-default branch) |
| `test_warnings_panel_renders_message_html_escaped` | a warning whose message contains `<script>` shows up escaped — `report.py` hand-writes HTML with `escape()`, so this is a real guard, not a Jinja freebie |
| `test_render_html_report_no_longer_contains_legacy_notice` | the old `_notice()` strings ("real on-chain activity fetched from Helius") are absent from the rendered HTML |

Existing tests:

- `test_render_html_report_contains_readable_sections` — doesn't reference `_notice()` content; stays untouched.
- `test_transaction_export_frame_is_flat_and_ordered_newest_first` — unaffected (CSV unchanged).
- `test_write_wallet_report_creates_html_and_csv` — unaffected (signature compatibility).

`__init__.py` test surface: not asserted directly today, but the new exports (`ReportWarning`, `NOT_AN_AUDIT`, `SYNTHETIC_FIXTURE`, `LIVE_UNVERIFIED_DATA`, `NO_PRICE_DATA`) get used by the new tests via `from ai_accountant import ...`, which catches missing-export regressions.

Following the project's existing pattern: stdlib `unittest`, no new test deps. TDD order: write each new test, watch it fail, implement against it.

## 7. Out of scope

These were considered and intentionally excluded — naming them so they don't get smuggled in during implementation:

- **The full `ai_accountant.demo` sub-package** from `2026-05-04-demo-experience-design.md` (`fixtures.py`, `classifier.py`, `ledger.py`, `prices.py`, `legal.py`, `pipeline.py`, `renderer/`). The audit pipeline stays in `examples/audit_demo.py`.
- **`audit` CLI** (`audit demo` / `audit serve`). Existing `python examples/<file>.py` invocations remain the entrypoint.
- **Flask web UI / `audit serve`.** No new dependencies; no `[demo]` extra; `pyproject.toml` is untouched.
- **JSON output / `report.json`.** CSV stays the only structured artifact alongside HTML.
- **Real legal grounding integration.** No `LegalSource`, no `LEGAL_CORPUS`, no citation rendering, no live `unverified_citation_count`. The credibility signal here is the *banner pattern*, not the audit machinery.
- **Auto-detection of warning conditions.** The renderer never sniffs the DataFrame to decide which warnings to add (e.g., it doesn't auto-emit `NO_PRICE_DATA` if no USD column exists). Warnings are caller-driven.
- **Suppressing `NOT_AN_AUDIT`.** No kwarg to disable it. A future caller with a legitimate need is a separate design discussion.
- **Deduplication of caller warnings.** Duplicate caller warnings render as passed, after the built-in `NOT_AN_AUDIT`; no deduplication is attempted.
- **`AuditMetadata` / `report_warnings` JSON schema** from the larger spec. No structured serialization of the warnings list — they only render in HTML. CSV is unchanged.
- **i18n / l10n.** Warning messages are English only.
