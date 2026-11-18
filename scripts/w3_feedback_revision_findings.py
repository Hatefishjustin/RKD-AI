"""Same-case before/after harness for controlled candidate feedback revision.

Drives ONLY the real ApiService public API with a real isolated SQLite store,
the real ControlledDesignRuntime and a local protocol stub.  On the frozen
baseline (902952e) the controlled feedback path is rejected with
CONTROLLED_FEEDBACK_PATH_UNSUPPORTED.  On the fixed tree the same request must
produce a NEW revision bound to a fresh invocation scope, with a new run and
admission, while the parent bytes stay unchanged.

    python scripts/w3_feedback_revision_findings.py --code-root <dir> \
        --label before|after --out <dir> [--expect vulnerable|fixed]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

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


class FeedbackStubOpener:
    """Generate -> two candidates; revise -> one changed candidate."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: list[bytes] = []

    def open(self, request, timeout=None):
        from w3_trust_findings import candidate
        body = bytes(getattr(request, "data", b"") or b"")
        payload = json.loads(body.decode("utf-8"))
        user_text = " ".join(str(message.get("content") or "")
                             for message in payload.get("messages", []))
        revising = "feedback_task" in user_text
        if revising:
            revised = candidate("loop", 10.3)
            revised["strategy_id"] = "feedback-revised"
            revised["concept"] = "反馈修订桩候选，不是设计成果"
            content = canon({"candidate": revised, "parsed_intents": ["more_open"],
                             "locked_conflicts": []}).decode("utf-8")
        else:
            content = canon({"candidates": [candidate("branch", 10.3),
                                            candidate("loop", 10.3)]}).decode("utf-8")
        response = canon({"choices": [{"message": {"content": content}}],
                          "model": payload.get("model"), "usage": {}})
        self.requests.append({"body": payload, "revising": revising,
                              "request_sha256": hashlib.sha256(body).hexdigest()})
        self.responses.append(response)
        return StubResponse(json.loads(response))


