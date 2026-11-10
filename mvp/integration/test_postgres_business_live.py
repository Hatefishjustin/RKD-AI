"""Actual business API/byte workflow tests against a non-owner PostgreSQL role."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import copy
import json
import zipfile
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg

from rkd_mvp.api_service import ApiError
from rkd_mvp.file_repository import PostgresFileTransaction
from rkd_mvp.models import TenantContext
from rkd_mvp.postgres_api_service import PostgresApiService
from rkd_mvp.postgres_store import PostgresStore
from rkd_mvp.design_rules import DEFAULT_PROGRAM
from rkd_mvp.requirement_repository import PostgresRequirementTransaction
from rkd_mvp.procurement_repository import PostgresProcurementTransaction

APP_FACTORY = None


class PostgresBusinessLiveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.org, self.project = "org-" + uuid4().hex, "project-" + uuid4().hex
        self.store = PostgresStore(APP_FACTORY)
        self.api = PostgresApiService(self.store, self.root)
        self.api.create_project(self.org, "Project / 项目", self.project)
        self.data = b"%PDF-1.7\nreal uploaded bytes\n"

    def upload(self, filename="plan.pdf", data=None):
        data = data or self.data
        item = self.api.initiate_upload(self.org, self.project, {"filename": filename, "size_bytes": len(data)})
        self.api.receive_upload(self.org, self.project, item["upload_id"], io.BytesIO(data), len(data))
        return item["upload_id"]

    def complete(self, upload):
        return self.api.complete_upload(self.org, self.project, upload, "")

    def test_01_catalog_org_scope_and_strict_project_rls(self):
        other = self.api.create_project(self.org, "Other")
        foreign = self.api.create_project("org-" + uuid4().hex, "Foreign")
        self.assertEqual({p["project_id"] for p in self.api.list_projects(self.org)["items"]},
                         {self.project, other["project_id"]})
        with APP_FACTORY() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.list_project_summaries()").fetchone()[0], 0)
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.project").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.file_asset").fetchone()[0], 0)
        with self.assertRaises(ApiError) as error:
            self.api.get_project(self.org, foreign["project_id"])
        self.assertEqual(error.exception.status, 404)

    def test_02_project_compare_and_swap_parallel_one_winner(self):
        def update(name):
            try:
                return self.api.update_project(self.org, self.project, {"name": name, "expected_version": 0})
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(update, ("First", "Second")))
        self.assertEqual(sum(isinstance(row, dict) for row in rows), 1)
        self.assertIn("STALE_PROJECT_VERSION", rows)
        self.assertEqual(self.api.get_project(self.org, self.project)["version"], 1)

    def test_03_file_revisions_concurrent_and_bytes_immutable(self):
        uploads = [self.upload() for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(self.complete, uploads))
        self.assertEqual(sorted(row["revision"] for row in rows), [1, 2, 3, 4])
        for row in rows:
            metadata, path = self.api.get_file_content(self.org, self.project, row["file_id"])
            self.assertEqual(path.read_bytes(), self.data)
            self.assertEqual(metadata["sha256"], hashlib.sha256(self.data).hexdigest())
        self.assertEqual(len(self.api.list_files(self.org, self.project)["items"]), 4)

    def test_04_same_upload_parallel_receive_preserves_winning_bytes(self):
        upload = self.api.initiate_upload(self.org, self.project, {"filename": "plan.pdf", "size_bytes": len(self.data)})
        def receive(_):
            try:
                return self.api.receive_upload(self.org, self.project, upload["upload_id"], io.BytesIO(self.data), len(self.data))
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(receive, range(2)))
        self.assertEqual(sum(isinstance(row, dict) for row in results), 1)
        self.assertIn("UPLOAD_STATE", results)
        row = self.complete(upload["upload_id"])
        self.assertEqual(self.api.get_file_content(self.org, self.project, row["file_id"])[1].read_bytes(), self.data)

    def test_05_file_transaction_failure_leaves_retryable_staging(self):
        upload = self.upload()
        with patch.object(PostgresFileTransaction, "insert_file", side_effect=RuntimeError("injected insert failure")):
            with self.assertRaises(RuntimeError):
                self.complete(upload)
        self.assertEqual(self.api.list_files(self.org, self.project)["items"], [])
        self.assertEqual(self.api.file_service._upload(self.org, self.project, upload)["status"], "staged")
        self.assertEqual(list(self.root.rglob("raw/*")), [])
        self.assertEqual(self.complete(upload)["revision"], 1)

    def test_06_project_and_event_rollback_together(self):
        with patch.object(self.api.repository, "append_command_event", side_effect=RuntimeError("event failure")):
            with self.assertRaises(RuntimeError):
                self.api.update_project(self.org, self.project, {"name": "Must roll back", "expected_version": 0})
        row = self.api.get_project(self.org, self.project)
        self.assertEqual((row["version"], row["name"]), (0, "Project / 项目"))
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.domain_event").fetchone()[0], 1)

    def test_07_wrong_scope_changed_hash_and_incomplete_upload(self):
        upload = self.upload()
        with self.assertRaises(ApiError) as error:
            self.api.complete_upload(self.org, self.project, upload, "0" * 64)
        self.assertEqual(error.exception.code, "UPLOAD_HASH_MISMATCH")
        row = self.complete(upload)
        other = self.api.create_project(self.org, "Other")
        with self.assertRaises(ApiError) as error:
            self.api.get_file_content(self.org, other["project_id"], row["file_id"])
        self.assertEqual(error.exception.status, 404)
        path = self.api.get_file_content(self.org, self.project, row["file_id"])[1]
        path.write_bytes(b"X" * len(self.data))
        with self.assertRaises(ApiError) as error:
            self.api.get_file_content(self.org, self.project, row["file_id"])
        self.assertEqual(error.exception.code, "FILE_INTEGRITY")
        partial = self.api.initiate_upload(self.org, self.project, {"filename": "partial.pdf", "size_bytes": len(self.data)})
        with self.assertRaises(ApiError):
            self.api.receive_upload(self.org, self.project, partial["upload_id"], io.BytesIO(b"short"), len(self.data))
        self.assertEqual(self.api.file_service._upload(self.org, self.project, partial["upload_id"])["status"], "initiated")
        self.api.receive_upload(self.org, self.project, partial["upload_id"], io.BytesIO(self.data), len(self.data))
        self.assertEqual(self.complete(partial["upload_id"])["revision"], 1)

    def test_08_non_project_domains_fail_explicitly_and_no_sqlite_file(self):
        for method, path in (("GET", "/api/v1/projects/p/workflows"), ("POST", "/api/v1/projects/p/commands"),
                             ("POST", "/api/v1/unconnected")):
            with self.assertRaises(ApiError) as error:
                self.api.validate_route(method, path)
            self.assertEqual(error.exception.status, 501)
        self.assertIsNone(self.api.file_service.db_path)
        self.assertEqual(list(self.root.rglob("*.sqlite3")), [])
        with self.assertRaises(psycopg.Error):
            with APP_FACTORY() as db:
                db.execute("INSERT INTO rkd.project(organization_id,project_id,name) VALUES ('forged','forged','forged')")

    def test_09_requirement_draft_keeps_real_file_source_and_unknown(self):
        file = self.complete(self.upload())
        self.assertIsNone(self.api.get_requirement(self.org, self.project)["item"])
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            db.execute("INSERT INTO rkd.project_decision(organization_id,project_id,decision_key,value,source,status,source_conflict) "
                       "VALUES (%s,%s,'trial_tax_rate','\"0.05\"'::jsonb,'user','trial','source tax unresolved')", (self.org, self.project))
        draft = self.api.create_requirement_draft(self.org, self.project, "actor-1", {})["item"]
        self.assertEqual(draft["content"]["budget"]["tax_rate"], "0.05")
        self.assertEqual(draft["content"]["budget"]["contract_target_gross_cny"], "unknown")
        refs = draft["source_refs"]
        self.assertEqual(next(row["file_id"] for row in refs if row["type"] == "file_asset"), file["file_id"])
        self.assertEqual(next(row["source_conflict"] for row in refs if row["type"] == "project_decision"), "source tax unresolved")
        self.assertEqual(self.api.create_requirement_draft(self.org, self.project, "actor-2", {})["item"], draft)

    def test_10_requirement_parallel_first_creation_is_single_revision(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            rows = list(pool.map(lambda _: self.api.create_requirement_draft(self.org, self.project, "test", {})["item"], range(3)))
        self.assertEqual(len({row["requirement_id"] for row in rows}), 1)
        self.assertEqual({row["revision_no"] for row in rows}, {1})

    def test_11_requirement_compare_and_swap_history_and_noop(self):
        self.api.create_requirement_draft(self.org, self.project, "test", {})
        request = {"expected_revision": 1, "design_program": DEFAULT_PROGRAM, "design_notes": "Actual shared rule draft", "change_reason": "test"}
        def edit(i):
            try:
                return self.api.update_requirement(self.org, self.project, "editor", {**request, "design_notes": "note-" + str(i)})["item"]
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(edit, range(2)))
        self.assertEqual(sum(isinstance(row, dict) for row in rows), 1)
        self.assertIn("STALE_REQUIREMENT_REVISION", rows)
        current = self.api.get_requirement(self.org, self.project)["item"]
        no_op = self.api.update_requirement(self.org, self.project, "editor", {**request, "expected_revision": 2,
                                          "design_notes": current["content"]["design_notes"]})["item"]
        self.assertEqual(no_op, current)
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            history = db.execute("SELECT revision_no,content FROM rkd.requirement_revision ORDER BY revision_no").fetchall()
        self.assertEqual([row[0] for row in history], [1, 2])
        self.assertNotIn("design_program", history[0][1])

    def test_12_requirement_insert_and_pointer_rollback_together(self):
        draft = self.api.create_requirement_draft(self.org, self.project, "test", {})["item"]
        original = PostgresRequirementTransaction.advance
        def fail_after_advance(transaction, *args):
            original(transaction, *args)
            raise RuntimeError("injected after pointer update")
        with patch.object(PostgresRequirementTransaction, "advance", fail_after_advance):
            with self.assertRaises(RuntimeError):
                self.api.update_requirement(self.org, self.project, "test", {"expected_revision": 1, "design_program": DEFAULT_PROGRAM,
                                            "design_notes": "retry", "change_reason": "rollback"})
        self.assertEqual(self.api.get_requirement(self.org, self.project)["item"], draft)
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.requirement_revision").fetchone()[0], 1)

    def test_13_requirement_validation_and_wrong_scope(self):
        draft = self.api.create_requirement_draft(self.org, self.project, "test", {})["item"]
        with self.assertRaises(ApiError) as error:
            self.api.update_requirement(self.org, self.project, "test", {"expected_revision": 1, "design_program": {"width_m": "bad"}, "change_reason": "invalid"})
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(self.api.get_requirement(self.org, self.project)["item"], draft)
        with self.assertRaises(ApiError) as error:
            self.api.get_requirement("foreign", self.project)
        self.assertEqual(error.exception.status, 404)

    def order(self, key="procurement-order-key-0001", multiple=False):
        lines = [{"item_code": "A", "item_name": "Floor A", "ordered_quantity": "10", "unit": "m2"}]
        if multiple:
            lines.append({"item_code": "B", "item_name": "Floor B", "ordered_quantity": "8", "unit": "m2"})
        return self.api.create_procurement_order(self.org, self.project, "test", {
            "supplier_name": "Supplier", "delivery_location": "Site", "lines": lines}, key)

    def test_14_procurement_parallel_idempotency_and_conflict(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            rows = list(pool.map(lambda _: self.order(), range(3)))
        self.assertEqual(len({row["order_id"] for row in rows}), 1)
        self.assertEqual(rows[0]["external_effects_enabled"], False)
        with self.assertRaises(ApiError) as error:
            self.api.create_procurement_order(self.org, self.project, "test", {"supplier_name": "Changed", "delivery_location": "Site",
                "lines": [{"item_name": "Floor", "ordered_quantity": "2", "unit": "m2"}]}, "procurement-order-key-0001")
        self.assertEqual(error.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_15_procurement_parallel_receipt_allocation_conserves_stock(self):
        order = self.order()
        line = order["lines"][0]["line_id"]
        request = {"receiver": "Person", "evidence_ref": "local://receipt", "lines": [{"line_id": line, "quantity": "6"}]}
        def receive(i):
            try:
                return self.api.receive_procurement(self.org, self.project, order["order_id"], "test", request, f"concurrent-receipt-key-{i}")
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(receive, range(2)))
        self.assertEqual(sum(isinstance(row, dict) for row in rows), 1)
        self.assertIn("RECEIPT_EXCEEDS_ORDER", rows)
        allocation = {"target_area": "Room", "recipient": "Team", "evidence_ref": "local://dispatch", "lines": [{"line_id": line, "quantity": "4"}]}
        def allocate(i):
            try:
                return self.api.allocate_procurement(self.org, self.project, order["order_id"], "test", allocation, f"concurrent-allocation-key-{i}")
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(allocate, range(2)))
        self.assertEqual(sum(isinstance(row, dict) for row in rows), 1)
        self.assertIn("ALLOCATION_EXCEEDS_RECEIPT", rows)
        current = self.api.get_procurement_order(self.org, self.project, order["order_id"])
        self.assertEqual(current["lines"][0]["remaining_quantity"], "2")
        self.assertEqual((len(current["receipts"]), len(current["allocations"])), (1, 1))

    def test_16_procurement_multi_line_allocation_and_replay(self):
        order = self.order(multiple=True)
        lines = [{"line_id": row["line_id"], "quantity": row["ordered_quantity"]} for row in order["lines"]]
        self.api.receive_procurement(self.org, self.project, order["order_id"], "test",
            {"receiver": "Person", "evidence_ref": "local://receipt", "lines": lines}, "multi-receipt-key-0001")
        request = {"target_area": "Room", "recipient": "Team", "evidence_ref": "local://dispatch", "lines": lines}
        current = self.api.allocate_procurement(self.org, self.project, order["order_id"], "test", request, "multi-allocation-key-0001")
        self.assertEqual((current["status"], len(current["allocations"])), ("allocated", 2))
        self.assertEqual(current, self.api.allocate_procurement(self.org, self.project, order["order_id"], "test", request, "multi-allocation-key-0001"))

    def test_17_procurement_fact_and_event_failure_rolls_back_all(self):
        order = self.order()
        request = {"receiver": "Person", "evidence_ref": "local://receipt", "lines": [{"line_id": order["lines"][0]["line_id"], "quantity": "6"}]}
        with patch.object(PostgresProcurementTransaction, "write_event", side_effect=RuntimeError("event insert failure")):
            with self.assertRaises(RuntimeError):
                self.api.receive_procurement(self.org, self.project, order["order_id"], "test", request, "failed-receipt-key-0001")
        current = self.api.get_procurement_order(self.org, self.project, order["order_id"])
        self.assertEqual((current["version"], current["receipts"], current["lines"][0]["received_quantity"]), (1, [], "0"))
        self.assertEqual(self.api.receive_procurement(self.org, self.project, order["order_id"], "test", request, "failed-receipt-key-0001")["version"], 2)

    def test_18_procurement_other_project_and_stale_version_rejected(self):
        order = self.order()
        other = self.api.create_project(self.org, "Other")
        with self.assertRaises(ApiError) as error:
            self.api.get_procurement_order(self.org, other["project_id"], order["order_id"])
        self.assertEqual(error.exception.status, 404)
        with self.assertRaises(ApiError) as error:
            self.api.receive_procurement(self.org, self.project, order["order_id"], "test", {
                "receiver": "Person", "evidence_ref": "local://receipt", "expected_version": 99,
                "lines": [{"line_id": order["lines"][0]["line_id"], "quantity": "1"}]}, "stale-receipt-key-0001")
        self.assertEqual(error.exception.code, "STALE_ORDER_VERSION")

    def design(self):
        self.api.create_requirement_draft(self.org, self.project, "test", {})
        self.api.update_requirement(self.org, self.project, "test", {"expected_revision": 1, "design_program": DEFAULT_PROGRAM,
                                    "design_notes": "PG test boundary", "change_reason": "test"})
        return self.api.create_design(self.org, self.project, "test", {
            "expected_revision": 0, "requirement_revision_no": 2, "change_reason": "test layout"})["item"]

    def configure(self, design_no=1, version=0, cost="100", **settings):
        return self.api.save_production_settings(self.org, self.project, "test", {"expected_version": version,
            "expected_design_revision": design_no, "settings": {"unit_cost_net": cost, "material_specification": "Floor test material",
                "supplier_name": "Test supplier", "delivery_location": "Test site", **settings}})

    def test_19_design_generates_shared_unknown_quote_and_real_artifacts(self):
        design = self.design()
        production = self.api.get_production(self.org, self.project)["item"]
        self.assertEqual(production["quote"]["quantity"], "78.0000")
        self.assertIsNone(production["quote"]["sale_gross"])
        self.assertEqual(production["design_revision_id"], design["design_revision_id"])
        self.assertEqual((len(design["artifacts"]), len(production["artifacts"])), (7, 8))
        for artifact in production["artifacts"]:
            metadata, path = self.api.get_production_artifact(self.org, self.project, artifact["artifact_id"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), metadata["sha256"])
        repeated = self.api.create_design(self.org, self.project, "test", {"expected_revision": 1, "requirement_revision_no": 2, "change_reason": "no-op"})["item"]
        self.assertEqual(repeated["design_revision_id"], design["design_revision_id"])
        self.assertEqual(len(self.api.get_production(self.org, self.project)["revisions"]), 1)

    def test_20_design_size_propagates_quote_order_and_preserves_old_package(self):
        self.design()
        before = self.configure()["item"]
        self.assertEqual(before["quote"]["sale_gross"], "9828.00")
        old = {a["artifact_id"]: self.api.get_production_artifact(self.org, self.project, a["artifact_id"])[1].read_bytes() for a in before["artifacts"]}
        program = copy.deepcopy(DEFAULT_PROGRAM)
        program["width"] = "16"
        self.api.update_requirement(self.org, self.project, "test", {"expected_revision": 2, "design_program": program,
                                    "design_notes": "PG 16m", "change_reason": "size"})
        self.assertEqual(self.api.get_production(self.org, self.project)["item"]["status"], "source_outdated")
        design = self.api.create_design(self.org, self.project, "test", {"expected_revision": 1, "requirement_revision_no": 3, "change_reason": "widen"})["item"]
        after = self.api.get_production(self.org, self.project)["item"]
        self.assertEqual((after["quote"]["quantity"], after["quote"]["sale_gross"]), ("104.0000", "13104.00"))
        order = self.api.get_procurement_order(self.org, self.project, after["procurement"]["order_id"])
        self.assertEqual(order["source_ref"], after["production_revision_id"])
        self.assertEqual(sum(float(line["ordered_quantity"]) for line in order["lines"]), 104)
        self.assertEqual(after["baseline"]["design_revision_id"], design["design_revision_id"])
        for artifact, data in old.items():
            self.assertEqual(self.api.get_production_artifact(self.org, self.project, artifact)[1].read_bytes(), data)
        package = next(a for a in after["artifacts"] if a["artifact_kind"] == "package_zip")
        path = self.api.get_production_artifact(self.org, self.project, package["artifact_id"])[1]
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(len(archive.namelist()), 7)
        ids = {row["quantity_item_id"] for row in after["quantities"]}
        self.assertEqual(ids, {row["item_code"] for row in order["lines"]})

    def test_21_design_production_order_failure_rolls_back_together(self):
        self.configure(design_no=0)
        self.api.create_requirement_draft(self.org, self.project, "test", {})
        self.api.update_requirement(self.org, self.project, "test", {"expected_revision": 1, "design_program": DEFAULT_PROGRAM, "change_reason": "test"})
        request = {"expected_revision": 0, "requirement_revision_no": 2, "change_reason": "test"}
        with patch("rkd_mvp.production_service.generate_production_outputs", side_effect=OSError("injected production failure")):
            with self.assertRaises(OSError):
                self.api.create_design(self.org, self.project, "test", request)
        self.assertIsNone(self.api.get_design(self.org, self.project)["item"])
        self.assertIsNone(self.api.get_production(self.org, self.project)["item"])
        self.assertEqual(self.api.list_procurement_orders(self.org, self.project)["items"], [])
        self.api.create_design(self.org, self.project, "test", request)
        before = self.api.get_production(self.org, self.project)
        with patch("rkd_mvp.production_service.generate_production_outputs", side_effect=OSError("settings failure")):
            with self.assertRaises(OSError):
                self.configure(version=1, cost="200")
        self.assertEqual(self.api.get_production(self.org, self.project), before)
        self.assertEqual(len(self.api.list_procurement_orders(self.org, self.project)["items"]), 1)

    def test_22_concurrent_design_cas_and_settings_cas(self):
        self.api.create_requirement_draft(self.org, self.project, "test", {})
        self.api.update_requirement(self.org, self.project, "test", {"expected_revision": 1, "design_program": DEFAULT_PROGRAM, "change_reason": "test"})
        def create(_):
            try:
                return self.api.create_design(self.org, self.project, "test", {"expected_revision": 0, "requirement_revision_no": 2, "change_reason": "parallel"})
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(create, range(2)))
        self.assertEqual(sum(isinstance(row, dict) for row in rows), 1)
        self.assertIn("STALE_DESIGN_REVISION", rows)
        def configure(cost):
            try:
                return self.configure(cost=cost)
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(configure, ("100", "200")))
        self.assertEqual(sum(isinstance(row, dict) for row in rows), 1)
        self.assertIn("STALE_PRODUCTION_SETTINGS", rows)

    def test_23_old_orders_and_existing_physical_facts_require_reconciliation(self):
        self.design()
        production = self.configure()["item"]
        order = self.api.get_procurement_order(self.org, self.project, production["procurement"]["order_id"])
        self.api.receive_procurement(self.org, self.project, order["order_id"], "test", {"receiver": "Person", "evidence_ref": "local://receipt",
            "lines": [{"line_id": order["lines"][0]["line_id"], "quantity": "1"}]}, "production-receipt-key-0001")
        latest = self.configure(version=1, cost="200")["item"]
        self.assertEqual(latest["procurement"]["status"], "requires_reconciliation")
        self.assertIsNone(latest["procurement"]["order_id"])
        with self.assertRaises(ApiError) as error:
            self.api.receive_procurement(self.org, self.project, order["order_id"], "test", {"receiver": "Person", "evidence_ref": "local://later",
                "lines": [{"line_id": order["lines"][0]["line_id"], "quantity": "1"}]}, "production-receipt-key-0002")
        self.assertEqual(error.exception.code, "ORDER_SOURCE_OUTDATED")
        self.assertEqual(len(self.api.list_procurement_orders(self.org, self.project)["items"]), 1)

    def test_24_model_artifact_scope_and_same_size_tamper_rejected(self):
        self.design()
        item = self.api.get_production(self.org, self.project)["item"]
        artifact = item["artifacts"][0]
        other = self.api.create_project(self.org, "Other")
        with self.assertRaises(ApiError) as error:
            self.api.get_production_artifact(self.org, other["project_id"], artifact["artifact_id"])
        self.assertEqual(error.exception.status, 404)
        _, path = self.api.get_production_artifact(self.org, self.project, artifact["artifact_id"])
        path.write_bytes(b"X" * path.stat().st_size)
        with self.assertRaises(ApiError) as error:
            self.api.get_production_artifact(self.org, self.project, artifact["artifact_id"])
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")

    def model_change(self):
        self.design()
        self.configure()
        program = copy.deepcopy(DEFAULT_PROGRAM)
        program["width"] = "16"
        change = self.api.create_change(self.org, self.project, "editor", {"title": "Wider boundary", "reason": "Site review",
            "description": "Regenerate from new dimensions", "design_program": program, "quantity_delta_m2": "999"}, "pg-model-change-create-0001")
        return self.api.analyze_change(self.org, self.project, change["change_id"], "editor",
                                       {"expected_version": change["version"]}, "pg-model-change-analyze-0001")

    def accept_model_change(self, change):
        return self.api.accept_change(self.org, self.project, change["change_id"], "manager", {
            "expected_version": change["version"], "conclusion": "accepted", "checklist": ["Model and cost reviewed"],
            "evidence_ref": "local://pg/review", "note": "Draft only"}, "pg-model-change-accept-0001")

    def apply_model_change(self, change):
        return self.api.reproduce_change(self.org, self.project, change["change_id"], "manager",
                                         {"expected_version": change["version"]}, "pg-model-change-reproduce-0001")

    def test_25_change_preview_and_reproduction_propagate_shared_models(self):
        analyzed = self.model_change()
        before = self.api.get_production(self.org, self.project)["item"]
        self.assertEqual((analyzed["impact"]["quantity_delta_m2"], analyzed["impact"]["cost_delta_net"]), ("26.0000", "2600.00"))
        self.assertEqual(before["quote"]["quantity"], "78.0000")
        old = {a["artifact_id"]: self.api.get_production_artifact(self.org, self.project, a["artifact_id"])[1].read_bytes() for a in before["artifacts"]}
        accepted = self.accept_model_change(analyzed)
        applied = self.apply_model_change(accepted)
        latest = self.api.get_production(self.org, self.project)["item"]
        self.assertEqual((latest["quote"]["quantity"], latest["quote"]["sale_gross"]), ("104.0000", "13104.00"))
        refs = applied["impact"]["reproduction"]
        self.assertEqual((refs["requirement_revision_no"], refs["design_revision_no"], refs["production_revision_no"]), (3, 2, 3))
        self.assertFalse(refs["external_effects_enabled"])
        self.assertEqual(self.apply_model_change(accepted), applied)
        for artifact, data in old.items():
            self.assertEqual(self.api.get_production_artifact(self.org, self.project, artifact)[1].read_bytes(), data)
        self.assertEqual(len(self.api.list_procurement_orders(self.org, self.project)["items"]), 2)

    def test_26_change_reproduction_rolls_back_even_after_all_outputs(self):
        from rkd_mvp.change_repository import ChangeTransaction
        accepted = self.accept_model_change(self.model_change())
        original = ChangeTransaction.query
        def failure(transaction, operation, params=()):
            if operation == "reproduction":
                raise RuntimeError("late change write failure")
            return original(transaction, operation, params)
        with patch.object(ChangeTransaction, "query", failure):
            with self.assertRaises(RuntimeError):
                self.apply_model_change(accepted)
        self.assertEqual(self.api.get_requirement(self.org, self.project)["item"]["revision_no"], 2)
        self.assertEqual(self.api.get_design(self.org, self.project)["item"]["revision_no"], 1)
        self.assertEqual(self.api.get_change(self.org, self.project, accepted["change_id"]), accepted)
        self.assertEqual(len(self.api.list_procurement_orders(self.org, self.project)["items"]), 1)
        self.assertIn("reproduction", self.apply_model_change(accepted)["impact"])

    def test_27_changed_price_rejects_old_acceptance_and_application(self):
        analyzed = self.model_change()
        self.configure(version=1, cost="200")
        with self.assertRaises(ApiError) as error:
            self.accept_model_change(analyzed)
        self.assertEqual(error.exception.code, "CHANGE_SOURCE_OUTDATED")
        self.assertEqual(self.api.get_requirement(self.org, self.project)["item"]["revision_no"], 2)

    def test_28_parallel_change_reproduction_has_one_fact(self):
        accepted = self.accept_model_change(self.model_change())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.apply_model_change(accepted), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.api.get_production(self.org, self.project)["revisions"]), 3)
        self.assertEqual(len(self.api.list_procurement_orders(self.org, self.project)["items"]), 2)

    def test_29_legacy_change_files_scope_and_integrity_remain_explicit(self):
        self.design()
        change = self.api.create_change(self.org, self.project, "editor", {"title": "Manual change", "reason": "Test",
            "description": "Manual quantity remains unverified", "quantity_delta_m2": "2"}, "pg-legacy-change-create-0001")
        change = self.api.analyze_change(self.org, self.project, change["change_id"], "editor", {"expected_version": change["version"]}, "pg-legacy-change-analyze-0001")
        self.assertEqual(change["impact"]["quantity_cost_source"], "manual_input_unverified")
        self.assertEqual(len(change["artifacts"]), 3)
        for artifact in change["artifacts"]:
            metadata, path = self.api.get_change_artifact(self.org, self.project, artifact["artifact_id"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), metadata["sha256"])
        other = self.api.create_project(self.org, "Other")
        with self.assertRaises(ApiError) as error:
            self.api.get_change(self.org, other["project_id"], change["change_id"])
        self.assertEqual(error.exception.status, 404)
        metadata, path = self.api.get_change_artifact(self.org, self.project, change["artifacts"][0]["artifact_id"])
        path.write_bytes(b"X" * metadata["size_bytes"])
        with self.assertRaises(ApiError) as error:
            self.api.get_change_artifact(self.org, self.project, metadata["artifact_id"])
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")

    def task_seed(self):
        fixture = Path(__file__).resolve().parents[2] / "fixtures/ningbo-xiecheng/2026-09"
        return self.api.task_service.ensure_ningbo_seed(self.org, self.project, fixture)

    def test_30_parallel_task_seed_is_single_import_and_scoped(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _: self.task_seed(), range(2)))
        self.assertEqual(rows[0], rows[1])
        self.assertEqual((rows[0]["status"], rows[0]["attempt_count"], rows[0]["output"]["issue_count"]), ("succeeded", 1, 5))
        self.assertEqual(len(self.api.list_jobs(self.org, self.project)["items"]), 1)
        issues = self.api.list_issues(self.org, self.project)["items"]
        self.assertEqual(len(issues), 5)
        other = self.api.create_project(self.org, "Other")
        with self.assertRaises(ApiError) as error:
            self.api.get_issue(self.org, other["project_id"], issues[0]["issue_id"])
        self.assertEqual(error.exception.status, 404)
        self.assertTrue(all(issue["source_locator"] for issue in issues))
        self.assertEqual(list(self.root.rglob("*.sqlite3")), [])

    def test_31_failed_import_savepoint_keeps_failure_and_retries_cleanly(self):
        from rkd_mvp.task_repository import PostgresTaskTransaction
        original = PostgresTaskTransaction.insert_issue
        calls = []
        def insert(tx, *args):
            calls.append(1)
            if len(calls) == 2:
                tx.db.execute("SELECT 1/0")
            return original(tx, *args)
        with patch.object(PostgresTaskTransaction, "insert_issue", insert):
            job = self.task_seed()
        self.assertEqual((job["status"], job["attempt_count"]), ("retryable", 1))
        self.assertEqual(self.api.list_issues(self.org, self.project)["items"], [])
        fixture = self.api.task_service.fixture_root
        job = self.api.retry_job(self.org, self.project, job["job_id"], fixture)
        self.assertEqual((job["status"], job["attempt_count"], job["output"]["issue_count"]), ("succeeded", 2, 5))
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            self.assertEqual(db.execute("SELECT status FROM rkd.job_attempt ORDER BY attempt_no").fetchall(), [("retryable",), ("succeeded",)])

    def test_32_issue_disposition_and_history_rollback_together(self):
        from rkd_mvp.task_repository import PostgresTaskTransaction
        self.task_seed()
        issue = self.api.list_issues(self.org, self.project)["items"][0]
        request = {"status": "in_review", "reason": "Locate source", "expected_version": issue["version"]}
        original = PostgresTaskTransaction.disposition
        def failure(tx, *args):
            original(tx, *args)
            raise RuntimeError("late issue action failure")
        with patch.object(PostgresTaskTransaction, "disposition", failure):
            with self.assertRaises(RuntimeError):
                self.api.record_issue_disposition(self.org, self.project, issue["issue_id"], request, "editor")
        latest = self.api.get_issue(self.org, self.project, issue["issue_id"])
        self.assertEqual((latest["version"], latest["actions"]), (1, []))
        saved = self.api.record_issue_disposition(self.org, self.project, issue["issue_id"], request, "editor")
        self.assertEqual((saved["version"], saved["disposition_actor_id"]), (2, "editor"))
        self.assertEqual(len(self.api.get_issue(self.org, self.project, issue["issue_id"])["actions"]), 1)
        with self.assertRaises(ApiError) as error:
            self.api.record_issue_disposition(self.org, self.project, issue["issue_id"], {**request, "status": "approved"}, "editor")
        self.assertEqual(error.exception.code, "INVALID_DISPOSITION")

    def test_33_scoped_orphan_recovery_and_cancel_preserve_other_projects(self):
        from rkd_mvp.models import now_iso
        job = self.task_seed()
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            db.execute("UPDATE rkd.job SET status='running' WHERE job_id=%s", (job["job_id"],))
            db.execute("UPDATE rkd.job_attempt SET status='running',finished_at=NULL WHERE job_id=%s", (job["job_id"],))
        other = self.api.create_project(self.org, "Other")
        self.api.task_service.recover_running_jobs(self.org, other["project_id"])
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            self.assertEqual(db.execute("SELECT status FROM rkd.job").fetchone()[0], "running")
        self.assertEqual(self.api.list_jobs(self.org, self.project)["items"][0]["status"], "retryable")
        cancelled = self.api.cancel_job(self.org, self.project, job["job_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaises(ApiError) as error:
            self.api.cancel_job(self.org, self.project, job["job_id"])
        self.assertEqual(error.exception.code, "JOB_STATE")

    def test_34_parallel_issue_compare_and_swap_has_one_action(self):
        self.task_seed()
        issue = self.api.list_issues(self.org, self.project)["items"][0]
        def update(status):
            try:
                return self.api.record_issue_disposition(self.org, self.project, issue["issue_id"],
                    {"status": status, "reason": "Reviewed source", "expected_version": 1}, "editor")
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(update, ("in_review", "deferred")))
        self.assertEqual(sum(isinstance(row, dict) for row in rows), 1)
        self.assertIn("STALE_ISSUE_VERSION", rows)
        self.assertEqual(len(self.api.get_issue(self.org, self.project, issue["issue_id"])["actions"]), 1)

    def estimate_source(self):
        fixture = Path(__file__).resolve().parents[2] / "fixtures/ningbo-xiecheng/2026-09"
        extract = json.loads((fixture / "derived/budget-source-extract.json").read_text(encoding="utf-8"))
        content = (fixture / "source/20260721宁波协诚集团样品展厅装修预算.xls").read_bytes()
        source = self.complete(self.upload("test-budget.xls", content))
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test-setup")) as db:
            db.execute("UPDATE rkd.file_asset SET source_ref=%s WHERE file_id=%s", (extract["source"]["asset_id"], source["file_id"]))
        return fixture

    def estimate(self):
        return self.api.estimate_service.seed_ningbo(self.org, self.project, self.estimate_source())

    def test_35_estimate_import_reconciles_real_source_and_unknown(self):
        estimate = self.estimate()
        result = estimate["calculation"]["result"]
        self.assertEqual(len(estimate["lines"]), 112)
        self.assertEqual((result["source_line_total_before_tax"], result["source_reconciliation_difference"]), ("616308.50", "0.00"))
        self.assertIsNone(result["design_cost_net"])
        self.assertIsNone(result["combined_gross_sale"])
        self.assertEqual(len(self.api.list_estimates(self.org, self.project)["items"]), 1)
        self.assertEqual(list(self.root.rglob("*.sqlite3")), [])

    def test_36_estimate_line_revision_decimal_and_independent_markups(self):
        from decimal import Decimal
        estimate = self.estimate()
        before = Decimal(estimate["calculation"]["result"]["included_construction_cost"])
        estimate = self.api.update_estimate_line(self.org, self.project, estimate["estimate_id"], "xls-exhibition-r004",
            {"expected_revision": 1, "quantity": "7.5", "change_reason": "test quantity"}, "editor")
        line = next(line for line in estimate["lines"] if line["line_id"] == "xls-exhibition-r004")
        self.assertEqual((line["quantity"], line["source_quantity"], line["current_cost"]), ("7.5", "6", "787.50"))
        self.assertEqual(Decimal(estimate["calculation"]["result"]["included_construction_cost"]), before + Decimal("157.50"))
        estimate = self.api.calculate_estimate(self.org, self.project, estimate["estimate_id"], {"expected_revision": 2,
            "trial_tax_rate": "0.05", "construction_cost_markup": "0.20", "design_cost_markup": "0.60", "design_cost_net": "1000"}, "editor")
        self.assertEqual((estimate["revision_no"], estimate["calculation"]["result"]["design_gross_sale"]), (3, "1680.00"))
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            self.assertEqual(db.execute("SELECT quantity_text FROM rkd.estimate_line WHERE revision_no=1 AND line_id='xls-exhibition-r004'").fetchone()[0], "6")

    def test_37_estimate_late_failure_rollback_and_parallel_compare_and_swap(self):
        from rkd_mvp.estimate_repository import PostgresEstimateTransaction
        estimate = self.estimate()
        original = PostgresEstimateTransaction.query
        def failure(tx, operation, params=()):
            if operation == "insert_calculation":
                raise RuntimeError("late calculation insert failure")
            return original(tx, operation, params)
        with patch.object(PostgresEstimateTransaction, "query", failure):
            with self.assertRaises(RuntimeError):
                self.api.calculate_estimate(self.org, self.project, estimate["estimate_id"], {"expected_revision": 1, "design_cost_net": "1000"}, "editor")
        self.assertEqual(self.api.get_estimate(self.org, self.project, estimate["estimate_id"]), estimate)
        def calculate(cost):
            try:
                return self.api.calculate_estimate(self.org, self.project, estimate["estimate_id"], {"expected_revision": 1, "design_cost_net": cost}, "editor")
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(calculate, ("0", "1000")))
        self.assertEqual(sum(isinstance(row, dict) for row in rows), 1)
        self.assertIn("STALE_ESTIMATE_REVISION", rows)
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.estimate_revision").fetchone()[0], 2)

    def test_38_estimate_parallel_exports_preserve_old_files_and_no_partial_rows(self):
        from rkd_mvp.estimate_repository import PostgresEstimateTransaction
        estimate = self.estimate()
        def export():
            return self.api.export_estimate(self.org, self.project, estimate["estimate_id"], "editor")
        with ThreadPoolExecutor(max_workers=2) as pool:
            exports = list(pool.map(lambda _: export(), range(2)))
        self.assertEqual({a["artifact_id"] for a in exports[0]["items"]}, {a["artifact_id"] for a in exports[1]["items"]})
        old = {a["artifact_id"]: self.api.get_estimate_artifact(self.org, self.project, a["artifact_id"])[1].read_bytes() for a in exports[0]["items"]}
        self.api.calculate_estimate(self.org, self.project, estimate["estimate_id"], {"expected_revision": 1, "design_cost_net": "1000"}, "editor")
        original = PostgresEstimateTransaction.query
        calls = []
        def failure(tx, operation, params=()):
            if operation == "insert_artifact":
                calls.append(1)
                if len(calls) == 2:
                    tx.db.execute("SELECT 1/0")
            return original(tx, operation, params)
        with patch.object(PostgresEstimateTransaction, "query", failure):
            with self.assertRaises(psycopg.Error):
                export()
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.estimate_artifact WHERE revision_no=2").fetchone()[0], 0)
        self.assertEqual(len(export()["items"]), 2)
        for artifact, data in old.items():
            self.assertEqual(self.api.get_estimate_artifact(self.org, self.project, artifact)[1].read_bytes(), data)

    def test_39_estimate_scope_same_size_tamper_and_separate_export_directories(self):
        estimate = self.estimate()
        artifact = self.api.export_estimate(self.org, self.project, estimate["estimate_id"], "editor")["items"][0]
        metadata, path = self.api.get_estimate_artifact(self.org, self.project, artifact["artifact_id"])
        other = self.api.create_project(self.org, "Other")
        with self.assertRaises(ApiError) as error:
            self.api.get_estimate_artifact(self.org, other["project_id"], artifact["artifact_id"])
        self.assertEqual(error.exception.status, 404)
        self.org = "foreign-" + uuid4().hex
        self.api.create_project(self.org, "Same project id", self.project)
        another = self.estimate()
        other_artifact = self.api.export_estimate(self.org, self.project, another["estimate_id"], "editor")["items"][0]
        other_path = self.api.get_estimate_artifact(self.org, self.project, other_artifact["artifact_id"])[1]
        self.assertNotEqual(path.parent, other_path.parent)
        path.write_bytes(b"X" * metadata["size_bytes"])
        self.assertEqual(hashlib.sha256(other_path.read_bytes()).hexdigest(), other_artifact["sha256"])
        with self.assertRaises(ApiError) as error:
            self.api.get_estimate_artifact(metadata["organization_id"], self.project, artifact["artifact_id"])
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")
        with self.assertRaises(ApiError) as error:
            self.api.export_estimate(metadata["organization_id"], self.project, estimate["estimate_id"], "editor")
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")

    def test_40_parallel_estimate_import_is_one_revision(self):
        fixture = self.estimate_source()
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _: self.api.estimate_service.seed_ningbo(self.org, self.project, fixture), range(2)))
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[0]["revision_no"], 1)
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.estimate_line").fetchone()[0], 112)

    def spatial(self, expected=0, width="10", cost="100", **extra):
        return self.api.create_spatial_revision(self.org, self.project, {"width": width, "length": "5",
            "expected_revision": expected, "pricing": {"unit_cost_net": cost, "cost_markup": "0.20", "trial_tax_rate": "0.05"}, **extra}, "editor")

    def test_41_spatial_deduction_quantity_quote_and_package_share_real_ids(self):
        import csv
        item = self.spatial(deductions=[{"deduction_id": "opening", "x": "1", "y": "1", "width": "2", "length": "2"}])
        self.assertEqual((item["area_m2"], item["quote"]["result"]["sale_gross"]), ("46.00", "5796.00"))
        self.assertEqual(len(item["artifacts"]), 6)
        content = {}
        for artifact in item["artifacts"]:
            metadata, path = self.api.get_spatial_artifact(self.org, self.project, artifact["artifact_id"])
            content[artifact["artifact_kind"]] = path.read_bytes()
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), metadata["sha256"])
        manifest = json.loads(content["manifest_json"])
        row = next(csv.DictReader(io.StringIO(content["quantity_csv"].decode("utf-8-sig"))))
        self.assertEqual((manifest["quantity_item_id"], row["quantity_item_id"]), (item["quantity_items"][0]["quantity_item_id"],) * 2)
        with zipfile.ZipFile(io.BytesIO(content["package_zip"])) as archive:
            self.assertEqual(len(archive.namelist()), 5)
        self.assertEqual(list(self.root.rglob("*.sqlite3")), [])

    def test_42_spatial_price_revision_revert_noop_unknown_and_zero(self):
        first = self.spatial()
        old = {a["artifact_id"]: self.api.get_spatial_artifact(self.org, self.project, a["artifact_id"])[1].read_bytes() for a in first["artifacts"]}
        self.assertEqual(self.spatial(1, cost="200")["quote"]["result"]["sale_gross"], "12600.00")
        self.spatial(2, width="12", cost="200")
        back = self.spatial(3, cost="100")
        self.assertEqual((back["revision_no"], back["width"]), (4, "10"))
        self.assertEqual(self.spatial(4)["geometry_revision_id"], back["geometry_revision_id"])
        self.assertIsNone(self.spatial(4, cost=None)["quote"]["result"]["sale_gross"])
        self.assertEqual(self.spatial(5, cost="0")["quote"]["result"]["sale_gross"], "0.00")
        for artifact, data in old.items():
            self.assertEqual(self.api.get_spatial_artifact(self.org, self.project, artifact)[1].read_bytes(), data)

    def test_43_spatial_late_artifact_failure_rollback_and_concurrent_cas(self):
        from rkd_mvp.spatial_repository import PostgresSpatialTransaction
        first = self.spatial()
        original = PostgresSpatialTransaction.query
        calls = []
        def failure(tx, operation, params=()):
            if operation == "insert_artifact":
                calls.append(1)
                if len(calls) == 2:
                    tx.db.execute("SELECT 1/0")
            return original(tx, operation, params)
        with patch.object(PostgresSpatialTransaction, "query", failure):
            with self.assertRaises(psycopg.Error):
                self.spatial(1, width="12")
        self.assertEqual(self.api.get_spatial_model(self.org, self.project)["items"][0], first)
        def change(cost):
            try:
                return self.spatial(1, cost=cost)
            except ApiError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(change, ("200", "300")))
        self.assertEqual(sum(isinstance(row, dict) for row in results), 1)
        self.assertIn("STALE_GEOMETRY_REVISION", results)
        with self.store.tenant_transaction(TenantContext(self.org, self.project, "test")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM rkd.geometry_revision").fetchone()[0], 2)

    def test_44_spatial_default_scope_legacy_id_and_artifact_tamper(self):
        first = self.spatial()
        metadata, path = self.api.get_spatial_artifact(self.org, self.project, first["artifacts"][0]["artifact_id"])
        original_org = self.org
        self.org = "other-" + uuid4().hex
        self.api.create_project(self.org, "Same project", self.project)
        other = self.spatial()
        self.assertNotEqual(first["spatial_unit_id"], other["spatial_unit_id"])
        with self.assertRaises(ApiError) as error:
            self.api.get_spatial_artifact(self.org, self.project, metadata["artifact_id"])
        self.assertEqual(error.exception.status, 404)
        with self.assertRaises(ApiError) as error:
            self.spatial(spatial_unit_id=first["spatial_unit_id"])
        self.assertEqual(error.exception.code, "SPATIAL_ID_UNAVAILABLE")
        path.write_bytes(b"X" * metadata["size_bytes"])
        with self.assertRaises(ApiError) as error:
            self.api.get_spatial_artifact(original_org, self.project, metadata["artifact_id"])
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")
        self.project = "legacy-" + uuid4().hex
        self.api.create_project(self.org, "Legacy", self.project)
        legacy = self.spatial(spatial_unit_id=f"space-{self.project}-test-floor")
        self.assertEqual(self.spatial(1)["geometry_revision_id"], legacy["geometry_revision_id"])

    def test_45_spatial_checks_and_change_baseline_remain_unapproved(self):
        with self.assertRaises(ApiError) as error:
            self.spatial(deductions=[{"x": "9", "y": "0", "width": "2", "length": "1"}])
        self.assertEqual(error.exception.code, "DEDUCTION_OUT_OF_BOUNDS")
        item = self.spatial()
        change = self.api.create_change(self.org, self.project, "editor", {"title": "Geometry review", "reason": "Test",
            "description": "Keep current parameter baseline", "geometry_revision_id": item["geometry_revision_id"]}, "pg-spatial-change-create-0001")
        self.assertEqual(change["baseline"]["geometry_area_m2"], "50.00")
        change = self.api.analyze_change(self.org, self.project, change["change_id"], "editor", {"expected_version": change["version"]}, "pg-spatial-change-analyze-0001")
        self.assertEqual(change["impact"]["affected_artifact_count"], 6)
        self.assertEqual(change["impact"]["approval_status"], "not_approved")
