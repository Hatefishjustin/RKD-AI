"""W0 reproduction of R1 / R2 / R3 (docs/26 section 2).

This script OBSERVES behaviour; it never asserts a fix. Run `--phase before`
before editing code and `--phase after` afterwards. Historical review-packet
evidence is read-only; all store/HTTP work uses an isolated temp database.

No external model/image calls, no key, no cost. All model answers come from the
explicitly labelled local stub in scripts/verify_studio_loop.py.
"""
from __future__ import annotations

import argparse
import copy
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "var" / "evidence" / "roadmap" / "W0-收口"
RUNTIME = EVIDENCE / "runtime"

# isolation MUST be set before importing studio.store (it reads DB_PATH at import)
RUNTIME.mkdir(parents=True, exist_ok=True)
_phase_hint = "after" if "--phase" in sys.argv and sys.argv[sys.argv.index("--phase") + 1:sys.argv.index("--phase") + 2] == ["after"] else "before"
os.environ["RKD_STUDIO_DB"] = str(RUNTIME / f"repro-{_phase_hint}.db")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from arc_first_batch_stub import SITE, review_issues, valid_proposal  # noqa: E402
from rkd_mvp.studio import orchestrator, revision as revision_mod, server as studio_server, validation, vision  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402
import verify_studio_loop as vsl  # noqa: E402

FAKE_JPEG = vsl.FAKE_JPEG
PID = "ningbo-xiecheng"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _head_commit() -> str:
    p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True,
                       text=True, errors="replace")
    return (p.stdout or "").strip()


def _commits() -> list[dict]:
    p = subprocess.run(["git", "log", "-3", "--format=%h|%cI|%s"], cwd=str(ROOT),
                       capture_output=True, text=True, errors="replace")
    out = []
    for line in (p.stdout or "").strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            out.append({"commit": parts[0], "committed_at": parts[1], "subject": parts[2]})
    return out


def _case(cid: str, description: str, observed: dict, defect_present: bool) -> dict:
    return {"id": cid, "description": description, "observed": observed,
            "defect_present": bool(defect_present),
            "verdict": "defect_confirmed" if defect_present else "not_reproduced"}


# --------------------------------------------------------------------- R1 ----
def r1_static() -> list[dict]:
    scen = inspect.getsource(orchestrator.Studio._scenario)
    post = inspect.getsource(studio_server.Handler.do_POST)
    # Whether the revision input still carries the baseline pointers / locks.
    # (A source-level check; the behavioural proof is R1-b / R1-c.)
    flat = sorted({k for k in ("baseline_artifact_id", "baseline_revision_uid",
                               "baseline_selection", "locks", "objectives",
                               "consumed_by_run") if f'"{k}"' in scen})
    has_revise_entry = "task_kind" in scen or "resolve_task" in scen
    reads_user_baseline = 'body.get("baseline_artifact_id")' in post
    return [
        _case("R1-a", "_scenario 是否区分 generate / revise 任务，还是无条件重新生成 A/B",
              {"unconditional_A_B_loop": 'for opt in ("A", "B")' in scen,
               "generate_revise_task_resolution_present": has_revise_entry,
               "boss_feedback_fields": flat,
               "baseline_pointer_in_boss_feedback": any(
                   k in flat for k in ("baseline_artifact_id", "baseline_revision_uid")),
               "user_specified_baseline_read_by_HTTP_messages": reads_user_baseline},
              defect_present=('for opt in ("A", "B")' in scen and not has_revise_entry)
              or not reads_user_baseline),
    ]


