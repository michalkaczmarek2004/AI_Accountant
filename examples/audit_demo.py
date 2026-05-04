"""
ILLUSTRATIVE ONLY -- not tax or legal advice.

End-to-end demo of an audit pipeline built on top of SolanaDataFetcher's
DataFrame output. All wallet addresses, counterparties, prices, and
transactions are synthetic.

Pipeline:
    raw helius-shaped json
        -> SolanaDataFetcher.transactions_to_dataframe(...)
        -> classifier (this file)
        -> FIFO cost-basis ledger (this file)
        -> advisory report (printed to stdout)

Assumptions baked in (would be user-elected in a real audit):
    Jurisdiction = US federal
    Cost basis method = FIFO across this single wallet
    Fiat = USD
    Prices = static stub (PRICE_USD), NOT a real oracle
"""

from __future__ import annotations

import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_accountant import SolanaDataFetcher  # noqa: E402

getcontext().prec = 50
TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# 1. Synthetic fixture
# ---------------------------------------------------------------------------
WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"

OWN_WALLET_2 = "OWN-WALLET-2-illustrative-counterparty-placeholder"
EXT_CEX = "EXT-CEX-illustrative-counterparty-placeholder"
EXT_LP = "EXT-LP-illustrative-counterparty-placeholder"
EXT_UNKNOWN = "EXT-UNKNOWN-illustrative-counterparty-placeholder"
EXT_AIRDROP = "EXT-AIRDROP-illustrative-counterparty-placeholder"
EXT_STAKE = "EXT-STAKE-illustrative-counterparty-placeholder"

OWN_WALLETS = {WALLET, OWN_WALLET_2}

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW"


