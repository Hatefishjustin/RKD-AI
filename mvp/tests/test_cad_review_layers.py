from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.cad_review_layers import CadReviewLayerAnalyzer


class CadReviewLayerAnalyzerTests(unittest.TestCase):
    def test_places_direct_and_nested_review_entities_without_promoting_them(self):
        inspection = {
            "source_asset_id": "drawing-cad-01",
            "sha256": "A" * 64,
            "intake_status": "geometry-parsed",
            "geometry_metadata": {"layer_names": ["0", "REVIEW"]},
        }
        mapping = {
            "source_sha256": "A" * 64,
            "mapping_version": "test-v1",
            "layer_mappings": [{
                "layer_name": "REVIEW",
                "verification_status": "needs-system-review",
                "category": "drawing.external-reference",
                "scope_disposition": "evidence-only",
                "entity_count": 4,
                "reachable_entity_count": 3,
                "block_context_counts": {"model-reachable": 2, "paper-reachable": 1},
            }],
        }
        plan = {
            "source_sha256": "A" * 64,
            "profile_id": "plan-v1",
            "target_region": {"bounds": {"minimum": [0, 0], "maximum": [100, 100]}},
        }
        payload = {"OBJECTS": [
            {"object": "LAYER", "handle": [0, 1]},
            {"object": "LAYER", "handle": [0, 2]},
            {
                "object": "BLOCK_HEADER", "name": "*Model_Space", "handle": [0, 10],
                "entities": [[0, 20], [0, 21]],
            },
            {
                "object": "BLOCK_HEADER", "name": "PART", "handle": [0, 11],
                "base_pt": [0, 0, 0], "entities": [[0, 22]],
            },
            {
                "entity": "LINE", "handle": [0, 20], "layer": [0, 2],
                "start": [10, 10, 0], "end": [20, 10, 0],
            },
            {
                "entity": "INSERT", "handle": [0, 21], "layer": [0, 1],
                "ins_pt": [200, 200, 0], "block_header": [0, 11],
            },
            {
                "entity": "LINE", "handle": [0, 22], "layer": [0, 2],
                "start": [0, 0, 0], "end": [10, 0, 0],
            },
        ]}
        result = CadReviewLayerAnalyzer().analyze(payload, inspection, mapping, plan)
        layer = result["layers"][0]
        self.assertEqual(layer["model_reachable_unique_source_entity_count"], 2)
        self.assertEqual(layer["declared_paper_only_reachable_entity_count"], 1)
        self.assertEqual(layer["noninstantiated_model_source_entity_count"], 0)
        self.assertEqual(layer["primary_plan_instance_count"], 1)
        self.assertEqual(layer["outside_primary_plan_instance_count"], 1)
        self.assertEqual(layer["disposition"], "evidence-only-review-required")
        self.assertFalse(result["summary"]["user_confirmation_required_now"])


if __name__ == "__main__":
    unittest.main()
