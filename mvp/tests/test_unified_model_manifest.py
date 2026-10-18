from pathlib import Path
import hashlib
import json
import unittest


class UnifiedModelManifestFixtureTests(unittest.TestCase):
    def test_fixture_tracks_current_contract_and_schema_hash(self):
        root = Path(__file__).parents[2]
        schema_path = root / "contracts" / "v1" / "unified-model-manifest.schema.json"
        fixture_path = root / "fixtures" / "vertical-mvp" / "v1" / "expected" / "unified-model-manifest.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(schema_path.read_bytes()).hexdigest()
        self.assertEqual(fixture["contract_version"], schema["properties"]["contract_version"]["const"])
        self.assertEqual(fixture["schema_hash"], f"sha256:{digest}")
        self.assertTrue(set(schema["required"]) <= set(fixture))
        self.assertEqual(fixture["coverage"]["mapping_ratio"], 1.0)
        self.assertEqual(
            {item["representation_type"] for item in fixture["representations"]},
            {"native", "exchange"},
        )


if __name__ == "__main__":
    unittest.main()
