from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]))

from rkd_mvp.gold_standard_intake import GoldStandardInventoryBuilder


def intake_config():
    return {
        "dataset_id": "gold-office-001-v1",
        "organization_id": "org-rkd",
        "source_project_ref": "historical-project-001",
        "project_type": "office",
        "received_at": "2026-09-19T10:00:00+08:00",
        "use_permissions": {
            "evaluation": {"status": "authorized", "authorization_reference": "approval-eval-001"},
            "training": {"status": "pending", "authorization_reference": None},
            "external_model_upload": {"status": "prohibited", "authorization_reference": None},
        },
        "privacy": {
            "classification": "confidential",
            "contains_personal_data": True,
            "contains_client_identifiers": True,
            "deidentification_status": "not-started",
            "review_status": "pending",
        },
        "professional_review": {
            "status": "pending",
            "reviewer_role": "design-lead",
            "reviewed_at": None,
            "approval_reference": None,
            "tolerance_profile_id": None,
            "known_defects": [],
        },
        "asset_overrides": {
            "CAD\\设计.dwg": {
                "role": "cad",
                "role_status": "confirmed",
                "revision_id": "cad-r1",
            }
        },
        "version_relationships": [
            {
                "from_path": "商务/预算报价.xlsx",
                "to_path": "CAD/设计.dwg",
                "relationship_type": "corresponds-to",
                "status": "candidate",
            }
        ],
    }


class GoldStandardIntakeTests(unittest.TestCase):
    def create_source(self, directory: str) -> Path:
        root = Path(directory) / "historical-project-001"
        (root / "CAD").mkdir(parents=True)
        (root / "商务").mkdir()
        (root / "需求").mkdir()
        (root / "CAD" / "设计.dwg").write_bytes(b"AC1021" + b"\x00" * 32)
        (root / "商务" / "预算报价.xlsx").write_bytes(b"spreadsheet")
        (root / "商务" / "预算报价-副本.xlsx").write_bytes(b"spreadsheet")
        (root / "需求" / "设计任务书.docx").write_bytes(b"requirements")
        return root

    def test_builds_read_only_inventory_with_hashes_roles_duplicates_and_relationships(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.create_source(directory)
            before = {
                path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in source.rglob("*") if path.is_file()
            }
            result = GoldStandardInventoryBuilder().build(source, intake_config())
            after = {
                path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in source.rglob("*") if path.is_file()
            }
        self.assertEqual(before, after)
        self.assertEqual(result["intake_status"], "privacy-review-required")
        self.assertEqual(result["coverage"]["asset_count"], 4)
        self.assertEqual(len(result["duplicate_groups"]), 1)
        self.assertEqual(len(result["version_relationships"]), 1)
        cad = next(item for item in result["assets"] if item["relative_path"] == "CAD/设计.dwg")
        self.assertEqual(cad["role_status"], "confirmed")
        self.assertEqual(cad["ingestion_mode"], "read-only")
        self.assertTrue(all(not Path(item["relative_path"]).is_absolute() for item in result["assets"]))
        self.assertEqual(result["use_permissions"]["training"]["status"], "pending")
        self.assertIn("INGESTION_IS_NOT_TRAINING_AUTHORIZATION", {item["code"] for item in result["warnings"]})

    def test_authorized_training_requires_explicit_reference(self):
        config = intake_config()
        config["use_permissions"]["training"] = {
            "status": "authorized",
            "authorization_reference": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            source = self.create_source(directory)
            with self.assertRaisesRegex(ValueError, "training use requires"):
                GoldStandardInventoryBuilder().build(source, config)

    def test_asset_override_cannot_escape_source_root(self):
        config = intake_config()
        config["asset_overrides"]["../outside.dwg"] = {"role": "cad"}
        with tempfile.TemporaryDirectory() as directory:
            source = self.create_source(directory)
            with self.assertRaisesRegex(ValueError, "stay inside"):
                GoldStandardInventoryBuilder().build(source, config)

    def test_critical_known_defect_blocks_positive_replay(self):
        config = intake_config()
        config["privacy"].update({"deidentification_status": "completed", "review_status": "approved"})
        config["professional_review"] = {
            "status": "approved",
            "reviewer_role": "design-lead",
            "reviewed_at": "2026-09-19T11:00:00+08:00",
            "approval_reference": "review-001",
            "tolerance_profile_id": "tolerance-v1",
            "known_defects": [
                {
                    "defect_id": "defect-001",
                    "severity": "E1",
                    "description": "Known drawing inconsistency.",
                    "accepted_for_replay": False,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = GoldStandardInventoryBuilder().build(self.create_source(directory), config)
        self.assertEqual(result["intake_status"], "blocked")
        self.assertIn("PROFESSIONAL_DEFECTS_BLOCK_REPLAY", {item["code"] for item in result["warnings"]})

    def test_manifest_validates_against_contract(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema optional test dependency unavailable")
        with tempfile.TemporaryDirectory() as directory:
            result = GoldStandardInventoryBuilder().build(self.create_source(directory), intake_config())
        root = Path(__file__).parents[2]
        schema = json.loads(
            (root / "contracts" / "v1" / "gold-standard-manifest.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(result)


if __name__ == "__main__":
    unittest.main()
