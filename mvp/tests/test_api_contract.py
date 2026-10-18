import json
from pathlib import Path
import unittest


SPEC_PATH = Path(__file__).parents[2] / "contracts" / "v1" / "openapi.v1.json"


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    def test_required_mvp_paths_exist(self):
        paths = self.spec["paths"]
        for path in (
            "/v1/projects", "/v1/projects/{projectId}/uploads",
            "/v1/projects/{projectId}/uploads/{uploadId}/content",
            "/v1/projects/{projectId}/files",
            "/v1/projects/{projectId}/files/{fileId}/content",
            "/v1/projects/{projectId}/decisions",
            "/v1/projects/{projectId}/issues",
            "/v1/projects/{projectId}/issues/{issueId}",
            "/v1/projects/{projectId}/jobs",
            "/v1/projects/{projectId}/jobs/{jobId}/retry",
            "/v1/projects/{projectId}/jobs/{jobId}/cancel",
            "/v1/projects/{projectId}/estimates",
            "/v1/projects/{projectId}/estimates/{estimateId}",
            "/v1/projects/{projectId}/estimates/{estimateId}/lines/{lineId}",
            "/v1/projects/{projectId}/estimates/{estimateId}/calculations",
            "/v1/projects/{projectId}/commands",
            "/v1/projects/{projectId}/workflows/{workflowRunId}",
            "/v1/projects/{projectId}/artifacts/{artifactId}",
            "/health/live", "/health/ready",
        ):
            self.assertIn(path, paths)

    def test_command_endpoint_requires_idempotency_and_has_no_direct_write_surface(self):
        operation = self.spec["paths"]["/v1/projects/{projectId}/commands"]["post"]
        parameter_refs = {item.get("$ref") for item in operation["parameters"]}
        self.assertIn("#/components/parameters/IdempotencyKey", parameter_refs)
        self.assertIn("CommandEnvelopeV1", operation["description"])
        self.assertNotIn("/database", self.spec["paths"])
        self.assertNotIn("/v1/executors", self.spec["paths"])

    def test_tenant_scoped_reads_define_not_found_and_security(self):
        self.assertIn("oidc", self.spec["components"]["securitySchemes"])
        for path in ("/v1/projects/{projectId}/workflows/{workflowRunId}", "/v1/projects/{projectId}/artifacts/{artifactId}"):
            responses = self.spec["paths"][path]["get"]["responses"]
            self.assertEqual(responses["404"]["$ref"], "#/components/responses/NotFound")

    def test_file_contract_requires_real_bytes_and_unparsed_result(self):
        paths = self.spec["paths"]
        content = paths["/v1/projects/{projectId}/uploads/{uploadId}/content"]["put"]
        self.assertIn("application/octet-stream", content["requestBody"]["content"])
        completion = paths["/v1/projects/{projectId}/uploads/{uploadId}/complete"]["post"]
        self.assertIn("201", completion["responses"])
        self.assertEqual(self.spec["components"]["schemas"]["FileStored"]["properties"]["status"]["enum"], ["stored_unparsed"])


if __name__ == "__main__":
    unittest.main()
