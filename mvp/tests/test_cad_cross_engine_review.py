from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.cad_cross_engine_review import CadCrossEngineReviewBuilder


class CadCrossEngineReviewTests(unittest.TestCase):
    def build_real_review(self):
        root = Path(__file__).parents[2]
        return CadCrossEngineReviewBuilder().build(
            json.loads((root / "fixtures/ningbo-xiecheng/2026-09/derived/cad-secondary-geometry-review.json").read_text(encoding="utf-8")),
            json.loads((root / "fixtures/ningbo-xiecheng/2026-09/derived/cad-plan-candidates.json").read_text(encoding="utf-8")),
        )

    def test_matches_preserved_handles_and_expanded_blocks_without_approval(self):
        result = self.build_real_review()
        self.assertEqual(result["summary"]["common_handle_count"], 640)
        self.assertEqual(result["summary"]["matched_handle_count"], 640)
        self.assertEqual(result["summary"]["review_required_handle_count"], 0)
        self.assertEqual(result["summary"]["dxf_only_count"], 114)
        self.assertEqual(result["summary"]["dwg_only_count"], 191)
        self.assertEqual(result["summary"]["created_domain_object_count"], 0)
        self.assertEqual(result["summary"]["promotion_status"], "not-approved")
        block_matches = [item for item in result["matched_candidates"] if item["comparison_mode"] == "expanded-block-bounds"]
        self.assertEqual(len(block_matches), 70)
        self.assertTrue(all(item["maximum_bounds_delta_mm"] <= 0.01 for item in block_matches))

    def test_output_validates_against_contract(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema optional test dependency unavailable")
        root = Path(__file__).parents[2]
        schema = json.loads((root / "contracts/v1/cad-cross-engine-review.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(self.build_real_review())


if __name__ == "__main__":
    unittest.main()
