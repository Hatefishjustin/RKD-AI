"""Reproduce the two P1 source-record defects against a given code root.

R1 concurrent observation cross-binding
    ``AIDesignOptionService._controlled_finalize`` bound a candidate to "the last
    observation of this project", so with two concurrent provider invocations on
    the SAME project one candidate could be signed with the other invocation's
    exchange (wrong run_id / request / response / input hash binding).

R2 phantom parent revision
    ``ControlledDesignRuntime.register_and_issue`` registered the revision in the
    run ledger BEFORE the business candidate was persisted.  When the repository
    transaction was discarded, the ledger still held a parent the business
    repository never contained, so it could be claimed as a parent later.

The same harness runs on the frozen review commit (f473c92) and on the fixed
tree.  It drives ONLY the real application composition root (``ApiService``
public API), the real injected ``ControlledDesignRuntime`` and a real isolated
SQLite repository.  No private helper replaces the product entry point, no paid
model call, no real key, every exchange is a local protocol stub
(``simulated=True``).

    python scripts/w3_r1r2_findings.py --code-root <dir> \
        --label before|after --out <dir> [--expect vulnerable|fixed]
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
ORG = "org-local"
PROJECT = "project_ningbo_xiecheng_2026"


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


class StubResponse:
    def __init__(self, payload) -> None:
        self._raw = canon(payload)
        self.headers = {}
        self.status = 200

    def read(self, _n=None) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class PerCallOpener:
    """Protocol stub: the Nth call gets marker N and its exact bytes are kept.

    The first call carries a padded concept string, so its JSON parse is slow
    enough that the second invocation records its exchange while the first is
    still between "exchange recorded" and "observation read".  That is the real
    race window of the project-last binding; the fix must make it irrelevant.
    """

    def __init__(self, pad_first: int = 3_000_000) -> None:
        self.lock = threading.Lock()
        self.calls = 0
        self.pad_first = pad_first
        self.responses: list[bytes] = []
        self.requests: list[bytes] = []
        self.markers: list[str] = []

    def open(self, request, timeout=None):
        body = bytes(getattr(request, "data", b"") or b"")
        with self.lock:
            index = self.calls
            self.calls += 1
            self.requests.append(body)
        marker = "A" if index == 0 else f"B{index}"
        pad = self.pad_first if index == 0 else 0
        branch, loop = candidate("branch", 10.3), candidate("loop", 10.3)
        for item in (branch, loop):
            item["tradeoffs"] = [f"{marker}-invocation", "仅验证工程链"]
            item["concept"] = f"{marker} 桩候选" + ("p" * pad)
        content = canon({"candidates": [branch, loop]}).decode("utf-8")
        response = canon({"choices": [{"message": {"content": content}}],
                          "model": "stub-model", "usage": {}})
        with self.lock:
            self.responses.append(response)
            self.markers.append(marker)
        return StubResponse(json.loads(response))


class BlockingOpener:
    """Holds the provider call open so the harness can act on the running set."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def open(self, request, timeout=None):
        self.entered.set()
        self.release.wait(timeout=20)
        content = canon({"candidates": [candidate("branch", 10.3),
                                        candidate("loop", 10.3)]}).decode("utf-8")
        return StubResponse({"choices": [{"message": {"content": content}}],
                             "model": "stub-model", "usage": {}})


def candidate(kind: str, entrance_y: float) -> dict:
    from w3_trust_findings import candidate as base_candidate
    return base_candidate(kind, entrance_y)


def real_config():
    from rkd_mvp.ai_design_option_provider import DesignOptionConfig
    return DesignOptionConfig(
        kind="openai_compatible", name="本地协议桩（模拟）", adapter_version="stub",
        prompt_version="pv", schema_version="rkd-ai-design-option.v1",
        max_candidates=2, real_model=True, configuration_errors=[],
        base_url="http://127.0.0.1:9/stub", model_id="stub-model",
        api_key_present=True, max_attempts=2, timeout_seconds=5,
        external_context_allowed=False)


