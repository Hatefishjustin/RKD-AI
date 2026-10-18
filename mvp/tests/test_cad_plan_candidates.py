from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.cad_plan_candidates import CadPlanCandidateExtractor


class CadPlanCandidateTests(unittest.TestCase):
    def setUp(self):
        self.extractor = CadPlanCandidateExtractor()
        self.inspection = {
            "source_asset_id": "drawing-cad-01",
            "sha256": "A" * 64,
            "intake_status": "geometry-parsed",
            "geometry_metadata": {
                "drawing_units": {"name": "millimeters"},
                "layer_names": ["ANCHOR-A", "ANCHOR-B", "WALL", "OUTLET"],
            },
        }
        self.mapping = {
            "source_sha256": "A" * 64,
            "mapping_version": "test-v1",
            "layer_mappings": [
                self._mapping("ANCHOR-A", "annotation.dimension", "supporting-evidence"),
                self._mapping("ANCHOR-B", "annotation.dimension", "supporting-evidence"),
                self._mapping("WALL", "architecture.wall", "included-design-evidence"),
                self._mapping("OUTLET", "mep.electrical.outlet", "excluded-by-project-decision"),
            ],
        }
        self.profile = {
            "contract_version": "1.0",
            "profile_id": "test-primary-plan-v1",
            "source_asset_id": "drawing-cad-01",
            "expected_dimensions_mm": [17920, 26170],
            "dimension_tolerance_mm": 1,
            "anchor_consensus_tolerance_mm": 1,
            "minimum_anchor_matches": 2,
            "primary_anchor_layers": ["ANCHOR-A", "ANCHOR-B"],
            "corroborating_evidence": [{"source_asset_id": "drawing-plan-01"}],
        }
        self.payload = {
            "OBJECTS": [
                self._layer(1), self._layer(2), self._layer(3), self._layer(4),
                {
                    "object": "BLOCK_HEADER", "name": "*Model_Space", "handle": [0, 50],
                    "entities": [[0, handle] for handle in (101, 102, 103, 104, 105)],
                },
                self._line(101, 1, [0, 0, 0], [26170, 17920, 0]),
                self._line(102, 2, [0, 0, 0], [26170, 17920, 0]),
                self._line(103, 3, [100, 100, 0], [1000, 100, 0]),
                self._line(104, 3, [30000, 100, 0], [31000, 100, 0]),
                {
                    "entity": "INSERT", "handle": [0, 105], "layer": [0, 4],
                    "ins_pt": [500, 500, 0], "block_header": [0, 60],
                },
            ]
        }

    @staticmethod
    def _mapping(layer, category, scope):
        return {
            "layer_name": layer,
            "layer_role": "professional",
            "category": category,
            "scope_disposition": scope,
            "confidence": 0.99,
        }

    @staticmethod
    def _layer(handle):
        return {"object": "LAYER", "handle": [0, handle]}

    @staticmethod
    def _line(handle, layer, start, end):
        return {
            "entity": "LINE", "handle": [0, handle], "layer": [0, layer],
            "start": start, "end": end,
        }

    def test_localizes_plan_and_filters_direct_model_candidates(self):
        result = self.extractor.extract(
            self.payload, self.inspection, self.mapping, self.profile
        )
        self.assertEqual(result["target_region"]["size"], {"x": 26170.0, "y": 17920.0})
        self.assertEqual(result["summary"]["direct_model_candidate_count"], 4)
        self.assertEqual(result["summary"]["current_scope_candidate_count"], 1)
        self.assertEqual(result["summary"]["excluded_scope_candidate_count"], 1)
        self.assertEqual(result["summary"]["other_non_current_scope_candidate_count"], 2)
        self.assertEqual(result["summary"]["outside_region_counts"], {"WALL": 1})
        outlet = next(item for item in result["candidates"] if item["source_entity_type"] == "INSERT")
        self.assertTrue(outlet["requires_block_expansion"])
        self.assertFalse(outlet["eligible_for_current_scope"])
        self.assertEqual(outlet["referenced_block_handle"], 60)
        self.assertEqual(
            result["target_region"]["corroborating_evidence"],
            [{"source_asset_id": "drawing-plan-01"}],
        )

    def test_rejects_anchor_dimension_mismatch(self):
        self.payload["OBJECTS"][6]["end"] = [20000, 10000, 0]
        with self.assertRaisesRegex(ValueError, "plan anchors matched"):
            self.extractor.extract(self.payload, self.inspection, self.mapping, self.profile)

    def test_dimension_clone_origin_does_not_expand_real_geometry_bounds(self):
        dimension = {
            "entity": "DIMENSION_LINEAR",
            "text_midpt": [150, 100, 0],
            "xline1_pt": [100, 100, 0],
            "xline2_pt": [200, 100, 0],
            "clone_ins_pt": [0, 0],
        }
        self.assertEqual(
            self.extractor._bounds(self.extractor._entity_points(dimension)),
            {"minimum": [100.0, 100.0], "maximum": [200.0, 100.0]},
        )
        self.assertTrue(self.extractor._source_geometry_closed({"entity": "LWPOLYLINE", "flag": 1}))
        self.assertFalse(self.extractor._source_geometry_closed({"entity": "LWPOLYLINE", "flag": 0}))

    def test_nested_block_transform_applies_base_scale_rotation_and_translation(self):
        objects = {
            60: {
                "object": "BLOCK_HEADER", "handle": [0, 60], "base_pt": [0, 0, 0],
                "entities": [[0, 61]],
            },
            61: self._line(61, 3, [0, 0, 0], [10, 0, 0]),
            70: {
                "object": "BLOCK_HEADER", "handle": [0, 70], "base_pt": [5, 5, 0],
                "entities": [[0, 71]],
            },
            71: {
                "entity": "INSERT", "handle": [0, 71], "layer": [0, 3],
                "ins_pt": [15, 5, 0], "scale": [1, 1, 1],
                "rotation": 1.5707963267948966, "block_header": [0, 60],
            },
        }
        root = {
            "entity": "INSERT", "handle": [0, 80], "layer": [0, 3],
            "ins_pt": [100, 100, 0], "scale": [2, 2, 1],
            "rotation": 0, "block_header": [0, 70],
        }
        result = self.extractor._expand_insert_geometry(
            root,
            objects,
            {handle: item for handle, item in objects.items() if item.get("object") == "BLOCK_HEADER"},
            max_depth=8,
        )
        self.assertEqual(result["status"], "expanded")
        self.assertEqual(result["maximum_nested_depth"], 2)
        self.assertEqual(result["leaf_entity_type_counts"], {"LINE": 1})
        rounded = {(round(x, 6), round(y, 6)) for x, y in result["points"]}
        self.assertEqual(rounded, {(120.0, 100.0), (120.0, 120.0)})

    def test_hatch_segment_endpoints_and_control_points_are_coordinates(self):
        hatch = {
            "entity": "HATCH",
            "paths": [{
                "segs": [
                    {"first_endpoint": [1, 2], "second_endpoint": [3, 4]},
                    {"control_points": [{"point": [5, 6]}, {"point": [7, 8]}]},
                ]
            }],
        }
        self.assertEqual(
            self.extractor._entity_points(hatch),
            [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0)],
        )

    def test_negative_z_extrusion_converts_ocs_to_planar_world_coordinates(self):
        block = {"base_pt": [0, 0, 0]}
        insert = {
            "ins_pt": [-100, 50, 0],
            "scale": [1, 1, -1],
            "rotation": 0,
            "extrusion": [0, 0, -1],
        }
        matrix = self.extractor._insert_matrix(insert, block)
        self.assertEqual(self.extractor._transform_point((0, 0), matrix), (100.0, 50.0))
        self.assertEqual(self.extractor._transform_point((10, 0), matrix), (90.0, 50.0))
        self.assertTrue(self.extractor._is_supported_planar_extrusion([0, 0, -1]))
        self.assertFalse(self.extractor._is_supported_planar_extrusion([0, 1, 0]))

    def test_arc_uses_start_and_end_angles_instead_of_a_full_circle(self):
        points = self.extractor._entity_points({
            "entity": "ARC", "center": [0, 0, 0], "radius": 10,
            "start_angle": 0, "end_angle": 1.5707963267948966,
        })
        bounds = self.extractor._bounds(points)
        self.assertAlmostEqual(bounds["minimum"][0], 0.0, places=6)
        self.assertAlmostEqual(bounds["minimum"][1], 0.0, places=6)
        self.assertAlmostEqual(bounds["maximum"][0], 10.0, places=6)
        self.assertAlmostEqual(bounds["maximum"][1], 10.0, places=6)
        self.assertNotIn((0.0, 0.0), points)

    def test_contract_is_valid_json_and_covers_scope_counts(self):
        root = Path(__file__).parents[2]
        schema = json.loads(
            (root / "contracts" / "v1" / "cad-plan-candidates.schema.json").read_text(encoding="utf-8")
        )
        summary = schema["$defs"]["summary"]["properties"]
        self.assertIn("scope_disposition_candidate_counts", summary)
        self.assertEqual(schema["properties"]["contract_version"]["const"], "1.0")


if __name__ == "__main__":
    unittest.main()
