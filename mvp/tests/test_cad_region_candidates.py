from pathlib import Path
import importlib.util
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.cad_region_candidates import CadRegionCandidateBuilder


@unittest.skipUnless(importlib.util.find_spec("shapely"), "Shapely optional geometry dependency unavailable")
class CadRegionCandidateTests(unittest.TestCase):
    def test_polygonizes_noded_floor_linework_without_approving_quantities(self):
        candidates = []
        segments = [
            ([0, 0], [20, 0]), ([20, 0], [20, 10]),
            ([20, 10], [0, 10]), ([0, 10], [0, 0]),
            ([10, 0], [10, 10]),
        ]
        for index, (start, end) in enumerate(segments):
            candidates.append({
                "candidate_id": f"c{index}",
                "category": "interior.floor.finish-line",
                "eligible_for_current_scope": True,
                "source_entity_type": "LINE",
                "geometry_points": [start, end],
                "source_geometry_closed": False,
            })
        payload = {
            "status": "candidate-extraction-complete",
            "source_asset_id": "drawing-cad-01",
            "source_sha256": "A" * 64,
            "profile_id": "plan-v1",
            "target_region": {"bounds": {"minimum": [0, 0], "maximum": [20, 10]}},
            "candidates": candidates,
        }
        result = CadRegionCandidateBuilder().build(
            payload, snap_tolerance_mm=0.1, minimum_area_m2=0.00001
        )
        floor = next(item for item in result["category_summary"] if item["category"] == "interior.floor.finish-line")
        self.assertEqual(floor["polygon_candidate_count"], 2)
        self.assertEqual(result["summary"]["created_domain_object_count"], 0)
        self.assertEqual(result["summary"]["quantity_ready_count"], 0)

    def test_contract_is_valid_json(self):
        root = Path(__file__).parents[2]
        schema = json.loads(
            (root / "contracts" / "v1" / "cad-region-candidates.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["contract_version"]["const"], "1.0")


if __name__ == "__main__":
    unittest.main()
