"""Tax classification and aggregation for the Tax Assistant dashboard module."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pandas as pd

from .explainer import _classify, _is_source_unknown, _safe_decimal, _safe_str

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CASE_TO_CATEGORY: dict[str, str] = {
    "sol_in": "Income",
    "token_in": "Income",
    "nft_received": "Income",
    "sol_out": "Expense",
    "token_out": "Expense",
    "swap": "Swap",
    "nft_bought": "Swap",
    "nft_sold": "Swap",
    "lp": "Swap",
    "perp": "Swap",
    "staking_deposit": "Transfer",
    "bridge": "Transfer",
    "mint_burn": "Transfer",
    "staking_withdrawal": "Staking / Needs review",
    "airdrop": "Airdrop",
    "unknown": "Unknown / Needs review",
}

_CATEGORY_LABELS: dict[str, str] = {
    "Income": "Income",
    "Expense": "Expense",
    "Swap": "Swap / trade",
    "Airdrop": "Airdrop",
    "Staking / Needs review": "Staking withdrawal",
    "Unknown / Needs review": "Unknown activity",
    "Transfer": "Transfer",
}

_CASE_LABELS: dict[str, str] = {
    "sol_in": "SOL received",
    "token_in": "Token received",
    "nft_received": "NFT received",
    "sol_out": "SOL sent",
    "token_out": "Token sent",
    "swap": "Swap / trade",
    "nft_bought": "NFT purchase",
    "nft_sold": "NFT sale",
    "lp": "Liquidity pool",
    "perp": "Perpetual trade",
    "staking_deposit": "Staking deposit",
    "staking_withdrawal": "Staking withdrawal",
    "airdrop": "Airdrop",
    "bridge": "Bridge transfer",
    "mint_burn": "Mint / burn",
    "unknown": "Unknown activity",
}

DEFAULT_TAX_COUNTRY = "US"

_TAX_COUNTRY_PROFILES: dict[str, dict[str, Any]] = {
    "US": {
        "code": "US",
        "label": "United States",
        "summary": (
            "United States federal guidance treats digital assets as property. "
            "Use these notes as a review checklist, not as a final tax conclusion."
        ),
        "deadline_warning_days": 30,
        "sources": [
            {
                "label": "IRS digital assets guidance",
                "url": "https://www.irs.gov/filing/digital-assets",
            },
            {
                "label": "IRS virtual currency FAQs",
                "url": (
                    "https://www.irs.gov/individuals/international-taxpayers/"
                    "frequently-asked-questions-on-virtual-currency-transactions"
                ),
            },
            {
                "label": "IRS Topic 409 capital gains",
                "url": "https://www.irs.gov/taxtopics/tc409",
            },
            {
                "label": "IRS Form 8949 instructions",
                "url": "https://www.irs.gov/instructions/i8949",
            },
        ],
    },
    "PL": {
        "code": "PL",
        "label": "Poland",
        "summary": (
            "Polish PIT guidance treats taxable crypto disposal separately from crypto-to-crypto swaps. "
            "Use these notes as a Polish PIT-38 review checklist, not as a final legal opinion."
        ),
        "deadline_warning_days": 30,
        "sources": [
            {
                "label": "podatki.gov.pl crypto disposal",
                "url": (
                    "https://www.podatki.gov.pl/podatki-osobiste/pit/informacje-podstawowe/"
                    "co-jest-opodatkowane/zbycie-kryptowalut/"
                ),
            },
            {
                "label": "podatki.gov.pl PIT-38 2025",
                "url": "https://www.podatki.gov.pl/twoj-e-pit/pit-38-za-2025-rok/",
            },
            {
                "label": "Personal Income Tax Act",
                "url": "https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU19910800350",
            },
        ],
    },
}

_TAX_COUNTRY_ALIASES: dict[str, str] = {
    "US": "US",
    "USA": "US",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "PL": "PL",
    "POLAND": "PL",
    "POLSKA": "PL",
}

_US_TAX_DEADLINES_BY_YEAR: dict[int, list[dict[str, str]]] = {
    2025: [
        {
            "kind": "annual_return_payment",
            "label": "File 2025 Form 1040 and pay 2025 federal tax due",
            "due_date": "2026-04-15",
            "action": "File the return, pay any balance due, or confirm an extension was requested.",
            "note": "An extension gives more time to file, not more time to pay.",
            "source_label": "IRS individual tax filing",
            "source_url": "https://www.irs.gov/individual-tax-filing",
        },
        {
            "kind": "extension_filing",
            "label": "Final extended filing deadline for 2025 Form 1040",
            "due_date": "2026-10-15",
            "action": "File the extended return if Form 4868 was submitted by the original deadline.",
            "note": "Payment was still due by April 15, 2026.",
            "source_label": "IRS extension reminder",
            "source_url": "https://www.irs.gov/newsroom/if-you-need-more-time-to-file-request-an-extension",
        },
    ],
    2026: [
        {
            "kind": "annual_return_payment",
            "label": "File 2026 Form 1040 and pay 2026 federal tax due",
            "due_date": "2027-04-15",
            "action": "File the return, pay any balance due, or request an extension by the deadline.",
            "note": "Calendar-year individual returns are generally due April 15.",
            "source_label": "IRS when to file",
            "source_url": "https://www.irs.gov/filing/individuals/when-to-file",
        },
        {
            "kind": "estimated_tax_q1",
            "label": "2026 estimated tax payment for Jan. 1-March 31 income",
            "due_date": "2026-04-15",
            "action": "Consider whether estimated tax is due for Q1 digital asset income or gains.",
            "note": "Estimated tax can apply if withholding is not enough.",
            "source_label": "IRS estimated tax FAQ",
            "source_url": "https://www.irs.gov/faqs/estimated-tax/individuals",
        },
        {
            "kind": "estimated_tax_q2",
            "label": "2026 estimated tax payment for April 1-May 31 income",
            "due_date": "2026-06-15",
            "action": "Review Q2 realized gains/income and consider an estimated payment.",
            "note": "A warning appears when this is within 30 days.",
            "source_label": "IRS Publication 505",
            "source_url": "https://www.irs.gov/publications/p505",
        },
        {
            "kind": "estimated_tax_q3",
            "label": "2026 estimated tax payment for June 1-Aug. 31 income",
            "due_date": "2026-09-15",
            "action": "Review Q3 realized gains/income and consider an estimated payment.",
            "note": "A warning appears when this is within 30 days.",
            "source_label": "IRS Publication 505",
            "source_url": "https://www.irs.gov/publications/p505",
        },
        {
            "kind": "estimated_tax_q4",
            "label": "2026 estimated tax payment for Sept. 1-Dec. 31 income",
            "due_date": "2027-01-15",
            "action": "Review Q4 realized gains/income and consider an estimated payment.",
            "note": "The January payment may not be needed if the return is filed and paid by Jan. 31.",
            "source_label": "IRS Publication 505",
            "source_url": "https://www.irs.gov/publications/p505",
        },
    ],
}

_PL_TAX_DEADLINES_BY_YEAR: dict[int, list[dict[str, str]]] = {
    2025: [
        {
            "kind": "annual_pit38_return",
            "label": "File PIT-38 for 2025 virtual currency disposal and acquisition costs",
            "due_date": "2026-04-30",
            "action": "File PIT-38 and pay any 2025 tax due by the statutory deadline.",
            "note": "Report documented acquisition costs even if no taxable disposal occurred in the year.",
            "source_label": "podatki.gov.pl PIT-38",
            "source_url": "https://www.podatki.gov.pl/twoj-e-pit/pit-38-za-2025-rok/",
        },
    ],
    2026: [
        {
            "kind": "annual_pit38_return",
            "label": "File PIT-38 for 2026 virtual currency disposal and acquisition costs",
            "due_date": "2027-04-30",
            "action": "File PIT-38 and pay any 2026 tax due by the statutory deadline.",
            "note": "For Polish crypto reporting, excess acquisition costs can carry forward instead of creating a deductible loss.",
            "source_label": "podatki.gov.pl crypto disposal",
            "source_url": (
                "https://www.podatki.gov.pl/podatki-osobiste/pit/informacje-podstawowe/"
                "co-jest-opodatkowane/zbycie-kryptowalut/"
            ),
        },
    ],
}

_US_TAX_GUIDANCE_BY_RULE: dict[str, dict[str, str]] = {
    "swap_trade_cost_basis": {
        "treatment": (
            "Likely taxable disposal if the wallet exchanged one digital asset for another. "
            "For a personal/investment wallet, this is usually reviewed as capital gain or loss."
        ),
        "tax_due": (
            "Potential tax is usually on the gain, not on the full trade size: USD value received "
            "minus cost basis and allowed costs. A loss may offset capital gains subject to US limits."
        ),
        "calculation": "Gain/loss = fair market value received in USD - cost basis in USD - eligible fees.",
        "forms": "Usually Form 8949 and Schedule D for capital assets.",
        "rate_note": (
            "Short-term gains are generally taxed as ordinary income. Long-term capital gains may be "
            "0%, 15%, or 20% depending on taxable income; special categories can differ."
        ),
    },
    "nft_cost_basis": {
        "treatment": (
            "Likely taxable NFT disposal if the NFT was sold or exchanged for SOL, USDC, another token, "
            "or cash. If it was only bought, there may be no immediate gain until a later sale/disposal."
        ),
        "tax_due": (
            "Potential tax is usually capital gains tax on profit, not on the full sale proceeds. "
            "If the NFT was held for business/inventory or received for services, ordinary-income rules may apply."
        ),
        "calculation": "NFT gain/loss = sale proceeds or FMV received in USD - NFT cost basis in USD - selling fees.",
        "forms": "Usually Form 8949 and Schedule D for investment NFTs; Schedule C can matter for business activity.",
        "rate_note": (
            "Short-term NFT gains are generally ordinary-income-rate capital gains. Long-term gains may use "
            "long-term capital gain rates; some collectible-like NFTs need specialist review."
        ),
    },
    "lp_cost_basis": {
        "treatment": (
            "Likely mixed tax event. Adding/removing liquidity can include token swaps, receipt or disposal "
            "of LP tokens, fees, rewards, or a position change."
        ),
        "tax_due": (
            "Potential tax depends on each leg: disposals may create capital gain/loss, while rewards or fees "
            "may be ordinary income."
        ),
        "calculation": "Break the transaction into assets disposed, assets received, fees, rewards, and LP token basis.",
        "forms": "Often Form 8949/Schedule D for disposals; Schedule 1 or Schedule C may matter for income.",
        "rate_note": "Rates depend on whether each leg is capital gain, ordinary income, or business income.",
    },
    "perp_pnl_review": {
        "treatment": (
            "Likely taxable trading result if the position produced realized PnL, funding, or fees. "
            "Perps need extra review because the dashboard only sees parsed wallet movements."
        ),
        "tax_due": "Potential tax is generally based on realized net gain/income after reconciling losses and fees.",
        "calculation": "Reconcile realized PnL, funding, fees, collateral movements, settlement asset, and timestamps.",
        "forms": "Form depends on instrument and taxpayer facts; discuss Form 8949/Schedule D vs other treatment.",
        "rate_note": "Do not infer the rate until the product, holding period, and taxpayer status are confirmed.",
    },
    "airdrop_income_review": {
        "treatment": (
            "Likely ordinary income if the user received and controlled new digital assets. "
            "A later sale/exchange can create a separate capital gain or loss."
        ),
        "tax_due": "Potential ordinary income tax on FMV in USD at receipt, plus later capital gain/loss when disposed.",
        "calculation": "Income amount = fair market value in USD when received and controlled.",
        "forms": "Often Schedule 1 for other income; Schedule C if connected to business activity.",
        "rate_note": "Ordinary income is taxed at the taxpayer's ordinary income rates.",
    },
    "staking_withdrawal_principal_reward": {
        "treatment": (
            "Could be non-taxable return of previously staked principal, taxable staking reward income, "
            "or a mix of both. The dashboard cannot split that automatically."
        ),
        "tax_due": (
            "Potential ordinary income tax applies to staking rewards when credited/controlled; returned "
            "principal is not the same as new income."
        ),
        "calculation": "Split withdrawn amount into principal vs reward; value rewards in USD when credited or controlled.",
        "forms": "Often Schedule 1 for reward income; Schedule C if staking is business activity.",
        "rate_note": "Reward income is generally ordinary income; later disposal can create capital gain/loss.",
    },
    "large_transfer_label": {
        "treatment": (
            "Not automatically taxable. If this was a transfer between wallets the same user owns, it is "
            "generally not a sale. If it went to another person, exchange, protocol, or merchant, tax treatment can change."
        ),
        "tax_due": "Possible tax only after the source, destination, ownership, and purpose are labeled.",
        "calculation": "Classify the transfer first; then calculate income or gain only if it was not a self-transfer.",
        "forms": "Self-transfers usually are not Form 8949 events; sales/exchanges may be.",
        "rate_note": "No rate can be estimated until the purpose is known.",
    },
    "source_unknown": {
        "treatment": (
            "Unknown. The same inflow could be a self-transfer, gift, exchange withdrawal, payment, reward, "
            "airdrop, or sale proceeds."
        ),
        "tax_due": "Possible tax depends entirely on source: income/reward/payment may be taxable; self-transfer may not be.",
        "calculation": "Label source first, then apply income or disposal calculation if relevant.",
        "forms": "Possible Schedule 1, Schedule C, Form 8949/Schedule D, Form 709, or no tax form depending on facts.",
        "rate_note": "No reliable tax rate can be shown until the source is identified.",
    },
    "failed_transaction_fee": {
        "treatment": "Usually not a sale/disposal of the intended asset because the transaction failed.",
        "tax_due": "Usually no gain/loss from the failed action itself; a paid network fee may still need records.",
        "calculation": "Record fee asset, fee amount, timestamp, and USD value if the wallet paid the fee.",
        "forms": "Usually supporting records rather than a standalone sale entry, unless the fee treatment requires it.",
        "rate_note": "No capital gain rate applies unless another asset was actually disposed.",
    },
    "unknown_program": {
        "treatment": (
            "Unknown. Do not treat this as safe until the program and economic purpose are identified."
        ),
        "tax_due": "Could be no tax, capital gain/loss, ordinary income, fee-only activity, or a protocol position change.",
        "calculation": "Identify program, assets received/disposed, FMV in USD, cost basis, and fees.",
        "forms": "Form depends on classification after review.",
        "rate_note": "No reliable rate can be shown until the transaction is classified.",
    },
    "tax_review_needed": {
        "treatment": "Needs manual classification before a US tax treatment can be assigned.",
        "tax_due": "Possible tax depends on whether this was income, sale/exchange/disposal, transfer, or fee.",
        "calculation": "Classify the event, then calculate USD income or gain/loss if applicable.",
        "forms": "Possible Form 8949/Schedule D, Schedule 1, Schedule C, or no form depending on facts.",
        "rate_note": "No reliable tax rate can be shown until classified.",
    },
}

_PL_TAX_GUIDANCE_BY_RULE: dict[str, dict[str, str]] = {
    "swap_trade_cost_basis": {
        "treatment": (
            "For Polish PIT, exchange between virtual currencies is generally not a taxable disposal. "
            "Taxable disposal usually means conversion to legal tender, goods, services, or a property right "
            "other than virtual currency."
        ),
        "tax_due": (
            "Potential tax is 19% of income from taxable crypto disposal. If documented costs exceed revenue, "
            "income is zero and excess costs carry forward; Polish rules do not create a separate deductible "
            "crypto loss."
        ),
        "calculation": "PIT-38 income = taxable disposal revenue in PLN - documented direct acquisition/disposal costs.",
        "forms": "Usually PIT-38 for an individual Polish tax resident.",
        "rate_note": "The Polish virtual currency PIT rate is 19%, subject to taxpayer-specific facts.",
    },
    "nft_cost_basis": {
        "treatment": (
            "NFT treatment can differ from virtual currency treatment. Review whether the NFT is a property right, "
            "service-related asset, collectible-like asset, or business inventory before using crypto rules."
        ),
        "tax_due": "Potential tax depends on the legal classification of the NFT and the taxpayer status.",
        "calculation": "Reconcile sale proceeds, acquisition cost, direct fees, and PLN conversion rate for the disposal date.",
        "forms": "Discuss PIT-38 versus other PIT treatment with a Polish tax professional.",
        "rate_note": "Do not infer the rate until NFT classification is confirmed.",
    },
    "airdrop_income_review": {
        "treatment": (
            "Airdrops and rewards need fact-specific Polish review. The dashboard should not assume the asset has "
            "deductible acquisition cost unless the taxpayer paid a documented direct acquisition expense."
        ),
        "tax_due": "Potential tax depends on whether and when income arises and on later taxable disposal.",
        "calculation": "Document receipt facts, control date, market value, later disposal revenue, and any direct costs.",
        "forms": "Potentially PIT-38 or another PIT schedule depending on facts.",
        "rate_note": "No reliable rate can be shown until the event is classified.",
    },
    "large_transfer_label": {
        "treatment": "A self-transfer between the taxpayer's own wallets is generally not a taxable disposal.",
        "tax_due": "Possible tax only after confirming whether this was a self-transfer, sale, payment, gift, or protocol action.",
        "calculation": "Classify ownership and purpose first; calculate PIT only for taxable disposals or income events.",
        "forms": "Usually support records for self-transfers; PIT reporting depends on the final classification.",
        "rate_note": "No rate can be inferred until ownership and purpose are confirmed.",
    },
    "source_unknown": {
        "treatment": "Unknown source. It may be a self-transfer, exchange withdrawal, reward, payment, gift, or sale proceeds.",
        "tax_due": "Possible tax depends entirely on the source and later disposal.",
        "calculation": "Label the source first, then apply Polish PIT treatment only if the event is taxable.",
        "forms": "Usually PIT-38 for taxable crypto disposals, but facts can require different treatment.",
        "rate_note": "No reliable rate can be shown until the source is identified.",
    },
    "failed_transaction_fee": {
        "treatment": "A failed transaction usually is not a disposal of the intended asset.",
        "tax_due": "Usually no taxable disposal from the failed action itself; keep network fee records.",
        "calculation": "Record fee asset, fee amount, timestamp, and PLN value if needed for support records.",
        "forms": "Usually support records rather than a standalone PIT-38 disposal entry.",
        "rate_note": "No rate applies unless another taxable event occurred.",
    },
    "unknown_program": {
        "treatment": "Unknown protocol interaction. Do not treat it as tax-ready until the economic purpose is known.",
        "tax_due": "Could be no tax, taxable disposal, income, fee-only activity, or a protocol position change.",
        "calculation": "Identify assets disposed, assets received, direct costs, timestamp, and PLN values.",
        "forms": "Form depends on classification after review.",
        "rate_note": "No reliable rate can be shown until the transaction is classified.",
    },
    "tax_review_needed": {
        "treatment": "Needs manual classification before Polish tax treatment can be assigned.",
        "tax_due": "Possible tax depends on whether this was a taxable disposal, income event, transfer, or fee.",
        "calculation": "Classify the event, then calculate PLN revenue and documented direct costs if taxable.",
        "forms": "Possible PIT-38 or other PIT treatment depending on facts.",
        "rate_note": "No reliable rate can be shown until classified.",
    },
}

TAXABLE_CATEGORIES: frozenset[str] = frozenset({"Income", "Swap", "Airdrop"})

REVIEW_REQUIRED_CATEGORIES: frozenset[str] = frozenset({
    "Swap",
    "Airdrop",
    "Staking / Needs review",
    "Unknown / Needs review",
})

LARGE_FLOW_THRESHOLD: Decimal = Decimal("0.5")

TAX_DISCLAIMER = (
    "This is not financial or tax advice. "
    "Always consult a qualified tax professional."
)

_TAX_ADVICE_ASSUMPTIONS: dict[str, dict[str, Any]] = {
    "US": {
        "currency": "USD",
        "sol_rate": Decimal("200"),
        "tax_rate": Decimal("0.24"),
        "rate_label": "demo 24% short-term/ordinary rate",
        "money_prefix": "$",
        "money_suffix": "",
    },
    "PL": {
        "currency": "PLN",
        "sol_rate": Decimal("560"),
        "tax_rate": Decimal("0.19"),
        "rate_label": "19% PIT virtual-currency rate",
        "money_prefix": "",
        "money_suffix": " PLN",
    },
}

# Category → review queue tier (lower = higher priority)
_CATEGORY_TIER: dict[str, int] = {
    "Unknown / Needs review": 1,
    "Swap": 2,
    "Airdrop": 3,
    "Staking / Needs review": 4,
}

# ---------------------------------------------------------------------------
# Public API — category
# ---------------------------------------------------------------------------


def tax_category(row: pd.Series) -> str:
    """Map a DataFrame row to one of the eight tax category labels."""
    case = _classify(row)
    return _CASE_TO_CATEGORY.get(case, "Unknown / Needs review")


def normalize_tax_country(country: str | None) -> str:
    """Return a supported tax country code, defaulting to United States."""
    raw = _safe_str(country, DEFAULT_TAX_COUNTRY).strip().upper()
    code = _TAX_COUNTRY_ALIASES.get(raw, raw)
    return code if code in _TAX_COUNTRY_PROFILES else DEFAULT_TAX_COUNTRY


def tax_country_options() -> list[dict[str, Any]]:
    """Return supported country profiles for the Tax Assistant selector."""
    return [
        {
            "code": profile["code"],
            "label": profile["label"],
            "summary": profile["summary"],
            "sources": profile["sources"],
        }
        for profile in _TAX_COUNTRY_PROFILES.values()
    ]


def tax_country_profile(country: str | None) -> dict[str, Any]:
    """Return the normalized country profile used by review notes."""
    return _TAX_COUNTRY_PROFILES[normalize_tax_country(country)]


def tax_deadline_rows(
    country: str | None,
    years: list[int] | set[int] | tuple[int, ...] | None = None,
    *,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return sourced tax deadlines with dashboard warning status."""
    tax_country = normalize_tax_country(country)
    if tax_country not in {"US", "PL"}:
        return []
    today = today or datetime.now(timezone.utc).date()
    warning_days = int(tax_country_profile(tax_country).get("deadline_warning_days", 30))
    target_years = sorted(set(years or []))
    if not target_years:
        target_years = [today.year - 1, today.year]
    deadlines_by_year = _US_TAX_DEADLINES_BY_YEAR if tax_country == "US" else _PL_TAX_DEADLINES_BY_YEAR

    rows: list[dict[str, Any]] = []
    for year in target_years:
        for raw in deadlines_by_year.get(year, []):
            due = date.fromisoformat(raw["due_date"])
            days_until = (due - today).days
            if days_until < 0:
                status = "overdue"
                status_label = f"Passed {abs(days_until)} days ago"
            elif days_until <= warning_days:
                status = "due-soon"
                status_label = "Due today" if days_until == 0 else f"Due in {days_until} days"
            else:
                status = "upcoming"
                status_label = f"Due in {days_until} days"
            rows.append({
                **raw,
                "ack_id": f"{tax_country}:deadline:{year}:{raw['kind']}:{raw['due_date']}",
                "confirm_label": "Mark as done",
                "tax_year": year,
                "country": tax_country,
                "due": due,
                "due_display": f"{due.strftime('%b')} {due.day}, {due.year}",
                "days_until": days_until,
                "status": status,
                "status_label": status_label,
                "warning_days": warning_days,
            })
    rows.sort(key=lambda r: (r["due"], r["kind"]))
    return rows


