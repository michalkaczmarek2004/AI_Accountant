# Tax Assistant — Design Spec

**Date:** 2026-05-09
**Status:** Approved

---

## Overview

Add a dedicated Tax Assistant module to the AI Accountant dashboard. It helps users understand and prepare tax-relevant Solana wallet activity by surfacing tax classification, a review queue, yearly aggregates, and targeted exports — all built on top of the existing `explainer.py`, `tagger.py`, and `report.py` infrastructure.

The Tax Assistant lives at `/wallet/<address>/tax` and is a fully separate page. The main wallet overview is not changed beyond adding a single `[Tax Assistant →]` entry-point button to the header actions area.

---

## Guiding Constraints

- **No legal certainty.** Labels like "Potentially taxable" not "Taxable"; disclaimer always visible.
- **No new data fetching.** All computation runs against the cached DataFrame.
- **Reuse, don't duplicate.** `explainer._classify()`, `_safe_decimal()`, `_is_source_unknown()`, and `explain_row()` are called directly from `tax_assistant.py`. The existing CSV/JSON export infrastructure in `routes.py` is the model for the new tax export routes. `_risk_rows()` is not called — the tax review queue uses its own tier-priority ordering defined in this spec.
- **Transfers are non-taxable by default.** They only appear in the review queue when there is missing information or suspicious context.
- **MVP scope.** No per-tax-jurisdiction logic, no cost-basis calculation, no LLM calls.

---

## Tax Category Mapping

`explainer._classify(row)` returns a `case` key. `tax_assistant.py` maps it to one of seven accounting labels:

| `case` key(s) | Tax category | Taxable by default | Review required |
|---|---|---|---|
| `sol_in`, `token_in`, `nft_received` | Income | Yes | No |
| `sol_out`, `token_out` | Expense | No | No |
| `swap`, `nft_bought`, `nft_sold`, `lp`, `perp` | Swap | Yes | Yes |
| `staking_deposit`, `bridge`, `mint_burn` | Transfer | No | No |
| `staking_withdrawal` | Staking / Needs review | No | Yes |
| `airdrop` | Airdrop | Yes | Yes |
| `unknown` | Unknown / Needs review | No | Yes |

`TAXABLE_CATEGORIES = frozenset({"Income", "Swap", "Airdrop"})`

**Staking withdrawals** are classified as "Staking / Needs review" rather than "Staking reward" because the parser cannot reliably distinguish a principal return from a reward-only payout. They are non-taxable by default but always flagged `review_required = True`. A future parser enhancement may introduce a `staking_reward_only` case that maps to a confirmed "Staking reward" category.

**Unknown transactions** are non-taxable by default but always carry `review_required = True`.

**Transfer** rows are non-taxable by default. A Transfer row enters the review queue only when `_is_source_unknown(row)` is true, `status == "failed"`, `abs(native_net_sol) > LARGE_FLOW_THRESHOLD`, or the original `review_label` is not "No action needed".

`LARGE_FLOW_THRESHOLD = Decimal("0.5")` — MVP default; intended to be made user-configurable in a future release.

---

## New Module: `src/ai_accountant/tax_assistant.py`

### Public API

```python
def tax_category(row: pd.Series) -> str:
    """Map a DataFrame row to one of the eight tax category labels."""

def tax_summary(df: pd.DataFrame, address: str) -> dict[str, Any]:
    """
    Returns:
      total_income_sol   Decimal  – sum of native_net_sol for Income rows (succeeded only)
      total_expense_sol  Decimal  – abs sum of native_net_sol for Expense rows (succeeded only)
      total_fees_sol     Decimal  – sum of fee_sol where fee_paid_by_wallet (succeeded only)
      net_sol            Decimal  – total_income_sol - total_expense_sol
      taxable_count      int      – rows whose tax_category is in TAXABLE_CATEGORIES (succeeded only; staking_withdrawal and unknown excluded)
      review_count       int      – rows in the review queue (all statuses)
    """

def tax_classification_rows(df: pd.DataFrame) -> list[dict]:
    """
    One dict per category present in the DataFrame:
      {category, count, sol_net (Decimal), flagged (bool)}
    Sorted by count descending; "Unknown / Needs review" always last.
    Returns [] if df is empty.
    """

def tax_review_queue(df: pd.DataFrame, *, limit: int = 100) -> list[dict]:
    """
    Rows that need manual review, sorted by priority tier (see below).
    Each dict:
      {date, signature, sig_short, category, sol_net,
       short_explanation, known_facts, unknown_facts, suggested_actions,
       expanded_explanation, review_label, status, source, tag_protocol}
    Populated by calling explain_row() once per qualifying row.
    """

def yearly_summary(df: pd.DataFrame) -> list[dict]:
    """
    [{year, income_sol, expense_sol, fees_sol, taxable_count}]
    Sorted year descending. Returns [] if df is empty.
    """

def tax_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Columns (in order):
      date, signature, status, tax_category, case_key, tag_type,
      sol_net, token_summary, fee_sol, is_potentially_taxable, review_label, notes
    Sorted by timestamp descending.
    """

def tax_yearly_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Flat CSV of yearly_summary()."""
```

