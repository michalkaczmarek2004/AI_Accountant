# Transaction Tagging — Design Spec

**Date:** 2026-05-08  
**Status:** Approved  

## Goal

Convert raw Solana transactions into structured, human-readable labels for accounting and analytics. Each transaction receives a `TagResult` with type, protocol, assets, amounts, optional USD estimate, and a confidence score. Tags are persisted as core DataFrame columns so they are available in exports, reports, the dashboard, and future AI features.

---

## Scope

**In scope:**
- New core module `tagger.py` with `enrich(df) -> df`
- Parser extended to extract `program_ids` from `instructions[].programId`
- 7 new `DATAFRAME_COLUMNS`: `program_ids`, `tag_type`, `tag_protocol`, `tag_assets`, `tag_amount_display`, `tag_usd_estimate`, `tag_confidence`
- Dashboard transactions table updated with new columns
- `FilterSpec` extended with `tag_type` filter
- `SCHEMA_VERSION` bumped to 2

**Out of scope (future):**
- Live USD price feed (hook is designed in, not wired)
- NFT metadata resolution
- Cross-transaction cost-basis or P&L using tags

---

## New module: `tagger.py`

Location: `src/ai_accountant/tagger.py`

### Public interface

```python
@dataclass
class TagResult:
    tag_type: str           # "Swap", "Transfer", "NFT Buy/Sell", "Stake/Unstake",
                            # "LP Deposit/Withdraw", "Airdrop", "Mint/Burn",
                            # "Bridge", "Perpetual Trade", "Unknown"
    tag_protocol: str       # "Jupiter", "Raydium", "Unknown", etc.
    tag_assets: str         # "SOL → BONK", "USDC", "NFT", ""
    tag_amount_display: str # "0.5 SOL → 1,234,567 BONK", "0.5 SOL", ""
    tag_usd_estimate: str | None  # "~125 USD" or None
    tag_confidence: float   # 0.0–1.0

def enrich(
    df: pd.DataFrame,
    *,
    price_provider: Callable[[str], Decimal | None] | None = None,
) -> pd.DataFrame:
    """Return df with tag columns appended. No-op on empty DataFrame."""
```

`enrich()` is a pure function. It appends tag columns without modifying the input DataFrame. The `price_provider` kwarg is wired in but always `None` until a price feed is integrated. When `price_provider` is `None`, `tag_usd_estimate` is always `None`.

### Internal function

```python
def _tag_row(row: dict[str, Any]) -> TagResult: ...
```

Not exported. Called once per row inside `enrich()`.

---

## Tagging logic — three layers

### Layer 1: Helius type/source mapping

Uses `transaction_type` and `source` columns (already parsed by `TransactionParser`).

**Type mapping:**

| Helius `transaction_type` | `tag_type` |
|---|---|
| `SWAP` | Swap |
| `TRANSFER`, `SEND`, `RECEIVE` | Transfer |
| `NFT_SALE`, `NFT_LISTING`, `NFT_BID`, `NFT_BID_CANCELLED`, `NFT_CANCEL_LISTING` | NFT Buy/Sell |
| `STAKE_SOL`, `UNSTAKE_SOL`, `STAKE_TOKEN` | Stake/Unstake |
| `ADD_LIQUIDITY`, `REMOVE_LIQUIDITY` | LP Deposit/Withdraw |
| `AIRDROP` | Airdrop |
| `BURN`, `TOKEN_MINT` | Mint/Burn |
| `BRIDGE` | Bridge |
| `PERPETUAL_TRADE`, `PERP_OPEN`, `PERP_CLOSE` | Perpetual Trade |
| anything else / `null` / `UNKNOWN` | → Layer 2 |

**Source mapping:**

| Helius `source` | `tag_protocol` |
|---|---|
| `JUPITER` | Jupiter |
| `RAYDIUM` | Raydium |
| `METEORA` | Meteora |
| `PUMP_FUN` | Pump.fun |
| `TENSOR` | Tensor |
| `DRIFT` | Drift |
| `MARGIN_FI` | MarginFi |
| `MARINADE` | Marinade |
| `SANCTUM` | Sanctum |
| `UNKNOWN` / `null` / unrecognised | → Layer 2 for protocol |

