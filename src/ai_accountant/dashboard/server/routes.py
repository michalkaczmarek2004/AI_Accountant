"""HTTP routes for the dashboard."""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

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
from ...tax_assistant import (
    TAX_DISCLAIMER,
    tax_export_frame,
    tax_summary,
    tax_yearly_export_frame,
    yearly_summary,
)
from .. import cache as cache_mod
from ..demo import TEST_DATASET_LABEL, TEST_WALLET_ADDRESS, build_test_cache_payloads
from ..fetcher import DashboardError, RefreshLocked, run_fetch
from ..filters import FilterSpec
from ..pdf_report import build_wallet_pdf_report
from ..tax_files import (
    DEFAULT_ENTITY_TYPE,
    DEFAULT_TAX_COUNTRY,
    MATCH_CONFIRMED,
    MATCH_REJECTED,
    OWNERSHIP_OWNED,
    TAX_CATEGORY_UNKNOWN,
    TAX_REVIEW_EXCLUDED,
    TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
    TAX_SCOPE_EXCLUDED,
    TAX_SCOPE_INCLUDED,
    TEST_TAX_FILE_ID,
    TaxFileStore,
    cost_basis_rows,
    create_test_tax_file,
    matchInternalTransfers,
    tax_estimate_plan,
    tax_file_cpa_ready_export_frame,
    tax_file_export_frame,
    tax_file_yearly_summary,
    tax_file_dashboard_context,
    tax_files_overview,
    tax_loss_harvesting_advice,
    unified_transaction_frame,
)
from ..views import tax_page, transaction_detail, wallet_page

ADDR_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
SIG_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{80,90}$")


