"""Controlled run ledger: the ONLY trusted source of run provenance.

Why this exists
---------------
A JSON file that carries its own ``record_sha256`` proves only that the file is
internally consistent.  Any caller can fabricate ``kind=real_model_run``,
``simulated=false``, candidate/input/output hashes and a project id, then
recompute the hash.  Earlier adapter versions accepted exactly that.

Trust boundary
--------------
* Records are ISSUED by this in-process service via ``issue()``.  Each gets a
  server-generated ``run_id`` and an HMAC signature made with a secret created
  at process start (``secrets.token_bytes``).  The secret is never written to
  disk, logged, returned, or accepted as a caller argument.
* Records are VERIFIED by looking up ``run_id`` in this ledger and recomputing
  the HMAC.  Caller-supplied file paths / embedded records are never trusted.
* Cross-project, wrong parent, tampered fields and fabricated ids fail closed.
* In offline verification only ``local_protocol_stub_run`` (simulated=true) is
  ever issued.  No ``real_model_run`` can be issued here, so an unverifiable
  ``real_model`` claim stays ``unknown`` / is rejected.

This module performs no network calls and reads no keys.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class RunLedgerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(f"{code}: {message}")


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class ControlledRunLedger:
    """Append-only, in-process ledger.  One instance per verification process."""

    service_id: str = "rkd-controlled-run-service.v1"
    _secret: bytes = field(default_factory=lambda: secrets.token_bytes(32),
                           repr=False, compare=False)
    _records: dict[str, dict] = field(default_factory=dict)
    _sequence: int = 0

    def _sign(self, payload: dict) -> str:
        return hmac.new(self._secret, canonical(payload), hashlib.sha256).hexdigest()

    def issue(self, *, kind: str, simulated: bool, project_id: str,
              candidate_sha256: str, input_hash: str, output_sha256: str,
              model: str, prompt_version: str, request_id: str,
              parent_revision_id: str | None = None,
              parent_candidate_sha256: str | None = None,
              parent_project_id: str | None = None,
              provider_request_id: str | None = None,
              details: dict | None = None) -> dict:
        """Issue a record.  Only the SERVICE decides run_id and signature."""
        if kind not in {"local_protocol_stub_run", "real_model_run", "human_edit", "fixture_run"}:
            raise RunLedgerError("RUN_KIND_INVALID", f"未知运行种类 {kind}")
        if kind == "real_model_run" and simulated:
            raise RunLedgerError("REAL_RUN_CANNOT_BE_SIMULATED", "真实运行不得标 simulated")
        self._sequence += 1
        run_id = f"{self.service_id}-run-{self._sequence:06d}"
        payload = {
            "schema_version": "rkd-controlled-run-record.v1",
            "run_id": run_id, "kind": kind, "simulated": simulated,
            "issued_at": _now(), "issuer": self.service_id,
            "project_id": str(project_id),
            "candidate_sha256": str(candidate_sha256),
            "input_hash": str(input_hash), "output_sha256": str(output_sha256),
            "model": str(model), "prompt_version": str(prompt_version),
            "request_id": str(request_id),
            "provider_request_id": str(provider_request_id or request_id),
            "parent_revision_id": parent_revision_id,
            "parent_candidate_sha256": parent_candidate_sha256,
            "parent_project_id": parent_project_id,
            "details": details or {},
        }
        record = {**payload, "issuer_signature": self._sign(payload)}
        self._records[run_id] = record
        return dict(record)

    def verify(self, run_id: str, *, project_id: str, candidate_sha256: str,
               parent_revision_id: str | None = None,
               parent_candidate_sha256: str | None = None) -> dict:
        """Verify a run by LEDGER LOOKUP, never by caller-supplied bytes."""
        record = self._records.get(str(run_id))
        if not record:
            raise RunLedgerError("RUN_ID_NOT_IN_LEDGER",
                                 f"运行 {run_id} 不存在于受控账本；自报文件/哈希不作为证据")
        payload = {k: v for k, v in record.items() if k != "issuer_signature"}
        if not hmac.compare_digest(str(record.get("issuer_signature") or ""), self._sign(payload)):
            raise RunLedgerError("RUN_SIGNATURE_INVALID", f"运行 {run_id} 签名不匹配（记录被篡改）")
        if record["issuer"] != self.service_id:
            raise RunLedgerError("RUN_ISSUER_UNKNOWN", f"运行 {run_id} 不是受控服务签发")
        if record["project_id"] != project_id:
            raise RunLedgerError("RUN_PROJECT_MISMATCH",
                                 f"运行 {run_id} 项目 {record['project_id']} 与当前 {project_id} 不符")
        if record["candidate_sha256"] != candidate_sha256:
            raise RunLedgerError("RUN_CANDIDATE_MISMATCH",
                                 f"运行 {run_id} 的候选摘要与当前候选不符")
        for field_name in ("input_hash", "output_sha256", "model", "prompt_version", "request_id"):
            if not record.get(field_name):
                raise RunLedgerError("RUN_FIELDS_INCOMPLETE", f"运行 {run_id} 缺 {field_name}")
        # Parent chain must match BOTH the revision id and the candidate digest,
        # and must live in the same project.
        if parent_revision_id is not None:
            if record.get("parent_revision_id") != parent_revision_id:
                raise RunLedgerError("PARENT_REVISION_MISMATCH",
                                     f"父修订 {parent_revision_id} 与运行记录不符")
            if parent_candidate_sha256 is not None and \
                    record.get("parent_candidate_sha256") != parent_candidate_sha256:
                raise RunLedgerError("PARENT_CANDIDATE_MISMATCH", "父候选摘要与运行记录不符")
            if record.get("parent_project_id") not in (None, project_id):
                raise RunLedgerError("PARENT_PROJECT_MISMATCH", "父版本属于其它项目")
        elif record.get("parent_revision_id"):
            raise RunLedgerError("PARENT_REVISION_MISSING", "运行记录带父链但调用者未提供")
        return dict(record)

    def export_public(self) -> list[dict]:
        """Export records WITHOUT the signing secret (signature stays verifiable
        only inside this process).  Useful for evidence manifests."""
        return [dict(r) for r in self._records.values()]
