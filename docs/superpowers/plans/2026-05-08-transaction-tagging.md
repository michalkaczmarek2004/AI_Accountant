# Transaction Tagging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic transaction tagging to core DataFrame — classify each Solana transaction by type, protocol, assets, and confidence score, persisted in cache and visible in the dashboard.

**Architecture:** New `tagger.py` module with a pure `enrich(df) -> df` function applies a three-layer classifier (Helius type/source → programId lookup → flow heuristics) to each row and appends six tag columns. Parser gains `program_ids` extraction. `SCHEMA_VERSION` bumps to 2. Dashboard filter and transactions table are updated.

**Tech Stack:** Python 3.10+, pandas, stdlib dataclasses. No new dependencies.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `src/ai_accountant/parser.py` | Extract `program_ids` from `instructions[].programId` |
| Modify | `src/ai_accountant/dataframe.py` | Add 7 new columns to `DATAFRAME_COLUMNS`; call `enrich()` |
| Modify | `src/ai_accountant/dashboard/cache.py` | Bump `SCHEMA_VERSION` 1 → 2 |
| Create | `src/ai_accountant/tagger.py` | `TagResult`, `_tag_row`, `enrich` |
| Modify | `src/ai_accountant/__init__.py` | Export `TagResult`, `enrich` |
| Modify | `src/ai_accountant/dashboard/filters.py` | Add `tag_type` field; `tag` querystring key |
| Modify | `src/ai_accountant/report.py` | Add tag fields to `_transaction_rows()` |
| Modify | `src/ai_accountant/dashboard/views.py` | Add `tag_types` to `_filter_options()` |
| Modify | `src/ai_accountant/dashboard/templates/wallet.html.j2` | New table columns; Tag filter dropdown |
| Extend | `tests/test_parser.py` | `program_ids` extraction |
| Extend | `tests/test_dataframe.py` | New columns in schema |
| Create | `tests/test_tagger.py` | All classification cases, assets display, `enrich()` |
| Extend | `tests/dashboard/test_cache.py` | `SCHEMA_VERSION == 2` assertion |
| Extend | `tests/dashboard/test_filters.py` | `tag_type` parse + apply |
| Extend | `tests/dashboard/test_views.py` | Tag fields in `transactions` rows; `tag_types` in filter options |
| Extend | `tests/dashboard/test_routes.py` | Tag filter querystring round-trip |

---

## Task 1: Parser — extract `program_ids`

**Files:**
- Modify: `src/ai_accountant/parser.py`
- Extend: `tests/test_parser.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_parser.py`:

```python
WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"

def _minimal_tx(**overrides):
    base = {
        "signature": "sig-test",
        "slot": 1,
        "timestamp": 1_700_000_000,
        "type": "TRANSFER",
        "source": "SYSTEM",
        "fee": 5_000,
        "feePayer": WALLET,
        "nativeTransfers": [],
        "tokenTransfers": [],
    }
    base.update(overrides)
    return base


class ProgramIdsParserTests(unittest.TestCase):
    def test_extracts_program_ids_in_order(self) -> None:
        tx = _minimal_tx(instructions=[
            {"programId": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"},
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
        ])
        row = TransactionParser(WALLET).parse(tx)
        self.assertEqual(row["program_ids"], [
            "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        ])

    def test_deduplicates_program_ids_preserving_order(self) -> None:
        tx = _minimal_tx(instructions=[
            {"programId": "AAA111"},
            {"programId": "BBB222"},
            {"programId": "AAA111"},
        ])
        row = TransactionParser(WALLET).parse(tx)
        self.assertEqual(row["program_ids"], ["AAA111", "BBB222"])

    def test_program_ids_empty_when_instructions_absent(self) -> None:
        tx = _minimal_tx()  # no "instructions" key
        row = TransactionParser(WALLET).parse(tx)
        self.assertEqual(row["program_ids"], [])

    def test_program_ids_empty_when_instructions_empty(self) -> None:
        tx = _minimal_tx(instructions=[])
        row = TransactionParser(WALLET).parse(tx)
        self.assertEqual(row["program_ids"], [])

    def test_instructions_without_program_id_are_skipped(self) -> None:
        tx = _minimal_tx(instructions=[{"data": "abc"}, {"programId": "XYZ999"}])
        row = TransactionParser(WALLET).parse(tx)
        self.assertEqual(row["program_ids"], ["XYZ999"])
```

- [ ] **Step 2: Run tests — expect failure**

```powershell
pytest tests/test_parser.py::ProgramIdsParserTests -v
```
Expected: `FAILED` — `KeyError: 'program_ids'`

- [ ] **Step 3: Add `program_ids` extraction to `parser.py`**

In `TransactionParser.parse()`, add the following key to the returned dict (after `"transaction_error": raw_error`):

```python
"program_ids": list(dict.fromkeys(
    str(ix.get("programId"))
    for ix in (transaction.get("instructions") or [])
    if ix.get("programId")
)),
```

- [ ] **Step 4: Run tests — expect pass**

```powershell
pytest tests/test_parser.py::ProgramIdsParserTests -v
```
Expected: `5 passed`

- [ ] **Step 5: Full suite green**

```powershell
pytest tests/test_parser.py -v
```
Expected: all passing.

- [ ] **Step 6: Commit**

```powershell
git add src/ai_accountant/parser.py tests/test_parser.py
git commit -m "feat(parser): extract program_ids from instructions"
```

---

## Task 2: `DATAFRAME_COLUMNS` additions + `SCHEMA_VERSION` bump

**Files:**
- Modify: `src/ai_accountant/dataframe.py`
- Modify: `src/ai_accountant/dashboard/cache.py`
- Extend: `tests/test_dataframe.py`
- Extend: `tests/dashboard/test_cache.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_dataframe.py`:

