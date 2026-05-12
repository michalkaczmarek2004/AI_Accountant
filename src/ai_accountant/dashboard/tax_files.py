"""Tax file storage and accounting helpers for the dashboard."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from ..addresses import validate_address
from ..dataframe import DATAFRAME_COLUMNS
from ..report import _format_decimal, _short
from . import cache as cache_mod

STORE_SCHEMA_VERSION = 1
STORE_DIRNAME = "_tax_files"
STORE_FILENAME = "tax_files.json"

ACCOUNT_TYPE_SOLANA_WALLET = "solana_wallet"
ACCOUNT_TYPES = (ACCOUNT_TYPE_SOLANA_WALLET,)

OWNERSHIP_OWNED = "owned"
OWNERSHIP_EXTERNAL = "external"
OWNERSHIP_WATCH_ONLY = "watch_only"
OWNERSHIP_UNKNOWN = "unknown"
OWNERSHIP_STATUSES = (
    OWNERSHIP_OWNED,
    OWNERSHIP_EXTERNAL,
    OWNERSHIP_WATCH_ONLY,
    OWNERSHIP_UNKNOWN,
)

MATCH_SUGGESTED = "suggested"
MATCH_CONFIRMED = "confirmed"
MATCH_REJECTED = "rejected"
MATCH_STATUSES = (MATCH_SUGGESTED, MATCH_CONFIRMED, MATCH_REJECTED)

TAX_REVIEW_READY = "ready"
TAX_REVIEW_NEEDS_CLIENT_ANSWER = "needs_client_answer"
TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW = "needs_accountant_review"
TAX_REVIEW_BLOCKED_MISSING_DATA = "blocked_missing_data"
TAX_REVIEW_RESOLVED = "resolved"
TAX_REVIEW_INFORMATIONAL = "informational"
TAX_REVIEW_EXCLUDED = "excluded"
TAX_REVIEW_STATUSES = (
    TAX_REVIEW_READY,
    TAX_REVIEW_NEEDS_CLIENT_ANSWER,
    TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
    TAX_REVIEW_BLOCKED_MISSING_DATA,
    TAX_REVIEW_RESOLVED,
    TAX_REVIEW_INFORMATIONAL,
    TAX_REVIEW_EXCLUDED,
)

REASON_UNKNOWN_SOURCE = "unknown_source"
REASON_UNKNOWN_DESTINATION = "unknown_destination"
REASON_POSSIBLE_INTERNAL_TRANSFER = "possible_internal_transfer"
REASON_MISSING_COST_BASIS = "missing_cost_basis"
REASON_MISSING_FMV = "missing_fmv"
REASON_COMPLEX_DEFI = "complex_defi"
REASON_FAILED_TRANSACTION = "failed_transaction"
REASON_WATCH_ONLY_EXCLUDED = "watch_only_excluded"
REASON_OWNERSHIP_UNKNOWN = "ownership_unknown"
REASON_FEE_ONLY = "fee_only"
REVIEW_REASONS = (
    REASON_UNKNOWN_SOURCE,
    REASON_UNKNOWN_DESTINATION,
    REASON_POSSIBLE_INTERNAL_TRANSFER,
    REASON_MISSING_COST_BASIS,
    REASON_MISSING_FMV,
    REASON_COMPLEX_DEFI,
    REASON_FAILED_TRANSACTION,
    REASON_WATCH_ONLY_EXCLUDED,
    REASON_OWNERSHIP_UNKNOWN,
    REASON_FEE_ONLY,
)

TAX_CATEGORY_INTERNAL_TRANSFER = "internal_transfer"
TAX_CATEGORY_TRANSFER_FROM_EXCHANGE = "transfer_from_exchange"
TAX_CATEGORY_TRANSFER_TO_EXCHANGE = "transfer_to_exchange"
TAX_CATEGORY_BUY = "buy"
TAX_CATEGORY_SELL = "sell"
TAX_CATEGORY_SWAP_TRADE = "swap_trade"
TAX_CATEGORY_AIRDROP_REWARD = "airdrop_reward"
TAX_CATEGORY_STAKING_REWARD = "staking_reward"
TAX_CATEGORY_NFT_SALE = "nft_sale"
TAX_CATEGORY_NFT_PURCHASE = "nft_purchase"
TAX_CATEGORY_STAKING_DEPOSIT = "staking_deposit"
TAX_CATEGORY_FAILED_FEE_ONLY = "failed_fee_only"
TAX_CATEGORY_GIFT = "gift"
TAX_CATEGORY_DONATION = "donation"
TAX_CATEGORY_PAYMENT_FOR_SERVICES = "payment_for_services"
TAX_CATEGORY_DEFI_COMPLEX = "defi_complex"
TAX_CATEGORY_UNKNOWN = "unknown"
TAX_CATEGORIES = (
    TAX_CATEGORY_INTERNAL_TRANSFER,
    TAX_CATEGORY_TRANSFER_FROM_EXCHANGE,
    TAX_CATEGORY_TRANSFER_TO_EXCHANGE,
    TAX_CATEGORY_BUY,
    TAX_CATEGORY_SELL,
    TAX_CATEGORY_SWAP_TRADE,
    TAX_CATEGORY_AIRDROP_REWARD,
    TAX_CATEGORY_STAKING_REWARD,
    TAX_CATEGORY_STAKING_DEPOSIT,
    TAX_CATEGORY_NFT_PURCHASE,
    TAX_CATEGORY_NFT_SALE,
    TAX_CATEGORY_FAILED_FEE_ONLY,
    TAX_CATEGORY_GIFT,
    TAX_CATEGORY_DONATION,
    TAX_CATEGORY_PAYMENT_FOR_SERVICES,
    TAX_CATEGORY_DEFI_COMPLEX,
    TAX_CATEGORY_UNKNOWN,
)

AUDIT_ACTOR_SYSTEM = "system"
AUDIT_ACTOR_CLIENT = "client"
AUDIT_ACTOR_ACCOUNTANT = "accountant"

INCOMING_CLIENT_ANSWER_OPTIONS = (
    ("own_wallet", "Transfer from my own wallet"),
    ("exchange", "Transfer from exchange"),
    ("bought_crypto", "Bought crypto"),
    ("services_income", "Payment for services / income"),
    ("airdrop_reward", "Airdrop / reward"),
    ("gift", "Gift"),
    ("unknown", "I don't know"),
)

OUTGOING_CLIENT_ANSWER_OPTIONS = (
    ("own_wallet", "Transfer to my own wallet"),
    ("exchange", "Transfer to exchange"),
    ("sold_crypto", "Sold crypto"),
    ("payment_purchase", "Payment / purchase"),
    ("gift_donation", "Gift / donation"),
    ("bridge_defi", "Bridge / DeFi"),
    ("unknown", "I don't know"),
)

TAX_SCOPE_INCLUDED = "included"
TAX_SCOPE_EXCLUDED = "excluded"
TAX_SCOPE_WATCH_ONLY = "watch_only"

DEFAULT_TAX_COUNTRY = "United States"
DEFAULT_ENTITY_TYPE = "individual"
TEST_TAX_FILE_ID = "2025-us-crypto-tax-review"
TEST_TAX_FILE_NAME = "2025 US Crypto Tax Review"
TEST_CLIENT_CONFIRMATION_QUESTION = "Was this transfer from your own wallet?"
TEST_CLIENT_CONFIRMATION_ANSWER = "Transfer from my own wallet"
TEST_SELF_TRANSFER_VALUE_USD = Decimal("2800")
TEST_SELF_TRANSFER_FALSE_TAX_USD = Decimal("672")
TRANSFER_MATCH_WINDOW_SECONDS = 2 * 60 * 60
POLISH_CRYPTO_TAX_RATE = Decimal("0.19")
DEMO_SOL_PLN_RATE = Decimal("560")
DEMO_SOL_USD_RATE = Decimal("200")
US_DEMO_SHORT_TERM_CAPITAL_RATE = Decimal("0.24")
TAX_LOSS_HARVESTING_MIN_LOSS_PLN = Decimal("100")
TAX_LOSS_HARVESTING_MIN_LOSS_USD = Decimal("50")
TAX_LOSS_HARVESTING_ASSUMPTIONS_PLN = {
    "SAMO": {
        "current_price_pln": Decimal("0.0068"),
        "market_date": "2025-12-15",
        "source": "Review market assumption.",
    },
}
TAX_LOSS_HARVESTING_ASSUMPTIONS_USD = {
    "SAMO": {
        "current_price_usd": Decimal("0.0024"),
        "market_date": "2025-12-15",
        "source": "Review market assumption.",
    },
}
POLISH_CRYPTO_TAX_SOURCE_URL = (
    "https://www.podatki.gov.pl/podatki-osobiste/pit/informacje-podstawowe/"
    "co-jest-opodatkowane/zbycie-kryptowalut/"
)
IRS_DIGITAL_ASSETS_SOURCE_URL = "https://www.irs.gov/businesses/small-businesses-self-employed/digital-assets"
IRS_TOPIC_409_SOURCE_URL = "https://www.irs.gov/taxtopics/tc409"
IRS_FORM_8949_SOURCE_URL = "https://www.irs.gov/instructions/i8949"

COST_BASIS_METHOD_FIFO = "FIFO"
COST_BASIS_CURRENCY = "USD"
COST_BASIS_ACCOUNTANT_NOTE = (
    "Cost basis tracking is preliminary. The app uses FIFO by default and flags missing acquisition lots, "
    "fees, and fair market values. Final treatment depends on the selected tax country, entity type, and "
    "accountant review."
)
ACCOUNTANT_CHECKLIST_NOTE = (
    "This checklist does not provide tax advice. It tracks whether the accounting workpaper has enough source "
    "data, classifications, cost basis, FMV values, and review notes to support a draft tax export."
)
LOSS_REVIEW_DISCLAIMER = (
    "This is not a trade recommendation or tax advice. The app only identifies unrealized loss candidates based "
    "on available wallet data and pricing assumptions. A qualified professional must review cost basis, FMV, "
    "legal/tax treatment, fees, liquidity, slippage, and re-entry risk before any action."
)
LOSS_REVIEW_ASSUMPTIONS_LIMITATIONS = (
    "This analysis is based on parsed Solana wallet activity, selected tax country, unresolved review items, "
    "and estimated pricing where real market data is unavailable. It does not confirm legal ownership, "
    "source of funds, final cost basis, fair market value, or final tax treatment."
)
DEMO_MANUAL_COST_BASIS_LOTS = (
    {
        "tax_file_id": "demo-tax-file-2025",
        "asset": "SOL",
        "acquired_on": "2025-01-05",
        "amount": Decimal("2.74995"),
        "cost_basis": Decimal("520.00"),
        "fees": Decimal("0.00"),
        "source": "manual lot",
    },
    {
        "tax_file_id": TEST_TAX_FILE_ID,
        "asset": "BONK",
        "acquired_on": "2023-12-01",
        "amount": Decimal("1000000"),
        "cost_basis": Decimal("100.00"),
        "fees": Decimal("0.00"),
        "source": "manual lot",
    },
)
DEMO_MANUAL_DISPOSAL_FMV_USD = {
    ("demo-tax-file-2025", "D" * 88, "SOL"): Decimal("72.50"),
}


@dataclass(frozen=True)
class TaxFile:
    id: str
    name: str
    tax_country: str
    tax_year: int
    entity_type: str
    created_at: str
    updated_at: str
    archived_at: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TaxFile:
        return cls(
            id=str(raw.get("id") or ""),
            name=str(raw.get("name") or "Untitled Tax File"),
            tax_country=str(raw.get("tax_country") or DEFAULT_TAX_COUNTRY),
            tax_year=int(raw.get("tax_year") or datetime.now(timezone.utc).year),
            entity_type=str(raw.get("entity_type") or DEFAULT_ENTITY_TYPE),
            created_at=str(raw.get("created_at") or _utc_now()),
            updated_at=str(raw.get("updated_at") or _utc_now()),
            archived_at=raw.get("archived_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Account:
    id: str
    tax_file_id: str
    account_type: str
    label: str
    address: str
    ownership_status: str
    source_status: str
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Account:
        ownership = _clean_choice(raw.get("ownership_status"), OWNERSHIP_STATUSES, OWNERSHIP_UNKNOWN)
        account_type = _clean_choice(raw.get("account_type"), ACCOUNT_TYPES, ACCOUNT_TYPE_SOLANA_WALLET)
        return cls(
            id=str(raw.get("id") or ""),
            tax_file_id=str(raw.get("tax_file_id") or ""),
            account_type=account_type,
            label=str(raw.get("label") or ""),
            address=str(raw.get("address") or ""),
            ownership_status=ownership,
            source_status=str(raw.get("source_status") or "active"),
            created_at=str(raw.get("created_at") or _utc_now()),
            updated_at=str(raw.get("updated_at") or _utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TransferMatch:
    id: str
    tax_file_id: str
    from_account_id: str
    to_account_id: str
    from_transaction_id: str
    to_transaction_id: str
    asset: str
    amount_sent: str
    amount_received: str
    fee_amount: str
    timestamp_diff_seconds: int
    confidence: str
    status: str
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TransferMatch:
        status = _clean_choice(raw.get("status"), MATCH_STATUSES, MATCH_SUGGESTED)
        return cls(
            id=str(raw.get("id") or ""),
            tax_file_id=str(raw.get("tax_file_id") or ""),
            from_account_id=str(raw.get("from_account_id") or ""),
            to_account_id=str(raw.get("to_account_id") or ""),
            from_transaction_id=str(raw.get("from_transaction_id") or ""),
            to_transaction_id=str(raw.get("to_transaction_id") or ""),
            asset=str(raw.get("asset") or ""),
            amount_sent=str(raw.get("amount_sent") or "0"),
            amount_received=str(raw.get("amount_received") or "0"),
            fee_amount=str(raw.get("fee_amount") or "0"),
            timestamp_diff_seconds=int(raw.get("timestamp_diff_seconds") or 0),
            confidence=str(raw.get("confidence") or "low"),
            status=status,
            created_at=str(raw.get("created_at") or _utc_now()),
            updated_at=str(raw.get("updated_at") or _utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClientAnswer:
    id: str
    tax_file_id: str
    review_item_id: str
    account_id: str
    transaction_id: str
    review_reason: str
    direction: str
    client_question: str
    client_answer: str
    tax_review_status: str
    tax_category: str
    client_answered_at: str
    resolved_at: str | None
    resolved_by: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ClientAnswer:
        status = _clean_choice(raw.get("tax_review_status"), TAX_REVIEW_STATUSES, TAX_REVIEW_RESOLVED)
        return cls(
            id=str(raw.get("id") or uuid4().hex),
            tax_file_id=str(raw.get("tax_file_id") or ""),
            review_item_id=str(raw.get("review_item_id") or ""),
            account_id=str(raw.get("account_id") or ""),
            transaction_id=str(raw.get("transaction_id") or ""),
            review_reason=str(raw.get("review_reason") or ""),
            direction=str(raw.get("direction") or ""),
            client_question=str(raw.get("client_question") or ""),
            client_answer=str(raw.get("client_answer") or ""),
            tax_review_status=status,
            tax_category=str(raw.get("tax_category") or TAX_CATEGORY_UNKNOWN),
            client_answered_at=str(raw.get("client_answered_at") or _utc_now()),
            resolved_at=raw.get("resolved_at"),
            resolved_by=raw.get("resolved_by"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TransactionOverride:
    id: str
    tax_file_id: str
    review_item_id: str
    account_id: str
    transaction_id: str
    review_reason: str
    tax_category: str
    original_tax_category: str
    tax_review_status: str
    accountant_note: str
    override_applied: bool
    override_by: str | None
    override_at: str | None
    tax_scope: str
    excluded_reason: str | None
    excluded_at: str | None
    resolved_at: str | None
    resolved_by: str | None
    reopened_at: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TransactionOverride:
        status = _clean_choice(raw.get("tax_review_status"), TAX_REVIEW_STATUSES, TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW)
        category = _clean_choice(raw.get("tax_category"), TAX_CATEGORIES, TAX_CATEGORY_UNKNOWN)
        scope = _clean_choice(raw.get("tax_scope"), (TAX_SCOPE_INCLUDED, TAX_SCOPE_EXCLUDED, TAX_SCOPE_WATCH_ONLY), TAX_SCOPE_INCLUDED)
        return cls(
            id=str(raw.get("id") or uuid4().hex),
            tax_file_id=str(raw.get("tax_file_id") or ""),
            review_item_id=str(raw.get("review_item_id") or ""),
            account_id=str(raw.get("account_id") or ""),
            transaction_id=str(raw.get("transaction_id") or ""),
            review_reason=str(raw.get("review_reason") or ""),
            tax_category=category,
            original_tax_category=str(raw.get("original_tax_category") or TAX_CATEGORY_UNKNOWN),
            tax_review_status=status,
            accountant_note=str(raw.get("accountant_note") or ""),
            override_applied=bool(raw.get("override_applied")),
            override_by=raw.get("override_by"),
            override_at=raw.get("override_at"),
            tax_scope=scope,
            excluded_reason=raw.get("excluded_reason"),
            excluded_at=raw.get("excluded_at"),
            resolved_at=raw.get("resolved_at"),
            resolved_by=raw.get("resolved_by"),
            reopened_at=raw.get("reopened_at"),
            created_at=str(raw.get("created_at") or _utc_now()),
            updated_at=str(raw.get("updated_at") or _utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuditLogEntry:
    id: str
    tax_file_id: str
    actor: str
    action_type: str
    target_type: str
    target_id: str
    target_label: str
    old_value_json: dict[str, Any]
    new_value_json: dict[str, Any]
    note: str
    created_at: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AuditLogEntry:
        old_value = raw.get("old_value_json")
        new_value = raw.get("new_value_json")
        return cls(
            id=str(raw.get("id") or uuid4().hex),
            tax_file_id=str(raw.get("tax_file_id") or ""),
            actor=str(raw.get("actor") or AUDIT_ACTOR_SYSTEM),
            action_type=str(raw.get("action_type") or ""),
            target_type=str(raw.get("target_type") or ""),
            target_id=str(raw.get("target_id") or ""),
            target_label=str(raw.get("target_label") or ""),
            old_value_json=old_value if isinstance(old_value, dict) else {},
            new_value_json=new_value if isinstance(new_value, dict) else {},
            note=str(raw.get("note") or ""),
            created_at=str(raw.get("created_at") or _utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _TransferCandidate:
    account: Account
    signature: str
    timestamp_unix: int
    direction: str
    asset: str
    amount: Decimal
    fee_amount: Decimal
    counterparty: str
    row_key: str


class TaxFileStore:
    """Small JSON document store colocated with the wallet cache."""

    def __init__(self, cache_root: Path) -> None:
        self.cache_root = Path(cache_root)
        self.path = self.cache_root / STORE_DIRNAME / STORE_FILENAME

    def list_tax_files(self, *, include_archived: bool = False) -> list[TaxFile]:
        files = [TaxFile.from_dict(raw) for raw in self._payload().get("tax_files", [])]
        if not include_archived:
            files = [tax_file for tax_file in files if not tax_file.archived_at]
        return sorted(files, key=lambda f: (f.tax_year, f.updated_at, f.name), reverse=True)

    def get_tax_file(self, tax_file_id: str) -> TaxFile | None:
        for tax_file in self.list_tax_files(include_archived=True):
            if tax_file.id == tax_file_id:
                return tax_file
        return None

    def create_tax_file(
        self,
        *,
        name: str,
        tax_year: int | str,
        tax_country: str | None = DEFAULT_TAX_COUNTRY,
        entity_type: str | None = DEFAULT_ENTITY_TYPE,
        tax_file_id: str | None = None,
    ) -> TaxFile:
        now = _utc_now()
        tax_file = TaxFile(
            id=tax_file_id or uuid4().hex,
            name=(name or "Untitled Tax File").strip(),
            tax_country=(tax_country or DEFAULT_TAX_COUNTRY).strip() or DEFAULT_TAX_COUNTRY,
            tax_year=_clean_tax_year(tax_year),
            entity_type=(entity_type or DEFAULT_ENTITY_TYPE).strip() or DEFAULT_ENTITY_TYPE,
            created_at=now,
            updated_at=now,
        )
        payload = self._payload()
        existing = [raw for raw in payload["tax_files"] if raw.get("id") != tax_file.id]
        payload["tax_files"] = existing + [tax_file.to_dict()]
        self._append_audit_entry(
            payload,
            tax_file_id=tax_file.id,
            actor=AUDIT_ACTOR_SYSTEM,
            action_type="tax_file_created",
            target_type="tax_file",
            target_id=tax_file.id,
            target_label=tax_file.name,
            old_value={},
            new_value=tax_file.to_dict(),
            note="Tax File created.",
        )
        self._write(payload)
        return tax_file

    def list_accounts(self, tax_file_id: str | None = None) -> list[Account]:
        accounts = [Account.from_dict(raw) for raw in self._payload().get("accounts", [])]
        if tax_file_id is not None:
            accounts = [account for account in accounts if account.tax_file_id == tax_file_id]
        return sorted(accounts, key=lambda a: (a.label.lower(), a.address))

    def get_account(self, account_id: str) -> Account | None:
        for account in self.list_accounts():
            if account.id == account_id:
                return account
        return None

    def add_account(
        self,
        *,
        tax_file_id: str,
        address: str,
        label: str | None = None,
        ownership_status: str | None = OWNERSHIP_OWNED,
        account_type: str = ACCOUNT_TYPE_SOLANA_WALLET,
    ) -> tuple[Account, bool]:
        if self.get_tax_file(tax_file_id) is None:
            raise KeyError(tax_file_id)
        validated = validate_address(address)
        account_type = _clean_choice(account_type, ACCOUNT_TYPES, ACCOUNT_TYPE_SOLANA_WALLET)
        ownership = _clean_choice(ownership_status, OWNERSHIP_STATUSES, OWNERSHIP_UNKNOWN)
        existing = self.find_account(tax_file_id=tax_file_id, address=validated)
        if existing is not None:
            return existing, False

        now = _utc_now()
        account = Account(
            id=uuid4().hex,
            tax_file_id=tax_file_id,
            account_type=account_type,
            label=(label or _short(validated, 6)).strip() or _short(validated, 6),
            address=validated,
            ownership_status=ownership,
            source_status="active",
            created_at=now,
            updated_at=now,
        )
        payload = self._payload()
        payload["accounts"].append(account.to_dict())
        self._touch_tax_file(payload, tax_file_id)
        self._append_audit_entry(
            payload,
            tax_file_id=tax_file_id,
            actor=AUDIT_ACTOR_ACCOUNTANT,
            action_type="account_added",
            target_type="account",
            target_id=account.id,
            target_label=account.label,
            old_value={},
            new_value=account.to_dict(),
            note="Account connected to Tax File.",
        )
        self._write(payload)
        return account, True

    def find_account(self, *, tax_file_id: str, address: str) -> Account | None:
        validated = validate_address(address)
        for account in self.list_accounts(tax_file_id):
            if account.address == validated:
                return account
        return None

    def update_account(
        self,
        account_id: str,
        *,
        label: str | None = None,
        ownership_status: str | None = None,
    ) -> Account:
        payload = self._payload()
        updated: Account | None = None
        previous: Account | None = None
        rows = []
        for raw in payload["accounts"]:
            account = Account.from_dict(raw)
            if account.id != account_id:
                rows.append(raw)
                continue
            previous = account
            updated = Account(
                **{
                    **account.to_dict(),
                    "label": (label if label is not None else account.label).strip()
                    or _short(account.address, 6),
                    "ownership_status": _clean_choice(
                        ownership_status, OWNERSHIP_STATUSES, account.ownership_status
                    ),
                    "updated_at": _utc_now(),
                }
            )
            rows.append(updated.to_dict())
            self._touch_tax_file(payload, account.tax_file_id)
        if updated is None:
            raise KeyError(account_id)
        payload["accounts"] = rows
        if previous is not None and previous.label != updated.label:
            self._append_audit_entry(
                payload,
                tax_file_id=updated.tax_file_id,
                actor=AUDIT_ACTOR_ACCOUNTANT,
                action_type="label_changed",
                target_type="account",
                target_id=updated.id,
                target_label=updated.label,
                old_value={"label": previous.label},
                new_value={"label": updated.label},
                note="Account label changed.",
            )
        if previous is not None and previous.ownership_status != updated.ownership_status:
            self._append_audit_entry(
                payload,
                tax_file_id=updated.tax_file_id,
                actor=AUDIT_ACTOR_ACCOUNTANT,
                action_type="ownership_changed",
                target_type="account",
                target_id=updated.id,
                target_label=updated.label,
                old_value={"ownership_status": previous.ownership_status},
                new_value={"ownership_status": updated.ownership_status},
                note="Account ownership changed.",
            )
        self._write(payload)
        return updated

    def remove_account(self, account_id: str, *, note: str | None = None) -> Account:
        payload = self._payload()
        removed: Account | None = None
        rows = []
        for raw in payload["accounts"]:
            account = Account.from_dict(raw)
            if account.id == account_id:
                removed = account
                continue
            rows.append(raw)
        if removed is None:
            raise KeyError(account_id)
        payload["accounts"] = rows
        payload["transfer_matches"] = [
            raw
            for raw in payload["transfer_matches"]
            if raw.get("from_account_id") != account_id and raw.get("to_account_id") != account_id
        ]
        payload["client_answers"] = [
            raw
            for raw in payload.get("client_answers", [])
            if raw.get("account_id") != account_id
        ]
        payload["transaction_overrides"] = [
            raw
            for raw in payload.get("transaction_overrides", [])
            if raw.get("account_id") != account_id
        ]
        self._touch_tax_file(payload, removed.tax_file_id)
        self._append_audit_entry(
            payload,
            tax_file_id=removed.tax_file_id,
            actor=AUDIT_ACTOR_ACCOUNTANT,
            action_type="account_removed",
            target_type="account",
            target_id=removed.id,
            target_label=removed.label,
            old_value=removed.to_dict(),
            new_value={},
            note=note or "Account removed from Tax File. Wallet cache was kept.",
        )
        self._write(payload)
        return removed

    def list_transfer_matches(self, tax_file_id: str | None = None) -> list[TransferMatch]:
        matches = [
            TransferMatch.from_dict(raw)
            for raw in self._payload().get("transfer_matches", [])
        ]
        if tax_file_id is not None:
            matches = [match for match in matches if match.tax_file_id == tax_file_id]
        return sorted(
            matches,
            key=lambda m: (
                m.status != MATCH_CONFIRMED,
                m.status != MATCH_SUGGESTED,
                -m.timestamp_diff_seconds,
                m.created_at,
            ),
        )

    def save_transfer_matches(self, tax_file_id: str, matches: list[TransferMatch]) -> None:
        payload = self._payload()
        current = [
            raw
            for raw in payload["transfer_matches"]
            if raw.get("tax_file_id") == tax_file_id
        ]
        incoming = [match.to_dict() for match in matches]
        if _canonical_rows(current) == _canonical_rows(incoming):
            return
        existing = [
            raw
            for raw in payload["transfer_matches"]
            if raw.get("tax_file_id") != tax_file_id
        ]
        payload["transfer_matches"] = existing + incoming
        self._touch_tax_file(payload, tax_file_id)
        self._write(payload)

    def update_transfer_match_status(self, match_id: str, status: str, *, note: str | None = None) -> TransferMatch:
        status = _clean_choice(status, MATCH_STATUSES, MATCH_SUGGESTED)
        payload = self._payload()
        updated: TransferMatch | None = None
        previous: TransferMatch | None = None
        rows = []
        for raw in payload["transfer_matches"]:
            match = TransferMatch.from_dict(raw)
            if match.id != match_id:
                rows.append(raw)
                continue
            previous = match
            updated = TransferMatch(
                **{
                    **match.to_dict(),
                    "status": status,
                    "updated_at": _utc_now(),
                }
            )
            rows.append(updated.to_dict())
            self._touch_tax_file(payload, match.tax_file_id)
        if updated is None:
            raise KeyError(match_id)
        payload["transfer_matches"] = rows
        action = "internal_transfer_confirmed" if status == MATCH_CONFIRMED else "internal_transfer_rejected"
        self._append_audit_entry(
            payload,
            tax_file_id=updated.tax_file_id,
            actor=AUDIT_ACTOR_ACCOUNTANT,
            action_type=action,
            target_type="transfer_match",
            target_id=updated.id,
            target_label=f"{updated.asset} {updated.amount_sent}",
            old_value=previous.to_dict() if previous is not None else {},
            new_value=updated.to_dict(),
            note=note or "Internal transfer status changed.",
        )
        self._write(payload)
        return updated

    def list_client_answers(self, tax_file_id: str | None = None) -> list[ClientAnswer]:
        answers = [
            ClientAnswer.from_dict(raw)
            for raw in self._payload().get("client_answers", [])
        ]
        if tax_file_id is not None:
            answers = [answer for answer in answers if answer.tax_file_id == tax_file_id]
        return sorted(answers, key=lambda answer: answer.client_answered_at, reverse=True)

    def save_client_answer(
        self,
        *,
        tax_file_id: str,
        review_item_id: str,
        account_id: str,
        transaction_id: str,
        review_reason: str,
        direction: str,
        client_question: str,
        client_answer: str,
        resolved_by: str = "client",
    ) -> ClientAnswer:
        if self.get_tax_file(tax_file_id) is None:
            raise KeyError(tax_file_id)
        status, category = _client_answer_treatment(direction, client_answer)
        now = _utc_now()
        resolved_at = now if status == TAX_REVIEW_RESOLVED else None
        answer = ClientAnswer(
            id=uuid4().hex,
            tax_file_id=tax_file_id,
            review_item_id=review_item_id,
            account_id=account_id,
            transaction_id=transaction_id,
            review_reason=_clean_choice(review_reason, REVIEW_REASONS, REASON_UNKNOWN_SOURCE),
            direction=direction if direction in {"incoming", "outgoing"} else "",
            client_question=client_question,
            client_answer=client_answer,
            tax_review_status=status,
            tax_category=category,
            client_answered_at=now,
            resolved_at=resolved_at,
            resolved_by=resolved_by if resolved_at else None,
        )

        payload = self._payload()
        existing_answers = [
            ClientAnswer.from_dict(raw)
            for raw in payload.get("client_answers", [])
            if raw.get("review_item_id") == review_item_id
        ]
        old_answer = existing_answers[0] if existing_answers else None
        payload["client_answers"] = [
            raw
            for raw in payload.get("client_answers", [])
            if raw.get("review_item_id") != review_item_id
        ]
        payload["client_answers"].append(answer.to_dict())
        self._touch_tax_file(payload, tax_file_id)
        self._append_audit_entry(
            payload,
            tax_file_id=tax_file_id,
            actor=AUDIT_ACTOR_CLIENT,
            action_type="client_answer_edited" if old_answer is not None else "client_answer_saved",
            target_type="review_item",
            target_id=review_item_id,
            target_label=_short(transaction_id, 8) if transaction_id else review_item_id,
            old_value=old_answer.to_dict() if old_answer is not None else {},
            new_value=answer.to_dict(),
            note="Client answer saved.",
        )
        self._write(payload)
        return answer

    def clear_client_answer(self, *, tax_file_id: str, review_item_id: str) -> ClientAnswer | None:
        payload = self._payload()
        removed: ClientAnswer | None = None
        kept = []
        for raw in payload.get("client_answers", []):
            answer = ClientAnswer.from_dict(raw)
            if answer.tax_file_id == tax_file_id and answer.review_item_id == review_item_id:
                removed = answer
                continue
            kept.append(raw)
        payload["client_answers"] = kept
        if removed is not None:
            self._touch_tax_file(payload, tax_file_id)
            self._append_audit_entry(
                payload,
                tax_file_id=tax_file_id,
                actor=AUDIT_ACTOR_ACCOUNTANT,
                action_type="review_item_reopened",
                target_type="review_item",
                target_id=review_item_id,
                target_label=_short(removed.transaction_id, 8) if removed.transaction_id else review_item_id,
                old_value=removed.to_dict(),
                new_value={},
                note="Client answer cleared.",
            )
            self._write(payload)
        return removed

    def list_transaction_overrides(self, tax_file_id: str | None = None) -> list[TransactionOverride]:
        overrides = [
            TransactionOverride.from_dict(raw)
            for raw in self._payload().get("transaction_overrides", [])
        ]
        if tax_file_id is not None:
            overrides = [override for override in overrides if override.tax_file_id == tax_file_id]
        return sorted(overrides, key=lambda override: override.updated_at, reverse=True)

    def save_transaction_override(
        self,
        *,
        tax_file_id: str,
        review_item_id: str,
        account_id: str,
        transaction_id: str,
        review_reason: str,
        tax_category: str,
        tax_review_status: str,
        accountant_note: str,
        original_tax_category: str | None = None,
        tax_scope: str = TAX_SCOPE_INCLUDED,
        actor: str = AUDIT_ACTOR_ACCOUNTANT,
        action_type: str = "accountant_override_saved",
    ) -> TransactionOverride:
        note = accountant_note.strip()
        if not note:
            raise ValueError("note_required")
        if self.get_tax_file(tax_file_id) is None:
            raise KeyError(tax_file_id)
        now = _utc_now()
        payload = self._payload()
        existing = self._find_override(payload, tax_file_id=tax_file_id, review_item_id=review_item_id)
        status = _clean_choice(tax_review_status, TAX_REVIEW_STATUSES, TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW)
        scope = _clean_choice(tax_scope, (TAX_SCOPE_INCLUDED, TAX_SCOPE_EXCLUDED, TAX_SCOPE_WATCH_ONLY), TAX_SCOPE_INCLUDED)
        category = _clean_choice(tax_category, TAX_CATEGORIES, TAX_CATEGORY_UNKNOWN)
        old_value = existing.to_dict() if existing is not None else {}
        override = TransactionOverride(
            id=existing.id if existing is not None else uuid4().hex,
            tax_file_id=tax_file_id,
            review_item_id=review_item_id,
            account_id=account_id,
            transaction_id=transaction_id,
            review_reason=_clean_choice(review_reason, REVIEW_REASONS, REASON_UNKNOWN_SOURCE),
            tax_category=category,
            original_tax_category=original_tax_category or (existing.original_tax_category if existing else TAX_CATEGORY_UNKNOWN),
            tax_review_status=status,
            accountant_note=note,
            override_applied=True,
            override_by=actor,
            override_at=now,
            tax_scope=scope,
            excluded_reason=note if scope == TAX_SCOPE_EXCLUDED else None,
            excluded_at=now if scope == TAX_SCOPE_EXCLUDED else None,
            resolved_at=now if status == TAX_REVIEW_RESOLVED else None,
            resolved_by=actor if status == TAX_REVIEW_RESOLVED else None,
            reopened_at=now if status in {TAX_REVIEW_NEEDS_CLIENT_ANSWER, TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW} else None,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        payload["transaction_overrides"] = [
            raw
            for raw in payload.get("transaction_overrides", [])
            if raw.get("review_item_id") != review_item_id or raw.get("tax_file_id") != tax_file_id
        ]
        payload["transaction_overrides"].append(override.to_dict())
        self._touch_tax_file(payload, tax_file_id)
        self._append_audit_entry(
            payload,
            tax_file_id=tax_file_id,
            actor=actor,
            action_type=action_type,
            target_type="transaction" if transaction_id else "review_item",
            target_id=transaction_id or review_item_id,
            target_label=_short(transaction_id, 8) if transaction_id else review_item_id,
            old_value=old_value,
            new_value=override.to_dict(),
            note=note,
        )
        self._write(payload)
        return override

    def reset_transaction_override(self, *, tax_file_id: str, review_item_id: str, note: str) -> TransactionOverride | None:
        reason = note.strip()
        if not reason:
            raise ValueError("note_required")
        payload = self._payload()
        removed: TransactionOverride | None = None
        kept = []
        for raw in payload.get("transaction_overrides", []):
            override = TransactionOverride.from_dict(raw)
            if override.tax_file_id == tax_file_id and override.review_item_id == review_item_id:
                removed = override
                continue
            kept.append(raw)
        payload["transaction_overrides"] = kept
        if removed is not None:
            self._touch_tax_file(payload, tax_file_id)
            self._append_audit_entry(
                payload,
                tax_file_id=tax_file_id,
                actor=AUDIT_ACTOR_ACCOUNTANT,
                action_type="review_item_reopened",
                target_type="review_item",
                target_id=review_item_id,
                target_label=_short(removed.transaction_id, 8) if removed.transaction_id else review_item_id,
                old_value=removed.to_dict(),
                new_value={},
                note=reason,
            )
            self._write(payload)
        return removed

    def archive_tax_file(self, tax_file_id: str, *, note: str) -> TaxFile:
        reason = note.strip()
        if not reason:
            raise ValueError("note_required")
        payload = self._payload()
        updated: TaxFile | None = None
        old_value: dict[str, Any] = {}
        rows = []
        for raw in payload["tax_files"]:
            tax_file = TaxFile.from_dict(raw)
            if tax_file.id != tax_file_id:
                rows.append(raw)
                continue
            old_value = tax_file.to_dict()
            updated = TaxFile(**{**tax_file.to_dict(), "archived_at": _utc_now(), "updated_at": _utc_now()})
            rows.append(updated.to_dict())
        if updated is None:
            raise KeyError(tax_file_id)
        payload["tax_files"] = rows
        self._append_audit_entry(
            payload,
            tax_file_id=tax_file_id,
            actor=AUDIT_ACTOR_ACCOUNTANT,
            action_type="tax_file_deleted_or_archived",
            target_type="tax_file",
            target_id=tax_file_id,
            target_label=updated.name,
            old_value=old_value,
            new_value=updated.to_dict(),
            note=reason,
        )
        self._write(payload)
        return updated

    def list_audit_log(self, tax_file_id: str | None = None, *, limit: int = 200) -> list[AuditLogEntry]:
        entries = [
            AuditLogEntry.from_dict(raw)
            for raw in self._payload().get("audit_log", [])
        ]
        if tax_file_id is not None:
            entries = [entry for entry in entries if entry.tax_file_id == tax_file_id]
        return sorted(entries, key=lambda entry: entry.created_at, reverse=True)[:limit]

    @staticmethod
    def _find_override(
        payload: dict[str, Any],
        *,
        tax_file_id: str,
        review_item_id: str,
    ) -> TransactionOverride | None:
        for raw in payload.get("transaction_overrides", []):
            override = TransactionOverride.from_dict(raw)
            if override.tax_file_id == tax_file_id and override.review_item_id == review_item_id:
                return override
        return None

    @staticmethod
    def _append_audit_entry(
        payload: dict[str, Any],
        *,
        tax_file_id: str,
        actor: str,
        action_type: str,
        target_type: str,
        target_id: str,
        target_label: str,
        old_value: dict[str, Any],
        new_value: dict[str, Any],
        note: str,
    ) -> AuditLogEntry:
        entry = AuditLogEntry(
            id=uuid4().hex,
            tax_file_id=tax_file_id,
            actor=actor,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            old_value_json=old_value,
            new_value_json=new_value,
            note=note,
            created_at=_utc_now(),
        )
        payload.setdefault("audit_log", []).append(entry.to_dict())
        return entry

    def links_by_address(self) -> dict[str, list[dict[str, str]]]:
        files = {tax_file.id: tax_file for tax_file in self.list_tax_files()}
        links: dict[str, list[dict[str, str]]] = {}
        for account in self.list_accounts():
            tax_file = files.get(account.tax_file_id)
            if tax_file is None:
                continue
            links.setdefault(account.address, []).append(
                {
                    "tax_file_id": tax_file.id,
                    "tax_file_name": tax_file.name,
                    "account_id": account.id,
                    "label": account.label,
                    "ownership_status": account.ownership_status,
                }
            )
        return links

    def _payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_payload()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_payload()
        if raw.get("schema_version") != STORE_SCHEMA_VERSION:
            return _empty_payload()
        payload = _empty_payload()
        payload.update(raw)
        payload.setdefault("tax_files", [])
        payload.setdefault("accounts", [])
        payload.setdefault("transfer_matches", [])
        payload.setdefault("client_answers", [])
        payload.setdefault("transaction_overrides", [])
        payload.setdefault("audit_log", [])
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": STORE_SCHEMA_VERSION,
            "tax_files": payload.get("tax_files", []),
            "accounts": payload.get("accounts", []),
            "transfer_matches": payload.get("transfer_matches", []),
            "client_answers": payload.get("client_answers", []),
            "transaction_overrides": payload.get("transaction_overrides", []),
            "audit_log": payload.get("audit_log", []),
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, self.path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)

    @staticmethod
    def _touch_tax_file(payload: dict[str, Any], tax_file_id: str) -> None:
        now = _utc_now()
        touched = []
        for raw in payload["tax_files"]:
            if raw.get("id") == tax_file_id:
                raw = {**raw, "updated_at": now}
            touched.append(raw)
        payload["tax_files"] = touched


def tax_files_overview(cache_root: Path, *, include_archived: bool = False) -> dict[str, Any]:
    store = TaxFileStore(cache_root)
    rows = []
    for tax_file in store.list_tax_files(include_archived=include_archived):
        accounts = store.list_accounts(tax_file.id)
        transaction_count = sum(_cached_row_count(account.address, cache_root) for account in accounts)
        unknown_accounts = sum(1 for account in accounts if account.ownership_status == OWNERSHIP_UNKNOWN)
        is_archived = bool(tax_file.archived_at)
        rows.append(
            {
                "id": tax_file.id,
                "name": tax_file.name,
                "tax_year": tax_file.tax_year,
                "tax_country": tax_file.tax_country,
                "entity_type": tax_file.entity_type,
                "accounts_count": len(accounts),
                "transactions_count": transaction_count,
                "tax_readiness": (
                    "Archived" if is_archived else "Needs ownership review" if unknown_accounts else "Draft review"
                    if accounts
                    else "No accounts"
                ),
                "updated_at": tax_file.updated_at,
                "archived_at": tax_file.archived_at,
                "is_archived": is_archived,
            }
        )
    return {
        "tax_files": rows,
        "show_archived": include_archived,
        "tax_year_default": datetime.now(timezone.utc).year - 1,
        "tax_country_default": DEFAULT_TAX_COUNTRY,
        "tax_country_options": _tax_country_options(),
        "entity_type_default": DEFAULT_ENTITY_TYPE,
        "ownership_statuses": OWNERSHIP_STATUSES,
    }


def tax_file_dashboard_context(tax_file_id: str, cache_root: Path) -> dict[str, Any]:
    store = TaxFileStore(cache_root)
    tax_file = store.get_tax_file(tax_file_id)
    if tax_file is None:
        raise KeyError(tax_file_id)
    matches = matchInternalTransfers(tax_file_id, cache_root=cache_root, store=store)
    accounts = store.list_accounts(tax_file_id)
    client_answers = store.list_client_answers(tax_file_id)
    annotated = unified_transaction_frame(
        tax_file_id,
        cache_root=cache_root,
        store=store,
        include_non_owned=True,
        matches=matches,
    )
    owned = annotated[annotated.get("tax_scope") == TAX_SCOPE_INCLUDED] if not annotated.empty else annotated
    account_rows = _account_rows(accounts, annotated, cache_root)
    review_queue = _review_queue(tax_file, accounts, annotated, matches, client_answers)
    active_review_queue = [
        item for item in review_queue if item["tax_review_status"] in {
            TAX_REVIEW_NEEDS_CLIENT_ANSWER,
            TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
            TAX_REVIEW_BLOCKED_MISSING_DATA,
        }
    ]
    summary = _unified_summary(owned, matches, active_review_queue)
    match_rows = _match_rows(matches, accounts)
    review_groups = _review_groups(review_queue)
    operations = _operation_rows(tax_file, accounts, annotated)
    audit_rows = _audit_rows(store.list_audit_log(tax_file_id))
    cached_wallets = _cached_wallet_rows(cache_root, accounts)
    tax_loss_harvesting = tax_loss_harvesting_advice(tax_file, owned)
    cost_basis = cost_basis_rows(tax_file, owned)
    filing_blockers = _filing_blockers(active_review_queue)
    readiness = tax_readiness_summary(
        accounts=accounts,
        matches=matches,
        frame=owned,
        active_review_queue=active_review_queue,
        review_queue=review_queue,
        cost_basis=cost_basis,
    )
    checklist = accountant_checklist(
        accounts=accounts,
        matches=matches,
        frame=owned,
        active_review_queue=active_review_queue,
        review_queue=review_queue,
        cost_basis=cost_basis,
        readiness=readiness,
    )
    tax_plan = tax_estimate_plan(
        tax_file,
        owned,
        client_questions=review_groups["needs_client_answer"],
        tax_loss_harvesting=tax_loss_harvesting,
    )
    ai_findings = ai_accountant_findings(
        tax_file,
        owned,
        review_queue=review_queue,
        active_review_queue=active_review_queue,
        tax_payment_plan=tax_plan,
    )
    solana_patterns = solana_patterns_detected(tax_file, owned, matches=matches)
    action_summary = tax_file_action_summary(
        readiness,
        review_groups["needs_client_answer"],
        cost_basis,
        tax_plan,
    )
    section_summaries = tax_file_section_summaries(
        accounts=accounts,
        match_rows=match_rows,
        operations=operations,
        audit_rows=audit_rows,
        tax_loss_harvesting=tax_loss_harvesting,
        accountant_checklist=checklist,
        readiness=readiness,
    )
    if tax_plan.get("available"):
        section_summaries.update(
            {
                "client_questions": (
                    "1 self-transfer confirmation needed"
                    if tax_plan.get("confirmation_pending")
                    else "Self-transfer confirmation complete"
                ),
                "export": (
                    "US export available after the pending confirmation"
                    if tax_plan.get("confirmation_pending")
                    else "US export available · no active blockers"
                ),
            }
        )
    section_state = tax_file_section_state(
        client_questions=review_groups["needs_client_answer"],
        match_rows=match_rows,
    )
    return {
        "tax_file": tax_file.to_dict(),
        "presenter_mode": _is_test_tax_file(tax_file),
        "accounts": account_rows,
        "summary": summary,
        "action_summary": action_summary,
        "section_summaries": section_summaries,
        "section_state": section_state,
        "ai_accountant_findings": ai_findings,
        "solana_patterns": solana_patterns,
        "export_package_items": [
            "Form 8949 draft fields",
            "Schedule D summary inputs",
            "Review items",
            "Audit trail",
            "Missing data report",
            "CSV export",
        ],
        "final_value_bullets": [
            "Taxable events classified",
            "Missing basis issues flagged",
            "Self-transfers matched",
            "Optimization opportunities explained",
            "Export package ready for CPA review",
        ],
        "tax_readiness": readiness,
        "accountant_checklist": checklist,
        "accountant_checklist_note": ACCOUNTANT_CHECKLIST_NOTE,
        "loss_review_disclaimer": LOSS_REVIEW_DISCLAIMER,
        "loss_review_assumptions_limitations": LOSS_REVIEW_ASSUMPTIONS_LIMITATIONS,
        "tax_loss_harvesting": tax_loss_harvesting,
        "tax_payment_plan": tax_plan,
        "cost_basis": cost_basis,
        "cost_basis_note": COST_BASIS_ACCOUNTANT_NOTE,
        "filing_blockers": filing_blockers,
        "client_questions": review_groups["needs_client_answer"],
        "review_groups": review_groups,
        "main_review_groups": {
            key: value
            for key, value in review_groups.items()
            if key in {"needs_client_answer", "needs_accountant_review"} and value
        },
        "advanced_review_groups": {
            key: value
            for key, value in review_groups.items()
            if key in {"resolved", "informational", "excluded"} and value
        },
        "resolved_review_items": review_groups["resolved"],
        "informational_review_items": review_groups["informational"],
        "excluded_review_items": review_groups["excluded"],
        "review_queue": review_queue,
        "operations": operations,
        "audit_log": audit_rows,
        "transfer_matches": match_rows,
        "cached_wallets": cached_wallets,
        "has_unlinked_cached_wallets": any(not wallet["linked"] for wallet in cached_wallets),
        "incoming_client_answer_options": _answer_options(INCOMING_CLIENT_ANSWER_OPTIONS),
        "outgoing_client_answer_options": _answer_options(OUTGOING_CLIENT_ANSWER_OPTIONS),
        "tax_categories": _answer_options(tuple((category, _category_label(category)) for category in TAX_CATEGORIES)),
        "tax_review_statuses": _answer_options(tuple((status, _status_label(status)) for status in TAX_REVIEW_STATUSES if status != TAX_REVIEW_READY)),
        "ownership_statuses": OWNERSHIP_STATUSES,
        "tax_country_default": DEFAULT_TAX_COUNTRY,
        "entity_type_default": DEFAULT_ENTITY_TYPE,
        "has_accounts": bool(accounts),
    }


def unified_transaction_frame(
    tax_file_id: str,
    *,
    cache_root: Path,
    store: TaxFileStore | None = None,
    include_non_owned: bool = False,
    matches: list[TransferMatch] | None = None,
) -> pd.DataFrame:
    store = store or TaxFileStore(cache_root)
    accounts = store.list_accounts(tax_file_id)
    if not include_non_owned:
        accounts = [account for account in accounts if account.ownership_status == OWNERSHIP_OWNED]
    matches = matches if matches is not None else store.list_transfer_matches(tax_file_id)
    client_answers = store.list_client_answers(tax_file_id)
    transaction_overrides = store.list_transaction_overrides(tax_file_id)

    frames: list[pd.DataFrame] = []
    for account in accounts:
        cached = _read_cache(account.address, cache_root)
        if cached is None:
            continue
        frame, _meta = cached
        frame = frame.copy()
        frame = _ensure_transaction_extensions(frame)
        frame["tax_file_id"] = tax_file_id
        frame["account_id"] = account.id
        frame["account_label"] = account.label
        frame["account_address"] = account.address
        frame["ownership_status"] = account.ownership_status
        frame["tax_scope"] = _tax_scope_for_account(account)
        frame["tax_review_status"] = _tax_review_status_for_account(account)
        frame["review_reason"] = _review_reason_for_account(account)
        frame["original_tax_category"] = None
        frame["accountant_note"] = None
        frame["override_applied"] = False
        frame["override_by"] = None
        frame["override_at"] = None
        frame["excluded_reason"] = None
        frame["excluded_at"] = None
        frame["reopened_at"] = None
        frame["transfer_match_id"] = None
        frame["is_internal_transfer"] = False
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=list(dict.fromkeys(DATAFRAME_COLUMNS + _TRANSACTION_EXTENSION_COLUMNS)))

    combined = pd.concat(frames, ignore_index=True, sort=False)
    _apply_accounting_classification(combined)
    _apply_matches_to_frame(combined, matches)
    _apply_client_answers_to_frame(combined, client_answers)
    _apply_transaction_overrides_to_frame(combined, transaction_overrides)
    return combined


def tax_loss_harvesting_advice(
    tax_file: TaxFile | dict[str, Any],
    frame: pd.DataFrame,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Return conservative potential loss review notes for a Tax File."""
    today = today or datetime.now(timezone.utc).date()
    raw_country = tax_file.tax_country if isinstance(tax_file, TaxFile) else str(tax_file.get("tax_country") or "")
    tax_year = tax_file.tax_year if isinstance(tax_file, TaxFile) else int(tax_file.get("tax_year") or today.year)
    country_code = _tax_country_code(raw_country)
    profile = _tax_loss_harvesting_profile(country_code)
    candidates = (
        _tax_loss_harvesting_candidates(frame, tax_year=tax_year, country_code=country_code, profile=profile)
        if profile is not None
        else []
    )
    total_loss = sum((_to_decimal(candidate["unrealized_loss_amount"]) for candidate in candidates), Decimal("0"))
    total_effect = sum((_to_decimal(candidate["estimated_tax_effect_amount"]) for candidate in candidates), Decimal("0"))
    currency = str(profile["currency"]) if profile is not None else "PLN"
    available = profile is not None and bool(candidates)
    if profile is None:
        status = "unsupported_jurisdiction"
        title = "Potential Loss Harvesting Review requires a local profile"
        message = (
            "This Tax File is not set to Poland or the United States, so the potential loss review model "
            "is not enabled."
        )
    elif candidates:
        status = "review_opportunity"
        title = "Potential Loss Harvesting Review"
        message = _tax_loss_harvesting_notification(tax_year, today, total_effect, country_code=country_code, currency=currency)
    else:
        status = "no_candidates"
        title = "No potential loss harvesting candidates found"
        message = (
            "No owned-account token acquisitions matched the loss review model. Add verified cost basis and current "
            "price data before using this as a professional review workflow."
        )

    return {
        "available": available,
        "status": status,
        "status_label": "Review Opportunity" if status == "review_opportunity" else status.replace("_", " ").title(),
        "title": title,
        "message": message,
        "country": country_code,
        "tax_year": tax_year,
        "currency": currency,
        "tax_rate": str(profile["tax_rate_label"]) if profile is not None else "",
        "total_unrealized_loss_amount": _decimal_to_storage(total_loss),
        "total_estimated_tax_effect_amount": _decimal_to_storage(total_effect),
        "total_unrealized_loss_display": _format_money(total_loss, currency),
        "total_estimated_tax_effect_display": _format_money(total_effect, currency),
        "total_unrealized_loss_pln": _format_money_pln(total_loss) if currency == "PLN" else "",
        "total_estimated_tax_effect_pln": _format_money_pln(total_effect) if currency == "PLN" else "",
        "candidates": candidates,
        "guardrails": _tax_loss_harvesting_guardrails(country_code),
        "review_guardrails": _loss_harvesting_review_guardrails(),
        "sources": _tax_loss_harvesting_sources(country_code),
        "assumptions": _tax_loss_harvesting_assumptions(country_code, currency),
    }