def tax_deadline_notice(
    country: str | None,
    tax_year: int | None,
    *,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Return the most relevant filing/payment deadline warning for one transaction year."""
    if tax_year is None:
        return None
    rows = tax_deadline_rows(country, [tax_year], today=today)
    if not rows:
        return None
    active = [row for row in rows if row["status"] in {"overdue", "due-soon"}]
    if active:
        active.sort(key=lambda r: (r["status"] != "due-soon", abs(r["days_until"])))
        return active[0]
    future = [row for row in rows if row["days_until"] >= 0]
    if future:
        return future[0]
    return rows[-1]


def tax_advice_cards(
    df: pd.DataFrame,
    *,
    country: str | None = DEFAULT_TAX_COUNTRY,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Return accountant-style action cards with conservative, sourced estimates."""
    if df.empty:
        return []

    tax_country = normalize_tax_country(country)
    cards = [
        _self_transfer_advice_card(df, tax_country),
        _cost_basis_advice_card(df, tax_country),
        _polish_crypto_swap_advice_card(df, tax_country),
        _us_specific_lot_advice_card(df, tax_country),
    ]
    result = [card for card in cards if card is not None]
    result.sort(key=lambda card: (card["priority"], card["title"]))
    return result[:limit]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _base_advice_card(
    *,
    card_id: str,
    priority: int,
    title: str,
    badge: str,
    status_class: str,
    impact_label: str,
    estimated_tax_effect_display: str,
    action: str,
    why: str,
    calculation: str,
    evidence: list[str],
    source_label: str,
    source_url: str,
) -> dict[str, Any]:
    return {
        "id": card_id,
        "priority": priority,
        "title": title,
        "badge": badge,
        "status_class": status_class,
        "impact_label": impact_label,
        "estimated_tax_effect_display": estimated_tax_effect_display,
        "action": action,
        "why": why,
        "calculation": calculation,
        "evidence": evidence,
        "source_label": source_label,
        "source_url": source_url,
    }


def _self_transfer_advice_card(df: pd.DataFrame, tax_country: str) -> dict[str, Any] | None:
    amount = Decimal("0")
    count = 0
    for _, row in df.iterrows():
        if not _row_is_advice_candidate(row):
            continue
        net = _safe_decimal(row.get("native_net_sol"))
        if net <= 0:
            continue
        if not (_is_possible_internal_transfer(row) or _is_source_unknown(row)):
            continue
        amount += net
        count += 1
    if count == 0:
        return None

    effect_display, calculation = _advice_tax_effect(amount, tax_country)
    if tax_country == "US":
        return _base_advice_card(
            card_id="confirm_self_transfers",
            priority=10,
            title="Confirm own-wallet transfers first",
            badge="Avoid overstatement",
            status_class="warning",
            impact_label="Possible false-tax exposure",
            estimated_tax_effect_display=effect_display,
            action=(
                f"Confirm or reject {count} incoming transfer{'s' if count != 1 else ''} before treating "
                "the funds as income or sale proceeds."
            ),
            why=(
                "IRS virtual-currency FAQs say transfers between wallets/accounts owned by the same taxpayer "
                "are non-taxable. This is usually the fastest accountant win because it removes false income."
            ),
            calculation=calculation,
            evidence=[f"{_fmt(amount)} SOL of incoming transfers still need ownership/source labels."],
            source_label="IRS virtual currency FAQ Q38",
            source_url=(
                "https://www.irs.gov/individuals/international-taxpayers/"
                "frequently-asked-questions-on-virtual-currency-transactions"
            ),
        )

    return _base_advice_card(
        card_id="confirm_self_transfers",
        priority=10,
        title="Najpierw potwierdz wlasne transfery",
        badge="Ryzyko nadplaty",
        status_class="warning",
        impact_label="Szacowany efekt przed review",
        estimated_tax_effect_display=effect_display,
        action=(
            f"Potwierdz lub odrzuc {count} przychodzacych transfer{'ow' if count != 1 else ''}, zanim "
            "oznaczysz je jako przychod, sprzedaz albo koszt."
        ),
        why=(
            "W polskim PIT-38 kluczowe jest ustalenie, czy doszlo do odplatnego zbycia. Wlasny transfer "
            "portfel-portfel nie powinien sztucznie powiekszac przychodow ani kosztow."
        ),
        calculation=calculation,
        evidence=[f"{_fmt(amount)} SOL przychodzacych transferow nadal wymaga etykiety zrodla/wlasnosci."],
        source_label="podatki.gov.pl - zbycie kryptowalut",
        source_url=(
            "https://www.podatki.gov.pl/podatki-osobiste/pit/informacje-podstawowe/"
            "co-jest-opodatkowane/zbycie-kryptowalut/"
        ),
    )


def _cost_basis_advice_card(df: pd.DataFrame, tax_country: str) -> dict[str, Any] | None:
    amount = Decimal("0")
    fees = Decimal("0")
    count = 0
    for _, row in df.iterrows():
        if not _row_is_advice_candidate(row):
            continue
        case = _classify(row)
        if case not in {"swap", "nft_sold", "lp", "perp"}:
            continue
        amount += _advice_disposed_sol(row)
        if bool(row.get("fee_paid_by_wallet")):
            fees += _safe_decimal(row.get("fee_sol"))
        count += 1
    if count == 0 and fees == 0:
        return None

    basis_amount = amount + fees
    effect_display, calculation = _advice_tax_effect(basis_amount, tax_country)
    if tax_country == "PL":
        return _base_advice_card(
            card_id="document_pit38_costs",
            priority=20,
            title="Udokumentuj koszty do PIT-38",
            badge="Mozliwa oszczednosc / carryforward",
            status_class="warning",
            impact_label="Szacowany efekt kosztow",
            estimated_tax_effect_display=effect_display,
            action=(
                f"Zbierz faktury, historie gield, potwierdzenia zakupu i oplat dla "
                f"{count} transakcji przed eksportem PIT-38."
            ),
            why=(
                "Polskie przepisy pozwalaja wykazac udokumentowane koszty nabycia i zbycia walut wirtualnych. "
                "Jezeli koszty przewyzszaja przychod, niewykorzystana czesc przechodzi na kolejne lata."
            ),
            calculation=calculation,
            evidence=[
                f"{_fmt(amount)} SOL potencjalnej bazy/kosztu z transakcji wymagajacych review.",
                f"{_fmt(fees)} SOL oplat sieciowych do potwierdzenia przez ksiegowego.",
            ],
            source_label="podatki.gov.pl - koszty i stawka 19%",
            source_url=(
                "https://www.podatki.gov.pl/podatki-osobiste/pit/informacje-podstawowe/"
                "co-jest-opodatkowane/zbycie-kryptowalut/"
            ),
        )

    return _base_advice_card(
        card_id="document_cost_basis",
        priority=20,
        title="Add cost basis before filing",
        badge="Estimated tax reduction",
        status_class="warning",
        impact_label="Potential basis effect",
        estimated_tax_effect_display=effect_display,
        action=(
            f"Attach acquisition lots, USD FMV, fees and timestamps for {count} disposal candidate"
            f"{'s' if count != 1 else ''} before exporting Form 8949."
        ),
        why=(
            "For US capital assets, confirmed basis and sale expenses reduce gain or increase a capital loss. "
            "Without lot records, the result can default to FIFO-style assumptions and overstate tax."
        ),
        calculation=calculation,
        evidence=[
            f"{_fmt(amount)} SOL of detected disposal value needs basis support.",
            f"{_fmt(fees)} SOL of fees should be tied to the relevant disposal or acquisition.",
        ],
        source_label="IRS Form 8949 instructions",
        source_url="https://www.irs.gov/instructions/i8949",
    )


def _polish_crypto_swap_advice_card(df: pd.DataFrame, tax_country: str) -> dict[str, Any] | None:
    if tax_country != "PL":
        return None
    amount = Decimal("0")
    count = 0
    for _, row in df.iterrows():
        if not _row_is_advice_candidate(row):
            continue
        if _classify(row) != "swap":
            continue
        amount += _advice_disposed_sol(row)
        count += 1
    if count == 0:
        return None

    effect_display, calculation = _advice_tax_effect(amount, tax_country)
    return _base_advice_card(
        card_id="pl_crypto_to_crypto_not_taxable",
        priority=30,
        title="Nie opodatkuj swapow krypto-krypto w PL",
        badge="Nadplata do unikniecia",
        status_class="confirmed",
        impact_label="Ryzyko blednego podatku",
        estimated_tax_effect_display=effect_display,
        action=(
            f"Oznacz {count} swap{'ow' if count != 1 else ''} krypto-krypto jako review/non-taxable dla PIT-38, "
            "a podatek licz dopiero przy wymianie na PLN/fiat, towar, usluge, prawo majatkowe albo przy zaplacie krypto."
        ),
        why=(
            "podatki.gov.pl wskazuje, ze wymiana pomiedzy walutami wirtualnymi nie podlega opodatkowaniu. "
            "To dobra rzecz do pokazania sedziom, bo app nie kopiuje slepo zasad z USA."
        ),
        calculation=calculation,
        evidence=[f"{count} swap{'y' if count != 1 else ''} wykryte jako potencjalnie do reklasyfikacji w PL."],
        source_label="podatki.gov.pl - wymiana krypto-krypto",
        source_url=(
            "https://www.podatki.gov.pl/podatki-osobiste/pit/informacje-podstawowe/"
            "co-jest-opodatkowane/zbycie-kryptowalut/"
        ),
    )


def _us_specific_lot_advice_card(df: pd.DataFrame, tax_country: str) -> dict[str, Any] | None:
    if tax_country != "US":
        return None
    count = 0
    amount = Decimal("0")
    for _, row in df.iterrows():
        if not _row_is_advice_candidate(row):
            continue
        if _classify(row) not in {"swap", "nft_sold", "lp", "perp"}:
            continue
        count += 1
        amount += _advice_disposed_sol(row)
    if count == 0:
        return None

    effect_display, calculation = _advice_tax_effect(amount, tax_country)
    return _base_advice_card(
        card_id="us_specific_identification",
        priority=40,
        title="Try specific-lot identification",
        badge="Planning lever",
        status_class="neutral",
        impact_label="Maximum lot-selection exposure",
        estimated_tax_effect_display=effect_display,
        action=(
            "Before finalizing FIFO, check whether the taxpayer can specifically identify higher-basis lots "
            "for the detected disposals."
        ),
        why=(
            "IRS FAQs allow specific identification when the taxpayer can substantiate the units, basis, FMV "
            "and sale/disposition details. If not, FIFO applies."
        ),
        calculation=calculation,
        evidence=[f"{count} disposal candidate{'s' if count != 1 else ''} may benefit from lot-level records."],
        source_label="IRS virtual currency FAQ Q39-Q41",
        source_url=(
            "https://www.irs.gov/individuals/international-taxpayers/"
            "frequently-asked-questions-on-virtual-currency-transactions"
        ),
    )


def _row_is_advice_candidate(row: pd.Series) -> bool:
    if _is_tax_excluded(row) or _is_confirmed_internal_transfer(row):
        return False
    return _safe_str(row.get("status"), "") == "succeeded"


def _advice_disposed_sol(row: pd.Series) -> Decimal:
    native_out = _safe_decimal(row.get("native_out_sol"))
    if native_out > 0:
        return native_out
    net = _safe_decimal(row.get("native_net_sol"))
    return net.copy_abs() if net < 0 else Decimal("0")


def _advice_tax_effect(amount_sol: Decimal, tax_country: str) -> tuple[str, str]:
    assumptions = _TAX_ADVICE_ASSUMPTIONS.get(tax_country, _TAX_ADVICE_ASSUMPTIONS["US"])
    if amount_sol <= 0:
        return (
            "Needs FMV",
            "No reliable amount yet: add fair market value, cost basis and fee data first.",
        )
    fiat_value = amount_sol * _safe_decimal(assumptions["sol_rate"])
    effect = fiat_value * _safe_decimal(assumptions["tax_rate"])
    currency = str(assumptions["currency"])
    return (
        _money(effect, currency),
        (
            f"Demo estimate: {_fmt(amount_sol)} SOL x {_money(_safe_decimal(assumptions['sol_rate']), currency)}/SOL "
            f"x {assumptions['rate_label']} = {_money(effect, currency)}. "
            "Replace demo rates with actual FMV before filing."
        ),
    )


def _money(value: Decimal, currency: str) -> str:
    rounded = value.quantize(Decimal("0.01"))
    rendered = f"{rounded:f}"
    if currency == "USD":
        return f"${rendered}"
    return f"{rendered} {currency}"


def _review_tier(row: pd.Series, category: str) -> int | None:
    """Return the priority tier (1–7) for the review queue, or None if not queued."""
    if category in _CATEGORY_TIER:
        return _CATEGORY_TIER[category]
    # Income, Expense, Transfer — only exceptional conditions enter the queue
    status = _safe_str(row.get("status"), "")
    if status == "failed":
        return 5
    net = _safe_decimal(row.get("native_net_sol"))
    if net.copy_abs() > LARGE_FLOW_THRESHOLD:
        return 6
    if _is_source_unknown(row):
        return 7
    return None


def _category_label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, category)


