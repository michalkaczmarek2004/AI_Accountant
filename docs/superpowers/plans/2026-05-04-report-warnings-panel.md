# Report scope-warnings panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a typed `ReportWarning` panel to the top of `render_html_report`'s output, anchored by a built-in `NOT_AN_AUDIT` blocking warning and extensible via a caller-supplied `report_warnings` kwarg. Replace today's prose `_notice()` block.

**Architecture:** All new code lives in the existing `src/ai_accountant/report.py`. A `ReportWarning` dataclass + four module-level constants (`NOT_AN_AUDIT`, `SYNTHETIC_FIXTURE`, `LIVE_UNVERIFIED_DATA`, `NO_PRICE_DATA`) form the data layer. An internal `_resolve_warnings(extras)` prepends `NOT_AN_AUDIT` and stable-sorts by severity (`blocking → warning → info`, unknown → last). A new `_warnings_panel(warnings)` HTML helper renders the panel; it is wired into `render_html_report` in place of the deleted `_notice()` helper. `write_wallet_report` forwards the kwarg. Two example scripts pass their context-specific warnings.

**Tech Stack:** Python 3.10+, stdlib `dataclasses` + `html.escape`, `pandas` (already a dep). Tests use stdlib `unittest` and `unittest.mock.patch`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-04-report-warnings-panel-design.md`

---

## File map

| File | Change |
|---|---|
| `src/ai_accountant/report.py` | Add `ReportWarning`, `SEVERITY_ORDER`, four constants, `_resolve_warnings`, `_warnings_panel`; add `report_warnings` kwarg to `render_html_report` and `write_wallet_report`; delete `_notice()`; extend `_stylesheet()`; extend `__all__` |
| `src/ai_accountant/__init__.py` | Re-export 5 new names; extend `__all__` |
| `tests/test_report.py` | Add 8 new test methods to `ReportTests`; extend imports |
| `examples/demo_html_report.py` | Pass `[SYNTHETIC_FIXTURE, NO_PRICE_DATA]` to `write_wallet_report` |
| `examples/real_wallet_report.py` | Pass `[LIVE_UNVERIFIED_DATA, NO_PRICE_DATA]` to `write_wallet_report` |

No new files. No deleted files (only the `_notice` function inside `report.py`).

---

## Task 1 — Foundation: `ReportWarning`, `NOT_AN_AUDIT`, minimal panel

Adds the dataclass, the always-on built-in warning, the panel renderer hardcoded for that single warning, and deletes `_notice()`. Two contract tests pin the result.

**Files:**
- Modify: `src/ai_accountant/report.py` (imports, new constants/helpers, `render_html_report` body, delete `_notice`, extend stylesheet, extend `__all__`)
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing tests**

Append to the `ReportTests` class in `tests/test_report.py`:

```python
    def test_warnings_panel_always_includes_not_an_audit(self):
        html = render_html_report(_frame(), WALLET)
        self.assertIn("NOT_AN_AUDIT", html)
        self.assertIn("Not an audit", html)
        self.assertIn("does not include cost basis", html)

        html_explicit_empty = render_html_report(_frame(), WALLET, report_warnings=())
        self.assertIn("NOT_AN_AUDIT", html_explicit_empty)

    def test_render_html_report_no_longer_contains_legacy_notice(self):
        html = render_html_report(_frame(), WALLET)
        self.assertNotIn("real on-chain activity fetched from Helius", html)
        self.assertNotIn("not a final tax filing", html)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_report.py::ReportTests::test_warnings_panel_always_includes_not_an_audit tests/test_report.py::ReportTests::test_render_html_report_no_longer_contains_legacy_notice -v`

Expected: both FAIL. The first because `report_warnings` is an unknown kwarg and the rendered HTML doesn't contain `NOT_AN_AUDIT`. The second because `_notice()` still produces the "real on-chain activity fetched from Helius" string.

- [ ] **Step 3: Update imports in `src/ai_accountant/report.py`**

Replace lines 5-11:

```python
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Any
```

(Adds `Sequence` to the `collections.abc` line and adds `from dataclasses import dataclass`.)

- [ ] **Step 4: Add the data model and constant after `EXPORT_COLUMNS`**

Insert immediately after the `EXPORT_COLUMNS` block (after line 30 in the current file) and before `def render_html_report(`:

```python
SEVERITY_ORDER = ("blocking", "warning", "info")


@dataclass(frozen=True)
class ReportWarning:
    """A typed scope/limitation note rendered at the top of the HTML report."""

    severity: str
    code: str
    title: str
    message: str


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

- [ ] **Step 5: Add `_warnings_panel` and `_warning_card` helpers**

Insert near the other section helpers (alongside `_section`, `_notice`, etc.) — recommended location is just before the existing `def _notice()` definition:

```python
def _warnings_panel(warnings: Sequence[ReportWarning]) -> str:
    cards = "\n".join(_warning_card(w) for w in warnings)
    return f"""
    <section class="warnings-panel" aria-label="Report scope and limitations">
      {cards}
    </section>
    """


def _warning_card(warning: ReportWarning) -> str:
    severity = escape(warning.severity)
    code = escape(warning.code)
    title = escape(warning.title)
    message = escape(warning.message)
    return f"""
      <article class="warning-card warning-{severity}">
        <header>
          <span class="severity-badge {severity}">{severity.capitalize()}</span>
          <code class="warning-code">{code}</code>
        </header>
        <h3>{title}</h3>
        <p>{message}</p>
      </article>
    """
```

- [ ] **Step 6: Add `report_warnings` kwarg to `render_html_report` and swap `_notice()` for `_warnings_panel`**

Modify the function signature (currently lines 33-39) and body. Replace:

```python
def render_html_report(
    transactions: pd.DataFrame,
    wallet_address: str,
    *,
    max_transactions: int = 250,
    generated_at: datetime | None = None,
) -> str:
    """Render a self-contained HTML report from an AI Accountant DataFrame."""
    generated_at = generated_at or datetime.now(timezone.utc)
```

with:

```python
def render_html_report(
    transactions: pd.DataFrame,
    wallet_address: str,
    *,
    max_transactions: int = 250,
    generated_at: datetime | None = None,
    report_warnings: Sequence[ReportWarning] = (),
) -> str:
    """Render a self-contained HTML report from an AI Accountant DataFrame."""
    generated_at = generated_at or datetime.now(timezone.utc)
    warnings = [NOT_AN_AUDIT, *report_warnings]
```

Then in the body of the function, replace the line `_notice(),` (currently line 64) with:

```python
            _warnings_panel(warnings),
```

- [ ] **Step 7: Delete the `_notice()` function**

Remove the entire `_notice()` definition (currently lines 348-356):

```python
def _notice() -> str:
    return """
    <section class="notice">
      <strong>What this report is:</strong> real on-chain activity fetched from Helius and
      normalized by AI Accountant. <strong>What it is not:</strong> a final tax filing.
      USD valuation, off-chain cost basis, CEX imports and legal citations still need to be
      connected before the output can be treated as an accounting conclusion.
    </section>
    """
```

- [ ] **Step 8: Add CSS rules for the warnings panel**

Append the following just before the closing `"""` of `_stylesheet()` (currently around line 760, just before the `"""` and `return`):

```css
    .warnings-panel {
      display: grid;
      gap: 12px;
      margin: 18px 0;
    }
    .warning-card {
      padding: 14px 16px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-left-width: 4px;
      border-radius: 8px;
    }
    .warning-card header {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .warning-card h3 {
      margin: 8px 0 6px;
      font-size: 15px;
      letter-spacing: 0;
    }
    .warning-card p {
      margin: 0;
      color: #344047;
    }
    .warning-code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
      color: var(--muted);
    }
    .warning-blocking { border-left-color: var(--bad); }
    .warning-warning  { border-left-color: var(--warn); }
    .warning-info     { border-left-color: var(--accent); }
    .severity-badge {
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .severity-badge.blocking { background: #f8dfdc; color: var(--bad); }
    .severity-badge.warning  { background: #f8edd7; color: var(--warn); }
    .severity-badge.info     { background: #d9eef0; color: var(--accent); }
```

- [ ] **Step 9: Extend `__all__` in `report.py`**

Replace the existing `__all__` block at the end of `report.py`:

```python
__all__ = [
    "EXPORT_COLUMNS",
    "render_html_report",
    "transaction_export_frame",
    "write_wallet_report",
]
```

with:

```python
__all__ = [
    "EXPORT_COLUMNS",
    "NOT_AN_AUDIT",
    "ReportWarning",
    "render_html_report",
    "transaction_export_frame",
    "write_wallet_report",
]
```

(Convenience constants `SYNTHETIC_FIXTURE`, `LIVE_UNVERIFIED_DATA`, `NO_PRICE_DATA` get added in Task 2.)

- [ ] **Step 10: Run the new tests to verify they pass**

Run: `pytest tests/test_report.py::ReportTests::test_warnings_panel_always_includes_not_an_audit tests/test_report.py::ReportTests::test_render_html_report_no_longer_contains_legacy_notice -v`

Expected: both PASS.

- [ ] **Step 11: Run the full test suite to confirm no regressions**

Run: `pytest`

Expected: all tests PASS. The existing `test_render_html_report_contains_readable_sections`, `test_transaction_export_frame_is_flat_and_ordered_newest_first`, and `test_write_wallet_report_creates_html_and_csv` should be unaffected.

- [ ] **Step 12: Commit**

```bash
git add src/ai_accountant/report.py tests/test_report.py
git commit -m "feat(report): add ReportWarning panel with built-in NOT_AN_AUDIT

Replaces the prose _notice() block with a typed warnings panel.
NOT_AN_AUDIT is always rendered as the first card; the panel is
positioned where _notice() used to sit (after KPI grid, before
Asset Flow). Caller-supplied additions land in Task 2."
```

---

## Task 2 — Caller-supplied warnings + convenience constants

Adds the three convenience constants (`SYNTHETIC_FIXTURE`, `LIVE_UNVERIFIED_DATA`, `NO_PRICE_DATA`) and wires up `_resolve_warnings` so callers can append warnings via `report_warnings=[...]`. Order is not yet sorted by severity — that's Task 3.

**Files:**
- Modify: `src/ai_accountant/report.py` (add 3 constants, add `_resolve_warnings`, swap manual prepend for the resolver)
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

Append to `ReportTests`:

```python
    def test_warnings_panel_appends_caller_warnings(self):
        from ai_accountant.report import SYNTHETIC_FIXTURE

        html = render_html_report(
            _frame(), WALLET, report_warnings=[SYNTHETIC_FIXTURE]
        )
        self.assertIn("NOT_AN_AUDIT", html)
        self.assertIn("SYNTHETIC_FIXTURE", html)
        self.assertIn("Synthetic data", html)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_report.py::ReportTests::test_warnings_panel_appends_caller_warnings -v`

Expected: FAIL — `SYNTHETIC_FIXTURE` does not yet exist in `ai_accountant.report` (`ImportError`).

- [ ] **Step 3: Add the three convenience constants**

Add immediately after `NOT_AN_AUDIT` in `report.py`:

```python
SYNTHETIC_FIXTURE = ReportWarning(
    severity="info",
    code="SYNTHETIC_FIXTURE",
    title="Synthetic data",
    message=(
        "Transactions in this report come from a hand-built fixture, not real "
        "on-chain activity. Useful for evaluating the report layout, not for "
        "verifying real wallet behavior."
    ),
)


LIVE_UNVERIFIED_DATA = ReportWarning(
    severity="warning",
    code="LIVE_UNVERIFIED_DATA",
    title="Live, unverified data",
    message=(
        "Transactions were pulled directly from an upstream data source "
        "without a reconciliation step. Cross-check against an independent "
        "source before using these figures."
    ),
)


NO_PRICE_DATA = ReportWarning(
    severity="warning",
    code="NO_PRICE_DATA",
    title="No fiat valuation",
    message=(
        "Token and native amounts are shown in their on-chain units. "
        "No USD or other fiat valuation has been applied."
    ),
)
```

- [ ] **Step 4: Replace the manual prepend in `render_html_report` with `_resolve_warnings`**

In `render_html_report`, replace:

```python
    warnings = [NOT_AN_AUDIT, *report_warnings]
```

with:

```python
    warnings = _resolve_warnings(report_warnings)
```

Add `_resolve_warnings` near the other helpers (recommended location: immediately above `_warnings_panel`):

```python
def _resolve_warnings(extras: Sequence[ReportWarning]) -> list[ReportWarning]:
    """Prepend the built-in NOT_AN_AUDIT and return the combined list."""
    return [NOT_AN_AUDIT, *extras]
```

(Severity sorting is added in Task 3; this version preserves caller order.)

- [ ] **Step 5: Extend `__all__` in `report.py`**

Add the three new constant names to the `__all__` list (keep alphabetical):

```python
__all__ = [
    "EXPORT_COLUMNS",
    "LIVE_UNVERIFIED_DATA",
    "NO_PRICE_DATA",
    "NOT_AN_AUDIT",
    "ReportWarning",
    "SYNTHETIC_FIXTURE",
    "render_html_report",
    "transaction_export_frame",
    "write_wallet_report",
]
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_report.py::ReportTests::test_warnings_panel_appends_caller_warnings -v`

Expected: PASS.

- [ ] **Step 7: Run the full suite to confirm no regressions**

Run: `pytest`

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/ai_accountant/report.py tests/test_report.py
git commit -m "feat(report): support caller-supplied warnings + 3 convenience constants

Adds SYNTHETIC_FIXTURE, LIVE_UNVERIFIED_DATA, NO_PRICE_DATA constants and
the _resolve_warnings helper that prepends NOT_AN_AUDIT to caller extras.
Severity ordering is added in the next commit."
```

---

## Task 3 — Severity ordering (with within-severity stability)

Sorts the resolved warnings list `blocking → warning → info`, preserving caller order within a severity via Python's stable `sorted()`.

**Files:**
- Modify: `src/ai_accountant/report.py` (extend `_resolve_warnings`)
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing tests**

Append to `ReportTests`:

```python
    def test_warnings_panel_orders_by_severity(self):
        from ai_accountant.report import LIVE_UNVERIFIED_DATA, SYNTHETIC_FIXTURE

        html = render_html_report(
            _frame(),
            WALLET,
            report_warnings=[SYNTHETIC_FIXTURE, LIVE_UNVERIFIED_DATA],
        )
        not_an_audit_pos = html.index("NOT_AN_AUDIT")
        live_unverified_pos = html.index("LIVE_UNVERIFIED_DATA")
        synthetic_pos = html.index("SYNTHETIC_FIXTURE")

        self.assertLess(not_an_audit_pos, live_unverified_pos)
        self.assertLess(live_unverified_pos, synthetic_pos)

    def test_warnings_panel_preserves_caller_order_within_severity(self):
        from ai_accountant.report import ReportWarning

        first = ReportWarning("warning", "FIRST_WARN", "First", "first warning")
        second = ReportWarning("warning", "SECOND_WARN", "Second", "second warning")

        html = render_html_report(
            _frame(), WALLET, report_warnings=[first, second]
        )

        self.assertLess(html.index("FIRST_WARN"), html.index("SECOND_WARN"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_report.py::ReportTests::test_warnings_panel_orders_by_severity tests/test_report.py::ReportTests::test_warnings_panel_preserves_caller_order_within_severity -v`

Expected: `test_warnings_panel_orders_by_severity` FAILS — caller passed `[SYNTHETIC_FIXTURE (info), LIVE_UNVERIFIED_DATA (warning)]`, so without sorting the rendered order is `[NOT_AN_AUDIT, SYNTHETIC_FIXTURE, LIVE_UNVERIFIED_DATA]` and `synthetic_pos < live_unverified_pos`. `test_warnings_panel_preserves_caller_order_within_severity` may already PASS (no sorting yet means caller order is preserved); leave it in — it pins behavior after Task 3 introduces sorting.

- [ ] **Step 3: Implement severity sorting in `_resolve_warnings`**

Replace the existing `_resolve_warnings` body:

```python
def _resolve_warnings(extras: Sequence[ReportWarning]) -> list[ReportWarning]:
    """Prepend NOT_AN_AUDIT, append caller extras, stable-sort by severity."""
    combined = [NOT_AN_AUDIT, *extras]
    rank = {sev: i for i, sev in enumerate(SEVERITY_ORDER)}
    return sorted(combined, key=lambda w: rank[w.severity])
```

(Unknown-severity fallback is added in Task 4.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_report.py::ReportTests::test_warnings_panel_orders_by_severity tests/test_report.py::ReportTests::test_warnings_panel_preserves_caller_order_within_severity -v`

Expected: both PASS. Python's `sorted()` is stable so within-severity caller order is preserved automatically.

- [ ] **Step 5: Run the full suite**

Run: `pytest`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ai_accountant/report.py tests/test_report.py
git commit -m "feat(report): sort warnings by severity (blocking, warning, info)

Stable sort preserves caller order within a severity bucket."
```

---

## Task 4 — Unknown severity falls back to last

Hardens `_resolve_warnings` so a caller-defined severity (e.g., `"urgent"`) doesn't `KeyError`; instead the warning sorts after all known severities.

**Files:**
- Modify: `src/ai_accountant/report.py` (one-line resolver tweak)
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

Append to `ReportTests`:

```python
    def test_warnings_panel_unknown_severity_sorts_last(self):
        from ai_accountant.report import ReportWarning, SYNTHETIC_FIXTURE

        urgent = ReportWarning("urgent", "URGENT_NOTE", "Urgent", "needs attention")
        html = render_html_report(
            _frame(),
            WALLET,
            report_warnings=[urgent, SYNTHETIC_FIXTURE],
        )

        # Order: NOT_AN_AUDIT (blocking) → SYNTHETIC_FIXTURE (info)
        # → URGENT_NOTE (unknown, last)
        self.assertLess(html.index("SYNTHETIC_FIXTURE"), html.index("URGENT_NOTE"))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_report.py::ReportTests::test_warnings_panel_unknown_severity_sorts_last -v`

Expected: FAIL with `KeyError: 'urgent'` raised inside `_resolve_warnings`.

- [ ] **Step 3: Switch the resolver to use `rank.get(...)` with a fallback**

In `_resolve_warnings`, replace:

```python
    return sorted(combined, key=lambda w: rank[w.severity])
```

with:

```python
    return sorted(combined, key=lambda w: rank.get(w.severity, len(SEVERITY_ORDER)))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_report.py::ReportTests::test_warnings_panel_unknown_severity_sorts_last -v`

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ai_accountant/report.py tests/test_report.py
git commit -m "fix(report): unknown severities sort after known ones, not crash

Defensive: a caller-defined severity outside (blocking, warning, info)
no longer raises KeyError. The warning still renders, just at the bottom."
```

---

## Task 5 — HTML escaping in warning fields

Pins that all four `ReportWarning` fields are HTML-escaped when rendered. Since `_warning_card` (Task 1) already calls `escape()` on each field, this test should pass without further implementation — it acts as a regression guard.

**Files:**
- Modify: `src/ai_accountant/report.py` (only if `escape()` was missed in Task 1; otherwise no code change)
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing (or passing-as-guard) test**

Append to `ReportTests`:

```python
    def test_warnings_panel_renders_message_html_escaped(self):
        from ai_accountant.report import ReportWarning

        nasty = ReportWarning(
            "warning",
            "XSS_TEST",
            "<b>Title</b>",
            "<script>alert(1)</script>",
        )

        html = render_html_report(_frame(), WALLET, report_warnings=[nasty])

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertNotIn("<b>Title</b>", html)
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_report.py::ReportTests::test_warnings_panel_renders_message_html_escaped -v`

Expected: PASS (because `_warning_card` from Task 1 calls `escape()` on every field). If it FAILS, audit `_warning_card` and ensure each interpolated value goes through `escape()`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_report.py
git commit -m "test(report): pin html-escape regression guard for warning fields"
```

---

## Task 6 — Forward `report_warnings` through `write_wallet_report`

The kwarg currently lives on `render_html_report` only. `write_wallet_report` needs to accept it and forward it.

**Files:**
- Modify: `src/ai_accountant/report.py` (signature + forwarding call)
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

Append to `ReportTests`:

```python
    def test_write_wallet_report_passes_warnings_through_to_html(self):
        from unittest.mock import patch

        from ai_accountant.report import (
            SYNTHETIC_FIXTURE,
            render_html_report as real_render,
            write_wallet_report,
        )

        captured: dict = {}

        def spy(transactions, wallet_address, **kwargs):
            captured["report_warnings"] = kwargs.get("report_warnings")
            return real_render(transactions, wallet_address, **kwargs)

        with (
            patch("ai_accountant.report.render_html_report", side_effect=spy),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
            patch("pandas.DataFrame.to_csv"),
        ):
            write_wallet_report(
                _frame(), WALLET, "reports", report_warnings=[SYNTHETIC_FIXTURE]
            )

        self.assertEqual(captured["report_warnings"], [SYNTHETIC_FIXTURE])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_report.py::ReportTests::test_write_wallet_report_passes_warnings_through_to_html -v`

Expected: FAIL — `write_wallet_report` doesn't accept `report_warnings` (`TypeError: unexpected keyword argument`).

- [ ] **Step 3: Add the kwarg and forward it**

In `write_wallet_report` (currently lines 75-103), update the signature and the body. Replace the existing function with:

```python
def write_wallet_report(
    transactions: pd.DataFrame,
    wallet_address: str,
    output_dir: str | Path = "reports",
    *,
    max_transactions: int = 250,
    report_warnings: Sequence[ReportWarning] = (),
) -> dict[str, Path]:
    """Write HTML and CSV report files and return their paths."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    wallet_prefix = _filename_token(wallet_address[:12] or "wallet")
    base = f"ai_accountant_{wallet_prefix}_{stamp}"

    html_path = target / f"{base}.html"
    csv_path = target / f"{base}_transactions.csv"

    html_path.write_text(
        render_html_report(
            transactions,
            wallet_address,
            max_transactions=max_transactions,
            report_warnings=report_warnings,
        ),
        encoding="utf-8",
    )
    transaction_export_frame(transactions).to_csv(csv_path, index=False)

    return {"html": html_path, "csv": csv_path}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_report.py::ReportTests::test_write_wallet_report_passes_warnings_through_to_html -v`

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest`

Expected: all PASS — including the existing `test_write_wallet_report_creates_html_and_csv` which calls `write_wallet_report` without the new kwarg (default `()` keeps the old contract).

- [ ] **Step 6: Commit**

```bash
git add src/ai_accountant/report.py tests/test_report.py
git commit -m "feat(report): forward report_warnings through write_wallet_report"
```

---

## Task 7 — Re-export new names from the package `__init__.py`

So callers can `from ai_accountant import ReportWarning, SYNTHETIC_FIXTURE, ...` instead of reaching into `ai_accountant.report`.

**Files:**
- Modify: `src/ai_accountant/__init__.py` (extend imports + `__all__`)
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

Append to `ReportTests`:

```python
    def test_warning_names_re_exported_from_top_level_package(self):
        import ai_accountant

        from ai_accountant import (
            LIVE_UNVERIFIED_DATA,
            NO_PRICE_DATA,
            NOT_AN_AUDIT,
            ReportWarning,
            SYNTHETIC_FIXTURE,
        )

        self.assertIsInstance(NOT_AN_AUDIT, ReportWarning)
        self.assertEqual(NOT_AN_AUDIT.code, "NOT_AN_AUDIT")
        self.assertEqual(SYNTHETIC_FIXTURE.severity, "info")
        self.assertEqual(LIVE_UNVERIFIED_DATA.severity, "warning")
        self.assertEqual(NO_PRICE_DATA.severity, "warning")

        for name in (
            "ReportWarning",
            "NOT_AN_AUDIT",
            "SYNTHETIC_FIXTURE",
            "LIVE_UNVERIFIED_DATA",
            "NO_PRICE_DATA",
        ):
            self.assertIn(name, ai_accountant.__all__)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_report.py::ReportTests::test_warning_names_re_exported_from_top_level_package -v`

Expected: FAIL — `ImportError` on the new names.

- [ ] **Step 3: Update `src/ai_accountant/__init__.py`**

Replace the current contents:

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
from .report import render_html_report, transaction_export_frame, write_wallet_report

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
    "render_html_report",
    "transaction_export_frame",
    "validate_address",
    "write_wallet_report",
]
```

with:

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
from .report import (
    LIVE_UNVERIFIED_DATA,
    NO_PRICE_DATA,
    NOT_AN_AUDIT,
    SYNTHETIC_FIXTURE,
    ReportWarning,
    render_html_report,
    transaction_export_frame,
    write_wallet_report,
)

__all__ = [
    "DATAFRAME_COLUMNS",
    "HeliusAPIError",
    "HeliusAuthenticationError",
    "HeliusPermissionError",
    "HeliusRateLimitError",
    "InvalidSolanaAddressError",
    "LIVE_UNVERIFIED_DATA",
    "NOT_AN_AUDIT",
    "NO_PRICE_DATA",
    "ReportWarning",
    "SYNTHETIC_FIXTURE",
    "SolanaDataFetcher",
    "SolanaDataFetcherError",
    "TransactionParser",
    "render_html_report",
    "transaction_export_frame",
    "validate_address",
    "write_wallet_report",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_report.py::ReportTests::test_warning_names_re_exported_from_top_level_package -v`

Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ai_accountant/__init__.py tests/test_report.py
git commit -m "feat(api): re-export ReportWarning + warning constants from ai_accountant"
```

---

## Task 8 — Update `examples/demo_html_report.py` to pass demo warnings

The synthetic-data example should declare it's running on a hand-built fixture and that no fiat valuation is applied.

**Files:**
- Modify: `examples/demo_html_report.py`

- [ ] **Step 1: Update the example script**

Replace the current contents of `examples/demo_html_report.py`:

```python
"""Write the readable HTML report using the existing synthetic demo dataset."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_accountant.report import write_wallet_report  # noqa: E402
from audit_demo import WALLET, build_dataframe  # noqa: E402


def main() -> int:
    frame = build_dataframe()
    paths = write_wallet_report(frame, WALLET, "reports")
    print(f"HTML report: {paths['html'].resolve()}")
    print(f"CSV export:   {paths['csv'].resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

with:

```python
"""Write the readable HTML report using the existing synthetic demo dataset."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_accountant import (  # noqa: E402
    NO_PRICE_DATA,
    SYNTHETIC_FIXTURE,
    write_wallet_report,
)
from audit_demo import WALLET, build_dataframe  # noqa: E402


def main() -> int:
    frame = build_dataframe()
    paths = write_wallet_report(
        frame,
        WALLET,
        "reports",
        report_warnings=[SYNTHETIC_FIXTURE, NO_PRICE_DATA],
    )
    print(f"HTML report: {paths['html'].resolve()}")
    print(f"CSV export:   {paths['csv'].resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-run the example**

Run: `python examples/demo_html_report.py`

Expected: the script prints two file paths, exits 0, writes a fresh HTML and CSV under `reports/`.

- [ ] **Step 3: Visually inspect the HTML**

Open the printed HTML path in a browser. Expected: the warnings panel at the top contains three cards in `blocking → warning → info` order:
1. `NOT_AN_AUDIT` (blocking, red left border)
2. `NO_PRICE_DATA` (warning, amber left border)
3. `SYNTHETIC_FIXTURE` (info, accent left border)

- [ ] **Step 4: Run the full test suite to confirm no regressions**

Run: `pytest`

Expected: all PASS. (Examples are not in `pytest testpaths` per `CLAUDE.md`, but the change should not affect anything that is.)

- [ ] **Step 5: Commit**

```bash
git add examples/demo_html_report.py
git commit -m "docs(examples): demo report declares SYNTHETIC_FIXTURE + NO_PRICE_DATA"
```

---

## Task 9 — Update `examples/real_wallet_report.py` to pass live-data warnings

The real-wallet example should declare that the upstream pull is unreconciled and that no fiat valuation is applied.

**Files:**
- Modify: `examples/real_wallet_report.py`

- [ ] **Step 1: Update imports and the `write_wallet_report` call**

In `examples/real_wallet_report.py`, replace the existing import line (currently line 18):

```python
from ai_accountant.report import write_wallet_report  # noqa: E402
```

with:

```python
from ai_accountant import (  # noqa: E402
    LIVE_UNVERIFIED_DATA,
    NO_PRICE_DATA,
    write_wallet_report,
)
```

Then replace the existing `write_wallet_report` call (currently lines 82-87):

```python
        paths = write_wallet_report(
            frame,
            args.wallet,
            args.output_dir,
            max_transactions=args.max_transactions,
        )
```

with:

```python
        paths = write_wallet_report(
            frame,
            args.wallet,
            args.output_dir,
            max_transactions=args.max_transactions,
            report_warnings=[LIVE_UNVERIFIED_DATA, NO_PRICE_DATA],
        )
```

- [ ] **Step 2: Confirm the script imports cleanly**

Run: `python -c "import ast, pathlib; ast.parse(pathlib.Path('examples/real_wallet_report.py').read_text())"`

Expected: no output, exit 0.

- [ ] **Step 3: Skip the live smoke test if no Helius key is available**

If `HELIUS_API_KEY` and `SOLANA_WALLET` are set in the environment, run: `python examples/real_wallet_report.py --max-pages 1` and visually confirm the rendered HTML shows `NOT_AN_AUDIT` + `LIVE_UNVERIFIED_DATA` + `NO_PRICE_DATA` cards. Otherwise skip — argparse-level smoke is sufficient.

Run: `python examples/real_wallet_report.py --help`

Expected: help text printed, exit 0. Confirms the imports and argparse plumbing are intact.

- [ ] **Step 4: Run the full test suite to confirm no regressions**

Run: `pytest`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add examples/real_wallet_report.py
git commit -m "docs(examples): real-wallet report declares LIVE_UNVERIFIED_DATA + NO_PRICE_DATA"
```

---

## Final verification

- [ ] **Run the entire test suite once more**

Run: `pytest -v`

Expected: all tests PASS, including the 8 new `ReportTests` methods (`test_warnings_panel_always_includes_not_an_audit`, `test_render_html_report_no_longer_contains_legacy_notice`, `test_warnings_panel_appends_caller_warnings`, `test_warnings_panel_orders_by_severity`, `test_warnings_panel_preserves_caller_order_within_severity`, `test_warnings_panel_unknown_severity_sorts_last`, `test_warnings_panel_renders_message_html_escaped`, `test_write_wallet_report_passes_warnings_through_to_html`, `test_warning_names_re_exported_from_top_level_package`).

- [ ] **Lint/format check**

Run: `ruff check . && ruff format --check .`

Expected: both clean.

- [ ] **Smoke-render the demo HTML one last time**

Run: `python examples/demo_html_report.py`

Open the resulting HTML and confirm: warnings panel sits where the old `_notice()` block used to (after KPI grid, before "Asset Flow"); three cards visible; `NOT_AN_AUDIT` first with a red left border.

---

## Self-review checklist

**Spec coverage** (cross-referenced against `docs/superpowers/specs/2026-05-04-report-warnings-panel-design.md`):

| Spec section | Plan task(s) |
|---|---|
| §2 Data model — `ReportWarning` dataclass + `SEVERITY_ORDER` | Task 1 (steps 3-4) |
| §2.1 `NOT_AN_AUDIT` constant | Task 1 (step 4) |
| §2.2 `SYNTHETIC_FIXTURE`, `LIVE_UNVERIFIED_DATA`, `NO_PRICE_DATA` constants | Task 2 (step 3) |
| §2.3 Public surface re-exports | Task 7 |
| §3 API: `report_warnings` kwarg on `render_html_report` | Task 1 (step 6) |
| §3 API: `report_warnings` kwarg on `write_wallet_report` | Task 6 |
| §3 API: `transaction_export_frame` unchanged | (no task; unmodified) |
| §3.1 `_resolve_warnings` resolver | Task 2 (step 4 — basic), Task 3 (step 3 — sort), Task 4 (step 3 — fallback) |
| §3.1 No deduplication | Implicitly covered: no dedup logic added |
| §4.1 Markup with `warnings-panel`, `warning-card`, severity badge, code, title, message | Task 1 (step 5) |
| §4.2 CSS for three card variants + badges | Task 1 (step 8) |
| §4.3 Order enforced in HTML, not CSS | Task 3 (sorted before render) |
| §4.4 Escaping all four fields | Task 1 (step 5 escapes); Task 5 (regression guard) |
| §5.1 `examples/demo_html_report.py` updated | Task 8 |
| §5.2 `examples/real_wallet_report.py` updated | Task 9 |
| §5.3 `audit_demo.py` and `legal_grounding.py` untouched | (no task; left alone) |
| §6 All 7 named tests + the new write_wallet_report forwarding test | Tasks 1, 2, 3, 4, 5, 6, 7 (and the per-task "run pytest" steps catch existing-test regressions) |
| §7 Out-of-scope items | (no task; left alone) |

All spec sections covered. No gaps.

**Placeholder scan:** No "TBD"/"TODO"/"implement later" strings; every code step shows the actual code. No "similar to Task N" cross-references — code is repeated where it would be needed out of order.

**Type/symbol consistency:** `ReportWarning`, `SEVERITY_ORDER`, `NOT_AN_AUDIT`, `SYNTHETIC_FIXTURE`, `LIVE_UNVERIFIED_DATA`, `NO_PRICE_DATA`, `_resolve_warnings`, `_warnings_panel`, `_warning_card`, `report_warnings` — names match identically across all task descriptions. Function signatures (`render_html_report`, `write_wallet_report`) declared in Task 1 / Task 6 match the example call sites in Tasks 8/9.
