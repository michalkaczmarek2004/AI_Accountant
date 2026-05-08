from __future__ import annotations

import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import DATAFRAME_COLUMNS, InvalidSolanaAddressError
from ai_accountant.dashboard import cache as cache_mod

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"
WALLET2 = "FduuYSbVSJojJL3RjL4QyZsoxtYdqoanZ9whCkQjPCAm"


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=DATAFRAME_COLUMNS)


def _decimal_df() -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {col: None for col in DATAFRAME_COLUMNS},
            {col: None for col in DATAFRAME_COLUMNS},
        ]
    )
    df["signature"] = ["sig-A", "sig-B"]
    df["fee_sol"] = [Decimal("0.000005"), Decimal("0.0000123")]
    df["timestamp_unix"] = [1_700_000_000, 1_700_000_500]
    df["timestamp"] = ["2023-11-14T22:13:20+00:00", "2023-11-14T22:21:40+00:00"]
    return df


def _meta(address: str = WALLET, **overrides) -> dict:
    base = {
        "schema_version": cache_mod.SCHEMA_VERSION,
        "address": address,
        "fetched_at": "2026-05-08T14:33:21Z",
        "pages_fetched": 5,
        "max_pages_at_fetch": 5,
        "row_count": 0,
        "earliest_tx": "",
        "latest_tx": "",
        "ai_accountant_version": "0.1.0",
    }
    base.update(overrides)
    return base


class CacheReadWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(self.id().replace(".", "_") + "_tmp")
        self._tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_read_returns_none_when_no_cache(self) -> None:
        self.assertIsNone(cache_mod.read(WALLET, cache_root=self._tmp))

    def test_write_then_read_round_trip_preserves_decimals(self) -> None:
        df = _decimal_df()
        cache_mod.write(WALLET, df, _meta(row_count=2), cache_root=self._tmp)
        result = cache_mod.read(WALLET, cache_root=self._tmp)
        self.assertIsNotNone(result)
        out_df, out_meta = result
        self.assertEqual(out_df["fee_sol"].tolist(), df["fee_sol"].tolist())
        self.assertEqual(out_meta["row_count"], 2)
        self.assertEqual(out_meta["address"], WALLET)

    def test_schema_version_mismatch_returns_none(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(), cache_root=self._tmp)
        meta_path = self._tmp / WALLET / "meta.json"
        bumped = json.loads(meta_path.read_text())
        bumped["schema_version"] = 99
        meta_path.write_text(json.dumps(bumped))
        self.assertIsNone(cache_mod.read(WALLET, cache_root=self._tmp))

    def test_corrupt_pickle_returns_none(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(), cache_root=self._tmp)
        (self._tmp / WALLET / "transactions.pkl").write_bytes(b"not a pickle")
        self.assertIsNone(cache_mod.read(WALLET, cache_root=self._tmp))

    def test_missing_meta_returns_none(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(), cache_root=self._tmp)
        (self._tmp / WALLET / "meta.json").unlink()
        self.assertIsNone(cache_mod.read(WALLET, cache_root=self._tmp))

    def test_atomic_write_does_not_clobber_on_partial_failure(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(row_count=1), cache_root=self._tmp)
        stale_pkl = self._tmp / WALLET / "transactions.pkl.tmp"
        stale_pkl.write_bytes(b"interrupted")
        result = cache_mod.read(WALLET, cache_root=self._tmp)
        self.assertIsNotNone(result)
        self.assertEqual(result[1]["row_count"], 1)


class CacheListWalletsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(self.id().replace(".", "_") + "_tmp")
        self._tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_list_wallets_empty(self) -> None:
        self.assertEqual(cache_mod.list_wallets(cache_root=self._tmp), [])

    def test_list_wallets_sorted_by_fetched_at_desc(self) -> None:
        cache_mod.write(
            WALLET,
            _empty_df(),
            _meta(address=WALLET, fetched_at="2026-05-01T10:00:00Z"),
            cache_root=self._tmp,
        )
        cache_mod.write(
            WALLET2,
            _empty_df(),
            _meta(address=WALLET2, fetched_at="2026-05-08T10:00:00Z"),
            cache_root=self._tmp,
        )
        wallets = cache_mod.list_wallets(cache_root=self._tmp)
        self.assertEqual([w.address for w in wallets], [WALLET2, WALLET])

    def test_list_wallets_skips_invalid_directories(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(), cache_root=self._tmp)
        (self._tmp / "not-a-real-wallet").mkdir()
        wallets = cache_mod.list_wallets(cache_root=self._tmp)
        self.assertEqual([w.address for w in wallets], [WALLET])


class CacheForgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(self.id().replace(".", "_") + "_tmp")
        self._tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_forget_removes_wallet_directory(self) -> None:
        cache_mod.write(WALLET, _empty_df(), _meta(), cache_root=self._tmp)
        self.assertTrue(cache_mod.forget(WALLET, cache_root=self._tmp))
        self.assertIsNone(cache_mod.read(WALLET, cache_root=self._tmp))

    def test_forget_returns_false_when_no_cache(self) -> None:
        self.assertFalse(cache_mod.forget(WALLET, cache_root=self._tmp))


class CacheAddressValidationTests(unittest.TestCase):
    def test_read_with_invalid_address_raises(self) -> None:
        with self.assertRaises(InvalidSolanaAddressError):
            cache_mod.read("not-a-wallet", cache_root=Path("."))

    def test_write_with_invalid_address_raises(self) -> None:
        with self.assertRaises(InvalidSolanaAddressError):
            cache_mod.write("not-a-wallet", _empty_df(), _meta(), cache_root=Path("."))

    def test_forget_with_invalid_address_raises(self) -> None:
        with self.assertRaises(InvalidSolanaAddressError):
            cache_mod.forget("../etc", cache_root=Path("."))


if __name__ == "__main__":
    unittest.main()