def _case_label(case: str) -> str:
    return _CASE_LABELS.get(case, case.replace("_", " ").title())


def _tax_review_label(row: pd.Series, category: str, tier: int, base_label: str) -> str:
    """Backward-compatible wrapper returning the tax-specific review reason."""
    case = _classify(row)
    return _tax_review_detail(row, case, category, tier, base_label, DEFAULT_TAX_COUNTRY)["review_reason"]


def _tax_review_detail(
    row: pd.Series,
    case: str,
    category: str,
    tier: int,
    base_label: str,
    country: str,
) -> dict[str, Any]:
    """Return user-facing tax review copy and traceability fields for one queued row."""
    tax_country = normalize_tax_country(country)
    status = _safe_str(row.get("status"), "")
    if status == "failed":
        return _detail(
            row,
            category,
            tax_country,
            review_reason="Failed transaction",
            rule_id="failed_transaction_fee",
            suggested_tax_action=(
                "Confirm that no asset balance changed, then record any network fee paid by this wallet."
            ),
            missing_information=[
                "Whether the fee was paid by this wallet.",
                "Whether the intended action later succeeded in a separate transaction.",
            ],
            tax_accounting_note=(
                "A failed transaction usually does not change asset balances, but a network fee may still "
                "have been paid and may need to be recorded."
            ),
        )

    if category == "Unknown / Needs review" or case == "unknown":
        return _detail(
            row,
            category,
            tax_country,
            review_reason="Unknown program",
            rule_id="unknown_program",
            suggested_tax_action=(
                "Open the raw transaction, identify the program and purpose, then assign the correct treatment."
            ),
            missing_information=[
                "Recognized program name and transaction purpose.",
                "Whether this moved assets, opened a position, closed a position, or only paid a fee.",
            ],
            tax_accounting_note=(
                "The program was not recognized, so the classification should not be trusted without "
                "manual review."
            ),
        )

    if case == "swap":
        return _trade_detail(
            row,
            category,
            tax_country,
            review_reason="Swap / trade needs cost-basis review",
            rule_id="swap_trade_cost_basis",
        )
    if case in {"nft_bought", "nft_sold"}:
        return _trade_detail(
            row,
            category,
            tax_country,
            review_reason="NFT transaction needs cost-basis review",
            rule_id="nft_cost_basis",
            note=(
                "NFT purchases and sales can require cost basis, sale value, fees, and timestamp before "
                "gain or loss can be reviewed."
            ),
        )
    if case == "lp":
        return _trade_detail(
            row,
            category,
            tax_country,
            review_reason="Liquidity pool activity needs review",
            rule_id="lp_cost_basis",
            note=(
                "LP deposits or withdrawals can represent asset disposals, receipts, fees, or position changes; "
                "cost basis and pool-token treatment may be needed."
            ),
        )
    if case == "perp":
        return _trade_detail(
            row,
            category,
            tax_country,
            review_reason="Perpetual trade needs PnL review",
            rule_id="perp_pnl_review",
            missing_information=[
                "Opening and closing timestamps.",
                "Realized PnL, funding, fees, settlement asset, and position size.",
            ],
            note=(
                "Perpetual trades may require realized PnL, funding, fees, price, and timestamp details "
                "before accounting treatment is reliable."
            ),
        )
    if case == "airdrop":
        return _detail(
            row,
            category,
            tax_country,
            review_reason="Airdrop income treatment may need review",
            rule_id="airdrop_income_review",
            suggested_tax_action=(
                "Record the asset received, timestamp, and fair market value at receipt before classifying it."
            ),
            missing_information=[
                "Fair market value at the time received.",
                "Jurisdiction-specific treatment and whether the wallet had control of the asset.",
            ],
            tax_accounting_note=(
                "An airdrop may be income depending on jurisdiction and value at the time it was received."
            ),
        )
    if case == "staking_withdrawal":
        return _detail(
            row,
            category,
            tax_country,
            review_reason="Staking withdrawal source needs review",
            rule_id="staking_withdrawal_principal_reward",
            suggested_tax_action=(
                "Split the withdrawal into original principal, reward, or a mix of both before using totals."
            ),
            missing_information=[
                "How much of the withdrawal was original principal.",
                "How much, if any, was staking reward and its value when credited.",
            ],
            tax_accounting_note=(
                "The system cannot tell whether this staking withdrawal is principal, reward, or a mix of both."
            ),
        )
    if tier == 6:
        net = _safe_decimal(row.get("native_net_sol"))
        direction = "incoming" if net > 0 else "outgoing"
        return _detail(
            row,
            category,
            tax_country,
            review_reason=f"Large {direction} transfer",
            rule_id="large_transfer_label",
            suggested_tax_action=(
                "Label the source, destination, and business or personal purpose of this large transfer."
            ),
            missing_information=[
                "Whether this was a self-transfer, exchange movement, payment, gift, loan, reward, or sale proceeds.",
                "Counterparty and supporting records.",
            ],
            tax_accounting_note=(
                "A large transfer is not automatically taxable, but it needs source and purpose labels before "
                "tax/accounting totals are reliable."
            ),
        )
    if tier == 7:
        return _detail(
            row,
            category,
            tax_country,
            review_reason="Source unknown",
            rule_id="source_unknown",
            suggested_tax_action=(
                "Label whether the funds came from your own wallet, an exchange, a third party, a reward, or another source."
            ),
            missing_information=[
                "Source of funds.",
                "Whether the transfer was a self-transfer, exchange deposit/withdrawal, payment, reward, or gift.",
            ],
            tax_accounting_note=(
                "Unknown source means this may need classification before it can be used in tax or accounting totals."
            ),
        )

    return _detail(
        row,
        category,
        tax_country,
        review_reason=base_label if base_label and base_label != "No action needed" else "Tax review needed",
        rule_id="tax_review_needed",
        suggested_tax_action="Review the transaction details and assign the correct tax/accounting treatment.",
        missing_information=["Manual classification decision."],
        tax_accounting_note="This item needs review before relying on it for tax/accounting totals.",
    )


