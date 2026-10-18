from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.cad_topology_review import CadTopologyReviewBuilder


class CadTopologyReviewTests(unittest.TestCase):
    def test_routes_categories_without_creating_domain_objects_or_quantities(self):
        candidates = {
            "status": "candidate-extraction-complete",
            "source_asset_id": "drawing-cad-01",
            "source_sha256": "A" * 64,
            "profile_id": "plan-v1",
            "candidates": [
                {
                    "candidate_id": "wall-1", "source_geometry_closed": False,
                    "requires_block_expansion": False,
                },
                {
                    "candidate_id": "door-1", "source_geometry_closed": None,
                    "requires_block_expansion": True,
                },
            ],
        }
        groups = {
            "status": "geometry-grouping-complete",
            "source_sha256": "A" * 64,
            "groups": [
                {
                    "group_id": "g-wall", "category": "architecture.wall",
                    "candidate_count": 1, "candidate_ids": ["wall-1"],
                    "bounds": {"minimum": [0, 0], "maximum": [100, 10]},
                },
                {
                    "group_id": "g-door", "category": "architecture.opening.door",
                    "candidate_count": 1, "candidate_ids": ["door-1"],
                    "bounds": {"minimum": [10, 0], "maximum": [20, 10]},
                },
            ],
        }
        result = CadTopologyReviewBuilder().build(candidates, groups)
        statuses = {item["category"]: item["review_status"] for item in result["items"]}
        self.assertEqual(statuses["architecture.wall"], "needs-wall-boundary-pairing")
        self.assertEqual(statuses["architecture.opening.door"], "needs-wall-opening-pairing")
        self.assertEqual(result["summary"]["created_domain_object_count"], 0)
        self.assertEqual(result["summary"]["quantity_ready_count"], 0)
        self.assertFalse(result["summary"]["user_confirmation_required_now"])


if __name__ == "__main__":
    unittest.main()
