from __future__ import annotations

import unittest
from decimal import Decimal

from ai_accountant.explainer import _format_sol, _shorten_address


class ShortenAddressTests(unittest.TestCase):
    def test_long_address_truncated(self):
        self.assertEqual(_shorten_address("AbcDEFGH12345678abcdefgh"), "AbcD…efgh")

    def test_address_exactly_8_chars_unchanged(self):
        self.assertEqual(_shorten_address("Abcd1234"), "Abcd1234")

    def test_short_address_unchanged(self):
        self.assertEqual(_shorten_address("Ab12"), "Ab12")

    def test_empty_string(self):
        self.assertEqual(_shorten_address(""), "")


class FormatSolTests(unittest.TestCase):
    def test_positive_decimal(self):
        self.assertEqual(_format_sol(Decimal("1.5")), "1.5 SOL")

    def test_negative_uses_absolute_value(self):
        self.assertEqual(_format_sol(Decimal("-0.5")), "0.5 SOL")

    def test_zero(self):
        self.assertEqual(_format_sol(Decimal("0")), "0 SOL")

    def test_small_amount(self):
        self.assertEqual(_format_sol(Decimal("0.000005")), "0.000005 SOL")

    def test_none_treated_as_zero(self):
        self.assertEqual(_format_sol(None), "0 SOL")


if __name__ == "__main__":
    unittest.main()


import pandas as pd

from ai_accountant.explainer import TransactionExplanation, explain_row

_SIG = "AbcDEFGH12345678abcdefgh12345678abcdefgh12345678abcdefgh1234567"


def _base_row(**overrides) -> pd.Series:
    row = {
        "tag_type": "Transfer",
        "tag_protocol": "Unknown",
        "tag_assets": "SOL",
        "tag_amount_display": "1 SOL",
        "tag_confidence": 0.8,
        "source": "UNKNOWN",
        "status": "succeeded",
        "fee_sol": Decimal("0.000005"),
        "native_net_sol": Decimal("1.0"),
        "token_flow_details": [],
        "date": "2024-01-01",
        "signature": _SIG,
        "description": "SOL transfer",
    }
    row.update(overrides)
    return pd.Series(row)


class ExplainRowTests(unittest.TestCase):
    def test_incoming_sol_source_unknown(self):
        row = _base_row(
            tag_type="Transfer", tag_protocol="Unknown", source="UNKNOWN",
            native_net_sol=Decimal("1.0"), tag_confidence=0.8,
        )
        exp = explain_row(row)
        self.assertIsInstance(exp, TransactionExplanation)
        self.assertEqual(exp.event_title, "Received SOL")
        self.assertEqual(exp.review_label, "Source unknown")
        self.assertEqual(exp.confidence_percent, 80)
        self.assertIn("source_unknown", exp.tags)
        self.assertIn("needs_label", exp.tags)
        self.assertIsInstance(exp.short_explanation, str)
        self.assertIsInstance(exp.known_facts, list)
        self.assertTrue(all(isinstance(f, str) for f in exp.known_facts))
        self.assertIsInstance(exp.unknown_facts, list)
        self.assertTrue(all(isinstance(f, str) for f in exp.unknown_facts))
        self.assertIsInstance(exp.suggested_actions, list)
        self.assertTrue(all(isinstance(a, str) for a in exp.suggested_actions))
        self.assertIsInstance(exp.expanded_explanation, str)
        self.assertIsInstance(exp.technical_summary, str)
        self.assertIsInstance(exp.tags, list)

    def test_outgoing_sol_known_source(self):
        row = _base_row(
            tag_type="Transfer", tag_protocol="Unknown", source="SYSTEM_PROGRAM",
            native_net_sol=Decimal("-0.5"), tag_confidence=0.8,
        )
        exp = explain_row(row)
        self.assertEqual(exp.event_title, "Sent SOL")
        self.assertEqual(exp.review_label, "No action needed")
        self.assertIn("outgoing", exp.tags)
        self.assertIn("sol", exp.tags)
        self.assertIsInstance(exp.confidence_percent, int)

    def test_swap(self):
        row = _base_row(
            tag_type="Swap", tag_protocol="Jupiter", source="JUPITER",
            tag_assets="SOL → USDC", tag_amount_display="1 SOL → 150 USDC",
            native_net_sol=Decimal("-1.0"), tag_confidence=0.95,
            token_flow_details=[{"symbol": "USDC", "net": Decimal("150"), "mint": "EPjF…"}],
        )
        exp = explain_row(row)
        self.assertEqual(exp.event_title, "Swapped tokens")
        self.assertEqual(exp.review_label, "Tax-relevant review")
        self.assertIn("swap", exp.tags)
        self.assertIn("tax_relevant", exp.tags)
        self.assertIsInstance(exp.suggested_actions, list)

    def test_unknown_program(self):
        row = _base_row(
            tag_type="Unknown", tag_protocol="Unknown", source="UNKNOWN",
            tag_assets="", tag_amount_display="",
            native_net_sol=Decimal("0"), tag_confidence=0.70,
            token_flow_details=[], description="",
        )
        exp = explain_row(row)
        self.assertEqual(exp.review_label, "Unknown program")
        self.assertIn("unknown_program", exp.tags)
        self.assertIsInstance(exp.suggested_actions, list)
        self.assertTrue(len(exp.suggested_actions) >= 1)

    def test_nft_received(self):
        row = _base_row(
            tag_type="NFT Buy/Sell", tag_protocol="Tensor", source="TENSOR",
            native_net_sol=Decimal("0"), tag_confidence=0.80,
        )
        exp = explain_row(row)
        self.assertEqual(exp.event_title, "Received NFT")
        self.assertEqual(exp.review_label, "Review NFT source")
        self.assertIn("nft", exp.tags)
        self.assertIn("incoming", exp.tags)

    def test_staked_sol(self):
        row = _base_row(
            tag_type="Stake/Unstake", tag_protocol="Marinade", source="MARINADE",
            native_net_sol=Decimal("-5.0"), tag_confidence=0.95,
        )
        exp = explain_row(row)
        self.assertEqual(exp.event_title, "Staked SOL")
        self.assertEqual(exp.review_label, "No action needed")
        self.assertIn("staking", exp.tags)

    def test_unknown_low_confidence(self):
        row = _base_row(
            tag_type="Unknown", tag_protocol="Unknown", source="UNKNOWN",
            tag_assets="", tag_amount_display="",
            native_net_sol=Decimal("0"), tag_confidence=0.30,
            token_flow_details=[], description="",
        )
        exp = explain_row(row)
        self.assertEqual(exp.event_title, "Unknown activity")
        self.assertEqual(exp.review_label, "Needs review")
        self.assertIn("low_confidence", exp.tags)
