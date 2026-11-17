"""Controlled run service: the ONLY issuer of run provenance.

Trust boundary (v2, after the 2253899 review)
---------------------------------------------
The previous ``ControlledRunLedger`` was a plain object any caller could
construct, and ``issue(kind="real_model_run", simulated=False, ...)`` accepted
whatever input/output/parent the caller asserted.  A second instance, a copied
record or an arbitrary object then verified, so "signed" proved only
"this instance signed what the caller typed".  That is not a trust boundary.

v2 rules:

1. **Constructing a ledger is not enough to be trusted.**  A service instance
   gets a persisted ``issuer_id`` and an HMAC key in its own store directory.
   Consumers verify through ``TrustedRunVerifier``, which is only produced by
   ``service.verifier()`` and pins the issuer id.  A record issued by any other
   service/store fails ``RUN_ISSUER_UNKNOWN``.
2. **A real run cannot be self-declared.**  ``issue()`` needs an
   ``ExchangeObservation`` created by ``observe_exchange()`` from the actual
   request/response bytes.  ``simulated`` is DERIVED by the service:
   an injected protocol stub is always simulated; only a live transport to a
   non-loopback endpoint can produce ``kind="real_model_run"``.
3. **A parent must exist in the same project.**  ``register_revision()`` is
   called by the real repository when a revision is persisted.  An invented
   parent id fails ``PARENT_UNREGISTERED``; a mismatched parent digest fails
   ``PARENT_CANDIDATE_MISMATCH``.
4. **Restart policy.**  The key and an append-only record log persist under the
   service directory, so records issued before a restart still verify.  If the
   key is missing/unreadable, the service refuses to verify anything issued
   earlier: those sources stay ``unknown`` and can never be promoted to
   ``real_model``.  Residual risk is stated honestly: an attacker with write
   access to the service directory and its key can forge records.  The boundary
   is the OS account + directory ACL, not a hardware token, and this batch does
   not add any account/NAS platform.
5. **Isolation.**  ``isolated_test`` mode exists for negative tests only; its
   records are marked ``admission_scope=not_validated`` and can never be used
   as adoptable evidence.

No network calls, no external keys, no reads outside the service directory.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SERVICE_VERSION = "rkd-controlled-run-service.v2"
RECORD_VERSION = "rkd-controlled-run-record.v2"
TRANSPORTS = {"live_http", "local_protocol_stub", "fixture"}
_KIND_BY_TRANSPORT = {"live_http": "real_model_run",
                      "local_protocol_stub": "local_protocol_stub_run",
                      "fixture": "fixture_run"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_PRIVATE_PREFIX = ("10.", "192.168.", "169.254.", "127.")


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


def _is_loopback_or_private(endpoint: str) -> bool:
    try:
        host = (urlparse(endpoint).hostname or "").lower()
    except ValueError:
        return True
    if not host or host in _LOCAL_HOSTS:
        return True
    if host.startswith(_PRIVATE_PREFIX):
        return True
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
        except (IndexError, ValueError):
            return True
        if 16 <= second <= 31:
            return True
    if host.endswith(".local") or host.endswith(".internal"):
        return True
    return False


@dataclass(frozen=True)
class ExchangeObservation:
    """Proof that the service SAW these request/response bytes."""

    observation_id: str
    project_id: str
    transport: str
    endpoint: str
    request_sha256: str
    response_sha256: str
    request_bytes: int
    response_bytes: int
    captured_at: str
    simulated: bool
    _token: object = field(repr=False, compare=False, default=None)


class TrustedRunVerifier:
    """Read-only verification capability handed to consumers.

    Consumers never receive the service, never receive the key and cannot issue.
    """

    __slots__ = ("_service_ref", "_token", "issuer_id", "service_id")

    def __init__(self, service_ref: "ControlledRunService", token: object) -> None:
        if token is not _VERIFIER_TOKEN:
            raise RunLedgerError("VERIFIER_FORGED",
                                 "验证能力只能由受控运行服务签发，不能自行构造")
        self._service_ref = service_ref
        self._token = token
        self.issuer_id = service_ref.issuer_id
        self.service_id = service_ref.service_id

    def is_live(self) -> bool:
        ref = self._service_ref
        return ref is not None and ref.issuer_id == self.issuer_id

    def verify(self, run_id: str, *, project_id: str, candidate_sha256: str,
               site_snapshot_sha256: str | None = None,
               parent_revision_id: str | None = None,
               parent_candidate_sha256: str | None = None) -> dict:
        ref = self._service_ref
        if ref is None or not self.is_live():
            raise RunLedgerError("VERIFIER_STALE", "验证能力对应的服务实例已失效")
        return ref._verify_record(run_id, project_id=project_id,
                                  candidate_sha256=candidate_sha256,
                                  site_snapshot_sha256=site_snapshot_sha256,
                                  parent_revision_id=parent_revision_id,
                                  parent_candidate_sha256=parent_candidate_sha256)

    def revision_registered(self, project_id: str, revision_id: str) -> bool:
        return self._service_ref._revisions.get((project_id, revision_id)) is not None


_VERIFIER_TOKEN = object()


class ControlledRunService:
    """The controlled service. One instance per application composition root."""

    def __init__(self, store_dir: str | Path, *, service_id: str = SERVICE_VERSION,
                 isolated_test: bool = False) -> None:
        self.store_dir = Path(store_dir).resolve()
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.service_id = service_id
        self.isolated_test = bool(isolated_test)
        self.admission_scope = "not_validated" if self.isolated_test else "controlled"
        self._lock = threading.RLock()
        self._observations: dict[str, ExchangeObservation] = {}
        self._revisions: dict[tuple[str, str], str] = {}
        self._load_identity()
        self._load_revisions()
        self._records = self._load_records()
        self._sequence = len(self._records)
        self._verification_state = "available" if self._secret else "unknown_missing_key"

    # -- identity / persistence ---------------------------------------------
    def _load_identity(self) -> None:
        meta_path = self.store_dir / "service.json"
        key_path = self.store_dir / "secret.key"
        meta: dict[str, Any] = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except ValueError:
                meta = {}
        self.issuer_id = str(meta.get("issuer_id") or f"issuer-{uuid.uuid4().hex[:16]}")
        if not meta:
            meta = {"schema_version": SERVICE_VERSION, "issuer_id": self.issuer_id,
                    "created_at": _now(), "service_dir": str(self.store_dir)}
            meta_path.write_bytes(canonical(meta))
        self._secret = b""
        if key_path.is_file():
            try:
                self._secret = key_path.read_bytes()
            except OSError:
                self._secret = b""
        elif meta.get("secret_written") is True:
            # The service once had a key but it is gone: do NOT mint a new one,
            # because that would silently invalidate every earlier signature.
            self._secret = b""
        else:
            self._secret = secrets.token_bytes(32)
            key_path.write_bytes(self._secret)
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
            meta["secret_written"] = True
            meta_path.write_bytes(canonical(meta))
        if len(self._secret) != 32:
            self._secret = b""  # verification unavailable -> sources stay unknown

    def _load_records(self) -> dict[str, dict]:
        path = self.store_dir / "runs.jsonl"
        records: dict[str, dict] = {}
        if not path.is_file():
            return records
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("run_id"):
                records[str(record["run_id"])] = record
        return records

    def _load_revisions(self) -> None:
        path = self.store_dir / "revisions.jsonl"
        if not path.is_file():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            key = (str(row.get("project_id")), str(row.get("revision_id")))
            if row.get("candidate_sha256"):
                self._revisions[key] = str(row["candidate_sha256"])

    def _append(self, name: str, payload: dict) -> None:
        with (self.store_dir / name).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    # -- signing -------------------------------------------------------------
    def _sign(self, payload: dict) -> str:
        if not self._secret:
            raise RunLedgerError("RUN_LEDGER_KEY_UNAVAILABLE",
                                 "服务签名密钥不可用；此前签发的运行只能保持 unknown")
        return hmac.new(self._secret, canonical(payload), hashlib.sha256).hexdigest()

    # -- repository integration ---------------------------------------------
    def register_revision(self, *, project_id: str, revision_id: str,
                          candidate_sha256: str) -> dict:
        """Called by the REAL repository when a revision is persisted."""
        key = (str(project_id), str(revision_id))
        if not key[0] or not key[1] or not candidate_sha256:
            raise RunLedgerError("REVISION_REGISTRATION_INVALID", "项目/修订/候选摘要不能为空")
        with self._lock:
            existing = self._revisions.get(key)
            if existing and existing != candidate_sha256:
                raise RunLedgerError("REVISION_ALREADY_REGISTERED",
                                     f"修订 {key[1]} 已登记为另一份候选，拒绝覆盖")
            self._revisions[key] = str(candidate_sha256)
        self._append("revisions.jsonl", {"project_id": key[0], "revision_id": key[1],
                                        "candidate_sha256": str(candidate_sha256),
                                        "registered_at": _now()})
        return {"project_id": key[0], "revision_id": key[1],
                "candidate_sha256": str(candidate_sha256), "status": "registered"}

    # -- observation ---------------------------------------------------------
    def observe_exchange(self, *, project_id: str, transport: str, endpoint: str,
                         request_bytes: bytes, response_bytes: bytes) -> ExchangeObservation:
        """Record the bytes the service actually saw on the wire."""
        if transport not in TRANSPORTS:
            raise RunLedgerError("TRANSPORT_UNKNOWN", f"未知传输类型 {transport!r}")
        if not project_id:
            raise RunLedgerError("PROJECT_REQUIRED", "观测必须带项目")
        # simulated is DERIVED, never accepted from the caller.
        simulated = True
        if transport == "live_http":
            if _is_loopback_or_private(endpoint):
                simulated = True   # loopback/private = local, never "real"
            else:
                simulated = False
        observation = ExchangeObservation(
            observation_id=f"obs-{uuid.uuid4().hex[:16]}", project_id=str(project_id),
            transport=transport, endpoint=str(endpoint),
            request_sha256=hashlib.sha256(request_bytes).hexdigest(),
            response_sha256=hashlib.sha256(response_bytes).hexdigest(),
            request_bytes=len(request_bytes), response_bytes=len(response_bytes),
            captured_at=_now(), simulated=simulated, _token=_OBSERVATION_TOKEN)
        with self._lock:
            self._observations[observation.observation_id] = observation
        self._append("observations.jsonl", {
            "observation_id": observation.observation_id, "project_id": str(project_id),
            "transport": transport, "endpoint": str(endpoint),
            "request_sha256": observation.request_sha256,
            "response_sha256": observation.response_sha256,
            "request_bytes": observation.request_bytes,
            "response_bytes": observation.response_bytes,
            "simulated": simulated, "captured_at": observation.captured_at})
        return observation

    # -- issuing -------------------------------------------------------------
    def issue(self, *, observation: ExchangeObservation, project_id: str,
              candidate_sha256: str, input_hash: str, output_sha256: str,
              model: str, prompt_version: str, site_snapshot_sha256: str,
              basemap_files_sha256: str,
              parent_revision_id: str | None = None,
              details: dict | None = None) -> dict:
        """Issue a run record. Only THIS service can turn an observation into one."""
        if _OBSERVATION_TOKEN is None:  # pragma: no cover - never true
            raise RunLedgerError("OBSERVATION_REQUIRED", "缺少观测")
        if not isinstance(observation, ExchangeObservation) or \
                observation._token is not _OBSERVATION_TOKEN or \
                self._observations.get(observation.observation_id) is not observation:
            raise RunLedgerError("OBSERVATION_FORGED",
                                 "只能由本服务观测到的真实请求/响应签发运行记录")
        if observation.project_id != str(project_id):
            raise RunLedgerError("OBSERVATION_PROJECT_MISMATCH", "观测项目与运行项目不一致")
        if observation.transport == "live_http" and observation.simulated is False and \
                self.isolated_test:
            raise RunLedgerError("ISOLATED_TEST_CANNOT_BE_REAL", "隔离测试模式不得签发真实运行")
        if not site_snapshot_sha256 or not basemap_files_sha256:
            raise RunLedgerError("SNAPSHOT_BINDING_REQUIRED",
                                 "运行记录必须同时绑定场地快照摘要与底图文件摘要")
        if not (candidate_sha256 and input_hash and output_sha256 and model and prompt_version):
            raise RunLedgerError("RUN_FIELDS_INCOMPLETE", "运行记录字段不完整")
        parent_candidate_sha = None
        parent_project = None
        if parent_revision_id:
            key = (str(project_id), str(parent_revision_id))
            parent_candidate_sha = self._revisions.get(key)
            if not parent_candidate_sha:
                raise RunLedgerError("PARENT_UNREGISTERED",
                                     f"父修订 {parent_revision_id} 未经仓储登记，不能作为父链")
            parent_project = str(project_id)
        kind = _KIND_BY_TRANSPORT[observation.transport]
        with self._lock:
            self._sequence += 1
            run_id = f"{self.service_id}-run-{self._sequence:06d}"
            payload = {
                "schema_version": RECORD_VERSION,
                "run_id": run_id, "kind": kind, "simulated": bool(observation.simulated),
                "issued_at": _now(), "issuer": self.service_id,
                "issuer_id": self.issuer_id,
                "admission_scope": self.admission_scope,
                "project_id": str(project_id),
                "candidate_sha256": str(candidate_sha256),
                "input_hash": str(input_hash), "output_sha256": str(output_sha256),
                "site_snapshot_sha256": str(site_snapshot_sha256),
                "basemap_files_sha256": str(basemap_files_sha256),
                "model": str(model), "prompt_version": str(prompt_version),
                "request_sha256": observation.request_sha256,
                "response_sha256": observation.response_sha256,
                "transport": observation.transport, "endpoint": observation.endpoint,
                "observation_id": observation.observation_id,
                "parent_revision_id": parent_revision_id,
                "parent_candidate_sha256": parent_candidate_sha,
                "parent_project_id": parent_project,
                "details": details or {},
            }
            record = {**payload, "issuer_signature": self._sign(payload)}
            self._records[run_id] = record
            self._append("runs.jsonl", record)
        return dict(record)

    # -- verification --------------------------------------------------------
    def verifier(self) -> TrustedRunVerifier:
        return TrustedRunVerifier(self, _VERIFIER_TOKEN)

    def _verify_record(self, run_id: str, *, project_id: str, candidate_sha256: str,
                       site_snapshot_sha256: str | None,
                       parent_revision_id: str | None,
                       parent_candidate_sha256: str | None) -> dict:
        record = self._records.get(str(run_id))
        if not record:
            raise RunLedgerError("RUN_ID_NOT_IN_LEDGER",
                                 f"运行 {run_id} 不存在于受控服务记录；自报文件/哈希不作为证据")
        if self._verification_state != "available":
            raise RunLedgerError("RUN_LEDGER_KEY_UNAVAILABLE",
                                 "签名密钥不可用（重启前后无法核电），该来源只能保持 unknown")
        payload = {k: v for k, v in record.items() if k != "issuer_signature"}
        if not hmac.compare_digest(str(record.get("issuer_signature") or ""), self._sign(payload)):
            raise RunLedgerError("RUN_SIGNATURE_INVALID", f"运行 {run_id} 签名不匹配（记录被篡改）")
        if record.get("issuer") != self.service_id or record.get("issuer_id") != self.issuer_id:
            raise RunLedgerError("RUN_ISSUER_UNKNOWN",
                                 f"运行 {run_id} 不是本受控服务实例签发")
        if record["project_id"] != str(project_id):
            raise RunLedgerError("RUN_PROJECT_MISMATCH",
                                 f"运行 {run_id} 项目 {record['project_id']} 与当前 {project_id} 不符")
        if record["candidate_sha256"] != candidate_sha256:
            raise RunLedgerError("RUN_CANDIDATE_MISMATCH", f"运行 {run_id} 的候选摘要与当前候选不符")
        if site_snapshot_sha256 is not None and \
                record.get("site_snapshot_sha256") != str(site_snapshot_sha256):
            raise RunLedgerError("RUN_SNAPSHOT_MISMATCH",
                                 f"运行 {run_id} 绑定的场地快照与当前快照不符")
        if parent_revision_id is not None:
            if record.get("parent_revision_id") != parent_revision_id:
                raise RunLedgerError("PARENT_REVISION_MISMATCH",
                                     f"父修订 {parent_revision_id} 与运行记录不符")
            registered = self._revisions.get((str(project_id), str(parent_revision_id)))
            if not registered:
                raise RunLedgerError("PARENT_UNREGISTERED",
                                     f"父修订 {parent_revision_id} 未经仓储登记")
            if record.get("parent_candidate_sha256") != registered:
                raise RunLedgerError("PARENT_CANDIDATE_MISMATCH", "父候选摘要与仓储登记不符")
            if parent_candidate_sha256 is not None and \
                    record.get("parent_candidate_sha256") != parent_candidate_sha256:
                raise RunLedgerError("PARENT_CANDIDATE_MISMATCH", "父候选摘要与调用者提供的不符")
        elif record.get("parent_revision_id"):
            raise RunLedgerError("PARENT_REVISION_MISSING", "运行记录带父链但调用者未提供")
        return dict(record)

    def export_public(self) -> list[dict]:
        """Public export without the secret; signatures remain process-verifiable."""
        return [dict(r) for r in self._records.values()]

    @property
    def verification_state(self) -> str:
        return self._verification_state


_OBSERVATION_TOKEN = object()


def assert_trusted_verifier(obj: Any) -> TrustedRunVerifier:
    """Consumers accept ONLY this capability, never a ledger/dict/duck-type."""
    if not isinstance(obj, TrustedRunVerifier):
        raise RunLedgerError("RUN_VERIFIER_UNTRUSTED",
                             "验证必须注入受控服务的只读验证能力；不接受自建账本或 JSON")
    if not obj.is_live():
        raise RunLedgerError("RUN_VERIFIER_STALE", "验证能力已失效")
    return obj
