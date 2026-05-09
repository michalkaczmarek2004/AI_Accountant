from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS, HeliusAuthenticationError, HeliusRateLimitError
from ai_accountant.dashboard.demo import DEMO_DATASET_LABEL, DEMO_WALLET_ADDRESS
from ai_accountant.dashboard.server import create_app

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
WALLET_BAD = "not-a-wallet"


class _FakeFetcher:
    def __init__(self, *, df=None, raises=None) -> None:
        self.df = df if df is not None else pd.DataFrame(columns=DATAFRAME_COLUMNS)
        self.raises = raises
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None

    def fetch_transactions_dataframe(self, wallet_address, *, max_pages=None, **_kw):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return self.df


class _RouteCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.id().replace(".", "_") + "_tmp")
        self.tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)
        self.fake = _FakeFetcher()
        self.app = create_app(
            helius_api_key="k",
            max_pages=5,
            cache_root=self.tmp,
            fetcher_factory=lambda: self.fake,
        )
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


class LandingRouteTests(_RouteCase):
    def test_get_landing_renders(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Solana wallet address", resp.data)

    def test_post_invalid_address_returns_400_with_message(self) -> None:
        resp = self.client.post("/", data={"address": WALLET_BAD})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"address", resp.data.lower())

    def test_post_valid_address_fetches_and_redirects(self) -> None:
        resp = self.client.post("/", data={"address": WALLET})
        self.assertEqual(resp.status_code, 303)
        self.assertIn(WALLET, resp.headers["Location"])
        self.assertEqual(self.fake.calls, 1)

    def test_demo_route_seeds_cache_and_redirects(self) -> None:
        resp = self.client.post("/demo")
        self.assertEqual(resp.status_code, 303)
        self.assertIn(DEMO_WALLET_ADDRESS, resp.headers["Location"])
        self.assertTrue((self.tmp / DEMO_WALLET_ADDRESS / "transactions.pkl").exists())
        wallet_resp = self.client.get(f"/wallet/{DEMO_WALLET_ADDRESS}")
        self.assertEqual(wallet_resp.status_code, 200)
        self.assertIn(DEMO_DATASET_LABEL.encode(), wallet_resp.data)
        self.assertIn(b"/tax-country?tax_country=US", wallet_resp.data)
        self.assertIn(b"ai-chart-line", wallet_resp.data)
        self.assertIn(b"ai-chart-bar", wallet_resp.data)
        self.assertIn(b"23.1%", wallet_resp.data)
        self.assertIn(b"7.7%", wallet_resp.data)
        self.assertNotIn(b"7.692307692307", wallet_resp.data)
        self.assertNotIn(b"Pages:", wallet_resp.data)

        tax_resp = self.client.get(f"/wallet/{DEMO_WALLET_ADDRESS}/tax")
        self.assertEqual(tax_resp.status_code, 200)
        self.assertIn(b"Tax country", tax_resp.data)
        self.assertIn(b"United States notes", tax_resp.data)
        self.assertIn(b"IRS digital assets guidance", tax_resp.data)
        self.assertIn(b"Tax Deadlines", tax_resp.data)
        self.assertIn(b'data-ack-scope="tax-deadlines"', tax_resp.data)
        self.assertIn(b'data-ack-kind="deadline"', tax_resp.data)
        self.assertIn(b"Mark as done", tax_resp.data)
        self.assertNotIn(b"Show confirmed items again", tax_resp.data)
        self.assertIn(b"IRS Publication 505", tax_resp.data)
        self.assertIn(b"Likely United States tax treatment", tax_resp.data)
        self.assertIn(b"Possible tax:", tax_resp.data)
        self.assertIn(b"How to calculate:", tax_resp.data)
        self.assertIn(b"Form 8949", tax_resp.data)
        self.assertIn(b"Deadline reminder", tax_resp.data)
        self.assertIn(b"Fee-only unknown program interaction", tax_resp.data)
        self.assertIn(b"Mark reviewed", tax_resp.data)
        self.assertIn(b"Why this needs review", tax_resp.data)
        self.assertIn(b"Suggested next step", tax_resp.data)
        self.assertIn(b"Tax/accounting note", tax_resp.data)
        self.assertNotIn(b"No action needed", tax_resp.data)


class WalletRouteTests(_RouteCase):
    def test_uncached_wallet_renders_empty_state(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No data cached", resp.data)
        self.assertEqual(self.fake.calls, 0)

    def test_filter_change_does_not_call_fetcher(self) -> None:
        self.client.post("/", data={"address": WALLET})
        self.fake.calls = 0
        resp = self.client.get(f"/wallet/{WALLET}?status=failed")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.fake.calls, 0)

    def test_invalid_address_returns_404(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET_BAD}")
        self.assertEqual(resp.status_code, 404)

    def test_path_traversal_returns_404(self) -> None:
        resp = self.client.get("/wallet/..%2Fetc")
        self.assertEqual(resp.status_code, 404)


