from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant import InvalidSolanaAddressError, TransactionParser

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW"
COUNTERPARTY = "Pool1111111111111111111111111111111111111"


def _swap_tx(token_transfers):
    return {
        "signature": "sig-test",
        "slot": 1,
        "timestamp": 1_700_000_000,
        "type": "SWAP",
        "source": "JUPITER",
        "fee": 5_000,
        "feePayer": WALLET,
        "nativeTransfers": [],
        "tokenTransfers": token_transfers,
    }


class TransactionParserConstructionTests(unittest.TestCase):
    def test_parser_validates_wallet_address_at_construction(self):
        with self.assertRaises(InvalidSolanaAddressError):
            TransactionParser("not-a-valid-address")

    def test_parser_stores_normalized_wallet(self):
        parser = TransactionParser(f"  {WALLET}  ")
        self.assertEqual(parser.wallet_address, WALLET)


class TransactionParserMintKeyingTests(unittest.TestCase):
    def test_token_collision_aggregated_by_mint_not_symbol(self):
        # Two distinct mints share the symbol "USDC" — they MUST aggregate as
        # two separate flows, not be collapsed by symbol.
        fake_usdc_mint = "FAKE5555555555555555555555555555555555555555"
        parser = TransactionParser(WALLET)
        row = parser.parse(
            _swap_tx(
                [
                    {
                        "fromUserAccount": COUNTERPARTY,
                        "toUserAccount": WALLET,
                        "tokenAmount": "100",
                        "mint": USDC_MINT,
                        "tokenSymbol": "USDC",
                    },
                    {
                        "fromUserAccount": COUNTERPARTY,
                        "toUserAccount": WALLET,
                        "tokenAmount": "200",
                        "mint": fake_usdc_mint,
                        "tokenSymbol": "USDC",
                    },
                ]
            )
        )
        flow_mints = sorted(d["mint"] for d in row["token_flow_details"])
        self.assertEqual(flow_mints, sorted([USDC_MINT, fake_usdc_mint]))
        self.assertEqual(len(row["token_flow_details"]), 2)
        self.assertEqual(row["net_flow"][USDC_MINT], Decimal("100"))
        self.assertEqual(row["net_flow"][fake_usdc_mint], Decimal("200"))

    def test_token_transfer_without_mint_is_skipped(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(
            _swap_tx(
                [
                    {
                        "fromUserAccount": COUNTERPARTY,
                        "toUserAccount": WALLET,
                        "tokenAmount": "100",
                        "mint": None,
                        "tokenSymbol": "USDC",
                    },
                ]
            )
        )
        self.assertEqual(row["token_flow_details"], [])
        self.assertEqual(row["movements_in"], [])

    def test_label_is_full_mint_not_truncated(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(
            _swap_tx(
                [
                    {
                        "fromUserAccount": COUNTERPARTY,
                        "toUserAccount": WALLET,
                        "tokenAmount": "1",
                        "mint": BONK_MINT,
                        "tokenSymbol": "BONK",
                    },
                ]
            )
        )
        self.assertEqual(
            row["token_flow_details"][0]["label"],
            f"BONK ({BONK_MINT})",
        )

    def test_net_flow_keyed_by_full_mint_for_tokens_and_SOL_for_native(self):
        parser = TransactionParser(WALLET)
        tx = {
            "signature": "sig-x",
            "slot": 1,
            "timestamp": 1_700_000_000,
            "type": "TRANSFER",
            "fee": 5_000,
            "feePayer": WALLET,
            "nativeTransfers": [
                {
                    "fromUserAccount": "ExtSender1111111111111111111111111111111",
                    "toUserAccount": WALLET,
                    "amount": 1_000_000_000,
                },
            ],
            "tokenTransfers": [
                {
                    "fromUserAccount": COUNTERPARTY,
                    "toUserAccount": WALLET,
                    "tokenAmount": "5",
                    "mint": USDC_MINT,
                    "tokenSymbol": "USDC",
                },
            ],
        }
        row = parser.parse(tx)
        self.assertIn("SOL", row["net_flow"])
        self.assertIn(USDC_MINT, row["net_flow"])
        self.assertEqual(row["net_flow"][USDC_MINT], Decimal("5"))


class TransactionParserStatusTests(unittest.TestCase):
    def _ok_tx(self, **overrides):
        base = {
            "signature": "sig-x",
            "slot": 1,
            "timestamp": 1_700_000_000,
            "type": "TRANSFER",
            "fee": 5_000,
            "feePayer": WALLET,
            "nativeTransfers": [],
            "tokenTransfers": [],
        }
        base.update(overrides)
        return base

    def test_failed_when_transaction_error_is_dict(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(self._ok_tx(transactionError={"InstructionError": [0, "Custom 6000"]}))
        self.assertEqual(row["status"], "failed")

    def test_failed_when_transaction_error_is_empty_dict(self):
        # Empty dict is FALSY but PRESENT — we want explicit-None semantics.
        parser = TransactionParser(WALLET)
        row = parser.parse(self._ok_tx(transactionError={}))
        self.assertEqual(row["status"], "failed")

    def test_failed_when_transaction_error_is_empty_list(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(self._ok_tx(transactionError=[]))
        self.assertEqual(row["status"], "failed")

    def test_succeeded_when_transaction_error_key_missing(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(self._ok_tx())
        self.assertEqual(row["status"], "succeeded")

    def test_succeeded_when_transaction_error_explicitly_null(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(self._ok_tx(transactionError=None))
        self.assertEqual(row["status"], "succeeded")


class TransactionParserSchemaTests(unittest.TestCase):
    def test_parse_many_returns_list_in_order(self):
        parser = TransactionParser(WALLET)
        rows = parser.parse_many(
            [
                {
                    "signature": "sig-1",
                    "slot": 1,
                    "timestamp": 1_700_000_000,
                    "fee": 0,
                    "feePayer": "",
                    "nativeTransfers": [],
                    "tokenTransfers": [],
                },
                {
                    "signature": "sig-2",
                    "slot": 2,
                    "timestamp": 1_700_000_001,
                    "fee": 0,
                    "feePayer": "",
                    "nativeTransfers": [],
                    "tokenTransfers": [],
                },
            ]
        )
        self.assertEqual([r["signature"] for r in rows], ["sig-1", "sig-2"])

    def test_self_transfers_ignored(self):
        parser = TransactionParser(WALLET)
        row = parser.parse(
            {
                "signature": "self",
                "slot": 1,
                "timestamp": 1_700_000_000,
                "fee": 0,
                "feePayer": WALLET,
                "nativeTransfers": [
                    {"fromUserAccount": WALLET, "toUserAccount": WALLET, "amount": 1_000_000_000},
                ],
                "tokenTransfers": [],
            }
        )
        self.assertEqual(row["movements_in"], [])
        self.assertEqual(row["movements_out"], [])

    def test_fee_subtracted_only_when_wallet_pays(self):
        parser = TransactionParser(WALLET)
        row_paid = parser.parse(
            {
                "signature": "p",
                "slot": 1,
                "timestamp": 1_700_000_000,
                "fee": 5_000,
                "feePayer": WALLET,
                "nativeTransfers": [],
                "tokenTransfers": [],
            }
        )
        self.assertTrue(row_paid["fee_paid_by_wallet"])
        self.assertEqual(row_paid["native_net_sol"], Decimal("-0.000005"))

        row_other = parser.parse(
            {
                "signature": "o",
                "slot": 1,
                "timestamp": 1_700_000_000,
                "fee": 5_000,
                "feePayer": "Other11111111111111111111111111111111111",
                "nativeTransfers": [],
                "tokenTransfers": [],
            }
        )
        self.assertFalse(row_other["fee_paid_by_wallet"])
        self.assertEqual(row_other["native_net_sol"], Decimal("0"))


def _minimal_tx(**overrides):
    base = {
        "signature": "sig-test",
        "slot": 1,
        "timestamp": 1_700_000_000,
        "type": "TRANSFER",
        "source": "SYSTEM",
        "fee": 5_000,
        "feePayer": "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY",
        "nativeTransfers": [],
        "tokenTransfers": [],
    }
    base.update(overrides)
    return base


class ProgramIdsParserTests(unittest.TestCase):
    def test_extracts_program_ids_in_order(self) -> None:
        tx = _minimal_tx(
            instructions=[
                {"programId": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"},
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            ]
        )
        row = TransactionParser("86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY").parse(tx)
        self.assertEqual(
            row["program_ids"],
            [
                "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            ],
        )

    def test_deduplicates_program_ids_preserving_order(self) -> None:
        tx = _minimal_tx(
            instructions=[
                {"programId": "AAA111"},
                {"programId": "BBB222"},
                {"programId": "AAA111"},
            ]
        )
        row = TransactionParser("86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY").parse(tx)
        self.assertEqual(row["program_ids"], ["AAA111", "BBB222"])

    def test_program_ids_empty_when_instructions_absent(self) -> None:
        tx = _minimal_tx()
        row = TransactionParser("86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY").parse(tx)
        self.assertEqual(row["program_ids"], [])

    def test_program_ids_empty_when_instructions_empty(self) -> None:
        tx = _minimal_tx(instructions=[])
        row = TransactionParser("86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY").parse(tx)
        self.assertEqual(row["program_ids"], [])

    def test_instructions_without_program_id_are_skipped(self) -> None:
        tx = _minimal_tx(instructions=[{"data": "abc"}, {"programId": "XYZ999"}])
        row = TransactionParser("86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY").parse(tx)
        self.assertEqual(row["program_ids"], ["XYZ999"])


if __name__ == "__main__":
    unittest.main()