def _trade_detail(
    row: pd.Series,
    category: str,
    country: str,
    *,
    review_reason: str,
    rule_id: str,
    missing_information: list[str] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return _detail(
        row,
        category,
        country,
        review_reason=review_reason,
        rule_id=rule_id,
        suggested_tax_action=(
            "Add cost basis, disposal value, fees, and timestamp before using this event in tax totals."
        ),
        missing_information=missing_information or [
            "Cost basis of the asset disposed.",
            "Fair market value or proceeds, fee, and timestamp.",
        ],
        tax_accounting_note=note or (
            "Swaps and trades may require cost basis, acquisition price, disposal value, fees, and timestamp."
        ),
    )


def _detail(
    row: pd.Series,
    category: str,
    country: str,
    *,
    review_reason: str,
    rule_id: str,
    suggested_tax_action: str,
    missing_information: list[str],
    tax_accounting_note: str,
) -> dict[str, Any]:
    tax_country = normalize_tax_country(country)
    guidance = _country_tax_guidance(rule_id, tax_country)
    return {
        "review_reason": review_reason,
        "rule_id": rule_id,
        "suggested_tax_action": suggested_tax_action,
        "evidence": _review_evidence(row, category),
        "missing_information": missing_information,
        "tax_accounting_note": _localized_tax_note(rule_id, tax_accounting_note, tax_country),
        "tax_treatment": guidance["treatment"],
        "tax_due": guidance["tax_due"],
        "tax_calculation": guidance["calculation"],
        "tax_forms": guidance["forms"],
        "tax_rate_note": guidance["rate_note"],
        "tax_country": tax_country,
        "tax_country_label": tax_country_profile(tax_country)["label"],
        "tax_deadline_notice": tax_deadline_notice(tax_country, _row_year(row)),
        "transaction_warning": _transaction_warning(row, rule_id),
    }


def _localized_tax_note(rule_id: str, base_note: str, country: str) -> str:
    if normalize_tax_country(country) not in {"US", "PL"}:
        return base_note
    guidance = _country_tax_guidance(rule_id, country)
    return (
        f"{base_note} {guidance['treatment']} {guidance['tax_due']} "
        f"Calculation: {guidance['calculation']} Forms to discuss: {guidance['forms']} "
        f"Rate note: {guidance['rate_note']}"
    )


def _country_tax_guidance(rule_id: str, country: str) -> dict[str, str]:
    tax_country = normalize_tax_country(country)
    if tax_country == "US":
        return _US_TAX_GUIDANCE_BY_RULE.get(rule_id, _US_TAX_GUIDANCE_BY_RULE["tax_review_needed"])
    if tax_country == "PL":
        return _PL_TAX_GUIDANCE_BY_RULE.get(rule_id, _PL_TAX_GUIDANCE_BY_RULE["tax_review_needed"])
    fallback = _US_TAX_GUIDANCE_BY_RULE["tax_review_needed"]
    return {
        "treatment": "No country-specific tax profile is available yet.",
        "tax_due": "Use this as a classification checklist only.",
        "calculation": fallback["calculation"],
        "forms": "Ask a local professional which forms apply.",
        "rate_note": "No country-specific rate can be shown.",
    }


def _review_evidence(row: pd.Series, category: str) -> list[str]:
    evidence = [
        f"Status: {_safe_str(row.get('status'), 'unknown') or 'unknown'}.",
        f"Likely group: {_category_label(category)}.",
        f"SOL net change: {_fmt(_safe_decimal(row.get('native_net_sol')), signed=True)} SOL.",
    ]
    fee = _safe_decimal(row.get("fee_sol"))
    if fee:
        evidence.append(f"Network fee: {_fmt(fee)} SOL.")
    source = _safe_str(row.get("source"), "")
    protocol = _safe_str(row.get("tag_protocol"), "")
    if source:
        evidence.append(f"Source: {source}.")
    if protocol:
        evidence.append(f"Detected protocol: {protocol}.")
    assets = _safe_str(row.get("tag_amount_display"), "") or _safe_str(row.get("tag_assets"), "")
    if assets:
        evidence.append(f"Parsed assets: {assets}.")
    return evidence


def _transaction_warning(row: pd.Series, rule_id: str) -> dict[str, str] | None:
    fee = _safe_decimal(row.get("fee_sol"))
    net = _safe_decimal(row.get("native_transfer_net_sol"))
    if net == 0 and row.get("native_transfer_net_sol") is None:
        net = _safe_decimal(row.get("native_net_sol"))
    token_flows = row.get("token_flow_details")
    has_token_movement = False
    if isinstance(token_flows, list):
        has_token_movement = any(
            isinstance(flow, dict) and _safe_decimal(flow.get("net")) != 0
            for flow in token_flows
        )
    no_asset_movement = net == 0 and not has_token_movement
    status = _safe_str(row.get("status"), "")
    if rule_id == "unknown_program" and fee > 0 and no_asset_movement:
        return {
            "ack_id": _warning_ack_id(row, rule_id),
            "level": "high",
            "title": "Fee-only unknown program interaction",
            "message": (
                "This is unusual: the wallet paid a network fee, but the parser found no SOL or token movement. "
                "Open the raw transaction before assuming it has no tax/accounting impact."
            ),
        }
    if status == "failed" and fee > 0:
        return {
            "ack_id": _warning_ack_id(row, rule_id),
            "level": "medium",
            "title": "Failed transaction with fee paid",
            "message": (
                "The intended action failed, but the wallet may still have paid a network fee. "
                "Record the fee and check whether the action later succeeded in another transaction."
            ),
        }
    return None


def _warning_ack_id(row: pd.Series, rule_id: str) -> str:
    sig = _safe_str(row.get("signature"), "")
    return f"warning:{sig or 'unknown'}:{rule_id}"


def _review_count(df: pd.DataFrame) -> int:
    """Count review-queue candidates without building the full queue (no explain_row calls)."""
    count = 0
    for _, row in df.iterrows():
        if _is_tax_excluded(row) or _is_confirmed_internal_transfer(row):
            continue
        custom_status = _safe_str(row.get("tax_review_status"), "")
        if custom_status in {"needs_client_answer", "needs_accountant_review", "blocked_missing_data"}:
            count += 1
            continue
        if custom_status in {"resolved", "informational", "excluded"}:
            continue
        if _is_possible_internal_transfer(row):
            count += 1
            continue
        cat = tax_category(row)
        if _review_tier(row, cat) is not None:
            count += 1
    return count


def _row_date(row: pd.Series) -> str:
    ts = row.get("timestamp_unix")
    if ts is None:
        return "Unknown"
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d")
    except (OSError, TypeError, ValueError):
        return "Unknown"


def _row_year(row: pd.Series) -> int | None:
    ts = row.get("timestamp_unix")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).year
    except (OSError, TypeError, ValueError):
        return None


