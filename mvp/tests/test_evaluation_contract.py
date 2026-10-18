from pathlib import Path
import json
import unittest


class EvaluationContractTests(unittest.TestCase):
    def test_observation_contract_separates_planned_gates_from_corrections(self):
        root = Path(__file__).parents[2]
        schema = json.loads(
            (root / "contracts" / "v1" / "evaluation-observation.schema.json").read_text(encoding="utf-8")
        )
        kinds = schema["$defs"]["intervention"]["properties"]["kind"]["enum"]
        self.assertIn("planned-gate", kinds)
        self.assertIn("correction", kinds)
        self.assertIn("rescue", kinds)

    def test_contract_records_versions_cost_and_consistency(self):
        root = Path(__file__).parents[2]
        schema = json.loads(
            (root / "contracts" / "v1" / "evaluation-observation.schema.json").read_text(encoding="utf-8")
        )
        required = set(schema["required"])
        self.assertTrue({"consistency_checks", "provenance", "runtime"} <= required)
        runtime = schema["properties"]["runtime"]["properties"]
        self.assertIn("model_versions", runtime)
        self.assertIn("executor_versions", runtime)


if __name__ == "__main__":
    unittest.main()
