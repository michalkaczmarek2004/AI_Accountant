from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant import InvalidSolanaAddressError
from ai_accountant.addresses import _decode_base58, validate_address

VALID_WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


class AddressesTests(unittest.TestCase):
    def test_validate_address_accepts_valid_base58(self):
        self.assertEqual(validate_address(VALID_WALLET), VALID_WALLET)

    def test_validate_address_strips_whitespace(self):
        self.assertEqual(validate_address(f"  {VALID_WALLET}  "), VALID_WALLET)

    def test_validate_address_rejects_wrong_length(self):
        with self.assertRaises(InvalidSolanaAddressError):
            validate_address("11111111")

    def test_validate_address_rejects_non_base58_characters(self):
        with self.assertRaises(InvalidSolanaAddressError):
            validate_address("0OIl" + VALID_WALLET[4:])

    def test_validate_address_rejects_non_string(self):
        with self.assertRaises(InvalidSolanaAddressError):
            validate_address(12345)  # type: ignore[arg-type]

    def test_validate_address_rejects_empty_string(self):
        with self.assertRaises(InvalidSolanaAddressError):
            validate_address("   ")

    def test_decode_base58_round_trip_length(self):
        decoded = _decode_base58(VALID_WALLET)
        self.assertEqual(len(decoded), 32)


if __name__ == "__main__":
    unittest.main()