```python
class DataFrameNewColumnsTests(unittest.TestCase):
    def test_new_columns_present_in_dataframe_columns(self) -> None:
        for col in (
            "program_ids", "tag_type", "tag_protocol", "tag_assets",
            "tag_amount_display", "tag_usd_estimate", "tag_confidence",
        ):
            self.assertIn(col, DATAFRAME_COLUMNS, f"missing: {col}")

    def test_new_columns_after_existing_columns(self) -> None:
        idx_signature = DATAFRAME_COLUMNS.index("signature")
        idx_tag = DATAFRAME_COLUMNS.index("tag_type")
        self.assertGreater(idx_tag, idx_signature)
```

Append to `tests/dashboard/test_cache.py`:

```python
class CacheSchemaVersionTests(unittest.TestCase):
    def test_schema_version_is_two(self) -> None:
        self.assertEqual(cache_mod.SCHEMA_VERSION, 2)
```

- [ ] **Step 2: Run tests — expect failure**

```powershell
pytest tests/test_dataframe.py::DataFrameNewColumnsTests tests/dashboard/test_cache.py::CacheSchemaVersionTests -v
```
Expected: `FAILED`

- [ ] **Step 3: Update `DATAFRAME_COLUMNS` in `dataframe.py`**

Append these 7 entries to the end of the `DATAFRAME_COLUMNS` list:

```python
    "program_ids",
    "tag_type",
    "tag_protocol",
    "tag_assets",
    "tag_amount_display",
    "tag_usd_estimate",
    "tag_confidence",
```

- [ ] **Step 4: Bump `SCHEMA_VERSION` in `cache.py`**

Change line 18 of `src/ai_accountant/dashboard/cache.py`:

```python
SCHEMA_VERSION = 2
```

- [ ] **Step 5: Run tests — expect pass**

```powershell
pytest tests/test_dataframe.py tests/dashboard/test_cache.py -v
```
Expected: all passing.

- [ ] **Step 6: Commit**

```powershell
git add src/ai_accountant/dataframe.py src/ai_accountant/dashboard/cache.py tests/test_dataframe.py tests/dashboard/test_cache.py
git commit -m "feat(schema): add tag columns to DATAFRAME_COLUMNS, bump SCHEMA_VERSION to 2"
```

---

## Task 3: Create `tagger.py` — `TagResult` + full `_tag_row`

**Files:**
- Create: `src/ai_accountant/tagger.py`
- Create: `tests/test_tagger.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_tagger.py`:

