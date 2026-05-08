"""HTTP routes for the dashboard."""

from __future__ import annotations

import io
import json
import re
from decimal import Decimal
from pathlib import Path

import pandas as pd
from flask import (
    Flask,
    Response,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)

from ...exceptions import InvalidSolanaAddressError
from ...report import transaction_export_frame
from .. import cache as cache_mod
from ..fetcher import DashboardError, RefreshLocked, run_fetch
from ..filters import FilterSpec
from ..views import transaction_detail, wallet_page

ADDR_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
SIG_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{80,90}$")


def register_routes(app: Flask) -> None:
    @app.get("/")
    def landing() -> Response:
        wallets = cache_mod.list_wallets(cache_root=_cache_root())
        return render_template("landing.html.j2", wallets=wallets, error=None, address_input="")

    @app.post("/")
    def landing_submit() -> Response:
        address = (request.form.get("address") or "").strip()
        if not ADDR_RE.match(address):
            wallets = cache_mod.list_wallets(cache_root=_cache_root())
            return (
                render_template(
                    "landing.html.j2",
                    wallets=wallets,
                    error="That doesn't look like a Solana wallet address.",
                    address_input=address,
                ),
                400,
            )
        try:
            cached = cache_mod.read(address, cache_root=_cache_root())
        except InvalidSolanaAddressError:
            wallets = cache_mod.list_wallets(cache_root=_cache_root())
            return (
                render_template(
                    "landing.html.j2",
                    wallets=wallets,
                    error="That doesn't look like a Solana wallet address.",
                    address_input=address,
                ),
                400,
            )
        if cached is None:
            try:
                _do_fetch(address)
            except DashboardError as exc:
                return _render_error(exc), exc.http_status
        return redirect(url_for("wallet_page_route", address=address), code=303)

    @app.get("/wallet/<address>")
    def wallet_page_route(address: str) -> Response:
        if not ADDR_RE.match(address):
            abort(404)
        try:
            cached = cache_mod.read(address, cache_root=_cache_root())
        except InvalidSolanaAddressError:
            abort(404)
        spec = FilterSpec.from_querystring(request.args)
        if cached is None:
            empty = pd.DataFrame()
            ctx = wallet_page(empty, spec=spec, meta=None, address=address)
            return render_template("wallet.html.j2", **ctx, no_cache=True)
        df, meta = cached
        ctx = wallet_page(df, spec=spec, meta=meta, address=address)
        return render_template("wallet.html.j2", **ctx, no_cache=False)

    @app.post("/wallet/<address>/refresh")
    def refresh_route(address: str) -> Response:
        if not ADDR_RE.match(address):
            abort(404)
        try:
            _do_fetch(address)
        except RefreshLocked as exc:
            return _render_error(exc), exc.http_status
        except DashboardError as exc:
            return _render_error(exc), exc.http_status
        target = request.referrer or url_for("wallet_page_route", address=address)
        return redirect(target, code=303)

    @app.post("/wallet/<address>/forget")
    def forget_route(address: str) -> Response:
        if not ADDR_RE.match(address):
            abort(404)
        try:
            cache_mod.forget(address, cache_root=_cache_root())
        except InvalidSolanaAddressError:
            abort(404)
        return redirect(url_for("landing"), code=303)

    @app.get("/wallet/<address>/tx/<sig>")
    def tx_detail_route(address: str, sig: str) -> Response:
        if not ADDR_RE.match(address) or not SIG_RE.match(sig):
            abort(404)
        try:
            cached = cache_mod.read(address, cache_root=_cache_root())
        except InvalidSolanaAddressError:
            abort(404)
        if cached is None:
            abort(404)
        df, _meta = cached
        try:
            ctx = transaction_detail(df, sig, address=address)
        except KeyError:
            abort(404)
        return render_template("transaction.html.j2", **ctx)

    @app.get("/wallet/<address>/export.csv")
    def export_csv_route(address: str) -> Response:
        df = _filtered_or_404(address)
        export = transaction_export_frame(df)
        buf = io.StringIO()
        export.to_csv(buf, index=False)
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{address[:8]}_transactions.csv"',
            },
        )

    @app.get("/wallet/<address>/export.json")
    def export_json_route(address: str) -> Response:
        df = _filtered_or_404(address)
        export = transaction_export_frame(df)
        records = json.loads(export.to_json(orient="records", default_handler=str))
        body = json.dumps(
            {"transactions": records, "meta": {"address": address, "count": len(records)}},
            indent=2,
            default=lambda v: str(v) if isinstance(v, Decimal) else v,
        )
        return Response(
            body,
            mimetype="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{address[:8]}_transactions.json"',
            },
        )


def _cache_root() -> Path:
    return current_app.config["AI_ACCOUNTANT_CACHE_ROOT"]


def _max_pages() -> int | None:
    return current_app.config["AI_ACCOUNTANT_MAX_PAGES"]


def _api_key() -> str:
    return current_app.config["AI_ACCOUNTANT_HELIUS_API_KEY"]


def _factory():
    return current_app.config.get("AI_ACCOUNTANT_FETCHER_FACTORY")


def _do_fetch(address: str) -> None:
    run_fetch(
        address,
        helius_api_key=_api_key(),
        max_pages=_max_pages(),
        cache_root=_cache_root(),
        fetcher_factory=_factory(),
    )


def _filtered_or_404(address: str) -> pd.DataFrame:
    if not ADDR_RE.match(address):
        abort(404)
    try:
        cached = cache_mod.read(address, cache_root=_cache_root())
    except InvalidSolanaAddressError:
        abort(404)
    if cached is None:
        abort(404)
    df, _meta = cached
    spec = FilterSpec.from_querystring(request.args)
    return spec.apply(df) if not df.empty else df


def _render_error(exc: DashboardError) -> str:
    return render_template(
        "error.html.j2",
        error_category=exc.category,
        error_message=exc.message,
        retryable=exc.retryable,
    )


__all__ = ["register_routes"]