def _landing_wallet_rows(wallets: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    demo_wallet_index = 0
    for wallet in wallets:
        address = str(getattr(wallet, "address", ""))
        dataset_label = str(getattr(wallet, "dataset_label", "") or "")
        public_dataset_label = _public_dataset_label(dataset_label)
        display_address = f"{address[:8]}...{address[-6:]}" if len(address) > 14 else address
        if public_dataset_label == TEST_DATASET_LABEL:
            demo_wallet_index += 1
            display_address = f"Solana Wallet {demo_wallet_index}"
        rows.append(
            {
                "address": address,
                "display_address": display_address,
                "dataset_label": public_dataset_label,
                "row_count": int(getattr(wallet, "row_count", 0) or 0),
                "earliest_tx": str(getattr(wallet, "earliest_tx", "") or ""),
                "latest_tx": str(getattr(wallet, "latest_tx", "") or ""),
                "fetched_at": str(getattr(wallet, "fetched_at", "") or ""),
            }
        )
    return rows


def _public_dataset_label(value: str) -> str:
    return value.replace("Demo dataset: ", "").replace("Synthetic demo data", "Sample wallet activity")


def register_routes(app: Flask) -> None:
    @app.get("/")
    def landing() -> Response:
        return render_template(
            "landing.html.j2",
            error=None,
            address_input="",
            notice=_notice_arg(),
        )

    @app.get("/wallets")
    def wallets_route() -> Response:
        wallets = _landing_wallet_rows(cache_mod.list_wallets(cache_root=_cache_root()))
        return render_template(
            "wallets.html.j2",
            wallets=wallets,
            notice=_notice_arg(),
        )

    @app.post("/")
    def landing_submit() -> Response:
        address = (request.form.get("address") or "").strip()
        if not ADDR_RE.match(address):
            return (
                render_template(
                    "landing.html.j2",
                    error="That doesn't look like a Solana wallet address.",
                    address_input=address,
                    notice=_notice_arg(),
                ),
                400,
            )
        try:
            cached = cache_mod.read(address, cache_root=_cache_root())
        except InvalidSolanaAddressError:
            return (
                render_template(
                    "landing.html.j2",
                    error="That doesn't look like a Solana wallet address.",
                    address_input=address,
                    notice=_notice_arg(),
                ),
                400,
            )
        if cached is None:
            try:
                _do_fetch(address)
            except DashboardError as exc:
                return _render_error(exc), exc.http_status
        return redirect(url_for("wallet_page_route", address=address), code=303)

    def _seed_presentation_demo() -> None:
        payloads = build_test_cache_payloads()
        for address, df, meta in payloads:
            cache_mod.write(address, df, meta, cache_root=_cache_root())
        create_test_tax_file(
            _cache_root(),
            primary_address=payloads[0][0],
            secondary_address=payloads[1][0],
        )

    @app.post("/demo")
    def demo_route() -> Response:
        if not _presentation_mode():
            abort(404)
        _seed_presentation_demo()
        return redirect(url_for("tax_file_detail_route", tax_file_id=TEST_TAX_FILE_ID), code=303)

    @app.post("/demo/reset")
    def reset_demo_route() -> Response:
        if not _presentation_mode():
            abort(404)
        _seed_presentation_demo()
        return redirect(url_for("tax_file_detail_route", tax_file_id=TEST_TAX_FILE_ID, notice="demo-reset"), code=303)

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
            return render_template("wallet.html.j2", **ctx, no_cache=True, notice=_notice_arg())
        df, meta = cached
        ctx = wallet_page(df, spec=spec, meta=meta, address=address)
        return render_template("wallet.html.j2", **ctx, no_cache=False, notice=_notice_arg())

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

    @app.get("/wallet/<address>/report.pdf")
    def export_pdf_route(address: str) -> Response:
        df, meta = _unfiltered_with_meta_or_404(address)
        spec = FilterSpec.from_querystring(request.args)
        filtered = spec.apply(df) if not df.empty else df
        body = build_wallet_pdf_report(
            filtered,
            address,
            meta=meta,
            tax_country=_tax_country_arg(),
        )
        return Response(
            body,
            mimetype="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{address[:8]}_ai_accountant_report.pdf"',
            },
        )

    @app.get("/wallet/<address>/tax")
    def tax_page_route(address: str) -> Response:
        return _render_tax_page(address)

    @app.get("/wallet/<address>/tax-country")
    def tax_country_page_route(address: str) -> Response:
        return _render_tax_page(address)

    def _render_tax_page(address: str) -> Response:
        if not ADDR_RE.match(address):
            abort(404)
        try:
            cached = cache_mod.read(address, cache_root=_cache_root())
        except InvalidSolanaAddressError:
            abort(404)
        if cached is None:
            abort(404)
        df, meta = cached
        selected_tax_country = "US" if address == TEST_WALLET_ADDRESS else _tax_country_arg()
        ctx = tax_page(df, address=address, meta=meta, tax_country=selected_tax_country)
        if address == TEST_WALLET_ADDRESS:
            ctx["tax_country_options"] = [{"code": "US", "label": "United States"}]
            ctx["demo_us_only"] = True
        return render_template("tax.html.j2", **ctx)

    @app.get("/tax-files")
    def tax_files_route() -> Response:
        show_archived = request.args.get("show_archived") == "1"
        return render_template(
            "tax_files.html.j2",
            **tax_files_overview(_cache_root(), include_archived=show_archived),
            notice=_notice_arg(),
        )

    @app.post("/tax-files")
    def create_tax_file_route() -> Response:
        store = TaxFileStore(_cache_root())
        tax_file = store.create_tax_file(
            name=request.form.get("name") or "Untitled Tax File",
            tax_year=request.form.get("tax_year") or datetime.now(timezone.utc).year,
            tax_country=request.form.get("tax_country") or DEFAULT_TAX_COUNTRY,
            entity_type=request.form.get("entity_type") or DEFAULT_ENTITY_TYPE,
        )
        return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file.id), code=303)

    @app.post("/tax-files/<tax_file_id>/accounts")
    def add_account_route(tax_file_id: str) -> Response:
        address = request.form.get("address") or ""
        if not tax_file_id or not ADDR_RE.match(address):
            return redirect(
                url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="link-failed"),
                code=303,
            )
        store = TaxFileStore(_cache_root())
        try:
            account, created = store.add_account(
                tax_file_id=tax_file_id,
                address=address,
                label=request.form.get("label") or f"Wallet {_short_address(address)}",
                ownership_status=request.form.get("ownership_status") or OWNERSHIP_OWNED,
            )
        except (KeyError, InvalidSolanaAddressError):
            return redirect(
                url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="link-failed"),
                code=303,
            )
        matchInternalTransfers(tax_file_id, cache_root=_cache_root(), store=store)
        notice = "account-linked" if created else "account-already-linked"
        return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice=notice), code=303)

    @app.get("/tax-files/<tax_file_id>")
    def tax_file_detail_route(tax_file_id: str) -> Response:
        try:
            ctx = tax_file_dashboard_context(tax_file_id, _cache_root())
        except KeyError:
            abort(404)
        return render_template("tax_file.html.j2", **ctx, notice=_notice_arg())

    @app.post("/tax-files/<tax_file_id>/accounts/<account_id>")
    def update_account_route(tax_file_id: str, account_id: str) -> Response:
        store = TaxFileStore(_cache_root())
        try:
            store.update_account(
                account_id,
                label=request.form.get("label"),
                ownership_status=request.form.get("ownership_status"),
            )
        except KeyError:
            abort(404)
        matchInternalTransfers(tax_file_id, cache_root=_cache_root(), store=store)
        return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="account-updated"), code=303)

    @app.post("/tax-files/<tax_file_id>/accounts/<account_id>/remove")
    def remove_account_route(tax_file_id: str, account_id: str) -> Response:
        note = (request.form.get("note") or "").strip()
        if not note:
            return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="note-required"), code=303)
        store = TaxFileStore(_cache_root())
        try:
            store.remove_account(account_id, note=note)
        except KeyError:
            abort(404)
        matchInternalTransfers(tax_file_id, cache_root=_cache_root(), store=store)
        return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="account-removed"), code=303)

    @app.post("/tax-files/<tax_file_id>/matches/<match_id>/confirm")
    def confirm_transfer_match_route(tax_file_id: str, match_id: str) -> Response:
        return _update_match_status(tax_file_id, match_id, MATCH_CONFIRMED)

    @app.post("/tax-files/<tax_file_id>/matches/<match_id>/reject")
    def reject_transfer_match_route(tax_file_id: str, match_id: str) -> Response:
        return _update_match_status(tax_file_id, match_id, MATCH_REJECTED)

    def _update_match_status(tax_file_id: str, match_id: str, status: str) -> Response:
        store = TaxFileStore(_cache_root())
        try:
            store.update_transfer_match_status(match_id, status, note=request.form.get("note") or None)
        except KeyError:
            abort(404)
        return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="match-updated"), code=303)

    @app.post("/tax-files/<tax_file_id>/review/<review_item_id>/answer")
    def answer_review_item_route(tax_file_id: str, review_item_id: str) -> Response:
        store = TaxFileStore(_cache_root())
        try:
            store.save_client_answer(
                tax_file_id=tax_file_id,
                review_item_id=review_item_id,
                account_id=request.form.get("account_id") or "",
                transaction_id=request.form.get("transaction_id") or "",
                review_reason=request.form.get("review_reason") or "",
                direction=request.form.get("direction") or "",
                client_question=request.form.get("client_question") or "",
                client_answer=request.form.get("client_answer") or "unknown",
            )
        except KeyError:
            abort(404)
        return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="client-answer-saved"), code=303)

    @app.post("/tax-files/<tax_file_id>/review/<review_item_id>/answer/clear")
    def clear_review_answer_route(tax_file_id: str, review_item_id: str) -> Response:
        store = TaxFileStore(_cache_root())
        removed = store.clear_client_answer(tax_file_id=tax_file_id, review_item_id=review_item_id)
        notice = "client-answer-cleared" if removed is not None else "review-item-not-found"
        return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice=notice), code=303)

    @app.post("/tax-files/<tax_file_id>/review/<review_item_id>/override")
    def override_review_item_route(tax_file_id: str, review_item_id: str) -> Response:
        return _save_review_override(
            tax_file_id,
            review_item_id,
            notice="override-saved",
            action_type="accountant_override_saved",
            tax_scope=request.form.get("tax_scope") or TAX_SCOPE_INCLUDED,
        )

    @app.post("/tax-files/<tax_file_id>/review/<review_item_id>/exclude")
    def exclude_review_item_route(tax_file_id: str, review_item_id: str) -> Response:
        return _save_review_override(
            tax_file_id,
            review_item_id,
            notice="transaction-excluded",
            action_type="transaction_excluded",
            tax_scope=TAX_SCOPE_EXCLUDED,
            status_override=TAX_REVIEW_EXCLUDED,
        )

    @app.post("/tax-files/<tax_file_id>/review/<review_item_id>/restore")
    def restore_review_item_route(tax_file_id: str, review_item_id: str) -> Response:
        return _save_review_override(
            tax_file_id,
            review_item_id,
            notice="transaction-restored",
            action_type="transaction_restored",
            tax_scope=TAX_SCOPE_INCLUDED,
            status_override=TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
        )

    @app.post("/tax-files/<tax_file_id>/review/<review_item_id>/reopen")
    def reopen_review_item_route(tax_file_id: str, review_item_id: str) -> Response:
        return _save_review_override(
            tax_file_id,
            review_item_id,
            notice="review-item-reopened",
            action_type="review_item_reopened",
            tax_scope=TAX_SCOPE_INCLUDED,
            status_override=request.form.get("tax_review_status") or TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
        )

    @app.post("/tax-files/<tax_file_id>/review/<review_item_id>/reset")
    def reset_review_item_route(tax_file_id: str, review_item_id: str) -> Response:
        note = (request.form.get("accountant_note") or request.form.get("note") or "").strip()
        if not note:
            return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="note-required"), code=303)
        store = TaxFileStore(_cache_root())
        removed = store.reset_transaction_override(tax_file_id=tax_file_id, review_item_id=review_item_id, note=note)
        notice = "override-reset" if removed is not None else "review-item-not-found"
        return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice=notice), code=303)

    @app.post("/tax-files/<tax_file_id>/archive")
    def archive_tax_file_route(tax_file_id: str) -> Response:
        note = (request.form.get("note") or "").strip()
        if not note:
            return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="note-required"), code=303)
        store = TaxFileStore(_cache_root())
        try:
            store.archive_tax_file(tax_file_id=tax_file_id, note=note)
        except KeyError:
            abort(404)
        return redirect(url_for("tax_files_route", notice="tax-file-archived"), code=303)

    def _save_review_override(
        tax_file_id: str,
        review_item_id: str,
        *,
        notice: str,
        action_type: str,
        tax_scope: str,
        status_override: str | None = None,
    ) -> Response:
        note = (request.form.get("accountant_note") or request.form.get("note") or "").strip()
        if not note:
            return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="note-required"), code=303)
        store = TaxFileStore(_cache_root())
        try:
            store.save_transaction_override(
                tax_file_id=tax_file_id,
                review_item_id=review_item_id,
                account_id=request.form.get("account_id") or "",
                transaction_id=request.form.get("transaction_id") or "",
                review_reason=request.form.get("review_reason") or "",
                tax_category=request.form.get("tax_category") or TAX_CATEGORY_UNKNOWN,
                original_tax_category=request.form.get("original_tax_category") or None,
                tax_review_status=status_override or request.form.get("tax_review_status") or TAX_REVIEW_NEEDS_ACCOUNTANT_REVIEW,
                accountant_note=note,
                tax_scope=tax_scope,
                action_type=action_type,
            )
        except KeyError:
            abort(404)
        except ValueError:
            return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice="note-required"), code=303)
        return redirect(url_for("tax_file_detail_route", tax_file_id=tax_file_id, notice=notice), code=303)

    @app.get("/tax-files/<tax_file_id>/tax")
    def tax_file_tax_route(tax_file_id: str) -> Response:
        store = TaxFileStore(_cache_root())
        tax_file = store.get_tax_file(tax_file_id)
        if tax_file is None:
            abort(404)
        matches = matchInternalTransfers(tax_file_id, cache_root=_cache_root(), store=store)
        df = unified_transaction_frame(
            tax_file_id,
            cache_root=_cache_root(),
            store=store,
            include_non_owned=False,
            matches=matches,
        )
        meta = {
            "address": tax_file.id,
            "row_count": len(df),
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "earliest_tx": _frame_date(df, earliest=True),
            "latest_tx": _frame_date(df, earliest=False),
            "dataset_label": "Unified Tax File",
        }
        selected_tax_country = "United States" if tax_file.id == TEST_TAX_FILE_ID else (_tax_country_arg() or tax_file.tax_country)
        ctx = tax_page(df, address=tax_file.id, meta=meta, tax_country=selected_tax_country)
        loss_tax_file = {**tax_file.to_dict(), "tax_country": ctx["tax_country"]}
        loss = tax_loss_harvesting_advice(loss_tax_file, df)
        tax_plan = tax_estimate_plan(tax_file, df, tax_loss_harvesting=loss)
        ctx.update(
            {
                "tax_file": tax_file.to_dict(),
                "unified_tax_assistant": True,
                "tax_loss_harvesting": loss,
                "tax_payment_plan": tax_plan,
                "demo_us_only": bool(tax_plan.get("demo_us_only")),
                "yearly": tax_file_yearly_summary(tax_file, df, tax_payment_plan=tax_plan),
                "yearly_tax_file_summary": True,
            }
        )
        if tax_plan.get("demo_us_only"):
            ctx["tax_country_options"] = [{"code": "US", "label": "United States"}]
        return render_template("tax.html.j2", **ctx)

    @app.get("/tax-files/<tax_file_id>/tax-export.csv")
    def tax_file_export_csv_route(tax_file_id: str) -> Response:
        store = TaxFileStore(_cache_root())
        tax_file = store.get_tax_file(tax_file_id)
        if tax_file is None:
            abort(404)
        df = _tax_file_frame_or_404(tax_file_id, store=store)
        export = tax_file_cpa_ready_export_frame(tax_file, df)
        return _csv_download_response(
            export,
            filename=f"{tax_file.name.replace(' ', '_')}_CPA_ready.csv",
            excel_compatible=True,
        )

    @app.get("/tax-files/<tax_file_id>/tax-export.json")
    def tax_file_export_json_route(tax_file_id: str) -> Response:
        store = TaxFileStore(_cache_root())
        tax_file = store.get_tax_file(tax_file_id)
        if tax_file is None:
            abort(404)
        df = _tax_file_frame_or_404(tax_file_id, store=store)
        export = tax_file_export_frame(tax_file, df)
        records = json.loads(export.to_json(orient="records", default_handler=str))
        raw_summary = tax_summary(df, tax_file.id)
        body = json.dumps(
            {
                "meta": {
                    "tax_file": tax_file.to_dict(),
                    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "disclaimer": TAX_DISCLAIMER,
                },
                "summary": {k: str(v) for k, v in raw_summary.items()},
                "yearly": yearly_summary(df),
                "tax_loss_harvesting": tax_loss_harvesting_advice(tax_file, df),
                "cost_basis": cost_basis_rows(tax_file, df),
                "transactions": records,
            },
            indent=2,
            default=lambda v: str(v) if isinstance(v, Decimal) else v,
        )
        return Response(
            body,
            mimetype="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{tax_file_id[:8]}_tax_file.json"',
            },
        )

    @app.get("/wallet/<address>/tax-export.csv")
    def tax_export_csv_route(address: str) -> Response:
        df = _unfiltered_or_404(address)
        export = tax_export_frame(df)
        buf = io.StringIO()
        export.to_csv(buf, index=False)
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{address[:8]}_tax.csv"',
            },
        )

    @app.get("/wallet/<address>/tax-export.json")
    def tax_export_json_route(address: str) -> Response:
        df = _unfiltered_or_404(address)
        export = tax_export_frame(df)
        records = json.loads(export.to_json(orient="records", default_handler=str))
        for rec in records:
            rec["is_potentially_taxable"] = rec.get("is_potentially_taxable") == "yes"
            if "notes" in rec:
                rec["short_explanation"] = rec.pop("notes")
        raw_summary = tax_summary(df, address)
        body = json.dumps(
            {
                "meta": {
                    "address": address,
                    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "disclaimer": TAX_DISCLAIMER,
                },
                "summary": {k: str(v) for k, v in raw_summary.items()},
                "yearly": yearly_summary(df),
                "transactions": records,
            },
            indent=2,
            default=lambda v: str(v) if isinstance(v, Decimal) else v,
        )
        return Response(
            body,
            mimetype="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{address[:8]}_tax.json"',
            },
        )

    @app.get("/wallet/<address>/tax-summary.csv")
    def tax_summary_csv_route(address: str) -> Response:
        df = _unfiltered_or_404(address)
        export = tax_yearly_export_frame(df)
        buf = io.StringIO()
        export.to_csv(buf, index=False)
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{address[:8]}_tax_yearly.csv"',
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