_TAX_FILE_EXPORT_COLUMNS = [
    "date",
    "account_label",
    "account_address",
    "source_wallet",
    "destination_wallet",
    "transaction_signature",
    "transaction_hash",
    "status",
    "tax_category",
    "tax_category_label",
    "tax_review_status",
    "tax_review_status_label",
    "is_potentially_taxable",
    "expected_form",
    "ordinary_income_usd",
    "cost_basis",
    "proceeds_usd",
    "gain_loss_usd",
    "holding_period",
    "holding_period_days",
    "fmv_usd",
    "fee_usd",
    "fee_treatment",
    "asset",
    "amount",
    "review_reason",
    "review_reason_label",
    "confidence_percent",
    "ai_explanation",
    "recommended_next_action",
]

_CPA_READY_EXPORT_COLUMNS = [
    "Tax Year",
    "Date",
    "Account",
    "Asset",
    "Quantity",
    "Transaction Type",
    "Tax Category",
    "Taxable Event",
    "Review Status",
    "Expected Tax Form",
    "Proceeds (USD)",
    "Cost Basis (USD)",
    "Gain/Loss (USD)",
    "Holding Period",
    "Days Held",
    "Ordinary Income (USD)",
    "FMV (USD)",
    "Network Fee (USD)",
    "Fee Treatment",
    "AI Confidence (%)",
    "Review Reason",
    "CPA Notes",
    "Recommended Next Action",
    "Source",
    "Destination",
    "Wallet Address",
    "Transaction Signature",
]


