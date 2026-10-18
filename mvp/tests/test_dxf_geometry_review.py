from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.dxf_geometry_review import DxfGeometryReviewBuilder


class DxfGeometryReviewTests(unittest.TestCase):
    def test_real_dxf_direct_geometry_is_compared_without_promotion(self):
        root = Path(__file__).parents[2]
        result = DxfGeometryReviewBuilder().build(
            root / "fixtures/ningbo-xiecheng/2026-09/source/04 平面PL.dxf",
            json.loads((root / "fixtures/ningbo-xiecheng/2026-09/derived/cad-plan-candidates.json").read_text(encoding="utf-8")),
            json.loads((root / "mvp/config/cad-layer-semantic-rules.v1.json").read_text(encoding="utf-8")),
            json.loads((root / "fixtures/ningbo-xiecheng/2026-09/derived/cad-plan-candidates.json").read_text(encoding="utf-8")),
        )
        self.assertEqual(result["status"], "geometry-review-created")
        self.assertGreater(result["summary"]["dxf_direct_entity_in_main_plan_count"], 0)
        self.assertGreater(result["summary"]["dxf_block_insertion_point_count"], 0)
        self.assertGreater(result["summary"]["dxf_expanded_block_point_count"], 0)
        self.assertIn("expanded", result["summary"]["dxf_block_expansion_status_counts"])
        self.assertEqual(result["summary"]["created_domain_object_count"], 0)
        self.assertEqual(result["summary"]["promotion_status"], "not-approved")
        self.assertTrue(any(item["status"] == "match" for item in result["category_comparison"]))

    def test_output_validates_against_contract(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema optional test dependency unavailable")
        root = Path(__file__).parents[2]
        result = DxfGeometryReviewBuilder().build(
            root / "fixtures/ningbo-xiecheng/2026-09/source/04 平面PL.dxf",
            json.loads((root / "fixtures/ningbo-xiecheng/2026-09/derived/cad-plan-candidates.json").read_text(encoding="utf-8")),
            json.loads((root / "mvp/config/cad-layer-semantic-rules.v1.json").read_text(encoding="utf-8")),
            json.loads((root / "fixtures/ningbo-xiecheng/2026-09/derived/cad-plan-candidates.json").read_text(encoding="utf-8")),
        )
        schema = json.loads((root / "contracts/v1/cad-secondary-geometry-review.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(result)


if __name__ == "__main__":
    unittest.main()
