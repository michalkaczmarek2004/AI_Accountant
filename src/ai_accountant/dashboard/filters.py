"""Querystring -> typed filter -> DataFrame mask."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any
from urllib.parse import urlencode

import pandas as pd

_VALID_STATUSES = ("succeeded", "failed")


@dataclass(frozen=True)
class FilterSpec:
    date_from: date | None = None
    date_to: date | None = None
    token: str | None = None
    type: str | None = None
    status: str | None = None
    source: str | None = None
    q: str | None = None
    page: int = 1

    @classmethod
    def from_querystring(cls, params: Mapping[str, Any]) -> FilterSpec:
        get = lambda k: _clean(params.get(k))  # noqa: E731

        date_from = _parse_date(get("from"))
        date_to = _parse_date(get("to"))
        status = get("status")
        if status not in _VALID_STATUSES:
            status = None
        page_raw = get("page") or "1"
        try:
            page = int(page_raw)
            if page < 1:
                page = 1
        except (TypeError, ValueError):
            page = 1
        return cls(
            date_from=date_from,
            date_to=date_to,
            token=get("token"),
            type=get("type"),
            status=status,
            source=get("source"),
            q=get("q"),
            page=page,
        )

    def is_active(self) -> bool:
        return any(
            v is not None
            for v in (
                self.date_from,
                self.date_to,
                self.token,
                self.type,
                self.status,
                self.source,
                self.q,
            )
        )

    def to_querystring(self) -> str:
        out: list[tuple[str, str]] = []
        if self.date_from:
            out.append(("from", self.date_from.isoformat()))
        if self.date_to:
            out.append(("to", self.date_to.isoformat()))
        if self.token:
            out.append(("token", self.token))
        if self.type:
            out.append(("type", self.type))
        if self.status:
            out.append(("status", self.status))
        if self.source:
            out.append(("source", self.source))
        if self.q:
            out.append(("q", self.q))
        if self.page > 1:
            out.append(("page", str(self.page)))
        return urlencode(out)

    def apply(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df.copy()

        mask = pd.Series([True] * len(df), index=df.index)

        if self.date_from is not None:
            cutoff = int(datetime.combine(self.date_from, time.min, timezone.utc).timestamp())
            mask &= df["timestamp_unix"].fillna(0).astype("int64") >= cutoff
        if self.date_to is not None:
            cutoff = int(datetime.combine(self.date_to, time.max, timezone.utc).timestamp())
            mask &= df["timestamp_unix"].fillna(0).astype("int64") <= cutoff
        if self.status is not None:
            mask &= df["status"] == self.status
        if self.type is not None:
            mask &= df["transaction_type"] == self.type
        if self.source is not None:
            mask &= df["source"] == self.source
        if self.token is not None:
            mask &= df["net_flow"].apply(lambda nf: _net_flow_has_key(nf, self.token))
        if self.q is not None:
            needle = self.q.casefold()
            mask &= df.apply(lambda row: _row_matches_q(row, needle), axis=1)
        return df[mask].reset_index(drop=True)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _net_flow_has_key(net_flow: Any, key: str) -> bool:
    if not isinstance(net_flow, Mapping):
        return False
    return key in net_flow


def _row_matches_q(row: pd.Series, needle: str) -> bool:
    for col in ("description", "source", "transaction_type"):
        value = row.get(col)
        if value is None:
            continue
        if needle in str(value).casefold():
            return True
    return False


__all__ = ["FilterSpec"]
