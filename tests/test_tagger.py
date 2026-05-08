from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_accountant.tagger import TagResult, _tag_row, enrich

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6YaB1pPB263rE4ZW"
JUP_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
RAYDIUM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"


def _row(**kwargs):
    base = {
        "transaction_type": None,
        "source": None,
        "program_ids": [],
        "net_flow": {},
        "token_flow_details": [],
        "movements_in": [],
        "movements_out": [],
        "net_flow_summary": "No net movement",
    }
    base.update(kwargs)
    return base


class Layer1TypeMappingTests(unittest.TestCase):
    def test_swap_jupiter(self) -> None:
        r = _tag_row(_row(transaction_type="SWAP", source="JUPITER"))
        self.assertEqual(r.tag_type, "Swap")
        self.assertEqual(r.tag_protocol, "Jupiter")
        self.assertAlmostEqual(r.tag_confidence, 0.95)

    def test_transfer_system(self) -> None:
        r = _tag_row(_row(transaction_type="TRANSFER", source="SYSTEM_PROGRAM"))
        self.assertEqual(r.tag_type, "Transfer")
        self.assertEqual(r.tag_protocol, "Unknown")
        self.assertAlmostEqual(r.tag_confidence, 0.80)

    def test_nft_sale_tensor(self) -> None:
        r = _tag_row(_row(transaction_type="NFT_SALE", source="TENSOR"))
        self.assertEqual(r.tag_type, "NFT Buy/Sell")
        self.assertEqual(r.tag_protocol, "Tensor")
        self.assertAlmostEqual(r.tag_confidence, 0.95)

    def test_stake_sol_marinade(self) -> None:
        r = _tag_row(_row(transaction_type="STAKE_SOL", source="MARINADE"))
        self.assertEqual(r.tag_type, "Stake/Unstake")
        self.assertEqual(r.tag_protocol, "Marinade")

    def test_add_liquidity_meteora(self) -> None:
        r = _tag_row(_row(transaction_type="ADD_LIQUIDITY", source="METEORA"))
        self.assertEqual(r.tag_type, "LP Deposit/Withdraw")
        self.assertEqual(r.tag_protocol, "Meteora")

    def test_airdrop(self) -> None:
        r = _tag_row(_row(transaction_type="AIRDROP", source=None))
        self.assertEqual(r.tag_type, "Airdrop")

    def test_burn(self) -> None:
        r = _tag_row(_row(transaction_type="BURN", source=None))
        self.assertEqual(r.tag_type, "Mint/Burn")

    def test_bridge(self) -> None:
        r = _tag_row(_row(transaction_type="BRIDGE", source=None))
        self.assertEqual(r.tag_type, "Bridge")

    def test_perpetual_trade_drift(self) -> None:
        r = _tag_row(_row(transaction_type="PERPETUAL_TRADE", source="DRIFT"))
        self.assertEqual(r.tag_type, "Perpetual Trade")
        self.assertEqual(r.tag_protocol, "Drift")

    def test_type_resolves_protocol_from_layer2_when_source_unknown(self) -> None:
        r = _tag_row(
            _row(
                transaction_type="SWAP",
                source="UNKNOWN",
                program_ids=[JUP_PROGRAM],
            )
        )
        self.assertEqual(r.tag_type, "Swap")
        self.assertEqual(r.tag_protocol, "Jupiter")
        self.assertAlmostEqual(r.tag_confidence, 0.80)


class Layer2ProgramIdTests(unittest.TestCase):
    def test_jupiter_program_id(self) -> None:
        r = _tag_row(_row(program_ids=[JUP_PROGRAM]))
        self.assertEqual(r.tag_type, "Swap")
        self.assertEqual(r.tag_protocol, "Jupiter")
        self.assertAlmostEqual(r.tag_confidence, 0.70)

    def test_raydium_program_id(self) -> None:
        r = _tag_row(_row(program_ids=[RAYDIUM_PROGRAM]))
        self.assertEqual(r.tag_type, "Swap")
        self.assertEqual(r.tag_protocol, "Raydium")

    def test_first_match_wins(self) -> None:
        r = _tag_row(_row(program_ids=[JUP_PROGRAM, RAYDIUM_PROGRAM]))
        self.assertEqual(r.tag_protocol, "Jupiter")

    def test_unknown_program_id_falls_through(self) -> None:
        r = _tag_row(_row(program_ids=["AAABBBCCC111"]))
        self.assertEqual(r.tag_type, "Unknown")


