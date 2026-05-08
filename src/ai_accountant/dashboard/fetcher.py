"""Helius fetch orchestration with cache write and per-address lockfile."""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from .. import __version__ as _AI_ACCOUNTANT_VERSION
except ImportError:  # pragma: no cover — defensive
    _AI_ACCOUNTANT_VERSION = "0.0.0"

from ..addresses import validate_address
from ..client import SolanaDataFetcher
from ..exceptions import (
    HeliusAPIError,
    HeliusAuthenticationError,
    HeliusPermissionError,
    HeliusRateLimitError,
    InvalidSolanaAddressError,
    SolanaDataFetcherError,
)
from . import cache as cache_mod

LOCK_FILENAME = ".refresh.lock"


class DashboardError(Exception):
    def __init__(
        self,
        category: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int = 500,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.retryable = retryable
        self.http_status = http_status


class RefreshLocked(DashboardError):
    def __init__(self, message: str = "Refresh already in progress for this wallet.") -> None:
        super().__init__("locked", message, retryable=True, http_status=409)


def run_fetch(
    address: str,
    *,
    helius_api_key: str,
    max_pages: int | None,
    cache_root: Path,
    fetcher_factory: Callable[[], Any] | None = None,
    lock_ttl_seconds: int = 1800,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    validated = validate_address(address)
    cache_root = Path(cache_root)
    wallet_dir = cache_root / validated
    wallet_dir.mkdir(parents=True, exist_ok=True)
    lock_path = wallet_dir / LOCK_FILENAME
    requested_pages = None if (max_pages is None or max_pages == 0) else int(max_pages)

    _acquire_lock(lock_path, ttl_seconds=lock_ttl_seconds)
    try:
        fetcher = (fetcher_factory or _default_factory(helius_api_key))()
        try:
            with fetcher:
                df = fetcher.fetch_transactions_dataframe(validated, max_pages=requested_pages)
        except InvalidSolanaAddressError:
            raise
        except HeliusAuthenticationError as exc:
            raise DashboardError("auth", str(exc), retryable=False, http_status=502) from exc
        except HeliusPermissionError as exc:
            raise DashboardError("auth", str(exc), retryable=False, http_status=502) from exc
        except HeliusRateLimitError as exc:
            raise DashboardError("rate_limit", str(exc), retryable=True, http_status=503) from exc
        except HeliusAPIError as exc:
            raise DashboardError("transport", str(exc), retryable=True, http_status=502) from exc
        except SolanaDataFetcherError as exc:
            raise DashboardError("transport", str(exc), retryable=False, http_status=502) from exc

        meta = _build_meta(df, validated, pages_fetched=requested_pages, max_pages=requested_pages)
        try:
            cache_mod.write(validated, df, meta, cache_root=cache_root)
        except OSError as exc:
            raise DashboardError(
                "cache_io", f"Could not write cache: {exc}", retryable=False, http_status=500
            ) from exc
        return df, meta
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()


def _acquire_lock(lock_path: Path, *, ttl_seconds: int) -> None:
    if lock_path.exists():
        try:
            mtime = lock_path.stat().st_mtime
        except OSError:
            mtime = 0
        if (time.time() - mtime) > ttl_seconds:
            with contextlib.suppress(FileNotFoundError):
                lock_path.unlink()
        else:
            raise RefreshLocked()
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError as exc:
        raise RefreshLocked() from exc


def _default_factory(api_key: str) -> Callable[[], SolanaDataFetcher]:
    return lambda: SolanaDataFetcher(api_key=api_key)


def _build_meta(
    df: pd.DataFrame,
    address: str,
    *,
    pages_fetched: int | None,
    max_pages: int | None,
) -> dict[str, Any]:
    earliest = ""
    latest = ""
    if not df.empty and "timestamp_unix" in df.columns and df["timestamp_unix"].notna().any():
        ts_series = df["timestamp_unix"].dropna().astype("int64")
        earliest = datetime.fromtimestamp(int(ts_series.min()), timezone.utc).strftime("%Y-%m-%d")
        latest = datetime.fromtimestamp(int(ts_series.max()), timezone.utc).strftime("%Y-%m-%d")

    pages = pages_fetched if pages_fetched is not None else 0
    return {
        "schema_version": cache_mod.SCHEMA_VERSION,
        "address": address,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pages_fetched": pages,
        "max_pages_at_fetch": pages,
        "row_count": int(len(df)),
        "earliest_tx": earliest,
        "latest_tx": latest,
        "ai_accountant_version": _safe_version(),
    }


def _safe_version() -> str:
    return _AI_ACCOUNTANT_VERSION


__all__ = ["DashboardError", "RefreshLocked", "run_fetch", "LOCK_FILENAME"]
