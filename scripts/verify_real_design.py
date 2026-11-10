"""End-to-end evidence for real-model design: brief -> two candidates -> feedback.

Run with the API key only in the process environment (never written to disk):

    RKD_AI_API_KEY=... python scripts/verify_real_design.py

The real language model performs requirement understanding, concept design and
feedback revision. The program still performs geometry validation, quantity
calculation, drawing and all responsibility boundaries. No project source
documents or parsed file contents are sent to the model by default.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))

from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402

ORG = "org-local"
STAMP = "2026-11-10"
NATURAL_LANGUAGE = "开放交流与展示，入口在左侧，暖木色，保留独立洽谈"
FEEDBACK = "更开放一些，但保留入口和主展台"

MODEL_ENV = {
    "RKD_AI_PROVIDER": "openai-compatible",
    "RKD_AI_DESIGN_PROVIDER": "openai-compatible",
    "RKD_AI_BASE_URL": "https://api.codelink.chat/v1",
    "RKD_AI_MODEL": "gpt-5.6-sol",
    "RKD_AI_EXTERNAL_CONTEXT": "false",
    "RKD_AI_TIMEOUT_SECONDS": "180",
    "RKD_AI_DESIGN_MAX_ATTEMPTS": "3",
    "RKD_AI_DESIGN_MAX_OUTPUT_TOKENS": "6000",
}


def main() -> int:
    key = (os.environ.get("RKD_AI_API_KEY") or "").strip()
    if not key:
        print("RKD_AI_API_KEY must be provided in the process environment", flush=True)
        return 2
    started = time.monotonic()
    evidence = ROOT / "var" / "evidence" / "real-design" / STAMP / (
        "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3))
    evidence.mkdir(parents=True)
    run_log = evidence / "model-runs"
    env = {**MODEL_ENV, "RKD_AI_API_KEY": key, "RKD_AI_RUN_LOG_DIR": str(run_log)}
    os.environ.update(env)
    runtime = evidence / "runtime"
    runtime.mkdir()
    db = runtime / "app.sqlite3"
    store = SQLiteStore(db)
    files = FileService(db, runtime)
    service = ApiService(MVPApp(store), files, runtime_root=runtime)
    files.seed_ningbo(service, ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09")
    report: dict = {"schema_version": "rkd-real-design-verification.v1",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "model": MODEL_ENV["RKD_AI_MODEL"], "base_url": MODEL_ENV["RKD_AI_BASE_URL"],
                    "external_context_allowed": False,
                    "input_natural_language": NATURAL_LANGUAGE, "feedback": FEEDBACK,
                    "steps": {}, "boundaries": [
                        "API key only in process environment; never written to a file, log, database or Git",
                        "no project source document, parsed file text or project decision sent to the model",
                        "geometry validation, quantities and drawings remain program-determined",
                        "candidates never trigger production sync, purchase order, formal quote or release"]}
    try:
        # 1) Real model understands the requirement and writes the brief.
        brief_job = service.submit_ai_requirement(ORG, NINGBO_PROJECT_ID, "real-design-qa",
                                                  {"natural_language": NATURAL_LANGUAGE},
                                                  "real-brief-0001")["item"]
        service.ai_requirement_service.wait_for_job(ORG, NINGBO_PROJECT_ID, brief_job["job_id"], 180)
        brief_state = service.get_ai_requirement_status(ORG, NINGBO_PROJECT_ID)
        job = service.ai_requirement_service.get_job(ORG, NINGBO_PROJECT_ID, brief_job["job_id"])["item"]
        assert job["status"] == "succeeded", f"real brief failed: {job.get('error_code')} {job.get('error_message')}"
        brief = brief_state["item"]["brief"]["brief"]
        report["steps"]["requirement_understanding"] = {
            "job_id": brief_job["job_id"], "status": job["status"],
            "runs": [{k: v for k, v in run.items() if k in {"status", "usage", "error", "provider_request_id"}}
                     for run in job["runs"]],
            "requirements": [str(item.get("statement", ""))[:160] for item in brief.get("requirements", [])],
            "design_intent": [str(item.get("statement", ""))[:160] for item in brief.get("design_intent", [])],
            "conflicts": [str(item.get("statement", ""))[:160] for item in brief.get("conflicts", [])],
            "source_status": brief.get("project_context", {}).get("source_status"),
            "real_model": brief["generation"]["real_model"],
        }
        assert brief["generation"]["real_model"] is True

        # 2) Real model designs two genuinely different spatial organisations.
        option_set = service.submit_ai_design_options(ORG, NINGBO_PROJECT_ID, "real-design-qa", {},
                                                      "real-options-0001")["item"]
        service.ai_design_option_service.wait_for_set(ORG, NINGBO_PROJECT_ID, option_set["set_id"], 600)
        option_state = service.get_ai_design_options(ORG, NINGBO_PROJECT_ID)
        set_status = next(item for item in option_state["sets"] if item["set_id"] == option_set["set_id"])
        assert set_status["status"] == "succeeded", f"real design failed: {set_status.get('error_message')}"
        options = option_state["item"]["options"]
        report["steps"]["concept_design"] = {
            "set_id": option_set["set_id"], "status": set_status["status"],
            "provider": option_state["provider"],
            "candidates": [{
                "strategy_id": item["strategy"]["strategy_id"],
                "statement": item["strategy"]["statement"][:400],
                "tradeoffs": item["strategy"]["tradeoffs"],
                "circulation": item["model"]["circulation"]["kind"],
                "entrance": item["model"]["boundary"]["entrance"]["side"],
                "zones": [obj["name"] for obj in item["model"]["objects"] if obj["kind"] == "functional_zone"],
                "object_count": len(item["model"]["objects"]),
                "materials": [m["material_id"] for m in item["model"]["materials"]],
                "path_segments": len(item["model"]["circulation"]["segments"]),
                "validation": item["validation"]["status"],
                "real_model": item["model"]["generation"]["real_model"],
                "source_kind": item["source_kind"],
                "svg_sha256": next(a["sha256"] for a in item["artifacts"] if a["artifact_kind"] == "layout_svg"),
            } for item in options],
        }
        assert len(options) >= 2
        assert all(item["model"]["generation"]["real_model"] for item in options)
        assert all(item["validation"]["status"] == "passed" for item in options)
        assert len({item["strategy"]["strategy_id"] for item in options}) >= 2

        # 3) Real model revises one candidate from natural-language feedback.
        target = options[0]
        revised = service.revise_ai_design_option(
            ORG, NINGBO_PROJECT_ID, "real-design-qa",
            {"option_id": target["option_id"], "expected_revision": 1,
             "feedback": FEEDBACK, "locks": ["entrance", "display"]})
        report["steps"]["feedback_revision"] = {
            "option_id": target["option_id"], "revision_no": revised["item"]["revision_no"],
            "source_kind": revised["item"]["source_kind"],
            "interpretation_method": revised["item"]["model"]["feedback"]["interpretation_method"],
            "parsed_intents": revised["item"]["model"]["feedback"]["parsed_intents"],
            "diff": revised["diff"][:12], "diff_count": len(revised["diff"]),
            "conflicts": revised["conflicts"],
            "real_model": revised["item"]["model"]["generation"]["real_model"],
            "validation": revised["item"]["validation"]["status"],
        }
        assert revised["item"]["source_kind"] == "human_feedback"
        assert revised["item"]["model"]["generation"]["real_model"] is True
        assert revised["item"]["validation"]["status"] == "passed"

        # 4) Same-source downstream chain still works from a real-model candidate.
        # Feedback created a new revision; adoption must use the current one.
        service.adopt_ai_design_option(ORG, NINGBO_PROJECT_ID, "real-design-qa",
                                       {"option_id": target["option_id"],
                                        "expected_revision": int(revised["item"]["revision_no"]),
                                        "expected_version": 0})
        development_job = service.submit_ai_development(ORG, NINGBO_PROJECT_ID, "real-design-qa",
                                                        {"expected_version": 1, "settings": {}},
                                                        "real-development-0001")["item"]
        service.ai_development_service.wait_for_job(ORG, NINGBO_PROJECT_ID, development_job["job_id"])
        service.submit_ai_technical_delivery(ORG, NINGBO_PROJECT_ID, "real-design-qa", {},
                                              "real-technical-0001")
        technical = service.get_ai_technical_delivery(ORG, NINGBO_PROJECT_ID)
        report["steps"]["same_source_downstream"] = {
            "development_status": service.get_ai_development(ORG, NINGBO_PROJECT_ID)["item"]["status"],
            "technical_status": technical["item"]["status"],
            "technical_artifacts": len(technical["item"]["artifacts"]),
            "professional_review": technical["professional_review"],
            "formal_quote": technical["formal_quote"], "construction_issue": technical["construction_issue"],
        }

        # 5) Model run ledger: real usage and cost status, no secrets.
        ledger = run_log / "design-model-runs.jsonl"
        runs = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        report["model_runs"] = {
            "count": len(runs),
            "total_input_tokens": sum((run.get("usage") or {}).get("input_tokens") or 0 for run in runs),
            "total_output_tokens": sum((run.get("usage") or {}).get("output_tokens") or 0 for run in runs),
            "cost_known_status": "unknown",
            "entries": [{k: run.get(k) for k in ("kind", "attempt", "status", "usage", "model",
                                                  "prompt_version", "adapter_version", "provider_request_id")}
                        for run in runs],
        }
        ledger_copy = evidence / "design-model-runs.jsonl"
        ledger_copy.write_text(ledger.read_text(encoding="utf-8"), encoding="utf-8")
        report["passed"] = True
    except BaseException as error:
        report["passed"] = False
        report["error"] = f"{type(error).__name__}: {error}"
        ledger = run_log / "design-model-runs.jsonl"
        if ledger.exists():
            (evidence / "design-model-runs.jsonl").write_text(ledger.read_text(encoding="utf-8"), encoding="utf-8")
    finally:
        service.ai_requirement_service.wait_for_idle()
        service.ai_design_option_service.wait_for_idle()
        service.ai_development_service.wait_for_idle()
        store.close()
        report["duration_seconds"] = round(time.monotonic() - started, 2)
        (evidence / "verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"evidence": str(evidence / "verification.json"), "passed": report.get("passed"),
                          "steps": list(report["steps"]), "error": report.get("error")},
                         ensure_ascii=False, indent=2), flush=True)
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