### Review Queue Priority Tiers

Rows are ordered by tier (ascending = higher priority), then by `timestamp_unix` descending within each tier:

| Tier | Condition |
|---|---|
| 1 | `tax_category == "Unknown / Needs review"` |
| 2 | `tax_category == "Swap"` |
| 3 | `tax_category == "Airdrop"` |
| 4 | `tax_category == "Staking / Needs review"` |
| 5 | `status == "failed"` |
| 6 | Large inflow or outflow — `abs(native_net_sol) > LARGE_FLOW_THRESHOLD` (0.5 SOL) |
| 7 | Missing counterparty — `_is_source_unknown(row)` |

A row that matches multiple tiers is placed at its lowest tier number. Transfer rows only appear if they hit tier 5, 6, or 7. Income and Expense rows only appear if they hit tier 5, 6, or 7.

`LARGE_FLOW_THRESHOLD = Decimal("0.5")` — MVP default; intended to be user-configurable in a future release.

---

## Dashboard Integration

### New view builder: `views.py`

```python
def tax_page(
    df: pd.DataFrame,
    *,
    address: str,
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    ...
```

Returns a context dict with keys: `address`, `address_short`, `meta`, `summary`, `classification`, `review_queue`, `yearly`, `no_data`.

`no_data` is `True` when `df` is empty or contains no succeeded transactions.

### New routes: `routes.py`

```
GET  /wallet/<address>/tax               → render tax.html.j2
GET  /wallet/<address>/tax-export.csv    → tax_export_frame() as CSV
GET  /wallet/<address>/tax-export.json   → accountant-friendly JSON with metadata wrapper
GET  /wallet/<address>/tax-summary.csv   → tax_yearly_export_frame() as CSV
```

All four routes abort 404 if the cache slot does not exist. No filter querystring — the Tax Assistant always operates on the full cached dataset.

### Entry point: `wallet.html.j2`

One button added inside `.header-actions`:

```html
<a href="{{ url_for('tax_page_route', address=address) }}" class="secondary">Tax Assistant</a>
```

Only rendered when `not no_cache`. No other changes to the wallet overview.

---

## Template: `tax.html.j2`

Sections in render order:

### 1. Page header
```
← Back to wallet DfKL…z4Bm
TAX ASSISTANT
DfKL…z4Bm  ·  Last updated: 2024-12-31 22:39 UTC
```

### 2. Disclaimer (always visible, styled as a notice banner)
> This is not financial or tax advice. Always consult a qualified tax professional.

### 3. Empty state (when `no_data`)
```
No tax-relevant events found for this wallet.
Fetch transactions first, or this wallet has no parsed activity yet.
```
Rendered in place of sections 4–8. Section 9 (disclaimer) always shows.

### 4. Tax summary KPI grid (6 cards)
| Card | Value |
|---|---|
| Income | `+{total_income_sol} SOL` |
| Expense | `-{total_expense_sol} SOL` |
| Fees paid | `{total_fees_sol} SOL` |
| Net change | `±{net_sol} SOL` (green if positive, red if negative) |
| Potentially taxable events | `{taxable_count}` |
| Review needed | `{review_count}` |

CSS: reuse `.kpi-grid`; extend grid to 6 columns (already the case on the wallet page).

### 5. Tax classification table
Columns: Category · Source case · Count · SOL net · Review?

`source case` shows the original `case_key` value (e.g. `swap`, `staking_withdrawal`) so users can trace how the tax category was derived. When a category groups multiple cases (e.g. Swap covers `swap`, `nft_bought`, `nft_sold`, `lp`, `perp`), the column lists all distinct case values present, comma-separated.

`⚠ review` badge (amber) in the Review? column for categories where `review_required = True`.

Empty-category message if `classification == []`.

