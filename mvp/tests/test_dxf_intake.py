from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.dxf_intake import DxfParseError, DxfSecondaryValidator, compare_dxf_to_dwg


MINIMAL_DXF = """0
SECTION
2
HEADER
9
$ACADVER
1
AC1027
9
$INSUNITS
70
4
9
$EXTMIN
10
0
20
0
30
0
9
$EXTMAX
10
100
20
50
30
0
0
ENDSEC
0
SECTION
2
TABLES
0
TABLE
2
LAYER
0
LAYER
2
0
70
0
0
LAYER
2
PL-新建墙体
70
0
0
ENDTAB
0
ENDSEC
0
SECTION
2
BLOCKS
0
BLOCK
2
*Model_Space
0
LINE
8
0
10
0
20
0
11
100
21
0
0
ENDBLK
0
ENDSEC
0
SECTION
2
ENTITIES
0
LINE
5
10
8
PL-新建墙体
10
0
20
0
11
100
21
0
0
TEXT
5
11
8
0
10
10
20
20
1
展厅
0
DIMENSION
5
12
8
0
10
0
20
0
0
ENDSEC
0
EOF
"""


class DxfIntakeTests(unittest.TestCase):
    def write_dxf(self, directory: str, content: str = MINIMAL_DXF) -> Path:
        path = Path(directory) / "plan.dxf"
        path.write_text(content, encoding="utf-8")
        return path

    def test_reads_header_layers_entities_and_blocks_without_promoting_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = DxfSecondaryValidator().parse(self.write_dxf(directory))
        self.assertEqual(summary["dxf_version"], "AC1027")
        self.assertEqual(summary["drawing_units"]["name"], "millimeters")
        self.assertEqual(summary["layer_names"], ["0", "PL-新建墙体"])
        self.assertEqual(summary["entities"]["entity_count"], 3)
        self.assertEqual(summary["entities"]["entity_counts"], {"DIMENSION": 1, "LINE": 1, "TEXT": 1})
        self.assertEqual(summary["entities"]["dimension_entity_count"], 1)
        self.assertEqual(summary["blocks"]["block_definition_count"], 1)
        self.assertEqual(summary["status"], "secondary-summary-read")
        self.assertIn("DXF_SUMMARY_ONLY", {item["code"] for item in summary["warnings"]})

    def test_rejects_binary_or_malformed_group_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.dxf"
            path.write_bytes(b"0\nSECTION\n2\nHEADER\n9\n")
            with self.assertRaises(DxfParseError):
                DxfSecondaryValidator().parse(path)

    def test_decodes_autocad_unicode_layer_escape(self):
        escaped = MINIMAL_DXF.replace("PL-新建墙体", r"PL-\U+65B0\U+5EFA\U+5899\U+4F53")
        with tempfile.TemporaryDirectory() as directory:
            summary = DxfSecondaryValidator().parse(self.write_dxf(directory, escaped))
        self.assertIn("PL-新建墙体", summary["layer_names"])
        self.assertEqual(summary["entities"]["layer_entity_counts"]["PL-新建墙体"], 1)

    def test_summary_comparison_is_explicitly_not_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            dxf = DxfSecondaryValidator().parse(self.write_dxf(directory))
        dwg = {
            "geometry_metadata": {
                "drawing_units": {"name": "millimeters"},
                "layer_count": 2,
                "layer_names": ["0", "PL-新建墙体"],
                "entity_count": 3,
                "entity_type_count": 3,
                "text_entity_count": 1,
                "dimension_entity_count": 1,
                "global_extents": {"minimum": [0, 0, 0], "maximum": [100, 50, 0]},
            }
        }
        comparison = compare_dxf_to_dwg(dxf, dwg)
        self.assertEqual(comparison["comparison_status"], "summary-matched")
        self.assertEqual(comparison["promotion_status"], "not-approved")
        self.assertNotIn("geometry-approved", json.dumps(comparison))

    def test_header_extent_comparison_allows_submillimeter_parser_rounding(self):
        with tempfile.TemporaryDirectory() as directory:
            dxf = DxfSecondaryValidator().parse(self.write_dxf(directory))
        dwg = {
            "geometry_metadata": {
                "drawing_units": {"name": "millimeters"},
                "layer_count": 2,
                "layer_names": ["0", "PL-新建墙体"],
                "entity_count": 3,
                "entity_type_count": 3,
                "text_entity_count": 1,
                "dimension_entity_count": 1,
                "global_extents": {"minimum": [0.001, 0, 0], "maximum": [100, 50.001, 0]},
            }
        }
        comparison = compare_dxf_to_dwg(dxf, dwg)
        extent = next(item for item in comparison["checks"] if item["check_id"] == "header-extents")
        self.assertEqual(extent["status"], "match")

    def test_schema_declares_non_approval_contract(self):
        schema_path = Path(__file__).parents[2] / "contracts" / "v1" / "cad-secondary-validation.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["contract_version"]["const"], "1.0")
        self.assertEqual(schema["$defs"]["comparison"]["properties"]["promotion_status"]["const"], "not-approved")

    def test_cli_payload_validates_against_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema optional test dependency unavailable")
        with tempfile.TemporaryDirectory() as directory:
            dxf = DxfSecondaryValidator().parse(self.write_dxf(directory))
        dwg = {
            "geometry_metadata": {
                "drawing_units": {"name": "millimeters"},
                "layer_count": 2,
                "layer_names": ["0", "PL-新建墙体"],
                "entity_count": 3,
                "entity_type_count": 3,
                "text_entity_count": 1,
                "dimension_entity_count": 1,
                "global_extents": {"minimum": [0, 0, 0], "maximum": [100, 50, 0]},
            }
        }
        comparison = compare_dxf_to_dwg(dxf, dwg)
        payload = {
            "contract_version": "1.0",
            "source_asset_id": "drawing-cad-01",
            "reference_dwg_sha256": "A" * 64,
            "source_relationship_status": "registered-reference-unverified",
            "dxf": dxf,
            "comparison": comparison,
            "status": comparison["comparison_status"],
            "warnings": [],
        }
        root = Path(__file__).parents[2]
        schema = json.loads((root / "contracts" / "v1" / "cad-secondary-validation.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(payload)


if __name__ == "__main__":
    unittest.main()
