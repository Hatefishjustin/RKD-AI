from __future__ import annotations

import hashlib
from typing import Any

from .models import ExecutorResult, new_id


class SimulatedExecutor:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.failure_mode: str | None = None

    def run(self, job_id: str, input_spec_hash: str, payload: dict[str, Any], attempt: int = 1) -> ExecutorResult:
        if self.failure_mode == "timeout":
            return ExecutorResult(job_id, attempt, "retryable", input_spec_hash, [], [{"code": "TIMEOUT"}])
        if self.failure_mode == "quality-failed":
            return ExecutorResult(job_id, attempt, "quality-failed", input_spec_hash, [], [{"code": "QUALITY_GATE"}])
        suffix = hashlib.sha256(f"{self.kind}:{input_spec_hash}".encode()).hexdigest()[:10]
        artifact = {
            "artifact_id": new_id("artifact"),
            "kind": self.kind,
            "name": f"{self.kind}-{suffix}",
            "input_spec_hash": input_spec_hash,
            "payload": payload,
        }
        return ExecutorResult(job_id, attempt, "succeeded", input_spec_hash, [artifact])


class SimulatedPublishAdapter:
    def __init__(self) -> None:
        self.mode = "confirmed"

    def dispatch(self, action_id: str, artifact_ids: list[str]) -> dict[str, Any]:
        if self.mode == "unknown":
            return {"action_id": action_id, "status": "unknown", "artifact_ids": artifact_ids}
        if self.mode == "rejected":
            return {"action_id": action_id, "status": "rejected", "artifact_ids": artifact_ids}
        return {"action_id": action_id, "status": "confirmed", "artifact_ids": artifact_ids}