def build_service(root: Path, opener, db: Path):
    from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider
    from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository
    from rkd_mvp.ai_requirement_service import AIRequirementService
    from rkd_mvp.api_service import ApiService
    from rkd_mvp.engine import MVPApp
    from rkd_mvp.file_service import FileService
    from rkd_mvp.requirement_service import RequirementService
    from rkd_mvp.sqlite_store import SQLiteStore

    root.mkdir(parents=True, exist_ok=True)
    store = SQLiteStore(db)
    files = FileService(db, root)
    requirements = RequirementService(db)
    req_cfg = AIProviderConfig(
        kind="synthetic", name="本地合成需求通道（非真实 AI）", model_id=None,
        base_url=None, api_key_present=False, adapter_version="v1", prompt_version="pv",
        schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
        max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
        real_model=False, configuration_errors=[])
    requirement_ai = AIRequirementService(
        SQLiteAIRequirementRepository(db), requirements, config=req_cfg,
        provider_factory=lambda config: build_provider(config))
    service = ApiService(
        MVPApp(store), files, requirement_service=requirements,
        ai_requirement_service=requirement_ai, runtime_root=root,
        design_option_config=real_config(), design_transport_opener=opener)
    return service, files, requirement_ai, store


def seed(service, files, requirement_ai, key: str) -> None:
    files.seed_ningbo(service, FIXTURE)
    item = service.submit_ai_requirement(
        ORG, PROJECT, "tester",
        {"natural_language": "开放交流，入口在左侧，暖木色"}, key)["item"]
    requirement_ai.wait_for_job(ORG, PROJECT, item["job_id"])


def revisions_of(service, set_id: str) -> list[dict]:
    repository = service.ai_design_option_service.repository
    with repository.transaction(ORG, PROJECT) as tx:
        return tx.revisions_for_set(set_id)


def set_row(service, set_id: str) -> dict:
    return next(row for row in service.get_ai_design_options(ORG, PROJECT)["sets"]
                if row["set_id"] == set_id)


def stored_phase(db: Path, set_id: str):
    """Read the authoritative store directly (no writes, no recovery side effects)."""
    connection = sqlite3.connect(db, timeout=10)
    try:
        return connection.execute(
            "SELECT status, phase FROM ai_design_option_sets WHERE set_id=?",
            (set_id,)).fetchone()
    finally:
        connection.close()


def stored_revision_count(db: Path, set_id: str) -> int:
    connection = sqlite3.connect(db, timeout=10)
    try:
        return connection.execute(
            "SELECT COUNT(*) FROM ai_design_option_revisions WHERE set_id=?",
            (set_id,)).fetchone()[0]
    finally:
        connection.close()


def bind_through_runtime(runtime, project_id: str, marker: str):
    """One real controlled exchange through the runtime; returns (observation, scope)."""
    if hasattr(runtime, "begin_invocation"):
        scope = runtime.begin_invocation(project_id)
        scope.opener().open(Request(f"http://127.0.0.1:9/stub?marker={marker}", b"{}"))
        return scope.latest(), scope
    runtime.bound_opener(project_id).open(
        Request(f"http://127.0.0.1:9/stub?marker={marker}", b"{}"))
    observations = runtime.run_service.controlled_observations(project_id=project_id)
    return (observations[-1] if observations else None), None


