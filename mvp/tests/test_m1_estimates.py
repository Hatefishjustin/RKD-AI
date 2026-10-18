from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from rkd_mvp.api_service import ApiService
from rkd_mvp.engine import MVPApp
from rkd_mvp.estimate_service import EstimateService, EstimateServiceError
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID
from rkd_mvp.sqlite_store import SQLiteStore


FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "ningbo-xiecheng" / "2026-09"


class M1EstimateServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.store = SQLiteStore(root / "app.sqlite3")
        self.files = FileService(root / "app.sqlite3", root)
        self.estimates = EstimateService(root / "app.sqlite3")
        self.service = ApiService(MVPApp(self.store), self.files, estimate_service=self.estimates)
        self.files.seed_ningbo(self.service, FIXTURE_ROOT)
        self.estimate = self.estimates.seed_ningbo("org-local", NINGBO_PROJECT_ID, FIXTURE_ROOT)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_source_import_reconciles_without_counting_summary_rows(self):
        result = self.estimate["calculation"]["result"]
        self.assertEqual(len(self.estimate["lines"]), 112)
        self.assertEqual(result["source_line_total_before_tax"], "616308.50")
        self.assertEqual(result["source_total_before_tax"], "616308.50")
        self.assertEqual(result["source_reconciliation_difference"], "0.00")
        self.assertNotIn("SOURCE_RECONCILIATION", {item["code"] for item in self.estimate["calculation"]["warnings"]})
        self.assertEqual(result["excluded_line_count"], 12)
        self.assertIsNone(result["design_cost_net"])
        self.assertIsNone(result["combined_gross_sale"])
        self.assertTrue(any(item["code"] == "DESIGN_COST_UNKNOWN" for item in self.estimate["calculation"]["warnings"]))
        self.assertTrue(all("小  计" not in line["name"] for line in self.estimate["lines"]))

    def test_line_edit_creates_revision_and_recalculates_with_decimal(self):
        line = next(item for item in self.estimate["lines"] if item["line_id"] == "xls-exhibition-r004")
        before = Decimal(self.estimate["calculation"]["result"]["included_construction_cost"])
        updated = self.estimates.update_line(
            "org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], line["line_id"],
            {"expected_revision": 1, "quantity": "7.5", "change_reason": "自动测试工程量修订"},
            "test-user",
        )
        changed = next(item for item in updated["lines"] if item["line_id"] == line["line_id"])
        self.assertEqual(updated["revision_no"], 2)
        self.assertEqual(changed["quantity"], "7.5")
        self.assertEqual(changed["current_cost"], "787.50")
        self.assertEqual(Decimal(updated["calculation"]["result"]["included_construction_cost"]), before + Decimal("157.50"))
        self.assertEqual(changed["source_quantity"], "6")
        with self.assertRaises(EstimateServiceError) as error:
            self.estimates.update_line(
                "org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"], line["line_id"],
                {"expected_revision": 1, "quantity": "8", "change_reason": "旧版写入"}, "test-user",
            )
        self.assertEqual(error.exception.code, "STALE_ESTIMATE_REVISION")

    def test_two_markups_and_tax_are_independently_recalculated(self):
        calculated = self.estimates.calculate(
            "org-local", NINGBO_PROJECT_ID, self.estimate["estimate_id"],
            {
                "expected_revision": 1,
                "trial_tax_rate": "0.05",
                "construction_cost_markup": "0.20",
                "design_cost_markup": "0.60",
                "design_cost_net": "1000",
                "change_reason": "自动测试试算参数",
            },
            "test-user",
        )
        result = calculated["calculation"]["result"]
        cost = Decimal(result["included_construction_cost"])
        self.assertEqual(Decimal(result["construction_net_sale"]), (cost * Decimal("1.20")).quantize(Decimal("0.01")))
        self.assertEqual(result["design_net_sale"], "1600.00")
        self.assertEqual(result["design_tax"], "80.00")
        self.assertEqual(result["design_gross_sale"], "1680.00")
        self.assertEqual(
            Decimal(result["combined_gross_sale"]),
            Decimal(result["construction_gross_sale"]) + Decimal("1680.00"),
        )
        self.assertEqual(result["contract_target_gross"], "600000.00")

    def test_project_scope_is_enforced(self):
        self.assertEqual(self.estimates.list_estimates("other-org", NINGBO_PROJECT_ID)["items"], [])
        with self.assertRaises(EstimateServiceError):
            self.estimates.get_estimate("other-org", NINGBO_PROJECT_ID, self.estimate["estimate_id"])


if __name__ == "__main__":
    unittest.main()