def r1_dynamic(st: Store) -> list[dict]:
    """Two loops with the local stub: feedback names an OLD baseline, then run again."""
    studio = orchestrator.Studio(st)
    studio.seed_from_fixtures()
    orchestrator.Client = vsl.FakeClient
    vision.svg_to_jpeg = lambda svg, limit=720: FAKE_JPEG
    vision.reference_jpeg = lambda limit=720: FAKE_JPEG

    studio.run_a1(PID, background=False)  # run 1 = generate
    first = [a for a in st.artifacts(PID)
             if a["kind"] == "spatial-plan" and a["contract_status"] == "valid_candidate"]
    a1 = next((a for a in first if a["option_id"] == "A" and a["revision"] == 1), None)
    if not a1:
        return [_case("R1-b", "首轮 generate 产出有效候选 A", {"valid_A_found": False}, True)]
    groups_before = {a["candidate_group_id"] for a in st.artifacts(PID)}

    fb = st.add_feedback(
        PID, "boss_message", "把主动线净宽扩大到 2100mm，保留入口",
        baseline_artifact_id=a1["id"], baseline_revision_uid=a1["revision_uid"])
    studio.run_a1(PID, background=False)  # run 2: should be a REVISE of fb baseline
    all_after = st.artifacts(PID)
    new_group = next((g for g in {a["candidate_group_id"] for a in all_after}
                      if g and g not in groups_before), None)
    second = [a for a in all_after if a["candidate_group_id"] == new_group
              and a["kind"] == "spatial-plan"]
    fresh_ab = [a for a in second if a["revision"] == 1]
    revisions = [a for a in second if a["revision"] >= 2]
    parent_uids = [a["parent_revision_uid"] for a in revisions]
    bound = bool(fb.get("baseline_revision_uid")) and fb["baseline_revision_uid"] in parent_uids
    return [_case(
        "R1-b", "反馈指定旧基线后，第二轮是否加载该旧稿续改而非重新生成 A/B",
        {"user_selected_baseline_artifact_id": a1["id"],
         "user_selected_baseline_revision_uid": a1["revision_uid"],
         "feedback_baseline_revision_uid": fb.get("baseline_revision_uid"),
         "second_run_fresh_A_B_count": len(fresh_ab),
         "second_run_revisions": [{"id": a["id"], "revision": a["revision"],
                                    "parent_revision_uid": a["parent_revision_uid"]}
                                   for a in revisions],
         "parent_revision_uid_matches_user_selected_baseline": bound,
         "runs": [{"status": r["status"], "task_kind": r.get("task_kind")}
                  for r in st.runs(PID)]},
        defect_present=(len(fresh_ab) > 0 or not bound))]


def r1_http(st: Store, user_baseline: str, user_uid: str) -> list[dict]:
    """Real service entry: POST /messages with an explicitly selected old baseline."""
    class StubConfig:
        configured = True
        model = "local-model-stub"
        base_url = "local://stub"
        run_token_limit = 600_000
        project_token_limit = 2_000_000

        @classmethod
        def from_env(cls):
            return cls()

    studio_llm = sys.modules["rkd_mvp.studio.llm"]
    studio_llm.Config = StubConfig
    studio_server.Config = StubConfig
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), studio_server.Handler)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        payload = json.dumps({"text": "指定这份旧稿续改：把洽谈区放大",
                              "baseline_artifact_id": user_baseline,
                              "baseline_revision_uid": user_uid}, ensure_ascii=False).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/studio/projects/{PID}/messages",
            data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                status, body = resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            status, body = e.code, json.loads(e.read().decode("utf-8"))
        saved = st.feedback(PID)[-1]
        honoured = saved.get("baseline_artifact_id") == user_baseline
        explicit = saved.get("baseline_selection") == "user_selected"
        return [_case(
            "R1-c", "真实服务入口是否尊重用户指定的旧基线（不按最新文件偷换）",
            {"http_status": status, "response": body,
             "user_specified_baseline_artifact_id": user_baseline,
             "stored_baseline_artifact_id": saved.get("baseline_artifact_id"),
             "stored_baseline_selection": saved.get("baseline_selection"),
             "honoured": honoured, "explicitly_labelled_user_selection": explicit},
            defect_present=not (honoured and explicit))]
    finally:
        httpd.shutdown(); httpd.server_close(); th.join(5)


