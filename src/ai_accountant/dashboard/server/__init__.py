"""Flask app factory for the local wallet dashboard."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from flask import Flask

from .routes import register_routes


def create_app(
    *,
    helius_api_key: str,
    max_pages: int | None,
    cache_root: Path,
    fetcher_factory: Callable[[], Any] | None = None,
) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent.parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )
    app.config.update(
        AI_ACCOUNTANT_HELIUS_API_KEY=helius_api_key,
        AI_ACCOUNTANT_MAX_PAGES=max_pages,
        AI_ACCOUNTANT_CACHE_ROOT=Path(cache_root),
        AI_ACCOUNTANT_FETCHER_FACTORY=fetcher_factory,
    )
    register_routes(app)
    return app


__all__ = ["create_app"]