```python
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant.tagger import TagResult, _tag_row

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW"
JUP_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
RAYDIUM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"


def _row(**kwargs):
    base = {
        "transaction_type": None,
        "source": None,
        "program_ids": [],
        "net_flow": {},
        "token_flow_details": [],
        "movements_in": [],
        "movements_out": [],
        "net_flow_summary": "No net movement",
    }
    base.update(kwargs)
    return base


class Layer1TypeMappingTests(unittest.TestCase):
    def test_swap_jupiter(self) -> None:
        r = _tag_row(_row(transaction_type="SWAP", source="JUPITER"))
        self.assertEqual(r.tag_type, "Swap")
        self.assertEqual(r.tag_protocol, "Jupiter")
        self.assertAlmostEqual(r.tag_confidence, 0.95)

    def test_transfer_system(self) -> None:
        r = _tag_row(_row(transaction_type="TRANSFER", source="SYSTEM_PROGRAM"))
        self.assertEqual(r.tag_type, "Transfer")
        self.assertEqual(r.tag_protocol, "Unknown")
        self.assertAlmostEqual(r.tag_confidence, 0.80)

    def test_nft_sale_tensor(self) -> None:
        r = _tag_row(_row(transaction_type="NFT_SALE", source="TENSOR"))
        self.assertEqual(r.tag_type, "NFT Buy/Sell")
        self.assertEqual(r.tag_protocol, "Tensor")
        self.assertAlmostEqual(r.tag_confidence, 0.95)

    def test_stake_sol_marinade(self) -> None:
        r = _tag_row(_row(transaction_type="STAKE_SOL", source="MARINADE"))
        self.assertEqual(r.tag_type, "Stake/Unstake")
        self.assertEqual(r.tag_protocol, "Marinade")

    def test_add_liquidity_meteora(self) -> None:
        r = _tag_row(_row(transaction_type="ADD_LIQUIDITY", source="METEORA"))
        self.assertEqual(r.tag_type, "LP Deposit/Withdraw")
        self.assertEqual(r.tag_protocol, "Meteora")

    def test_airdrop(self) -> None:
        r = _tag_row(_row(transaction_type="AIRDROP", source=None))
        self.assertEqual(r.tag_type, "Airdrop")

    def test_burn(self) -> None:
        r = _tag_row(_row(transaction_type="BURN", source=None))
        self.assertEqual(r.tag_type, "Mint/Burn")

    def test_bridge(self) -> None:
        r = _tag_row(_row(transaction_type="BRIDGE", source=None))
        self.assertEqual(r.tag_type, "Bridge")

    def test_perpetual_trade_drift(self) -> None:
        r = _tag_row(_row(transaction_type="PERPETUAL_TRADE", source="DRIFT"))
        self.assertEqual(r.tag_type, "Perpetual Trade")
        self.assertEqual(r.tag_protocol, "Drift")

    def test_type_resolves_protocol_from_layer2_when_source_unknown(self) -> None:
        r = _tag_row(_row(
            transaction_type="SWAP",
            source="UNKNOWN",
            program_ids=[JUP_PROGRAM],
        ))
        self.assertEqual(r.tag_type, "Swap")
        self.assertEqual(r.tag_protocol, "Jupiter")
        self.assertAlmostEqual(r.tag_confidence, 0.80)


class Layer2ProgramIdTests(unittest.TestCase):
    def test_jupiter_program_id(self) -> None:
        r = _tag_row(_row(program_ids=[JUP_PROGRAM]))
        self.assertEqual(r.tag_type, "Swap")
        self.assertEqual(r.tag_protocol, "Jupiter")
        self.assertAlmostEqual(r.tag_confidence, 0.70)

    def test_raydium_program_id(self) -> None:
        r = _tag_row(_row(program_ids=[RAYDIUM_PROGRAM]))
        self.assertEqual(r.tag_type, "Swap")
        self.assertEqual(r.tag_protocol, "Raydium")

    def test_first_match_wins(self) -> None:
        r = _tag_row(_row(program_ids=[JUP_PROGRAM, RAYDIUM_PROGRAM]))
        self.assertEqual(r.tag_protocol, "Jupiter")

    def test_unknown_program_id_falls_through(self) -> None:
        r = _tag_row(_row(program_ids=["AAABBBCCC111"]))
        self.assertEqual(r.tag_type, "Unknown")


class Layer3FlowHeuristicsTests(unittest.TestCase):
    def test_swap_by_flow(self) -> None:
        r = _tag_row(_row(
            net_flow={"SOL": Decimal("-0.5"), USDC_MINT: Decimal("100")},
            token_flow_details=[{
                "mint": USDC_MINT, "symbol": "USDC",
                "net": Decimal("100"), "in": Decimal("100"), "out": Decimal("0"),
            }],
        ))
        self.assertEqual(r.tag_type, "Swap")
        self.assertAlmostEqual(r.tag_confidence, 0.50)

    def test_transfer_by_flow(self) -> None:
        r = _tag_row(_row(
            net_flow={"SOL": Decimal("-0.5")},
            token_flow_details=[],
            movements_out=[{"counterparty": "ReceiverXXX", "asset_type": "native"}],
        ))
        self.assertEqual(r.tag_type, "Transfer")
        self.assertAlmostEqual(r.tag_confidence, 0.55)

    def test_airdrop_by_flow(self) -> None:
        r = _tag_row(_row(
            net_flow={USDC_MINT: Decimal("50")},
            token_flow_details=[{
                "mint": USDC_MINT, "symbol": "USDC",
                "net": Decimal("50"), "in": Decimal("50"), "out": Decimal("0"),
            }],
            movements_in=[{"counterparty": None, "asset_type": "token"}],
        ))
        self.assertEqual(r.tag_type, "Airdrop")
        self.assertAlmostEqual(r.tag_confidence, 0.45)

    def test_unknown_fallback(self) -> None:
        r = _tag_row(_row())
        self.assertEqual(r.tag_type, "Unknown")
        self.assertAlmostEqual(r.tag_confidence, 0.10)


class AssetsDisplayTests(unittest.TestCase):
    def test_swap_sol_to_usdc(self) -> None:
        r = _tag_row(_row(
            transaction_type="SWAP",
            source="JUPITER",
            net_flow={"SOL": Decimal("-0.5"), USDC_MINT: Decimal("100")},
            token_flow_details=[{
                "mint": USDC_MINT, "symbol": "USDC",
                "net": Decimal("100"), "in": Decimal("100"), "out": Decimal("0"),
            }],
        ))
        self.assertEqual(r.tag_assets, "SOL → USDC")
        self.assertIn("0.5 SOL", r.tag_amount_display)
        self.assertIn("100 USDC", r.tag_amount_display)
        self.assertIn("→", r.tag_amount_display)

    def test_swap_usdc_to_bonk(self) -> None:
        r = _tag_row(_row(
            transaction_type="SWAP",
            source="RAYDIUM",
            net_flow={USDC_MINT: Decimal("-50"), BONK_MINT: Decimal("1234567")},
            token_flow_details=[
                {"mint": USDC_MINT, "symbol": "USDC",
                 "net": Decimal("-50"), "in": Decimal("0"), "out": Decimal("50")},
                {"mint": BONK_MINT, "symbol": "BONK",
                 "net": Decimal("1234567"), "in": Decimal("1234567"), "out": Decimal("0")},
            ],
        ))
        self.assertEqual(r.tag_assets, "USDC → BONK")
        self.assertIn("50 USDC", r.tag_amount_display)
        self.assertIn("1,234,567 BONK", r.tag_amount_display)

    def test_transfer_assets(self) -> None:
        r = _tag_row(_row(
            transaction_type="TRANSFER",
            source="SYSTEM_PROGRAM",
            net_flow={"SOL": Decimal("-0.5")},
            token_flow_details=[],
        ))
        self.assertEqual(r.tag_assets, "SOL")
        self.assertIn("0.5 SOL", r.tag_amount_display)

    def test_unknown_has_empty_assets(self) -> None:
        r = _tag_row(_row())
        self.assertEqual(r.tag_assets, "")
        self.assertEqual(r.tag_amount_display, "")

    def test_usd_estimate_none_without_price_provider(self) -> None:
        r = _tag_row(_row(transaction_type="SWAP", source="JUPITER"))
        self.assertIsNone(r.tag_usd_estimate)


class TagResultTypeTests(unittest.TestCase):
    def test_returns_tag_result_dataclass(self) -> None:
        r = _tag_row(_row(transaction_type="SWAP", source="JUPITER"))
        self.assertIsInstance(r, TagResult)
        self.assertIsInstance(r.tag_type, str)
        self.assertIsInstance(r.tag_protocol, str)
        self.assertIsInstance(r.tag_confidence, float)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — expect ImportError**

```powershell
pytest tests/test_tagger.py -v
```
Expected: `ERROR` — `ModuleNotFoundError: No module named 'ai_accountant.tagger'`

- [ ] **Step 3: Create `src/ai_accountant/tagger.py`**

```python
"""Classify parsed Solana transactions into human-readable labels."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pandas as pd

_HELIUS_TYPE_MAP: dict[str, str] = {
    "SWAP": "Swap",
    "TRANSFER": "Transfer",
    "SEND": "Transfer",
    "RECEIVE": "Transfer",
    "NFT_SALE": "NFT Buy/Sell",
    "NFT_LISTING": "NFT Buy/Sell",
    "NFT_BID": "NFT Buy/Sell",
    "NFT_BID_CANCELLED": "NFT Buy/Sell",
    "NFT_CANCEL_LISTING": "NFT Buy/Sell",
    "STAKE_SOL": "Stake/Unstake",
    "UNSTAKE_SOL": "Stake/Unstake",
    "STAKE_TOKEN": "Stake/Unstake",
    "ADD_LIQUIDITY": "LP Deposit/Withdraw",
    "REMOVE_LIQUIDITY": "LP Deposit/Withdraw",
    "AIRDROP": "Airdrop",
    "BURN": "Mint/Burn",
    "TOKEN_MINT": "Mint/Burn",
    "BRIDGE": "Bridge",
    "PERPETUAL_TRADE": "Perpetual Trade",
    "PERP_OPEN": "Perpetual Trade",
    "PERP_CLOSE": "Perpetual Trade",
}

_HELIUS_SOURCE_MAP: dict[str, str] = {
    "JUPITER": "Jupiter",
    "RAYDIUM": "Raydium",
    "METEORA": "Meteora",
    "PUMP_FUN": "Pump.fun",
    "TENSOR": "Tensor",
    "DRIFT": "Drift",
    "MARGIN_FI": "MarginFi",
    "MARINADE": "Marinade",
    "SANCTUM": "Sanctum",
}

KNOWN_PROGRAMS: dict[str, tuple[str, str]] = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": ("Swap", "Jupiter"),
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB": ("Swap", "Jupiter"),
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": ("Swap", "Raydium"),
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1": ("Swap", "Raydium"),
    "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EkAW7vAV": ("LP Deposit/Withdraw", "Meteora"),
    "LBUZKhRxPF3XUpBCjp4YzTKgLLjgzAkT3S3jT7hCwJ3": ("LP Deposit/Withdraw", "Meteora"),
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": ("Swap", "Pump.fun"),
    "TCMPhJdwDryooaGtiocG1u3xcYbRpiJzb283XoqBBnN": ("NFT Buy/Sell", "Tensor"),
    "dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH": ("Perpetual Trade", "Drift"),
    "MFv2hWf31Z9kbCa1snEPdcgKDBQwGHaRN1eJZ7QC2WL": ("Transfer", "MarginFi"),
    "MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD": ("Stake/Unstake", "Marinade"),
    "stkJF5aBBKFzHFHQoFeMHSvBPBbZu43k7hVz5cXnFqT": ("Stake/Unstake", "Sanctum"),
}


@dataclass
class TagResult:
    tag_type: str
    tag_protocol: str
    tag_assets: str
    tag_amount_display: str
    tag_usd_estimate: str | None
    tag_confidence: float


def _nan_safe(v: Any, default: Any) -> Any:
    if v is None:
        return default
    if isinstance(v, float) and math.isnan(v):
        return default
    return v


def _fmt_amount(symbol: str, amount: Decimal) -> str:
    normalized = amount.normalize()
    rendered = format(normalized, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    parts = rendered.split(".")
    try:
        int_part = f"{int(parts[0]):,}"
    except ValueError:
        int_part = parts[0]
    rendered = f"{int_part}.{parts[1]}" if len(parts) > 1 else int_part
    return f"{rendered} {symbol}"


def _build_assets(
    tag_type: str,
    net_flow: dict,
    token_flow_details: list,
    net_flow_summary: str,
) -> tuple[str, str]:
    if tag_type == "Swap":
        out_parts: list[tuple[str, Decimal]] = []
        in_parts: list[tuple[str, Decimal]] = []
        sol_net = net_flow.get("SOL")
        if sol_net is not None:
            sol_dec = Decimal(str(sol_net))
            if sol_dec < 0:
                out_parts.append(("SOL", abs(sol_dec)))
            elif sol_dec > 0:
                in_parts.append(("SOL", sol_dec))
        for flow in token_flow_details:
            if not isinstance(flow, dict):
                continue
            net = Decimal(str(flow.get("net", 0)))
            sym = str(flow.get("symbol") or "Token")
            if net < 0:
                out_parts.append((sym, abs(net)))
            elif net > 0:
                in_parts.append((sym, net))
        if not out_parts or not in_parts:
            return "", net_flow_summary
        assets_out = " + ".join(s for s, _ in out_parts)
        assets_in = " + ".join(s for s, _ in in_parts)
        amt_out = " + ".join(_fmt_amount(s, a) for s, a in out_parts)
        amt_in = " + ".join(_fmt_amount(s, a) for s, a in in_parts)
        return f"{assets_out} → {assets_in}", f"{amt_out} → {amt_in}"

    if tag_type == "Transfer":
        candidates: list[tuple[str, Decimal]] = []
        sol_net = net_flow.get("SOL")
        if sol_net is not None:
            sol_dec = Decimal(str(sol_net))
            if sol_dec != 0:
                candidates.append(("SOL", abs(sol_dec)))
        for flow in token_flow_details:
            if not isinstance(flow, dict):
                continue
            net = Decimal(str(flow.get("net", 0)))
            sym = str(flow.get("symbol") or "Token")
            if net != 0:
                candidates.append((sym, abs(net)))
        if not candidates:
            return "", net_flow_summary
        sym, amt = candidates[0]
        return sym, _fmt_amount(sym, amt)

    if tag_type == "NFT Buy/Sell":
        nft_sym = "NFT"
        for flow in token_flow_details:
            if isinstance(flow, dict) and flow.get("symbol"):
                nft_sym = str(flow["symbol"])
                break
        sol_net = net_flow.get("SOL")
        if sol_net is not None:
            return nft_sym, _fmt_amount("SOL", abs(Decimal(str(sol_net))))
        return nft_sym, nft_sym

    return "", net_flow_summary


def _layer2_lookup(program_ids: list) -> tuple[str | None, str | None]:
    for pid in program_ids:
        match = KNOWN_PROGRAMS.get(str(pid))
        if match:
            return match[0], match[1]
    return None, None


def _layer3_heuristic(
    net_flow: dict,
    token_flow_details: list,
    movements_in: list,
    movements_out: list,
) -> tuple[str, float]:
    has_token_out = any(
        Decimal(str(f.get("net", 0))) < 0
        for f in token_flow_details
        if isinstance(f, dict)
    )
    has_token_in = any(
        Decimal(str(f.get("net", 0))) > 0
        for f in token_flow_details
        if isinstance(f, dict)
    )
    sol_net = Decimal(str(net_flow.get("SOL", 0)))

    if (has_token_out and (has_token_in or sol_net > 0)) or (
        has_token_in and sol_net < 0
    ):
        return "Swap", 0.50

    all_movements = list(movements_in) + list(movements_out)
    counterparties = {
        str(m.get("counterparty"))
        for m in all_movements
        if isinstance(m, dict) and m.get("counterparty")
    }
    nonzero_assets = sum(
        1 for v in net_flow.values() if Decimal(str(v)) != 0
    )
    if nonzero_assets <= 1 and len(counterparties) <= 1 and not (
        has_token_out and has_token_in
    ):
        return "Transfer", 0.55

    if has_token_in and sol_net >= 0 and not has_token_out and not counterparties:
        return "Airdrop", 0.45

    return "Unknown", 0.10


def _tag_row(row: dict[str, Any]) -> TagResult:
    tx_type = _nan_safe(row.get("transaction_type"), None)
    source = _nan_safe(row.get("source"), None)
    program_ids = _nan_safe(row.get("program_ids"), [])
    net_flow = _nan_safe(row.get("net_flow"), {})
    token_flow_details = _nan_safe(row.get("token_flow_details"), [])
    movements_in = _nan_safe(row.get("movements_in"), [])
    movements_out = _nan_safe(row.get("movements_out"), [])
    net_flow_summary = _nan_safe(row.get("net_flow_summary"), "") or ""

    if not isinstance(program_ids, list):
        program_ids = []
    if not isinstance(net_flow, dict):
        net_flow = {}
    if not isinstance(token_flow_details, list):
        token_flow_details = []
    if not isinstance(movements_in, list):
        movements_in = []
    if not isinstance(movements_out, list):
        movements_out = []

    l1_type = _HELIUS_TYPE_MAP.get((tx_type or "").upper())
    l1_protocol = _HELIUS_SOURCE_MAP.get((source or "").upper())

    if l1_type:
        tag_type = l1_type
        if l1_protocol:
            tag_protocol, confidence = l1_protocol, 0.95
        else:
            _, l2_protocol = _layer2_lookup(program_ids)
            tag_protocol = l2_protocol or "Unknown"
            confidence = 0.80
    else:
        l2_type, l2_protocol = _layer2_lookup(program_ids)
        if l2_type:
            tag_type = l2_type
            tag_protocol = l1_protocol or l2_protocol or "Unknown"
            confidence = 0.70
        else:
            tag_type, confidence = _layer3_heuristic(
                net_flow, token_flow_details, movements_in, movements_out
            )
            tag_protocol = l1_protocol or "Unknown"

    tag_assets, tag_amount_display = _build_assets(
        tag_type, net_flow, token_flow_details, net_flow_summary
    )

    return TagResult(
        tag_type=tag_type,
        tag_protocol=tag_protocol,
        tag_assets=tag_assets,
        tag_amount_display=tag_amount_display,
        tag_usd_estimate=None,
        tag_confidence=confidence,
    )


def enrich(
    df: pd.DataFrame,
    *,
    price_provider: Callable[[str], Decimal | None] | None = None,
) -> pd.DataFrame:
    """Return df with tag columns appended. Input DataFrame is not modified."""
    tag_cols = [
        "tag_type", "tag_protocol", "tag_assets",
        "tag_amount_display", "tag_usd_estimate", "tag_confidence",
    ]
    out = df.copy()
    if df.empty:
        for c in tag_cols:
            if c not in out.columns:
                out[c] = pd.Series(dtype=object)
        return out
    results = [_tag_row(row) for row in df.to_dict(orient="records")]
    out["tag_type"] = [r.tag_type for r in results]
    out["tag_protocol"] = [r.tag_protocol for r in results]
    out["tag_assets"] = [r.tag_assets for r in results]
    out["tag_amount_display"] = [r.tag_amount_display for r in results]
    out["tag_usd_estimate"] = [r.tag_usd_estimate for r in results]
    out["tag_confidence"] = [r.tag_confidence for r in results]
    return out


__all__ = ["TagResult", "enrich"]
```

- [ ] **Step 4: Run tests — expect pass**

```powershell
pytest tests/test_tagger.py -v
```
Expected: all passing.

- [ ] **Step 5: Commit**

```powershell
git add src/ai_accountant/tagger.py tests/test_tagger.py
git commit -m "feat(tagger): add TagResult, _tag_row, enrich — three-layer transaction classifier"
```

---

## Task 4: Wire `enrich()` into `to_dataframe()`

**Files:**
- Modify: `src/ai_accountant/dataframe.py`
- Extend: `tests/test_dataframe.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_dataframe.py`:

```python
class ToDataFrameTagEnrichmentTests(unittest.TestCase):
    def test_to_dataframe_includes_tag_columns(self) -> None:
        from ai_accountant.dataframe import to_dataframe
        from ai_accountant.parser import TransactionParser

        parser = TransactionParser(WALLET)
        tx = {
            "signature": "sig-1",
            "slot": 1,
            "timestamp": 1_700_000_000,
            "type": "SWAP",
            "source": "JUPITER",
            "fee": 5_000,
            "feePayer": WALLET,
            "nativeTransfers": [],
            "tokenTransfers": [],
            "instructions": [],
        }
        df = to_dataframe(parser, [tx])
        self.assertIn("tag_type", df.columns)
        self.assertEqual(df.iloc[0]["tag_type"], "Swap")
        self.assertEqual(df.iloc[0]["tag_protocol"], "Jupiter")
        self.assertAlmostEqual(float(df.iloc[0]["tag_confidence"]), 0.95)

    def test_to_dataframe_empty_has_all_columns_including_tags(self) -> None:
        from ai_accountant.dataframe import to_dataframe
        from ai_accountant.parser import TransactionParser

        parser = TransactionParser(WALLET)
        df = to_dataframe(parser, [])
        self.assertEqual(list(df.columns), DATAFRAME_COLUMNS)
```

- [ ] **Step 2: Run tests — expect failure**

```powershell
pytest tests/test_dataframe.py::ToDataFrameTagEnrichmentTests -v
```
Expected: `FAILED` — tag columns missing or wrong value.

- [ ] **Step 3: Update `to_dataframe()` in `dataframe.py`**

Replace the current `to_dataframe` function body:

```python
def to_dataframe(
    parser: TransactionParser,
    transactions: Iterable[Mapping[str, Any]],
) -> pd.DataFrame:
    """Parse `transactions` with `parser` and return a DataFrame with the canonical schema."""
    from .tagger import enrich

    rows = parser.parse_many(transactions)
    if not rows:
        return pd.DataFrame(columns=DATAFRAME_COLUMNS)
    df = pd.DataFrame(rows)
    enriched = enrich(df)
    return enriched.reindex(columns=DATAFRAME_COLUMNS).reset_index(drop=True)
```

- [ ] **Step 4: Run tests — expect pass**

```powershell
pytest tests/test_dataframe.py -v
```
Expected: all passing.

- [ ] **Step 5: Full suite**

```powershell
pytest -v
```
Expected: all passing.

- [ ] **Step 6: Commit**

```powershell
git add src/ai_accountant/dataframe.py tests/test_dataframe.py
git commit -m "feat(dataframe): wire enrich() into to_dataframe(), tag columns in all outputs"
```

---

## Task 5: Export `TagResult` and `enrich` from `__init__.py`

**Files:**
- Modify: `src/ai_accountant/__init__.py`

- [ ] **Step 1: Update `__init__.py`**

Add the import line after the `report` imports:

```python
from .tagger import TagResult, enrich
```

Add to `__all__`:

```python
    "TagResult",
    "enrich",
```

- [ ] **Step 2: Verify importable**

```powershell
pytest tests/test_compat_shim.py -v
python -c "from ai_accountant import TagResult, enrich; print('OK')"
```
Expected: all passing, `OK` printed.

- [ ] **Step 3: Commit**

```powershell
git add src/ai_accountant/__init__.py
git commit -m "feat(api): export TagResult and enrich from public surface"
```

---

## Task 6: Extend `FilterSpec` with `tag_type`

**Files:**
- Modify: `src/ai_accountant/dashboard/filters.py`
- Extend: `tests/dashboard/test_filters.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/dashboard/test_filters.py`:

```python
class FilterSpecTagTypeTests(unittest.TestCase):
    def test_parses_tag_querystring_key(self) -> None:
        spec = FilterSpec.from_querystring({"tag": "Swap"})
        self.assertEqual(spec.tag_type, "Swap")

    def test_empty_tag_yields_none(self) -> None:
        spec = FilterSpec.from_querystring({"tag": ""})
        self.assertIsNone(spec.tag_type)

    def test_tag_type_makes_filter_active(self) -> None:
        spec = FilterSpec.from_querystring({"tag": "Transfer"})
        self.assertTrue(spec.is_active())

    def test_tag_type_included_in_querystring(self) -> None:
        spec = FilterSpec.from_querystring({"tag": "Swap"})
        self.assertIn("tag=Swap", spec.to_querystring())

    def test_apply_tag_type_filter(self) -> None:
        df = _df_with([
            {"signature": "a", "tag_type": "Swap"},
            {"signature": "b", "tag_type": "Transfer"},
            {"signature": "c", "tag_type": "Swap"},
        ])
        spec = FilterSpec.from_querystring({"tag": "Swap"})
        out = spec.apply(df)
        self.assertEqual(sorted(out["signature"].tolist()), ["a", "c"])

    def test_apply_tag_type_case_insensitive(self) -> None:
        df = _df_with([
            {"signature": "a", "tag_type": "Swap"},
            {"signature": "b", "tag_type": "Transfer"},
        ])
        spec = FilterSpec.from_querystring({"tag": "swap"})
        out = spec.apply(df)
        self.assertEqual(out["signature"].tolist(), ["a"])
```

- [ ] **Step 2: Run tests — expect failure**

```powershell
pytest tests/dashboard/test_filters.py::FilterSpecTagTypeTests -v
```
Expected: `FAILED`

- [ ] **Step 3: Update `FilterSpec` in `filters.py`**

Add `tag_type: str | None = None` to the dataclass fields (before `page`):

```python
@dataclass(frozen=True)
class FilterSpec:
    date_from: date | None = None
    date_to: date | None = None
    token: str | None = None
    type: str | None = None
    status: str | None = None
    source: str | None = None
    q: str | None = None
    tag_type: str | None = None
    page: int = 1
```

In `from_querystring`, add `tag_type=get("tag"),` to the `cls(...)` call.

In `is_active`, add `self.tag_type` to the `any(...)` tuple.

In `to_querystring`, add:

```python
        if self.tag_type:
            out.append(("tag", self.tag_type))
```

In `apply`, add after the `self.q` block:

```python
        if self.tag_type is not None and "tag_type" in df.columns:
            needle = self.tag_type.casefold()
            mask &= df["tag_type"].fillna("").str.casefold() == needle
```

- [ ] **Step 4: Run tests — expect pass**

```powershell
pytest tests/dashboard/test_filters.py -v
```
Expected: all passing.

- [ ] **Step 5: Commit**

```powershell
git add src/ai_accountant/dashboard/filters.py tests/dashboard/test_filters.py
git commit -m "feat(filters): add tag_type filter field with tag querystring key"
```

---

## Task 7: Extend `_transaction_rows()` and `_filter_options()`

**Files:**
- Modify: `src/ai_accountant/report.py`
- Modify: `src/ai_accountant/dashboard/views.py`
- Extend: `tests/dashboard/test_views.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/dashboard/test_views.py`:

```python
class TransactionRowTagFieldsTests(unittest.TestCase):
    def test_transaction_rows_include_tag_fields(self) -> None:
        row = _row(
            tag_type="Swap",
            tag_protocol="Jupiter",
            tag_assets="SOL → USDC",
            tag_amount_display="0.5 SOL → 100 USDC",
            tag_usd_estimate="~125 USD",
            tag_confidence=0.95,
            program_ids=[],
        )
        ctx = wallet_page(_df([row]), spec=FilterSpec(), meta=_meta(), address=WALLET)
        tx = ctx["transactions"][0]
        self.assertEqual(tx["tag_type"], "Swap")
        self.assertEqual(tx["tag_protocol"], "Jupiter")
        self.assertEqual(tx["tag_assets"], "SOL → USDC")
        self.assertEqual(tx["tag_amount_display"], "0.5 SOL → 100 USDC")
        self.assertEqual(tx["tag_usd_estimate"], "~125 USD")
        self.assertEqual(tx["tag_confidence_pct"], "95")

    def test_unknown_row_has_fallback_programs(self) -> None:
        row = _row(
            tag_type="Unknown",
            tag_protocol="Unknown",
            tag_assets="",
            tag_amount_display="",
            tag_usd_estimate=None,
            tag_confidence=0.10,
            program_ids=["AAABBBCCC111222333", "DDDEEEFFF444555666"],
        )
        ctx = wallet_page(_df([row]), spec=FilterSpec(), meta=_meta(), address=WALLET)
        tx = ctx["transactions"][0]
        self.assertIn("AAABBBCC", tx["fallback_programs"])

    def test_filter_options_includes_tag_types(self) -> None:
        rows = [
            _row(signature="a", tag_type="Swap"),
            _row(signature="b", tag_type="Transfer"),
            _row(signature="c", tag_type="Swap"),
        ]
        ctx = wallet_page(_df(rows), spec=FilterSpec(), meta=_meta(), address=WALLET)
        tag_types = ctx["filter_options"]["tag_types"]
        self.assertIn("Swap", tag_types)
        self.assertIn("Transfer", tag_types)
        self.assertEqual(tag_types, sorted(tag_types))
```

- [ ] **Step 2: Run tests — expect failure**

```powershell
pytest tests/dashboard/test_views.py::TransactionRowTagFieldsTests -v
```
Expected: `FAILED`

- [ ] **Step 3: Update `_transaction_rows()` in `report.py`**

In the `_transaction_rows` function, inside the loop, add to the `rows.append({...})` dict:

```python
            "tag_type": str(row.get("tag_type") or "Unknown"),
            "tag_protocol": str(row.get("tag_protocol") or "Unknown"),
            "tag_assets": str(row.get("tag_assets") or ""),
            "tag_amount_display": str(row.get("tag_amount_display") or ""),
            "tag_usd_estimate": row.get("tag_usd_estimate") or None,
            "tag_confidence": float(row.get("tag_confidence") or 0.0),
            "tag_confidence_pct": str(round(float(row.get("tag_confidence") or 0.0) * 100)),
            "fallback_programs": _fallback_programs(row),
```

Add this helper function to `report.py` (alongside the other private helpers):

```python
def _fallback_programs(row: Any) -> str:
    pids = row.get("program_ids")
    if not isinstance(pids, list) or not pids:
        return ""
    return ", ".join(str(p)[:8] + "…" for p in pids[:2])
```

- [ ] **Step 4: Update `_filter_options()` in `views.py`**

Add inside `_filter_options`, after the existing `for _, row in df.iterrows()` loop body:

```python
        tt = row.get("tag_type")
        if tt:
            tag_types.add(str(tt))
```

Declare `tag_types: set[str] = set()` before the loop, and add to the return dict:

```python
        "tag_types": sorted(tag_types),
```

- [ ] **Step 5: Run tests — expect pass**

```powershell
pytest tests/dashboard/test_views.py -v
```
Expected: all passing.

- [ ] **Step 6: Commit**

```powershell
git add src/ai_accountant/report.py src/ai_accountant/dashboard/views.py tests/dashboard/test_views.py
git commit -m "feat(dashboard): add tag fields to transaction rows and filter options"
```

---

## Task 8: Update `wallet.html.j2` — transactions table and filter bar

**Files:**
- Modify: `src/ai_accountant/dashboard/templates/wallet.html.j2`
- Extend: `tests/dashboard/test_routes.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/dashboard/test_routes.py`:

```python
import pandas as pd
from ai_accountant import DATAFRAME_COLUMNS


def _tagged_df():
    row = {col: None for col in DATAFRAME_COLUMNS}
    row.update(
        signature="sig-tag-1",
        timestamp_unix=1_700_000_000,
        status="succeeded",
        transaction_type="SWAP",
        source="JUPITER",
        fee_sol=__import__("decimal").Decimal("0.000005"),
        tag_type="Swap",
        tag_protocol="Jupiter",
        tag_assets="SOL → USDC",
        tag_amount_display="0.5 SOL → 100 USDC",
        tag_usd_estimate=None,
        tag_confidence=0.95,
        program_ids=[],
        net_flow={},
        token_flow_details=[],
        movements_in=[],
        movements_out=[],
    )
    return pd.DataFrame([row], columns=DATAFRAME_COLUMNS)


class TaggedDashboardRenderTests(_RouteCase):
    def setUp(self) -> None:
        super().setUp()
        self.fake.df = _tagged_df()

    def test_wallet_page_renders_tag_type_column(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn("Swap", html)
        self.assertIn("Jupiter", html)

    def test_tag_filter_dropdown_present(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}")
        html = resp.data.decode()
        self.assertIn('name="tag"', html)

    def test_tag_querystring_preserved_in_pagination(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}?tag=Swap")
        self.assertEqual(resp.status_code, 200)
```

- [ ] **Step 2: Run tests — expect failure (or pass with missing assertions)**

```powershell
pytest tests/dashboard/test_routes.py::TaggedDashboardRenderTests -v
```

- [ ] **Step 3: Update the transactions table in `wallet.html.j2`**

Replace the `<section class="report-section">` block that contains the transactions table (lines 148–175 in the current file). New content:

```html
<section class="report-section">
  <h2>Transactions</h2>
  {% if transactions %}
  <table>
    <thead>
      <tr>
        <th>Date</th><th>Status</th><th>Type</th>
        <th>Assets</th><th>Amount</th><th>Fee</th>
        <th>Confidence</th><th>Tx</th>
      </tr>
    </thead>
    <tbody>
      {% for r in transactions %}
      <tr>
        <td>{{ r.date }}</td>
        <td><mark class="{{ r.status }}">{{ r.status }}</mark></td>
        <td>
          <strong>{{ r.tag_type }}</strong>
          <span class="muted">{{ r.tag_protocol }}</span>
        </td>
        <td>
          {% if r.tag_assets %}
            {{ r.tag_assets }}
          {% elif r.fallback_programs %}
            <span class="muted">{{ r.fallback_programs }}</span>
          {% endif %}
        </td>
        <td>
          {{ r.tag_amount_display }}
          {% if r.tag_usd_estimate %}<span class="muted">{{ r.tag_usd_estimate }}</span>{% endif %}
        </td>
        <td>{{ r.fee }}</td>
        <td>
          {% set conf = r.tag_confidence_pct | int %}
          <mark class="confidence {% if conf >= 80 %}high{% elif conf >= 50 %}medium{% else %}low{% endif %}">{{ conf }}%</mark>
        </td>
        <td><a href="{{ url_for('tx_detail_route', address=address, sig=r.signature) }}">{{ r.signature_short }}</a></td>
      </tr>
      <tr class="description-row"><td></td><td colspan="7" class="muted">{{ r.description }}</td></tr>
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
```

- [ ] **Step 4: Add the Tag filter dropdown to the filter bar**

In the filter bar form, after the `<label>Source ...` block and before the `<label>Search` block, insert:

```html
  <label>Tag
    <select name="tag">
      <option value="">Any</option>
      {% for t in filter_options.tag_types %}
      <option value="{{ t }}" {% if filter.tag_type == t %}selected{% endif %}>{{ t }}</option>
      {% endfor %}
    </select>
  </label>
```

- [ ] **Step 5: Run tests — expect pass**

```powershell
pytest tests/dashboard/test_routes.py -v
```
Expected: all passing.

- [ ] **Step 6: Full suite**

```powershell
pytest -v
```
Expected: all passing.

- [ ] **Step 7: Commit**

```powershell
git add src/ai_accountant/dashboard/templates/wallet.html.j2 tests/dashboard/test_routes.py
git commit -m "feat(dashboard): update transactions table with tag columns and Tag filter dropdown"
```

---

## Self-Review Checklist

- [x] **spec: `tagger.py` with `TagResult` + `enrich()`** → Task 3
- [x] **spec: parser `program_ids`** → Task 1
- [x] **spec: 7 new `DATAFRAME_COLUMNS`** → Task 2
- [x] **spec: `SCHEMA_VERSION` = 2** → Task 2
- [x] **spec: three-layer classification** → Task 3 (`_tag_row`)
- [x] **spec: assets/amount display for all types** → Task 3 (`_build_assets`)
- [x] **spec: `enrich()` wired into `to_dataframe()`** → Task 4
- [x] **spec: `__init__.py` exports** → Task 5
- [x] **spec: `FilterSpec.tag_type` + `tag` querystring** → Task 6
- [x] **spec: `_transaction_rows()` tag fields + `fallback_programs`** → Task 7
- [x] **spec: `_filter_options()` adds `tag_types`** → Task 7
- [x] **spec: dashboard table columns + Tag filter dropdown** → Task 8
- [x] **spec: `tag_usd_estimate` always `None` (no price feed yet)** → Task 3 (`_tag_row`)
- [x] **spec: `price_provider` hook on `enrich()`** → Task 3