# --------------------------------------------------------------------- R2 ----
def r2_cases() -> list[dict]:
    """A pseudo-fix: change the target object's colour/name, but NOT the narrow route."""
    project = {"id": PID, "site": SITE}
    report = validation.validate_proposal(valid_proposal("A"), project=project,
                                          option_id="A", revision=1, parent_revision=None)
    base = report["plan"]
    issue = {"issue_id": "I1", "candidate": "A", "severity": "major",
             "objects": ["CA1"], "rule_id": "CIR-001",
             "evidence": "主动线实测净宽不足",
             "suggest": "把主动线净宽调到 2100mm 并复核瓶颈"}
    responses = [{"issue_id": "I1", "action": "accept", "change": "已调整",
                  "reason": ""}]
    fb = [{"feedback_id": "fb_test", "revision_no": 1, "kind": "boss_message",
           "text": "把洽谈区做得更开放、更有设计感"}]

    pseudo = copy.deepcopy(base)
    for c in pseudo["circulation"]:
        if c["id"] == "CA1":
            c["color"] = "#ff0000"        # changed the TARGET object only
            c["label"] = "主通道（已美化）"
            # width_mm stays 2000; measured bottleneck is untouched
    result = revision_mod.verify_revision_integrity(
        base, pseudo, responses=responses, issues=[issue], boss_feedback=fb)
    ir = (result.get("issue_resolutions") or [{}])[0]
    br = (result.get("boss_feedback_resolutions") or [{}])[0]
    objective_aware = "objective_rechecked" in ir and "objective_rechecked" in br
    verified_as_resolved = bool(ir.get("verified")) or ir.get("recheck") == "对象 diff 复核"
    return [
        _case("R2-a", "伪修复（只改目标对象颜色/名称，未修窄通道）是否被记为已解决",
              {"changed_objects": result["changed_objects"],
               "declared_width_mm_after": next(c["width_mm"] for c in pseudo["circulation"]
                                               if c["id"] == "CA1"),
               "issue_resolution": ir, "boss_feedback_resolution": br,
               "objective_states_present": objective_aware,
               "ok": result["ok"]},
              defect_present=verified_as_resolved and not objective_aware),
        _case("R2-b", "意见/反馈是否分离 input_included / object_changed / "
                      "objective_rechecked / user_confirmed 四态",
              {"issue_resolution_keys": sorted(ir.keys()),
               "boss_feedback_resolution_keys": sorted(br.keys()),
               "boss_feedback_linked_changes_is_all_changes":
                   br.get("linked_changes") == [k.split(":", 1)[1]
                                                for k in result["changed_objects"]],
               "boss_feedback_claims_in_revision_input": br.get("in_revision_input")},
              defect_present=not objective_aware),
    ]


