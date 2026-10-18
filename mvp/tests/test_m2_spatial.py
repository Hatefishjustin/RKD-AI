from decimal import Decimal
import hashlib
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


if __name__ == "__main__":
    unittest.main()
