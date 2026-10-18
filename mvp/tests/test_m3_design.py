from copy import deepcopy
import csv
import hashlib
from http.client import HTTPConnection
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from jsonschema import Draft202012Validator

from rkd_mvp.api_server import create_server
from rkd_mvp.api_service import ApiService, ApiError
from rkd_mvp.design_rules import DEFAULT_PROGRAM, generate_model, normalize_program
from rkd_mvp.engine import MVPApp
from rkd_mvp.sqlite_store import SQLiteStore


class M3DesignTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.directory.name) / "app.sqlite3"
        self.store = SQLiteStore(self.db_path)
        self.service = ApiService(MVPApp(self.store))
        self.service.create_project("org-local", "M3 展厅测试", "m3-test")
        self.service.create_project("org-local", "另一个测试项目", "m3-other")
        self.service.create_requirement_draft("org-local", "m3-test", "tester", {})
        self.req = self.update_requirement(deepcopy(DEFAULT_PROGRAM), 1)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def update_requirement(self, program, expected):
        return self.service.update_requirement("org-local", "m3-test", "tester", {"expected_revision": expected, "design_program": program, "design_notes": "测试设计需求", "change_reason": "测试保存需求"})["item"]

    def generate(self, expected=0, model=None):
        return self.service.create_design("org-local", "m3-test", "tester", {"expected_revision": expected, "requirement_revision_no": self.req["revision_no"], "change_reason": "测试生成或修订布局", **({"model": model} if model is not None else {})})["item"]

    def test_design_chain_area_source_ids_and_package_consistency(self):
        design = self.generate()
        schema = json.loads((Path(__file__).resolve().parents[2] / "contracts/v1/showroom-design.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(design)
        model = design["model"]
        self.assertEqual(model["total_area_m2"], "96.00")
        self.assertEqual(model["zone_area_m2"], "78.00")
        self.assertEqual(model["aisle_area_m2"], "18.00")
        self.assertEqual([z["area_m2"] for z in model["zones"]], ["19.50", "39.00", "19.50"])
        self.assertEqual(design["requirement_hash"], self.req["input_hash"])
        self.assertEqual(len(design["artifacts"]), 7)
        self.assertEqual(design["validation"]["publication_status"], "not_approved")
        self.assertTrue(all(c["status"] == "unknown" for c in design["validation"]["professional_checks"]))
        for a in design["artifacts"]:
            meta, path = self.service.get_design_artifact("org-local", "m3-test", a["artifact_id"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), meta["sha256"])
        package = next(a for a in design["artifacts"] if a["artifact_kind"] == "package_zip")
        path = self.service.get_design_artifact("org-local", "m3-test", package["artifact_id"])[1]
        with zipfile.ZipFile(path) as archive:
            snapshot = json.loads(archive.read("model-v1.json"))
            manifest = json.loads(archive.read("manifest-v1.json"))
            self.assertEqual(snapshot["baseline"]["design_revision_id"], design["design_revision_id"])
            self.assertEqual(snapshot["model"], model)
            for entry in manifest["files"]:
                self.assertEqual(hashlib.sha256(archive.read(entry["filename"])).hexdigest(), entry["sha256"])
            csv_rows = list(csv.DictReader(io.StringIO(archive.read("zones-v1.csv").decode("utf-8-sig"))))
            self.assertEqual([r["area"] for r in csv_rows], ["19.50", "39.00", "19.50"])
            self.assertIn("TEST / DESIGN DRAFT", archive.read("layout-v1.svg").decode())
            self.assertIn(b"NOT FOR CONSTRUCTION", archive.read("layout-v1.dxf"))

    def test_manual_layout_edit_propagates_to_area_and_preserves_old_files(self):
        first = self.generate()
        model = deepcopy(first["model"])
        model["zones"][0]["width"] = "2"
        second = self.generate(1, model)
        self.assertEqual(second["source_kind"], "manual_layout_edit")
        self.assertEqual(second["model"]["zones"][0]["area_m2"], "13.00")
        self.assertEqual(second["model"]["unassigned_area_m2"], "6.50")
        old = self.service.get_design("org-local", "m3-test", 1)["item"]
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(self.service.get_design("org-local", "m3-test")["item"]["status"], "draft")
        self.assertTrue(self.service.get_design_artifact("org-local", "m3-test", old["artifacts"][0]["artifact_id"])[1].is_file())

    def test_requirement_changes_invalidate_design_and_regenerate(self):
        first = self.generate()
        program = deepcopy(DEFAULT_PROGRAM)
        program["width"] = "16"
        self.req = self.update_requirement(program, self.req["revision_no"])
        self.assertEqual(self.service.get_design("org-local", "m3-test")["item"]["status"], "source_outdated")
        second = self.generate(1)
        self.assertEqual(second["model"]["zone_area_m2"], "104.00")
        self.assertEqual([z["zone_id"] for z in second["model"]["zones"]], [z["zone_id"] for z in first["model"]["zones"]])

    def test_regeneration_does_not_overwrite_edited_requirement(self):
        repeated = self.service.create_requirement_draft("org-local", "m3-test", "tester", {})["item"]
        self.assertEqual(repeated["input_hash"], self.req["input_hash"])
        self.assertEqual(repeated["content"]["design_notes"], "测试设计需求")

    def test_invalid_layouts_rejected_without_revision_or_partial_files(self):
        first = self.generate()
        cases = [("x", "11", "ZONE_OUT_OF_BOUNDS"), ("width", "4", "ZONE_OVERLAP"), ("y", "0", "AISLE_BLOCKED"), ("width", "1", "ZONE_AREA_TOO_SMALL")]
        for field, value, code in cases:
            with self.subTest(code=code):
                model = deepcopy(first["model"])
                model["zones"][0][field] = value
                with self.assertRaises(ApiError) as error:
                    self.generate(1, model)
                self.assertEqual(error.exception.code, code)
        self.assertEqual(len(self.service.get_design("org-local", "m3-test")["revisions"]), 1)

    def test_area_capacity_and_duplicate_ids_rejected(self):
        program = deepcopy(DEFAULT_PROGRAM)
        program["zones"][0]["min_area_m2"] = "100"
        self.req = self.update_requirement(program, self.req["revision_no"])
        with self.assertRaises(ApiError) as error:
            self.generate()
        self.assertEqual(error.exception.code, "INSUFFICIENT_LAYOUT_AREA")
        self.assertIsNone(self.service.get_design("org-local", "m3-test")["item"])
        program["zones"][1]["zone_id"] = program["zones"][0]["zone_id"]
        with self.assertRaises(ApiError) as error:
            self.update_requirement(program, self.req["revision_no"])
        self.assertEqual(error.exception.code, "DUPLICATE_ZONE_ID")

    def test_stale_writes_and_project_scope_are_enforced(self):
        design = self.generate()
        with self.assertRaises(ApiError) as error:
            self.generate(0)
        self.assertEqual(error.exception.code, "STALE_DESIGN_REVISION")
        with self.assertRaises(ApiError) as error:
            self.update_requirement(DEFAULT_PROGRAM, 1)
        self.assertEqual(error.exception.code, "STALE_REQUIREMENT_REVISION")
        for org, project in [("other-org", "m3-test"), ("org-local", "m3-other")]:
            with self.assertRaises(ApiError):
                self.service.get_design_artifact(org, project, design["artifacts"][0]["artifact_id"])

    def test_identical_request_reuses_revision_and_storage_survives_reload(self):
        first = self.generate()
        second = self.generate(1)
        self.assertEqual(second["design_revision_id"], first["design_revision_id"])
        restored = ApiService(MVPApp(self.store))
        self.assertEqual(restored.get_design("org-local", "m3-test")["item"], self.service.get_design("org-local", "m3-test")["item"])

    def test_output_generation_failure_rolls_back_database_and_new_files(self):
        with patch("rkd_mvp.design_service.generate_design_outputs", side_effect=OSError("Injected output failure")):
            with self.assertRaises(OSError):
                self.generate()
        self.assertIsNone(self.service.get_design("org-local", "m3-test")["item"])
        self.assertEqual(list(Path(self.directory.name).rglob("layout-*.svg")), [])

    def test_http_download_bytes_and_restart(self):
        design = self.generate()
        for _ in range(2):
            server = create_server(ApiService(MVPApp(self.store)), port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                c = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                c.request("GET", "/api/v1/projects/m3-test/design", headers={"X-Organization-Id": "org-local"})
                response = c.getresponse()
                self.assertEqual(response.status, 200)
                item = json.loads(response.read())["item"]
                self.assertEqual(item["design_revision_id"], design["design_revision_id"])
                artifact = item["artifacts"][0]
                c.request("GET", artifact["download_url"], headers={"X-Organization-Id": "org-local"})
                response = c.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(hashlib.sha256(response.read()).hexdigest(), artifact["sha256"])
                c.close()
            finally:
                server.shutdown(); server.server_close(); thread.join(2)

    def test_millimetre_rounding_never_shrinks_below_required_area(self):
        program = deepcopy(DEFAULT_PROGRAM)
        program.update(width="1", length="4", aisle_width="1")
        program["zones"] = [{"zone_id": "a", "name": "A", "min_area_m2": "1"}, {"zone_id": "b", "name": "B", "min_area_m2": "1.99"}]
        model = generate_model(normalize_program(program))
        self.assertEqual(model["zones"][0]["width"], "0.334")
        self.assertEqual(model["zones"][1]["width"], "0.666")
        self.assertEqual(model["unassigned_area_m2"], "0.00")

    def test_artifact_tampering_is_detected(self):
        design = self.generate()
        a = design["artifacts"][0]
        path = self.service.get_design_artifact("org-local", "m3-test", a["artifact_id"])[1]
        path.write_bytes(b"changed")
        with self.assertRaises(ApiError) as error:
            self.service.get_design_artifact("org-local", "m3-test", a["artifact_id"])
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")


if __name__ == "__main__":
    unittest.main()
