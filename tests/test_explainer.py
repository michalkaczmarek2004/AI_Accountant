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
