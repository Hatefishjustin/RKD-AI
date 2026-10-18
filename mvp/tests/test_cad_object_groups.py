from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.cad_object_groups import CadObjectGroupBuilder


class CadObjectGroupBuilderTests(unittest.TestCase):
    @staticmethod
    def candidate(identifier, start, end, category="architecture.wall", block=False):
        points = [start, end]
        return {
            "candidate_id": identifier,
            "category": category,
            "source_layer": "WALL",
            "source_entity_type": "INSERT" if block else "LINE",
            "bounds": {
                "minimum": [min(start[0], end[0]), min(start[1], end[1])],
                "maximum": [max(start[0], end[0]), max(start[1], end[1])],
            },
            "point_count": 2,
            "geometry_points": points,
            "source_geometry_closed": False,
            "requires_block_expansion": block,
            "eligible_for_current_scope": True,
        }

    def test_groups_touching_primitives_but_keeps_blocks_isolated(self):
        payload = {
            "status": "candidate-extraction-complete",
            "source_asset_id": "drawing-cad-01",
            "source_sha256": "A" * 64,
            "profile_id": "plan-v1",
            "candidates": [
                self.candidate("a", [0, 0], [10, 0]),
                self.candidate("b", [10, 0], [20, 0]),
                self.candidate("c", [10, -5], [10, 5]),
                self.candidate("block", [10, 0], [12, 2], block=True),
                {**self.candidate("excluded", [20, 0], [30, 0]), "eligible_for_current_scope": False},
            ],
        }
        result = CadObjectGroupBuilder().build(payload)
        self.assertEqual(result["summary"]["input_current_scope_candidate_count"], 4)
        self.assertEqual(result["summary"]["geometry_group_count"], 2)
        sizes = sorted(item["candidate_count"] for item in result["groups"])
        self.assertEqual(sizes, [1, 3])
        self.assertEqual(result["summary"]["final_domain_object_count"], 0)

    def test_contract_is_valid_json(self):
        root = Path(__file__).parents[2]
        schema = json.loads(
            (root / "contracts" / "v1" / "cad-object-groups.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["contract_version"]["const"], "1.0")


if __name__ == "__main__":
    unittest.main()
