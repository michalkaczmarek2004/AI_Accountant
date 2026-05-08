"""Filesystem cache for fetched wallet DataFrames."""

from __future__ import annotations

import json
import os
import pickle
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..addresses import validate_address

SCHEMA_VERSION = 2
_ADDRESS_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


@dataclass(frozen=True)
class CachedWallet:
    address: str
    fetched_at: str
    row_count: int
    earliest_tx: str
    latest_tx: str
    pages_fetched: int
    max_pages_at_fetch: int


def _wallet_dir(address: str, *, cache_root: Path) -> Path:
    validated = validate_address(address)
    if not _ADDRESS_PATTERN.match(validated):
        from ..exceptions import InvalidSolanaAddressError

        raise InvalidSolanaAddressError(f"Address fails directory-name regex: {validated!r}")
    return Path(cache_root) / validated


def read(address: str, *, cache_root: Path) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    wallet_dir = _wallet_dir(address, cache_root=cache_root)
    pkl_path = wallet_dir / "transactions.pkl"
    meta_path = wallet_dir / "meta.json"
    if not pkl_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if meta.get("schema_version") != SCHEMA_VERSION:
        return None
    try:
        with pkl_path.open("rb") as fh:
            df = pickle.load(fh)
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ImportError):
        return None
    if not isinstance(df, pd.DataFrame):
        return None
    return df, meta


def write(
    address: str,
    df: pd.DataFrame,
    meta: dict[str, Any],
    *,
    cache_root: Path,
) -> None:
    wallet_dir = _wallet_dir(address, cache_root=cache_root)
    wallet_dir.mkdir(parents=True, exist_ok=True)

    pkl_path = wallet_dir / "transactions.pkl"
    meta_path = wallet_dir / "meta.json"
    pkl_tmp = pkl_path.with_suffix(".pkl.tmp")
    meta_tmp = meta_path.with_suffix(".json.tmp")

    payload = dict(meta)
    payload["schema_version"] = SCHEMA_VERSION

    with pkl_tmp.open("wb") as fh:
        pickle.dump(df, fh, protocol=5)
    meta_tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    os.replace(pkl_tmp, pkl_path)
    os.replace(meta_tmp, meta_path)


def forget(address: str, *, cache_root: Path) -> bool:
    wallet_dir = _wallet_dir(address, cache_root=cache_root)
    if not wallet_dir.exists():
        return False
    shutil.rmtree(wallet_dir)
    return True


def list_wallets(*, cache_root: Path) -> list[CachedWallet]:
    root = Path(cache_root)
    if not root.exists():
        return []
    out: list[CachedWallet] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if not _ADDRESS_PATTERN.match(child.name):
            continue
        meta_path = child / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("schema_version") != SCHEMA_VERSION:
            continue
        out.append(
            CachedWallet(
                address=str(meta.get("address") or child.name),
                fetched_at=str(meta.get("fetched_at") or ""),
                row_count=int(meta.get("row_count") or 0),
                earliest_tx=str(meta.get("earliest_tx") or ""),
                latest_tx=str(meta.get("latest_tx") or ""),
                pages_fetched=int(meta.get("pages_fetched") or 0),
                max_pages_at_fetch=int(meta.get("max_pages_at_fetch") or 0),
            )
        )
    out.sort(key=lambda w: w.fetched_at, reverse=True)
    return out


__all__ = ["SCHEMA_VERSION", "CachedWallet", "read", "write", "forget", "list_wallets"]
