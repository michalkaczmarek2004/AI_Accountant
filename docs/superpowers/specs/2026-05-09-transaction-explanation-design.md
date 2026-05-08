# Transaction Explanation Feature — Design Spec

**Date:** 2026-05-09
**Status:** Approved

## Problem

The dashboard transaction table exposes raw technical data (transaction_type codes, source labels, raw amounts) that non-technical users cannot interpret. There is no explanation of what happened, what is uncertain, or what action — if any — the user should take.

## Goal

For every transaction row in the dashboard, generate a structured explanation object that tells the user:
- what happened, in plain English
- what is known and unknown about the transaction
- what they should do (if anything)
- a confidence level and technical summary for advanced users

The expanded content is hidden by default and revealed via a native HTML `<details>`/`<summary>` element — no JavaScript required.

## Scope

- New `src/ai_accountant/explainer.py` module
- Minor addition to `src/ai_accountant/dashboard/views.py`
- Updated transactions table in the Jinja2 dashboard template
- New `tests/test_explainer.py`
- No changes to `report.py`, `tagger.py`, `dataframe.py`, `cache.py`, or the public `__init__.py` surface

## Out of Scope

- React / TypeScript frontend (project is Python/Flask/Jinja2)
- Pre-computing or caching explanation fields
- Exporting explanation data via CSV or API
- `confidenceExplanation` field (dropped from MVP)

---

## Data Model

```python
@dataclass(frozen=True)
class TransactionExplanation:
    event_title: str
    short_explanation: str
    review_label: str
    confidence_percent: int       # 0–100
    known_facts: list[str]
    unknown_facts: list[str]
    suggested_actions: list[str]
    expanded_explanation: str
    technical_summary: str
    tags: list[str]
```

### Input

`explain_row(row: pd.Series) -> TransactionExplanation`

Reads from these existing DataFrame columns (all produced by `tagger.py` or `parser.py`):

| Column | Type | Source |
|---|---|---|
| `tag_type` | str | tagger — values: `"Transfer"`, `"Swap"`, `"NFT Buy/Sell"`, `"Stake/Unstake"`, `"LP Deposit/Withdraw"`, `"Airdrop"`, `"Mint/Burn"`, `"Bridge"`, `"Perpetual Trade"`, `"Unknown"` |
| `tag_protocol` | str | tagger — e.g. `"Jupiter"`, `"Raydium"`, `"Unknown"` |
| `tag_assets` | str | tagger (display string, e.g. `"SOL → USDC"`) |
| `tag_amount_display` | str | tagger (formatted amounts) |
| `tag_confidence` | float 0–1 | tagger |
| `source` | str | parser / Helius — e.g. `"JUPITER"`, `"UNKNOWN"` |
| `status` | str | parser |
| `fee_sol` | Decimal | parser |
| `native_net_sol` | Decimal | parser — positive = SOL received, negative = SOL sent |
| `token_flow_details` | list[dict] | parser — each dict has `"net"` (Decimal), `"symbol"` (str) |
| `date` | datetime | parser |
| `signature` | str | parser |
| `description` | str | parser / Helius free-text |

---

## Classification Rules

### tag_type → base explanation

Direction for `"Transfer"` and `"NFT Buy/Sell"` is inferred from flow data:
- SOL direction: `native_net_sol > 0` = received, `< 0` = sent
- Token direction: `token_flow_details` net > 0 = received, < 0 = sent

| `tag_type` | Direction condition | `event_title` | Base `review_label` | Core `tags` |
|---|---|---|---|---|
| `Transfer` | `native_net_sol > 0` | Received SOL | No action needed | `incoming`, `sol` |
| `Transfer` | `native_net_sol < 0` | Sent SOL | No action needed | `outgoing`, `sol` |
| `Transfer` | token net > 0 | Received token | No action needed | `incoming`, `token` |
| `Transfer` | token net < 0 | Sent token | No action needed | `outgoing`, `token` |
| `Swap` | — | Swapped tokens | Tax-relevant review | `swap`, `tax_relevant` |
| `NFT Buy/Sell` | `native_net_sol < 0` | Bought NFT | Tax-relevant review | `nft`, `tax_relevant` |
| `NFT Buy/Sell` | `native_net_sol > 0` | Sold NFT | Tax-relevant review | `nft`, `tax_relevant` |
| `NFT Buy/Sell` | `native_net_sol == 0` | Received NFT | Review NFT source | `nft`, `incoming` |
| `Stake/Unstake` | `native_net_sol < 0` | Staked SOL | No action needed | `staking` |
| `Stake/Unstake` | `native_net_sol > 0` | Unstaked SOL | No action needed | `staking` |
| `Airdrop` | — | Received airdrop | Tax-relevant review | `airdrop`, `tax_relevant` |
| `LP Deposit/Withdraw` | — | LP interaction | Tax-relevant review | `lp`, `tax_relevant` |
| `Mint/Burn` | — | Token mint/burn | No action needed | `mint_burn` |
| `Bridge` | — | Bridge transfer | No action needed | `bridge` |
| `Perpetual Trade` | — | Perpetual trade | Tax-relevant review | `perp`, `tax_relevant` |
| `Unknown` / fallback | — | Unknown activity | Needs review | `unknown` |

### Override rules (applied in priority order after base mapping)