def _ts(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


RAW_TRANSACTIONS: list[dict[str, Any]] = [
    # 1) External SOL deposit -- basis must be sourced off-chain (CEX export).
    {
        "signature": "demo-001-cex-deposit",
        "slot": 280_000_001,
        "timestamp": _ts(2024, 12, 15),
        "type": "TRANSFER",
        "source": "SYSTEM_PROGRAM",
        "description": "External deposit: 10 SOL from CEX",
        "fee": 5_000,
        "feePayer": EXT_CEX,
        "nativeTransfers": [
            {"fromUserAccount": EXT_CEX, "toUserAccount": WALLET, "amount": 10_000_000_000},
        ],
        "tokenTransfers": [],
    },
    # 2) Sell 2 SOL for USDC -- capital event, small gain.
    {
        "signature": "demo-002-swap-sol-usdc",
        "slot": 285_000_002,
        "timestamp": _ts(2025, 1, 20),
        "type": "SWAP",
        "source": "JUPITER",
        "description": "Swap 2 SOL -> 410 USDC",
        "fee": 9_000,
        "feePayer": WALLET,
        "nativeTransfers": [
            {"fromUserAccount": WALLET, "toUserAccount": EXT_LP, "amount": 2_000_000_000},
        ],
        "tokenTransfers": [
            {
                "fromUserAccount": EXT_LP,
                "toUserAccount": WALLET,
                "fromTokenAccount": "FromUSDC1",
                "toTokenAccount": "ToUSDC1",
                "tokenAmount": "410",
                "mint": USDC_MINT,
                "tokenSymbol": "USDC",
            },
        ],
    },
    # 3) Staking reward -- ordinary income at FMV.
    {
        "signature": "demo-003-stake-reward",
        "slot": 288_000_003,
        "timestamp": _ts(2025, 3, 1),
        "type": "STAKE_REWARDS",
        "source": "STAKE_PROGRAM",
        "description": "Stake reward 0.05 SOL",
        "fee": 0,
        "feePayer": WALLET,
        "nativeTransfers": [
            {"fromUserAccount": EXT_STAKE, "toUserAccount": WALLET, "amount": 50_000_000},
        ],
        "tokenTransfers": [],
    },
    # 4) BONK airdrop -- ordinary income at FMV.
    {
        "signature": "demo-004-airdrop-bonk",
        "slot": 288_500_004,
        "timestamp": _ts(2025, 3, 10),
        "type": "AIRDROP",
        "source": "UNKNOWN",
        "description": "BONK airdrop 1,000,000",
        "fee": 0,
        "feePayer": EXT_AIRDROP,
        "nativeTransfers": [],
        "tokenTransfers": [
            {
                "fromUserAccount": EXT_AIRDROP,
                "toUserAccount": WALLET,
                "fromTokenAccount": "FromBonk1",
                "toTokenAccount": "ToBonk1",
                "tokenAmount": "1000000",
                "mint": BONK_MINT,
                "tokenSymbol": "BONK",
            },
        ],
    },
    # 5) High-slippage swap SOL -> BONK -- capital event AND risk flag.
    #    1 SOL out (basis ~$200), received BONK whose stub-priced FMV is ~$540
    #    but in real life the quoted/expected fill was meaningfully higher.
    {
        "signature": "demo-005-swap-sol-bonk-slip",
        "slot": 290_000_005,
        "timestamp": _ts(2025, 4, 1),
        "type": "SWAP",
        "source": "JUPITER",
        "description": "Swap 1 SOL -> 30,000,000 BONK (suspected slippage)",
        "fee": 12_000,
        "feePayer": WALLET,
        "nativeTransfers": [
            {"fromUserAccount": WALLET, "toUserAccount": EXT_LP, "amount": 1_000_000_000},
        ],
        "tokenTransfers": [
            {
                "fromUserAccount": EXT_LP,
                "toUserAccount": WALLET,
                "fromTokenAccount": "FromBonk2",
                "toTokenAccount": "ToBonk2",
                "tokenAmount": "30000000",
                "mint": BONK_MINT,
                "tokenSymbol": "BONK",
            },
        ],
    },
    # 6) Inbound USDC from unknown source -- MISSING BASIS.
    {
        "signature": "demo-006-unknown-usdc",
        "slot": 290_500_006,
        "timestamp": _ts(2025, 4, 25),
        "type": "TRANSFER",
        "source": "SYSTEM_PROGRAM",
        "description": "Inbound 500 USDC from unidentified counterparty",
        "fee": 5_000,
        "feePayer": EXT_UNKNOWN,
        "nativeTransfers": [],
        "tokenTransfers": [
            {
                "fromUserAccount": EXT_UNKNOWN,
                "toUserAccount": WALLET,
                "fromTokenAccount": "FromUSDC2",
                "toTokenAccount": "ToUSDC2",
                "tokenAmount": "500",
                "mint": USDC_MINT,
                "tokenSymbol": "USDC",
            },
        ],
    },
    # 7) Internal transfer to second own wallet -- non-taxable.
    {
        "signature": "demo-007-internal-transfer",
        "slot": 291_000_007,
        "timestamp": _ts(2025, 5, 2),
        "type": "TRANSFER",
        "source": "SYSTEM_PROGRAM",
        "description": "Move 5 SOL to OWN_WALLET_2",
        "fee": 5_000,
        "feePayer": WALLET,
        "nativeTransfers": [
            {"fromUserAccount": WALLET, "toUserAccount": OWN_WALLET_2, "amount": 5_000_000_000},
        ],
        "tokenTransfers": [],
    },
    # 8) Failed transaction -- fee burned, no movements.
    {
        "signature": "demo-008-failed-swap",
        "slot": 291_500_008,
        "timestamp": _ts(2025, 5, 3),
        "type": "SWAP",
        "source": "RAYDIUM",
        "description": "Failed swap (slippage tolerance exceeded)",
        "fee": 7_500,
        "feePayer": WALLET,
        "nativeTransfers": [],
        "tokenTransfers": [],
        "transactionError": {"InstructionError": [0, "Custom 6000"]},
    },
]


# ---------------------------------------------------------------------------
# 2. Build DataFrame with the production fetcher (no HTTP)
# ---------------------------------------------------------------------------
class _OfflineSession:
    def get(self, *_a: Any, **_k: Any) -> Any:
        raise RuntimeError("Demo runs offline.")

    def close(self) -> None:
        return None


def build_dataframe() -> pd.DataFrame:
    fetcher = SolanaDataFetcher(api_key="demo-not-used", session=_OfflineSession())
    return fetcher.transactions_to_dataframe(WALLET, RAW_TRANSACTIONS)


# ---------------------------------------------------------------------------
# 3. Price oracle stub  (asset, YYYY-MM-DD) -> USD per unit
# ---------------------------------------------------------------------------
PRICE_USD: dict[tuple[str, str], Decimal] = {
    ("SOL", "2024-12-15"): Decimal("200"),
    ("SOL", "2025-01-20"): Decimal("205"),
    ("SOL", "2025-03-01"): Decimal("180"),
    ("SOL", "2025-04-01"): Decimal("170"),
    ("SOL", "2025-04-25"): Decimal("160"),
    ("SOL", "2025-05-02"): Decimal("155"),
    ("SOL", "2025-05-03"): Decimal("155"),
    ("USDC", "*"): Decimal("1"),
    ("BONK", "2025-03-10"): Decimal("0.000020"),
    ("BONK", "2025-04-01"): Decimal("0.000018"),
}


def price_usd(symbol: str, when: str) -> Decimal | None:
    return PRICE_USD.get((symbol, when)) or PRICE_USD.get((symbol, "*"))


# ---------------------------------------------------------------------------
# 4. FIFO cost-basis ledger
# ---------------------------------------------------------------------------
@dataclass
class Lot:
    acquired: str
    units: Decimal
    basis_usd_per_unit: Decimal
    source: str

    def __repr__(self) -> str:
        return (
            f"Lot({self.units} @ ${self.basis_usd_per_unit}/u, "
            f"acq={self.acquired}, src={self.source})"
        )


@dataclass
class Ledger:
    lots: dict[str, deque[Lot]] = field(default_factory=lambda: defaultdict(deque))
    missing_basis: list[dict[str, Any]] = field(default_factory=list)

    def acquire(
        self, asset: str, units: Decimal, basis_per_unit: Decimal, acquired: str, source: str
    ) -> None:
        self.lots[asset].append(Lot(acquired, units, basis_per_unit, source))

    def dispose_fifo(self, asset: str, units: Decimal, signature: str, date: str) -> Decimal:
        basis_consumed = Decimal("0")
        remaining = units
        queue = self.lots[asset]
        while remaining > 0 and queue:
            head = queue[0]
            take = min(head.units, remaining)
            basis_consumed += take * head.basis_usd_per_unit
            head.units -= take
            remaining -= take
            if head.units == 0:
                queue.popleft()
        if remaining > 0:
            self.missing_basis.append(
                {
                    "asset": asset,
                    "units_unbacked": remaining,
                    "signature": signature,
                    "date": date,
                    "reason": "Disposal exceeds tracked acquisitions",
                }
            )
        return basis_consumed


# ---------------------------------------------------------------------------
# 5. Classifier
# ---------------------------------------------------------------------------
def classify(row: pd.Series) -> str:
    if row["status"] == "failed":
        return "Failed transaction"

    in_movs = row["movements_in"] or []
    out_movs = row["movements_out"] or []

    counterparties = {m["counterparty"] for m in (in_movs + out_movs) if m.get("counterparty")}
    if counterparties and counterparties.issubset(OWN_WALLETS):
        return "Internal transfer (non-taxable)"

    ttype = (row["transaction_type"] or "").upper()
    if ttype in {"STAKE_REWARDS", "STAKE_REWARD"}:
        return "Staking income (ordinary)"
    if ttype == "AIRDROP":
        return "Airdrop (ordinary income)"
    if ttype == "SWAP" and in_movs and out_movs:
        return "Swap (capital event)"
    if in_movs and not out_movs:
        return "Inbound deposit -- UNKNOWN BASIS"
    if out_movs and not in_movs:
        return "Outbound transfer"
    return "Uncategorized"


# ---------------------------------------------------------------------------
# 6. Pipeline
# ---------------------------------------------------------------------------
EXTERNAL_BASIS: dict[str, list[Lot]] = {
    "demo-001-cex-deposit": [
        Lot(
            acquired="2024-12-15",
            units=Decimal("10"),
            basis_usd_per_unit=Decimal("200"),
            source="external (CEX export, illustrative)",
        ),
    ],
}


def run_pipeline(df: pd.DataFrame) -> tuple[pd.DataFrame, Ledger, list[dict]]:
    ledger = Ledger()
    findings: list[dict] = []

    df = df.sort_values("timestamp_unix", kind="stable").reset_index(drop=True)
    rows: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        category = classify(row)
        date = row["timestamp"][:10] if row["timestamp"] else "unknown"
        sig = row["signature"]

        income_usd = Decimal("0")
        proceeds_usd = Decimal("0")
        basis_usd = Decimal("0")
        gain_usd = Decimal("0")

        if sig in EXTERNAL_BASIS:
            for lot in EXTERNAL_BASIS[sig]:
                ledger.acquire(
                    asset="SOL",
                    units=lot.units,
                    basis_per_unit=lot.basis_usd_per_unit,
                    acquired=lot.acquired,
                    source=lot.source,
                )
            category = "External acquisition (basis seeded)"

        elif category == "Staking income (ordinary)":
            for m in row["movements_in"]:
                px = price_usd(m["symbol"], date)
                if px is None:
                    findings.append({"sig": sig, "issue": "missing price", "asset": m["symbol"]})
                    continue
                amt = Decimal(m["amount"])
                income_usd += amt * px
                ledger.acquire(m["symbol"], amt, px, date, "income:staking")

        elif category == "Airdrop (ordinary income)":
            for m in row["movements_in"]:
                px = price_usd(m["symbol"], date)
                if px is None:
                    findings.append({"sig": sig, "issue": "missing price", "asset": m["symbol"]})
                    continue
                amt = Decimal(m["amount"])
                income_usd += amt * px
                ledger.acquire(m["symbol"], amt, px, date, "income:airdrop")

        elif category == "Swap (capital event)":
            for m in row["movements_in"]:
                px = price_usd(m["symbol"], date)
                if px is None:
                    findings.append({"sig": sig, "issue": "missing price", "asset": m["symbol"]})
                    continue
                proceeds_usd += Decimal(m["amount"]) * px
            for m in row["movements_out"]:
                amt = Decimal(m["amount"])
                basis_usd += ledger.dispose_fifo(m["symbol"], amt, sig, date)
            gain_usd = proceeds_usd - basis_usd
            for m in row["movements_in"]:
                px = price_usd(m["symbol"], date)
                if px is None:
                    continue
                ledger.acquire(m["symbol"], Decimal(m["amount"]), px, date, "swap")
            # Slippage detection — compare implied execution price (in_value_usd / out_units)
            # to the oracle reference price for the out-asset on the swap date.
            # ILLUSTRATIVE — production needs a real quote provider (e.g. Jupiter quote
            # API at swap-submit time). A daily oracle close still confuses true slippage
            # with intra-day price drift, but it removes the basis-vs-proceeds confusion
            # that the previous check had.
            if (
                len(row["movements_in"]) == 1
                and len(row["movements_out"]) >= 1
                and proceeds_usd > 0
            ):
                out_units = Decimal(row["movements_in"][0]["amount"])
                out_symbol = row["movements_in"][0]["symbol"]
                oracle_px = price_usd(out_symbol, date)
                in_value_usd = Decimal("0")
                for m in row["movements_out"]:
                    in_px = price_usd(m["symbol"], date)
                    if in_px is None:
                        in_value_usd = Decimal("0")
                        break
                    in_value_usd += Decimal(m["amount"]) * in_px
                if oracle_px is not None and oracle_px > 0 and out_units > 0 and in_value_usd > 0:
                    implied_px = in_value_usd / out_units
                    slip_pct = (oracle_px - implied_px) / oracle_px
                    if slip_pct > Decimal("0.05"):
                        findings.append(
                            {
                                "sig": sig,
                                "issue": "Possible high slippage (implied execution price below oracle reference)",
                                "implied_slippage_pct": f"{(slip_pct * 100).quantize(TWO_PLACES)}%",
                            }
                        )

        elif category == "Inbound deposit -- UNKNOWN BASIS":
            for m in row["movements_in"]:
                amt = Decimal(m["amount"])
                ledger.acquire(m["symbol"], amt, Decimal("0"), date, "unknown")
                ledger.missing_basis.append(
                    {
                        "asset": m["symbol"],
                        "units_unbacked": amt,
                        "signature": sig,
                        "date": date,
                        "reason": "External counterparty, no income classification",
                    }
                )

        elif category == "Internal transfer (non-taxable)":
            findings.append(
                {
                    "sig": sig,
                    "issue": (
                        "Internal transfer -- basis must follow asset to "
                        "OWN_WALLET_2; single-wallet view is partial."
                    ),
                }
            )

        elif category == "Failed transaction":
            findings.append(
                {
                    "sig": sig,
                    "issue": "Failed tx -- fee paid but no economic outcome; "
                    "fee deductibility uncertain under US current law.",
                }
            )

        fee_usd = Decimal("0")
        if row["fee_paid_by_wallet"]:
            sol_px = price_usd("SOL", date) or Decimal("0")
            fee_usd = Decimal(row["fee_sol"]) * sol_px

        rows.append(
            {
                "signature": sig,
                "date": date,
                "category": category,
                "income_usd": income_usd.quantize(TWO_PLACES),
                "proceeds_usd": proceeds_usd.quantize(TWO_PLACES),
                "basis_usd": basis_usd.quantize(TWO_PLACES),
                "gain_usd": gain_usd.quantize(TWO_PLACES),
                "fee_usd": fee_usd.quantize(TWO_PLACES),
            }
        )

    classified = pd.DataFrame(rows)
    return classified, ledger, findings


# ---------------------------------------------------------------------------
# 7. Internal consistency checks (run before report)
# ---------------------------------------------------------------------------
def consistency_checks(classified: pd.DataFrame, ledger: Ledger) -> list[str]:
    issues: list[str] = []
    for _, r in classified.iterrows():
        if r["category"] == "Swap (capital event)":
            expected = (r["proceeds_usd"] - r["basis_usd"]).quantize(TWO_PLACES)
            if expected != r["gain_usd"]:
                issues.append(
                    f"{r['signature']}: gain != proceeds - basis ({r['gain_usd']} vs {expected})"
                )
    for asset, queue in ledger.lots.items():
        for lot in queue:
            if lot.units < 0:
                issues.append(f"Negative units in lot for {asset}: {lot}")
    return issues


# ---------------------------------------------------------------------------
# 8. Report
# ---------------------------------------------------------------------------
def render_report(
    classified: pd.DataFrame, ledger: Ledger, findings: list[dict], checks: list[str]
) -> str:
    total_income = classified["income_usd"].sum()
    total_gain = classified["gain_usd"].sum()
    total_fee = classified["fee_usd"].sum()
    by_cat = classified.groupby("category")[["income_usd", "gain_usd", "fee_usd"]].sum()

    lines: list[str] = []
    sep = "=" * 78
    sub = "-" * 78
    lines += [
        sep,
        "AI ACCOUNTANT  --  ILLUSTRATIVE AUDIT REPORT",
        f"Wallet:        {WALLET}",
        "Period:        2024-12-15 -> 2025-05-03 (synthetic)",
        "Jurisdiction:  US federal (assumed)",
        "Method:        FIFO, single-wallet, base fiat USD",
        "Price source:  static stub (NOT a real oracle)",
        sep,
        "",
        "EXECUTIVE SUMMARY",
        sub,
        f"  Ordinary income (staking + airdrops):   $ {total_income:>12}",
        f"  Net realized capital gain / (loss):     $ {total_gain:>12}",
        f"  Network fees paid by wallet:            $ {total_fee:>12}",
        "  Internal-consistency checks:           "
        f" {'PASS' if not checks else 'FAIL (' + str(len(checks)) + ')'}",
        "",
        "BREAKDOWN BY CATEGORY",
        sub,
        by_cat.to_string(),
        "",
        "PER-TRANSACTION DETAIL",
        sub,
        classified.to_string(index=False),
        "",
        "REMAINING OPEN LOTS (post-period, FIFO order)",
        sub,
    ]
    if not ledger.lots:
        lines.append("  (none)")
    for asset, queue in ledger.lots.items():
        for lot in queue:
            lines.append(
                f"  {asset:<6} {str(lot.units):>20} units "
                f"@ ${lot.basis_usd_per_unit:<10} "
                f"acq {lot.acquired}  src={lot.source}"
            )
    lines += ["", "RISK FINDINGS", sub]
    if not findings:
        lines.append("  (none)")
    for f in findings:
        lines.append(f"  - {f}")
    if ledger.missing_basis:
        lines += ["", "MISSING-BASIS FLAGS", sub]
        for mb in ledger.missing_basis:
            lines.append(f"  - {mb}")
    if checks:
        lines += ["", "INTERNAL CHECK FAILURES", sub]
        for c in checks:
            lines.append(f"  - {c}")
    lines += [
        "",
        "STRATEGIC MOVES",
        sub,
        _strategic_moves(ledger),
        "",
        sep,
        "ILLUSTRATIVE OUTPUT  --  NOT TAX OR LEGAL ADVICE.",
        "Synthetic data, synthetic prices, single-wallet view, US defaults.",
        sep,
    ]
    return "\n".join(lines)


def _strategic_moves(ledger: Ledger) -> str:
    underwater: list[str] = []
    for asset, queue in ledger.lots.items():
        cur = price_usd(asset, "2025-05-03")
        if cur is None:
            continue
        for lot in queue:
            if lot.basis_usd_per_unit > cur and lot.units > 0:
                unrealized = (cur - lot.basis_usd_per_unit) * lot.units
                underwater.append(
                    f"{asset}: {lot.units} units acquired {lot.acquired} "
                    f"@ ${lot.basis_usd_per_unit} (now ${cur}, "
                    f"unrealized ${unrealized.quantize(TWO_PLACES)})"
                )

    block = []
    block.append("[CONFIRMED CURRENT LAW -- US federal]")
    block.append("  * Staking rewards are ordinary income at FMV when dominion")
    block.append("    and control is established (Rev. Rul. 2023-14).")
    block.append("  * Airdrops are ordinary income at FMV on receipt")
    block.append("    (Rev. Rul. 2019-24).")
    block.append("  * Crypto is property (Notice 2014-21); each disposal is a")
    block.append("    capital event. Hold > 12 months -> long-term rates.")
    block.append("  * IRC sec.1091 wash-sale rule does NOT apply to digital")
    block.append("    assets today. Tax-loss harvesting is currently legal even")
    block.append("    with same-day repurchase. Underwater open lots:")
    if underwater:
        for u in underwater:
            block.append(f"      - {u}")
    else:
        block.append("      (none material in this period)")
    block.append("")
    block.append("[HIGH-PROBABILITY DRAFTS / PROPOSED -- not enacted, watch]")
    block.append("  * Multiple congressional drafts have proposed extending")
    block.append("    sec.1091 to digital assets. If enacted, harvest-and-")
    block.append("    repurchase within 30 days would be disallowed.")
    block.append("  * Form 1099-DA broker reporting begins for centralized")
    block.append("    brokers (TY 2025). The DeFi broker rule was rescinded by")
    block.append("    Congress in 2025; on-chain DEX activity here is NOT")
    block.append("    subject to broker 1099 today.")
    block.append("  * Mark-to-market for actively-traded digital assets has")
    block.append("    been proposed periodically; not law.")
    block.append("")
    block.append("[OPERATIONAL -- before filing]")
    block.append("  * Resolve all 'UNKNOWN BASIS' rows. A zero-basis fallback")
    block.append("    inflates gain on subsequent disposal.")
    block.append("  * Unify ledger across all own wallets; the internal")
    block.append("    transfer flagged above moves basis off this wallet.")
    block.append("  * Replace static price stub with a block-time oracle")
    block.append("    (Pyth, Birdeye, or CoinGecko historical) before any")
    block.append("    USD figure here is relied upon.")
    block.append("  * For the high-slippage swap, compare on-chain fill price")
    block.append("    to a contemporaneous Jupiter quote to confirm slippage")
    block.append("    vs. simple price drift before treating it as a risk event.")
    return "\n".join(block)


# ---------------------------------------------------------------------------
# 9. Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    df = build_dataframe()
    classified, ledger, findings = run_pipeline(df)
    checks = consistency_checks(classified, ledger)
    print(render_report(classified, ledger, findings, checks))


if __name__ == "__main__":
    main()
