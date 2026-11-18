"""Same-case before/after check for the mandatory invocation scope (small follow-up).

On the reviewed baseline (9dca78b) both issuance APIs accept a candidate signed
with only an observation — i.e. "the ledger saw this exchange" — and silently
skip invocation-scope ownership.  This harness checks that omitting (or
nulling) the scope is rejected on both APIs, while the real ApiService chain
still generates and adopts a candidate.

    python scripts/w3_scope_required_findings.py --code-root <dir> \
        --label before|after --out <dir> [--expect vulnerable|fixed]
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
import tempfile
from pathlib import Path
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
ORG = "org-local"
PROJECT = "project_ningbo_xiecheng_2026"


def canon(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def real_config():
    from rkd_mvp.ai_design_option_provider import DesignOptionConfig
    return DesignOptionConfig(
        kind="openai_compatible", name="本地协议桩（模拟）", adapter_version="stub",
        prompt_version="pv", schema_version="rkd-ai-design-option.v1",
        max_candidates=2, real_model=True, configuration_errors=[],
        base_url="http://127.0.0.1:9/stub", model_id="stub-model",
        api_key_present=True, max_attempts=2, timeout_seconds=5,
        external_context_allowed=False)


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


class StubOpener:
    def open(self, request, timeout=None):
        from w3_trust_findings import candidate
        content = canon({"candidates": [candidate("branch", 10.3),
                                        candidate("loop", 10.3)]}).decode("utf-8")
        return StubResponse({"choices": [{"message": {"content": content}}],
                             "model": "stub-model", "usage": {}})


def build(directory: Path):
    from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider
    from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository
    from rkd_mvp.ai_requirement_service import AIRequirementService
    from rkd_mvp.api_service import ApiService
    from rkd_mvp.engine import MVPApp
    from rkd_mvp.file_service import FileService
    from rkd_mvp.requirement_service import RequirementService
    from rkd_mvp.sqlite_store import SQLiteStore

    db = directory / "app.sqlite3"
    store = SQLiteStore(db)
    files = FileService(db, directory)
    requirements = RequirementService(db)
    cfg = AIProviderConfig(
        kind="synthetic", name="本地合成需求通道（非真实 AI）", model_id=None,
        base_url=None, api_key_present=False, adapter_version="v1", prompt_version="pv",
        schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
        max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
        real_model=False, configuration_errors=[])
    ai = AIRequirementService(SQLiteAIRequirementRepository(db), requirements, config=cfg,
                              provider_factory=lambda config: build_provider(config))
    service = ApiService(MVPApp(store), files, requirement_service=requirements,
                         ai_requirement_service=ai, runtime_root=directory,
                         design_option_config=real_config(),
                         design_transport_opener=StubOpener())
    files.seed_ningbo(service, FIXTURE)
    brief = service.submit_ai_requirement(
        ORG, PROJECT, "tester", {"natural_language": "开放交流，入口在左侧"},
        "brief-scope-00001")["item"]
    ai.wait_for_job(ORG, PROJECT, brief["job_id"])
    return service


def attempts(runtime, model: dict, source_sha: str, other_runtime) -> dict:
    from rkd_mvp import realmodel_spatial_adapter as adapter
    from rkd_mvp.controlled_run_ledger import RunLedgerError

    runtime_kwargs = dict(
        project_id=PROJECT, revision_id="rev-scope-required0001", candidate_model=model,
        observation=last_observation(runtime), config=real_config(), input_hash="h" * 64)
    ledger_kwargs = dict(
        observation=last_observation(runtime), project_id=PROJECT,
        candidate_sha256=source_sha, input_hash="h" * 64,
        output_sha256=adapter.sha256_hex(model), model="stub-model", prompt_version="pv",
        site_snapshot_sha256="s" * 64, basemap_files_sha256="b" * 64)

    def call(fn, kwargs):
        try:
            fn(**kwargs)
            return "accepted"
        except Exception as error:  # noqa: BLE001
            return getattr(error, "code", type(error).__name__)

    detail = {
        "runtime_omitted": call(runtime.register_and_issue, runtime_kwargs),
        "runtime_none": call(runtime.register_and_issue, {**runtime_kwargs, "scope": None}),
        "ledger_omitted": call(runtime.run_service.issue, ledger_kwargs),
        "ledger_none": call(runtime.run_service.issue, {**ledger_kwargs, "scope": None}),
        "foreign_scope": call(runtime.run_service.issue,
                              {**ledger_kwargs, "scope": other_scope(other_runtime)}),
    }
    accepted = [name for name, result in detail.items() if result == "accepted"]
    detail["accepted"] = accepted
    detail["ok"] = not accepted
    return detail


def last_observation(runtime):
    runtime.bound_opener(PROJECT).open(Request("http://127.0.0.1:9/stub?scope", b"{}"))
    observations = runtime.run_service.controlled_observations(project_id=PROJECT)
    return observations[-1]


def other_scope(runtime):
    if hasattr(runtime, "begin_invocation"):
        scope = runtime.begin_invocation(PROJECT)
        scope.opener().open(Request("http://127.0.0.1:9/stub?other", b"{}"))
        return scope
    runtime.bound_opener(PROJECT).open(Request("http://127.0.0.1:9/stub?other", b"{}"))
    return runtime.run_service.controlled_observations(project_id=PROJECT)[-1]


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
    from rkd_mvp import realmodel_spatial_adapter as adapter

    directory = Path(tempfile.mkdtemp())
    service = build(directory)
    runtime = service.controlled_design_runtime
    other = build(Path(tempfile.mkdtemp()))

    set_id = service.submit_ai_design_options(
        ORG, PROJECT, "tester", {}, "options-scope-00001")["item"]["set_id"]
    service.ai_design_option_service.wait_for_set(ORG, PROJECT, set_id, timeout_seconds=120)
    state = service.get_ai_design_options(ORG, PROJECT)
    option = state["item"]["options"][0]
    controlled = option["validation"]["controlled"]
    model = controlled["source_candidate"]
    source_sha = adapter.sha256_hex(adapter.candidate_from_persisted(model)[0])

    scope_check = attempts(runtime, model, source_sha, other.controlled_design_runtime)
    adopted = service.adopt_ai_design_option(ORG, PROJECT, "tester", {
        "option_id": option["option_id"], "expected_revision": 1, "expected_version": 0})
    product_ok = bool(state["sets"][0]["status"] == "succeeded"
                      and adopted["item"]["status"] == "adopted_draft")

    summary = {"scope_required": "fixed" if scope_check["ok"] else "vulnerable"}
    audit = {
        "schema_version": "rkd-w3-scope-required.v1",
        "baseline": "9dca78b", "code_root": str(code_root), "label": args.label,
        "runtime_signature": str(inspect.signature(
            runtime.register_and_issue)),
        "ledger_signature": str(inspect.signature(runtime.run_service.issue)),
        "scope_required": scope_check,
        "product_path_also_passes": product_ok,
        "summary": summary,
        "external_calls": 0, "cost_cny": 0, "keys_used": False,
    }
    (out / "findings.json").write_bytes(canon(audit))
    print(json.dumps({"summary": summary, "product_path_also_passes": product_ok},
                     ensure_ascii=False, sort_keys=True))
    if args.expect == "vulnerable":
        return 0 if summary["scope_required"] == "vulnerable" else 2
    if args.expect == "fixed":
        return 0 if summary["scope_required"] == "fixed" and product_ok else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