def _fmt(d: Decimal, *, signed: bool = False) -> str:
    if not d:
        return "+0" if signed else "0"
    try:
        s = f"{d:+f}" if signed else f"{d:f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s
    except Exception:
        return "+0" if signed else "0"


# ---------------------------------------------------------------------------
# Public API — aggregation
# ---------------------------------------------------------------------------


def tax_summary(df: pd.DataFrame, address: str) -> dict[str, Any]:
    """Return aggregate tax metrics over the full (unfiltered) DataFrame."""
    zero = Decimal("0")
    if df.empty:
        return {
            "total_income_sol": zero,
            "total_expense_sol": zero,
            "total_fees_sol": zero,
            "net_sol": zero,
            "taxable_count": 0,
            "review_count": 0,
        }

    income = zero
    expense = zero
    fees = zero
    taxable_count = 0

    for _, row in df.iterrows():
        if _is_tax_excluded(row):
            continue
        if bool(row.get("fee_paid_by_wallet")):
            fees += _safe_decimal(row.get("fee_sol"))
        if _skip_tax_amount_totals(row):
            continue
        if _safe_str(row.get("status"), "") != "succeeded":
            continue
        if _is_confirmed_internal_transfer(row) or _is_possible_internal_transfer(row):
            continue
        cat = tax_category(row)
        net = _safe_decimal(row.get("native_net_sol"))
        if cat == "Income":
            income += net
        elif cat == "Expense":
            expense += net.copy_abs()
        if cat in TAXABLE_CATEGORIES:
            taxable_count += 1

    return {
        "total_income_sol": income,
        "total_expense_sol": expense,
        "total_fees_sol": fees,
        "net_sol": income - expense,
        "taxable_count": taxable_count,
        "review_count": _review_count(df),
    }


