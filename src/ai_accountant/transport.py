"""HTTP transport for the Helius client.

Defines the structural `SessionProtocol` test doubles can implement, the
`_UrllibSession` default, case-insensitive header normalization, and
RFC-7231-compliant `Retry-After` parsing.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class TransportError(Exception):
    """Raised by the internal HTTP transport when a request cannot be completed."""


class _CaseInsensitiveHeaders(Mapping[str, str]):
    """Case-insensitive HTTP header mapping that preserves original-case keys on iteration."""

    def __init__(self, items: Iterable[tuple[str, str]]) -> None:
        self._store: dict[str, tuple[str, str]] = {}
        for key, value in items:
            self._store[key.lower()] = (key, value)

    def __getitem__(self, key: str) -> str:
        return self._store[key.lower()][1]

    def __iter__(self) -> Iterator[str]:
        return (original for original, _ in self._store.values())

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._store

    def get(self, key: str, default: Any = None) -> Any:
        entry = self._store.get(key.lower())
        return entry[1] if entry is not None else default


@runtime_checkable
class ResponseProtocol(Protocol):
    status_code: int
    text: str
    headers: Mapping[str, str]

    def json(self) -> Any: ...


@runtime_checkable
class SessionProtocol(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> ResponseProtocol: ...

    def close(self) -> None: ...


class _SimpleResponse:
    def __init__(
        self,
        status_code: int,
        body: str,
        headers: Mapping[str, str] | Iterable[tuple[str, str]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = body
        if headers is None:
            self.headers: Mapping[str, str] = _CaseInsensitiveHeaders([])
        elif isinstance(headers, _CaseInsensitiveHeaders):
            self.headers = headers
        elif isinstance(headers, Mapping):
            self.headers = _CaseInsensitiveHeaders(headers.items())
        else:
            self.headers = _CaseInsensitiveHeaders(headers)

    def json(self) -> Any:
        return json.loads(self.text)


class _UrllibSession:
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> _SimpleResponse:
        query = urlencode(params or {}, doseq=True)
        full_url = f"{url}?{query}" if query else url
        request = Request(full_url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                return _SimpleResponse(
                    status_code=response.getcode(),
                    body=body,
                    headers=dict(response.headers.items()),
                )
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            headers = dict(exc.headers.items()) if exc.headers else {}
            return _SimpleResponse(status_code=exc.code, body=body, headers=headers)
        except URLError as exc:
            raise TransportError(str(exc)) from exc

    def close(self) -> None:
        return None


def _parse_retry_after(
    value: str | None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> float | None:
    """Parse `Retry-After` per RFC 7231: numeric seconds OR HTTP-date.

    Returns the wait in seconds (clamped at 0), or `None` if the value cannot be
    interpreted. Negative numeric values are treated as `None` (caller falls back
    to its own backoff).
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None

    try:
        n = float(stripped)
    except ValueError:
        pass
    else:
        return n if n >= 0 else None

    try:
        target = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    delta = (target - now()).total_seconds()
    return max(delta, 0.0)
