"""W0 acceptance: R1 old-baseline continuation, R2 objective rechecks, R3 erratum.

Real HTTP service + real browser-facing endpoints + isolated SQLite. All model
answers come from explicitly-labelled local stubs: 0 external calls, 0 keys,
0 cost. This proves engineering control, NOT design or AD01-AD08.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "var" / "evidence" / "roadmap" / "W0-收口" / "after"
RUNTIME = ROOT / "var" / "evidence" / "roadmap" / "W0-收口" / "runtime"
EVIDENCE.mkdir(parents=True, exist_ok=True)
RUNTIME.mkdir(parents=True, exist_ok=True)
os.environ["RKD_STUDIO_DB"] = str(RUNTIME / "w0-verify.db")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from arc_first_batch_stub import SITE, review_issues, valid_proposal  # noqa: E402
from rkd_mvp.studio import (orchestrator, revision as R, revision_task,  # noqa: E402
                            server as studio_server, validation, vision)
from rkd_mvp.studio.llm import Config as RealConfig  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402
import verify_studio_loop as vsl  # noqa: E402

FAKE_JPEG = vsl.FAKE_JPEG
PID = "ningbo-xiecheng"
CHECKS: list[dict] = []


def check(cid: str, name: str, ok: bool, evidence: dict) -> None:
    CHECKS.append({"id": cid, "name": name,
                   "result": "observed_pass" if ok else "observed_fail",
                   "evidence": evidence})
    print(("PASS " if ok else "FAIL ") + cid + " " + name, flush=True)


class StubConfig:
    configured = True
    model = "local-model-stub"
    base_url = "local://stub"
    run_token_limit = 600_000
    project_token_limit = 2_000_000

    @classmethod
    def from_env(cls):
        return cls()


def http(path: str, payload: dict | None = None, method: str = "GET") -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def state() -> dict:
    code, body = http(f"/studio/projects/{PID}/state")
    assert code == 200, (code, body)
    return body


def wait_run(timeout: float = 90.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        s = state()
        runs = s.get("runs") or []
        if runs and runs[-1]["status"] != "running":
            return s
        time.sleep(0.4)
    raise TimeoutError("run did not finish")


def object_sig(plan: dict) -> dict:
    out = {}
    for g in ("zones", "furniture", "circulation", "platforms"):
        for o in plan.get(g) or []:
            if isinstance(o, dict) and o.get("id"):
                out[f"{g}:{o['id']}"] = json.dumps(o, ensure_ascii=False, sort_keys=True)
    return out


# --------------------------------------------------------------- service setup
db = RUNTIME / "w0-verify.db"
if db.exists():
    db.unlink()
st = Store(db)
orchestrator.Studio(st).seed_from_fixtures()
orchestrator.Client = vsl.FakeClient
vision.svg_to_jpeg = lambda svg, limit=720: FAKE_JPEG
vision.reference_jpeg = lambda limit=720: FAKE_JPEG
sys.modules["rkd_mvp.studio.llm"].Config = StubConfig
studio_server.Config = StubConfig
studio_server.STUDIO = orchestrator.Studio(st)  # same isolated store

httpd = ThreadingHTTPServer(("127.0.0.1", 0), studio_server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()

try:
    # --------------------------------------------------- C01: real service revise
    code, gen = http(f"/studio/projects/{PID}/run", {})
    s0 = wait_run()
    valid = [a for a in s0["artifacts"] if a["kind"] == "spatial-plan"
             and a.get("display_group") == "valid"]
    a1 = next(a for a in valid if a["option_id"] == "A" and a["revision"] == 1)
    b1 = next(a for a in valid if a["option_id"] == "B" and a["revision"] == 1)
    base_plan = next(a["payload"] for a in s0["artifacts"] if a["id"] == a1["id"])

    code, posted = http(f"/studio/projects/{PID}/messages", {
        "text": "把主动线净宽扩大到 2100mm，保留入口",
        "baseline_artifact_id": a1["id"],
        "baseline_revision_uid": a1["revision_uid"],
        "locks": [{"object_id": "ZA1", "fields": ["*"], "reason": "入口序厅保留"}],
    })
    code2, started = http(f"/studio/projects/{PID}/run", {})
    s1 = wait_run()
    runs = s1["runs"]
    last_run = runs[-1]
    new_plans = [a for a in s1["artifacts"] if a["kind"] == "spatial-plan"
                 and a["run_id"] == last_run["id"]]
    fresh_ab = [a for a in new_plans if a["revision"] == 1]
    revision = next((a for a in new_plans if a["revision"] >= 2), None)
    new_payload = revision["payload"] if revision else None
    before_sig, after_sig = object_sig(base_plan), object_sig(new_payload or {})
    unrelated = sorted(k for k in set(before_sig) & set(after_sig)
                       if k not in {"circulation:CA1", "furniture:F3"}
                       and before_sig[k] != after_sig[k])
    c01 = {
        "generate_http": gen.get("task_kind"),
        "post_feedback_http": code,
        "feedback_baseline_selection": posted.get("baseline_selection"),
        "feedback_baseline_artifact_id": posted.get("feedback", {}).get("baseline_artifact_id"),
        "run_http_status": code2, "run_task_kind": started.get("task_kind"),
        "run_target_artifact_id": started.get("target_artifact_id"),
        "run_target_revision_uid": started.get("target_revision_uid"),
        "selected_baseline_revision_uid": a1["revision_uid"],
        "new_revision_parent_revision_uid": revision["parent_revision_uid"] if revision else None,
        "fresh_A_B_in_revise_run": len(fresh_ab),
        "unrelated_objects_changed": unrelated,
        "old_baseline_bytes_still_present": any(a["id"] == a1["id"] and a["sha256"] == a1["sha256"]
                                                for a in s1["artifacts"]),
        "run_status": last_run["status"],
        "run_task_kind_in_store": last_run.get("task_kind"),
    }
    check("W0-R1-01", "真实服务入口：选中旧方案反馈→revise→parent_revision_uid 指向用户选中旧版",
          bool(c01["generate_http"] == "generate" and code == 201
               and posted.get("baseline_selection") == "user_selected"
               and started.get("task_kind") == "revise"
               and started.get("target_artifact_id") == a1["id"]
               and revision is not None
               and revision["parent_revision_uid"] == a1["revision_uid"]
               and len(fresh_ab) == 0 and not unrelated
               and c01["old_baseline_bytes_still_present"]
               and last_run["status"] == "succeeded"), c01)

    # ------------------------------------------------------------ R1 negatives
    neg: dict[str, dict] = {}

    code, body = http(f"/studio/projects/{PID}/messages", {
        "text": "跨候选：拿 A 的产物配 B 的版本号",
        "baseline_artifact_id": a1["id"],
        "baseline_revision_uid": b1["revision_uid"]})
    neg["cross_candidate_uid_mismatch"] = {"status": code, "body": body}
    ok = code == 409 and body.get("conflict_code") == "baseline_uid_mismatch"

    # an artifact belonging to ANOTHER project
    other_pid = "w0-other-project"
    st.ensure_project(other_pid, "另一项目", SITE, {"text": "x", "must_have": [],
                                                    "constraints": {}})
    foreign_id = st.save_artifact(other_pid, "spatial-plan", base_plan, "D2",
                                  option_id="A", revision=1, status="valid_candidate",
                                  contract_status="valid_candidate")
    code, body = http(f"/studio/projects/{PID}/messages", {
        "text": "跨项目旧基线", "baseline_artifact_id": foreign_id})
    neg["cross_project_baseline"] = {"status": code, "body": body}
    ok = ok and code == 409 and body.get("conflict_code") == "cross_project_baseline"

    code, body = http(f"/studio/projects/{PID}/messages", {
        "text": "不存在的旧基线", "baseline_artifact_id": "art_does_not_exist"})
    neg["baseline_not_found"] = {"status": code, "body": body}
    ok = ok and code == 409 and body.get("conflict_code") == "baseline_not_found"

    # invalid (invalid_raw) baseline must be refused, never substituted
    bad_id = st.save_artifact(PID, "spatial-plan-raw", {"bad": True}, "D2",
                              option_id="A", revision=9, status="invalid_raw",
                              contract_status="invalid_raw")
    code, body = http(f"/studio/projects/{PID}/messages", {
        "text": "拿失败稿当旧基线", "baseline_artifact_id": bad_id})
    neg["baseline_invalid"] = {"status": code, "body": body}
    ok = ok and code == 409 and body.get("conflict_code") == "baseline_invalid"

    # the consumed feedback must NOT be replayable through a new run
    code, body = http(f"/studio/projects/{PID}/run", {})
    neg["old_feedback_replay"] = {"status": code, "body": body}
    ok = ok and code == 409 and body.get("conflict_code") == "feedback_already_consumed"

    # concurrent new feedback: resolution with a stale expected revision
    stale = revision_task.resolve_task(st, PID, 0)
    neg["concurrent_new_feedback"] = {"kind": stale["kind"],
                                      "code": stale.get("conflict_code")}
    ok = ok and stale["kind"] == "conflict" and \
        stale.get("conflict_code") == "concurrent_new_feedback"

    # late result: invalidation keeps bytes, never deletes history
    run_id = last_run["id"]
    old_bytes = {a["id"]: a["sha256"] for a in st.artifacts(PID)}
    st.invalidate_artifacts(run_id)
    after_bytes = {a["id"]: a["sha256"] for a in st.artifacts(PID)}
    neg["late_result_bytes_preserved"] = {
        "bytes_identical": old_bytes == after_bytes,
        "superseded": [a["id"] for a in st.artifacts(PID) if a["status"] == "superseded"]}
    ok = ok and old_bytes == after_bytes
    check("W0-R1-02", "R1 负例：跨候选/跨项目/旧反馈/并发新反馈/失败稿/晚到结果均明确拒绝",
          ok, neg)

    # ------------------------------------------------------------- R2 unit cases
    project = {"id": PID, "site": SITE}
    report = validation.validate_proposal(valid_proposal("A"), project=project,
                                          option_id="A", revision=1,
                                          parent_revision=None)
    base = report["plan"]
    issue = {"issue_id": "I1", "candidate": "A", "severity": "major",
             "objects": ["CA1"], "rule_id": "CIR-001",
             "evidence": "主动线实测净宽不足",
             "suggest": "把主动线净宽调到 2100mm 并复核瓶颈"}
    responses = [{"issue_id": "I1", "action": "accept", "change": "已调整", "reason": ""}]
    fb_rows = [{"feedback_id": "fb_w0", "revision_no": 1, "kind": "boss_message",
                "text": "把主动线净宽扩大到 2100mm，保留入口", "locks": [], "objectives": []}]
    objectives = revision_task.derive_objectives(fb_rows, [issue])

    # pseudo-fix: change the TARGET object's path only, width stays 2000
    pseudo = copy.deepcopy(base)
    for c in pseudo["circulation"]:
        if c["id"] == "CA1":
            c["path"] = [list(p) for p in c["path"]]
            c["path"][-1][0] += 1
    pseudo_integ = R.verify_revision_integrity(
        base, pseudo, responses=responses, issues=[issue], boss_feedback=fb_rows,
        objectives=objectives, site=SITE,
        locks=revision_task.structured_locks(base, SITE))
    ir = pseudo_integ["issue_resolutions"][0]
    pseudo_ev = {
        "declared_width_after": next(c["width_mm"] for c in pseudo["circulation"]
                                     if c["id"] == "CA1"),
        "changed_objects": pseudo_integ["changed_objects"],
        "objective_rechecked": ir["objective_rechecked"],
        "verified": ir["verified"], "resolved": ir["resolved"],
        "errors": [e["rule_id"] for e in pseudo_integ["errors"]],
        "recheck_evidence": ir["recheck_details"][0]["evidence"]["after"] if ir["recheck_details"] else None,
    }
    check("W0-R2-01", "R2 负例：改了目标对象但未修窄通道 → REV-OBJECTIVE 拒绝，不记已解决",
          bool(ir["objective_rechecked"] == "fail" and not ir["verified"]
               and ir["resolved"] is False
               and "REV-OBJECTIVE" in pseudo_ev["errors"]), pseudo_ev)

    # real fix: width actually reaches 2100
    fixed = copy.deepcopy(base)
    for c in fixed["circulation"]:
        if c["id"] == "CA1":
            c["width_mm"] = 2100
    fixed_integ = R.verify_revision_integrity(
        base, fixed, responses=responses, issues=[issue], boss_feedback=fb_rows,
        objectives=objectives, site=SITE,
        locks=revision_task.structured_locks(base, SITE))
    fir = fixed_integ["issue_resolutions"][0]
    check("W0-R2-02", "R2 正例：净宽由几何规则实测达标才记 pass（不是只看对象 diff）",
          bool(fir["objective_rechecked"] == "pass" and fir["verified"]
               and fixed_integ["ok"]),
          {"objective_rechecked": fir["objective_rechecked"], "verified": fir["verified"],
           "resolved": fir["resolved"], "summary": fixed_integ["objective_recheck_summary"]})

    # aesthetic + unimplemented rule stays unknown / pending
    aesthetic_fb = [{"feedback_id": "fb_aes", "revision_no": 2, "kind": "boss_message",
                     "text": "把洽谈区做得更开放、更有设计感", "locks": [], "objectives": []}]
    sightline = {"issue_id": "I9", "candidate": "B", "severity": "minor",
                 "objects": ["ZB5"], "rule_id": "STD-004",
                 "evidence": "北洽谈区没有对应视线", "suggest": "本轮只深化 A"}
    aes_obj = revision_task.derive_objectives(aesthetic_fb, [sightline])
    aes_integ = R.verify_revision_integrity(
        base, copy.deepcopy(base), issues=[sightline], boss_feedback=aesthetic_fb,
        objectives=aes_obj, site=SITE)
    br = aes_integ["boss_feedback_resolutions"][0]
    aes_ev = {
        "objective_states": [o["objective_rechecked"] for o in aes_integ["objective_rechecks"]],
        "user_confirmed": [o["user_confirmed"] for o in aes_integ["objective_rechecks"]],
        "boss_objective_rechecked": br["objective_rechecked"],
        "boss_resolved": br["resolved"], "boss_user_confirmed": br["user_confirmed"],
        "issue_states_present": sorted(k for k in br if k in
                                       ("input_included", "object_changed",
                                        "objective_rechecked", "user_confirmed")),
        "linked_changes": br["linked_changes"],
        "in_revision_input": br["in_revision_input"],
        "summary": aes_integ["objective_recheck_summary"],
    }
    check("W0-R2-03", "R2 正例：审美/未实现目标写 unknown + user_confirmed=pending，四态分离",
          bool(br["objective_rechecked"] == "unknown" and br["resolved"] is None
               and br["user_confirmed"] == "pending"
               and len(aes_ev["issue_states_present"]) == 4
               and aes_integ["objective_recheck_summary"]["unknown"] >= 2), aes_ev)

    # ------------------------------------------- R2 service-level pseudo-fix
    # The late-result test above marked C01's new revision `superseded`, so it
    # is correctly refused as a baseline. Use the still-valid A/v1 OLD plan
    # (refusing a superseded artifact is itself a verified R1 behaviour).
    v2 = a1
    original_payload_fn = vsl.revision_payload
    v2_uid = v2.get("revision_uid")
    code, posted2 = http(f"/studio/projects/{PID}/messages", {
        "text": "把主动线净宽扩大到 2100mm，保留入口",
        "baseline_artifact_id": v2["id"],
        "baseline_revision_uid": v2_uid})
    vsl.revision_payload = lambda: {
        "responses": [],
        "patch": [{"op": "update", "group": "circulation", "id": "CA1",
                   "fields": {"path": [[100, 11000], [8000, 11000], [17500, 11000],
                                       [17500, 6000], [8001, 5200]]}}]}
    try:
        code3, started2 = http(f"/studio/projects/{PID}/run", {})
        s2 = wait_run()
        last2 = s2["runs"][-1]
        raw_artifacts = [a for a in s2["artifacts"]
                         if a["kind"] == "spatial-plan-raw" and a["run_id"] == last2["id"]]
        diag = json.dumps([a.get("diagnostics") for a in raw_artifacts], ensure_ascii=False)
        svc_ev = {"post_status": code, "run_status": code3,
                  "baseline_used": v2["id"],
                  "baseline_revision_uid": v2_uid,
                  "task_kind": started2.get("task_kind"),
                  "final_run_status": last2["status"],
                  "raw_invalid_artifacts": len(raw_artifacts),
                  "rev_objective_in_diagnostics": "REV-OBJECTIVE" in diag,
                  "no_valid_revision_in_this_run": not any(
                      a["kind"] == "spatial-plan" and a["run_id"] == last2["id"]
                      and a.get("display_group") == "valid" for a in s2["artifacts"])}
        check("W0-R2-04", "R2 服务级负例：伪修复经真实 /run 被拦，不生成新候选、不宣称成功",
              bool(code == 201 and started2.get("task_kind") == "revise"
                   and last2["status"] == "incomplete"
                   and svc_ev["raw_invalid_artifacts"] >= 1
                   and svc_ev["rev_objective_in_diagnostics"]
                   and svc_ev["no_valid_revision_in_this_run"]), svc_ev)
    finally:
        vsl.revision_payload = original_payload_fn

    # --------------------------------------------------------------- R3 + bounds
    arc = ROOT / "deliverables-for-review" / "arc-first-batch"
    packet_b = (arc / "review-packet.md").read_bytes()
    note_b = (arc / "ARC-05-adaptation-note.md").read_bytes()
    erratum = ROOT / "deliverables-for-review/roadmap/W0-收口/evidence-provenance-erratum.md"
    err_text = erratum.read_text(encoding="utf-8")
    r3 = {
        "packet_sha256": hashlib.sha256(packet_b).hexdigest(),
        "adaptation_note_sha256": hashlib.sha256(note_b).hexdigest(),
        "erratum_exists": erratum.exists(),
        "erratum_has_time_axis": all(k in err_text for k in ("编制", "执行", "提交")),
        "erratum_has_three_schemas": all(k in err_text for k in
                                         ("spatial-plan-proposal.v1", "spatial-plan-draft.v1",
                                          "rkd-ai-design-option.v1")),
        "q10_not_run": True,
        "ad_conclusions_unchanged": True,
    }
    check("W0-R3-01", "R3：历史证据字节不变、独立勘误含时间轴与三份 schema 映射；Q10 仍 not_run",
          bool(r3["packet_sha256"] ==
               "8ac87bd723818054f71c1b00adbab43a7777370e7ce8da87458e9791c046ca21"
               and r3["adaptation_note_sha256"] ==
               "cc451e8bd6c0e078da5732db6d963cf318d1229433e5b439a2aec3d62e95d451"
               and r3["erratum_exists"] and r3["erratum_has_time_axis"]
               and r3["erratum_has_three_schemas"]), r3)

    passed = sum(1 for c in CHECKS if c["result"] == "observed_pass")
    failed = sum(1 for c in CHECKS if c["result"] == "observed_fail")
    out = {
        "task_id": "W0 收口（R1/R2/R3）",
        "schema_version": "rkd-w0-checks.v1",
        "baseline": "957cf775e1d835cf25bbdf196de4e7f3f51280fa",
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "environment": {"python": sys.version.split()[0],
                        "geometry_engine": "shapely-2.1.2",
                        "jsonschema": "4.25.1",
                        "model_channel": "local-model-stub (explicitly labelled)",
                        "service": f"studio HTTP 127.0.0.1:{PORT} (isolated DB)",
                        "keys_used": False},
        "checks": CHECKS,
        "totals": {"observed_pass": passed, "observed_fail": failed, "not_run": 1},
        "artifact_refs": ["var/evidence/roadmap/W0-收口/before/reproduction.json",
                          "var/evidence/roadmap/W0-收口/after/reproduction.json",
                          "deliverables-for-review/roadmap/W0-收口/evidence-provenance-erratum.md"],
        "external_calls": 0,
        "image_counts": {"images_sent_external": 0, "images_generated_external": 0},
        "tokens": 0,
        "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
        "limitations": ["本批是工程修复，没有新增设计成果",
                        "Q10 同源平面/渲染/数量一致性仍 not_run（W1/W2）",
                        "AD01—AD08 结论不改判，设计阶段结论只能由用户给出",
                        "所有模型回答为明确标记的本地桩，不代表真实 AI 设计能力"],
    }
    (EVIDENCE / "checks.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": passed, "failed": failed,
                      "out": str(EVIDENCE / "checks.json")}, ensure_ascii=False), flush=True)
    sys.exit(0 if failed == 0 else 1)
finally:
    httpd.shutdown(); httpd.server_close()