### 6. Review queue
Each item is a `<details class="tx-row">` / `<summary class="tx-summary">` row (same pattern as the wallet Transactions list).

Summary line: `date · tax_category badge · sig_short · sol_net · review_label badge`

Expanded content (reused from `explain_row()` output):
- `short_explanation`
- Known facts (bullet list)
- Missing information (bullet list, from `unknown_facts`)
- Suggested actions (bullet list)
- `expanded_explanation` (muted paragraph, only if non-empty)
- `[View transaction →]` link to `/wallet/<address>/tx/<sig>`

Empty-state: "No transactions flagged for review."

### 7. Yearly summary table
Columns: Year · Income · Expense · Fees · Potentially taxable

Empty-state: "No yearly data available."

### 8. Export bar
```
[Download Tax CSV]  [Download Accountant JSON]  [Download Yearly Summary CSV]
```

### 9. Disclaimer (repeated at bottom as static text)
Same text as section 2.

---

## Export Formats

### Tax CSV (`tax-export.csv`)
```
date, signature, status, tax_category, case_key, tag_type,
sol_net, token_summary, fee_sol, is_potentially_taxable, review_label, notes
```

`case_key` = output of `explainer._classify(row)` (e.g. `"swap"`, `"sol_in"`).
`tag_type` = raw `tag_type` column from tagger (e.g. `"Swap"`, `"Transfer"`).
`is_potentially_taxable` = `"yes"` / `"no"`.
`notes` = `short_explanation` from `explain_row()` — truncated to 200 chars.

### Accountant JSON (`tax-export.json`)
```json
{
  "meta": {
    "address": "...",
    "generated_at": "...",
    "disclaimer": "This is not financial or tax advice..."
  },
  "summary": { "income_sol": "...", "expense_sol": "...", ... },
  "yearly": [...],
  "transactions": [
    {
      "date": "...",
      "signature": "...",
      "status": "...",
      "tax_category": "...",
      "case_key": "...",
      "tag_type": "...",
      "sol_net": "...",
      "token_summary": "...",
      "fee_sol": "...",
      "is_potentially_taxable": true,
      "review_label": "...",
      "short_explanation": "..."
    }
  ]
}
```

### Yearly Summary CSV (`tax-summary.csv`)
```
year, income_sol, expense_sol, fees_sol, potentially_taxable_count
```

---

## CSS Changes (`dashboard.css`)

- `.tax-disclaimer` — amber notice banner, full width, border-left accent, `var(--warn)` text color
- `.tax-kpi-grid` — same as `.kpi-grid` but `grid-template-columns: repeat(6, minmax(0, 1fr))` at all viewports (not 2-col on mobile)
- `.review-tier` — small muted badge showing priority tier label (e.g. "Swap", "Unknown") on each review queue item summary line

No other CSS changes.

---

## Tests

| File | What it covers |
|---|---|
| `tests/test_tax_assistant.py` | `tax_category`, `tax_summary`, `tax_classification_rows`, `tax_review_queue` (priority ordering, tier logic, limit cap), `yearly_summary`, `tax_export_frame` (columns present, `case_key`+`tag_type` both present), `tax_yearly_export_frame`, empty-DataFrame edge cases for all functions |
| `tests/dashboard/test_tax_views.py` | `tax_page()` returns correct keys; `no_data=True` on empty df; summary values; review queue population and ordering |
| `tests/dashboard/test_routes.py` | GET `/wallet/<address>/tax` → 200 + `text/html`; GET tax CSV → 200 + `text/csv`; GET tax JSON → 200 + `application/json`; GET tax summary CSV → 200 + `text/csv`; 404 on unknown address |

All test fixtures reuse `synthetic_df` from `tests/dashboard/conftest.py`.

---

## File Inventory

| Action | Path |
|---|---|
| New | `src/ai_accountant/tax_assistant.py` |
| New | `src/ai_accountant/dashboard/templates/tax.html.j2` |
| Edit | `src/ai_accountant/dashboard/views.py` — add `tax_page()` |
| Edit | `src/ai_accountant/dashboard/server/routes.py` — add 4 routes |
| Edit | `src/ai_accountant/dashboard/server/static/dashboard.css` — add 3 CSS rules |
| Edit | `src/ai_accountant/dashboard/templates/wallet.html.j2` — add 1 button |
| New | `tests/test_tax_assistant.py` |
| New | `tests/dashboard/test_tax_views.py` |
| Edit | `tests/dashboard/test_routes.py` — add tax route tests |
