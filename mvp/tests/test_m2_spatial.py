from decimal import Decimal
from contextlib import closing
import hashlib
import csv
import io
import json
import sqlite3
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

from rkd_mvp.api_service import ApiError, ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.spatial_service import SpatialService, SpatialServiceError
from rkd_mvp.sqlite_store import SQLiteStore


class M2SpatialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = SQLiteStore(root / "app.sqlite3")
        self.service = ApiService(MVPApp(self.store), spatial_service=SpatialService(root / "app.sqlite3"))
        self.service.create_project("org-local", "M2 测试项目", "project-m2")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_rectangle_with_deduction_creates_quantity(self):
        result = self.service.create_spatial_revision("org-local", "project-m2", {
            "width": "10", "length": "5", "deductions": [{"deduction_id": "opening-1", "x": "1", "y": "1", "width": "2", "length": "2"}],
            "expected_revision": 0, "pricing": {"unit_cost_net": "100", "cost_markup": "0.20", "trial_tax_rate": "0.05"},
        }, "test-user")
        self.assertEqual(result["revision_no"], 1)
        self.assertEqual(result["area_m2"], "46.00")
        self.assertEqual(result["quantity_items"][0]["quantity"], "46.00")
        self.assertEqual(result["quantity_items"][0]["unit"], "m²")
        self.assertEqual({item["artifact_kind"] for item in result["artifacts"]}, {"svg", "dxf", "quantity_csv", "quote_html", "manifest_json", "package_zip"})
        self.assertEqual(result["quote"]["result"]["sale_gross"], "5796.00")
        for artifact in result["artifacts"]:
            metadata, path = self.service.get_spatial_artifact("org-local", "project-m2", artifact["artifact_id"])
            content = path.read_bytes()
            self.assertEqual(metadata["size_bytes"], len(content))
            self.assertEqual(metadata["sha256"], hashlib.sha256(content).hexdigest())
        svg = next(item for item in result["artifacts"] if item["artifact_kind"] == "svg")
        self.assertIn(b"46.00", self.service.get_spatial_artifact("org-local", "project-m2", svg["artifact_id"])[1].read_bytes())

        changed = self.service.create_spatial_revision("org-local", "project-m2", {
            "spatial_unit_id": result["spatial_unit_id"], "width": "12", "length": "5", "deductions": result["deductions"], "expected_revision": 1, "pricing": {"unit_cost_net": "100", "cost_markup": "0.20", "trial_tax_rate": "0.05"},
        }, "test-user")
        self.assertEqual(changed["revision_no"], 2)
        self.assertEqual(changed["area_m2"], "56.00")
        self.assertEqual(len(changed["revisions"]), 2)
        self.assertEqual(len(changed["artifacts"]), 6)
        self.assertEqual(changed["quote"]["result"]["sale_gross"], "7056.00")
        old_artifacts = self.service.list_spatial_artifacts("org-local", "project-m2")["items"]
        self.assertEqual({item["status"] for item in old_artifacts if item["geometry_revision_id"] == result["geometry_revision_id"]}, {"superseded"})
        self.assertEqual({item["status"] for item in old_artifacts if item["geometry_revision_id"] == changed["geometry_revision_id"]}, {"draft"})

    def test_invalid_deduction_and_stale_revision_are_rejected(self):
        with self.assertRaises(ApiError) as error:
            self.service.create_spatial_revision("org-local", "project-m2", {"width": "10", "length": "5", "deductions": [{"x": "9", "y": "0", "width": "2", "length": "1"}]}, "test-user")
        self.assertEqual(error.exception.code, "DEDUCTION_OUT_OF_BOUNDS")
        created = self.service.create_spatial_revision("org-local", "project-m2", {"width": "10", "length": "5"}, "test-user")
        with self.assertRaises(ApiError) as error:
            self.service.create_spatial_revision("org-local", "project-m2", {"width": "12", "length": "5", "expected_revision": 0}, "test-user")
        self.assertEqual(error.exception.code, "STALE_GEOMETRY_REVISION")

    def save_floor(self, expected=0, width="10", cost="100", **extra):
        return self.service.create_spatial_revision("org-local", "project-m2", {
            "width": width, "length": "5", "expected_revision": expected,
            "pricing": {"unit_cost_net": cost, "cost_markup": "0.20", "trial_tax_rate": "0.05"},
            **extra,
        }, "audit-regression")

    def test_price_markup_tax_unknown_and_source_changes_create_revisions(self):
        first = self.save_floor()
        second = self.save_floor(1, cost="200")
        self.assertEqual(second["quote"]["result"]["sale_gross"], "12600.00")
        self.assertEqual(second["revision_no"], 2)
        self.assertNotEqual(first["quote"]["quote_revision_id"], second["quote"]["quote_revision_id"])
        for revision, pricing, expected in (
            (2, {"unit_cost_net": "200", "cost_markup": "0.30", "trial_tax_rate": "0.05"}, "13650.00"),
            (3, {"unit_cost_net": "200", "cost_markup": "0.30", "trial_tax_rate": "0.10"}, "14300.00"),
            (4, {"unit_cost_net": None}, None),
            (5, {"unit_cost_net": "0"}, "0.00"),
            (6, {"unit_cost_net": "0", "source_label": "明确的人工成本来源"}, "0.00"),
        ):
            with self.subTest(pricing=pricing):
                saved = self.save_floor(revision, pricing=pricing)
                self.assertEqual(saved["revision_no"], revision + 1)
                self.assertEqual(saved["quote"]["result"]["sale_gross"], expected)
        self.assertEqual(first["quote"]["result"]["sale_gross"], "6300.00")

    def test_revert_is_new_current_revision_and_current_noop_is_reused(self):
        self.save_floor()
        self.save_floor(1, width="12")
        reverted = self.save_floor(2)
        self.assertEqual(reverted["revision_no"], 3)
        self.assertEqual(reverted["width"], "10")
        self.assertEqual(self.save_floor(3)["geometry_revision_id"], reverted["geometry_revision_id"])
        self.store.close()
        restored = SQLiteStore(Path(self.directory.name) / "app.sqlite3")
        try:
            current = ApiService(MVPApp(restored)).spatial_service.get_model("org-local", "project-m2")["items"][0]
            self.assertEqual((current["revision_no"], current["width"], len(current["revisions"])), (3, "10", 3))
        finally:
            restored.close()

    def test_existing_geometry_only_hash_history_can_be_updated_without_rewriting_it(self):
        first = self.save_floor()
        legacy_hash = hashlib.sha256(b'legacy-geometry-only').hexdigest()
        with closing(sqlite3.connect(Path(self.directory.name) / "app.sqlite3")) as db, db:
            db.execute("UPDATE geometry_revisions SET input_hash=?", (legacy_hash,))
        self.assertEqual(self.save_floor(1)["input_hash"], legacy_hash)
        changed = self.save_floor(1, cost="200")
        self.assertEqual(changed["revision_no"], 2)
        with closing(sqlite3.connect(Path(self.directory.name) / "app.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT input_hash FROM geometry_revisions WHERE geometry_revision_id=?", (first["geometry_revision_id"],)).fetchone()[0], legacy_hash)

    def test_multiple_units_and_organizations_keep_distinct_immutable_files(self):
        first = self.save_floor(spatial_unit_id="room-a")
        snapshots = {}
        for artifact in first["artifacts"]:
            _, path = self.service.get_spatial_artifact("org-local", "project-m2", artifact["artifact_id"])
            snapshots[artifact["artifact_id"]] = (path, path.read_bytes())
        second = self.save_floor(width="8", spatial_unit_id="room-b")
        self.service.create_project("other-org", "同名项目", "project-m2")
        third = self.service.create_spatial_revision("other-org", "project-m2", {
            "width": "7", "length": "5", "expected_revision": 0,
            "spatial_unit_id": "room-c",
        }, "other-user")
        for artifact in first["artifacts"]:
            metadata, path = self.service.get_spatial_artifact("org-local", "project-m2", artifact["artifact_id"])
            self.assertEqual((path, path.read_bytes()), snapshots[artifact["artifact_id"]])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), metadata["sha256"])
        first_path = next(iter(snapshots.values()))[0].parent
        other_paths = [self.service.get_spatial_artifact(org, "project-m2", model["artifacts"][0]["artifact_id"])[1].parent
                       for org, model in (("org-local", second), ("other-org", third))]
        self.assertEqual(len({first_path, *other_paths}), 3)
        with self.assertRaises(ApiError) as error:
            self.service.get_spatial_artifact("other-org", "project-m2", first["artifacts"][0]["artifact_id"])
        self.assertEqual(error.exception.status, 404)

    def test_manifest_and_csv_quantity_ids_resolve_to_same_persisted_revision(self):
        saved = self.save_floor()
        data = {}
        for item in saved["artifacts"]:
            _, path = self.service.get_spatial_artifact("org-local", "project-m2", item["artifact_id"])
            data[item["artifact_kind"]] = path.read_bytes()
        manifest = json.loads(data["manifest_json"])
        row = next(csv.DictReader(io.StringIO(data["quantity_csv"].decode("utf-8-sig"))))
        quantity_id = saved["quantity_items"][0]["quantity_item_id"]
        self.assertEqual(manifest["quantity_item_id"], quantity_id)
        self.assertEqual(row["quantity_item_id"], quantity_id)
        with closing(sqlite3.connect(Path(self.directory.name) / "app.sqlite3")) as db:
            quantity = db.execute("SELECT geometry_revision_id,organization_id,project_id,quantity_text FROM quantity_items WHERE quantity_item_id=?", (quantity_id,)).fetchone()
        self.assertEqual(quantity, (saved["geometry_revision_id"], "org-local", "project-m2", "50.00"))

    def test_download_rejects_tampered_content_even_if_size_is_unchanged(self):
        saved = self.save_floor()
        item = saved["artifacts"][0]
        _, path = self.service.get_spatial_artifact("org-local", "project-m2", item["artifact_id"])
        original = path.read_bytes()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaises(ApiError) as error:
            self.service.get_spatial_artifact("org-local", "project-m2", item["artifact_id"])
        self.assertEqual(error.exception.code, "ARTIFACT_INTEGRITY")

    def test_file_generation_failure_rolls_back_and_retry_preserves_old_artifacts(self):
        first = self.save_floor()
        old = {a["artifact_id"]: self.service.get_spatial_artifact("org-local", "project-m2", a["artifact_id"])[1].read_bytes() for a in first["artifacts"]}
        with patch("rkd_mvp.spatial_service.generate_outputs", side_effect=RuntimeError("injected export failure")):
            with self.assertRaises(RuntimeError):
                self.save_floor(1, width="12")
        current = self.service.spatial_service.get_model("org-local", "project-m2")["items"][0]
        self.assertEqual((current["revision_no"], len(current["revisions"])), (1, 1))
        self.assertTrue(all(a["status"] == "draft" for a in current["artifacts"]))
        self.assertEqual(self.save_floor(1, width="12")["revision_no"], 2)
        for artifact_id, content in old.items():
            self.assertEqual(self.service.get_spatial_artifact("org-local", "project-m2", artifact_id)[1].read_bytes(), content)

    def test_default_ids_include_org_scope_and_legacy_default_remains_stable(self):
        first = self.save_floor()
        self.service.create_project("other-org", "Same project id", "project-m2")
        other = self.service.create_spatial_revision("other-org", "project-m2", {"width": "7", "length": "5"}, "test")
        self.assertNotEqual(first["spatial_unit_id"], other["spatial_unit_id"])
        with self.assertRaises(ApiError) as error:
            self.service.create_spatial_revision("other-org", "project-m2", {"width": "7", "length": "5", "spatial_unit_id": first["spatial_unit_id"]}, "test")
        self.assertEqual(error.exception.code, "SPATIAL_ID_UNAVAILABLE")
        self.service.create_project("org-local", "Legacy", "legacy")
        old = self.service.create_spatial_revision("org-local", "legacy", {"width": "10", "length": "5", "spatial_unit_id": "space-legacy-test-floor"}, "test")
        saved = self.service.create_spatial_revision("org-local", "legacy", {"width": "10", "length": "5", "expected_revision": 1}, "test")
        self.assertEqual((saved["spatial_unit_id"], saved["geometry_revision_id"]), (old["spatial_unit_id"], old["geometry_revision_id"]))


if __name__ == "__main__":
    unittest.main()