# ------------------------------------------------------------------- R1 (a)
def check_concurrent_binding(directory: Path) -> dict:
    """Two concurrent invocations for ONE project must not cross-bind."""
    opener = PerCallOpener()
    service, files, requirement_ai, _store = build_service(directory, opener, directory / "app.sqlite3")
    seed(service, files, requirement_ai, "brief-r1-0001")
    runtime = service.controlled_design_runtime

    set_a = service.submit_ai_design_options(
        ORG, PROJECT, "tester", {}, "options-r1-aaaa")["item"]["set_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and opener.calls < 1:
        time.sleep(0.001)
    set_b = service.submit_ai_design_options(
        ORG, PROJECT, "tester", {}, "options-r1-bbbb")["item"]["set_id"]
    for set_id in (set_a, set_b):
        service.ai_design_option_service.wait_for_set(
            ORG, PROJECT, set_id, timeout_seconds=120)
    service.ai_design_option_service.wait_for_idle(timeout_seconds=30)

    records = runtime.run_service.export_public()
    by_run = {record["run_id"]: record for record in records}
    marker_of = {hashlib.sha256(raw).hexdigest(): marker
                 for raw, marker in zip(opener.responses, opener.markers)}
    from rkd_mvp import realmodel_spatial_adapter as adapter

    detail = {"ok": True, "problems": [], "sets": {}, "bound_markers": {},
              "stub_calls": opener.calls, "run_records": len(records)}
    for set_id in (set_a, set_b):
        row = set_row(service, set_id)
        revisions = revisions_of(service, set_id)
        entry = {"status": row["status"], "revisions": len(revisions), "bindings": []}
        detail["sets"][set_id[-6:]] = entry
        if row["status"] != "succeeded" or len(revisions) != 2:
            detail["problems"].append(f"{set_id[-6:]} 未成功或修订数不是 2")
            detail["ok"] = False
            continue
        markers = set()
        for revision in revisions:
            controlled = (revision["validation"] or {}).get("controlled") or {}
            record = by_run.get(controlled.get("run_id"))
            if record is None:
                detail["problems"].append(f"{set_id[-6:]} 候选缺少运行记录")
                detail["ok"] = False
                continue
            source_sha = adapter.sha256_hex(adapter.candidate_from_persisted(
                controlled.get("source_candidate"))[0])
            binding = {
                "option": revision["option_id"].rsplit(":", 1)[-1][-14:],
                "run_id": controlled.get("run_id"),
                "bound_response": marker_of.get(record.get("response_sha256"), "unknown"),
                "request_sha256": record.get("request_sha256"),
                "response_sha256": record.get("response_sha256"),
                "input_hash": record.get("input_hash"),
                "candidate_sha_matches_own_source": record.get("candidate_sha256") == source_sha,
            }
            entry["bindings"].append(binding)
            if not binding["candidate_sha_matches_own_source"]:
                detail["problems"].append(f"{set_id[-6:]} 候选摘要不是本人来源")
                detail["ok"] = False
            if record.get("input_hash") != row["input_hash"]:
                detail["problems"].append(f"{set_id[-6:]} input_hash 与本人候选集不符")
                detail["ok"] = False
            if binding["bound_response"] != "unknown":
                markers.add(binding["bound_response"])
        detail["bound_markers"][set_id[-6:]] = sorted(markers)
        if len(markers) > 1:
            detail["problems"].append(f"{set_id[-6:]} 同一候选集内不同候选绑定到不同交换")
            detail["ok"] = False
    distinct = {marker for value in detail["bound_markers"].values() for marker in value}
    if len(distinct) < 2:
        detail["problems"].append(
            "两个并发执行的调用没有分别绑定各自的交换（串线或被同一交换覆盖）")
        detail["ok"] = False
    detail["distinct_run_ids"] = len({record["run_id"] for record in records})
    return detail


# ------------------------------------------------------------------- R1 (b)
def check_invocation_scope(directory: Path) -> dict:
    """A candidate may only be signed from its OWN invocation's observation."""
    detail = {"ok": False, "problems": []}
    opener = PerCallOpener(pad_first=0)
    service, files, requirement_ai, _store = build_service(directory, opener, directory / "app.sqlite3")
    seed(service, files, requirement_ai, "brief-r1-0002")
    runtime = service.controlled_design_runtime
    detail["invocation_scope_api"] = hasattr(runtime, "begin_invocation")
    if not detail["invocation_scope_api"]:
        detail["problems"].append(
            "运行时没有按 invocation 的观测句柄：只能取项目最后一条观测，并发必然串线")
        return detail

    item = service.submit_ai_design_options(ORG, PROJECT, "tester", {}, "options-r1-cccc")["item"]
    service.ai_design_option_service.wait_for_set(ORG, PROJECT, item["set_id"], timeout_seconds=120)
    revisions = revisions_of(service, item["set_id"])
    if not revisions:
        detail["problems"].append("正例候选集没有修订")
        return detail
    model = revisions[0]["validation"]["controlled"]["source_candidate"]

    scope_a = runtime.begin_invocation(PROJECT)
    scope_b = runtime.begin_invocation(PROJECT)
    scope_a.opener().open(Request("http://127.0.0.1:9/stub?a", b"{}"))
    scope_b.opener().open(Request("http://127.0.0.1:9/stub?b", b"{}"))
    detail["scope_counts"] = [len(scope_a.observations), len(scope_b.observations)]
    detail["scopes_distinct"] = (scope_a.latest().observation_id
                                 != scope_b.latest().observation_id)

    def attempt(**kwargs):
        try:
            runtime.register_and_issue(**kwargs)
            return "accepted"
        except Exception as error:  # noqa: BLE001
            return getattr(error, "code", type(error).__name__)

    empty = runtime.begin_invocation(PROJECT)
    detail["missing_observation"] = attempt(
        project_id=PROJECT, revision_id="rev-empty-000001", candidate_model=model,
        observation=None, scope=empty, config=real_config(), input_hash="h" * 64)
    detail["foreign_observation"] = attempt(
        project_id=PROJECT, revision_id="rev-foreign-00001", candidate_model=model,
        observation=scope_b.latest(), scope=scope_a, config=real_config(),
        input_hash="h" * 64)
    accepted = attempt(
        project_id=PROJECT, revision_id="rev-own-0000001", candidate_model=model,
        observation=scope_a.latest(), scope=scope_a, config=real_config(),
        input_hash="h" * 64)
    detail["own_observation"] = accepted
    if accepted == "accepted":
        record = next(record for record in runtime.run_service.export_public()
                      if (record.get("details") or {}).get("revision_id") == "rev-own-0000001")
        detail["own_binds_own_exchange"] = (
            record["observation_id"] == scope_a.latest().observation_id
            and record["response_sha256"] == scope_a.latest().response_sha256)
        detail["own_run_id"] = record["run_id"]
    else:
        detail["own_binds_own_exchange"] = False

    for name, value in (("missing_observation", detail["missing_observation"]),
                        ("foreign_observation", detail["foreign_observation"])):
        if value == "accepted":
            detail["problems"].append(f"{name} 被接受，未 fail closed")
    if not detail["own_binds_own_exchange"]:
        detail["problems"].append("本 invocation 的签发没有绑定自己的交换")
    detail["ok"] = not detail["problems"]
    return detail


# ---------------------------------------------------------------------- R2
def check_phantom_parent(directory: Path) -> dict:
    """A revision the business repository never kept must not become a parent."""
    detail = {"ok": False, "problems": []}
    db = directory / "app.sqlite3"
    healthy = PerCallOpener(pad_first=0)
    service, files, requirement_ai, _store = build_service(directory / "healthy", healthy, db)
    seed(service, files, requirement_ai, "brief-r2-0001")
    runtime = service.controlled_design_runtime

    ok_set = service.submit_ai_design_options(
        ORG, PROJECT, "tester", {}, "options-r2-okok")["item"]["set_id"]
    service.ai_design_option_service.wait_for_set(ORG, PROJECT, ok_set, timeout_seconds=120)
    ok_rows = revisions_of(service, ok_set)
    detail["healthy_set"] = {"status": set_row(service, ok_set)["status"],
                             "revisions": len(ok_rows)}
    if not ok_rows:
        detail["problems"].append("正常候选集没有修订，无法继续")
        return detail
    model = ok_rows[0]["validation"]["controlled"]["source_candidate"]
    detail["healthy_registered"] = len(
        [key for key in getattr(runtime.run_service, "_revisions", {}) if key[0] == PROJECT])

    # Force the business transaction to be discarded AFTER the controlled
    # finalize: a second composition root over the same store reclaims the
    # running set (WORKER_RESTARTED) as soon as the worker enters its outputs
    # phase, so the worker's insert never commits.
    blocking = BlockingOpener()
    owner, _owner_files, _owner_ai, _owner_store = build_service(
        directory / "owner", blocking, db)
    shadow, _shadow_files, _shadow_ai, _shadow_store = build_service(
        directory / "shadow", BlockingOpener(), db)
    owner_runtime = owner.controlled_design_runtime
    bad_set = owner.submit_ai_design_options(
        ORG, PROJECT, "tester", {}, "options-r2-bad0")["item"]["set_id"]
    if not blocking.entered.wait(timeout=20):
        detail["problems"].append("阻塞桩没有被调用")
        return detail
    blocking.release.set()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        row = stored_phase(db, bad_set)
        if row and row[1] == "outputs":
            break
    shadow.get_ai_design_options(ORG, PROJECT)   # reclaim the abandoned running set
    for _ in range(400):
        row = stored_phase(db, bad_set)
        if row and row[0] in {"failed", "cancelled", "succeeded"}:
            break
        time.sleep(0.01)
    time.sleep(0.3)

    bad_row = stored_phase(db, bad_set)
    bad_revisions = stored_revision_count(db, bad_set)
    ledger_registered = [key for key in getattr(owner_runtime.run_service, "_revisions", {})
                         if str(key[0]) == PROJECT]
    records = owner_runtime.run_service.export_public()
    detail.update({
        "failed_set": {"status": (bad_row or [None])[0],
                       "phase": (bad_row or [None, None])[1],
                       "business_revisions": bad_revisions},
        "ledger_registered": len(ledger_registered),
        "run_records": len(records),
    })
    if bad_revisions:
        detail["problems"].append("被丢弃的候选集仍写入了业务修订")
    if ledger_registered:
        detail["problems"].append(
            f"业务仓储没有对应修订，账本仍登记了 {len(ledger_registered)} 条父修订（幽灵父修订）")

    target = ledger_registered[0][1] if ledger_registered else None
    if target is None:
        for record in records:
            candidate_id = (record.get("details") or {}).get("revision_id")
            if candidate_id:
                target = candidate_id
    detail["parent_attempt_target"] = target
    if target is None:
        detail["problems"].append("无法取得本次失败尝试的修订号，父链负例无法执行")
        return detail

    observation, scope = bind_through_runtime(owner_runtime, PROJECT, "parent-attempt")
    kwargs = {"project_id": PROJECT, "revision_id": "rev-child-000001",
              "candidate_model": model, "observation": observation,
              "config": real_config(), "input_hash": "h" * 64,
              "parent_revision_id": target}
    if scope is not None:
        kwargs["scope"] = scope
    try:
        owner_runtime.register_and_issue(**kwargs)
        detail["parent_attempt"] = "accepted"
        detail["problems"].append("以未持久化的修订作为父链被接受（幽灵父修订可用）")
    except Exception as error:  # noqa: BLE001
        detail["parent_attempt"] = getattr(error, "code", type(error).__name__)
    detail["ok"] = (not detail["problems"]
                    and detail["parent_attempt"] not in {"accepted", None})
    return detail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-root", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--expect", choices=("vulnerable", "fixed"), default=None)
    args = ap.parse_args()
    code_root = Path(args.code_root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for path in (code_root / "mvp", code_root, ROOT / "scripts"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    from rkd_mvp.api_service import ApiService
    parameters = inspect.signature(ApiService.__init__).parameters
    tools = Path(tempfile.mkdtemp())
    results = {
        "R1-binding": check_concurrent_binding(tools / "r1-binding"),
        "R1-scope": check_invocation_scope(tools / "r1-scope"),
        "R2-phantom": check_phantom_parent(tools / "r2"),
    }
    summary = {name: ("fixed" if value.get("ok") else "vulnerable")
               for name, value in results.items()}
    audit = {"schema_version": "rkd-w3-r1r2-source-records.v1",
             "baseline": "f473c92", "code_root": str(code_root), "label": args.label,
             "composition_root_seams": [name for name in parameters],
             "results": results, "summary": summary,
             "external_calls": 0, "cost_cny": 0, "keys_used": False}
    (out / "findings.json").write_bytes(canon(audit))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    if args.expect == "vulnerable":
        return 0 if all(value == "vulnerable" for value in summary.values()) else 2
    if args.expect == "fixed":
        return 0 if all(value == "fixed" for value in summary.values()) else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
