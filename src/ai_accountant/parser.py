"""Parse Helius Enhanced transactions into accounting-grade row dicts.

Each `TransactionParser` is bound to a single wallet address (the audit
perspective). Output rows match the schema in `dataframe.DATAFRAME_COLUMNS`.

Token flows are aggregated by full mint string. Display labels are rendered
from `(symbol, mint)` and used only in the rendered summary fields; they are
never used as dictionary keys.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .addresses import validate_address
from .exceptions import HeliusAPIError

LAMPORTS_PER_SOL = Decimal("1000000000")


class TransactionParser:
    """Parse Helius transactions from a single wallet's perspective."""

    NATIVE_KEY = "SOL"  # net_flow dict key for native SOL; tokens use full mint.

    def __init__(self, wallet_address: str) -> None:
        self.wallet_address = validate_address(wallet_address)

    def parse(self, transaction: Mapping[str, Any]) -> dict[str, Any]:
        movements = self._parse_wallet_movements(transaction)

        fee_lamports = int(transaction.get("fee") or 0)
        fee_sol = Decimal(fee_lamports) / LAMPORTS_PER_SOL
        fee_payer = str(transaction.get("feePayer") or "")
        fee_paid_by_wallet = fee_payer == self.wallet_address

        native_in_sol = movements["native_in_sol"]
        native_out_sol = movements["native_out_sol"]
        native_transfer_net_sol = native_in_sol - native_out_sol
        native_net_sol = native_transfer_net_sol - (fee_sol if fee_paid_by_wallet else Decimal("0"))

        token_flow_details = self._flow_details_to_rows(movements["token_flows"])
        token_in_summary = self._format_flow_summary(token_flow_details, key="in")
        token_out_summary = self._format_flow_summary(token_flow_details, key="out")
        token_net_summary = self._format_flow_summary(
            token_flow_details,
            key="net",
            signed=True,
        )

        net_flow = self._build_net_flow(native_net_sol, token_flow_details)
        net_flow_summary = self._format_net_flow_summary(
            native_net_sol,
            token_flow_details,
        )

        timestamp_unix = transaction.get("timestamp")
        raw_error = transaction.get("transactionError")
        status = "failed" if raw_error is not None else "succeeded"

        return {
            "signature": transaction.get("signature"),
            "slot": transaction.get("slot"),
            "timestamp_unix": timestamp_unix,
            "timestamp": self._format_timestamp(timestamp_unix),
            "transaction_type": transaction.get("type"),
            "description": transaction.get("description"),
            "source": transaction.get("source"),
            "fee_lamports": fee_lamports,
            "fee_sol": fee_sol,
            "fee_paid_by_wallet": fee_paid_by_wallet,
            "fee_payer": fee_payer or None,
            "status": status,
            "native_in_sol": native_in_sol,
            "native_out_sol": native_out_sol,
            "native_transfer_net_sol": native_transfer_net_sol,
            "native_net_sol": native_net_sol,
            "token_in_summary": token_in_summary,
            "token_out_summary": token_out_summary,
            "token_net_summary": token_net_summary,
            "net_flow_summary": net_flow_summary,
            "net_flow": net_flow,
            "token_flow_details": token_flow_details,
            "movements_in": movements["movements_in"],
            "movements_out": movements["movements_out"],
            "raw_native_transfers": list(transaction.get("nativeTransfers") or []),
            "raw_token_transfers": list(transaction.get("tokenTransfers") or []),
            "transaction_error": raw_error,
            "program_ids": list(
                dict.fromkeys(
                    str(ix.get("programId"))
                    for ix in (transaction.get("instructions") or [])
                    if ix.get("programId")
                )
            ),
        }

    def parse_many(
        self,
        transactions: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return [self.parse(tx) for tx in transactions]

    # ------------------------------------------------------------------ helpers

    def _parse_wallet_movements(
        self,
        transaction: Mapping[str, Any],
    ) -> dict[str, Any]:
        wallet = self.wallet_address
        native_in_sol = Decimal("0")
        native_out_sol = Decimal("0")
        token_flows: dict[str, dict[str, Any]] = {}
        movements_in: list[dict[str, Any]] = []
        movements_out: list[dict[str, Any]] = []

        for native_transfer in transaction.get("nativeTransfers") or []:
            from_account = str(native_transfer.get("fromUserAccount") or "")
            to_account = str(native_transfer.get("toUserAccount") or "")
            if from_account == wallet and to_account == wallet:
                continue

            amount_lamports = self._coerce_decimal(native_transfer.get("amount"))
            if amount_lamports <= 0:
                continue

            amount_sol = amount_lamports / LAMPORTS_PER_SOL
            base = {
                "asset_type": "native",
                "symbol": "SOL",
                "mint": None,
                "amount": amount_sol,
                "amount_lamports": int(amount_lamports),
                "from_user_account": from_account or None,
                "to_user_account": to_account or None,
            }

            if to_account == wallet:
                native_in_sol += amount_sol
                movements_in.append(
                    {**base, "direction": "in", "counterparty": from_account or None}
                )
            if from_account == wallet:
                native_out_sol += amount_sol
                movements_out.append(
                    {**base, "direction": "out", "counterparty": to_account or None}
                )

        for token_transfer in transaction.get("tokenTransfers") or []:
            from_account = str(token_transfer.get("fromUserAccount") or "")
            to_account = str(token_transfer.get("toUserAccount") or "")
            if from_account == wallet and to_account == wallet:
                continue

            amount = self._coerce_decimal(token_transfer.get("tokenAmount"))
            if amount <= 0:
                continue

            mint = token_transfer.get("mint")
            if not mint:
                # Without a mint we cannot disambiguate this asset from any other
                # token sharing the same symbol. Drop the transfer.
                continue
            mint_str = str(mint)
            symbol = self._resolve_token_symbol(token_transfer)

            flow_entry = token_flows.setdefault(
                mint_str,
                {
                    "mint": mint_str,
                    "symbol": symbol,
                    "in": Decimal("0"),
                    "out": Decimal("0"),
                },
            )

            base = {
                "asset_type": "token",
                "symbol": symbol,
                "mint": mint_str,
                "amount": amount,
                "from_user_account": from_account or None,
                "to_user_account": to_account or None,
                "from_token_account": token_transfer.get("fromTokenAccount"),
                "to_token_account": token_transfer.get("toTokenAccount"),
            }

            if to_account == wallet:
                flow_entry["in"] += amount
                movements_in.append(
                    {**base, "direction": "in", "counterparty": from_account or None}
                )
            if from_account == wallet:
                flow_entry["out"] += amount
                movements_out.append(
                    {**base, "direction": "out", "counterparty": to_account or None}
                )

        return {
            "native_in_sol": native_in_sol,
            "native_out_sol": native_out_sol,
            "token_flows": token_flows,
            "movements_in": movements_in,
            "movements_out": movements_out,
        }

    def _flow_details_to_rows(
        self,
        token_flows: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for mint in sorted(token_flows):
            flow = token_flows[mint]
            inflow = Decimal(flow["in"])
            outflow = Decimal(flow["out"])
            rows.append(
                {
                    "symbol": flow["symbol"],
                    "mint": mint,
                    "label": self._asset_label(flow["symbol"], mint),
                    "in": inflow,
                    "out": outflow,
                    "net": inflow - outflow,
                }
            )
        return rows

    def _build_net_flow(
        self,
        native_net_sol: Decimal,
        token_flow_details: Iterable[Mapping[str, Any]],
    ) -> dict[str, Decimal]:
        net_flow: dict[str, Decimal] = {self.NATIVE_KEY: native_net_sol}
        for flow in token_flow_details:
            net_flow[str(flow["mint"])] = Decimal(flow["net"])
        return net_flow

    def _format_flow_summary(
        self,
        token_flow_details: Iterable[Mapping[str, Any]],
        *,
        key: str,
        signed: bool = False,
    ) -> str:
        parts: list[str] = []
        for flow in token_flow_details:
            amount = Decimal(flow[key])
            if amount == 0:
                continue
            rendered = self._decimal_to_string(amount, signed=signed)
            parts.append(f"{flow['label']}: {rendered}")
        return ", ".join(parts) if parts else "None"

    def _format_net_flow_summary(
        self,
        native_net_sol: Decimal,
        token_flow_details: Iterable[Mapping[str, Any]],
    ) -> str:
        parts: list[str] = []
        if native_net_sol != 0:
            parts.append(f"SOL: {self._decimal_to_string(native_net_sol, signed=True)}")
        for flow in token_flow_details:
            net = Decimal(flow["net"])
            if net == 0:
                continue
            parts.append(f"{flow['label']}: {self._decimal_to_string(net, signed=True)}")
        return ", ".join(parts) if parts else "No net movement"

    @staticmethod
    def _asset_label(symbol: str, mint: str | None) -> str:
        if mint and mint != symbol:
            return f"{symbol} ({mint})"
        return symbol

    @staticmethod
    def _coerce_decimal(value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise HeliusAPIError(f"Unable to parse numeric value from {value!r}.") from exc

    @staticmethod
    def _resolve_token_symbol(token_transfer: Mapping[str, Any]) -> str:
        candidates = (
            token_transfer.get("tokenSymbol"),
            token_transfer.get("symbol"),
            token_transfer.get("currencySymbol"),
            token_transfer.get("name"),
            token_transfer.get("mint"),
        )
        for candidate in candidates:
            if candidate:
                return str(candidate)
        return "UNKNOWN_TOKEN"

    @staticmethod
    def _format_timestamp(timestamp_unix: Any) -> str | None:
        if timestamp_unix in (None, ""):
            return None
        try:
            return datetime.fromtimestamp(
                int(timestamp_unix),
                tz=timezone.utc,
            ).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, OverflowError, TypeError, ValueError):
            return None

    @staticmethod
    def _decimal_to_string(value: Decimal, *, signed: bool = False) -> str:
        normalized = value.normalize()
        rendered = format(normalized, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        if rendered in {"", "-0"}:
            rendered = "0"
        if signed and not rendered.startswith("-") and rendered != "0":
            rendered = f"+{rendered}"
        return rendered