def tax_file_export_frame(tax_file: TaxFile | dict[str, Any], frame: pd.DataFrame) -> pd.DataFrame:
    """Return a Tax File export aligned with accountant classifications and cost-basis rows."""
    if frame.empty:
        return pd.DataFrame(columns=_TAX_FILE_EXPORT_COLUMNS)

    allocations = _cost_basis_allocations_by_signature(cost_basis_rows(tax_file, frame))
    rows: list[dict[str, Any]] = []
    sorted_frame = frame.sort_values("timestamp_unix", ascending=False, kind="stable").reset_index(drop=True)
    for _, row in sorted_frame.iterrows():
        if str(row.get("tax_scope") or TAX_SCOPE_INCLUDED) == TAX_SCOPE_EXCLUDED:
            continue
        signature = str(row.get("signature") or "")
        category = str(row.get("tax_category") or TAX_CATEGORY_UNKNOWN)
        status = str(row.get("tax_review_status") or TAX_REVIEW_READY)
        allocation = allocations.get(signature, {})
        taxable_status = _tax_file_taxable_status(category, status)
        ordinary_income = _tax_file_ordinary_income_usd(row, category)
        fmv = _cost_basis_value_from_row(row)
        rows.append(
            {
                "date": _row_date(row),
                "account_label": str(row.get("account_label") or ""),
                "account_address": str(row.get("account_address") or ""),
                "source_wallet": _source_wallet(row),
                "destination_wallet": _destination_wallet(row),
                "transaction_signature": signature,
                "transaction_hash": signature,
                "status": str(row.get("status") or ""),
                "tax_category": category,
                "tax_category_label": _category_label(category),
                "tax_review_status": status,
                "tax_review_status_label": _status_label(status),
                "is_potentially_taxable": taxable_status,
                "expected_form": _expected_form(category, status),
                "ordinary_income_usd": _decimal_to_storage(ordinary_income) if ordinary_income is not None else "",
                "cost_basis": allocation.get("cost_basis", ""),
                "proceeds_usd": allocation.get("proceeds_usd", ""),
                "gain_loss_usd": allocation.get("gain_loss_usd", ""),
                "holding_period": allocation.get("holding_period", ""),
                "holding_period_days": allocation.get("holding_period_days", ""),
                "fmv_usd": _decimal_to_storage(fmv) if fmv is not None else "",
                "fee_usd": _fee_usd(row),
                "fee_treatment": _fee_treatment(category, status),
                "asset": allocation.get("asset", _row_assets(row)),
                "amount": allocation.get("amount", _row_amount(row)),
                "review_reason": str(row.get("review_reason") or ""),
                "review_reason_label": _reason_label(str(row.get("review_reason") or "")),
                "confidence_percent": _confidence_percent(row),
                "ai_explanation": _tax_file_ai_explanation(row, category, status),
                "recommended_next_action": _tax_file_next_action(row, category, status),
            }
        )
    return pd.DataFrame(rows, columns=_TAX_FILE_EXPORT_COLUMNS)


def tax_file_cpa_ready_export_frame(tax_file: TaxFile | dict[str, Any], frame: pd.DataFrame) -> pd.DataFrame:
    """Return a CPA-facing CSV frame with readable columns and technical IDs last."""
    if frame.empty:
        return pd.DataFrame(columns=_CPA_READY_EXPORT_COLUMNS)

    machine_export = tax_file_export_frame(tax_file, frame)
    rows: list[dict[str, Any]] = []
    for _, row in machine_export.iterrows():
        rows.append(
            {
                "Tax Year": _row_year_from_date(str(row.get("date") or "")),
                "Date": row.get("date", ""),
                "Account": _public_account_label(row.get("account_label")),
                "Asset": row.get("asset", ""),
                "Quantity": _public_quantity(row.get("amount")),
                "Transaction Type": _public_transaction_type(row),
                "Tax Category": row.get("tax_category_label", ""),
                "Taxable Event": _public_taxable_status(row.get("is_potentially_taxable")),
                "Review Status": row.get("tax_review_status_label", ""),
                "Expected Tax Form": row.get("expected_form", ""),
                "Proceeds (USD)": row.get("proceeds_usd", ""),
                "Cost Basis (USD)": row.get("cost_basis", ""),
                "Gain/Loss (USD)": row.get("gain_loss_usd", ""),
                "Holding Period": row.get("holding_period", ""),
                "Days Held": row.get("holding_period_days", ""),
                "Ordinary Income (USD)": row.get("ordinary_income_usd", ""),
                "FMV (USD)": row.get("fmv_usd", ""),
                "Network Fee (USD)": row.get("fee_usd", ""),
                "Fee Treatment": _public_text(row.get("fee_treatment"), max_len=160),
                "AI Confidence (%)": row.get("confidence_percent", ""),
                "Review Reason": row.get("review_reason_label", ""),
                "CPA Notes": _public_text(row.get("ai_explanation"), max_len=180),
                "Recommended Next Action": _public_text(row.get("recommended_next_action"), max_len=160),
                "Source": _public_counterparty(row.get("source_wallet")),
                "Destination": _public_counterparty(row.get("destination_wallet")),
                "Wallet Address": row.get("account_address", ""),
                "Transaction Signature": row.get("transaction_signature", ""),
            }
        )
    return pd.DataFrame(rows, columns=_CPA_READY_EXPORT_COLUMNS)


def _row_year_from_date(value: str) -> str:
    return value[:4] if value and len(value) >= 4 else ""


def _public_transaction_type(row: pd.Series) -> str:
    category = str(row.get("tax_category") or "")
    label = str(row.get("tax_category_label") or "").strip()
    if category == TAX_CATEGORY_SWAP_TRADE:
        return "Swap"
    if category == TAX_CATEGORY_TRANSFER_FROM_EXCHANGE:
        return "Exchange funding"
    if category == TAX_CATEGORY_INTERNAL_TRANSFER:
        return "Self-transfer"
    if category == TAX_CATEGORY_FAILED_FEE_ONLY:
        return "Failed transaction fee"
    return label or category.replace("_", " ").title()