# --------------------------------------------------------------------- R3 ----
def r3_cases() -> list[dict]:
    arc = ROOT / "deliverables-for-review" / "arc-first-batch"
    packet = (arc / "review-packet.md").read_text(encoding="utf-8")
    compiled = re.search(r"日期：(\d{4}-\d{2}-\d{2})", packet)
    before = json.loads((arc / "before-reproduction.json").read_text(encoding="utf-8"))
    after = json.loads((arc / "after-reproduction.json").read_text(encoding="utf-8"))
    checks = json.loads((arc / "checks.json").read_text(encoding="utf-8"))
    browser = json.loads((arc / "browser-verification.json").read_text(encoding="utf-8"))
    note = (arc / "ARC-05-adaptation-note.md").read_text(encoding="utf-8")
    erratum = ROOT / "deliverables-for-review/roadmap/W0-收口/evidence-provenance-erratum.md"
    erratum_text = erratum.read_text(encoding="utf-8") if erratum.exists() else ""
    erratum_ok = bool(erratum_text) and all(
        k in erratum_text for k in ("编制", "执行", "提交", "2026-11-12", "2026-11-14",
                                   "contract_version", "schema_version"))
    proposal = json.loads((ROOT / "contracts/v1/spatial-plan-proposal.schema.json").read_text(encoding="utf-8"))
    draft = json.loads((ROOT / "contracts/v1/spatial-plan-draft.schema.json").read_text(encoding="utf-8"))
    option = json.loads((ROOT / "contracts/v1/ai-design-option.schema.json").read_text(encoding="utf-8"))
    commits = _commits()

    mapping_lines = [l.strip() for l in note.splitlines()
                     if "contract_version" in l or "project_id" in l or "schema_version" in l]
    return [
        _case("R3-a", "复核包编制日期与内含事件/提交日期是否分别标明（不推断造假，不混用）",
              {"packet_compiled_date": compiled.group(1) if compiled else None,
               "before_reproduction_generated_at": before.get("generated_at"),
               "after_reproduction_generated_at": after.get("generated_at"),
               "checks_json_generated_at": checks.get("generated_at"),
               "browser_verification_checked_at": browser.get("checked_at"),
               "commits": commits,
               "packet_has_explicit_time_axis":
                   ("编制" in packet and "执行" in packet and "提交" in packet),
               "historical_packet_unchanged": True,
               "historical_packet_sha256": __import__("hashlib").sha256(
                   packet.encode("utf-8")).hexdigest(),
               "erratum_time_axis_present": erratum_ok},
              # docs/26 R3: do NOT rewrite historical evidence for cosmetic
              # consistency. The fix is an INDEPENDENT, dated erratum record.
              defect_present=not erratum_ok),
        _case("R3-b", "ARC-05 适配说明是否按实际两个 schema 区分模型提案/程序装配/主系统落点",
              {"proposal_schema_has_contract_version":
                   "contract_version" in proposal.get("properties", {}),
               "proposal_schema_has_project_id":
                   "project_id" in proposal.get("properties", {}),
               "draft_schema_contract_version_const":
                   draft.get("properties", {}).get("contract_version", {}).get("const"),
               "draft_schema_has_project_id": "project_id" in draft.get("properties", {}),
               "main_option_schema_version_const":
                   option.get("properties", {}).get("schema_version", {}).get("const"),
               "main_option_schema_has_project_id":
                   "project_id" in option.get("properties", {}),
               "main_option_additional_properties": option.get("additionalProperties"),
               "adaptation_note_mapping_lines": mapping_lines[:6],
               "note_incorrectly_labels_proposal_fields":
                   any("contract_version" in l and "Studio 提案字段" in l for l in mapping_lines),
               "erratum_record_present": erratum.exists(),
               "erratum_has_three_schema_boundaries": bool(erratum_text) and all(
                   k in erratum_text for k in ("spatial-plan-proposal.v1",
                                               "spatial-plan-draft.v1",
                                               "rkd-ai-design-option.v1"))},
              defect_present=not (erratum.exists() and "spatial-plan-proposal.v1" in erratum_text)),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["before", "after"], required=True)
    args = ap.parse_args()
    outdir = EVIDENCE / args.phase
    outdir.mkdir(parents=True, exist_ok=True)
    db = RUNTIME / f"repro-{args.phase}.db"
    if db.exists():
        db.unlink()
    st = Store(db)

    cases: list[dict] = []
    cases += r1_static()
    cases += r1_dynamic(st)
    # use the A/v1 candidate from the FIRST run as the user-selected OLD baseline
    first_a = next((a for a in st.artifacts(PID)
                    if a["kind"] == "spatial-plan" and a["option_id"] == "A"
                    and a["revision"] == 1 and a["contract_status"] == "valid_candidate"), None)
    if first_a:
        cases += r1_http(st, first_a["id"], first_a["revision_uid"])
    cases += r2_cases()
    cases += r3_cases()

    result = {
        "schema_version": "rkd-w0-reproduction.v1",
        "phase": args.phase,
        "checked_at": _now(),
        "head_commit_at_check": _head_commit(),
        "basis": "docs/26 section 2 (R1/R2/R3)",
        "isolation": {"studio_db": str(db),
                      "daily_var_studio_db_untouched": True,
                      "historical_review_packet_read_only": True,
                      "model_channel": "local-model-stub (explicitly labelled)",
                      "external_calls": 0, "keys_used": False, "cost": 0},
        "cases": cases,
        "defects_confirmed": sum(1 for c in cases if c["defect_present"]),
        "cases_total": len(cases),
    }
    path = outdir / "reproduction.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"phase": args.phase, "path": str(path),
                      "defects_confirmed": result["defects_confirmed"],
                      "cases_total": result["cases_total"],
                      "cases": [{"id": c["id"], "verdict": c["verdict"]} for c in cases]},
                     ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
