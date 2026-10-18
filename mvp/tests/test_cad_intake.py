from pathlib import Path
import hashlib
import json
import tempfile
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.cad_intake import DwgIntakeAdapter, LibreDwgParser


def valid_geometry_metadata():
    return {
        "quality_status": "parsed",
        "requires_secondary_validation": False,
        "parser_output_validation": {
            "valid_json": True,
            "required_sections_present": True,
            "json_size_bytes": 1234,
        },
        "drawing_units": {"code": 4, "name": "millimeters"},
        "object_count": 6,
        "entity_count": 3,
        "non_entity_object_count": 3,
        "entity_type_count": 2,
        "entity_counts": {"LINE": 2, "MTEXT": 1},
        "text_entity_count": 1,
        "dimension_entity_count": 0,
        "layer_count": 2,
        "layer_names": ["0", "PL-新建墙体"],
        "layer_statistics": [
            {
                "name": "0", "handle": 6, "entity_count": 2, "entity_counts": {"LINE": 2},
                "block_context_counts": {"model-reachable": 2}, "top_owner_blocks": [],
            },
            {
                "name": "PL-新建墙体", "handle": 100, "entity_count": 1, "entity_counts": {"MTEXT": 1},
                "block_context_counts": {"model-reachable": 1}, "top_owner_blocks": [],
            },
        ],
        "unresolved_layer_reference_count": 0,
        "block_context": {
            "block_header_count": 1,
            "insert_relationship_count": 0,
            "unique_block_graph_edge_count": 0,
            "model_space_root_count": 1,
            "paper_space_root_count": 0,
            "model_reachable_block_count": 1,
            "paper_reachable_block_count": 0,
            "model_and_paper_reachable_block_count": 0,
            "entity_context_counts": {"model-reachable": 3},
        },
        "global_extents": {
            "minimum": [0.0, 0.0, 0.0],
            "maximum": [10.0, 20.0, 0.0],
            "usage": "diagnostic-only",
        },
        "parser_diagnostics": {
            "diagnostic_line_count": 0,
            "error_line_count": 0,
            "categories": {},
        },
    }


class FakeCadParser:
    name = "fake-cad-parser"
    version = "1.0"

    def supports(self, dwg_signature: str) -> bool:
        return dwg_signature == "AC1021"

    def parse(self, source_path: Path):
        return valid_geometry_metadata()


