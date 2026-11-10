from contextlib import closing
from copy import deepcopy
from decimal import Decimal
import csv
import hashlib
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from rkd_mvp.api_service import ApiError, ApiService
from rkd_mvp.api_server import create_server
from rkd_mvp.design_rules import DEFAULT_PROGRAM
from rkd_mvp.engine import MVPApp
from rkd_mvp.sqlite_store import SQLiteStore


class ProductionChainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "app.sqlite3"
        self.store = SQLiteStore(self.database)
        self.service = ApiService(MVPApp(self.store))
        self.service.create_project("org-local", "生产链测试展厅", "chain")
        self.service.create_project("org-local", "另一个项目", "other")
        self.service.create_requirement_draft("org-local", "chain", "tester", {})
        self.requirement = self.save_requirement(DEFAULT_PROGRAM, 1)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def save_requirement(self, program, expected):
        return self.service.update_requirement("org-local", "chain", "tester", {"expected_revision": expected, "design_program": deepcopy(program), "change_reason": "生产链测试"})["item"]

    def design(self, expected=0, model=None):
        return self.service.create_design("org-local", "chain", "tester", {"expected_revision": expected, "requirement_revision_no": self.requirement["revision_no"], "change_reason": "保存生产模型", **({"model": model} if model else {})})["item"]

    def production(self, revision=None):
        return self.service.get_production("org-local", "chain", revision)

    def settings(self, **changes):
        current = self.production()
        version, values = current["settings"]["version"], dict(current["settings"])
        values.update(changes)
        design = self.service.get_design("org-local", "chain")["item"]
        return self.service.save_production_settings("org-local", "chain", "tester", {"expected_version": version, "expected_design_revision": design["revision_no"] if design else 0, "settings": values})

    def configured(self):
        return self.settings(unit_cost_net="100", source_label="明确标记的测试成本", material_specification="测试地坪规格", supplier_name="测试供应商", delivery_location="测试现场")

    def test_design_creates_same_source_quantities_with_unknown_cost_and_procurement(self):
        design = self.design()
        item = self.production()["item"]
        self.assertEqual(item["baseline"]["design_revision_id"], design["design_revision_id"])
        self.assertEqual([q["object_id"] for q in item["quantities"]], ["zone:reception", "zone:display", "zone:discussion"])
        self.assertEqual(item["quote"]["quantity"], "78.0000")
        self.assertIsNone(item["quote"]["sale_gross"])
        self.assertIsNone(item["procurement"]["supplier_name"])
        self.assertEqual(item["procurement"]["status"], "awaiting_details")
        self.assertEqual(len(item["artifacts"]), 8)
        self.assertEqual(self.service.list_procurement_orders("org-local", "chain")["items"], [])

    def test_pre_review_missing_cost_stale_and_tampered_artifacts(self):
        from rkd_mvp.review_readiness import assess
        empty = assess(self.service, 'org-local', 'chain')
        self.assertFalse(empty['engineering_checks_passed'])
        self.design()
        unknown = assess(self.service, 'org-local', 'chain')
        self.assertFalse(unknown['engineering_checks_passed'])
        self.configured()
        report = assess(self.service, 'org-local', 'chain')
        self.assertTrue(report['engineering_checks_passed'])
        self.assertFalse(report['formal_release_allowed'])
        self.assertEqual(len(report['artifacts']), 8)
        self.assertEqual(report['evidence_sha256'], assess(self.service, 'org-local', 'chain')['evidence_sha256'])
        artifact = self.production()['item']['artifacts'][0]
        _, path = self.service.get_production_artifact('org-local', 'chain', artifact['artifact_id'])
        data = path.read_bytes(); path.write_bytes(b'X' * len(data))
        self.assertFalse(assess(self.service, 'org-local', 'chain')['engineering_checks_passed'])
        path.write_bytes(data)
        self.save_requirement({**DEFAULT_PROGRAM, 'width': '16'}, self.requirement['revision_no'])
        self.assertFalse(assess(self.service, 'org-local', 'chain')['engineering_checks_passed'])
        with self.assertRaises(ApiError):
            assess(self.service, 'other-org', 'chain')

    def test_model_change_propagates_to_boq_quote_order_and_immutable_files(self):
        self.configured()
        self.design()
        first = self.production()["item"]
        old_files = {a["artifact_id"]: self.service.get_production_artifact("org-local", "chain", a["artifact_id"])[1].read_bytes() for a in first["artifacts"]}
        self.assertEqual(first["quote"]["sale_gross"], "9828.00")
        program = deepcopy(DEFAULT_PROGRAM)
        program["width"] = "16"
        self.requirement = self.save_requirement(program, self.requirement["revision_no"])
        self.assertEqual(self.production()["item"]["status"], "source_outdated")
        self.design(1)
        current = self.production()["item"]
        self.assertEqual((current["quote"]["quantity"], current["quote"]["sale_gross"]), ("104.0000", "13104.00"))
        order = self.service.get_procurement_order("org-local", "chain", current["procurement"]["order_id"])
        self.assertEqual(sum(Decimal(q["ordered_quantity"]) for q in order["lines"]), Decimal("104"))
        self.assertEqual([q["item_code"] for q in order["lines"]], [q["quantity_item_id"] for q in current["quantities"]])
        self.assertFalse(order["external_effects_enabled"])
        self.assertEqual(self.production(1)["item"]["status"], "superseded")
        for identifier, data in old_files.items():
            self.assertEqual(self.service.get_production_artifact("org-local", "chain", identifier)[1].read_bytes(), data)

    def test_manual_zone_edit_and_optional_aisle_do_not_double_count_unassigned_area(self):
        design = self.design()
        model = deepcopy(design["model"])
        model["zones"][0]["width"] = "2"
        self.design(1, model)
        self.assertEqual(self.production()["item"]["quote"]["quantity"], "71.5000")
        result = self.settings(include_aisle=True)
        self.assertEqual(result["item"]["quote"]["quantity"], "89.5000")
        self.assertEqual(result["item"]["quantities"][-1]["object_id"], "aisle:main")

    def test_price_changes_zero_unknown_and_current_noop_preserve_history(self):
        self.design()
        first = self.settings(unit_cost_net="100")["item"]
        second = self.settings(unit_cost_net="200")["item"]
        self.assertEqual(second["quote"]["sale_gross"], "19656.00")
        self.assertEqual(second["design_revision_id"], first["design_revision_id"])
        repeated = self.settings(unit_cost_net="200")["item"]
        self.assertEqual(repeated["production_revision_id"], second["production_revision_id"])
        self.assertEqual(self.settings(unit_cost_net="0")["item"]["quote"]["sale_gross"], "0.00")
        self.assertIsNone(self.settings(unit_cost_net=None)["item"]["quote"]["sale_gross"])
        self.assertEqual(self.production(first["revision_no"])["item"]["quote"]["sale_gross"], "9828.00")

    def test_duplicate_design_does_not_duplicate_production_or_orders(self):
        self.configured()
        self.design()
        first = self.production()["item"]
        self.design(1)
        self.assertEqual(self.production()["item"]["production_revision_id"], first["production_revision_id"])
        self.assertEqual(len(self.service.list_procurement_orders("org-local", "chain")["items"]), 1)

    def test_package_references_real_stored_quantities_and_same_design_drawings(self):
        design = self.design()
        production = self.production()["item"]
        artifact = next(a for a in production["artifacts"] if a["artifact_kind"] == "package_zip")
        path = self.service.get_production_artifact("org-local", "chain", artifact["artifact_id"])[1]
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest-v1.json"))
            quantities = list(csv.DictReader(io.StringIO(archive.read("boq-v1.csv").decode("utf-8-sig"))))
            self.assertEqual(manifest["quantity_item_ids"], [q["quantity_item_id"] for q in production["quantities"]])
            self.assertEqual([q["quantity_item_id"] for q in quantities], manifest["quantity_item_ids"])
            self.assertTrue(all(q["design_revision_id"] == design["design_revision_id"] for q in quantities))
            for item in manifest["files"]:
                self.assertEqual(hashlib.sha256(archive.read(item["filename"])).hexdigest(), item["sha256"])
            for item in design["artifacts"]:
                if item["artifact_kind"] in {"layout_svg", "layout_dxf"}:
                    source = self.service.get_design_artifact("org-local", "chain", item["artifact_id"])[1]
                    self.assertEqual(archive.read("design-" + item["filename"]), source.read_bytes())

    def test_generation_failure_rolls_back_design_order_settings_and_production(self):
        self.configured()
        with patch("rkd_mvp.production_service.generate_production_outputs", side_effect=OSError("injected failure")):
            with self.assertRaises(OSError):
                self.design()
        self.assertIsNone(self.production()["item"])
        self.assertIsNone(self.service.get_design("org-local", "chain")["item"])
        self.assertEqual(self.service.list_procurement_orders("org-local", "chain")["items"], [])
        self.design()
        before = self.production()
        with patch("rkd_mvp.production_service.generate_production_outputs", side_effect=OSError("settings failure")):
            with self.assertRaises(OSError):
                self.settings(unit_cost_net="200")
        self.assertEqual(self.production(), before)

    def test_stale_settings_design_scope_and_artifact_tampering_rejected(self):
        self.design()
        self.settings(unit_cost_net="100")
        with self.assertRaises(ApiError) as error:
            self.service.save_production_settings("org-local", "chain", "tester", {"expected_version": 0, "settings": {}})
        self.assertEqual(error.exception.code, "STALE_PRODUCTION_SETTINGS")
        artifact = self.production()["item"]["artifacts"][0]
        with self.assertRaises(ApiError):
            self.service.get_production_artifact("org-local", "other", artifact["artifact_id"])
        path = self.service.get_production_artifact("org-local", "chain", artifact["artifact_id"])[1]
        path.write_bytes(b"tampered")
        with self.assertRaises(ApiError) as error:
            self.service.get_production_artifact("org-local", "chain", artifact["artifact_id"])
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")

    def test_old_order_rejects_receipt_and_existing_receipts_block_duplicate_order(self):
        self.configured()
        self.design()
        first = self.production()["item"]
        old_order = self.service.get_procurement_order("org-local", "chain", first["procurement"]["order_id"])
        second = self.settings(unit_cost_net="200")["item"]
        with self.assertRaises(ApiError) as error:
            self.service.receive_procurement("org-local", "chain", old_order["order_id"], "tester", {"receiver": "测试收货人", "evidence_ref": "test://receipt", "lines": [{"line_id": old_order["lines"][0]["line_id"], "quantity": "1"}]}, "old-receipt-attempt-key")
        self.assertEqual(error.exception.code, "ORDER_SOURCE_OUTDATED")
        order = self.service.get_procurement_order("org-local", "chain", second["procurement"]["order_id"])
        self.service.receive_procurement("org-local", "chain", order["order_id"], "tester", {"receiver": "测试收货人", "evidence_ref": "test://receipt", "lines": [{"line_id": order["lines"][0]["line_id"], "quantity": "1"}]}, "current-receipt-attempt-key")
        changed = self.settings(unit_cost_net="300")["item"]
        self.assertEqual(changed["procurement"]["status"], "requires_reconciliation")
        self.assertIsNone(changed["procurement"]["order_id"])
        self.assertEqual(len(self.service.list_procurement_orders("org-local", "chain")["items"]), 2)

    def test_restart_preserves_production_and_order_links(self):
        self.configured()
        self.design()
        before = self.production()
        self.store.close()
        self.store = SQLiteStore(self.database)
        self.service = ApiService(MVPApp(self.store))
        self.assertEqual(self.production(), before)

    def test_http_settings_patch_and_get_do_not_share_a_write_route(self):
        self.design()
        server = create_server(self.service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        try:
            connection.request("GET", "/api/v1/projects/chain/production/settings", headers={"X-Organization-Id": "org-local"})
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
            before = self.production()
            connection.request("PATCH", "/api/v1/projects/chain/production/settings", json.dumps({"expected_version": 0, "expected_design_revision": 1, "settings": {"unit_cost_net": "100"}}), {"Content-Type": "application/json", "X-Organization-Id": "org-local"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["item"]["quote"]["sale_gross"], "9828.00")
            self.assertEqual(before["settings"]["version"], 0)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__ == "__main__":
    unittest.main()