1. `status == "failed"` → `review_label = "Failed transaction"`, add tag `failed`
2. `tag_confidence < 0.7` → `review_label = "Needs review"`, add tag `low_confidence`
3. Incoming + `source == "UNKNOWN"` and `tag_protocol == "Unknown"` → `review_label = "Source unknown"`, add tags `source_unknown`, `needs_label`
4. Token in `token_flow_details` has no symbol or symbol is `"Token"` → add tag `unknown_token`
5. `tag_type == "Unknown"` with `tag_protocol == "Unknown"` → `review_label = "Unknown program"`, add tag `unknown_program`

`confidence_percent = round(tag_confidence * 100)`, clamped to [0, 100].

### Known facts

Always included if non-zero/non-null:
- Transaction status (succeeded / failed)
- Asset changes (from `tag_assets`)
- Network fee (from `fee_sol`)
- Program name, if known
- Counterparty address (shortened), if available in `description`

### Unknown facts

Included when the condition is true:
- Source unknown (incoming, `source == "UNKNOWN"` and `tag_protocol == "Unknown"`)
- Counterparty unknown (outgoing, no counterparty identifiable from `description`)
- Asset symbol or name not recognized
- Program not in known-program list
- Purpose of interaction unclear
- Cost basis missing (for swaps, NFT purchases/sales, staking rewards)
- User's tax country not set (for tax-relevant events)

### Suggested actions

At most 3, in order of relevance:
- "Label the source of this transfer." (source unknown)
- "Confirm whether this address belongs to you." (own-wallet uncertainty)
- "Review this unknown program interaction." (unknown program)
- "Add cost basis for this asset." (swap / NFT / staking reward)
- "Mark this transaction as reviewed." (low confidence or needs_review)
- "No action needed." only when no other action applies

### Technical summary

One compact sentence using shortened addresses (first 4 + last 4 chars):
> "Address Biw4…3xKm transferred 0.037675 SOL to 5ECZ…7qPt. Transaction succeeded."

### Expanded explanation

2–4 sentences of plain English. Does not repeat `short_explanation` verbatim. For tax-relevant events includes: "This may be relevant for tax or portfolio reporting depending on your country. This is not a legal or tax conclusion."

---

## Architecture

```
explainer.py          ← new, no dashboard/ imports
    explain_row(row) → TransactionExplanation
    _event_title(row) → str
    _review_label(row, base) → str
    _known_facts(row) → list[str]
    _unknown_facts(row) → list[str]
    _suggested_actions(row) → list[str]
    _expanded_explanation(row) → str
    _technical_summary(row) → str
    _tags(row, base_tags) → list[str]
    _shorten_address(addr) → str
    _format_sol(amount) → str

dashboard/views.py    ← minor addition
    tx_explanations = [explain_row(row) for _, row in page_slice.iterrows()]
    # added to returned context dict alongside tx_rows

dashboard template    ← transactions table redesigned
    columns: Date | Event | Change | Status | Review | Confidence
    <details><summary>…row…</summary><div>…expanded…</div></details>
```

### Dependency rules

- `explainer.py` imports: stdlib, `decimal`, `pandas` only. No `dashboard/` imports. No `report.py` imports. No `tagger.py` imports (reads only tag columns already on the DataFrame row).
- `dashboard/views.py` imports `explain_row` from `..explainer`.
- `explainer.py` is NOT exported from `__init__.py`.

---

## Template: Transaction Table Column Mapping

| Column header | Source |
|---|---|
| Date | `row["date"]` (existing) |
| Event | `exp.event_title` |
| Change | `tag_assets` / `native_net_sol` formatted |
| Status | `row["status"]` |
| Review | `exp.review_label` |
| Confidence | `exp.confidence_percent` % |

Expanded section (inside `<details>`):
1. `exp.short_explanation` (paragraph)
2. Known facts (unordered list)
3. Unknown facts (unordered list)
4. Suggested actions (unordered list)
5. `exp.expanded_explanation` (paragraph)
6. `exp.technical_summary` (small/code styled)

---

## Tests

File: `tests/test_explainer.py`

Seven cases, each building a minimal `pd.Series` with relevant `tag_*` and parser columns:

1. Incoming SOL, `tag_source="unknown"`, `tag_confidence=0.8` → `event_title="Received SOL"`, `review_label="Source unknown"`, tags include `source_unknown`
2. Outgoing SOL, known counterparty → `event_title="Sent SOL"`, `review_label="No action needed"`
3. Swap, two tokens → `event_title="Swapped tokens"`, `review_label="Tax-relevant review"`, tags include `tax_relevant`
4. Program interaction, unknown program → `review_label="Unknown program"`, tags include `unknown_program`
5. NFT received, unknown source → `event_title="Received NFT"`, `review_label="Review NFT source"`
6. Staking reward → `event_title="Received staking reward"`, `review_label="Tax-relevant review"`, tags include `staking`
7. Unknown type, `tag_confidence=0.3` → `event_title="Unknown activity"`, `review_label="Needs review"`, tags include `low_confidence`

All tests assert field types (str / int / list[str]) in addition to values.

---

## Language and Tone Rules

- Plain English. No blockchain jargon unless necessary.
- Never claim purchase, sale, income, airdrop, taxable event unless `tag_type` clearly supports it.
- For tax/legal topics: "may be relevant", "depending on your country", "this is not a legal or tax conclusion."
- `suggested_actions` contains at most 3 items. Never mix "No action needed" with other actions.
- `unknown_facts` never speculates — only states what is missing from the parsed data.
