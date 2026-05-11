from __future__ import annotations

import shutil
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ai_accountant.dashboard import cache as cache_mod
from ai_accountant.dashboard.demo import (
    DEMO_SECOND_WALLET_ADDRESS,
    DEMO_WALLET_ADDRESS,
    TEST_WALLET_ADDRESS,
    build_demo_cache_payloads,
    build_test_dataframe,
    build_test_cache_payloads,
)
from ai_accountant.dashboard.server import create_app
from ai_accountant.dashboard.tax_files import (
    MATCH_CONFIRMED,
    MATCH_REJECTED,
    OWNERSHIP_OWNED,
    OWNERSHIP_UNKNOWN,
    OWNERSHIP_WATCH_ONLY,
    TEST_TAX_FILE_ID,
    TaxFileStore,
    cost_basis_rows,
    create_demo_tax_file,
    create_test_tax_file,
    matchInternalTransfers,
    tax_file_export_frame,
    tax_file_dashboard_context,
    tax_loss_harvesting_advice,
    unified_transaction_frame,
    _format_money,
)
from ai_accountant.tax_assistant import tax_summary


class _TaxFileCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.id().replace(".", "_") + "_tmp")
        self.tmp.mkdir(exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        for address, df, meta in build_demo_cache_payloads():
            cache_mod.write(address, df, meta, cache_root=self.tmp)
        for address, df, meta in build_test_cache_payloads():
            cache_mod.write(address, df, meta, cache_root=self.tmp)
        self.store = TaxFileStore(self.tmp)


class TaxFileStoreTests(_TaxFileCase):
    def test_add_account_does_not_duplicate_address_in_same_tax_file(self) -> None:
        tax_file = self.store.create_tax_file(
            name="Client 2025",
            tax_year=2025,
            tax_country="United States",
            entity_type="individual",
        )
        account, created = self.store.add_account(
            tax_file_id=tax_file.id,
            address=DEMO_WALLET_ADDRESS,
            label="Phantom main",
            ownership_status=OWNERSHIP_OWNED,
        )
        duplicate, duplicate_created = self.store.add_account(
            tax_file_id=tax_file.id,
            address=DEMO_WALLET_ADDRESS,
            label="Duplicate",
            ownership_status=OWNERSHIP_UNKNOWN,
        )

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(account.id, duplicate.id)
        self.assertEqual(len(self.store.list_accounts(tax_file.id)), 1)

    def test_match_internal_transfers_finds_demo_self_transfer(self) -> None:
        tax_file = create_demo_tax_file(
            self.tmp,
            primary_address=DEMO_WALLET_ADDRESS,
            secondary_address=DEMO_SECOND_WALLET_ADDRESS,
        )
        matches = matchInternalTransfers(tax_file.id, cache_root=self.tmp, store=self.store)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].asset, "SOL")
        self.assertEqual(matches[0].amount_sent, "0.42")
        self.assertEqual(matches[0].amount_received, "0.42")
        self.assertEqual(matches[0].confidence, "high")
        self.assertEqual(matches[0].status, "confirmed")

    def test_confirmed_internal_transfer_is_not_counted_as_income_or_outflow(self) -> None:
        tax_file = create_demo_tax_file(
            self.tmp,
            primary_address=DEMO_WALLET_ADDRESS,
            secondary_address=DEMO_SECOND_WALLET_ADDRESS,
        )
        match = self.store.list_transfer_matches(tax_file.id)[0]
        self.store.update_transfer_match_status(match.id, MATCH_CONFIRMED)
        matches = self.store.list_transfer_matches(tax_file.id)
        frame = unified_transaction_frame(
            tax_file.id,
            cache_root=self.tmp,
            store=self.store,
            include_non_owned=False,
            matches=matches,
        )
        summary = tax_summary(frame, tax_file.id)

        self.assertTrue(frame["is_internal_transfer"].any())
        self.assertEqual(summary["total_expense_sol"], Decimal("0"))

    def test_rejected_internal_transfer_returns_to_normal_classification(self) -> None:
        tax_file = create_demo_tax_file(
            self.tmp,
            primary_address=DEMO_WALLET_ADDRESS,
            secondary_address=DEMO_SECOND_WALLET_ADDRESS,
        )
        match = self.store.list_transfer_matches(tax_file.id)[0]
        self.store.update_transfer_match_status(match.id, MATCH_REJECTED)
        matches = self.store.list_transfer_matches(tax_file.id)
        frame = unified_transaction_frame(
            tax_file.id,
            cache_root=self.tmp,
            store=self.store,
            include_non_owned=False,
            matches=matches,
        )
        summary = tax_summary(frame, tax_file.id)

        self.assertFalse(frame["is_internal_transfer"].any())
        self.assertEqual(summary["total_expense_sol"], Decimal("0.420005"))

    def test_watch_only_and_unknown_accounts_enter_review_context(self) -> None:
        tax_file = self.store.create_tax_file(
            name="Review client",
            tax_year=2025,
            tax_country="United States",
            entity_type="individual",
        )
        self.store.add_account(
            tax_file_id=tax_file.id,
            address=DEMO_WALLET_ADDRESS,
            label="Watch",
            ownership_status=OWNERSHIP_WATCH_ONLY,
        )
        self.store.add_account(
            tax_file_id=tax_file.id,
            address=DEMO_SECOND_WALLET_ADDRESS,
            label="Unknown",
            ownership_status=OWNERSHIP_UNKNOWN,
        )

        ctx = tax_file_dashboard_context(tax_file.id, self.tmp)
        messages = " ".join(item["message"] for item in ctx["review_queue"])

        self.assertIn("Wallet is watch-only and excluded from tax totals.", messages)
        self.assertIn("Wallet ownership unknown. Transactions are not ready for tax review.", messages)
        self.assertEqual(ctx["summary"]["transactions_total"], "0")

    def test_tax_loss_harvesting_advice_finds_demo_candidate(self) -> None:
        tax_file = create_demo_tax_file(
            self.tmp,
            primary_address=DEMO_WALLET_ADDRESS,
            secondary_address=DEMO_SECOND_WALLET_ADDRESS,
        )
        frame = unified_transaction_frame(tax_file.id, cache_root=self.tmp, store=self.store)
        advice = tax_loss_harvesting_advice(tax_file, frame, today=date(2025, 12, 10))

        self.assertTrue(advice["available"])
        self.assertEqual(advice["country"], "US")
        self.assertEqual(advice["status_label"], "Review Opportunity")
        self.assertIn("December review note", advice["message"])
        self.assertIn("before professional review", advice["message"])
        self.assertEqual(advice["total_estimated_tax_effect_pln"], "")
        self.assertEqual(advice["total_estimated_tax_effect_display"], "$226.56")
        self.assertEqual(advice["candidates"][0]["asset"], "SAMO")
        self.assertIn("capital loss rules", advice["candidates"][0]["warning"])
        self.assertEqual(advice["review_guardrails"][0]["guardrail"], "Cost basis confirmed")

    def test_test_tax_file_has_one_confirmation_then_zero_blockers(self) -> None:
        tax_file = create_test_tax_file(
            self.tmp,
            primary_address=TEST_WALLET_ADDRESS,
            secondary_address=build_test_cache_payloads()[1][0],
        )
        ctx = tax_file_dashboard_context(tax_file.id, self.tmp)

        self.assertEqual(tax_file.tax_country, "United States")
        self.assertEqual(len(ctx["client_questions"]), 1)
        self.assertEqual(ctx["client_questions"][0]["client_question"], "Was this transfer from your own wallet?")
        self.assertEqual(ctx["client_questions"][0]["choices"], [{"value": "own_wallet", "label": "Transfer from my own wallet"}])
        self.assertEqual(ctx["tax_readiness"]["blocking_items"], 1)
        self.assertEqual(ctx["action_summary"]["metrics"][3]["value"], "1")
        self.assertEqual(ctx["tax_payment_plan"]["estimated_tax_before_display"], "$6,172.8")
        self.assertEqual(ctx["tax_payment_plan"]["samo_tax_savings_display"], "$4,848")
        self.assertEqual(ctx["tax_payment_plan"]["optimized_tax_due_display"], "$1,324.8")
        self.assertIn("assumptions", ctx["tax_payment_plan"])
        self.assertIn("Estimated federal tax is calculated", ctx["tax_payment_plan"]["assumptions"][0])

        question = ctx["client_questions"][0]
        self.store.save_client_answer(
            tax_file_id=tax_file.id,
            review_item_id=question["id"],
            account_id=question["account_id"],
            transaction_id=question["signature"],
            review_reason=question["review_reason"],
            direction=question["direction"],
            client_question=question["client_question"],
            client_answer="own_wallet",
        )
        after = tax_file_dashboard_context(tax_file.id, self.tmp)

        self.assertEqual(after["client_questions"], [])
        self.assertEqual(after["tax_readiness"]["blocking_items"], 0)
        self.assertEqual(after["action_summary"]["metrics"][3]["value"], "0")
        self.assertTrue(after["tax_payment_plan"]["confirmation_pending"] is False)

    def test_test_tax_file_export_uses_tax_file_classification_columns(self) -> None:
        tax_file = create_test_tax_file(
            self.tmp,
            primary_address=TEST_WALLET_ADDRESS,
            secondary_address=build_test_cache_payloads()[1][0],
        )
        frame = unified_transaction_frame(tax_file.id, cache_root=self.tmp, store=self.store)
        export = tax_file_export_frame(tax_file, frame)

        required = {
            "tax_category",
            "tax_review_status",
            "cost_basis",
            "proceeds_usd",
            "gain_loss_usd",
            "holding_period",
            "holding_period_days",
            "fmv_usd",
            "fee_usd",
            "fee_treatment",
            "source_wallet",
            "destination_wallet",
            "account_address",
            "transaction_signature",
            "transaction_hash",
            "review_reason",
            "confidence_percent",
        }
        self.assertTrue(required.issubset(set(export.columns)))
        funding = export[export["transaction_signature"] == "G" * 88].iloc[0]
        self.assertEqual(funding["tax_category"], "transfer_from_exchange")
        self.assertEqual(funding["is_potentially_taxable"], "no")
        self.assertEqual(funding["ordinary_income_usd"], "")
        sale = export[export["transaction_signature"] == "K" * 88].iloc[0]
        self.assertEqual(sale["cost_basis"], "6000")
        self.assertEqual(sale["proceeds_usd"], "30000")
        self.assertEqual(sale["gain_loss_usd"], "24000")
        self.assertEqual(sale["holding_period"], "Short-term")

    def test_small_usd_token_price_does_not_render_as_zero(self) -> None:
        self.assertEqual(_format_money(Decimal("0.0024"), "USD"), "$0.0024")

    def test_test_dataset_covers_required_demo_patterns(self) -> None:
        frame = build_test_dataframe()
        tx_types = set(frame["transaction_type"].astype(str))
        tag_types = set(frame["tag_type"].astype(str))

        self.assertIn("SWAP", tx_types)
        self.assertIn("NFT_MINT", tx_types)
        self.assertIn("NFT_SALE", tx_types)
        self.assertIn("STAKE_REWARD", tx_types)
        self.assertIn("WRAP_SOL", tx_types)
        self.assertIn("LP_DEPOSIT", tx_types)
        self.assertIn("AIRDROP", tx_types)
        self.assertIn("Swap", tag_types)
        self.assertIn("LP Deposit/Withdraw", tag_types)
        self.assertTrue((frame["status"] == "failed").any())
        self.assertTrue(frame["tag_usd_estimate"].isna().any())

    def test_tax_loss_harvesting_advice_supports_us_tax_file(self) -> None:
        tax_file = self.store.create_tax_file(
            name="US client",
            tax_year=2025,
            tax_country="United States",
            entity_type="individual",
        )
        self.store.add_account(
            tax_file_id=tax_file.id,
            address=DEMO_WALLET_ADDRESS,
            label="Phantom main",
            ownership_status=OWNERSHIP_OWNED,
        )
        frame = unified_transaction_frame(tax_file.id, cache_root=self.tmp, store=self.store)
        advice = tax_loss_harvesting_advice(tax_file, frame, today=date(2025, 12, 10))

        self.assertTrue(advice["available"])
        self.assertEqual(advice["country"], "US")
        self.assertEqual(advice["currency"], "USD")
        self.assertEqual(advice["total_estimated_tax_effect_display"], "$226.56")
        self.assertIn("US federal tax", advice["message"])
        self.assertIn("Form 8949", " ".join(advice["guardrails"]))

    def test_cost_basis_rows_track_demo_fifo_lots_and_missing_basis(self) -> None:
        tax_file = create_demo_tax_file(
            self.tmp,
            primary_address=DEMO_WALLET_ADDRESS,
            secondary_address=DEMO_SECOND_WALLET_ADDRESS,
        )
        frame = unified_transaction_frame(tax_file.id, cache_root=self.tmp, store=self.store)
        rows = cost_basis_rows(tax_file, frame)

        self.assertTrue(rows)
        self.assertTrue(any(row["asset"] == "SOL" and row["method"] == "FIFO" for row in rows))
        self.assertTrue(any(row["status"] == "Ready for review" for row in rows))
        self.assertTrue(any(row["status"] == "Needs FMV" for row in rows))
        self.assertTrue(any(row["status"] == "Needs cost basis" for row in rows))
        self.assertTrue(
            any(
                "Missing acquisition lot for" in row["missing_data"]
                and "SOL disposed on 2025-12-03" in row["missing_data"]
                for row in rows
            )
        )

    def test_missing_cost_basis_review_message_names_disposed_amount(self) -> None:
        tax_file = create_demo_tax_file(
            self.tmp,
            primary_address=DEMO_WALLET_ADDRESS,
            secondary_address=DEMO_SECOND_WALLET_ADDRESS,
        )
        ctx = tax_file_dashboard_context(tax_file.id, self.tmp)
        messages = " ".join(item["message"] for item in ctx["review_queue"])

        self.assertIn(
            "Missing acquisition lot for 6.4 SOL disposed on 2025-12-03. Add exchange history, manual purchase data, or mark the basis as unknown before relying on tax totals.",
            messages,
        )
        self.assertNotIn("Cost basis needed", messages)

    def test_tax_readiness_and_accountant_checklist_flag_demo_blockers(self) -> None:
        tax_file = create_demo_tax_file(
            self.tmp,
            primary_address=DEMO_WALLET_ADDRESS,
            secondary_address=DEMO_SECOND_WALLET_ADDRESS,
        )
        ctx = tax_file_dashboard_context(tax_file.id, self.tmp)
        readiness = ctx["tax_readiness"]
        checklist = {row["task"]: row for row in ctx["accountant_checklist"]}

        self.assertEqual(readiness["score_display"], "0%")
        self.assertEqual(readiness["status_label"], "Blocked")
        self.assertEqual(readiness["blocking_items"], 6)
        self.assertEqual(readiness["counts"]["missing_cost_basis"], 3)
        self.assertEqual(readiness["counts"]["unknown_outgoing"], 1)
        self.assertIn("6 blockers need resolution", readiness["explanation"])
        self.assertIn("relying on draft tax totals", readiness["explanation"])
        self.assertIn("Resolve 3 missing acquisition", ctx["action_summary"]["primary_next_action"])
        self.assertIn("blocked", ctx["section_summaries"]["accountant_checklist"])
        self.assertEqual(checklist["Wallets connected"]["status"], "Done")
        self.assertEqual(checklist["Exchange history imported"]["status"], "Blocked")
        self.assertEqual(checklist["Cost basis completed"]["status"], "Blocked")
        self.assertEqual(checklist["FMV values completed"]["status"], "Blocked")
        self.assertEqual(checklist["Year-end balances reconciled"]["status"], "Needs review")
        self.assertEqual(checklist["Accountant sign-off"]["status"], "Blocked")


class TaxFileRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.id().replace(".", "_") + "_tmp")
        self.tmp.mkdir(exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.app = create_app(
            helius_api_key="k",
            max_pages=1,
            cache_root=self.tmp,
            fetcher_factory=None,
        )
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_demo_route_creates_tax_file_dashboard_and_unified_assistant(self) -> None:
        self.client.post("/demo")
        store = TaxFileStore(self.tmp)
        tax_file = store.get_tax_file(TEST_TAX_FILE_ID)
        self.assertIsNotNone(tax_file)
        self.assertEqual(tax_file.tax_country, "United States")

        detail = self.client.get(f"/tax-files/{TEST_TAX_FILE_ID}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"1 User Confirmation Needed", detail.data)
        self.assertIn(b"Was this transfer from your own wallet?", detail.data)
        self.assertIn(b"Confirm: Transfer from my own wallet", detail.data)
        self.assertIn(b"Presentation Readiness", detail.data)
        self.assertIn(b"Pending User Confirmation", detail.data)
        self.assertIn(b"Client Questions", detail.data)
        self.assertIn(b"Action Summary", detail.data)
        self.assertIn(b"Primary next action", detail.data)
        self.assertIn(b"Potential Loss Harvesting Review", detail.data)
        self.assertIn(b"Review Opportunity", detail.data)
        self.assertIn(b"This is not a trade recommendation or tax advice", detail.data)
        self.assertIn(b"Potential tax impact before professional review", detail.data)
        self.assertIn(b"$4,848", detail.data)
        self.assertIn(b"$1,324.8", detail.data)
        self.assertIn(b"AI Accountant Findings", detail.data)
        self.assertIn(b"Demo dataset: 2025 US taxpayer story", detail.data)
        self.assertNotIn(b"No items in this group", detail.data)
        self.assertNotIn(b"PLN", detail.data)
        self.assertNotIn(b"PIT-38", detail.data)
        self.assertIn(b"Open Unified Tax Assistant", detail.data)

        wallet = self.client.get(f"/wallet/{TEST_WALLET_ADDRESS}")
        self.assertEqual(wallet.status_code, 200)
        self.assertIn(b"Wallet Dashboard shows raw Solana wallet activity", wallet.data)

        tax = self.client.get(f"/tax-files/{TEST_TAX_FILE_ID}/tax")
        self.assertEqual(tax.status_code, 200)
        self.assertIn(b"Unified Tax Assistant", tax.data)
        self.assertIn(b"United States", tax.data)
        self.assertIn(b"US Tax Estimate &amp; Optimization Plan", tax.data)
        self.assertIn(b"Estimated federal tax", tax.data)
        self.assertIn(b"$6,172.8", tax.data)
        self.assertIn(b"Estimate assumptions", tax.data)
        self.assertIn(b"Tax Reporting", tax.data)
        self.assertIn(b"Tax Planning", tax.data)
        self.assertIn(b"CPA-ready package", tax.data)
        self.assertNotIn(b"PLN", tax.data)
        self.assertNotIn(b"PIT-38", tax.data)
        self.assertNotIn(b"Poland notes", tax.data)
        self.assertNotIn(b"/wallet/2025-us-crypto-tax-review/tx/", tax.data)
        self.assertIn(f"/wallet/{TEST_WALLET_ADDRESS}/tx/".encode(), tax.data)
        raw = self.client.get(f"/wallet/{TEST_WALLET_ADDRESS}/tx/{'K' * 88}")
        self.assertEqual(raw.status_code, 200)

        export = self.client.get(f"/tax-files/{TEST_TAX_FILE_ID}/tax-export.json")
        self.assertEqual(export.status_code, 200)
        self.assertIn(b'"cost_basis"', export.data)
        self.assertIn(b'"confidence_percent"', export.data)

    def test_tax_files_create_form_uses_tax_country_dropdown(self) -> None:
        response = self.client.get("/tax-files")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<select name="tax_country">', response.data)
        self.assertIn(b'value="Poland"', response.data)
        self.assertIn(b'value="United States"', response.data)

    def test_wallets_screen_stays_simple_portfolio_workflow(self) -> None:
        for address, df, meta in build_demo_cache_payloads()[:1]:
            cache_mod.write(address, df, meta, cache_root=self.tmp)

        landing = self.client.get("/")
        self.assertEqual(landing.status_code, 200)
        self.assertIn(b"Manage Tax Files", landing.data)
        self.assertIn(b"Open Dashboard", landing.data)
        self.assertNotIn(b"Create Tax File from selected", landing.data)
        self.assertNotIn(b"Add to Tax File", landing.data)
        self.assertNotIn(b'name="ownership_status"', landing.data)

    def test_create_tax_file_and_link_cached_wallet_from_tax_file_detail(self) -> None:
        for address, df, meta in build_demo_cache_payloads()[:1]:
            cache_mod.write(address, df, meta, cache_root=self.tmp)

        create = self.client.post(
            "/tax-files",
            data={
                "name": "Client A 2025",
                "tax_year": "2025",
                "tax_country": "United States",
                "entity_type": "individual",
            },
        )
        self.assertEqual(create.status_code, 303)
        tax_file_id = create.headers["Location"].rsplit("/", 1)[-1]

        link = self.client.post(
            f"/tax-files/{tax_file_id}/accounts",
            data={
                "address": DEMO_WALLET_ADDRESS,
                "label": "Phantom main",
                "ownership_status": "owned",
            },
        )
        self.assertEqual(link.status_code, 303)

        detail = self.client.get(f"/tax-files/{tax_file_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Phantom main", detail.data)
        self.assertIn(b"owned", detail.data)

    def test_client_answer_resolves_active_question(self) -> None:
        self.client.post("/demo")
        detail = self.client.get(f"/tax-files/{TEST_TAX_FILE_ID}")
        self.assertIn(b"Was this transfer from your own wallet?", detail.data)

        ctx = tax_file_dashboard_context(TEST_TAX_FILE_ID, self.tmp)
        question = next(
            item
            for item in ctx["client_questions"]
            if item["review_reason"] == "unknown_source"
        )
        answer = self.client.post(
            f"/tax-files/{TEST_TAX_FILE_ID}/review/{question['id']}/answer",
            data={
                "account_id": question["account_id"],
                "transaction_id": question["signature"],
                "review_reason": question["review_reason"],
                "direction": question["direction"],
                "client_question": question["client_question"],
                "client_answer": "own_wallet",
            },
        )
        self.assertEqual(answer.status_code, 303)

        after_ctx = tax_file_dashboard_context(TEST_TAX_FILE_ID, self.tmp)
        active_ids = {item["id"] for item in after_ctx["client_questions"]}
        self.assertNotIn(question["id"], active_ids)
        self.assertEqual(after_ctx["tax_readiness"]["blocking_items"], 0)
        frame = unified_transaction_frame(TEST_TAX_FILE_ID, cache_root=self.tmp, store=TaxFileStore(self.tmp))
        confirmed = frame[frame["signature"] == question["signature"]].iloc[0]
        self.assertTrue(bool(confirmed["is_internal_transfer"]))

    def test_accountant_override_resolves_item_and_writes_audit_log(self) -> None:
        self.client.post("/demo")
        ctx = tax_file_dashboard_context(TEST_TAX_FILE_ID, self.tmp)
        item = next(item for item in ctx["client_questions"] if item["review_reason"] == "unknown_source")
        item_id = item["id"]

        response = self.client.post(
            f"/tax-files/{TEST_TAX_FILE_ID}/review/{item['id']}/override",
            data={
                "account_id": item["account_id"],
                "transaction_id": item["signature"],
                "review_reason": item["review_reason"],
                "original_tax_category": item["detected_category_enum"],
                "tax_category": "internal_transfer",
                "tax_review_status": "resolved",
                "accountant_note": "Accountant confirmed this came from the client-owned cold wallet.",
            },
        )
        self.assertEqual(response.status_code, 303)

        after_ctx = tax_file_dashboard_context(TEST_TAX_FILE_ID, self.tmp)
        active_ids = {item["id"] for item in after_ctx["client_questions"]}
        self.assertNotIn(item_id, active_ids)
        frame = unified_transaction_frame(TEST_TAX_FILE_ID, cache_root=self.tmp, store=TaxFileStore(self.tmp))
        overridden = frame[frame["signature"] == item["signature"]].iloc[0]
        self.assertTrue(bool(overridden["override_applied"]))
        self.assertEqual(overridden["tax_category"], "internal_transfer")
        audit_actions = [entry["action_type"] for entry in after_ctx["audit_log"]]
        self.assertIn("accountant_override_saved", audit_actions)

    def test_exclude_and_restore_transaction_from_tax_file(self) -> None:
        self.client.post("/demo")
        ctx = tax_file_dashboard_context(TEST_TAX_FILE_ID, self.tmp)
        item = next(item for item in ctx["client_questions"] if item["review_reason"] == "unknown_source")

        excluded = self.client.post(
            f"/tax-files/{TEST_TAX_FILE_ID}/review/{item['id']}/exclude",
            data={
                "account_id": item["account_id"],
                "transaction_id": item["signature"],
                "review_reason": item["review_reason"],
                "original_tax_category": item["detected_category_enum"],
                "tax_category": item["tax_category"],
                "accountant_note": "Duplicate imported from another source.",
            },
        )
        self.assertEqual(excluded.status_code, 303)

        excluded_ctx = tax_file_dashboard_context(TEST_TAX_FILE_ID, self.tmp)
        excluded_ids = {item["id"] for item in excluded_ctx["excluded_review_items"]}
        self.assertIn(item["id"], excluded_ids)

        restored = self.client.post(
            f"/tax-files/{TEST_TAX_FILE_ID}/review/{item['id']}/restore",
            data={
                "account_id": item["account_id"],
                "transaction_id": item["signature"],
                "review_reason": item["review_reason"],
                "original_tax_category": item["detected_category_enum"],
                "tax_category": item["tax_category"],
                "accountant_note": "Duplicate check was incorrect; restore for review.",
            },
        )
        self.assertEqual(restored.status_code, 303)

        restored_ctx = tax_file_dashboard_context(TEST_TAX_FILE_ID, self.tmp)
        excluded_ids = {item["id"] for item in restored_ctx["excluded_review_items"]}
        accountant_ids = {item["id"] for item in restored_ctx["review_groups"]["needs_accountant_review"]}
        audit_actions = [entry["action_type"] for entry in restored_ctx["audit_log"]]
        self.assertNotIn(item["id"], excluded_ids)
        self.assertIn(item["id"], accountant_ids)
        self.assertIn("transaction_excluded", audit_actions)
        self.assertIn("transaction_restored", audit_actions)

    def test_archive_tax_file_is_hidden_until_requested(self) -> None:
        self.client.post("/demo")
        archived = self.client.post(
            f"/tax-files/{TEST_TAX_FILE_ID}/archive",
            data={"note": "Client engagement completed."},
        )
        self.assertEqual(archived.status_code, 303)

        default_list = self.client.get("/tax-files")
        self.assertEqual(default_list.status_code, 200)
        self.assertNotIn(b"test-tax-file-2025", default_list.data)

        archived_list = self.client.get("/tax-files?show_archived=1")
        self.assertEqual(archived_list.status_code, 200)
        self.assertIn(b"2025 US Crypto Tax Review", archived_list.data)
        self.assertIn(b"Archived", archived_list.data)


if __name__ == "__main__":
    unittest.main()