class RefreshRouteTests(_RouteCase):
    def test_refresh_calls_fetcher_once_and_redirects(self) -> None:
        self.client.post("/", data={"address": WALLET})
        self.fake.calls = 0
        resp = self.client.post(f"/wallet/{WALLET}/refresh")
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(self.fake.calls, 1)

    def test_refresh_with_auth_error_renders_error_page(self) -> None:
        self.fake.raises = HeliusAuthenticationError("nope")
        resp = self.client.post(f"/wallet/{WALLET}/refresh")
        self.assertEqual(resp.status_code, 502)
        self.assertIn(b"nope", resp.data)

    def test_refresh_with_rate_limit_renders_503(self) -> None:
        self.fake.raises = HeliusRateLimitError("slow down")
        resp = self.client.post(f"/wallet/{WALLET}/refresh")
        self.assertEqual(resp.status_code, 503)


class ForgetRouteTests(_RouteCase):
    def test_forget_removes_cache_and_redirects(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.post(f"/wallet/{WALLET}/forget")
        self.assertEqual(resp.status_code, 303)
        self.assertFalse((self.tmp / WALLET / "transactions.pkl").exists())


class ExportRouteTests(_RouteCase):
    def test_export_csv_returns_200_with_csv_mimetype(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}/export.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.mimetype.startswith("text/csv"))

    def test_export_json_returns_200_with_json_mimetype(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}/export.json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.mimetype.startswith("application/json"))

    def test_export_pdf_returns_200_with_pdf_mimetype(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}/report.pdf")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.mimetype.startswith("application/pdf"))
        self.assertTrue(resp.data.startswith(b"%PDF-"))

    def test_empty_filter_export_returns_200_not_404(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}/export.csv?status=failed")
        self.assertEqual(resp.status_code, 200)


class TransactionDetailTests(_RouteCase):
    def test_unknown_signature_returns_404(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}/tx/" + "1" * 88)
        self.assertEqual(resp.status_code, 404)


class MalformedQuerystringTests(_RouteCase):
    def test_bad_date_in_querystring_returns_200(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}?from=2025-13-99")
        self.assertEqual(resp.status_code, 200)


def _tagged_df():
    row = {col: None for col in DATAFRAME_COLUMNS}
    row.update(
        signature="sig-tag-1",
        timestamp_unix=1_700_000_000,
        status="succeeded",
        transaction_type="SWAP",
        source="JUPITER",
        fee_sol=__import__("decimal").Decimal("0.000005"),
        tag_type="Swap",
        tag_protocol="Jupiter",
        tag_assets="SOL → USDC",
        tag_amount_display="0.5 SOL → 100 USDC",
        tag_usd_estimate=None,
        tag_confidence=0.95,
        program_ids=[],
        net_flow={},
        token_flow_details=[],
        movements_in=[],
        movements_out=[],
    )
    return pd.DataFrame([row], columns=DATAFRAME_COLUMNS)


class TaggedDashboardRenderTests(_RouteCase):
    def setUp(self) -> None:
        super().setUp()
        self.fake.df = _tagged_df()

    def test_wallet_page_renders_tag_type_column(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn("Swap", html)
        self.assertIn("Jupiter", html)

    def test_tag_filter_dropdown_present(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}")
        html = resp.data.decode()
        self.assertIn('name="tag"', html)

    def test_tag_querystring_preserved_in_pagination(self) -> None:
        self.client.post("/", data={"address": WALLET})
        resp = self.client.get(f"/wallet/{WALLET}?tag=Swap")
        self.assertEqual(resp.status_code, 200)


class TaxRouteTests(_RouteCase):
    def setUp(self) -> None:
        super().setUp()
        # Seed the cache by triggering a fetch with the fake fetcher
        self.client.post("/", data={"address": WALLET})

    def test_tax_page_returns_200(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET}/tax")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content_type.startswith("text/html"))

    def test_tax_country_page_returns_200(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET}/tax-country?tax_country=US")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"United States notes", resp.data)

    def test_tax_page_contains_disclaimer(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET}/tax")
        self.assertIn(b"not financial or tax advice", resp.data)

    def test_tax_page_unknown_address_returns_404(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET_BAD}/tax")
        self.assertEqual(resp.status_code, 404)

    def test_tax_page_uncached_wallet_returns_404(self) -> None:
        OTHER = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
        resp = self.client.get(f"/wallet/{OTHER}/tax")
        self.assertEqual(resp.status_code, 404)

    def test_tax_export_csv_returns_200_with_csv_mimetype(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET}/tax-export.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.mimetype.startswith("text/csv"))

    def test_tax_export_json_returns_200_with_json_mimetype(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET}/tax-export.json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.mimetype.startswith("application/json"))

    def test_tax_export_json_contains_disclaimer(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET}/tax-export.json")
        self.assertIn(b"not financial or tax advice", resp.data)

    def test_tax_export_json_has_meta_and_transactions_keys(self) -> None:
        import json
        resp = self.client.get(f"/wallet/{WALLET}/tax-export.json")
        body = json.loads(resp.data)
        self.assertIn("meta", body)
        self.assertIn("transactions", body)
        self.assertIn("summary", body)
        self.assertIn("yearly", body)

    def test_tax_summary_csv_returns_200_with_csv_mimetype(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET}/tax-summary.csv")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.mimetype.startswith("text/csv"))

    def test_tax_export_csv_unknown_address_returns_404(self) -> None:
        resp = self.client.get(f"/wallet/{WALLET_BAD}/tax-export.csv")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