**Confidence:**
- Both type and source resolve: `0.95`
- Type resolves, source does not: `0.80`
- Type does not resolve: → Layer 2

### Layer 2: programId heuristics

Applied when Layer 1 yields Unknown type or Unknown protocol. Checks `program_ids` list against a static registry:

```python
KNOWN_PROGRAMS: dict[str, tuple[str, str]] = {
    # (tag_type, tag_protocol)
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": ("Swap", "Jupiter"),
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB":  ("Swap", "Jupiter"),
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": ("Swap", "Raydium"),
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1": ("Swap", "Raydium"),
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EkAW7vAV": ("LP Deposit/Withdraw", "Meteora"),
    "LBUZKhRxPF3XUpBCjp4YzTKgLLjgzAkT3S3jT7hCwJ3":  ("LP Deposit/Withdraw", "Meteora"),
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P":  ("Swap", "Pump.fun"),
    "TCMPhJdwDryooaGtiocG1u3xcYbRpiJzb283XoqBBnN":  ("NFT Buy/Sell", "Tensor"),
    "dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH":  ("Perpetual Trade", "Drift"),
    "MFv2hWf31Z9kbCa1snEPdcgKDBQwGHaRN1eJZ7QC2WL":  ("Transfer", "MarginFi"),
    "MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD":  ("Stake/Unstake", "Marinade"),
    "stkJF5aBBKFzHFHQoFeMHSvBPBbZu43k7hVz5cXnFqT":  ("Stake/Unstake", "Sanctum"),
}
```

First match in `program_ids` order wins. Confidence: `0.70`.

If Layer 1 resolved the type but not the protocol, Layer 2 supplies the protocol only (type is kept from Layer 1, confidence stays at `0.80`).

### Layer 3: flow heuristics

Applied only when both Layers 1 and 2 yield Unknown type. Rules evaluated in order:

| Condition | `tag_type` | Confidence |
|---|---|---|
| Token flow out + SOL/token flow in (swap pattern) | Swap | 0.50 |
| Single asset in/out, single counterparty, no swap pattern | Transfer | 0.55 |
| Token in, no SOL out, no known counterparty | Airdrop | 0.45 |
| None of the above | Unknown | 0.10 |

Unknown rows: `tag_assets = ""`, `tag_amount_display = ""`. The raw `program_ids` list is preserved in the DataFrame column for display.

---

## Assets and amount display

Built inside `_tag_row()` from `net_flow` (dict keyed by `"SOL"` or full mint) and `token_flow_details` (list of flow dicts with `symbol`, `net`, `in`, `out`).

**Swap:** Assets with negative net → left side; positive net → right side.
- `tag_assets`: `"SOL → BONK"`
- `tag_amount_display`: `"0.5 SOL → 1,234,567 BONK"`

**Transfer:** Dominant single moving asset.
- `tag_assets`: `"SOL"`
- `tag_amount_display`: `"0.5 SOL"`

**NFT Buy/Sell:** `"NFT"` (token symbol if resolvable from flow details).
- `tag_amount_display`: SOL paid/received.

**Stake/Unstake, LP, Airdrop, Mint/Burn, Bridge, Perp:** Best-effort from flows; falls back to `net_flow_summary` already computed by the parser.

**Unknown:** `tag_assets = ""`, `tag_amount_display = ""`.

---

## Parser extension

`TransactionParser.parse()` gains one new output field:

```python
"program_ids": list(dict.fromkeys(
    str(ix.get("programId"))
    for ix in (transaction.get("instructions") or [])
    if ix.get("programId")
)),
```

- `dict.fromkeys` preserves insertion order while deduplicating.
- Empty list `[]` when `instructions` is absent (older Helius responses).
- No other changes to parsing logic.