def tax_review_queue(
    df: pd.DataFrame,
    *,
    limit: int = 100,
    country: str | None = DEFAULT_TAX_COUNTRY,
) -> list[dict]:
    """Return priority-sorted review queue items, each enriched with explain_row() output."""
    from .explainer import explain_row

    if df.empty:
        return []

    tax_country = normalize_tax_country(country)
    qualified: list[tuple[int, int, dict]] = []

    for _, row in df.iterrows():
        if _is_tax_excluded(row) or _is_confirmed_internal_transfer(row):
            continue
        custom_status = _safe_str(row.get("tax_review_status"), "")
        if custom_status in {"resolved", "informational", "excluded", "ready"}:
            continue
        if _is_possible_internal_transfer(row):
            item = _possible_internal_review_item(row, tax_country)
            ts = int(row.get("timestamp_unix") or 0)
            qualified.append((1, -ts, item))
            continue
        case = _classify(row)
        cat = _CASE_TO_CATEGORY.get(case, "Unknown / Needs review")
        tier = _review_tier(row, cat)
        if tier is None:
            continue

        exp = explain_row(row)
        review = _tax_review_detail(row, case, cat, tier, exp.review_label, tax_country)
        ts = int(row.get("timestamp_unix") or 0)
        sig = _safe_str(row.get("signature"), "")

        item = {
            "date": _row_date(row),
            "signature": sig,
            "sig_short": (sig[:8] + "…") if len(sig) > 8 else sig,
            "account_address": _safe_str(row.get("account_address"), ""),
            "explorer_url": f"https://explorer.solana.com/tx/{sig}" if sig else "",
            "category": cat,
            "category_label": _category_label(cat),
            "case_key": case,
            "detected_pattern": _case_label(case),
            "sol_net": _fmt(_safe_decimal(row.get("native_net_sol")), signed=True),
            "short_explanation": exp.short_explanation,
            "known_facts": exp.known_facts,
            "unknown_facts": exp.unknown_facts,
            "suggested_actions": [review["suggested_tax_action"]],
            "expanded_explanation": exp.expanded_explanation,
            "confidence_percent": exp.confidence_percent,
            "review_label": exp.review_label,
            "review_reason": review["review_reason"],
            "rule_id": review["rule_id"],
            "suggested_tax_action": review["suggested_tax_action"],
            "evidence": review["evidence"],
            "missing_information": review["missing_information"],
            "tax_accounting_note": review["tax_accounting_note"],
            "tax_treatment": review["tax_treatment"],
            "tax_due": review["tax_due"],
            "tax_calculation": review["tax_calculation"],
            "tax_forms": review["tax_forms"],
            "tax_rate_note": review["tax_rate_note"],
            "tax_country": review["tax_country"],
            "tax_country_label": review["tax_country_label"],
            "tax_deadline_notice": review["tax_deadline_notice"],
            "transaction_warning": review["transaction_warning"],
            "status": _safe_str(row.get("status"), ""),
            "source": _safe_str(row.get("source"), ""),
            "tag_protocol": _safe_str(row.get("tag_protocol"), ""),
            "tier": tier,
        }
        qualified.append((tier, -ts, item))

    qualified.sort(key=lambda x: (x[0], x[1]))
    return [item for _, _, item in qualified[:limit]]


