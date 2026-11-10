from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from http.client import HTTPConnection
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiService, ApiError
from rkd_mvp.design_rules import DEFAULT_PROGRAM
from rkd_mvp.engine import MVPApp
from rkd_mvp.sqlite_store import SQLiteStore


class ChangeReproductionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.store = SQLiteStore(self.root / "app.sqlite3")
        self.api = ApiService(MVPApp(self.store))
        self.api.create_project("org-local", "Change reproduction", "change-test")
        self.api.create_requirement_draft("org-local", "change-test", "test", {})
        self.api.update_requirement("org-local", "change-test", "test", {"expected_revision": 1,
            "design_program": DEFAULT_PROGRAM, "change_reason": "test model", "design_notes": "source test"})
        self.api.create_design("org-local", "change-test", "test", {"expected_revision": 0,
            "requirement_revision_no": 2, "change_reason": "base design"})
        self.api.save_production_settings("org-local", "change-test", "test", {"expected_version": 0,
            "expected_design_revision": 1, "settings": {"unit_cost_net": "100", "material_specification": "Floor",
                "supplier_name": "Supplier", "delivery_location": "Site"}})
        self.before = self.api.get_production("org-local", "change-test")["item"]

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def create(self, key="change-create-key-0001", width="16"):
        program = deepcopy(DEFAULT_PROGRAM)
        program["width"] = width
        return self.api.create_change("org-local", "change-test", "editor", {"title": "Widen room", "reason": "Updated boundary",
            "description": "Regenerate layout from new requirement width", "design_program": program,
            "quantity_delta_m2": "999", "cost_delta_net": "999999"}, key)

    def analyze(self, change):
        return self.api.analyze_change("org-local", "change-test", change["change_id"], "editor",
            {"expected_version": change["version"]}, "change-analyze-key-0001")

    def accept(self, change):
        return self.api.accept_change("org-local", "change-test", change["change_id"], "manager",
            {"expected_version": change["version"], "conclusion": "accepted", "checklist": ["Computed model and price reviewed"],
             "evidence_ref": "local://review", "note": "Draft only"}, "change-accept-key-0001")

    def apply(self, change, key="change-reproduce-key-0001"):
        return self.api.reproduce_change("org-local", "change-test", change["change_id"], "manager",
                                         {"expected_version": change["version"]}, key)

    def test_preview_computes_real_deltas_and_preserves_models_until_applied(self):
        change = self.analyze(self.create())
        self.assertEqual(change["impact"]["calculation_status"], "computed_from_candidate_model")
        self.assertEqual(change["impact"]["quantity_delta_m2"], "26.0000")
        self.assertEqual(change["impact"]["cost_delta_net"], "2600.00")
        self.assertEqual(change["impact"]["quote_after"]["sale_gross"], "13104.00")
        self.assertEqual(self.api.get_production("org-local", "change-test")["item"], self.before)
        self.assertEqual(change["impact"]["preview"]["status"], "candidate_not_saved")
        self.assertTrue(all(q["quantity_item_id"] is None for q in change["impact"]["preview"]["quantities"]))
        self.assertEqual(len(change["artifacts"]), 3)

    def test_accepted_change_reproduces_shared_model_quote_order_and_replays_once(self):
        old = {a["artifact_id"]: self.api.get_production_artifact("org-local", "change-test", a["artifact_id"])[1].read_bytes() for a in self.before["artifacts"]}
        accepted = self.accept(self.analyze(self.create()))
        result = self.apply(accepted)
        reproduction = result["impact"]["reproduction"]
        self.assertEqual((reproduction["requirement_revision_no"], reproduction["design_revision_no"], reproduction["production_revision_no"]), (3, 2, 3))
        self.assertEqual((reproduction["accepted_by"], reproduction["applied_by"], reproduction["status"]), ("manager", "manager", "draft_not_published"))
        latest = self.api.get_production("org-local", "change-test")["item"]
        self.assertEqual((latest["quote"]["quantity"], latest["quote"]["sale_gross"]), ("104.0000", "13104.00"))
        order = self.api.get_procurement_order("org-local", "change-test", latest["procurement"]["order_id"])
        self.assertEqual(order["source_ref"], latest["production_revision_id"])
        self.assertEqual(self.apply(accepted), result)
        for artifact, data in old.items():
            self.assertEqual(self.api.get_production_artifact("org-local", "change-test", artifact)[1].read_bytes(), data)
        self.store.close()
        self.store = SQLiteStore(self.root / "app.sqlite3")
        self.api = ApiService(MVPApp(self.store))
        self.assertEqual(self.api.get_change("org-local", "change-test", result["change_id"]), result)
        self.assertEqual(self.api.get_production("org-local", "change-test")["item"], latest)

    def test_changed_price_after_acceptance_rejects_application(self):
        accepted = self.accept(self.analyze(self.create()))
        self.api.save_production_settings("org-local", "change-test", "test", {"expected_version": 1,
            "expected_design_revision": 1, "settings": {"unit_cost_net": "200"}})
        with self.assertRaises(ApiError) as error:
            self.apply(accepted)
        self.assertEqual(error.exception.code, "CHANGE_SOURCE_OUTDATED")
        self.assertEqual(self.api.get_requirement("org-local", "change-test")["item"]["revision_no"], 2)
        self.assertNotIn("reproduction", self.api.get_change("org-local", "change-test", accepted["change_id"])["impact"])

    def test_changed_requirement_rejects_acceptance_of_old_preview(self):
        analyzed = self.analyze(self.create())
        program = deepcopy(DEFAULT_PROGRAM)
        program["length"] = "10"
        self.api.update_requirement("org-local", "change-test", "test", {"expected_revision": 2,
            "design_program": program, "change_reason": "different source"})
        with self.assertRaises(ApiError) as error:
            self.accept(analyzed)
        self.assertEqual(error.exception.code, "CHANGE_SOURCE_OUTDATED")

    def test_generation_failure_rolls_back_requirement_design_orders_and_change(self):
        accepted = self.accept(self.analyze(self.create()))
        with patch("rkd_mvp.production_service.generate_production_outputs", side_effect=OSError("injected failure")):
            with self.assertRaises(OSError):
                self.apply(accepted)
        self.assertEqual(self.api.get_production("org-local", "change-test")["item"], self.before)
        self.assertEqual(self.api.get_requirement("org-local", "change-test")["item"]["revision_no"], 2)
        self.assertEqual(self.api.get_change("org-local", "change-test", accepted["change_id"]), accepted)
        self.assertEqual(len(self.api.list_procurement_orders("org-local", "change-test")["items"]), 1)
        self.assertIn("reproduction", self.apply(accepted)["impact"])

    def test_unaccepted_legacy_and_no_model_change_cannot_reproduce(self):
        draft = self.create()
        with self.assertRaises(ApiError) as error:
            self.apply(draft)
        self.assertEqual(error.exception.code, "REPRODUCTION_NOT_READY")
        same = self.create(key="same-program-key-0001", width="12")
        with self.assertRaises(ApiError) as error:
            self.analyze(same)
        self.assertEqual(error.exception.code, "NO_MODEL_CHANGE")
        self.assertEqual(self.api.get_production("org-local", "change-test")["item"], self.before)

    def test_parallel_reproduction_replays_only_one_production(self):
        accepted = self.accept(self.analyze(self.create()))
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(lambda _: self.apply(accepted), range(2)))
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(len(self.api.get_production("org-local", "change-test")["revisions"]), 3)
        self.assertEqual(len(self.api.list_procurement_orders("org-local", "change-test")["items"]), 2)

    def test_unknown_cost_delta_stays_unknown(self):
        self.api.save_production_settings("org-local", "change-test", "test", {"expected_version": 1,
            "expected_design_revision": 1, "settings": {"unit_cost_net": None}})
        analyzed = self.analyze(self.create())
        self.assertIsNone(analyzed["impact"]["cost_delta_net"])
        self.assertIsNone(analyzed["impact"]["quote_after"]["sale_gross"])
        self.assertIn("reproduction", self.apply(self.accept(analyzed))["impact"])

    def test_real_http_reproduction_route_uses_server_actor(self):
        accepted = self.accept(self.analyze(self.create()))
        server = create_server(self.api, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=15)
            path = f"/api/v1/projects/change-test/changes/{accepted['change_id']}/reproduce"
            connection.request("POST", path, json.dumps({"expected_version": accepted["version"], "actor_id": "forged"}),
                {"Content-Type": "application/json", "X-Organization-Id": "org-local", "X-Actor-Id": "test-manager", "Idempotency-Key": "http-change-reproduce-0001"})
            response = connection.getresponse()
            result = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 201)
            self.assertEqual(result["impact"]["reproduction"]["applied_by"], "test-manager")
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)