def _presentation_mode() -> bool:
    return bool(current_app.config.get("AI_ACCOUNTANT_PRESENTATION_MODE", True))


def _tax_country_arg() -> str | None:
    return request.args.get("tax_country") or request.args.get("country")


def _notice_arg() -> str:
    key = request.args.get("notice") or ""
    messages = {
        "account-linked": "Wallet linked to the tax file.",
        "account-already-linked": "This wallet is already linked to that tax file. Existing account was used.",
        "account-updated": "Account ownership and label updated.",
        "account-removed": "Account removed from this tax file. Wallet cache was kept.",
        "link-failed": "Could not link that wallet to a tax file.",
        "match-updated": "Internal transfer match status updated.",
        "client-answer-saved": "Your confirmation was added to the audit trail and will be included in the CPA-ready package.",
        "client-answer-cleared": "Client answer cleared and item reopened.",
        "override-saved": "Accountant override saved.",
        "override-reset": "Accountant override reset.",
        "transaction-excluded": "Transaction excluded from this tax file.",
        "transaction-restored": "Transaction restored to this tax file.",
        "review-item-reopened": "Review item reopened.",
        "review-item-not-found": "That review item was not found.",
        "tax-file-archived": "Tax file archived.",
        "demo-reset": "Tax review reset to the initial review state.",
        "note-required": "A note or reason is required for that action.",
    }
    return messages.get(key, "")