class CadIntakeTests(unittest.TestCase):
    def create_dwg(self, directory: str, name: str = "plan.dwg", signature: bytes = b"AC1021") -> Path:
        path = Path(directory) / name
        path.write_bytes(signature + b"\x00" * 128)
        return path

    def test_registered_dwg_waits_for_professional_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.create_dwg(directory)
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            result = DwgIntakeAdapter().inspect(source, "drawing-cad-01", expected)
            self.assertEqual(result.intake_status, "geometry-parse-pending")
            self.assertEqual(result.geometry_status, "not-run")
            self.assertEqual(result.dwg_signature, "AC1021")
            self.assertEqual(result.dwg_version, "AutoCAD 2007/2008/2009")
            self.assertEqual(result.sha256, expected.upper())
            self.assertIn("CAD_GEOMETRY_PARSER_UNAVAILABLE", [item.code for item in result.warnings])

    def test_hash_mismatch_blocks_geometry_parse(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.create_dwg(directory)
            result = DwgIntakeAdapter(FakeCadParser()).inspect(source, "drawing-cad-01", "0" * 64)
            self.assertEqual(result.intake_status, "rejected")
            self.assertEqual(result.geometry_status, "not-run")
            self.assertEqual(result.geometry_metadata, {})
            self.assertIn("SOURCE_HASH_MISMATCH", [item.code for item in result.warnings])

    def test_unknown_signature_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.create_dwg(directory, signature=b"NOTDWG")
            result = DwgIntakeAdapter().inspect(source, "drawing-cad-01")
            self.assertEqual(result.intake_status, "rejected")
            self.assertIsNone(result.dwg_version)

    def test_configured_parser_can_return_geometry_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.create_dwg(directory)
            result = DwgIntakeAdapter(FakeCadParser()).inspect(source, "drawing-cad-01")
            self.assertEqual(result.intake_status, "geometry-parsed")
            self.assertEqual(result.geometry_status, "succeeded")
            self.assertEqual(result.geometry_metadata["drawing_units"]["name"], "millimeters")
            self.assertEqual(result.geometry_metadata["layer_count"], 2)

    def test_parser_warning_is_exposed_without_discarding_metadata(self):
        class WarningParser(FakeCadParser):
            def parse(self, source_path: Path):
                metadata = valid_geometry_metadata()
                metadata["quality_status"] = "parsed-with-compatibility-warnings"
                metadata["requires_secondary_validation"] = True
                metadata["parser_diagnostics"] = {
                    "diagnostic_line_count": 1,
                    "error_line_count": 0,
                    "categories": {"unstable-class": 1},
                }
                return metadata

        with tempfile.TemporaryDirectory() as directory:
            source = self.create_dwg(directory)
            result = DwgIntakeAdapter(WarningParser()).inspect(source, "drawing-cad-01")
            self.assertEqual(result.intake_status, "geometry-parsed")
            self.assertEqual(result.checks[-1].status, "warning")
            self.assertIn("CAD_GEOMETRY_PARSE_WARNINGS", [item.code for item in result.warnings])

    def test_inconsistent_parser_summary_is_rejected(self):
        class InconsistentParser(FakeCadParser):
            def parse(self, source_path: Path):
                metadata = valid_geometry_metadata()
                metadata["entity_count"] = 999
                return metadata

        with tempfile.TemporaryDirectory() as directory:
            source = self.create_dwg(directory)
            result = DwgIntakeAdapter(InconsistentParser()).inspect(source, "drawing-cad-01")
            self.assertEqual(result.intake_status, "geometry-parse-failed")
            self.assertEqual(result.geometry_status, "failed")
            self.assertIn("CAD_GEOMETRY_PARSE_FAILED", [item.code for item in result.warnings])

    def test_libredwg_summary_counts_entities_units_and_diagnostics(self):
        payload = {
            "HEADER": {
                "INSUNITS": 4,
                "EXTMIN": [1.0, 2.0, 0.0],
                "EXTMAX": [10.0, 20.0, 0.0],
            },
            "OBJECTS": [
                {"object": "LAYER", "name": "0", "handle": [0, 1, 6]},
                {"object": "LAYER", "name": "PL-\ufffd", "handle": [0, 1, 100]},
                {
                    "object": "BLOCK_HEADER", "name": "*Model_Space", "handle": [0, 1, 2],
                    "entities": [[3, 1, 10, 10], [3, 1, 11, 11], [3, 1, 12, 12], [3, 1, 13, 13]],
                },
                {"entity": "LINE", "handle": [0, 1, 10], "layer": [5, 1, 6, 6]},
                {"entity": "LINE", "handle": [0, 1, 11], "layer": [5, 1, 6, 6]},
                {"entity": "MTEXT", "handle": [0, 1, 12], "layer": [5, 1, 100, 100]},
                {"entity": "DIMENSION_LINEAR", "handle": [0, 1, 13], "layer": [5, 1, 100, 100]},
            ],
        }
        summary = LibreDwgParser._summarize_payload(
            payload,
            ["0", "PL-新建墙体"],
            1234,
            {"diagnostic_line_count": 2, "error_line_count": 0, "categories": {"unstable-class": 2}},
        )
        self.assertEqual(summary["drawing_units"]["name"], "millimeters")
        self.assertEqual(summary["entity_count"], 4)
        self.assertEqual(summary["entity_counts"]["LINE"], 2)
        self.assertEqual(summary["text_entity_count"], 1)
        self.assertEqual(summary["dimension_entity_count"], 1)
        self.assertEqual(summary["layer_count"], 2)
        self.assertEqual(summary["layer_statistics"][0]["entity_count"], 2)
        self.assertEqual(summary["layer_statistics"][0]["block_context_counts"]["model-reachable"], 2)
        self.assertEqual(summary["block_context"]["model_reachable_block_count"], 1)
        self.assertEqual(summary["unresolved_layer_reference_count"], 0)
        self.assertTrue(summary["requires_secondary_validation"])

    def test_block_context_distinguishes_reachable_and_unused_definitions(self):
        payload = {
            "HEADER": {"INSUNITS": 4},
            "OBJECTS": [
                {"object": "LAYER", "name": "0", "handle": [0, 1, 6]},
                {
                    "object": "BLOCK_HEADER", "name": "*Model_Space", "handle": [0, 1, 2],
                    "entities": [[3, 1, 10, 10]],
                },
                {
                    "object": "BLOCK_HEADER", "name": "USED", "handle": [0, 1, 20],
                    "entities": [[3, 1, 21, 21]],
                },
                {
                    "object": "BLOCK_HEADER", "name": "UNUSED", "handle": [0, 1, 30],
                    "entities": [[3, 1, 31, 31]],
                },
                {
                    "entity": "INSERT", "handle": [0, 1, 10], "layer": [5, 1, 6, 6],
                    "block_header": [5, 1, 20, 20],
                },
                {"entity": "LINE", "handle": [0, 1, 21], "layer": [5, 1, 6, 6]},
                {"entity": "LINE", "handle": [0, 1, 31], "layer": [5, 1, 6, 6]},
            ],
        }
        summary = LibreDwgParser._summarize_payload(
            payload,
            ["0"],
            4321,
            {"diagnostic_line_count": 0, "error_line_count": 0, "categories": {}},
        )
        contexts = summary["layer_statistics"][0]["block_context_counts"]
        self.assertEqual(contexts["model-reachable"], 2)
        self.assertEqual(contexts["unreachable-block-definition"], 1)
        self.assertEqual(summary["block_context"]["unique_block_graph_edge_count"], 1)
        self.assertEqual(summary["block_context"]["model_reachable_block_count"], 2)

    def test_libredwg_rejects_incomplete_json_structure(self):
        with self.assertRaisesRegex(RuntimeError, "missing required sections"):
            LibreDwgParser._validate_payload({"HEADER": {}, "OBJECTS": []})

    def test_layer_output_preserves_chinese_names(self):
        output = " + \t0\n + \tPL-新建墙体\n".encode("utf-8")
        self.assertEqual(LibreDwgParser._parse_layer_names(output), ["0", "PL-新建墙体"])

    def test_contract_lists_all_runtime_statuses(self):
        schema_path = Path(__file__).parents[2] / "contracts" / "v1" / "cad-source-inspection.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        statuses = schema["properties"]["intake_status"]["enum"]
        self.assertEqual(set(statuses), {
            "rejected", "geometry-parse-pending", "geometry-parse-failed", "geometry-parsed",
        })
        metadata = schema["properties"]["geometry_metadata"]["properties"]
        self.assertIn("quality_status", metadata)
        self.assertIn("parser_diagnostics", metadata)
        self.assertIn("layer_names", metadata)
        self.assertIn("block_context", metadata)


if __name__ == "__main__":
    unittest.main()
