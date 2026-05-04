"""Solana address validation. Stdlib-only Base58 decode."""

from __future__ import annotations

from .exceptions import InvalidSolanaAddressError

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {character: index for index, character in enumerate(BASE58_ALPHABET)}


def validate_address(address: str) -> str:
    """Validate a Solana public key and return the stripped value."""
    if not isinstance(address, str):
        raise InvalidSolanaAddressError("Wallet address must be a string.")

    normalized = address.strip()
    if not normalized:
        raise InvalidSolanaAddressError("Wallet address cannot be empty.")

    decoded = _decode_base58(normalized)
    if len(decoded) != 32:
        raise InvalidSolanaAddressError(
            "Wallet address must decode to a 32-byte Solana public key."
        )
    return normalized


def _decode_base58(value: str) -> bytes:
    number = 0
    for character in value:
        if character not in BASE58_INDEX:
            raise InvalidSolanaAddressError(
                f"Wallet address contains invalid Base58 character: {character!r}."
            )
        number = (number * 58) + BASE58_INDEX[character]

    decoded = b""
    if number:
        decoded = number.to_bytes((number.bit_length() + 7) // 8, "big")

    leading_zeroes = len(value) - len(value.lstrip("1"))
    return (b"\x00" * leading_zeroes) + decoded
