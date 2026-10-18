from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.cad_semantics import CadLayerSemanticMapper


class CadSemanticMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rules_path = Path(__file__).parents[1] / "config" / "cad-layer-semantic-rules.v1.json"
        cls.mapper = CadLayerSemanticMapper.from_file(rules_path)

    @staticmethod
    def inspection():
        return {
            "source_asset_id": "drawing-cad-01",
            "sha256": "A" * 64,
            "intake_status": "geometry-parsed",
            "geometry_metadata": {
                "quality_status": "parsed-with-compatibility-warnings",
                "requires_secondary_validation": True,
                "entity_count": 22,
                "layer_statistics": [
                    {
                        "name": "PL-新建墙体", "handle": 10, "entity_count": 10,
                        "entity_counts": {"LINE": 8, "LWPOLYLINE": 2},
                        "block_context_counts": {"model-reachable": 10},
                        "top_owner_blocks": [],
                    },
                    {
                        "name": "插座", "handle": 11, "entity_count": 5,
                        "entity_counts": {"INSERT": 5},
                        "block_context_counts": {"model-reachable": 5},
                        "top_owner_blocks": [],
                    },
                    {
                        "name": "155", "handle": 12, "entity_count": 7,
                        "entity_counts": {"LINE": 7},
                        "block_context_counts": {
                            "model-reachable": 2,
                            "unreachable-block-definition": 5,
                        },
                        "top_owner_blocks": [
                            {
                                "block_handle": 99,
                                "block_name": "G$TEST",
                                "entity_count": 5,
                                "context": "unreachable-block-definition",
                                "insertion_reference_count": 0,
                                "external_reference_hint": True,
                            }
                        ],
                    },
                ],
            },
        }

    def test_maps_professional_layers_and_preserves_project_scope(self):
        result = self.mapper.map_inspection(self.inspection())
        wall = result["layer_mappings"][0]
        outlet = result["layer_mappings"][1]
        self.assertEqual(wall["category"], "architecture.wall")
        self.assertEqual(wall["scope_disposition"], "included-design-evidence")
        self.assertEqual(outlet["category"], "mep.electrical.outlet")
        self.assertEqual(outlet["scope_disposition"], "excluded-by-project-decision")

    def test_legacy_layer_candidate_stays_in_system_review_before_user_confirmation(self):
        result = self.mapper.map_inspection(self.inspection())
        unknown = result["layer_mappings"][2]
        self.assertEqual(unknown["mapping_status"], "mapped")
        self.assertEqual(unknown["category"], "drawing.external-reference")
        self.assertEqual(unknown["verification_status"], "needs-system-review")
        self.assertEqual(unknown["reachable_entity_count"], 2)
        self.assertEqual(unknown["unreachable_definition_entity_count"], 5)
        self.assertEqual(result["summary"]["review_layer_count"], 1)
        self.assertEqual(result["summary"]["review_reachable_entity_count"], 2)
        self.assertFalse(result["summary"]["user_confirmation_required_now"])
        self.assertEqual(result["system_review_queue"][0]["layer_name"], "155")

    def test_mapping_is_rejected_before_geometry_parse(self):
        inspection = self.inspection()
        inspection["intake_status"] = "geometry-parse-pending"
        with self.assertRaisesRegex(ValueError, "geometry-parsed"):
            self.mapper.map_inspection(inspection)

    def test_rules_and_mapping_contract_are_valid_json(self):
        root = Path(__file__).parents[2]
        rules = json.loads((root / "mvp" / "config" / "cad-layer-semantic-rules.v1.json").read_text(encoding="utf-8"))
        schema = json.loads((root / "contracts" / "v1" / "cad-layer-semantic-mapping.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(rules["contract_version"], "1.0")
        self.assertEqual(schema["properties"]["contract_version"]["const"], "1.0")
        summary = schema["properties"]["summary"]["properties"]
        self.assertIn("reachable_entity_count", summary)
        self.assertIn("unreachable_definition_entity_count", summary)


if __name__ == "__main__":
    unittest.main()