---

## DATAFRAME_COLUMNS additions

Appended after existing columns in this order:

```python
"program_ids",        # list[str] — extracted by parser
"tag_type",           # str
"tag_protocol",       # str
"tag_assets",         # str
"tag_amount_display", # str
"tag_usd_estimate",   # str | None
"tag_confidence",     # float
```

`to_dataframe()` in `dataframe.py` calls `enrich()` after building the DataFrame. The call is unconditional — all DataFrames produced by this package include tag columns.

---

## Cache schema version

`SCHEMA_VERSION` in `cache.py` bumps from `1` → `2`. Existing cached pickles with schema version 1 return `None` from `cache.read()` (existing behaviour on mismatch). Users see a stale-cache prompt and must re-fetch.

---

## Dashboard integration

### `report.py` — `_transaction_rows()`

Adds to each row dict:

```python
"tag_type":           str(row.get("tag_type") or "Unknown"),
"tag_protocol":       str(row.get("tag_protocol") or "Unknown"),
"tag_assets":         str(row.get("tag_assets") or ""),
"tag_amount_display": str(row.get("tag_amount_display") or ""),
"tag_usd_estimate":   row.get("tag_usd_estimate") or None,
"tag_confidence":     float(row.get("tag_confidence") or 0.0),
```

### `wallet.html.j2` — transactions table

New column layout: **Date | Type | Assets | Amount | Fee | Status | Confidence | Tx**

- **Type cell**: `tag_type` bold, `tag_protocol` as muted subtext.
- **Assets cell**: `tag_assets`. For Unknown rows, first 2 `program_ids` shown as muted truncated text.
- **Amount cell**: `tag_amount_display` primary; `tag_usd_estimate` as muted subtext when not None.
- **Confidence cell**: rendered as a percentage badge (e.g. `92%`), colour-coded: ≥0.80 green, 0.50–0.79 yellow, <0.50 red/muted.

The old `Net flow` column is removed from the main table (it remains accessible on the transaction detail page).

### `filters.py` — `FilterSpec`

Gains `tag_type: str | None = None`. Parsed from querystring key `tag`. Applied as a case-insensitive equality filter on the `tag_type` column.

### `views.py` — `_filter_options()`

Extended to include `tag_types: list[str]` — sorted unique values of `tag_type` across all rows in the full (unfiltered) DataFrame. Added alongside the existing `types` and `sources` keys.

### `wallet.html.j2` — filter bar

Gains a `Tag` dropdown (alongside existing `Type` filter), populated from `filter_options["tag_types"]`.

---

## Testing

| File | Coverage |
|---|---|
| `tests/test_tagger.py` | New. `_tag_row` for all 10 types; each confidence tier; assets string for swap/transfer/airdrop/unknown; empty DataFrame; missing columns; `program_ids` fallback |
| `tests/test_parser.py` | Extended. `program_ids` extraction: present, absent, deduplication |
| `tests/test_dataframe.py` | Extended. `DATAFRAME_COLUMNS` includes 7 new columns; `to_dataframe()` returns enriched rows |
| `tests/dashboard/test_views.py` | Extended. Tag fields present in `transactions` rows; `tag_type` filter in `_filter_options` |
| `tests/dashboard/test_routes.py` | Extended. `tag` querystring parameter round-trips correctly |
| `tests/dashboard/test_cache.py` | Extended. `SCHEMA_VERSION == 2`; schema-1 pickle returns `None` |
| `tests/dashboard/test_filters.py` | Extended. `tag_type` parses from querystring; filters DataFrame correctly |

No changes to: `test_client.py`, `test_transport.py`, `test_addresses.py`, `test_report.py`, `test_compat_shim.py`.

---

## Public API impact

`tagger.py` exports are added to `__init__.py`: `TagResult`, `enrich`. `DATAFRAME_COLUMNS` grows by 7 entries — consumers who build DataFrames manually (e.g. from raw dicts) must add the new columns or use `to_dataframe()`.