def tax_classification_rows(df: pd.DataFrame) -> list[dict]:
    """Return one dict per tax category present, sorted by count (Unknown always last)."""
    if df.empty:
        return []

    buckets: dict[str, dict] = {}
    for _, row in df.iterrows():
        if _is_tax_excluded(row) or _is_confirmed_internal_transfer(row) or _is_possible_internal_transfer(row):
            continue
        case = _classify(row)
        cat = _CASE_TO_CATEGORY.get(case, "Unknown / Needs review")
        if cat not in buckets:
            buckets[cat] = {"count": 0, "sol_net": Decimal("0"), "case_keys": set()}
        buckets[cat]["count"] += 1
        buckets[cat]["sol_net"] += _safe_decimal(row.get("native_net_sol"))
        buckets[cat]["case_keys"].add(case)

    unknown_bucket = buckets.pop("Unknown / Needs review", None)

    rows = [
        {
            "category": cat,
            "category_label": _category_label(cat),
            "case_keys": sorted(data["case_keys"]),
            "case_labels": sorted(_case_label(case) for case in data["case_keys"]),
            "count": data["count"],
            "sol_net": _fmt(data["sol_net"], signed=True),
            "flagged": cat in REVIEW_REQUIRED_CATEGORIES,
        }
        for cat, data in buckets.items()
    ]
    rows.sort(key=lambda r: -r["count"])

    if unknown_bucket is not None:
        rows.append({
            "category": "Unknown / Needs review",
            "category_label": _category_label("Unknown / Needs review"),
            "case_keys": sorted(unknown_bucket["case_keys"]),
            "case_labels": sorted(_case_label(case) for case in unknown_bucket["case_keys"]),
            "count": unknown_bucket["count"],
            "sol_net": _fmt(unknown_bucket["sol_net"], signed=True),
            "flagged": True,
        })

    return rows


def yearly_summary(df: pd.DataFrame) -> list[dict]:
    """Return per-year tax aggregates, sorted year descending."""
    if df.empty:
        return []

    years: dict[int, dict] = {}
    for _, row in df.iterrows():
        if _is_tax_excluded(row):
            continue
        ts = row.get("timestamp_unix")
        if ts is None:
            continue
        try:
            year = datetime.fromtimestamp(int(ts), timezone.utc).year
        except (OSError, TypeError, ValueError):
            continue
        if _safe_str(row.get("status"), "") != "succeeded":
            continue

        skip_amount_totals = _skip_tax_amount_totals(row)
        is_internal_or_pending = _is_confirmed_internal_transfer(row) or _is_possible_internal_transfer(row)
        cat = tax_category(row)
        net = _safe_decimal(row.get("native_net_sol"))

        if year not in years:
            years[year] = {
                "year": year,
                "_income": Decimal("0"),
                "_expense": Decimal("0"),
                "_fees": Decimal("0"),
                "taxable_count": 0,
            }
        if cat == "Income" and not is_internal_or_pending and not skip_amount_totals:
            years[year]["_income"] += net
        elif cat == "Expense" and not is_internal_or_pending and not skip_amount_totals:
            years[year]["_expense"] += net.copy_abs()
        if cat in TAXABLE_CATEGORIES and not is_internal_or_pending and not skip_amount_totals:
            years[year]["taxable_count"] += 1
        if bool(row.get("fee_paid_by_wallet")):
            years[year]["_fees"] += _safe_decimal(row.get("fee_sol"))

    result = []
    for data in sorted(years.values(), key=lambda r: r["year"], reverse=True):
        result.append({
            "year": data["year"],
            "income_sol": _fmt(data["_income"], signed=True),
            "expense_sol": _fmt(data["_expense"]),
            "fees_sol": _fmt(data["_fees"]),
            "taxable_count": data["taxable_count"],
        })
    return result


