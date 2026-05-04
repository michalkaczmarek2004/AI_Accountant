from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant import (
    HeliusRateLimitError,
    InvalidSolanaAddressError,
    SolanaDataFetcher,
)
from ai_accountant.transport import _CaseInsensitiveHeaders

WALLET_ADDRESS = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        payload=None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        raw = headers or {}
        self.headers = _CaseInsensitiveHeaders(raw.items())

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def get(self, url, params=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError("No fake responses remaining.")
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class SolanaDataFetcherTests(unittest.TestCase):
    def test_transactions_to_dataframe_parses_native_token_flows_and_fees(self):
        fetcher = SolanaDataFetcher(api_key="test-key")
        transactions = [
            {
                "signature": "sig-001",
                "slot": 123456,
                "timestamp": 1_700_000_000,
                "type": "SWAP",
                "description": "Swapped SOL for tokens",
                "source": "JUPITER",
                "fee": 5_000,
                "feePayer": WALLET_ADDRESS,
                "nativeTransfers": [
                    {
                        "fromUserAccount": WALLET_ADDRESS,
                        "toUserAccount": "CounterpartyOut11111111111111111111111111",
                        "amount": 200_000_000,
                    },
                    {
                        "fromUserAccount": "CounterpartyIn111111111111111111111111111",
                        "toUserAccount": WALLET_ADDRESS,
                        "amount": 50_000_000,
                    },
                ],
                "tokenTransfers": [
                    {
                        "fromUserAccount": WALLET_ADDRESS,
                        "toUserAccount": "Pool1111111111111111111111111111111111111",
                        "fromTokenAccount": "FromToken11111111111111111111111111111111",
                        "toTokenAccount": "ToToken1111111111111111111111111111111111",
                        "tokenAmount": "25",
                        "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                        "tokenSymbol": "USDC",
                    },
                    {
                        "fromUserAccount": "Pool1111111111111111111111111111111111111",
                        "toUserAccount": WALLET_ADDRESS,
                        "fromTokenAccount": "FromToken22222222222222222222222222222222",
                        "toTokenAccount": "ToToken2222222222222222222222222222222222",
                        "tokenAmount": "1000",
                        "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW",
                        "tokenSymbol": "BONK",
                    },
                ],
            }
        ]

        frame = fetcher.transactions_to_dataframe(WALLET_ADDRESS, transactions)

        self.assertEqual(list(frame.columns), SolanaDataFetcher.DATAFRAME_COLUMNS)
        self.assertEqual(len(frame), 1)

        row = frame.iloc[0]
        self.assertEqual(row["signature"], "sig-001")
        self.assertEqual(row["timestamp"], "2023-11-14 22:13:20")
        self.assertEqual(row["transaction_type"], "SWAP")
        self.assertEqual(row["description"], "Swapped SOL for tokens")
        self.assertEqual(row["fee_sol"], Decimal("0.000005"))
        self.assertEqual(row["native_in_sol"], Decimal("0.05"))
        self.assertEqual(row["native_out_sol"], Decimal("0.2"))
        self.assertEqual(row["native_transfer_net_sol"], Decimal("-0.15"))
        self.assertEqual(row["native_net_sol"], Decimal("-0.150005"))
        self.assertEqual(row["net_flow"]["SOL"], Decimal("-0.150005"))
        self.assertEqual(
            row["net_flow"]["EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"],
            Decimal("-25"),
        )
        self.assertEqual(
            row["net_flow"]["DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW"],
            Decimal("1000"),
        )
        self.assertEqual(row["status"], "succeeded")

        self.assertEqual(
            row["movements_in"],
            [
                {
                    "asset_type": "native",
                    "symbol": "SOL",
                    "mint": None,
                    "amount": Decimal("0.05"),
                    "amount_lamports": 50_000_000,
                    "from_user_account": "CounterpartyIn111111111111111111111111111",
                    "to_user_account": WALLET_ADDRESS,
                    "direction": "in",
                    "counterparty": "CounterpartyIn111111111111111111111111111",
                },
                {
                    "asset_type": "token",
                    "symbol": "BONK",
                    "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW",
                    "amount": Decimal("1000"),
                    "from_user_account": "Pool1111111111111111111111111111111111111",
                    "to_user_account": WALLET_ADDRESS,
                    "from_token_account": "FromToken22222222222222222222222222222222",
                    "to_token_account": "ToToken2222222222222222222222222222222222",
                    "direction": "in",
                    "counterparty": "Pool1111111111111111111111111111111111111",
                },
            ],
        )

        self.assertEqual(
            row["movements_out"],
            [
                {
                    "asset_type": "native",
                    "symbol": "SOL",
                    "mint": None,
                    "amount": Decimal("0.2"),
                    "amount_lamports": 200_000_000,
                    "from_user_account": WALLET_ADDRESS,
                    "to_user_account": "CounterpartyOut11111111111111111111111111",
                    "direction": "out",
                    "counterparty": "CounterpartyOut11111111111111111111111111",
                },
                {
                    "asset_type": "token",
                    "symbol": "USDC",
                    "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "amount": Decimal("25"),
                    "from_user_account": WALLET_ADDRESS,
                    "to_user_account": "Pool1111111111111111111111111111111111111",
                    "from_token_account": "FromToken11111111111111111111111111111111",
                    "to_token_account": "ToToken1111111111111111111111111111111111",
                    "direction": "out",
                    "counterparty": "Pool1111111111111111111111111111111111111",
                },
            ],
        )

        self.assertEqual(
            row["token_flow_details"],
            [
                {
                    "symbol": "BONK",
                    "mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW",
                    "label": "BONK (DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW)",
                    "in": Decimal("1000"),
                    "out": Decimal("0"),
                    "net": Decimal("1000"),
                },
                {
                    "symbol": "USDC",
                    "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "label": "USDC (EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v)",
                    "in": Decimal("0"),
                    "out": Decimal("25"),
                    "net": Decimal("-25"),
                },
            ],
        )

    def test_fetch_transaction_history_uses_before_signature_pagination(self):
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    payload=[
                        {"signature": "sig-003"},
                        {"signature": "sig-002"},
                    ],
                ),
                FakeResponse(
                    200,
                    payload=[
                        {"signature": "sig-001"},
                    ],
                ),
                FakeResponse(200, payload=[]),
            ]
        )
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)

        transactions = fetcher.fetch_transaction_history(WALLET_ADDRESS)

        self.assertEqual(
            [transaction["signature"] for transaction in transactions],
            ["sig-003", "sig-002", "sig-001"],
        )
        self.assertEqual(session.calls[0]["params"]["sort-order"], "desc")
        self.assertNotIn("before-signature", session.calls[0]["params"])
        self.assertEqual(session.calls[1]["params"]["before-signature"], "sig-002")
        self.assertEqual(session.calls[2]["params"]["before-signature"], "sig-001")

    def test_fetch_transaction_history_retries_after_rate_limit(self):
        session = FakeSession(
            [
                FakeResponse(
                    429,
                    payload={"message": "Too many requests"},
                    headers={"Retry-After": "0"},
                ),
                FakeResponse(200, payload=[]),
            ]
        )
        sleep_calls: list[float] = []
        fetcher = SolanaDataFetcher(
            api_key="test-key",
            session=session,
            sleep_func=sleep_calls.append,
        )

        transactions = fetcher.fetch_transaction_history(WALLET_ADDRESS)

        self.assertEqual(transactions, [])
        self.assertEqual(sleep_calls, [0.0])

    def test_fetch_transaction_history_raises_rate_limit_after_retry_exhaustion(self):
        session = FakeSession(
            [
                FakeResponse(429, payload={"message": "Too many requests"}),
                FakeResponse(429, payload={"message": "Still limited"}),
            ]
        )
        fetcher = SolanaDataFetcher(
            api_key="test-key",
            session=session,
            max_retries=1,
            sleep_func=lambda _: None,
        )

        with self.assertRaises(HeliusRateLimitError):
            fetcher.fetch_transaction_history(WALLET_ADDRESS)

    def test_invalid_address_fails_fast_without_http_request(self):
        session = FakeSession([])
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)

        with self.assertRaises(InvalidSolanaAddressError):
            fetcher.fetch_transaction_history("not-a-valid-solana-address")

        self.assertEqual(session.calls, [])

    def test_iter_transactions_yields_one_at_a_time(self):
        session = FakeSession(
            [
                FakeResponse(
                    200,
                    payload=[
                        {"signature": "sig-3"},
                        {"signature": "sig-2"},
                    ],
                ),
                FakeResponse(200, payload=[{"signature": "sig-1"}]),
                FakeResponse(200, payload=[]),
            ]
        )
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        seen: list[str] = []
        for tx in fetcher.iter_transactions(WALLET_ADDRESS):
            seen.append(tx["signature"])
        self.assertEqual(seen, ["sig-3", "sig-2", "sig-1"])

    def test_iter_transactions_invokes_cursor_callback_per_page(self):
        session = FakeSession(
            [
                FakeResponse(200, payload=[{"signature": "sig-3"}, {"signature": "sig-2"}]),
                FakeResponse(200, payload=[{"signature": "sig-1"}]),
                FakeResponse(200, payload=[]),
            ]
        )
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        cursors: list[str] = []
        list(
            fetcher.iter_transactions(
                WALLET_ADDRESS,
                on_cursor_advance=cursors.append,
            )
        )
        # Callback fires after each page that produced a NEW cursor for the
        # NEXT request. After page 1 cursor advances to "sig-2", after page 2
        # cursor advances to "sig-1". Page 3 is empty — no further advance.
        self.assertEqual(cursors, ["sig-2", "sig-1"])

    def test_iter_transactions_callback_not_invoked_after_terminal_page(self):
        session = FakeSession([FakeResponse(200, payload=[])])
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        cursors: list[str] = []
        list(
            fetcher.iter_transactions(
                WALLET_ADDRESS,
                on_cursor_advance=cursors.append,
            )
        )
        self.assertEqual(cursors, [])

    def test_fetch_transaction_history_returns_concrete_list(self):
        session = FakeSession(
            [
                FakeResponse(200, payload=[{"signature": "sig-1"}]),
                FakeResponse(200, payload=[]),
            ]
        )
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        result = fetcher.fetch_transaction_history(WALLET_ADDRESS)
        self.assertIsInstance(result, list)
        self.assertEqual(result, [{"signature": "sig-1"}])

    def test_payload_validation_non_object_item_raises_helius_api_error(self):
        from ai_accountant import HeliusAPIError

        session = FakeSession(
            [
                FakeResponse(200, payload=[{"signature": "ok"}, "not-an-object"]),
            ]
        )
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        with self.assertRaises(HeliusAPIError) as ctx:
            fetcher.fetch_transaction_history(WALLET_ADDRESS)
        self.assertIn("not a JSON object", str(ctx.exception))

    def test_payload_validation_non_list_top_level_raises_helius_api_error(self):
        from ai_accountant import HeliusAPIError

        session = FakeSession(
            [
                FakeResponse(200, payload={"unexpected": "shape"}),
            ]
        )
        fetcher = SolanaDataFetcher(api_key="test-key", session=session)
        with self.assertRaises(HeliusAPIError):
            fetcher.fetch_transaction_history(WALLET_ADDRESS)

    def test_retry_after_lowercase_header_respected(self):
        session = FakeSession(
            [
                FakeResponse(429, payload={"message": "slow down"}, headers={"retry-after": "0"}),
                FakeResponse(200, payload=[]),
            ]
        )
        sleep_calls: list[float] = []
        fetcher = SolanaDataFetcher(
            api_key="test-key",
            session=session,
            sleep_func=sleep_calls.append,
        )
        result = fetcher.fetch_transaction_history(WALLET_ADDRESS)
        self.assertEqual(result, [])
        self.assertEqual(sleep_calls, [0.0])

    def test_retry_after_http_date_header_respected(self):
        # The HTTP-date branch is tested directly in test_transport.py with a
        # mocked `now`. Here we just verify the integration: a syntactically
        # valid HTTP-date is accepted (parsed without raising) and a retry
        # actually happens.
        session = FakeSession(
            [
                FakeResponse(
                    429,
                    payload={"message": "slow"},
                    headers={"Retry-After": "Mon, 04 May 2026 12:00:00 GMT"},
                ),
                FakeResponse(200, payload=[]),
            ]
        )
        sleep_calls: list[float] = []
        fetcher = SolanaDataFetcher(
            api_key="test-key",
            session=session,
            sleep_func=sleep_calls.append,
        )
        result = fetcher.fetch_transaction_history(WALLET_ADDRESS)
        self.assertEqual(result, [])
        self.assertEqual(len(sleep_calls), 1)
        # Delay clamped at 0 if date is in the past relative to wall clock.
        self.assertGreaterEqual(sleep_calls[0], 0.0)


if __name__ == "__main__":
    unittest.main()
