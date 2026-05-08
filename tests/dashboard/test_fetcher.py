from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant import (
    DATAFRAME_COLUMNS,
    HeliusAuthenticationError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
)
from ai_accountant.dashboard import cache as cache_mod
from ai_accountant.dashboard.fetcher import (
    DashboardError,
    RefreshLocked,
    run_fetch,
)

WALLET = "86xCnPeV69n6t3DnyGvkKobf9FdN2H9oiVDdaMpo2MMY"


class _FakeFetcher:
    def __init__(self, *, df: pd.DataFrame | None = None, raises: BaseException | None = None) -> None:
        self.df = df if df is not None else pd.DataFrame(columns=DATAFRAME_COLUMNS)
        self.raises = raises
        self.calls = 0
        self.last_args: tuple = ()

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None

    def fetch_transactions_dataframe(self, wallet_address, *, max_pages=None, **_kw):
        self.calls += 1
        self.last_args = (wallet_address, max_pages)
        if self.raises is not None:
            raise self.raises
        return self.df


class _Tmp(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.id().replace(".", "_") + "_tmp")
        self.tmp.mkdir(exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)


class HappyPathTests(_Tmp):
    def test_run_fetch_writes_cache_and_returns_dataframe(self) -> None:
        fake = _FakeFetcher()
        df, meta = run_fetch(
            WALLET,
            helius_api_key="k",
            max_pages=5,
            cache_root=self.tmp,
            fetcher_factory=lambda: fake,
        )
        self.assertEqual(fake.calls, 1)
        self.assertEqual(fake.last_args, (WALLET, 5))
        self.assertEqual(meta["address"], WALLET)
        self.assertEqual(meta["max_pages_at_fetch"], 5)
        self.assertEqual(meta["row_count"], 0)
        self.assertTrue((self.tmp / WALLET / "transactions.pkl").exists())
        self.assertTrue((self.tmp / WALLET / "meta.json").exists())

    def test_unbounded_max_pages_zero_means_none(self) -> None:
        fake = _FakeFetcher()
        run_fetch(
            WALLET,
            helius_api_key="k",
            max_pages=0,
            cache_root=self.tmp,
            fetcher_factory=lambda: fake,
        )
        self.assertEqual(fake.last_args, (WALLET, None))


class ErrorTranslationTests(_Tmp):
    def test_invalid_address_raises_before_fetcher_call(self) -> None:
        fake = _FakeFetcher()
        with self.assertRaises(InvalidSolanaAddressError):
            run_fetch(
                "not-a-wallet",
                helius_api_key="k",
                max_pages=1,
                cache_root=self.tmp,
                fetcher_factory=lambda: fake,
            )
        self.assertEqual(fake.calls, 0)

    def test_auth_error_translates_to_dashboard_error(self) -> None:
        fake = _FakeFetcher(raises=HeliusAuthenticationError("nope"))
        with self.assertRaises(DashboardError) as ctx:
            run_fetch(
                WALLET,
                helius_api_key="k",
                max_pages=1,
                cache_root=self.tmp,
                fetcher_factory=lambda: fake,
            )
        self.assertEqual(ctx.exception.category, "auth")
        self.assertEqual(ctx.exception.http_status, 502)
        self.assertFalse(ctx.exception.retryable)

    def test_rate_limit_translates_to_503(self) -> None:
        fake = _FakeFetcher(raises=HeliusRateLimitError("slow down"))
        with self.assertRaises(DashboardError) as ctx:
            run_fetch(
                WALLET,
                helius_api_key="k",
                max_pages=1,
                cache_root=self.tmp,
                fetcher_factory=lambda: fake,
            )
        self.assertEqual(ctx.exception.category, "rate_limit")
        self.assertEqual(ctx.exception.http_status, 503)
        self.assertTrue(ctx.exception.retryable)


class LockfileTests(_Tmp):
    def _hold_lock(self) -> Path:
        wallet_dir = self.tmp / WALLET
        wallet_dir.mkdir(parents=True, exist_ok=True)
        lock = wallet_dir / ".refresh.lock"
        lock.write_text("held")
        return lock

    def test_concurrent_refresh_raises_refresh_locked(self) -> None:
        self._hold_lock()
        fake = _FakeFetcher()
        with self.assertRaises(RefreshLocked):
            run_fetch(
                WALLET,
                helius_api_key="k",
                max_pages=1,
                cache_root=self.tmp,
                fetcher_factory=lambda: fake,
            )
        self.assertEqual(fake.calls, 0)

    def test_stale_lock_is_replaced(self) -> None:
        lock = self._hold_lock()
        old = time.time() - 3600
        import os

        os.utime(lock, (old, old))
        fake = _FakeFetcher()
        run_fetch(
            WALLET,
            helius_api_key="k",
            max_pages=1,
            cache_root=self.tmp,
            fetcher_factory=lambda: fake,
            lock_ttl_seconds=1800,
        )
        self.assertEqual(fake.calls, 1)
        self.assertFalse(lock.exists())

    def test_lock_released_on_failure(self) -> None:
        fake = _FakeFetcher(raises=HeliusAuthenticationError("nope"))
        with self.assertRaises(DashboardError):
            run_fetch(
                WALLET,
                helius_api_key="k",
                max_pages=1,
                cache_root=self.tmp,
                fetcher_factory=lambda: fake,
            )
        lock = self.tmp / WALLET / ".refresh.lock"
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