def _csv_download_response(
    export: pd.DataFrame,
    *,
    filename: str,
    excel_compatible: bool = False,
) -> Response:
    buf = io.StringIO()
    export.to_csv(buf, index=False, lineterminator="\r\n")
    body = buf.getvalue()
    if excel_compatible:
        body = "\ufeffsep=,\r\n" + body
    return Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _tax_file_frame_or_404(
    tax_file_id: str,
    *,
    store: TaxFileStore | None = None,
) -> pd.DataFrame:
    store = store or TaxFileStore(_cache_root())
    tax_file = store.get_tax_file(tax_file_id)
    if tax_file is None:
        abort(404)
    matches = matchInternalTransfers(tax_file_id, cache_root=_cache_root(), store=store)
    return unified_transaction_frame(
        tax_file_id,
        cache_root=_cache_root(),
        store=store,
        include_non_owned=False,
        matches=matches,
    )


def _frame_date(df: pd.DataFrame, *, earliest: bool) -> str:
    if df.empty or "timestamp" not in df.columns:
        return ""
    values = sorted(str(value)[:10] for value in df["timestamp"] if value)
    if not values:
        return ""
    return values[0] if earliest else values[-1]


def _short_address(address: str) -> str:
    if len(address) <= 14:
        return address
    return f"{address[:6]}...{address[-4:]}"


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


def _unfiltered_or_404(address: str) -> pd.DataFrame:
    """Read the full cached DataFrame, abort 404 if missing."""
    df, _meta = _unfiltered_with_meta_or_404(address)
    return df


def _unfiltered_with_meta_or_404(address: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read the full cached DataFrame and metadata, abort 404 if missing."""
    if not ADDR_RE.match(address):
        abort(404)
    try:
        cached = cache_mod.read(address, cache_root=_cache_root())
    except InvalidSolanaAddressError:
        abort(404)
    if cached is None:
        abort(404)
    return cached


def _render_error(exc: DashboardError) -> str:
    return render_template(
        "error.html.j2",
        error_category=exc.category,
        error_message=exc.message,
        retryable=exc.retryable,
    )


__all__ = ["register_routes"]