_TAX_EXPORT_COLUMNS = [
    "date", "signature", "status", "tax_category", "case_key", "tag_type",
    "sol_net", "token_summary", "fee_sol", "is_potentially_taxable",
    "review_label", "notes",
]


def tax_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a flat DataFrame suitable for CSV export with full traceability columns."""
    from .explainer import explain_row

    if df.empty:
        return pd.DataFrame(columns=_TAX_EXPORT_COLUMNS)

    sorted_df = df.sort_values("timestamp_unix", ascending=False, kind="stable").reset_index(drop=True)
    rows = []
    for _, row in sorted_df.iterrows():
        if _is_tax_excluded(row):
            continue
        custom_category = _safe_str(row.get("tax_category"), "")
        custom_status = _safe_str(row.get("tax_review_status"), "")
        if custom_category and custom_category not in {"unknown"}:
            case = custom_category
            cat = custom_category.replace("_", " ").title()
            taxable_value = _custom_taxable_export_value(custom_category, custom_status)
        elif _is_confirmed_internal_transfer(row):
            case = "internal_transfer"
            cat = "Internal transfer"
            taxable_value = "no"
        elif _is_possible_internal_transfer(row):
            case = "possible_internal_transfer"
            cat = "Possible internal transfer"
            taxable_value = "review"
        else:
            case = _classify(row)
            cat = _CASE_TO_CATEGORY.get(case, "Unknown / Needs review")
            taxable_value = "yes" if cat in TAXABLE_CATEGORIES else "no"
        exp = explain_row(row)
        rows.append({
            "date": _row_date(row),
            "signature": _safe_str(row.get("signature"), ""),
            "status": _safe_str(row.get("status"), ""),
            "tax_category": cat,
            "case_key": case,
            "tag_type": _safe_str(row.get("tag_type"), ""),
            "sol_net": _fmt(_safe_decimal(row.get("native_net_sol")), signed=True),
            "token_summary": _safe_str(row.get("net_flow_summary"), ""),
            "fee_sol": _fmt(_safe_decimal(row.get("fee_sol"))),
            "is_potentially_taxable": taxable_value,
            "review_label": exp.review_label,
            "notes": exp.short_explanation[:200],
        })
    return pd.DataFrame(rows, columns=_TAX_EXPORT_COLUMNS)


def _custom_taxable_export_value(category: str, status: str) -> str:
    if status in {"needs_client_answer", "needs_accountant_review", "blocked_missing_data"}:
        return "review"
    if category in {
        "internal_transfer",
        "transfer_from_exchange",
        "buy",
        "staking_deposit",
        "failed_fee_only",
    }:
        return "no"
    if category in {
        "sell",
        "swap_trade",
        "airdrop_reward",
        "staking_reward",
        "nft_sale",
        "payment_for_services",
    }:
        return "yes"
    return "review" if category in {"transfer_to_exchange", "defi_complex"} else "no"


def _is_tax_excluded(row: pd.Series) -> bool:
    return _safe_str(row.get("tax_scope"), "") in {"excluded", "watch_only"}


def _is_confirmed_internal_transfer(row: pd.Series) -> bool:
    return bool(row.get("is_internal_transfer"))


def _is_possible_internal_transfer(row: pd.Series) -> bool:
    return _safe_str(row.get("review_reason"), "") == "possible_internal_transfer"


def _skip_tax_amount_totals(row: pd.Series) -> bool:
    custom_category = _safe_str(row.get("tax_category"), "")
    custom_status = _safe_str(row.get("tax_review_status"), "")
    if custom_status in {
        "needs_client_answer",
        "needs_accountant_review",
        "blocked_missing_data",
        "informational",
        "excluded",
    }:
        return True
    return custom_category in {
        "internal_transfer",
        "transfer_from_exchange",
        "transfer_to_exchange",
        "staking_deposit",
        "failed_fee_only",
    }


def _possible_internal_review_item(row: pd.Series, tax_country: str) -> dict[str, Any]:
    from .explainer import explain_row

    exp = explain_row(row)
    sig = _safe_str(row.get("signature"), "")
    direction = "incoming" if _safe_decimal(row.get("native_net_sol")) > 0 else "outgoing"
    if direction == "incoming":
        action = (
            "Confirm whether this came from another wallet owned by the taxpayer before treating it as income."
        )
        note = (
            "This incoming transfer may be from another wallet owned by the taxpayer. "
            "Confirm ownership before treating as income."
        )
    else:
        action = "Confirm whether this is an internal transfer before assigning a tax treatment."
        note = (
            "This outgoing transfer may be an internal transfer. "
            "Do not classify as expense until confirmed."
        )
    return {
        "date": _row_date(row),
        "signature": sig,
        "sig_short": (sig[:8] + "…") if len(sig) > 8 else sig,
        "account_address": _safe_str(row.get("account_address"), ""),
        "explorer_url": f"https://explorer.solana.com/tx/{sig}" if sig else "",
        "category": "Transfer",
        "category_label": "Possible internal transfer",
        "case_key": "possible_internal_transfer",
        "detected_pattern": "Possible internal transfer",
        "sol_net": _fmt(_safe_decimal(row.get("native_net_sol")), signed=True),
        "short_explanation": exp.short_explanation,
        "known_facts": exp.known_facts,
        "unknown_facts": exp.unknown_facts,
        "suggested_actions": [action],
        "expanded_explanation": exp.expanded_explanation,
        "confidence_percent": exp.confidence_percent,
        "review_label": "Possible internal transfer",
        "review_reason": "possible_internal_transfer",
        "rule_id": "possible_internal_transfer",
        "suggested_tax_action": action,
        "evidence": _review_evidence(row, "Transfer"),
        "missing_information": [
            "Whether the sending and receiving wallets are both owned by this taxpayer.",
            "Whether the transfer match should be confirmed or rejected.",
        ],
        "tax_accounting_note": note,
        "tax_treatment": "Likely not taxable if confirmed as a self-transfer; needs review before final use.",
        "tax_due": "Do not calculate income, proceeds, or gain until ownership is confirmed.",
        "tax_calculation": "Confirm/reject the internal transfer match, then keep only the network fee in records if confirmed.",
        "tax_forms": "Usually no Form 8949 event for a confirmed self-transfer; keep support records.",
        "tax_rate_note": "No rate can be inferred until ownership and purpose are confirmed.",
        "tax_country": tax_country,
        "tax_country_label": tax_country_profile(tax_country)["label"],
        "tax_deadline_notice": tax_deadline_notice(tax_country, _row_year(row)),
        "transaction_warning": None,
        "status": _safe_str(row.get("status"), ""),
        "source": _safe_str(row.get("source"), ""),
        "tag_protocol": _safe_str(row.get("tag_protocol"), ""),
        "tier": 1,
    }


_YEARLY_EXPORT_COLUMNS = [
    "year", "income_sol", "expense_sol", "fees_sol", "potentially_taxable_count",
]


def tax_yearly_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return yearly_summary() as a flat DataFrame for CSV export."""
    if df.empty:
        return pd.DataFrame(columns=_YEARLY_EXPORT_COLUMNS)

    rows = [
        {
            "year": ys["year"],
            "income_sol": ys["income_sol"],
            "expense_sol": ys["expense_sol"],
            "fees_sol": ys["fees_sol"],
            "potentially_taxable_count": ys["taxable_count"],
        }
        for ys in yearly_summary(df)
    ]
    return pd.DataFrame(rows, columns=_YEARLY_EXPORT_COLUMNS)


__all__ = [
    "DEFAULT_TAX_COUNTRY",
    "LARGE_FLOW_THRESHOLD",
    "REVIEW_REQUIRED_CATEGORIES",
    "TAXABLE_CATEGORIES",
    "TAX_DISCLAIMER",
    "normalize_tax_country",
    "tax_advice_cards",
    "tax_category",
    "tax_classification_rows",
    "tax_country_options",
    "tax_country_profile",
    "tax_export_frame",
    "tax_review_queue",
    "tax_summary",
    "tax_yearly_export_frame",
    "yearly_summary",
]