class Layer3FlowHeuristicsTests(unittest.TestCase):
    def test_swap_by_flow(self) -> None:
        r = _tag_row(
            _row(
                net_flow={"SOL": Decimal("-0.5"), USDC_MINT: Decimal("100")},
                token_flow_details=[
                    {
                        "mint": USDC_MINT,
                        "symbol": "USDC",
                        "net": Decimal("100"),
                        "in": Decimal("100"),
                        "out": Decimal("0"),
                    }
                ],
            )
        )
        self.assertEqual(r.tag_type, "Swap")
        self.assertAlmostEqual(r.tag_confidence, 0.50)

    def test_transfer_by_flow(self) -> None:
        r = _tag_row(
            _row(
                net_flow={"SOL": Decimal("-0.5")},
                token_flow_details=[],
                movements_out=[{"counterparty": "ReceiverXXX", "asset_type": "native"}],
            )
        )
        self.assertEqual(r.tag_type, "Transfer")
        self.assertAlmostEqual(r.tag_confidence, 0.55)

    def test_airdrop_by_flow(self) -> None:
        r = _tag_row(
            _row(
                net_flow={USDC_MINT: Decimal("50")},
                token_flow_details=[
                    {
                        "mint": USDC_MINT,
                        "symbol": "USDC",
                        "net": Decimal("50"),
                        "in": Decimal("50"),
                        "out": Decimal("0"),
                    }
                ],
                movements_in=[{"counterparty": None, "asset_type": "token"}],
            )
        )
        self.assertEqual(r.tag_type, "Airdrop")
        self.assertAlmostEqual(r.tag_confidence, 0.45)

    def test_unknown_fallback(self) -> None:
        r = _tag_row(_row())
        self.assertEqual(r.tag_type, "Unknown")
        self.assertAlmostEqual(r.tag_confidence, 0.10)


class AssetsDisplayTests(unittest.TestCase):
    def test_swap_sol_to_usdc(self) -> None:
        r = _tag_row(
            _row(
                transaction_type="SWAP",
                source="JUPITER",
                net_flow={"SOL": Decimal("-0.5"), USDC_MINT: Decimal("100")},
                token_flow_details=[
                    {
                        "mint": USDC_MINT,
                        "symbol": "USDC",
                        "net": Decimal("100"),
                        "in": Decimal("100"),
                        "out": Decimal("0"),
                    }
                ],
            )
        )
        self.assertEqual(r.tag_assets, "SOL → USDC")
        self.assertIn("0.5 SOL", r.tag_amount_display)
        self.assertIn("100 USDC", r.tag_amount_display)
        self.assertIn("→", r.tag_amount_display)

    def test_swap_usdc_to_bonk(self) -> None:
        r = _tag_row(
            _row(
                transaction_type="SWAP",
                source="RAYDIUM",
                net_flow={USDC_MINT: Decimal("-50"), BONK_MINT: Decimal("1234567")},
                token_flow_details=[
                    {
                        "mint": USDC_MINT,
                        "symbol": "USDC",
                        "net": Decimal("-50"),
                        "in": Decimal("0"),
                        "out": Decimal("50"),
                    },
                    {
                        "mint": BONK_MINT,
                        "symbol": "BONK",
                        "net": Decimal("1234567"),
                        "in": Decimal("1234567"),
                        "out": Decimal("0"),
                    },
                ],
            )
        )
        self.assertEqual(r.tag_assets, "USDC → BONK")
        self.assertIn("50 USDC", r.tag_amount_display)
        self.assertIn("1,234,567 BONK", r.tag_amount_display)

    def test_transfer_assets(self) -> None:
        r = _tag_row(
            _row(
                transaction_type="TRANSFER",
                source="SYSTEM_PROGRAM",
                net_flow={"SOL": Decimal("-0.5")},
                token_flow_details=[],
            )
        )
        self.assertEqual(r.tag_assets, "SOL")
        self.assertIn("0.5 SOL", r.tag_amount_display)

    def test_unknown_has_empty_assets(self) -> None:
        r = _tag_row(_row())
        self.assertEqual(r.tag_assets, "")
        self.assertEqual(r.tag_amount_display, "")

    def test_usd_estimate_none_without_price_provider(self) -> None:
        r = _tag_row(_row(transaction_type="SWAP", source="JUPITER"))
        self.assertIsNone(r.tag_usd_estimate)


class TagResultTypeTests(unittest.TestCase):
    def test_returns_tag_result_dataclass(self) -> None:
        r = _tag_row(_row(transaction_type="SWAP", source="JUPITER"))
        self.assertIsInstance(r, TagResult)
        self.assertIsInstance(r.tag_type, str)
        self.assertIsInstance(r.tag_protocol, str)
        self.assertIsInstance(r.tag_confidence, float)