def build(code_root: Path, directory: Path, opener):
    from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider
    from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository
    from rkd_mvp.ai_requirement_service import AIRequirementService
    from rkd_mvp.ai_design_option_provider import DesignOptionConfig
    from rkd_mvp.api_service import ApiService
    from rkd_mvp.engine import MVPApp
    from rkd_mvp.file_service import FileService
    from rkd_mvp.requirement_service import RequirementService
    from rkd_mvp.sqlite_store import SQLiteStore

    db = directory / "app.sqlite3"
    store = SQLiteStore(db)
    files = FileService(db, directory)
    requirements = RequirementService(db)
    req_cfg = AIProviderConfig(
        kind="synthetic", name="本地合成需求通道（非真实 AI）", model_id=None,
        base_url=None, api_key_present=False, adapter_version="v1", prompt_version="pv",
        schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
        max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
        real_model=False, configuration_errors=[])
    ai = AIRequirementService(SQLiteAIRequirementRepository(db), requirements, config=req_cfg,
                              provider_factory=lambda config: build_provider(config))
    config = DesignOptionConfig(
        kind="openai_compatible", name="本地协议桩（模拟）", adapter_version="stub",
        prompt_version="pv", schema_version="rkd-ai-design-option.v1", max_candidates=2,
        real_model=True, configuration_errors=[], base_url="http://127.0.0.1:9/stub",
        model_id="stub-model", api_key_present=True, max_attempts=2, timeout_seconds=5,
        external_context_allowed=False)
    service = ApiService(MVPApp(store), files, requirement_service=requirements,
                         ai_requirement_service=ai, runtime_root=directory,
                         design_option_config=config, design_transport_opener=opener)
    files.seed_ningbo(service, FIXTURE)
    brief = service.submit_ai_requirement(
        ORG, PROJECT, "tester", {"natural_language": "开放交流，入口在左侧，暖木色"},
        "brief-feedback-00001")["item"]
    ai.wait_for_job(ORG, PROJECT, brief["job_id"])
    return service, store


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

    from rkd_mvp.api_service import ApiError
    from rkd_mvp import realmodel_spatial_adapter as adapter

    directory = Path(tempfile.mkdtemp())
    opener = FeedbackStubOpener()
    service, store = build(code_root, directory, opener)
    detail: dict = {"ok": False, "problems": []}

    item = service.submit_ai_design_options(
        ORG, PROJECT, "tester", {}, "options-feedback-0001")["item"]
    service.ai_design_option_service.wait_for_set(ORG, PROJECT, item["set_id"], timeout_seconds=120)
    state = service.get_ai_design_options(ORG, PROJECT)
    parent = state["item"]["options"][0]
    parent_id = parent["option_revision_id"]
    parent_model_sha = hashlib.sha256(canon(parent["model"])).hexdigest()
    parent_admission = parent["validation"].get("controlled", {}).get("admission")
    parent_admission_sha = hashlib.sha256(canon(parent_admission)).hexdigest() if parent_admission else None
    expected_version = int(state["adoption"]["expected_revision"]) if state.get("adoption") else 0
    input_hash = next(row["input_hash"] for row in state["sets"] if row["set_id"] == item["set_id"])
    detail.update({"parent_revision_id": parent_id, "parent_revision_no": parent["revision_no"],
                   "parent_model_sha256": parent_model_sha,
                   "parent_admission_sha256": parent_admission_sha,
                   "expected_version": expected_version, "input_hash": input_hash,
                   "schema": parent["model"]["schema_version"]})

    request = {"option_id": parent["option_id"], "expected_revision": parent["revision_no"],
               "parent_revision_id": parent_id, "expected_version": expected_version,
               "expected_input_hash": input_hash,
               "feedback": "更开放但保留入口", "locks": ["entrance"]}
    try:
        result = service.revise_ai_design_option(ORG, PROJECT, "tester", request)
        revision = result["item"]
        detail["result"] = {"option_revision_id": revision["option_revision_id"],
                            "revision_no": revision["revision_no"],
                            "parent_revision_id": revision["parent_revision_id"],
                            "run_id": (revision["validation"].get("controlled") or {}).get("run_id")}
        detail["ok"] = bool(revision["revision_no"] == parent["revision_no"] + 1
                            and revision["parent_revision_id"] == parent_id
                            and detail["result"]["run_id"]
                            and revision["option_revision_id"] != parent_id)
        # parent must remain byte-identical
        after = service.get_ai_design_options(ORG, PROJECT)
        same_parent = next((row for row in after["item"]["revisions"]
                            if row["option_revision_id"] == parent_id), None)
        detail["parent_unchanged"] = bool(same_parent and
            hashlib.sha256(canon(same_parent["model"])).hexdigest() == parent_model_sha)
        new_admission = (revision["validation"].get("controlled") or {}).get("admission")
        detail["fresh_admission"] = bool(new_admission and
            (not parent_admission_sha or
             hashlib.sha256(canon(new_admission)).hexdigest() != parent_admission_sha))
        detail["adoptable"] = bool((new_admission or {}).get("adoptable"))
        detail["visible_in_store"] = bool(service.get_ai_design_options(
            ORG, PROJECT)["item"]["options"] and any(
            row["option_revision_id"] == revision["option_revision_id"]
            for row in after["item"]["revisions"]))
        detail["ok"] = detail["ok"] and detail["parent_unchanged"] and detail["fresh_admission"]
    except ApiError as error:
        detail["result"] = {"error_code": error.code, "status": error.status,
                            "message": error.message}
        detail["problems"].append(f"反馈修订被拒绝：{error.code}: {error.message}")
    except Exception as error:  # noqa: BLE001
        detail["result"] = {"error": f"{type(error).__name__}: {error}"}
        detail["problems"].append("反馈修订抛出未分类异常")

    summary = "fixed" if detail["ok"] else "vulnerable"
    audit = {"schema_version": "rkd-w3-controlled-feedback.v1", "baseline": "902952e",
             "code_root": str(code_root), "label": args.label,
             "summary": summary, "detail": detail,
             "stub_revising_calls": sum(1 for item in opener.requests if item["revising"]),
             "stub_generate_calls": sum(1 for item in opener.requests if not item["revising"]),
             "external_calls": 0, "cost_cny": 0, "keys_used": False}
    (out / "findings.json").write_bytes(canon(audit))
    print(json.dumps({"summary": summary, "detail": detail,
                      "stub_revising_calls": audit["stub_revising_calls"]},
                     ensure_ascii=False, sort_keys=True))
    if args.expect == "vulnerable":
        return 0 if summary == "vulnerable" else 2
    if args.expect == "fixed":
        return 0 if summary == "fixed" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