def _public_quantity(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text[0] not in "+-.0123456789":
        return ""
    if len(text) > 60:
        return ""
    return _public_text(text)


def _public_taxable_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw == "yes":
        return "Yes"
    if raw == "no":
        return "No"
    if raw == "review":
        return "Review"
    return raw.title() if raw else ""


def _public_account_label(value: Any) -> str:
    text = str(value or "")
    if text == "Demo Solana Wallet":
        return "Primary Solana Wallet"
    if text == "Demo Solana Cold Wallet":
        return "Cold Storage Wallet"
    return _public_text(text)


def _public_counterparty(value: Any) -> str:
    text = str(value or "")
    labels = {
        "COINBASE": "Coinbase",
        "JUPITER": "Jupiter",
        "ORCA": "Orca",
        "WORMHOLE": "Wormhole",
        "STAKE_PROGRAM": "Solana Stake Program",
        "MAGIC_EDEN": "Magic Eden",
    }
    return labels.get(text.upper(), _public_text(text))


def _public_text(value: Any, *, max_len: int | None = None) -> str:
    text = str(value or "")
    replacements = [
        ("Demo seed: ", "Reviewed: "),
        ("Demo dataset: ", ""),
        ("Demo estimate", "Draft estimate"),
        ("Demo assumption", "FMV assumption"),
        ("Demo Solana Wallet", "Primary Solana Wallet"),
        ("Demo Solana Cold Wallet", "Cold Storage Wallet"),
        ("Demo NFT", "Solana NFT"),
        ("demo NFT", "NFT"),
        ("demo loss model", "loss review model"),
        ("demo rates", "review rates"),
        ("demo rate", "review rate"),
        ("demo lots", "review lots"),
        ("the demo", "the review"),
        ("The demo", "The review"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    text = re.sub(
        r"\bdemo\b",
        lambda match: "Review" if match.group(0)[:1].isupper() else "review",
        text,
        flags=re.IGNORECASE,
    )
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def tax_file_yearly_summary(
    tax_file: TaxFile | dict[str, Any],
    frame: pd.DataFrame,
    *,
    tax_payment_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return a US tax-year summary aligned with the Tax File estimate."""
    if frame.empty:
        return []

    estimate = (tax_payment_plan or {}).get("estimate") or tax_estimate_breakdown(tax_file, frame)
    export = tax_file_export_frame(tax_file, frame)
    taxable_events = int((export["is_potentially_taxable"] == "yes").sum()) if not export.empty else 0
    fee_usd = sum(
        (
            _to_decimal(_fee_usd(row))
            for _, row in frame.iterrows()
            if str(row.get("tax_scope") or TAX_SCOPE_INCLUDED) == TAX_SCOPE_INCLUDED
        ),
        Decimal("0"),
    )
    tax_year = tax_file.tax_year if isinstance(tax_file, TaxFile) else int(tax_file.get("tax_year") or 0)
    return [
        {
            "year": tax_year or "",
            "realized_gain_usd": estimate.get("realized_capital_gain_display", ""),
            "ordinary_income_usd": estimate.get("ordinary_income_display", ""),
            "missing_basis_usd": estimate.get("missing_basis_exposure_display", ""),
            "fees_usd": _format_money(fee_usd, "USD"),
            "estimated_federal_tax_usd": estimate.get("estimated_federal_tax_display", ""),
            "taxable_count": str(taxable_events),
            "review_items": str(estimate.get("review_items_affecting_estimate") or "0"),
        }
    ]


def tax_estimate_breakdown(
    tax_file: TaxFile | dict[str, Any],
    frame: pd.DataFrame,
    *,
    client_questions: list[dict[str, Any]] | None = None,
    tax_loss_harvesting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a traceable federal demo estimate from verified Tax File facts."""
    federal_rate = US_DEMO_SHORT_TERM_CAPITAL_RATE
    cost_rows = cost_basis_rows(tax_file, frame)
    realized_gain = sum(
        (_to_decimal(row.get("gain_loss_usd_amount")) for row in cost_rows if str(row.get("gain_loss_usd_amount") or "")),
        Decimal("0"),
    )
    ordinary_income = sum(
        (
            _tax_file_ordinary_income_usd(row, str(row.get("tax_category") or TAX_CATEGORY_UNKNOWN)) or Decimal("0")
            for _, row in frame.iterrows()
            if str(row.get("tax_scope") or TAX_SCOPE_INCLUDED) == TAX_SCOPE_INCLUDED
        ),
        Decimal("0"),
    )
    missing_basis_exposure = sum(
        (
            _to_decimal(row.get("proceeds_usd_amount"))
            for row in cost_rows
            if str(row.get("status") or "") == "Needs cost basis"
        ),
        Decimal("0"),
    )
    active_review_items = int(
        sum(
            1
            for _, row in frame.iterrows()
            if str(row.get("tax_review_status") or "") in {
                TAX_REVIEW_NEEDS_CLIENT_ANSWER,
                TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
                TAX_REVIEW_BLOCKED_MISSING_DATA,
            }
        )
    )
    realized_capital_gain = max(realized_gain, Decimal("0"))
    loss_available = _to_decimal((tax_loss_harvesting or {}).get("total_unrealized_loss_amount"))
    if loss_available <= 0:
        loss_available = sum(
            (_to_decimal(candidate.get("unrealized_loss_amount")) for candidate in (tax_loss_harvesting or {}).get("candidates", [])),
            Decimal("0"),
        )
    loss_offset = min(realized_capital_gain, max(loss_available, Decimal("0")))
    taxable_base_before = realized_capital_gain + ordinary_income
    taxable_base_after = max(realized_capital_gain - loss_offset, Decimal("0")) + ordinary_income
    estimated_tax_before = taxable_base_before * federal_rate
    estimated_tax_after = taxable_base_after * federal_rate
    potential_reduction = estimated_tax_before - estimated_tax_after
    confirmation_pending = bool(
        client_questions
        and any(
            item.get("review_reason") == REASON_UNKNOWN_SOURCE
            and item.get("tax_review_status") == TAX_REVIEW_NEEDS_CLIENT_ANSWER
            for item in client_questions
        )
    )
    if client_questions is None:
        confirmation_pending = _frame_has_pending_test_confirmation(frame)
    self_transfer_value = _self_transfer_confirmation_value(frame)
    false_tax = self_transfer_value * federal_rate

    return {
        "realized_capital_gain": _decimal_to_storage(realized_capital_gain),
        "realized_capital_gain_display": _format_money(realized_capital_gain, "USD"),
        "ordinary_income": _decimal_to_storage(ordinary_income),
        "ordinary_income_display": _format_money(ordinary_income, "USD"),
        "missing_basis_exposure": _decimal_to_storage(missing_basis_exposure),
        "missing_basis_exposure_display": _format_money(missing_basis_exposure, "USD"),
        "federal_rate": _decimal_to_storage(federal_rate),
        "federal_rate_display": "24%",
        "state_tax_display": "Not configured",
        "review_items_affecting_estimate": str(active_review_items),
        "last_calculated_timestamp": _utc_now(),
        "loss_offset": _decimal_to_storage(loss_offset),
        "loss_offset_display": _format_money(loss_offset, "USD"),
        "estimated_federal_tax": _decimal_to_storage(estimated_tax_before),
        "estimated_federal_tax_display": _format_money(estimated_tax_before, "USD"),
        "estimated_federal_tax_formula_display": (
            f"({_format_money(realized_capital_gain, 'USD')} + {_format_money(ordinary_income, 'USD')}) "
            f"x 24% = {_format_money(estimated_tax_before, 'USD')}"
        ),
        "estimated_federal_tax_after_planning": _decimal_to_storage(estimated_tax_after),
        "estimated_federal_tax_after_planning_display": _format_money(estimated_tax_after, "USD"),
        "potential_federal_tax_reduction": _decimal_to_storage(potential_reduction),
        "potential_federal_tax_reduction_display": _format_money(potential_reduction, "USD"),
        "potential_federal_tax_reduction_formula_display": (
            f"{_format_money(loss_offset, 'USD')} x 24% = {_format_money(potential_reduction, 'USD')}"
        ),
        "self_transfer_value_display": _format_money(self_transfer_value, "USD"),
        "self_transfer_false_tax_display": _format_money(false_tax, "USD"),
        "confirmation_pending": confirmation_pending,
        "assumptions": [
            "Estimated federal tax is calculated from verified realized gains, ordinary income, selected federal rate assumption, and review-status adjustments. This is not tax advice and should be reviewed by a CPA.",
            "Draft estimate based on verified lots, FMV assumptions, and selected federal rate.",
            "State tax: Not configured.",
            "Missing basis exposure is shown separately and is not treated as final tax due.",
            "Potential planning impact assumes enough current-year capital gains to absorb the reviewed loss candidate.",
        ],
    }


def tax_estimate_plan(
    tax_file: TaxFile | dict[str, Any],
    frame: pd.DataFrame,
    *,
    client_questions: list[dict[str, Any]] | None = None,
    tax_loss_harvesting: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the concrete US demo tax estimate and action cards."""
    if not _is_test_tax_file(tax_file):
        return {"available": False}

    confirmation_item = None
    if client_questions is not None:
        confirmation_item = next(
            (
                item for item in client_questions
                if item.get("review_reason") == REASON_UNKNOWN_SOURCE
                and item.get("tax_review_status") == TAX_REVIEW_NEEDS_CLIENT_ANSWER
            ),
            None,
        )
        confirmation_pending = confirmation_item is not None
    else:
        confirmation_pending = _frame_has_pending_test_confirmation(frame)

    estimate = tax_estimate_breakdown(
        tax_file,
        frame,
        client_questions=client_questions,
        tax_loss_harvesting=tax_loss_harvesting,
    )
    confirmation_status = "1 confirmation needed" if confirmation_pending else "Confirmed"
    confirmation_class = "warning" if confirmation_pending else "confirmed"
    optimized_due = estimate["estimated_federal_tax_after_planning_display"]
    savings = estimate["potential_federal_tax_reduction_display"]
    loss = estimate["loss_offset_display"]
    return {
        "available": True,
        "demo_us_only": True,
        "confirmation_pending": confirmation_pending,
        "confirmation_item": confirmation_item,
        "confirmation_question": TEST_CLIENT_CONFIRMATION_QUESTION,
        "confirmation_answer_label": TEST_CLIENT_CONFIRMATION_ANSWER,
        "confirmation_status_label": confirmation_status,
        "confirmation_status_class": confirmation_class,
        "estimated_tax_before_display": estimate["estimated_federal_tax_display"],
        "samo_unrealized_loss_display": loss,
        "samo_tax_savings_display": savings,
        "optimized_tax_due_display": optimized_due,
        "self_transfer_value_display": estimate["self_transfer_value_display"],
        "self_transfer_false_tax_display": estimate["self_transfer_false_tax_display"],
        "estimate": estimate,
        "assumptions": estimate["assumptions"],
        "kpis": [
            {"label": "Realized capital gain", "value": estimate["realized_capital_gain_display"], "note": "Verified FIFO lot gain/loss only.", "class": "kpi-success"},
            {"label": "Ordinary income", "value": estimate["ordinary_income_display"], "note": "Airdrops, rewards, and income events.", "class": "kpi-info"},
            {"label": "Missing basis", "value": estimate["missing_basis_exposure_display"], "note": "Exposure excluded from final filing totals.", "class": "kpi-warning"},
            {"label": "Estimated federal tax", "value": estimate["estimated_federal_tax_display"], "note": "Draft estimate, not final tax due.", "class": "kpi-review"},
            {"label": "Review items", "value": estimate["review_items_affecting_estimate"], "note": "Open items affecting confidence.", "class": "kpi-warning"},
            {"label": "Taxable events detected", "value": str(_taxable_event_count(frame)), "note": "Swaps, sales, NFT sales, and income events.", "class": "kpi-info"},
        ],
        "reporting_rows": [
            {"label": "Realized gains", "value": estimate["realized_capital_gain_display"], "note": "Form 8949 / Schedule D draft support."},
            {"label": "Ordinary income", "value": estimate["ordinary_income_display"], "note": "Schedule 1 or Schedule C review depending taxpayer facts."},
            {"label": "Missing basis", "value": estimate["missing_basis_exposure_display"], "note": "Blocked from final use until reviewed."},
            {"label": "State tax", "value": estimate["state_tax_display"], "note": "Optional configuration, not included in the draft estimate."},
        ],
        "planning_rows": [
            {"label": "SAMO loss available", "value": estimate["loss_offset_display"], "note": "Unrealized loss candidate before CPA review."},
            {"label": "Federal rate assumption", "value": estimate["federal_rate_display"], "note": "Selected federal short-term rate assumption."},
            {"label": "Potential federal reduction", "value": savings, "note": "State tax not included."},
            {"label": "After planning review", "value": optimized_due, "note": "Requires sale before year-end and CPA review."},
        ],
        "estimate_breakdown": [
            {"label": "Input amount", "value": f"{estimate['realized_capital_gain_display']} realized gain + {estimate['ordinary_income_display']} ordinary income"},
            {"label": "Formula", "value": estimate["estimated_federal_tax_formula_display"]},
            {"label": "State tax", "value": "Excluded / not configured"},
            {"label": "Review status", "value": f"{estimate['review_items_affecting_estimate']} open item affecting confidence"},
            {"label": "Disclaimer", "value": "Draft estimate only. This is not tax advice."},
        ],
        "planning_breakdown": [
            {"label": "Unrealized SAMO loss available", "value": estimate["loss_offset_display"]},
            {"label": "Realized gains available to offset", "value": estimate["loss_offset_display"]},
            {"label": "Federal rate assumption", "value": estimate["federal_rate_display"]},
            {"label": "Estimated reduction", "value": estimate["potential_federal_tax_reduction_formula_display"]},
            {"label": "State tax", "value": "Excluded / not configured"},
            {"label": "Review status", "value": "Requires CPA review before year-end"},
        ],
        "summary": (
            "Draft estimate based on verified lots, FMV assumptions, and selected federal rate. "
            "This is a CPA-ready draft review workflow, not final tax due."
        ),
        "primary_next_action": (
            "Answer the self-transfer question with Transfer from my own wallet. The transaction becomes an "
            "internal transfer, taxable income stays clean, and the review moves to 0 blockers."
            if confirmation_pending
            else f"Review is clean: export the CPA-ready package with estimated federal tax after planning review of {optimized_due}."
        ),
        "cards": [
            {
                "badge": "Client confirmation",
                "title": "Confirm self-transfer",
                "status_label": confirmation_status,
                "status_class": confirmation_class,
                "impact_label": "False tax avoided",
                "impact_display": _format_money(TEST_SELF_TRANSFER_FALSE_TAX_USD, "USD"),
                "action": (
                    "Ask: Was this transfer from your own wallet? Save the answer Transfer from my own wallet."
                ),
                "why": (
                    f"The transfer is worth {estimate['self_transfer_value_display']} in this review. Confirmation "
                    "classifies it as an internal transfer and excludes it from taxable income."
                ),
            },
            {
                "badge": "Year-end optimization",
                "title": "Realize SAMO loss before year-end",
                "status_label": "Tax savings modeled",
                "status_class": "confirmed",
                "impact_label": "Estimated tax reduction",
                "impact_display": savings,
                "action": (
                    "Review a year-end taxable disposition of 3,000,000 SAMO with a qualified tax professional."
                ),
                "why": (
                    f"The reviewed lots have {loss} of loss available against current-year gains. At the selected "
                    f"{estimate['federal_rate_display']} federal rate, the potential federal reduction is {savings}, "
                    "assuming enough capital gains and professional approval."
                ),
            },
            {
                "badge": "US export",
                "title": "Export US tax package",
                "status_label": "Ready after confirmation" if confirmation_pending else "Ready",
                "status_class": "warning" if confirmation_pending else "confirmed",
                "impact_label": "Estimated federal tax after planning review",
                "impact_display": optimized_due,
                "action": "Export the CPA-ready CSV or JSON package for accountant review.",
                "why": (
                    "The package keeps self-transfers out of income, carries Form 8949/Schedule D review notes, "
                    "and includes missing data, audit trail, and confidence fields."
                ),
            },
        ],
        "readiness_rows": [
            {
                "item": "Self-transfer confirmation",
                "status": confirmation_status,
                "status_class": confirmation_class,
                "note": (
                    "Client must answer one question."
                    if confirmation_pending
                    else "Client confirmed this as an own-wallet transfer."
                ),
            },
            {
                "item": "Unrelated blockers",
                "status": "0",
                "status_class": "confirmed",
                "note": "Cost basis, FMV, staking, and exchange items are pre-reviewed for this workflow.",
            },
            {
                "item": "US tax estimate",
                "status": optimized_due,
                "status_class": "confirmed",
                "note": "Estimated federal tax after planning review; not final tax due.",
            },
            {
                "item": "Exports",
                "status": "Available",
                "status_class": "confirmed",
                "note": "CSV and JSON package includes Form 8949 draft fields, Schedule D summary inputs, review items, and audit context.",
            },
        ],
        "loss_model_matches": bool((tax_loss_harvesting or {}).get("available")),
    }


def solana_patterns_detected(
    tax_file: TaxFile | dict[str, Any],
    frame: pd.DataFrame,
    *,
    matches: list[TransferMatch],
) -> dict[str, Any]:
    """Return demo-safe Solana-specific accounting patterns backed by Tax File data."""
    if not _is_test_tax_file(tax_file):
        return {"available": False, "items": []}

    def has_row(predicate) -> bool:
        return any(predicate(row) for _, row in frame.iterrows()) if not frame.empty else False

    def tx_type(row: pd.Series) -> str:
        return str(row.get("transaction_type") or "").upper()

    def tag(row: pd.Series) -> str:
        return str(row.get("tag_type") or "")

    def category(row: pd.Series) -> str:
        return str(row.get("tax_category") or "")

    token_assets = {
        _asset_label(str(row.get("primary_token_symbol") or row.get("asset") or ""))
        for _, row in frame.iterrows()
        if _asset_label(str(row.get("primary_token_symbol") or row.get("asset") or "")) not in {"", "SOL"}
    }
    confirmed_or_pending_transfer = any(match.status in {MATCH_CONFIRMED, MATCH_SUGGESTED} for match in matches)

    items = [
        {
            "label": "Jupiter swap classified as taxable disposal",
            "status": "Detected" if has_row(lambda row: category(row) == TAX_CATEGORY_SWAP_TRADE or tag(row) == "Swap") else "Not in dataset",
            "status_class": "confirmed" if has_row(lambda row: category(row) == TAX_CATEGORY_SWAP_TRADE or tag(row) == "Swap") else "neutral",
            "note": "SOL -> BONK and stablecoin swap records carry taxable-event review fields.",
        },
        {
            "label": "Stake reward classified as ordinary income",
            "status": "Detected" if has_row(lambda row: category(row) == TAX_CATEGORY_STAKING_REWARD) else "Not in dataset",
            "status_class": "confirmed" if has_row(lambda row: category(row) == TAX_CATEGORY_STAKING_REWARD) else "neutral",
            "note": "Staking reward FMV is separated from capital gains.",
        },
        {
            "label": "SPL token activity parsed",
            "status": f"{len(token_assets)} tokens" if token_assets else "Not in dataset",
            "status_class": "confirmed" if token_assets else "neutral",
            "note": "BONK, SAMO, JUP, USDC/USDT, and wSOL-style activity appear in the Tax File.",
        },
        {
            "label": "wSOL wrap/bridge flagged for CPA review",
            "status": "Detected" if has_row(lambda row: tx_type(row) == "WRAP_SOL") else "Not in dataset",
            "status_class": "warning" if has_row(lambda row: tx_type(row) == "WRAP_SOL") else "neutral",
            "note": "Wrapped-token activity is not treated as a final taxable disposal without review.",
        },
        {
            "label": "NFT mint/sale prepared for gain/loss review",
            "status": "Detected" if has_row(lambda row: tx_type(row) in {"NFT_MINT", "NFT_SALE"}) else "Not in dataset",
            "status_class": "confirmed" if has_row(lambda row: tx_type(row) in {"NFT_MINT", "NFT_SALE"}) else "neutral",
            "note": "Mint cost, sale proceeds, and fees are carried into the CPA package.",
        },
        {
            "label": "Self-transfer matched across Solana wallets",
            "status": "Detected" if confirmed_or_pending_transfer else "Not in dataset",
            "status_class": "confirmed" if confirmed_or_pending_transfer else "neutral",
            "note": "Own-wallet movement is excluded from income after confirmation.",
        },
        {
            "label": "Fees tracked in SOL",
            "status": "Detected" if has_row(lambda row: _to_decimal(row.get("fee")) > 0) else "Not in dataset",
            "status_class": "confirmed" if has_row(lambda row: _to_decimal(row.get("fee")) > 0) else "neutral",
            "note": "Network fees stay available for audit context and basis review.",
        },
        {
            "label": "Transaction signatures linked for audit trail",
            "status": "Detected" if has_row(lambda row: bool(str(row.get("signature") or ""))) else "Not in dataset",
            "status_class": "confirmed" if has_row(lambda row: bool(str(row.get("signature") or ""))) else "neutral",
            "note": "Rows link back to raw Solana transaction details when address and signature exist.",
        },
    ]
    return {
        "available": True,
        "intro": "Built for Solana wallet activity: Jupiter swaps, staking rewards, SPL tokens, NFTs, wSOL, and transaction signatures.",
        "items": items,
    }


def ai_accountant_findings(
    tax_file: TaxFile | dict[str, Any],
    frame: pd.DataFrame,
    *,
    review_queue: list[dict[str, Any]],
    active_review_queue: list[dict[str, Any]],
    tax_payment_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return high-level AI Accountant findings for the Tax File hero area."""
    export = tax_file_export_frame(tax_file, frame)
    taxable_events = int((export["is_potentially_taxable"] == "yes").sum()) if not export.empty else 0
    possible_self_transfers = sum(
        1
        for item in review_queue
        if item.get("review_reason") in {REASON_POSSIBLE_INTERNAL_TRANSFER, REASON_UNKNOWN_SOURCE}
        and item.get("tax_category") in {TAX_CATEGORY_INTERNAL_TRANSFER, TAX_CATEGORY_UNKNOWN}
    )
    missing_basis = sum(1 for item in review_queue if item.get("review_reason") == REASON_MISSING_COST_BASIS)
    ordinary_income = int(
        frame["tax_category"].isin([TAX_CATEGORY_AIRDROP_REWARD, TAX_CATEGORY_STAKING_REWARD]).sum()
    ) if not frame.empty and "tax_category" in frame else 0
    pending_answers = sum(1 for item in active_review_queue if item.get("tax_review_status") == TAX_REVIEW_NEEDS_CLIENT_ANSWER)
    package_copy = (
        f"CPA package ready after {pending_answers} answer" if pending_answers else "CPA package ready for export"
    )
    estimate = tax_payment_plan.get("estimate", {}) if tax_payment_plan else {}
    items = [
        {
            "label": "Taxable events detected",
            "value": str(taxable_events),
            "href": "#tax-classification",
            "note": "Swaps, sales, NFT sales, and income events prepared for review.",
        },
        {
            "label": "Possible self-transfer",
            "value": str(possible_self_transfers),
            "href": "#review-queue",
            "note": "Matched or pending wallet ownership confirmation.",
        },
        {
            "label": "Missing basis issues",
            "value": str(missing_basis),
            "href": "#cost-basis",
            "note": "Acquisition history needed before relying on final totals.",
        },
        {
            "label": "Ordinary income events",
            "value": str(ordinary_income),
            "href": "#tax-classification",
            "note": "Airdrops and staking rewards kept separate from capital gains.",
        },
    ]
    if estimate:
        items.append(
            {
                "label": "Estimated federal tax",
                "value": str(estimate.get("estimated_federal_tax_display") or ""),
                "href": "#cpa-export",
                "note": "Draft estimate with visible assumptions. State tax excluded.",
            }
        )
    items.append(
        {
            "label": package_copy,
            "value": "Ready" if not pending_answers else str(pending_answers),
            "href": "#cpa-export",
            "note": "Draft package only. Final filing requires taxpayer/CPA review.",
        }
    )
    return {
        "badge": "2025 US taxpayer story",
        "defensive_copy": "Classification is deterministic for auditability, with an AI explanation layer for user guidance, review prioritization, and CPA-ready summaries.",
        "items": items,
        "estimate_available": bool((tax_payment_plan or {}).get("available")),
    }


def cost_basis_rows(tax_file: TaxFile | dict[str, Any], frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return preliminary FIFO lot tracking rows for accountant review."""
    if frame.empty:
        return []

    lots = _cost_basis_lots(tax_file, frame)
    rows: list[dict[str, Any]] = []
    for disposition in _cost_basis_dispositions(tax_file, frame):
        unmatched = disposition["amount"]
        for lot in lots:
            if unmatched <= 0:
                break
            if lot["asset"] != disposition["asset"]:
                continue
            if lot["acquired_on"] > disposition["disposed_on"]:
                continue
            available = lot["amount"] - lot["disposed_total"]
            if available <= 0:
                continue
            allocated = min(available, unmatched)
            lot["disposed_total"] += allocated
            unmatched -= allocated
            rows.append(_cost_basis_allocation_row(lot, disposition, allocated))
        if unmatched > 0:
            rows.append(_cost_basis_missing_lot_row(disposition, unmatched))

    if not rows:
        rows.extend(_cost_basis_unmatched_acquisition_row(lot) for lot in lots)
    else:
        used_lot_ids = {row.get("lot_id") for row in rows if row.get("lot_id")}
        rows.extend(
            _cost_basis_unmatched_acquisition_row(lot)
            for lot in lots
            if lot["id"] not in used_lot_ids and lot["source"] == "manual lot"
        )

    return rows[:75]


def tax_readiness_summary(
    *,
    accounts: list[Account],
    matches: list[TransferMatch],
    frame: pd.DataFrame,
    active_review_queue: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
    cost_basis: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a conservative readiness score for the Tax File workpaper."""
    counts = _tax_readiness_counts(accounts, matches, frame, active_review_queue, review_queue, cost_basis)
    score = 100
    score -= counts["missing_cost_basis"] * 20
    score -= counts["unknown_outgoing"] * 15
    score -= counts["missing_fmv"] * 15
    score -= counts["unresolved_nft_sales"] * 10
    score -= counts["unresolved_airdrops_rewards"] * 10
    score -= counts["unresolved_informational"] * 5
    score = max(0, min(100, score))
    blocking_items = counts["blocking_items"]
    label = _tax_readiness_label(score, blocking_items)
    return {
        "score": score,
        "score_display": f"{score}%",
        "status_label": label,
        "status_class": _tax_readiness_status_class(score, blocking_items),
        "explanation": _tax_readiness_explanation(score, blocking_items),
        "blocking_items": blocking_items,
        "counts": counts,
        "blockers": [
            {
                "type": "Missing acquisition lots / cost basis",
                "count": counts["missing_cost_basis"],
                "status_class": "warning" if counts["missing_cost_basis"] else "confirmed",
            },
            {
                "type": "Unknown outgoing destinations",
                "count": counts["unknown_outgoing"],
                "status_class": "warning" if counts["unknown_outgoing"] else "confirmed",
            },
            {
                "type": "Unknown incoming sources",
                "count": counts["unknown_incoming"],
                "status_class": "warning" if counts["unknown_incoming"] else "confirmed",
            },
            {
                "type": "Possible internal transfers",
                "count": counts["possible_internal_transfers"],
                "status_class": "warning" if counts["possible_internal_transfers"] else "confirmed",
            },
            {
                "type": "Missing FMV / proceeds",
                "count": counts["missing_fmv"],
                "status_class": "warning" if counts["missing_fmv"] else "confirmed",
            },
            {
                "type": "NFT sales to review",
                "count": counts["unresolved_nft_sales"],
                "status_class": "warning" if counts["unresolved_nft_sales"] else "confirmed",
            },
            {
                "type": "Airdrops / rewards to review",
                "count": counts["unresolved_airdrops_rewards"],
                "status_class": "warning" if counts["unresolved_airdrops_rewards"] else "confirmed",
            },
            {
                "type": "Informational review notes",
                "count": counts["unresolved_informational"],
                "status_class": "neutral" if counts["unresolved_informational"] else "confirmed",
            },
        ],
    }


def accountant_checklist(
    *,
    accounts: list[Account],
    matches: list[TransferMatch],
    frame: pd.DataFrame,
    active_review_queue: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
    cost_basis: list[dict[str, Any]],
    readiness: dict[str, Any],
) -> list[dict[str, str]]:
    """Return checklist rows for accountant handoff readiness."""
    counts = readiness["counts"]
    owned_accounts = [account for account in accounts if account.ownership_status == OWNERSHIP_OWNED]
    possible_transfer_items = [
        item for item in active_review_queue if item.get("review_reason") == REASON_POSSIBLE_INTERNAL_TRANSFER
    ]
    transfer_reviewed = bool(matches) and all(match.status in {MATCH_CONFIRMED, MATCH_REJECTED} for match in matches)
    nft_rows = _frame_has_category(frame, TAX_CATEGORY_NFT_SALE)
    airdrop_rows = _frame_has_any_category(frame, {TAX_CATEGORY_AIRDROP_REWARD, TAX_CATEGORY_STAKING_REWARD})
    failed_rows = _failed_rows(frame)
    failed_open = [
        item
        for item in review_queue
        if item.get("review_reason") == REASON_FAILED_TRANSACTION
        and item.get("tax_review_status") not in {TAX_REVIEW_RESOLVED, TAX_REVIEW_INFORMATIONAL, TAX_REVIEW_EXCLUDED}
    ]
    blockers = int(readiness["blocking_items"])

    return [
        _checklist_row(
            "Wallets connected",
            "Done" if owned_accounts else "Blocked",
            f"{len(owned_accounts)} owned wallet account{'s' if len(owned_accounts) != 1 else ''} connected."
            if owned_accounts
            else "Connect at least one owned wallet before preparing a Tax File.",
        ),
        _checklist_row(
            "Exchange history imported",
            "Blocked" if counts["missing_cost_basis"] else "Done",
            "Missing acquisition lots likely require exchange history, manual purchase data, or an unknown-basis override."
            if counts["missing_cost_basis"]
            else "No missing acquisition-lot blocker is active in the current review queue.",
        ),
        _checklist_row(
            "Internal transfers reviewed",
            "Needs review" if possible_transfer_items or not transfer_reviewed else "Done",
            f"{len(possible_transfer_items)} possible internal transfer item{'s' if len(possible_transfer_items) != 1 else ''} still need review."
            if possible_transfer_items
            else "No internal transfer match has been confirmed or rejected yet."
            if not transfer_reviewed
            else "Internal transfer matches have been reviewed.",
        ),
        _checklist_row(
            "Unknown destinations answered",
            "Blocked" if counts["unknown_outgoing"] else "Done",
            (
                "1 outgoing destination still needs a client answer."
                if counts["unknown_outgoing"] == 1
                else f"{counts['unknown_outgoing']} outgoing destinations still need client answers."
            )
            if counts["unknown_outgoing"]
            else "No unresolved unknown outgoing destinations are active.",
        ),
        _checklist_row(
            "Cost basis completed",
            "Blocked" if counts["missing_cost_basis"] or _cost_basis_status_count(cost_basis, "Needs cost basis") else "Done",
            "Disposed assets still have missing acquisition lots or cost basis."
            if counts["missing_cost_basis"] or _cost_basis_status_count(cost_basis, "Needs cost basis")
            else "No Cost Basis row is currently blocked by missing acquisition lots.",
        ),
        _checklist_row(
            "FMV values completed",
            "Blocked" if counts["missing_fmv"] or _cost_basis_status_count(cost_basis, "Needs FMV") else "Done",
            "Some transactions or disposals still need USD FMV/proceeds values."
            if counts["missing_fmv"] or _cost_basis_status_count(cost_basis, "Needs FMV")
            else "No active missing-FMV issue is detected.",
        ),
        _checklist_row(
            "NFT sales reviewed",
            "Needs review" if counts["unresolved_nft_sales"] else "Done" if nft_rows else "Not applicable",
            (
                "1 NFT sale item still needs cost basis or accountant review."
                if counts["unresolved_nft_sales"] == 1
                else f"{counts['unresolved_nft_sales']} NFT sale items still need cost basis or accountant review."
            )
            if counts["unresolved_nft_sales"]
            else "NFT sale activity was found and no active blocker remains."
            if nft_rows
            else "No NFT sale activity was found in the current Tax File.",
        ),
        _checklist_row(
            "Airdrops/rewards reviewed",
            "Needs review" if counts["unresolved_airdrops_rewards"] else "Done" if airdrop_rows else "Not applicable",
            (
                "1 airdrop/reward item still needs FMV or income treatment review."
                if counts["unresolved_airdrops_rewards"] == 1
                else f"{counts['unresolved_airdrops_rewards']} airdrop/reward items still need FMV or income treatment review."
            )
            if counts["unresolved_airdrops_rewards"]
            else "Airdrop/reward activity was found and no active blocker remains."
            if airdrop_rows
            else "No airdrop or reward activity was found in the current Tax File.",
        ),
        _checklist_row(
            "Failed transactions reviewed",
            "Needs review" if failed_open else "Done" if len(failed_rows) else "Not applicable",
            f"{len(failed_open)} failed transaction item{'s' if len(failed_open) != 1 else ''} still need classification."
            if failed_open
            else "Failed fee-only transactions are classified as informational."
            if len(failed_rows)
            else "No failed transactions were found in the current Tax File.",
        ),
        _checklist_row(
            "Year-end balances reconciled",
            "Needs review",
            "Balance reconciliation is not implemented yet; accountant should reconcile year-end balances manually.",
        ),
        _checklist_row(
            "Draft report generated",
            "Needs review" if blockers else "Done",
            f"Tax export exists, but {blockers} blocker{'s' if blockers != 1 else ''} remain."
            if blockers
            else "Draft export is available and no active blockers remain.",
        ),
        _checklist_row(
            "Accountant sign-off",
            "Blocked" if blockers else "Needs review",
            "Resolve all blocker statuses before sign-off."
            if blockers
            else "No active blockers remain; accountant sign-off is still a manual review step.",
        ),
    ]


def tax_file_action_summary(
    readiness: dict[str, Any],
    client_questions: list[dict[str, Any]],
    cost_basis: list[dict[str, Any]],
    tax_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if tax_plan and tax_plan.get("available"):
        confirmation_count = 1 if tax_plan.get("confirmation_pending") else 0
        return {
            "metrics": [
                {"label": "Estimated federal tax", "value": str(tax_plan["estimated_tax_before_display"])},
                {"label": "Potential federal reduction", "value": str(tax_plan["samo_tax_savings_display"])},
                {"label": "After planning review", "value": str(tax_plan["optimized_tax_due_display"])},
                {"label": "Confirmation needed", "value": str(confirmation_count)},
                {"label": "Unrelated blockers", "value": "0"},
            ],
            "primary_next_action": str(tax_plan["primary_next_action"]),
        }

    cost_basis_issues = max(
        _to_int(readiness["counts"].get("missing_cost_basis")),
        _cost_basis_status_count(cost_basis, "Needs cost basis"),
    )
    missing_fmv_issues = max(
        _to_int(readiness["counts"].get("missing_fmv")),
        _cost_basis_status_count(cost_basis, "Needs FMV"),
    )
    blockers = _to_int(readiness.get("blocking_items"))
    client_question_count = len(client_questions)
    return {
        "metrics": [
            {"label": "Readiness score", "value": readiness["score_display"]},
            {"label": "Blockers", "value": str(blockers)},
            {"label": "Client questions", "value": str(client_question_count)},
            {"label": "Cost basis issues", "value": str(cost_basis_issues)},
            {"label": "Missing FMV issues", "value": str(missing_fmv_issues)},
        ],
        "primary_next_action": _primary_next_action(
            blockers=blockers,
            client_questions=client_question_count,
            cost_basis_issues=cost_basis_issues,
            missing_fmv_issues=missing_fmv_issues,
            readiness_score=_to_int(readiness.get("score")),
        ),
    }


def tax_file_section_summaries(
    *,
    accounts: list[Account],
    match_rows: list[dict[str, Any]],
    operations: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    tax_loss_harvesting: dict[str, Any],
    accountant_checklist: list[dict[str, str]],
    readiness: dict[str, Any],
) -> dict[str, str]:
    owned = sum(1 for account in accounts if account.ownership_status == OWNERSHIP_OWNED)
    watch_only = sum(1 for account in accounts if account.ownership_status == OWNERSHIP_WATCH_ONLY)
    external = sum(1 for account in accounts if account.ownership_status == OWNERSHIP_EXTERNAL)
    blocked = sum(1 for row in accountant_checklist if row["status"] == "Blocked")
    needs_review = sum(1 for row in accountant_checklist if row["status"] == "Needs review")
    done = sum(1 for row in accountant_checklist if row["status"] == "Done")
    client_questions = _to_int(readiness["counts"].get("unknown_incoming")) + _to_int(readiness["counts"].get("unknown_outgoing"))
    suggested_matches = sum(1 for row in match_rows if row.get("status") == MATCH_SUGGESTED)
    confirmed_matches = sum(1 for row in match_rows if row.get("status") == MATCH_CONFIRMED)
    rejected_matches = sum(1 for row in match_rows if row.get("status") == MATCH_REJECTED)
    blockers = _to_int(readiness.get("blocking_items"))
    candidates = len(tax_loss_harvesting.get("candidates") or [])
    return {
        "loss_review": (
            f"{_count_phrase(candidates, 'potential candidate')} subject to professional review"
            if candidates
            else "No potential loss candidates found in the current model"
        ),
        "accountant_checklist": f"{blocked} blocked · {needs_review} need review · {done} done",
        "connected_accounts": f"{owned} owned wallet{'s' if owned != 1 else ''} included · {watch_only} watch-only · {external} external",
        "client_questions": (
            f"{_count_phrase(client_questions, 'unanswered client question')}"
            if client_questions
            else "No unanswered client questions"
        ),
        "internal_transfers": (
            f"{_count_phrase(suggested_matches, 'possible match')} need review"
            if suggested_matches
            else f"{confirmed_matches} confirmed · {rejected_matches} rejected"
        ),
        "operations": f"{_count_phrase(len(operations), 'transaction')} connected to this Tax File",
        "audit_log": f"{_count_phrase(len(audit_rows), 'audit event')} recorded",
        "export": "Draft export available · blockers remain" if blockers else "Draft export available · no active blockers",
    }


def tax_file_section_state(
    *,
    client_questions: list[dict[str, Any]],
    match_rows: list[dict[str, Any]],
) -> dict[str, bool]:
    return {
        "client_questions_open": bool(client_questions),
        "internal_transfers_open": any(row.get("status") == MATCH_SUGGESTED for row in match_rows),
    }


def matchInternalTransfers(
    tax_file_id: str,
    *,
    cache_root: Path,
    store: TaxFileStore | None = None,
    window_seconds: int = TRANSFER_MATCH_WINDOW_SECONDS,
) -> list[TransferMatch]:
    """Find likely self-transfers between owned accounts in a tax file."""
    store = store or TaxFileStore(cache_root)
    accounts = [
        account
        for account in store.list_accounts(tax_file_id)
        if account.ownership_status == OWNERSHIP_OWNED
    ]
    by_id = {account.id: account for account in accounts}
    if len(accounts) < 2:
        return store.list_transfer_matches(tax_file_id)

    outgoing: list[_TransferCandidate] = []
    incoming: list[_TransferCandidate] = []
    for account in accounts:
        cached = _read_cache(account.address, cache_root)
        if cached is None:
            continue
        frame, _meta = cached
        outgoing.extend(_transfer_candidates(frame, account, direction="out"))
        incoming.extend(_transfer_candidates(frame, account, direction="in"))

    existing = {match.id: match for match in store.list_transfer_matches(tax_file_id)}
    matched_incoming: set[str] = set()
    found: list[TransferMatch] = []
    for out in sorted(outgoing, key=lambda c: (c.timestamp_unix, c.account.id, c.signature)):
        options = [
            inc
            for inc in incoming
            if inc.account.id != out.account.id
            and inc.asset == out.asset
            and inc.row_key not in matched_incoming
            and abs(inc.timestamp_unix - out.timestamp_unix) <= window_seconds
            and _amounts_match(out, inc)
        ]
        if not options:
            continue
        inc = sorted(
            options,
            key=lambda candidate: (
                abs(candidate.timestamp_unix - out.timestamp_unix),
                abs(candidate.amount - out.amount),
            ),
        )[0]
        match_id = _match_id(tax_file_id, out, inc)
        old = existing.get(match_id)
        confidence = _confidence(out, inc)
        now = _utc_now()
        status = old.status if old is not None else MATCH_SUGGESTED
        created_at = old.created_at if old is not None else now
        found.append(
            TransferMatch(
                id=match_id,
                tax_file_id=tax_file_id,
                from_account_id=out.account.id,
                to_account_id=inc.account.id,
                from_transaction_id=out.signature,
                to_transaction_id=inc.signature,
                asset=_asset_label(out.asset),
                amount_sent=_decimal_to_storage(out.amount),
                amount_received=_decimal_to_storage(inc.amount),
                fee_amount=_decimal_to_storage(out.fee_amount),
                timestamp_diff_seconds=abs(inc.timestamp_unix - out.timestamp_unix),
                confidence=confidence,
                status=status,
                created_at=created_at,
                updated_at=old.updated_at if old is not None else now,
            )
        )
        matched_incoming.add(inc.row_key)

    preserved = [
        match
        for match in existing.values()
        if match.id not in {m.id for m in found}
        and match.tax_file_id == tax_file_id
        and match.from_account_id in by_id
        and match.to_account_id in by_id
        and match.status in {MATCH_CONFIRMED, MATCH_REJECTED}
    ]
    result = found + preserved
    store.save_transfer_matches(tax_file_id, result)
    return store.list_transfer_matches(tax_file_id)


def create_demo_tax_file(cache_root: Path, *, primary_address: str, secondary_address: str) -> TaxFile:
    store = TaxFileStore(cache_root)
    tax_file = store.create_tax_file(
        tax_file_id="demo-tax-file-2025",
        name="2025 Crypto Tax Review",
        tax_country=DEFAULT_TAX_COUNTRY,
        tax_year=2025,
        entity_type=DEFAULT_ENTITY_TYPE,
    )
    store.add_account(
        tax_file_id=tax_file.id,
        address=primary_address,
        label="Phantom main",
        ownership_status=OWNERSHIP_OWNED,
    )
    store.add_account(
        tax_file_id=tax_file.id,
        address=secondary_address,
        label="Ledger",
        ownership_status=OWNERSHIP_OWNED,
    )
    matches = matchInternalTransfers(tax_file.id, cache_root=cache_root, store=store)
    for match in matches:
        if match.status == MATCH_SUGGESTED:
            store.update_transfer_match_status(match.id, MATCH_CONFIRMED)
    return tax_file


def create_test_tax_file(cache_root: Path, *, primary_address: str, secondary_address: str) -> TaxFile:
    """Create the US-only presentation Tax File with one pending client confirmation."""
    from .demo import TEST_SIGNATURES

    store = TaxFileStore(cache_root)
    _reset_tax_file_state(store, TEST_TAX_FILE_ID)
    tax_file = store.create_tax_file(
        tax_file_id=TEST_TAX_FILE_ID,
        name=TEST_TAX_FILE_NAME,
        tax_country=DEFAULT_TAX_COUNTRY,
        tax_year=2025,
        entity_type=DEFAULT_ENTITY_TYPE,
    )
    primary, _ = store.add_account(
        tax_file_id=tax_file.id,
        address=primary_address,
        label="Primary Solana Wallet",
        ownership_status=OWNERSHIP_OWNED,
    )
    store.add_account(
        tax_file_id=tax_file.id,
        address=secondary_address,
        label="Cold Storage Wallet",
        ownership_status=OWNERSHIP_OWNED,
    )
    matches = matchInternalTransfers(tax_file.id, cache_root=cache_root, store=store)
    for match in matches:
        if match.status == MATCH_SUGGESTED:
            store.update_transfer_match_status(
                match.id,
                MATCH_CONFIRMED,
                note="Seeded self-transfer between taxpayer-owned wallets.",
            )

    for key, reason, category, note in _test_demo_resolved_items(TEST_SIGNATURES):
        signature = TEST_SIGNATURES[key]
        store.save_transaction_override(
            tax_file_id=tax_file.id,
            review_item_id=_review_item_id(tax_file.id, primary.id, signature, reason),
            account_id=primary.id,
            transaction_id=signature,
            review_reason=reason,
            tax_category=category,
            original_tax_category=category,
            tax_review_status=TAX_REVIEW_RESOLVED,
            accountant_note=note,
            actor=AUDIT_ACTOR_SYSTEM,
            action_type="classification_seeded",
        )
    return tax_file


def _reset_tax_file_state(store: TaxFileStore, tax_file_id: str) -> None:
    payload = store._payload()
    for key in (
        "tax_files",
        "accounts",
        "transfer_matches",
        "client_answers",
        "transaction_overrides",
        "audit_log",
    ):
        payload[key] = [
            raw for raw in payload.get(key, [])
            if raw.get("tax_file_id") != tax_file_id
        ]
    store._write(payload)


def _test_demo_resolved_items(signatures: dict[str, str]) -> list[tuple[str, str, str, str]]:
    return [
        (
            "samo_large",
            REASON_MISSING_COST_BASIS,
            TAX_CATEGORY_SWAP_TRADE,
            "Reviewed: acquisition lot, USD FMV, and fee treatment reviewed for the SAMO lot.",
        ),
        (
            "bonk_long_sale",
            REASON_MISSING_COST_BASIS,
            TAX_CATEGORY_SELL,
            "Reviewed: long-term BONK lot basis imported from historical exchange records.",
        ),
        (
            "samo_small",
            REASON_MISSING_COST_BASIS,
            TAX_CATEGORY_SWAP_TRADE,
            "Reviewed: acquisition lot, USD FMV, and fee treatment reviewed for the SAMO lot.",
        ),
        (
            "usdc_sale",
            REASON_MISSING_COST_BASIS,
            TAX_CATEGORY_SELL,
            "Reviewed: sale proceeds and FIFO SOL basis are ready for US capital gain estimate.",
        ),
        (
            "airdrop",
            REASON_MISSING_FMV,
            TAX_CATEGORY_AIRDROP_REWARD,
            "Reviewed: token reward FMV is documented in USD.",
        ),
        (
            "staking_deposit",
            REASON_COMPLEX_DEFI,
            TAX_CATEGORY_STAKING_DEPOSIT,
            "Reviewed: staking deposit reviewed as a non-taxable transfer into staking.",
        ),
        (
            "staking_reward",
            REASON_MISSING_FMV,
            TAX_CATEGORY_STAKING_REWARD,
            "Reviewed: staking reward FMV documented as ordinary income support.",
        ),
        (
            "nft_mint",
            REASON_MISSING_COST_BASIS,
            TAX_CATEGORY_NFT_PURCHASE,
            "Reviewed: NFT mint basis includes mint cost and Solana network fee.",
        ),
        (
            "nft_sale",
            REASON_MISSING_COST_BASIS,
            TAX_CATEGORY_NFT_SALE,
            "Reviewed: NFT sale proceeds and basis are prepared for Form 8949 review.",
        ),
        (
            "bridge_wsol",
            REASON_COMPLEX_DEFI,
            TAX_CATEGORY_DEFI_COMPLEX,
            "Reviewed: wSOL wrap/bridge pattern marked for CPA review rather than treated as final disposal.",
        ),
        (
            "lp_deposit",
            REASON_COMPLEX_DEFI,
            TAX_CATEGORY_DEFI_COMPLEX,
            "Reviewed: LP deposit requires DeFi treatment review and is kept in the CPA workspace.",
        ),
        (
            "stablecoin_swap",
            REASON_MISSING_COST_BASIS,
            TAX_CATEGORY_SWAP_TRADE,
            "Reviewed: stablecoin swap is tracked as a low-gain taxable review event.",
        ),
        (
            "failed_fee",
            REASON_FEE_ONLY,
            TAX_CATEGORY_FAILED_FEE_ONLY,
            "Reviewed: failed transaction records the fee only and no disposal.",
        ),
        (
            "missing_price",
            REASON_MISSING_FMV,
            TAX_CATEGORY_AIRDROP_REWARD,
            "Reviewed: historical FMV is missing and included in the missing data report.",
        ),
        (
            "missing_basis",
            REASON_MISSING_COST_BASIS,
            TAX_CATEGORY_SWAP_TRADE,
            "Reviewed: external JUP acquisition history is missing and included in the missing basis report.",
        ),
        (
            "duplicate_candidate",
            REASON_UNKNOWN_SOURCE,
            TAX_CATEGORY_TRANSFER_FROM_EXCHANGE,
            "Reviewed: duplicate exchange support row reviewed as non-income and not a disposal.",
        ),
    ]


def _account_rows(accounts: list[Account], frame: pd.DataFrame, cache_root: Path) -> list[dict[str, Any]]:
    rows = []
    for account in accounts:
        cached = _read_cache(account.address, cache_root)
        meta = cached[1] if cached else {}
        if frame.empty or "account_id" not in frame.columns:
            tx_count = 0
        else:
            tx_count = int((frame["account_id"] == account.id).sum())
        rows.append(
            {
                **account.to_dict(),
                "address_short": _short(account.address, 8),
                "transactions_count": tx_count,
                "last_fetched": str(meta.get("fetched_at") or ""),
                "last_fetched_display": str(meta.get("fetched_at") or "")[:16].replace("T", " "),
                "dataset_label": str(meta.get("dataset_label") or ""),
                "tax_scope": _tax_scope_for_account(account),
            }
        )
    return rows


def _operation_rows(tax_file: TaxFile, accounts: list[Account], frame: pd.DataFrame) -> list[dict[str, Any]]:
    by_id = {account.id: account for account in accounts}
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return rows
    for _, row in frame.sort_values("timestamp_unix", ascending=False, kind="stable").iterrows():
        account = by_id.get(str(row.get("account_id") or ""))
        if account is None:
            continue
        signature = str(row.get("signature") or "")
        review_reason = str(row.get("review_reason") or REASON_UNKNOWN_SOURCE)
        review_id = _review_item_id(tax_file.id, account.id, signature, review_reason)
        category = str(row.get("tax_category") or TAX_CATEGORY_UNKNOWN)
        original_category = str(row.get("original_tax_category") or category)
        review_status = str(row.get("tax_review_status") or TAX_REVIEW_READY)
        rows.append(
            {
                "id": review_id,
                "date": _row_date(row),
                "account_id": account.id,
                "account_label": _account_label(account),
                "account_address": account.address,
                "signature": signature,
                "signature_short": _short(signature, 8) if signature else "",
                "detected_category": _category_label(original_category),
                "detected_category_enum": original_category,
                "tax_category": category,
                "tax_category_label": _category_label(category),
                "tax_review_status": review_status,
                "tax_review_status_label": _status_label(review_status),
                "review_reason": review_reason,
                "review_reason_label": _reason_label(review_reason),
                "client_answer": str(row.get("client_answer") or ""),
                "client_answer_label": _answer_label(str(row.get("client_answer") or ""), _row_direction(row)),
                "accountant_note": str(row.get("accountant_note") or ""),
                "override_applied": bool(row.get("override_applied")),
                "tax_scope": str(row.get("tax_scope") or TAX_SCOPE_INCLUDED),
                "excluded_reason": str(row.get("excluded_reason") or ""),
                "description": str(row.get("description") or row.get("net_flow_summary") or ""),
                "direction": _row_direction(row),
                "is_internal_transfer": bool(row.get("is_internal_transfer")),
                "confidence_percent": _confidence_percent(row),
                "ai_reason": _tax_file_ai_explanation(row, category, review_status),
                "tax_impact": _tax_impact_copy(category, review_status),
            }
        )
    return rows


def _audit_rows(entries: list[AuditLogEntry]) -> list[dict[str, Any]]:
    return [
        {
            **entry.to_dict(),
            "created_display": entry.created_at[:16].replace("T", " "),
            "action_label": entry.action_type.replace("_", " ").title(),
            "actor_label": entry.actor.title(),
            "old_value_display": _audit_value_summary(entry.old_value_json),
            "new_value_display": _audit_value_summary(entry.new_value_json),
        }
        for entry in entries
    ]


def _audit_value_summary(value: dict[str, Any]) -> str:
    if not value:
        return ""
    pieces: list[str] = []
    if value.get("name"):
        pieces.append(f"Name: {value['name']}")
    if value.get("label"):
        pieces.append(f"Label: {value['label']}")
    if value.get("address"):
        pieces.append(f"Address: {_short(str(value['address']), 8)}")
    if value.get("ownership_status"):
        pieces.append(f"Ownership: {value['ownership_status']}")
    if value.get("tax_category"):
        pieces.append(f"Category: {_category_label(str(value['tax_category']))}")
    if value.get("tax_review_status"):
        pieces.append(f"Status: {_status_label(str(value['tax_review_status']))}")
    if value.get("tax_scope"):
        pieces.append(f"Scope: {value['tax_scope']}")
    if value.get("client_answer"):
        pieces.append(f"Client answer: {_answer_label(str(value['client_answer']))}")
    if value.get("accountant_note"):
        pieces.append(f"Accountant note: {value['accountant_note']}")
    if value.get("excluded_reason"):
        pieces.append(f"Excluded reason: {value['excluded_reason']}")
    if value.get("archived_at"):
        pieces.append(f"Archived at: {str(value['archived_at'])[:16].replace('T', ' ')} UTC")
    if not pieces:
        for key in ("id", "target_id", "transaction_id", "review_item_id", "status"):
            if value.get(key):
                pieces.append(f"{key.replace('_', ' ').title()}: {value[key]}")
    return "; ".join(pieces)


def _unified_summary(
    owned: pd.DataFrame,
    matches: list[TransferMatch],
    review_queue: list[dict[str, Any]],
) -> dict[str, str]:
    total = len(owned)
    succeeded = int((owned["status"] == "succeeded").sum()) if total and "status" in owned else 0
    failed = int((owned["status"] == "failed").sum()) if total and "status" in owned else 0
    fees = sum((_to_decimal(v) for v in owned.get("fee_sol", [])), Decimal("0"))
    counterparties: set[str] = set()
    if not owned.empty:
        for _, row in owned.iterrows():
            for movement in _safe_movements(row.get("movements_in")) + _safe_movements(row.get("movements_out")):
                cp = str(movement.get("counterparty") or "")
                if cp:
                    counterparties.add(cp)
            source = str(row.get("source") or "")
            if source and source.upper() != "UNKNOWN":
                counterparties.add(source)

    confirmed_matches = [match for match in matches if match.status == MATCH_CONFIRMED]
    unmatched_in = sum(
        1 for item in review_queue if item.get("review_reason") == REASON_UNKNOWN_SOURCE
    )
    unmatched_out = sum(
        1 for item in review_queue if item.get("review_reason") == REASON_UNKNOWN_DESTINATION
    )

    return {
        "transactions_total": str(total),
        "succeeded": str(succeeded),
        "failed": str(failed),
        "total_network_fees": f"{_format_decimal(fees)} SOL",
        "unique_counterparties": str(len(counterparties)),
        "internal_transfers_matched": str(len(confirmed_matches)),
        "unmatched_inflows": str(unmatched_in),
        "unmatched_outflows": str(unmatched_out),
        "review_needed": str(len(review_queue)),
    }


def _review_queue(
    tax_file: TaxFile,
    accounts: list[Account],
    frame: pd.DataFrame,
    matches: list[TransferMatch],
    client_answers: list[ClientAnswer] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    account_by_id = {account.id: account for account in accounts}
    answers_by_item = {answer.review_item_id: answer for answer in (client_answers or [])}
    for account in accounts:
        if account.ownership_status == OWNERSHIP_UNKNOWN:
            rows.append(
                _review_item(
                    "wallet marked unknown ownership",
                    tax_file_id=tax_file.id,
                    account=account,
                    reason=REASON_OWNERSHIP_UNKNOWN,
                    status=TAX_REVIEW_BLOCKED_MISSING_DATA,
                    message="Wallet ownership unknown. Transactions are not ready for tax review.",
                )
            )
        elif account.ownership_status == OWNERSHIP_WATCH_ONLY:
            rows.append(
                _review_item(
                    "watch-only wallet excluded",
                    tax_file_id=tax_file.id,
                    account=account,
                    reason=REASON_WATCH_ONLY_EXCLUDED,
                    status=TAX_REVIEW_EXCLUDED,
                    message="Wallet is watch-only and excluded from tax totals.",
                    group="informational",
                )
            )

    for match in matches:
        if match.status != MATCH_SUGGESTED:
            continue
        from_account = account_by_id.get(match.from_account_id)
        to_account = account_by_id.get(match.to_account_id)
        review_id = _review_item_id(
            tax_file.id,
            match.from_account_id,
            match.from_transaction_id,
            REASON_POSSIBLE_INTERNAL_TRANSFER,
        )
        rows.append(
            {
                "id": review_id,
                "kind": "possible internal transfer awaiting confirmation",
                "title": "Possible internal transfer",
                "account_label": _pair_label(from_account, to_account),
                "account_id": match.from_account_id,
                "account_address": from_account.address if from_account is not None else "",
                "address_short": "",
                "date": "",
                "signature": match.from_transaction_id,
                "signature_short": _short(match.from_transaction_id, 8),
                "review_reason": REASON_POSSIBLE_INTERNAL_TRANSFER,
                "review_reason_label": _reason_label(REASON_POSSIBLE_INTERNAL_TRANSFER),
                "tax_review_status": TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
                "tax_review_status_label": _status_label(TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW),
                "tax_category": TAX_CATEGORY_INTERNAL_TRANSFER,
                "tax_category_label": _category_label(TAX_CATEGORY_INTERNAL_TRANSFER),
                "group": "needs_accountant_review",
                "client_question": "",
                "client_answer": "",
                "client_answer_label": "",
                "client_answered_at": "",
                "resolved_at": "",
                "resolved_by": "",
                "direction": "outgoing",
                "choices": [],
                "message": (
                    "This outgoing transfer may be an internal transfer. "
                    "Do not classify as expense until confirmed."
                ),
                "detail": (
                    "This incoming transfer may be from another wallet owned by the taxpayer. "
                    "Confirm ownership before treating as income."
                ),
                "confidence_percent": "92",
                "ai_reason": (
                    "The outgoing and incoming SOL movements occur between wallets linked to the same Tax File "
                    "within the matching window."
                ),
                "tax_impact": "No realized gain/loss if confirmed. Fees remain tracked for audit context.",
            }
        )

    if not frame.empty:
        for _, row in frame.iterrows():
            account = account_by_id.get(str(row.get("account_id") or ""))
            if account is None:
                continue
            tax_scope = str(row.get("tax_scope") or "")
            if tax_scope == TAX_SCOPE_EXCLUDED:
                rows.append(
                    _review_item_for_row(
                        tax_file_id=tax_file.id,
                        account=account,
                        row=row,
                        answer=None,
                    )
                )
                continue
            if tax_scope != TAX_SCOPE_INCLUDED:
                continue
            if bool(row.get("is_internal_transfer")):
                continue
            row_status = str(row.get("tax_review_status") or TAX_REVIEW_READY)
            if row_status in {TAX_REVIEW_READY, TAX_REVIEW_EXCLUDED}:
                continue
            review_reason = str(row.get("review_reason") or "")
            if not review_reason:
                continue
            review_id = _review_item_id(
                tax_file.id,
                account.id,
                str(row.get("signature") or ""),
                review_reason,
            )
            answer = answers_by_item.get(review_id)
            rows.append(
                _review_item_for_row(
                    tax_file_id=tax_file.id,
                    account=account,
                    row=row,
                    answer=answer,
                )
            )

    deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in rows:
        key = (
            item.get("id", item["kind"]),
            item.get("review_reason", ""),
            item.get("account_label", ""),
            item.get("signature_short", ""),
        )
        deduped.setdefault(key, item)
    return sorted(deduped.values(), key=_review_sort_key)[:120]


def _match_rows(matches: list[TransferMatch], accounts: list[Account]) -> list[dict[str, Any]]:
    by_id = {account.id: account for account in accounts}
    rows = []
    for match in matches:
        from_account = by_id.get(match.from_account_id)
        to_account = by_id.get(match.to_account_id)
        rows.append(
            {
                **match.to_dict(),
                "from_account": _account_label(from_account),
                "to_account": _account_label(to_account),
                "from_signature_short": _short(match.from_transaction_id, 8),
                "to_signature_short": _short(match.to_transaction_id, 8),
                "amount_sent_display": _format_decimal(match.amount_sent),
                "amount_received_display": _format_decimal(match.amount_received),
                "fee_display": _format_decimal(match.fee_amount),
            }
        )
    return rows


def _review_item_for_row(
    *,
    tax_file_id: str,
    account: Account,
    row: pd.Series,
    answer: ClientAnswer | None = None,
) -> dict[str, Any]:
    reason = str(row.get("review_reason") or REASON_UNKNOWN_SOURCE)
    status = str(row.get("tax_review_status") or TAX_REVIEW_READY)
    category = str(row.get("tax_category") or TAX_CATEGORY_UNKNOWN)
    direction = _row_direction(row)
    if answer is not None:
        status = answer.tax_review_status
        category = answer.tax_category
    return _review_item(
        _kind_for_reason(reason, direction, category),
        tax_file_id=tax_file_id,
        account=account,
        row=row,
        reason=reason,
        status=status,
        message=_review_message_for_row(reason, direction, category, status, row),
    )


def _review_item(
    kind: str,
    *,
    tax_file_id: str,
    account: Account,
    reason: str,
    status: str,
    message: str,
    row: pd.Series | None = None,
    group: str | None = None,
) -> dict[str, Any]:
    sig = str(row.get("signature") or "") if row is not None else ""
    review_id = _review_item_id(tax_file_id, account.id, sig or account.id, reason)
    category = str(row.get("tax_category") or TAX_CATEGORY_UNKNOWN) if row is not None else TAX_CATEGORY_UNKNOWN
    original_category = str(row.get("original_tax_category") or category) if row is not None else TAX_CATEGORY_UNKNOWN
    confidence_percent = _confidence_percent(row) if row is not None else ""
    return {
        "id": review_id,
        "kind": kind,
        "title": _title_for_reason(reason, category, kind),
        "account_label": _account_label(account),
        "account_id": account.id,
        "account_address": account.address,
        "address_short": _short(account.address, 8),
        "date": _row_date(row) if row is not None else "",
        "signature": sig,
        "signature_short": _short(sig, 8) if sig else "",
        "review_reason": reason,
        "review_reason_label": _reason_label(reason),
        "tax_review_status": status,
        "tax_review_status_label": _status_label(status),
        "tax_category": category,
        "tax_category_label": _category_label(category),
        "detected_category": _category_label(original_category),
        "detected_category_enum": original_category,
        "group": group or _review_group_for_status(status),
        "direction": _row_direction(row) if row is not None else "",
        "client_question": str(row.get("client_question") or "") if row is not None else "",
        "client_answer": str(row.get("client_answer") or "") if row is not None else "",
        "client_answer_label": _answer_label(
            str(row.get("client_answer") or ""),
            _row_direction(row),
        ) if row is not None else "",
        "client_answered_at": str(row.get("client_answered_at") or "") if row is not None else "",
        "accountant_note": str(row.get("accountant_note") or "") if row is not None else "",
        "override_applied": bool(row.get("override_applied")) if row is not None else False,
        "override_by": str(row.get("override_by") or "") if row is not None else "",
        "override_at": str(row.get("override_at") or "") if row is not None else "",
        "resolved_at": str(row.get("resolved_at") or "") if row is not None else "",
        "resolved_by": str(row.get("resolved_by") or "") if row is not None else "",
        "excluded_reason": str(row.get("excluded_reason") or "") if row is not None else "",
        "excluded_at": str(row.get("excluded_at") or "") if row is not None else "",
        "tax_scope": str(row.get("tax_scope") or TAX_SCOPE_INCLUDED) if row is not None else TAX_SCOPE_INCLUDED,
        "choices": _client_answer_choices(reason, row),
        "message": message,
        "detail": str(row.get("description") or row.get("net_flow_summary") or "") if row is not None else "",
        "confidence_percent": confidence_percent,
        "ai_reason": _tax_file_ai_explanation(row, category, status) if row is not None else "",
        "tax_impact": _tax_impact_copy(category, status),
    }


def _apply_accounting_classification(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    for idx, row in frame.iterrows():
        if str(row.get("tax_scope") or "") != TAX_SCOPE_INCLUDED:
            continue
        status = str(row.get("status") or "")
        tx_type = str(row.get("transaction_type") or "").upper()
        tag_type = str(row.get("tag_type") or "")
        source = str(row.get("source") or "").upper()
        direction = _row_direction(row)

        if status == "failed":
            _set_row_classification(
                frame,
                idx,
                TAX_CATEGORY_FAILED_FEE_ONLY,
                TAX_REVIEW_INFORMATIONAL,
                REASON_FEE_ONLY,
            )
            continue
        if tag_type == "Swap" or tx_type == "SWAP":
            _set_row_classification(
                frame,
                idx,
                TAX_CATEGORY_SWAP_TRADE,
                TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
                REASON_MISSING_COST_BASIS,
            )
            continue
        if tag_type == "Airdrop" or tx_type == "AIRDROP":
            _set_row_classification(
                frame,
                idx,
                TAX_CATEGORY_AIRDROP_REWARD,
                TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
                REASON_MISSING_FMV,
            )
            continue
        if tx_type in {"STAKE_REWARD", "STAKING_REWARD"} or tag_type == "Staking Reward":
            _set_row_classification(
                frame,
                idx,
                TAX_CATEGORY_STAKING_REWARD,
                TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
                REASON_MISSING_FMV,
            )
            continue
        if tag_type == "NFT Buy/Sell" or tx_type in {"NFT_SALE", "NFT_BUY", "NFT_MINT", "NFT_BUY_SELL"}:
            nft_category = TAX_CATEGORY_NFT_SALE if _row_direction(row) in {"incoming", "mixed"} and _to_decimal(row.get("native_in_sol")) > 0 else TAX_CATEGORY_NFT_PURCHASE
            _set_row_classification(
                frame,
                idx,
                nft_category,
                TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
                REASON_MISSING_COST_BASIS,
            )
            continue
        if tx_type in {"STAKE", "STAKE_DEPOSIT"} or "STAKE" in tag_type.upper():
            _set_row_classification(
                frame,
                idx,
                TAX_CATEGORY_STAKING_DEPOSIT,
                TAX_REVIEW_INFORMATIONAL,
                REASON_COMPLEX_DEFI,
            )
            continue
        if tag_type in {"LP Deposit/Withdraw", "Perpetual Trade", "Bridge", "Wrapped Token"} or tx_type in {"LP", "LP_DEPOSIT", "LP_WITHDRAWAL", "PERP", "BRIDGE", "WRAP_SOL", "UNWRAP_SOL"}:
            _set_row_classification(
                frame,
                idx,
                TAX_CATEGORY_DEFI_COMPLEX,
                TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
                REASON_COMPLEX_DEFI,
            )
            continue
        if source in {"COINBASE", "KRAKEN", "BINANCE", "GEMINI", "EXCHANGE"}:
            category = (
                TAX_CATEGORY_TRANSFER_FROM_EXCHANGE
                if direction == "incoming"
                else TAX_CATEGORY_TRANSFER_TO_EXCHANGE
                if direction == "outgoing"
                else TAX_CATEGORY_UNKNOWN
            )
            _set_row_classification(frame, idx, category, TAX_REVIEW_RESOLVED, None)
            continue
        if direction == "incoming" and _is_unknown_incoming(row):
            client_question = (
                TEST_CLIENT_CONFIRMATION_QUESTION
                if str(row.get("tax_file_id") or "") == TEST_TAX_FILE_ID
                else "What was the source of this incoming transfer?"
            )
            _set_row_classification(
                frame,
                idx,
                TAX_CATEGORY_UNKNOWN,
                TAX_REVIEW_NEEDS_CLIENT_ANSWER,
                REASON_UNKNOWN_SOURCE,
                client_question=client_question,
            )
            continue
        if direction == "outgoing" and _is_unknown_outgoing(row):
            _set_row_classification(
                frame,
                idx,
                TAX_CATEGORY_UNKNOWN,
                TAX_REVIEW_NEEDS_CLIENT_ANSWER,
                REASON_UNKNOWN_DESTINATION,
                client_question="What was the destination or purpose of this outgoing transfer?",
            )


def _apply_matches_to_frame(frame: pd.DataFrame, matches: list[TransferMatch]) -> None:
    for match in matches:
        if match.status not in {MATCH_CONFIRMED, MATCH_SUGGESTED}:
            continue
        for account_id, signature in (
            (match.from_account_id, match.from_transaction_id),
            (match.to_account_id, match.to_transaction_id),
        ):
            mask = (frame["account_id"] == account_id) & (frame["signature"] == signature)
            frame.loc[mask, "transfer_match_id"] = match.id
            if match.status == MATCH_CONFIRMED:
                original_mask = mask & (frame["original_tax_category"].isna() | (frame["original_tax_category"] == ""))
                frame.loc[original_mask, "original_tax_category"] = frame.loc[original_mask, "tax_category"]
                frame.loc[mask, "is_internal_transfer"] = True
                frame.loc[mask, "tax_category"] = TAX_CATEGORY_INTERNAL_TRANSFER
                frame.loc[mask, "tax_review_status"] = TAX_REVIEW_RESOLVED
                frame.loc[mask, "review_reason"] = None
                frame.loc[mask, "client_question"] = None
            else:
                frame.loc[mask, "tax_review_status"] = TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW
                frame.loc[mask, "review_reason"] = REASON_POSSIBLE_INTERNAL_TRANSFER


def _apply_client_answers_to_frame(frame: pd.DataFrame, answers: list[ClientAnswer]) -> None:
    if frame.empty or not answers:
        return
    for answer in answers:
        mask = (frame["account_id"] == answer.account_id) & (
            frame["signature"] == answer.transaction_id
        )
        if not bool(mask.any()):
            continue
        frame.loc[mask, "client_question"] = answer.client_question
        frame.loc[mask, "client_answer"] = answer.client_answer
        frame.loc[mask, "client_answered_at"] = answer.client_answered_at
        frame.loc[mask, "resolved_at"] = answer.resolved_at
        frame.loc[mask, "resolved_by"] = answer.resolved_by
        frame.loc[mask, "tax_review_status"] = answer.tax_review_status
        frame.loc[mask, "tax_category"] = answer.tax_category
        frame.loc[mask, "review_reason"] = answer.review_reason
        if answer.tax_review_status == TAX_REVIEW_RESOLVED and answer.tax_category == TAX_CATEGORY_INTERNAL_TRANSFER:
            frame.loc[mask, "is_internal_transfer"] = True


def _apply_transaction_overrides_to_frame(
    frame: pd.DataFrame,
    overrides: list[TransactionOverride],
) -> None:
    if frame.empty or not overrides:
        return
    for override in overrides:
        if override.transaction_id:
            mask = (frame["account_id"] == override.account_id) & (
                frame["signature"] == override.transaction_id
            )
        else:
            mask = frame["account_id"] == override.account_id
        if not bool(mask.any()):
            continue
        original_mask = mask & (frame["original_tax_category"].isna() | (frame["original_tax_category"] == ""))
        frame.loc[original_mask, "original_tax_category"] = frame.loc[original_mask, "tax_category"]
        frame.loc[mask, "tax_category"] = override.tax_category
        frame.loc[mask, "tax_review_status"] = override.tax_review_status
        frame.loc[mask, "review_reason"] = override.review_reason
        frame.loc[mask, "accountant_note"] = override.accountant_note
        frame.loc[mask, "override_applied"] = override.override_applied
        frame.loc[mask, "override_by"] = override.override_by
        frame.loc[mask, "override_at"] = override.override_at
        frame.loc[mask, "tax_scope"] = override.tax_scope
        frame.loc[mask, "excluded_reason"] = override.excluded_reason
        frame.loc[mask, "excluded_at"] = override.excluded_at
        frame.loc[mask, "resolved_at"] = override.resolved_at
        frame.loc[mask, "resolved_by"] = override.resolved_by
        frame.loc[mask, "reopened_at"] = override.reopened_at
        frame.loc[mask, "is_internal_transfer"] = override.tax_category == TAX_CATEGORY_INTERNAL_TRANSFER


def _set_row_classification(
    frame: pd.DataFrame,
    idx: int,
    category: str,
    status: str,
    reason: str | None,
    *,
    client_question: str | None = None,
) -> None:
    if frame.at[idx, "original_tax_category"] in (None, ""):
        frame.at[idx, "original_tax_category"] = category
    frame.at[idx, "tax_category"] = category
    frame.at[idx, "tax_review_status"] = status
    frame.at[idx, "review_reason"] = reason
    frame.at[idx, "client_question"] = client_question


def _transfer_candidates(
    frame: pd.DataFrame,
    account: Account,
    *,
    direction: str,
) -> list[_TransferCandidate]:
    if frame.empty:
        return []
    candidates: list[_TransferCandidate] = []
    for row_index, row in frame.iterrows():
        if str(row.get("status") or "") != "succeeded":
            continue
        movements = _safe_movements(row.get("movements_out" if direction == "out" else "movements_in"))
        if movements:
            for idx, movement in enumerate(movements):
                amount = _to_decimal(movement.get("amount"))
                if amount <= 0:
                    continue
                candidates.append(
                    _candidate_from_parts(
                        account,
                        row,
                        direction=direction,
                        asset=_movement_asset(movement),
                        amount=amount,
                        counterparty=str(movement.get("counterparty") or ""),
                        suffix=f"{idx}",
                    )
                )
            continue
        candidates.extend(_fallback_candidates(row, account, direction=direction, row_index=row_index))
    return candidates


def _frame_candidates(frame: pd.DataFrame) -> list[_TransferCandidate]:
    if frame.empty:
        return []
    candidates: list[_TransferCandidate] = []
    for _, group in frame.groupby("account_id"):
        first = group.iloc[0]
        account = Account(
            id=str(first.get("account_id") or ""),
            tax_file_id=str(first.get("tax_file_id") or ""),
            account_type=ACCOUNT_TYPE_SOLANA_WALLET,
            label=str(first.get("account_label") or ""),
            address=str(first.get("account_address") or ""),
            ownership_status=str(first.get("ownership_status") or OWNERSHIP_OWNED),
            source_status="active",
            created_at="",
            updated_at="",
        )
        candidates.extend(_transfer_candidates(group, account, direction="in"))
        candidates.extend(_transfer_candidates(group, account, direction="out"))
    return candidates


def _fallback_candidates(
    row: pd.Series,
    account: Account,
    *,
    direction: str,
    row_index: int,
) -> list[_TransferCandidate]:
    candidates: list[_TransferCandidate] = []
    if direction == "in":
        sol_amount = _to_decimal(row.get("native_in_sol"))
    else:
        sol_amount = _to_decimal(row.get("native_out_sol"))
    if sol_amount > 0:
        candidates.append(
            _candidate_from_parts(
                account,
                row,
                direction=direction,
                asset="SOL",
                amount=sol_amount,
                counterparty="",
                suffix=f"fallback-sol-{row_index}",
            )
        )
    for idx, flow in enumerate(_safe_movements(row.get("token_flow_details"))):
        amount = _to_decimal(flow.get("in" if direction == "in" else "out"))
        if amount <= 0:
            continue
        candidates.append(
            _candidate_from_parts(
                account,
                row,
                direction=direction,
                asset=_movement_asset(flow),
                amount=amount,
                counterparty="",
                suffix=f"fallback-token-{idx}",
            )
        )
    return candidates


def _candidate_from_parts(
    account: Account,
    row: pd.Series,
    *,
    direction: str,
    asset: str,
    amount: Decimal,
    counterparty: str,
    suffix: str,
) -> _TransferCandidate:
    signature = str(row.get("signature") or "")
    timestamp = int(row.get("timestamp_unix") or 0)
    row_key = f"{account.id}:{signature}:{direction}:{asset}:{suffix}"
    return _TransferCandidate(
        account=account,
        signature=signature,
        timestamp_unix=timestamp,
        direction=direction,
        asset=asset,
        amount=amount,
        fee_amount=_to_decimal(row.get("fee_sol")),
        counterparty=counterparty,
        row_key=row_key,
    )


def _amounts_match(out: _TransferCandidate, inc: _TransferCandidate) -> bool:
    diff = abs(out.amount - inc.amount)
    tolerance = max(out.amount.copy_abs() * Decimal("0.001"), Decimal("0.000001"))
    if diff <= tolerance:
        return True
    if out.asset == "SOL" and out.amount >= inc.amount:
        return (out.amount - inc.amount) <= max(out.fee_amount, tolerance)
    return False


def _confidence(out: _TransferCandidate, inc: _TransferCandidate) -> str:
    direct_addresses = (
        out.counterparty == inc.account.address and inc.counterparty == out.account.address
    )
    if out.signature and out.signature == inc.signature:
        return "high"
    if direct_addresses:
        return "high"
    if abs(out.amount - inc.amount) <= max(out.amount * Decimal("0.001"), Decimal("0.000001")):
        return "medium"
    return "low"


def _match_id(tax_file_id: str, out: _TransferCandidate, inc: _TransferCandidate) -> str:
    raw = "|".join(
        [
            tax_file_id,
            out.account.id,
            inc.account.id,
            out.signature,
            inc.signature,
            out.asset,
            _decimal_to_storage(out.amount),
            _decimal_to_storage(inc.amount),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _match_key(match: TransferMatch, *, direction: str) -> tuple[str, str, str]:
    if direction == "out":
        return (match.from_account_id, match.from_transaction_id, "out")
    return (match.to_account_id, match.to_transaction_id, "in")


def _is_unknown_incoming(row: pd.Series) -> bool:
    if str(row.get("review_reason") or "") == REASON_POSSIBLE_INTERNAL_TRANSFER:
        return False
    if _to_decimal(row.get("native_in_sol")) <= 0 and not _has_token_direction(row, "in"):
        return False
    return str(row.get("source") or "").upper() in {"", "UNKNOWN"} or not _safe_movements(row.get("movements_in"))


def _is_unknown_outgoing(row: pd.Series) -> bool:
    if str(row.get("review_reason") or "") == REASON_POSSIBLE_INTERNAL_TRANSFER:
        return False
    if _to_decimal(row.get("native_out_sol")) <= 0 and not _has_token_direction(row, "out"):
        return False
    movements = _safe_movements(row.get("movements_out"))
    if not movements:
        return True
    return any(not str(movement.get("counterparty") or "").strip() for movement in movements)


def _has_token_direction(row: pd.Series, direction: str) -> bool:
    key = "in" if direction == "in" else "out"
    return any(_to_decimal(flow.get(key)) > 0 for flow in _safe_movements(row.get("token_flow_details")))


def _row_direction(row: pd.Series | None) -> str:
    if row is None:
        return ""
    incoming = _to_decimal(row.get("native_in_sol")) > 0 or _has_token_direction(row, "in")
    outgoing = _to_decimal(row.get("native_out_sol")) > 0 or _has_token_direction(row, "out")
    if incoming and not outgoing:
        return "incoming"
    if outgoing and not incoming:
        return "outgoing"
    if incoming and outgoing:
        return "mixed"
    return "fee_only"


def _client_answer_treatment(direction: str, client_answer: str) -> tuple[str, str]:
    if client_answer == "unknown":
        return TAX_REVIEW_BLOCKED_MISSING_DATA, TAX_CATEGORY_UNKNOWN
    if direction == "incoming":
        if client_answer == "own_wallet":
            return TAX_REVIEW_RESOLVED, TAX_CATEGORY_INTERNAL_TRANSFER
        if client_answer in {"exchange", "bought_crypto"}:
            return TAX_REVIEW_RESOLVED, TAX_CATEGORY_TRANSFER_FROM_EXCHANGE
        if client_answer == "airdrop_reward":
            return TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW, TAX_CATEGORY_AIRDROP_REWARD
        return TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW, TAX_CATEGORY_UNKNOWN
    if direction == "outgoing":
        if client_answer == "own_wallet":
            return TAX_REVIEW_RESOLVED, TAX_CATEGORY_INTERNAL_TRANSFER
        if client_answer == "exchange":
            return TAX_REVIEW_RESOLVED, TAX_CATEGORY_TRANSFER_TO_EXCHANGE
        if client_answer == "sold_crypto":
            return TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW, TAX_CATEGORY_SWAP_TRADE
        return TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW, TAX_CATEGORY_UNKNOWN
    return TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW, TAX_CATEGORY_UNKNOWN


def _review_item_id(tax_file_id: str, account_id: str, signature: str, reason: str) -> str:
    raw = "|".join([tax_file_id, account_id, signature, reason])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def _review_groups(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "needs_client_answer": [],
        "needs_accountant_review": [],
        "resolved": [],
        "informational": [],
        "excluded": [],
    }
    for item in items:
        groups[_review_group_for_status(str(item.get("tax_review_status") or ""))].append(item)
    return groups


def _filing_blockers(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocker_reasons = {
        REASON_OWNERSHIP_UNKNOWN,
        REASON_UNKNOWN_SOURCE,
        REASON_UNKNOWN_DESTINATION,
        REASON_POSSIBLE_INTERNAL_TRANSFER,
        REASON_MISSING_COST_BASIS,
        REASON_MISSING_FMV,
    }
    return [item for item in items if item.get("review_reason") in blocker_reasons]


def _review_group_for_status(status: str) -> str:
    if status in {TAX_REVIEW_RESOLVED, TAX_REVIEW_READY}:
        return "resolved"
    if status == TAX_REVIEW_EXCLUDED:
        return "excluded"
    if status == TAX_REVIEW_INFORMATIONAL:
        return "informational"
    if status in {TAX_REVIEW_NEEDS_CLIENT_ANSWER, TAX_REVIEW_BLOCKED_MISSING_DATA}:
        return "needs_client_answer"
    return "needs_accountant_review"


def _review_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    priority = {
        "needs_client_answer": 0,
        "needs_accountant_review": 1,
        "informational": 2,
        "excluded": 3,
        "resolved": 4,
    }
    return (
        priority.get(str(item.get("group") or ""), 9),
        str(item.get("date") or "9999-12-31"),
        str(item.get("signature_short") or ""),
    )


def _client_answer_choices(reason: str, row: pd.Series | None) -> list[dict[str, str]]:
    if reason == REASON_UNKNOWN_SOURCE:
        if row is not None and str(row.get("tax_file_id") or "") == TEST_TAX_FILE_ID:
            return _answer_options((("own_wallet", TEST_CLIENT_CONFIRMATION_ANSWER),))
        return _answer_options(INCOMING_CLIENT_ANSWER_OPTIONS)
    if reason == REASON_UNKNOWN_DESTINATION:
        return _answer_options(OUTGOING_CLIENT_ANSWER_OPTIONS)
    direction = _row_direction(row)
    if direction == "incoming":
        return _answer_options(INCOMING_CLIENT_ANSWER_OPTIONS)
    if direction == "outgoing":
        return _answer_options(OUTGOING_CLIENT_ANSWER_OPTIONS)
    return []


def _answer_options(options: tuple[tuple[str, str], ...]) -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in options]


def _answer_label(answer: str, direction: str = "") -> str:
    if direction == "incoming":
        labels = dict(INCOMING_CLIENT_ANSWER_OPTIONS)
    elif direction == "outgoing":
        labels = dict(OUTGOING_CLIENT_ANSWER_OPTIONS)
    else:
        labels = dict(INCOMING_CLIENT_ANSWER_OPTIONS) | dict(OUTGOING_CLIENT_ANSWER_OPTIONS)
    return labels.get(answer, answer.replace("_", " ").title() if answer else "")


def _kind_for_reason(reason: str, direction: str, category: str) -> str:
    if category == TAX_CATEGORY_STAKING_DEPOSIT:
        return "staking deposit note"
    if reason == REASON_UNKNOWN_SOURCE:
        return "unknown incoming transfer"
    if reason == REASON_UNKNOWN_DESTINATION:
        return "unknown outgoing transfer"
    if reason == REASON_MISSING_COST_BASIS and category == TAX_CATEGORY_NFT_SALE:
        return "NFT sale cost basis review"
    if reason == REASON_MISSING_COST_BASIS:
        return "swap cost basis review"
    if reason == REASON_MISSING_FMV:
        return "airdrop FMV review"
    if reason == REASON_COMPLEX_DEFI:
        return "DeFi activity review"
    if reason == REASON_FEE_ONLY:
        return "failed transaction fee"
    if direction == "incoming":
        return "incoming transfer review"
    if direction == "outgoing":
        return "outgoing transfer review"
    return "review item"


def _title_for_reason(reason: str, category: str, fallback: str) -> str:
    if category == TAX_CATEGORY_STAKING_DEPOSIT:
        return "Staking deposit note"
    if reason == REASON_UNKNOWN_SOURCE:
        return "Unknown incoming source"
    if reason == REASON_UNKNOWN_DESTINATION:
        return "Unknown outgoing destination"
    if reason == REASON_POSSIBLE_INTERNAL_TRANSFER:
        return "Possible internal transfer"
    if reason == REASON_MISSING_COST_BASIS and category == TAX_CATEGORY_NFT_SALE:
        return "NFT sale missing acquisition lot"
    if reason == REASON_MISSING_COST_BASIS:
        return "Missing acquisition lot"
    if reason == REASON_MISSING_FMV:
        return "USD FMV needed"
    if reason == REASON_COMPLEX_DEFI:
        return "Complex DeFi review"
    if reason == REASON_FEE_ONLY:
        return "Fee-only failed transaction"
    if reason == REASON_OWNERSHIP_UNKNOWN:
        return "Missing wallet ownership"
    if reason == REASON_WATCH_ONLY_EXCLUDED:
        return "Watch-only excluded"
    return fallback.title()


def _review_message(reason: str, direction: str, category: str, status: str) -> str:
    if status == TAX_REVIEW_RESOLVED:
        return "Client answer recorded. This item is no longer blocking the active review queue."
    if status == TAX_REVIEW_EXCLUDED:
        return "Transaction excluded from this Tax File. Raw wallet data was kept."
    if category == TAX_CATEGORY_STAKING_DEPOSIT:
        return "Staking deposit is likely non-taxable if no receipt token was received. Confirm this before filing."
    if reason == REASON_UNKNOWN_SOURCE:
        return "This incoming transfer needs a client answer before it can be classified."
    if reason == REASON_UNKNOWN_DESTINATION:
        return "This outgoing transfer needs a client answer before assigning tax treatment."
    if reason == REASON_MISSING_COST_BASIS and category == TAX_CATEGORY_NFT_SALE:
        return "Missing acquisition lot for the asset disposed in this transaction. Add exchange history, manual purchase data, or mark the basis as unknown before relying on tax totals."
    if reason == REASON_MISSING_COST_BASIS:
        return "Missing acquisition lot for the asset disposed in this transaction. Add exchange history, manual purchase data, or mark the basis as unknown before relying on tax totals."
    if reason == REASON_MISSING_FMV:
        return "Airdrop/reward detected. USD fair market value at receipt needs review."
    if reason == REASON_COMPLEX_DEFI:
        return "Protocol activity needs accountant review before it is included in filing totals."
    if reason == REASON_FEE_ONLY:
        return "Failed transaction. No asset movement was counted; network fee remains visible."
    return "Review this item before relying on the tax file."


def _review_message_for_row(
    reason: str,
    direction: str,
    category: str,
    status: str,
    row: pd.Series,
) -> str:
    if reason == REASON_MISSING_COST_BASIS and status not in {TAX_REVIEW_RESOLVED, TAX_REVIEW_EXCLUDED}:
        return _missing_acquisition_lot_message_for_row(row)
    return _review_message(reason, direction, category, status)


def _missing_acquisition_lot_message_for_row(row: pd.Series) -> str:
    disposed_assets = _cost_basis_disposed_assets(row)
    disposed_on = _row_date(row)
    for item in disposed_assets:
        amount = _to_decimal(item.get("amount"))
        asset = str(item.get("asset") or "")
        if amount > 0 and asset and disposed_on:
            return _missing_acquisition_lot_message_from_values(
                asset=asset,
                amount=amount,
                disposed_on=disposed_on,
            )
    return _missing_acquisition_lot_generic_message()


def _missing_acquisition_lot_message_from_values(*, asset: str, amount: Decimal, disposed_on: str) -> str:
    if amount > 0 and asset and disposed_on:
        return (
            f"Missing acquisition lot for {_format_decimal(amount)} {asset} disposed on {disposed_on}. "
            "Add exchange history, manual purchase data, or mark the basis as unknown before relying on tax totals."
        )
    return _missing_acquisition_lot_generic_message()


def _missing_acquisition_lot_generic_message() -> str:
    return (
        "Missing acquisition lot for the asset disposed in this transaction. Add exchange history, manual "
        "purchase data, or mark the basis as unknown before relying on tax totals."
    )


def _reason_label(reason: str) -> str:
    labels = {
        REASON_UNKNOWN_SOURCE: "Unknown source",
        REASON_UNKNOWN_DESTINATION: "Unknown destination",
        REASON_POSSIBLE_INTERNAL_TRANSFER: "Possible internal transfer",
        REASON_MISSING_COST_BASIS: "Missing acquisition lot",
        REASON_MISSING_FMV: "Missing USD FMV",
        REASON_COMPLEX_DEFI: "Complex DeFi",
        REASON_FAILED_TRANSACTION: "Failed transaction",
        REASON_WATCH_ONLY_EXCLUDED: "Watch-only excluded",
        REASON_OWNERSHIP_UNKNOWN: "Ownership unknown",
        REASON_FEE_ONLY: "Fee only",
    }
    return labels.get(reason, reason.replace("_", " ").title())


def _status_label(status: str) -> str:
    labels = {
        TAX_REVIEW_READY: "Ready",
        TAX_REVIEW_NEEDS_CLIENT_ANSWER: "Needs client answer",
        TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW: "Needs accountant review",
        TAX_REVIEW_BLOCKED_MISSING_DATA: "Blocked: missing data",
        TAX_REVIEW_RESOLVED: "Resolved",
        TAX_REVIEW_INFORMATIONAL: "Informational",
        TAX_REVIEW_EXCLUDED: "Excluded",
    }
    return labels.get(status, status.replace("_", " ").title())


def _category_label(category: str) -> str:
    labels = {
        TAX_CATEGORY_INTERNAL_TRANSFER: "Internal transfer",
        TAX_CATEGORY_TRANSFER_FROM_EXCHANGE: "Transfer from exchange",
        TAX_CATEGORY_TRANSFER_TO_EXCHANGE: "Transfer to exchange",
        TAX_CATEGORY_BUY: "Buy / acquisition",
        TAX_CATEGORY_SELL: "Sale / disposal",
        TAX_CATEGORY_SWAP_TRADE: "Swap / trade",
        TAX_CATEGORY_AIRDROP_REWARD: "Airdrop / reward",
        TAX_CATEGORY_STAKING_REWARD: "Staking reward",
        TAX_CATEGORY_NFT_PURCHASE: "NFT mint / purchase",
        TAX_CATEGORY_NFT_SALE: "NFT sale",
        TAX_CATEGORY_STAKING_DEPOSIT: "Staking deposit",
        TAX_CATEGORY_FAILED_FEE_ONLY: "Failed fee-only",
        TAX_CATEGORY_DEFI_COMPLEX: "DeFi / bridge review",
        TAX_CATEGORY_UNKNOWN: "Unknown",
    }
    return labels.get(category, category.replace("_", " ").title())


def _cached_wallet_rows(cache_root: Path, accounts: list[Account]) -> list[dict[str, Any]]:
    linked = {account.address for account in accounts}
    rows = []
    demo_wallet_index = 0
    for wallet in cache_mod.list_wallets(cache_root=cache_root):
        address = str(getattr(wallet, "address", ""))
        dataset_label = str(getattr(wallet, "dataset_label", "") or "")
        public_dataset_label = _public_dataset_label(dataset_label)
        address_short = _short(address, 8)
        display_label = address_short
        if public_dataset_label == "2025 US taxpayer story":
            demo_wallet_index += 1
            display_label = f"Solana Wallet {demo_wallet_index}"
        rows.append(
            {
                "address": address,
                "address_short": address_short,
                "display_label": display_label,
                "dataset_label": public_dataset_label,
                "row_count": int(getattr(wallet, "row_count", 0) or 0),
                "earliest_tx": str(getattr(wallet, "earliest_tx", "") or ""),
                "latest_tx": str(getattr(wallet, "latest_tx", "") or ""),
                "linked": address in linked,
            }
        )
    return rows


def _public_dataset_label(value: str) -> str:
    return str(value or "").replace("Demo dataset: ", "").replace("Synthetic demo data", "Sample wallet activity")


def _read_cache(address: str, cache_root: Path) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    try:
        return cache_mod.read(address, cache_root=cache_root)
    except Exception:
        return None


def _cached_row_count(address: str, cache_root: Path) -> int:
    cached = _read_cache(address, cache_root)
    if cached is None:
        return 0
    frame, meta = cached
    return int(meta.get("row_count") or len(frame))


def _ensure_transaction_extensions(frame: pd.DataFrame) -> pd.DataFrame:
    for column in _TRANSACTION_EXTENSION_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    return frame


def _tax_scope_for_account(account: Account) -> str:
    if account.ownership_status == OWNERSHIP_OWNED:
        return TAX_SCOPE_INCLUDED
    if account.ownership_status == OWNERSHIP_WATCH_ONLY:
        return TAX_SCOPE_WATCH_ONLY
    return TAX_SCOPE_EXCLUDED


def _tax_review_status_for_account(account: Account) -> str:
    if account.ownership_status == OWNERSHIP_OWNED:
        return TAX_REVIEW_READY
    if account.ownership_status == OWNERSHIP_UNKNOWN:
        return TAX_REVIEW_BLOCKED_MISSING_DATA
    return TAX_REVIEW_EXCLUDED


def _review_reason_for_account(account: Account) -> str | None:
    if account.ownership_status == OWNERSHIP_WATCH_ONLY:
        return REASON_WATCH_ONLY_EXCLUDED
    if account.ownership_status == OWNERSHIP_UNKNOWN:
        return REASON_OWNERSHIP_UNKNOWN
    return None


def _movement_asset(movement: dict[str, Any]) -> str:
    if str(movement.get("asset_type") or "") == "native":
        return "SOL"
    return str(movement.get("mint") or movement.get("symbol") or "UNKNOWN_TOKEN")


def _asset_label(asset: str) -> str:
    if asset == "SOL":
        return "SOL"
    if len(asset) > 16:
        return f"Token ({_short(asset, 6)})"
    return asset


def _tax_readiness_counts(
    accounts: list[Account],
    matches: list[TransferMatch],
    frame: pd.DataFrame,
    active_review_queue: list[dict[str, Any]],
    review_queue: list[dict[str, Any]],
    cost_basis: list[dict[str, Any]],
) -> dict[str, int]:
    reason_counts = _review_reason_counts(active_review_queue)
    missing_cost_basis = max(
        reason_counts.get(REASON_MISSING_COST_BASIS, 0),
        _cost_basis_status_count(cost_basis, "Needs cost basis"),
    )
    missing_fmv = max(
        reason_counts.get(REASON_MISSING_FMV, 0),
        _cost_basis_status_count(cost_basis, "Needs FMV"),
    )
    unresolved_nft_sales = _active_category_count(active_review_queue, {TAX_CATEGORY_NFT_SALE})
    unresolved_airdrops_rewards = _active_category_count(
        active_review_queue,
        {TAX_CATEGORY_AIRDROP_REWARD, TAX_CATEGORY_STAKING_REWARD},
    )
    informational = sum(1 for item in review_queue if item.get("tax_review_status") == TAX_REVIEW_INFORMATIONAL)
    blocker_count = len(_filing_blockers(active_review_queue))
    return {
        "blocking_items": blocker_count,
        "missing_cost_basis": missing_cost_basis,
        "unknown_outgoing": reason_counts.get(REASON_UNKNOWN_DESTINATION, 0),
        "missing_fmv": missing_fmv,
        "unresolved_nft_sales": unresolved_nft_sales,
        "unresolved_airdrops_rewards": unresolved_airdrops_rewards,
        "unresolved_informational": informational,
        "unknown_incoming": reason_counts.get(REASON_UNKNOWN_SOURCE, 0),
        "possible_internal_transfers": reason_counts.get(REASON_POSSIBLE_INTERNAL_TRANSFER, 0),
        "ownership_unknown": reason_counts.get(REASON_OWNERSHIP_UNKNOWN, 0),
    }


def _review_reason_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        reason = str(item.get("review_reason") or "")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def _active_category_count(items: list[dict[str, Any]], categories: set[str]) -> int:
    return sum(1 for item in items if item.get("tax_category") in categories)


def _tax_readiness_label(score: int, blocking_items: int) -> str:
    if score >= 90 and blocking_items == 0:
        return "Ready for accountant review"
    if score >= 70:
        return "Minor review needed"
    if score >= 40:
        return "Draft review"
    return "Blocked"


def _tax_readiness_status_class(score: int, blocking_items: int) -> str:
    if score >= 90 and blocking_items == 0:
        return "confirmed"
    if score >= 40:
        return "warning"
    return "failed"


def _tax_readiness_explanation(score: int, blocking_items: int) -> str:
    if score >= 90 and blocking_items == 0:
        return "No active blockers remain. The file is ready for accountant review, subject to professional judgment."
    if blocking_items == 1:
        return "1 blocker needs resolution before relying on draft tax totals."
    if blocking_items > 1:
        return f"{blocking_items} blockers need resolution before relying on draft tax totals."
    return "No filing blockers remain, but review notes still reduce the readiness score."


def _checklist_row(task: str, status: str, note: str) -> dict[str, str]:
    return {
        "task": task,
        "status": status,
        "status_class": _checklist_status_class(status),
        "note": note,
    }


def _checklist_status_class(status: str) -> str:
    if status == "Done":
        return "confirmed"
    if status == "Blocked":
        return "failed"
    if status == "Not applicable":
        return "neutral"
    return "warning"


def _cost_basis_status_count(cost_basis: list[dict[str, Any]], status: str) -> int:
    return sum(1 for row in cost_basis if row.get("status") == status)


def _frame_has_category(frame: pd.DataFrame, category: str) -> bool:
    return _frame_has_any_category(frame, {category})


def _frame_has_any_category(frame: pd.DataFrame, categories: set[str]) -> bool:
    if frame.empty or "tax_category" not in frame.columns:
        return False
    return any(str(value) in categories for value in frame["tax_category"])


def _failed_rows(frame: pd.DataFrame) -> list[pd.Series]:
    if frame.empty or "status" not in frame.columns:
        return []
    return [row for _, row in frame.iterrows() if str(row.get("status") or "") == "failed"]


def _primary_next_action(
    *,
    blockers: int,
    client_questions: int,
    cost_basis_issues: int,
    missing_fmv_issues: int,
    readiness_score: int,
) -> str:
    if cost_basis_issues:
        return (
            f"Resolve {_count_phrase(cost_basis_issues, 'missing acquisition lot / cost basis issue')} "
            "before relying on tax totals."
        )
    if client_questions:
        return f"Answer {_count_phrase(client_questions, 'client question')} before professional review."
    if missing_fmv_issues:
        return f"Verify {_count_phrase(missing_fmv_issues, 'FMV/proceeds issue')} before relying on tax totals."
    if blockers:
        return f"Resolve {_count_phrase(blockers, 'filing blocker')} before relying on draft exports."
    if readiness_score >= 90:
        return "Complete accountant sign-off after final professional review."
    return "Review checklist items before treating the draft export as supportable."


def _loss_harvesting_review_guardrails() -> list[dict[str, str]]:
    return [
        {
            "guardrail": "Cost basis confirmed",
            "status": "Needs review",
            "status_class": "warning",
            "note": "Estimated or missing acquisition data may be used",
        },
        {
            "guardrail": "FMV confirmed",
            "status": "Needs review",
            "status_class": "warning",
            "note": "Price source must be verified",
        },
        {
            "guardrail": "Fees/slippage checked",
            "status": "Not checked",
            "status_class": "neutral",
            "note": "Execution costs are not guaranteed",
        },
        {
            "guardrail": "Liquidity checked",
            "status": "Not checked",
            "status_class": "neutral",
            "note": "Market depth is not verified",
        },
        {
            "guardrail": "Legal/tax review completed",
            "status": "Required",
            "status_class": "failed",
            "note": "Final treatment requires professional review",
        },
        {
            "guardrail": "Re-entry risk reviewed",
            "status": "Required",
            "status_class": "failed",
            "note": "User may not regain the same market exposure",
        },
    ]


def _count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _cost_basis_lots(tax_file: TaxFile | dict[str, Any], frame: pd.DataFrame) -> list[dict[str, Any]]:
    tax_file_id = _tax_file_identifier(tax_file)
    lots = [_cost_basis_lot_from_manual(raw) for raw in DEMO_MANUAL_COST_BASIS_LOTS if raw["tax_file_id"] == tax_file_id]
    manual_keys = {(lot["asset"], lot["acquired_on"]) for lot in lots}
    acquisition_categories = {
        TAX_CATEGORY_TRANSFER_FROM_EXCHANGE,
        TAX_CATEGORY_BUY,
        TAX_CATEGORY_NFT_PURCHASE,
        TAX_CATEGORY_AIRDROP_REWARD,
        TAX_CATEGORY_STAKING_REWARD,
        TAX_CATEGORY_PAYMENT_FOR_SERVICES,
    }

    for _, row in frame.sort_values("timestamp_unix", ascending=True, kind="stable").iterrows():
        if not _cost_basis_row_is_usable(row):
            continue
        category = str(row.get("tax_category") or TAX_CATEGORY_UNKNOWN)
        if category not in acquisition_categories:
            continue
        acquired_on = _row_date(row)
        signature = str(row.get("signature") or "")

        native_amount = _cost_basis_native_acquired_amount(row)
        if native_amount > 0 and ("SOL", acquired_on) not in manual_keys:
            lots.append(
                _cost_basis_lot(
                    asset="SOL",
                    acquired_on=acquired_on,
                    amount=native_amount,
                    cost_basis=_cost_basis_value_from_row(row),
                    fees=_cost_basis_fee_value_from_row(row),
                    source=_category_label(category),
                    category=category,
                    signature=signature,
                )
            )

        for flow in _safe_movements(row.get("token_flow_details")):
            amount = _to_decimal(flow.get("in"))
            if amount <= 0:
                continue
            asset = _cost_basis_flow_asset(flow)
            if (asset, acquired_on) in manual_keys:
                continue
            lots.append(
                _cost_basis_lot(
                    asset=asset,
                    acquired_on=acquired_on,
                    amount=amount,
                    cost_basis=_cost_basis_value_from_row(row),
                    fees=_cost_basis_fee_value_from_row(row),
                    source=_category_label(category),
                    category=category,
                    signature=signature,
                )
            )

    lots.sort(key=lambda lot: (lot["acquired_on"], 0 if lot["source"] == "manual lot" else 1, lot["id"]))
    return lots


def _cost_basis_dispositions(tax_file: TaxFile | dict[str, Any], frame: pd.DataFrame) -> list[dict[str, Any]]:
    tax_file_id = _tax_file_identifier(tax_file)
    rows: list[dict[str, Any]] = []
    for _, row in frame.sort_values("timestamp_unix", ascending=True, kind="stable").iterrows():
        if not _cost_basis_row_is_usable(row):
            continue
        category = str(row.get("tax_category") or TAX_CATEGORY_UNKNOWN)
        if not _cost_basis_disposition_category(category, row):
            continue
        signature = str(row.get("signature") or "")
        disposed_on = _row_date(row)
        proceeds_fmv = _cost_basis_proceeds_fmv(tax_file_id, row)
        for disposed in _cost_basis_disposed_assets(row):
            rows.append(
                {
                    "asset": disposed["asset"],
                    "amount": disposed["amount"],
                    "disposed_on": disposed_on,
                    "signature": signature,
                    "signature_short": _short(signature, 8) if signature else "",
                    "category": category,
                    "proceeds_fmv": proceeds_fmv,
                }
            )
    return rows


def _cost_basis_lot_from_manual(raw: dict[str, Any]) -> dict[str, Any]:
    return _cost_basis_lot(
        asset=str(raw["asset"]),
        acquired_on=str(raw["acquired_on"]),
        amount=_to_decimal(raw["amount"]),
        cost_basis=_to_decimal(raw["cost_basis"]),
        fees=_to_decimal(raw["fees"]),
        source=str(raw.get("source") or "manual lot"),
        category="manual_lot",
        signature="manual",
    )


def _cost_basis_lot(
    *,
    asset: str,
    acquired_on: str,
    amount: Decimal,
    cost_basis: Decimal | None,
    fees: Decimal | None,
    source: str,
    category: str,
    signature: str,
) -> dict[str, Any]:
    lot_id_raw = "|".join([asset, acquired_on, _decimal_to_storage(amount), source, signature])
    return {
        "id": hashlib.sha1(lot_id_raw.encode("utf-8")).hexdigest()[:24],
        "asset": asset,
        "acquired_on": acquired_on,
        "amount": amount,
        "cost_basis": cost_basis,
        "fees": fees,
        "source": source,
        "category": category,
        "signature": signature,
        "disposed_total": Decimal("0"),
    }


def _cost_basis_allocation_row(
    lot: dict[str, Any],
    disposition: dict[str, Any],
    disposed_amount: Decimal,
) -> dict[str, Any]:
    remaining = lot["amount"] - lot["disposed_total"]
    allocated_basis = _allocate_cost_basis_value(lot["cost_basis"], lot["amount"], disposed_amount)
    allocated_fees = _allocate_cost_basis_value(lot["fees"], lot["amount"], disposed_amount)
    allocated_proceeds = _allocate_cost_basis_value(disposition["proceeds_fmv"], disposition["amount"], disposed_amount)
    realized = None
    if allocated_basis is not None and allocated_fees is not None and allocated_proceeds is not None:
        realized = allocated_proceeds - allocated_basis - allocated_fees
    missing = _cost_basis_missing_parts(lot, disposition)
    status = _cost_basis_status(lot, disposition)
    holding_days = _holding_period_days(lot["acquired_on"], disposition["disposed_on"])
    holding_period = _holding_period_label(holding_days)
    return {
        "lot_id": lot["id"],
        "asset": lot["asset"],
        "lot_acquired": lot["acquired_on"],
        "amount_acquired": _format_decimal(lot["amount"]),
        "cost_basis": _cost_basis_money(lot["cost_basis"]),
        "allocated_cost_basis": _cost_basis_money(allocated_basis) if allocated_basis is not None else "",
        "allocated_cost_basis_amount": _decimal_to_storage(allocated_basis) if allocated_basis is not None else "",
        "fees": _cost_basis_money(lot["fees"]),
        "allocated_fees_amount": _decimal_to_storage(allocated_fees) if allocated_fees is not None else "",
        "disposed": _format_decimal(disposed_amount),
        "remaining": _format_decimal(max(remaining, Decimal("0"))),
        "method": COST_BASIS_METHOD_FIFO,
        "status": status,
        "status_class": _cost_basis_status_class(status),
        "missing_data": _cost_basis_missing_text(missing),
        "disposal_date": disposition["disposed_on"],
        "transaction_id": disposition["signature"],
        "signature_short": disposition["signature_short"],
        "proceeds_usd": _cost_basis_money(allocated_proceeds) if allocated_proceeds is not None else "",
        "proceeds_usd_amount": _decimal_to_storage(allocated_proceeds) if allocated_proceeds is not None else "",
        "realized_gain_loss": _cost_basis_money(realized) if realized is not None else "",
        "gain_loss_usd_amount": _decimal_to_storage(realized) if realized is not None else "",
        "holding_period_days": str(holding_days) if holding_days is not None else "",
        "holding_period": holding_period,
        "source": lot["source"],
    }


def _cost_basis_missing_lot_row(disposition: dict[str, Any], amount: Decimal) -> dict[str, Any]:
    message = _missing_acquisition_lot_message_from_values(
        asset=disposition["asset"],
        amount=amount,
        disposed_on=disposition["disposed_on"],
    )
    missing = [message]
    if disposition["proceeds_fmv"] is None:
        missing.append("Disposal FMV/proceeds")
    return {
        "lot_id": "",
        "asset": disposition["asset"],
        "lot_acquired": "Missing acquisition lot",
        "amount_acquired": "0",
        "cost_basis": "Missing",
        "allocated_cost_basis": "Missing",
        "allocated_cost_basis_amount": "",
        "fees": "-",
        "allocated_fees_amount": "",
        "disposed": _format_decimal(amount),
        "remaining": "0",
        "method": COST_BASIS_METHOD_FIFO,
        "status": "Needs cost basis",
        "status_class": "warning",
        "missing_data": _cost_basis_missing_text(missing),
        "disposal_date": disposition["disposed_on"],
        "transaction_id": disposition["signature"],
        "signature_short": disposition["signature_short"],
        "proceeds_usd": _cost_basis_money(disposition["proceeds_fmv"]) if disposition["proceeds_fmv"] is not None else "",
        "proceeds_usd_amount": _decimal_to_storage(disposition["proceeds_fmv"]) if disposition["proceeds_fmv"] is not None else "",
        "realized_gain_loss": "",
        "gain_loss_usd_amount": "",
        "holding_period_days": "",
        "holding_period": "Missing basis",
        "source": "unmatched disposal",
    }


def _cost_basis_unmatched_acquisition_row(lot: dict[str, Any]) -> dict[str, Any]:
    disposition = {
        "amount": Decimal("0"),
        "disposed_on": "",
        "signature": "",
        "signature_short": "",
        "proceeds_fmv": Decimal("0"),
    }
    status = _cost_basis_status(lot, disposition)
    return {
        "lot_id": lot["id"],
        "asset": lot["asset"],
        "lot_acquired": lot["acquired_on"],
        "amount_acquired": _format_decimal(lot["amount"]),
        "cost_basis": _cost_basis_money(lot["cost_basis"]),
        "allocated_cost_basis": "",
        "allocated_cost_basis_amount": "",
        "fees": _cost_basis_money(lot["fees"]),
        "allocated_fees_amount": "",
        "disposed": "0",
        "remaining": _format_decimal(lot["amount"] - lot["disposed_total"]),
        "method": COST_BASIS_METHOD_FIFO,
        "status": status,
        "status_class": _cost_basis_status_class(status),
        "missing_data": _cost_basis_missing_text(_cost_basis_missing_parts(lot, disposition)),
        "disposal_date": "",
        "transaction_id": "",
        "signature_short": "",
        "proceeds_usd": "",
        "proceeds_usd_amount": "",
        "realized_gain_loss": "",
        "gain_loss_usd_amount": "",
        "holding_period_days": "",
        "holding_period": "",
        "source": lot["source"],
    }


def _cost_basis_row_is_usable(row: pd.Series) -> bool:
    if str(row.get("status") or "") != "succeeded":
        return False
    if str(row.get("tax_scope") or TAX_SCOPE_INCLUDED) != TAX_SCOPE_INCLUDED:
        return False
    return not bool(row.get("is_internal_transfer"))


def _cost_basis_disposition_category(category: str, row: pd.Series) -> bool:
    if category in {
        TAX_CATEGORY_SELL,
        TAX_CATEGORY_SWAP_TRADE,
        TAX_CATEGORY_NFT_SALE,
        TAX_CATEGORY_TRANSFER_TO_EXCHANGE,
        TAX_CATEGORY_PAYMENT_FOR_SERVICES,
    }:
        return True
    return category == TAX_CATEGORY_UNKNOWN and _row_direction(row) in {"outgoing", "mixed"}


def _cost_basis_native_acquired_amount(row: pd.Series) -> Decimal:
    native_in = _to_decimal(row.get("native_in_sol"))
    if native_in <= 0:
        return Decimal("0")
    native_net = _to_decimal(row.get("native_net_sol"))
    if native_net > 0 and bool(row.get("fee_paid_by_wallet")):
        return native_net
    return native_in


def _cost_basis_disposed_assets(row: pd.Series) -> list[dict[str, Any]]:
    disposed: list[dict[str, Any]] = []
    native_out = _to_decimal(row.get("native_out_sol"))
    if native_out > 0:
        disposed.append({"asset": "SOL", "amount": native_out})
    for flow in _safe_movements(row.get("token_flow_details")):
        amount = _to_decimal(flow.get("out"))
        if amount <= 0:
            continue
        disposed.append({"asset": _cost_basis_flow_asset(flow), "amount": amount})
    return disposed


def _cost_basis_flow_asset(flow: dict[str, Any]) -> str:
    return str(flow.get("symbol") or flow.get("mint") or "UNKNOWN_TOKEN")


def _cost_basis_value_from_row(row: pd.Series) -> Decimal | None:
    value = _to_decimal(row.get("tag_usd_estimate"))
    return value if value > 0 else None


def _cost_basis_fee_value_from_row(row: pd.Series) -> Decimal | None:
    if _to_decimal(row.get("fee_sol")) == 0:
        return Decimal("0")
    return None


def _cost_basis_proceeds_fmv(tax_file_id: str, row: pd.Series) -> Decimal | None:
    signature = str(row.get("signature") or "")
    for disposed in _cost_basis_disposed_assets(row):
        manual = DEMO_MANUAL_DISPOSAL_FMV_USD.get((tax_file_id, signature, disposed["asset"]))
        if manual is not None:
            return manual
    tag_value = _cost_basis_value_from_row(row)
    if tag_value is not None:
        return tag_value
    stablecoin_value = _cost_basis_stablecoin_value(row)
    if stablecoin_value is not None:
        return stablecoin_value
    native_in = _to_decimal(row.get("native_in_sol"))
    if native_in > 0:
        return native_in * DEMO_SOL_USD_RATE
    return None


def _cost_basis_stablecoin_value(row: pd.Series) -> Decimal | None:
    stablecoins = {"USDC", "USDT", "PYUSD", "USDS"}
    total = Decimal("0")
    for flow in _safe_movements(row.get("token_flow_details")):
        symbol = str(flow.get("symbol") or "").upper()
        if symbol in stablecoins:
            total += _to_decimal(flow.get("in"))
    return total if total > 0 else None


def _allocate_cost_basis_value(value: Decimal | None, total_amount: Decimal, allocated_amount: Decimal) -> Decimal | None:
    if value is None or total_amount <= 0:
        return None
    return value * allocated_amount / total_amount


def _cost_basis_missing_parts(lot: dict[str, Any], disposition: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if lot["cost_basis"] is None:
        if lot["category"] in {
            TAX_CATEGORY_AIRDROP_REWARD,
            TAX_CATEGORY_STAKING_REWARD,
            TAX_CATEGORY_PAYMENT_FOR_SERVICES,
        }:
            missing.append("Acquisition FMV")
        else:
            missing.append("Acquisition cost basis")
    if lot["fees"] is None:
        missing.append("Fees")
    if disposition["amount"] > 0 and disposition["proceeds_fmv"] is None:
        missing.append("Disposal FMV/proceeds")
    return missing


def _cost_basis_status(lot: dict[str, Any], disposition: dict[str, Any]) -> str:
    missing = _cost_basis_missing_parts(lot, disposition)
    if "Acquisition cost basis" in missing or "Fees" in missing:
        return "Needs cost basis"
    if "Acquisition FMV" in missing or "Disposal FMV/proceeds" in missing:
        return "Needs FMV"
    return "Ready for review"


def _cost_basis_status_class(status: str) -> str:
    if status == "Ready for review":
        return "confirmed"
    return "warning"


def _cost_basis_missing_text(parts: list[str]) -> str:
    if not parts:
        return "-"
    return "; ".join(parts)


def _cost_basis_money(value: Decimal | None) -> str:
    if value is None:
        return "Missing"
    return _format_money(value, COST_BASIS_CURRENCY)


def _holding_period_days(acquired_on: str, disposed_on: str) -> int | None:
    if not acquired_on or not disposed_on:
        return None
    try:
        acquired = date.fromisoformat(acquired_on)
        disposed = date.fromisoformat(disposed_on)
    except ValueError:
        return None
    return max((disposed - acquired).days, 0)


def _holding_period_label(days: int | None) -> str:
    if days is None:
        return ""
    return "Long-term" if days > 365 else "Short-term"


def _cost_basis_allocations_by_signature(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        signature = str(row.get("transaction_id") or "")
        if not signature:
            continue
        bucket = grouped.setdefault(
            signature,
            {
                "assets": [],
                "amounts": [],
                "cost_basis": Decimal("0"),
                "proceeds_usd": Decimal("0"),
                "gain_loss_usd": Decimal("0"),
                "has_cost_basis": False,
                "has_proceeds": False,
                "has_gain_loss": False,
                "holding_period_days": "",
                "holding_period": "",
            },
        )
        asset = str(row.get("asset") or "")
        amount = str(row.get("disposed") or "")
        if asset:
            bucket["assets"].append(asset)
        if amount and asset:
            bucket["amounts"].append(f"{amount} {asset}")
        cost_basis = str(row.get("allocated_cost_basis_amount") or "")
        if cost_basis:
            bucket["cost_basis"] += _to_decimal(cost_basis)
            bucket["has_cost_basis"] = True
        proceeds = str(row.get("proceeds_usd_amount") or "")
        if proceeds:
            bucket["proceeds_usd"] += _to_decimal(proceeds)
            bucket["has_proceeds"] = True
        gain_loss = str(row.get("gain_loss_usd_amount") or "")
        if gain_loss:
            bucket["gain_loss_usd"] += _to_decimal(gain_loss)
            bucket["has_gain_loss"] = True
        days = str(row.get("holding_period_days") or "")
        if days and (not bucket["holding_period_days"] or _to_int(days) > _to_int(bucket["holding_period_days"])):
            bucket["holding_period_days"] = days
            bucket["holding_period"] = str(row.get("holding_period") or "")

    result: dict[str, dict[str, str]] = {}
    for signature, bucket in grouped.items():
        result[signature] = {
            "asset": ", ".join(dict.fromkeys(bucket["assets"])),
            "amount": "; ".join(bucket["amounts"]),
            "cost_basis": _decimal_to_storage(bucket["cost_basis"]) if bucket["has_cost_basis"] else "",
            "proceeds_usd": _decimal_to_storage(bucket["proceeds_usd"]) if bucket["has_proceeds"] else "",
            "gain_loss_usd": _decimal_to_storage(bucket["gain_loss_usd"]) if bucket["has_gain_loss"] else "",
            "holding_period": str(bucket["holding_period"]),
            "holding_period_days": str(bucket["holding_period_days"]),
        }
    return result


def _tax_file_taxable_status(category: str, status: str) -> str:
    if status in {TAX_REVIEW_NEEDS_CLIENT_ANSWER, TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW, TAX_REVIEW_BLOCKED_MISSING_DATA}:
        return "review"
    if category in {
        TAX_CATEGORY_INTERNAL_TRANSFER,
        TAX_CATEGORY_TRANSFER_FROM_EXCHANGE,
        TAX_CATEGORY_BUY,
        TAX_CATEGORY_STAKING_DEPOSIT,
        TAX_CATEGORY_FAILED_FEE_ONLY,
        TAX_CATEGORY_GIFT,
    }:
        return "no"
    if category in {
        TAX_CATEGORY_SELL,
        TAX_CATEGORY_SWAP_TRADE,
        TAX_CATEGORY_AIRDROP_REWARD,
        TAX_CATEGORY_STAKING_REWARD,
        TAX_CATEGORY_NFT_SALE,
        TAX_CATEGORY_PAYMENT_FOR_SERVICES,
    }:
        return "yes"
    return "review" if category in {TAX_CATEGORY_DEFI_COMPLEX, TAX_CATEGORY_UNKNOWN, TAX_CATEGORY_TRANSFER_TO_EXCHANGE} else "no"


def _expected_form(category: str, status: str) -> str:
    if _tax_file_taxable_status(category, status) == "review":
        return "Review before form mapping"
    if category in {TAX_CATEGORY_SELL, TAX_CATEGORY_SWAP_TRADE, TAX_CATEGORY_NFT_SALE}:
        return "Form 8949 draft / Schedule D summary"
    if category in {TAX_CATEGORY_AIRDROP_REWARD, TAX_CATEGORY_STAKING_REWARD}:
        return "Schedule 1 or Schedule C review"
    if category == TAX_CATEGORY_PAYMENT_FOR_SERVICES:
        return "Schedule C review"
    if category in {TAX_CATEGORY_INTERNAL_TRANSFER, TAX_CATEGORY_TRANSFER_FROM_EXCHANGE, TAX_CATEGORY_BUY, TAX_CATEGORY_STAKING_DEPOSIT, TAX_CATEGORY_FAILED_FEE_ONLY}:
        return "Support record only"
    return "CPA review"


def _tax_file_ordinary_income_usd(row: pd.Series, category: str) -> Decimal | None:
    if category not in {TAX_CATEGORY_AIRDROP_REWARD, TAX_CATEGORY_STAKING_REWARD, TAX_CATEGORY_PAYMENT_FOR_SERVICES}:
        return None
    value = _cost_basis_value_from_row(row)
    return value


def _fee_usd(row: pd.Series) -> str:
    fee_sol = _to_decimal(row.get("fee_sol"))
    if fee_sol <= 0:
        return "0"
    return _decimal_to_storage(fee_sol * DEMO_SOL_USD_RATE)


def _fee_treatment(category: str, status: str) -> str:
    if category == TAX_CATEGORY_FAILED_FEE_ONLY:
        return "Fee-only record; no disposal detected."
    if category in {TAX_CATEGORY_INTERNAL_TRANSFER, TAX_CATEGORY_TRANSFER_FROM_EXCHANGE, TAX_CATEGORY_BUY, TAX_CATEGORY_STAKING_DEPOSIT}:
        return "Tracked for audit context; not treated as a taxable disposal by itself."
    if category in {TAX_CATEGORY_SELL, TAX_CATEGORY_SWAP_TRADE, TAX_CATEGORY_NFT_SALE}:
        return "Include in disposal review when basis/proceeds are verified."
    if status in {TAX_REVIEW_NEEDS_CLIENT_ANSWER, TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW, TAX_REVIEW_BLOCKED_MISSING_DATA}:
        return "Review required before final fee treatment."
    return "Tracked for CPA review."


def _source_wallet(row: pd.Series) -> str:
    account = str(row.get("account_address") or "")
    direction = _row_direction(row)
    if direction == "outgoing":
        return account
    for movement in _safe_movements(row.get("movements_in")):
        counterparty = str(movement.get("counterparty") or movement.get("from_user_account") or "")
        if counterparty:
            return counterparty
    source = str(row.get("source") or "")
    return source if source and source.upper() != "UNKNOWN" else ""


def _destination_wallet(row: pd.Series) -> str:
    account = str(row.get("account_address") or "")
    direction = _row_direction(row)
    if direction == "incoming":
        return account
    for movement in _safe_movements(row.get("movements_out")):
        counterparty = str(movement.get("counterparty") or movement.get("to_user_account") or "")
        if counterparty:
            return counterparty
    source = str(row.get("source") or "")
    return source if source and source.upper() != "UNKNOWN" else ""


def _row_assets(row: pd.Series) -> str:
    assets = str(row.get("tag_assets") or "")
    if assets:
        return assets
    symbols = [str(flow.get("symbol") or flow.get("mint") or "") for flow in _safe_movements(row.get("token_flow_details"))]
    return ", ".join(symbol for symbol in symbols if symbol)


def _row_amount(row: pd.Series) -> str:
    display = str(row.get("tag_amount_display") or "")
    if display:
        return display
    native_in = _to_decimal(row.get("native_in_sol"))
    native_out = _to_decimal(row.get("native_out_sol"))
    if native_in > 0:
        return f"{_format_decimal(native_in)} SOL"
    if native_out > 0:
        return f"{_format_decimal(native_out)} SOL"
    return str(row.get("net_flow_summary") or "")


def _confidence_percent(row: pd.Series) -> str:
    raw = row.get("tag_confidence")
    if raw in (None, ""):
        return ""
    value = _to_decimal(raw)
    if value <= 0:
        return ""
    if value <= 1:
        value *= Decimal("100")
    return str(int(value.quantize(Decimal("1"))))


def _tax_file_ai_explanation(row: pd.Series, category: str, status: str) -> str:
    if category == TAX_CATEGORY_INTERNAL_TRANSFER:
        return "This transaction was marked as a self-transfer because the source and destination wallets are linked to the same taxpayer profile. No disposal was detected."
    if category == TAX_CATEGORY_TRANSFER_FROM_EXCHANGE:
        return "Funding from an exchange account is treated as an acquisition/support record, not ordinary income, because the source is identified as an exchange transfer into the taxpayer wallet."
    if category == TAX_CATEGORY_SWAP_TRADE:
        return "A Jupiter swap exchanged one digital asset for another, so it is prepared as a taxable disposal candidate with Form 8949 / Schedule D review fields."
    if category == TAX_CATEGORY_SELL:
        return "The asset was disposed for stablecoin or USD-equivalent proceeds, so realized gain/loss is calculated from proceeds minus verified basis."
    if category == TAX_CATEGORY_AIRDROP_REWARD:
        return "The token reward is separated from capital gains and reviewed as ordinary income based on fair market value at receipt."
    if category == TAX_CATEGORY_STAKING_REWARD:
        return "The staking reward is separated from capital gains and reviewed as ordinary income based on fair market value at receipt."
    if category == TAX_CATEGORY_NFT_SALE:
        return "The NFT sale is prepared for capital gain/loss review using proceeds, cost basis, fees, and holding period."
    if category == TAX_CATEGORY_NFT_PURCHASE:
        return "The NFT mint or purchase is treated as an acquisition record; mint cost and fees become basis support."
    if category == TAX_CATEGORY_FAILED_FEE_ONLY:
        return "The transaction failed and only a network fee was paid, so no asset disposal was detected."
    if category == TAX_CATEGORY_DEFI_COMPLEX:
        return "This Solana DeFi pattern needs CPA review because LP, bridge, or wrapped-token treatment depends on the exact facts."
    if status in {TAX_REVIEW_NEEDS_CLIENT_ANSWER, TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW, TAX_REVIEW_BLOCKED_MISSING_DATA}:
        return "AI Accountant flagged this transaction because required tax facts are missing or ambiguous."
    return "AI Accountant classified this transaction from parsed wallet activity, labels, asset flows, and review overrides."


def _tax_file_next_action(row: pd.Series, category: str, status: str) -> str:
    reason = str(row.get("review_reason") or "")
    if status == TAX_REVIEW_NEEDS_CLIENT_ANSWER:
        return "Ask the taxpayer to answer the ownership/source question before using this in tax totals."
    if reason == REASON_MISSING_COST_BASIS:
        return "Add acquisition history, exchange import, or manual cost basis before relying on gain/loss."
    if reason == REASON_MISSING_FMV:
        return "Add historical fair market value at receipt/disposal."
    if reason == REASON_COMPLEX_DEFI:
        return "Route to Advanced / CPA workspace for treatment review."
    if category == TAX_CATEGORY_TRANSFER_FROM_EXCHANGE:
        return "Keep as support record; do not include as ordinary income."
    if category == TAX_CATEGORY_INTERNAL_TRANSFER:
        return "Keep wallet-link evidence and audit trail."
    return "Include in CPA-ready draft package and review before filing."


def _tax_impact_copy(category: str, status: str) -> str:
    taxable = _tax_file_taxable_status(category, status)
    if category in {TAX_CATEGORY_INTERNAL_TRANSFER, TAX_CATEGORY_TRANSFER_FROM_EXCHANGE}:
        return "No realized gain/loss. Fees may still be tracked for audit context."
    if taxable == "yes" and category in {TAX_CATEGORY_SELL, TAX_CATEGORY_SWAP_TRADE, TAX_CATEGORY_NFT_SALE}:
        return "Potential capital gain/loss. Proceeds, cost basis, fees, and holding period affect Form 8949 / Schedule D review."
    if taxable == "yes" and category in {TAX_CATEGORY_AIRDROP_REWARD, TAX_CATEGORY_STAKING_REWARD, TAX_CATEGORY_PAYMENT_FOR_SERVICES}:
        return "Potential ordinary income based on fair market value when received."
    if taxable == "review":
        return "Review required before including this transaction in tax totals."
    return "Support record only unless CPA review identifies a taxable event."


def _taxable_event_count(frame: pd.DataFrame) -> int:
    if frame.empty or "tax_category" not in frame:
        return 0
    count = 0
    for _, row in frame.iterrows():
        if str(row.get("tax_scope") or TAX_SCOPE_INCLUDED) != TAX_SCOPE_INCLUDED:
            continue
        if _tax_file_taxable_status(
            str(row.get("tax_category") or TAX_CATEGORY_UNKNOWN),
            str(row.get("tax_review_status") or TAX_REVIEW_READY),
        ) == "yes":
            count += 1
    return count


def _self_transfer_confirmation_value(frame: pd.DataFrame) -> Decimal:
    if frame.empty:
        return TEST_SELF_TRANSFER_VALUE_USD
    for _, row in frame.iterrows():
        if str(row.get("review_reason") or "") == REASON_UNKNOWN_SOURCE:
            value = _cost_basis_value_from_row(row)
            if value is not None:
                return value
    return TEST_SELF_TRANSFER_VALUE_USD


def _tax_file_identifier(tax_file: TaxFile | dict[str, Any]) -> str:
    if isinstance(tax_file, TaxFile):
        return tax_file.id
    return str(tax_file.get("id") or "")


def _is_test_tax_file(tax_file: TaxFile | dict[str, Any]) -> bool:
    return _tax_file_identifier(tax_file) == TEST_TAX_FILE_ID


def _frame_has_pending_test_confirmation(frame: pd.DataFrame) -> bool:
    if frame.empty:
        return False
    for _, row in frame.iterrows():
        if str(row.get("tax_file_id") or "") != TEST_TAX_FILE_ID:
            continue
        if (
            str(row.get("review_reason") or "") == REASON_UNKNOWN_SOURCE
            and str(row.get("tax_review_status") or "") == TAX_REVIEW_NEEDS_CLIENT_ANSWER
        ):
            return True
    return False


def _tax_loss_harvesting_profile(country_code: str) -> dict[str, Any] | None:
    if country_code == "PL":
        return {
            "currency": "PLN",
            "tax_rate": POLISH_CRYPTO_TAX_RATE,
            "tax_rate_label": "19%",
            "sol_rate": DEMO_SOL_PLN_RATE,
            "price_key": "current_price_pln",
            "assumptions": TAX_LOSS_HARVESTING_ASSUMPTIONS_PLN,
            "min_loss": TAX_LOSS_HARVESTING_MIN_LOSS_PLN,
        }
    if country_code == "US":
        return {
            "currency": "USD",
            "tax_rate": US_DEMO_SHORT_TERM_CAPITAL_RATE,
            "tax_rate_label": "24% short-term capital rate assumption",
            "sol_rate": DEMO_SOL_USD_RATE,
            "price_key": "current_price_usd",
            "assumptions": TAX_LOSS_HARVESTING_ASSUMPTIONS_USD,
            "min_loss": TAX_LOSS_HARVESTING_MIN_LOSS_USD,
        }
    return None


def _tax_loss_harvesting_candidates(
    frame: pd.DataFrame,
    *,
    tax_year: int,
    country_code: str,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    if frame.empty:
        return []

    currency = str(profile["currency"])
    assumptions = profile["assumptions"]
    price_key = str(profile["price_key"])
    sol_rate = _to_decimal(profile["sol_rate"])
    tax_rate = _to_decimal(profile["tax_rate"])
    min_loss = _to_decimal(profile["min_loss"])
    candidates: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        if _row_tax_year(row) != tax_year:
            continue
        if str(row.get("status") or "") != "succeeded":
            continue
        if str(row.get("tax_scope") or TAX_SCOPE_INCLUDED) != TAX_SCOPE_INCLUDED:
            continue
        if bool(row.get("is_internal_transfer")):
            continue
        native_out = _to_decimal(row.get("native_out_sol"))
        if native_out <= 0:
            continue

        for flow in _safe_movements(row.get("token_flow_details")):
            amount = _to_decimal(flow.get("in"))
            if amount <= 0:
                continue
            symbol = str(flow.get("symbol") or "").upper()
            assumption = assumptions.get(symbol)
            if not assumption:
                continue
            current_price = _to_decimal(assumption.get(price_key))
            cost_basis = native_out * sol_rate
            current_value = amount * current_price
            unrealized_loss = cost_basis - current_value
            if unrealized_loss < min_loss:
                continue
            estimated_effect = unrealized_loss * tax_rate
            signature = str(row.get("signature") or "")
            action, warning = _tax_loss_harvesting_candidate_copy(country_code)
            candidates.append(
                {
                    "asset": symbol,
                    "amount": _format_decimal(amount),
                    "acquired_on": _row_date(row),
                    "transaction_id": signature,
                    "signature_short": _short(signature, 8) if signature else "",
                    "currency": currency,
                    "cost_basis_amount": _decimal_to_storage(cost_basis),
                    "cost_basis_pln": _decimal_to_storage(cost_basis) if currency == "PLN" else "",
                    "cost_basis_display": _format_money(cost_basis, currency),
                    "current_value_amount": _decimal_to_storage(current_value),
                    "current_value_pln": _decimal_to_storage(current_value) if currency == "PLN" else "",
                    "current_value_display": _format_money(current_value, currency),
                    "unrealized_loss_amount": _decimal_to_storage(unrealized_loss),
                    "unrealized_loss_pln": _decimal_to_storage(unrealized_loss) if currency == "PLN" else "",
                    "unrealized_loss_display": _format_money(unrealized_loss, currency),
                    "estimated_tax_effect_amount": _decimal_to_storage(estimated_effect),
                    "estimated_tax_effect_pln": _decimal_to_storage(estimated_effect) if currency == "PLN" else "",
                    "estimated_tax_effect_display": _format_money(estimated_effect, currency),
                    "market_price_display": _format_money(current_price, currency),
                    "market_date": str(assumption.get("market_date") or ""),
                    "market_source": str(assumption.get("source") or "Review market assumption."),
                    "confidence": "review",
                    "action": action,
                    "warning": warning,
                }
            )

    candidates.sort(key=lambda item: _to_decimal(item["estimated_tax_effect_amount"]), reverse=True)
    return candidates


def _tax_loss_harvesting_candidate_copy(country_code: str) -> tuple[str, str]:
    if country_code == "US":
        return (
            "Ask a qualified professional to review whether a taxable disposition before year-end could be relevant "
            "given capital gains, deduction limits, carryforwards, market, fee, and re-entry risk.",
            "For US taxpayers, digital asset losses are subject to capital loss rules. Do not assume an "
            "immediate sell-and-rebuy is risk-free; confirm wash-sale, substance, and anti-abuse risk under current law.",
        )
    return (
        "Ask a qualified professional to review whether any year-end disposition planning is relevant given taxable "
        "crypto income, documentation, market, fee, and re-entry risk.",
        "In Poland this is not a classic deductible loss. If costs exceed crypto disposal revenue, the "
        "unused costs generally carry forward instead of creating a PIT loss.",
    )


def _tax_loss_harvesting_notification(
    tax_year: int,
    today: date,
    estimated_effect: Decimal,
    *,
    country_code: str,
    currency: str,
) -> str:
    effect = _format_money(estimated_effect, currency)
    year_end = date(tax_year, 12, 31)
    country_note = "US federal tax" if country_code == "US" else "Polish PIT"
    if today.year == tax_year and today.month == 12:
        days_left = max((year_end - today).days, 0)
        return (
            f"December review note: available wallet data shows potential loss candidates with an estimated "
            f"{effect} {country_note} impact before professional review. {days_left} days remain in {tax_year}; "
            "this is not final and depends on verified facts."
        )
    if today.year > tax_year:
        return (
            f"Year-end review: before December 31, {tax_year}, available wallet data would have shown an estimated "
            f"{effect} potential {country_note} impact before professional review. This is not final."
        )
    return (
        f"Planning preview: current review candidates show an estimated {effect} potential {country_note} impact "
        "before professional review. This is not final."
    )


def _tax_loss_harvesting_guardrails(country_code: str) -> list[str]:
    if country_code == "US":
        return [
            "IRS guidance treats digital assets as property; a sale or exchange can realize capital gain or loss.",
            "If capital losses exceed capital gains, individual deductions are limited and excess losses may carry forward.",
            "Report capital asset disposals on Form 8949 and summarize them on Schedule D when applicable.",
            "Immediate sell-and-rebuy planning needs professional review for wash-sale, substance, fee, slippage, and audit risk.",
        ]
    if country_code != "PL":
        return ["No country-specific potential loss review rule is enabled for this Tax File."]
    return [
        "Polish crypto rules do not recognize a separate deductible loss from virtual currency disposal.",
        "Crypto-to-crypto swaps are generally not taxable disposals for Polish PIT, so swapping one token for another is not enough.",
        "Only documented direct acquisition/disposal costs should be used; unsupported cost basis should stay in review.",
        "Immediate sell-and-rebuy planning needs professional review for economic substance, fees, slippage, and anti-avoidance risk.",
    ]


def _tax_loss_harvesting_sources(country_code: str) -> list[dict[str, str]]:
    if country_code == "US":
        return [
            {"label": "IRS digital assets", "url": IRS_DIGITAL_ASSETS_SOURCE_URL},
            {"label": "IRS Topic 409 capital gains and losses", "url": IRS_TOPIC_409_SOURCE_URL},
            {"label": "IRS Form 8949 instructions", "url": IRS_FORM_8949_SOURCE_URL},
        ]
    if country_code == "PL":
        return [
            {"label": "podatki.gov.pl crypto disposal", "url": POLISH_CRYPTO_TAX_SOURCE_URL},
            {"label": "podatki.gov.pl PIT-38 2025", "url": "https://www.podatki.gov.pl/twoj-e-pit/pit-38-za-2025-rok/"},
        ]
    return []


def _tax_loss_harvesting_assumptions(country_code: str, currency: str) -> list[str]:
    if country_code == "US":
        return [
            "Review uses fixed SOL/USD and token/USD market assumptions; no live oracle is connected.",
            "Potential impact uses a 24% short-term capital rate assumption and does not know the taxpayer's actual bracket.",
            "Loss value depends on available capital gains, the capital loss deduction limit, and carryforward rules.",
            "The dashboard does not place trades and should not recommend immediate repurchases without professional review.",
        ]
    if country_code != "PL":
        return ["No country-specific potential loss review assumptions are enabled for this Tax File."]
    return [
        f"Review uses fixed SOL/{currency} and token/{currency} market assumptions; no live oracle is connected.",
        "Potential impact assumes there is enough current-year taxable crypto income to absorb the cost effect.",
        "The dashboard does not place trades and should not recommend wash-style round trips without professional review.",
    ]


def _tax_country_code(country: str) -> str:
    normalized = (country or "").strip().upper()
    aliases = {
        "PL": "PL",
        "POLAND": "PL",
        "POLSKA": "PL",
        "US": "US",
        "USA": "US",
        "UNITED STATES": "US",
        "UNITED STATES OF AMERICA": "US",
    }
    return aliases.get(normalized, normalized or "UNKNOWN")


def _tax_country_options() -> list[dict[str, str]]:
    return [
        {"value": "United States", "label": "United States"},
        {"value": "Poland", "label": "Poland"},
    ]


def _row_tax_year(row: pd.Series) -> int | None:
    ts = row.get("timestamp_unix")
    if ts in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).year
    except (OSError, TypeError, ValueError):
        return None


def _format_money_pln(value: Decimal) -> str:
    return _format_money(value, "PLN")


def _format_money(value: Decimal, currency: str) -> str:
    if currency == "USD":
        abs_value = abs(value)
        if Decimal("0") < abs_value < Decimal("0.01"):
            rounded = value.quantize(Decimal("0.00000001")).normalize()
        elif Decimal("0.01") <= abs_value < Decimal("1"):
            rounded = value.quantize(Decimal("0.0001")).normalize()
        else:
            rounded = value.quantize(Decimal("0.01"))
        rendered = f"{rounded:,.2f}".rstrip("0").rstrip(".")
        if Decimal("0") < abs_value < Decimal("1"):
            rendered = f"{rounded:f}".rstrip("0").rstrip(".")
        return f"${rendered}"
    rounded = value.quantize(Decimal("0.01"))
    return f"{_format_decimal(rounded)} {currency}"


def _safe_movements(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _pair_label(from_account: Account | None, to_account: Account | None) -> str:
    return f"{_account_label(from_account)} -> {_account_label(to_account)}"


def _account_label(account: Account | None) -> str:
    if account is None:
        return "Unknown account"
    return account.label or _short(account.address, 6)


def _row_date(row: pd.Series | None) -> str:
    if row is None:
        return ""
    timestamp = row.get("timestamp")
    if isinstance(timestamp, str) and timestamp:
        return timestamp[:10]
    ts = row.get("timestamp_unix")
    if ts in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d")
    except (OSError, TypeError, ValueError):
        return ""


def _to_decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _decimal_to_storage(value: Decimal) -> str:
    rendered = f"{value:f}"
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_choice(value: Any, choices: tuple[str, ...], default: str) -> str:
    raw = str(value or "").strip()
    return raw if raw in choices else default


def _clean_tax_year(value: int | str) -> int:
    try:
        year = int(value)
    except (TypeError, ValueError):
        year = datetime.now(timezone.utc).year
    return max(2009, min(2100, year))


def _empty_payload() -> dict[str, Any]:
    return {
        "schema_version": STORE_SCHEMA_VERSION,
        "tax_files": [],
        "accounts": [],
        "transfer_matches": [],
        "client_answers": [],
        "transaction_overrides": [],
        "audit_log": [],
    }


def _canonical_rows(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)


_TRANSACTION_EXTENSION_COLUMNS = [
    "tax_file_id",
    "account_id",
    "account_label",
    "account_address",
    "ownership_status",
    "tax_category",
    "original_tax_category",
    "tax_review_status",
    "review_reason",
    "client_question",
    "client_answer",
    "client_answered_at",
    "accountant_note",
    "override_applied",
    "override_by",
    "override_at",
    "resolved_at",
    "resolved_by",
    "excluded_reason",
    "excluded_at",
    "reopened_at",
    "transfer_match_id",
    "tax_scope",
    "is_internal_transfer",
]


__all__ = [
    "ACCOUNT_TYPE_SOLANA_WALLET",
    "ACCOUNT_TYPES",
    "Account",
    "AuditLogEntry",
    "ClientAnswer",
    "DEFAULT_ENTITY_TYPE",
    "DEFAULT_TAX_COUNTRY",
    "MATCH_CONFIRMED",
    "MATCH_REJECTED",
    "MATCH_STATUSES",
    "MATCH_SUGGESTED",
    "OWNERSHIP_EXTERNAL",
    "OWNERSHIP_OWNED",
    "OWNERSHIP_STATUSES",
    "OWNERSHIP_UNKNOWN",
    "OWNERSHIP_WATCH_ONLY",
    "REVIEW_REASONS",
    "STORE_SCHEMA_VERSION",
    "TAX_CATEGORIES",
    "TAX_REVIEW_STATUSES",
    "TAX_SCOPE_EXCLUDED",
    "TAX_SCOPE_INCLUDED",
    "TAX_SCOPE_WATCH_ONLY",
    "TaxFile",
    "TaxFileStore",
    "TransactionOverride",
    "TransferMatch",
    "TEST_TAX_FILE_ID",
    "ai_accountant_findings",
    "cost_basis_rows",
    "create_demo_tax_file",
    "create_test_tax_file",
    "matchInternalTransfers",
    "tax_estimate_plan",
    "tax_file_cpa_ready_export_frame",
    "tax_file_export_frame",
    "tax_file_yearly_summary",
    "tax_file_dashboard_context",
    "tax_files_overview",
    "tax_loss_harvesting_advice",
    "unified_transaction_frame",
]