class EnrichTests(unittest.TestCase):
    def _make_row(self, **overrides):
        base = {
            "transaction_type": "SWAP",
            "source": "JUPITER",
            "program_ids": [],
            "net_flow": {"SOL": Decimal("-0.5"), BONK_MINT: Decimal("1234567")},
            "token_flow_details": [{"symbol": "BONK", "net": Decimal("1234567")}],
            "movements_in": [],
            "movements_out": [],
            "net_flow_summary": "0.5 SOL out, 1,234,567 BONK in",
        }
        base.update(overrides)
        return base

    def test_enrich_appends_tag_columns(self) -> None:
        import pandas as pd

        df = pd.DataFrame([self._make_row()])
        out = enrich(df)
        for col in (
            "tag_type",
            "tag_protocol",
            "tag_assets",
            "tag_amount_display",
            "tag_usd_estimate",
            "tag_confidence",
        ):
            self.assertIn(col, out.columns, f"missing column: {col}")
        self.assertEqual(out.iloc[0]["tag_type"], "Swap")
        self.assertEqual(out.iloc[0]["tag_protocol"], "Jupiter")

    def test_enrich_does_not_mutate_input(self) -> None:
        import pandas as pd

        df = pd.DataFrame([self._make_row()])
        original_cols = list(df.columns)
        enrich(df)
        self.assertEqual(list(df.columns), original_cols)

    def test_enrich_empty_dataframe_returns_tag_columns(self) -> None:
        import pandas as pd

        df = pd.DataFrame(columns=["transaction_type", "source", "program_ids"])
        out = enrich(df)
        for col in (
            "tag_type",
            "tag_protocol",
            "tag_assets",
            "tag_amount_display",
            "tag_usd_estimate",
            "tag_confidence",
        ):
            self.assertIn(col, out.columns)
        self.assertEqual(len(out), 0)


class BestEffortAssetsTests(unittest.TestCase):
    def test_stake_shows_sol_amount(self) -> None:
        row = {
            "transaction_type": "STAKE_SOL",
            "source": "MARINADE",
            "program_ids": [],
            "net_flow": {"SOL": Decimal("-2.5")},
            "token_flow_details": [],
            "movements_in": [],
            "movements_out": [],
            "net_flow_summary": "2.5 SOL",
        }
        result = _tag_row(row)
        self.assertEqual(result.tag_type, "Stake/Unstake")
        self.assertEqual(result.tag_assets, "SOL")
        self.assertIn("2.5", result.tag_amount_display)

    def test_unknown_type_returns_empty_assets(self) -> None:
        row = {
            "transaction_type": None,
            "source": None,
            "program_ids": [],
            "net_flow": {},
            "token_flow_details": [],
            "movements_in": [],
            "movements_out": [],
            "net_flow_summary": "",
        }
        result = _tag_row(row)
        self.assertEqual(result.tag_type, "Unknown")
        self.assertEqual(result.tag_assets, "")
        self.assertEqual(result.tag_amount_display, "")

    def test_net_flow_summary_fallback_when_no_flows(self) -> None:
        row = {
            "transaction_type": "ADD_LIQUIDITY",
            "source": "METEORA",
            "program_ids": [],
            "net_flow": {},
            "token_flow_details": [],
            "movements_in": [],
            "movements_out": [],
            "net_flow_summary": "2 USDC + 0.5 SOL",
        }
        result = _tag_row(row)
        self.assertEqual(result.tag_type, "LP Deposit/Withdraw")
        self.assertEqual(result.tag_assets, "2 USDC + 0.5 SOL")
        self.assertEqual(result.tag_amount_display, "2 USDC + 0.5 SOL")


class NFTAssetsTests(unittest.TestCase):
    def test_nft_with_sol_shows_sol_amount(self) -> None:
        row = {
            "transaction_type": "NFT_SALE",
            "source": "TENSOR",
            "program_ids": [],
            "net_flow": {"SOL": Decimal("10")},
            "token_flow_details": [{"symbol": "DeGod", "net": Decimal("1")}],
            "movements_in": [],
            "movements_out": [],
            "net_flow_summary": "",
        }
        result = _tag_row(row)
        self.assertEqual(result.tag_type, "NFT Buy/Sell")
        self.assertEqual(result.tag_assets, "DeGod")
        self.assertIn("10", result.tag_amount_display)
        self.assertIn("SOL", result.tag_amount_display)

    def test_nft_without_sol_shows_nft_symbol(self) -> None:
        row = {
            "transaction_type": "NFT_SALE",
            "source": "TENSOR",
            "program_ids": [],
            "net_flow": {},  # no SOL key
            "token_flow_details": [{"symbol": "MyNFT", "net": Decimal("1")}],
            "movements_in": [],
            "movements_out": [],
            "net_flow_summary": "",
        }
        result = _tag_row(row)
        self.assertEqual(result.tag_assets, "MyNFT")
        self.assertEqual(result.tag_amount_display, "MyNFT")


if __name__ == "__main__":
    unittest.main()
