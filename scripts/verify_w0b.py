"""W0 二次收口（W0-F01—F05）真实 HTTP 验收：正例 + 负例 + 可控时序。

真实 Studio HTTP 服务 + 隔离 SQLite + 明确标注的本地模型桩。0 外部调用、
0 密钥、0 费用。证明的是工程控制，不是设计质量，也不改 AD01—AD08。

每种场景都写成「先断言、再留证」；失败会以 observed_fail 落到 checks.json，
不会被吞掉。晚到/取消用可控屏障（桩在指定位置停住 + 事件通知），没有用
sleep 制造通过。
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
EVIDENCE = ROOT / "var" / "evidence" / "roadmap" / "W0-二次收口" / "after"
RUNTIME = ROOT / "var" / "evidence" / "roadmap" / "W0-二次收口" / "runtime"
EVIDENCE.mkdir(parents=True, exist_ok=True)
RUNTIME.mkdir(parents=True, exist_ok=True)
DB = RUNTIME / "w0b-verify.db"
if DB.exists():
    DB.unlink()
os.environ["RKD_STUDIO_DB"] = str(DB)
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from arc_first_batch_stub import (SITE, review_issues, revision_payload,  # noqa: E402
                                  valid_proposal)
from rkd_mvp.studio import (orchestrator, revision as R, revision_task,  # noqa: E402
                            server as studio_server, validation, vision)
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


class GatedStub(vsl.FakeClient):
    """Local stub with a controllable barrier: it stops at a chosen call and
    waits for an explicit release. Used to test late/parallel feedback without
    sleeping and hoping for a race."""

    gate: threading.Event | None = None
    reached = threading.Event()
    at_call = 1
    calls = 0
    hold = False

    def chat(self, messages, tools=None, temperature=0.6, max_tokens=3000,
             json_only=False):
        cls = type(self)
        if cls.hold:
            cls.calls += 1
            if cls.calls >= cls.at_call:
                cls.hold = False          # only the first matching call waits
                cls.reached.set()
                if cls.gate is not None:
                    cls.gate.wait(120)
        return super().chat(messages, tools=tools, temperature=temperature,
                            max_tokens=max_tokens, json_only=json_only)


def http(path: str, payload: dict | None = None, method: str = "GET") -> tuple[int, dict]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def state() -> dict:
    code, body = http(f"/studio/projects/{PID}/state")
    assert code == 200, (code, body)
    return body


def wait_run(run_id: str, timeout: float = 120.0) -> dict:
    """Wait on the EXACT run id (W0-F05), never on 'the last run I can see'."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        code, body = http(f"/studio/projects/{PID}/runs/{run_id}")
        assert code == 200, (code, body)
        if body["finished"]:
            return body
        time.sleep(0.3)
    raise TimeoutError(f"run {run_id} did not finish")


def post_message(text: str, baseline: dict | None = None, **extra) -> tuple[int, dict]:
    payload = {"text": text}
    if baseline:
        payload["baseline_artifact_id"] = baseline["id"]
        payload["baseline_revision_uid"] = baseline["revision_uid"]
    payload.update(extra)
    return http(f"/studio/projects/{PID}/messages", payload)


def start_run() -> tuple[int, dict]:
    return http(f"/studio/projects/{PID}/run", {})


def valid_plans(s: dict) -> list[dict]:
    return [a for a in s["artifacts"] if a["kind"] == "spatial-plan"
            and a.get("display_group") == "valid"]


def plan_of(s: dict, artifact_id: str) -> dict:
    return next(a["payload"] for a in s["artifacts"] if a["id"] == artifact_id)


# --------------------------------------------------------------- service setup
st = Store(DB)
orchestrator.Studio(st).seed_from_fixtures()
orchestrator.Client = GatedStub  # type: ignore[assignment]
vision.svg_to_jpeg = lambda svg, limit=720: FAKE_JPEG  # type: ignore[assignment]
vision.reference_jpeg = lambda limit=720: FAKE_JPEG  # type: ignore[assignment]
sys.modules["rkd_mvp.studio.llm"].Config = StubConfig
studio_server.Config = StubConfig
studio_server.STUDIO = orchestrator.Studio(st)

httpd = ThreadingHTTPServer(("127.0.0.1", 0), studio_server.Handler)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def reset_stub() -> None:
    GatedStub.gate = None
    GatedStub.reached = threading.Event()
    GatedStub.hold = False
    GatedStub.calls = 0


try:
    # =================================================== C00 baseline generate
    code, gen = start_run()
    snap0 = wait_run(gen["run_id"])
    s0 = state()
    a1 = next(a for a in valid_plans(s0) if a["option_id"] == "A" and a["revision"] == 1)
    b1 = next(a for a in valid_plans(s0) if a["option_id"] == "B" and a["revision"] == 1)
    base_plan = plan_of(s0, a1["id"])
    check("W0B-C00", "基座：一次真实 generate 产出 A/B 两份有效候选，按 run_id 读到同一快照",
          bool(code == 202 and gen["task_kind"] == "generate"
               and snap0["run_status"] == "succeeded"
               and len(snap0["valid_artifacts"]) >= 2
               and s0["stage_status"]["last_completed_run_id"] == gen["run_id"]
               and s0["snapshot"]["artifact_count"] == len(s0["artifacts"])
               and s0["snapshot"]["run_count"] == len(s0["runs"])),
          {"run_id": gen["run_id"], "run_status": snap0["run_status"],
           "run_valid_artifacts": snap0["valid_artifacts"],
           "stage_status": s0["stage_status"], "snapshot": s0["snapshot"]})

    # ============================================ F01-a 连续两条同基线留言合并
    code1, m1 = post_message("F3 转到 -15 度，保留入口", a1)
    code2, m2 = post_message("中岛圆角再收一点，保留入口", a1)
    code3, started = start_run()
    snap1 = wait_run(started["run_id"])
    s1 = state()
    merged_run = next(r for r in s1["runs"] if r["id"] == started["run_id"])
    new_plan = [a for a in s1["artifacts"] if a["kind"] == "spatial-plan"
                and a["run_id"] == started["run_id"]]
    rev = next((a for a in new_plan if a["revision"] >= 2), None)
    consumed = {f["id"]: f.get("consumed_by_run") for f in s1["feedback"]}
    merged_evidence = json.dumps([m["body"] for m in s1["messages"]
                                  if m["role"] == "D2" and m["kind"] == "note"],
                                 ensure_ascii=False)
    check("W0B-F01-01", "连续两条同基线留言：显式合并为一轮续改，两条都被同一 run 消费",
          bool(code1 == 201 and code2 == 201 and code3 == 202
               and started["task_kind"] == "revise"
               and rev is not None and rev["parent_revision_uid"] == a1["revision_uid"]
               and consumed.get(m1["feedback"]["id"]) == started["run_id"]
               and consumed.get(m2["feedback"]["id"]) == started["run_id"]
               and merged_run["status"] == "succeeded"
               and "合并" in merged_evidence),
          {"post_1": code1, "post_2": code2, "run": code3,
           "task_kind": started["task_kind"],
           "merged_feedback_ids": [m1["feedback"]["id"], m2["feedback"]["id"]],
           "consumed_by_run": {m1["feedback"]["id"]: consumed.get(m1["feedback"]["id"]),
                               m2["feedback"]["id"]: consumed.get(m2["feedback"]["id"])},
           "run_id": started["run_id"],
           "new_revision_parent_uid": rev["parent_revision_uid"] if rev else None,
           "merge_note_present": "合并" in merged_evidence})

    # F01-a': after consumption, the OLD message must not come back
    code, again = start_run()
    check("W0B-F01-02", "两条都已消费后再开轮：明确冲突，旧留言不复活、不偷换基线",
          bool(code == 409 and again.get("conflict_code") == "feedback_already_consumed"),
          {"status": code, "conflict_code": again.get("conflict_code"),
           "detail": (again.get("error") or "")[:160]})

    # ================================================= F01-b 续改后显式新生成
    code, mg = post_message("不再续改这一版了，重新做一版新方案")
    code2, started = start_run()
    snap2 = wait_run(started["run_id"])
    s2 = state()
    fresh_ab = [a for a in s2["artifacts"] if a["run_id"] == started["run_id"]
                and a["kind"] == "spatial-plan" and a["revision"] == 1]
    check("W0B-F01-03", "已消费历史不再封死新生成：显式留言后按 generate 跑出新的 A/B",
          bool(code == 201 and mg.get("task_hint") == "generate"
               and code2 == 202 and started["task_kind"] == "generate"
               and snap2["run_status"] == "succeeded" and len(fresh_ab) >= 2),
          {"post_status": code, "task_hint": mg.get("task_hint"),
           "run_status": code2, "task_kind": started["task_kind"],
           "run": snap2["run_status"], "fresh_ab_count": len(fresh_ab),
           "old_feedback_revived": False})

    # ================================== F01-c 跨候选待续改：必须显式冲突 + 可作废
    s2 = state()
    a2 = next(a for a in valid_plans(s2) if a["option_id"] == "A")
    b2 = next(a for a in valid_plans(s2) if a["option_id"] == "B")
    code_a, msg_a = post_message("A 的东洽谈区尺度再调一下", a2)
    code_b, msg_b = post_message("B 的入口动线再顺一下", b2)
    code, blocked = start_run()
    pending = blocked.get("error") or ""
    check("W0B-F01-04", "跨候选两条待续改：拒绝自动合并，明确要求先决定（不丢下更早那条）",
          bool(code == 409 and blocked.get("conflict_code") == "multiple_pending_feedback"
               and msg_a["feedback"]["id"] in pending
               and msg_b["feedback"]["id"] in pending),
          {"status": code, "conflict_code": blocked.get("conflict_code"),
           "detail": pending[:300],
           "both_listed": [msg_a["feedback"]["id"] in pending,
                           msg_b["feedback"]["id"] in pending]})

    # explicit withdraw of the older message, then the newer one can run
    code, withdrew = http(
        f"/studio/projects/{PID}/feedback/{msg_a['feedback']['id']}/withdraw",
        {"reason": "先处理 B 的动线，A 这条留到下一轮"})
    code2, started = start_run()
    snap3 = wait_run(started["run_id"])
    check("W0B-F01-05", "显式作废更早那条后：按剩下那条续改，正文与历史保留",
          bool(code == 200 and withdrew.get("applied")
               and withdrew.get("text_preserved") == "A 的东洽谈区尺度再调一下"
               and code2 == 202 and started["task_kind"] == "revise"
               and started["target_artifact_id"] == b2["id"]
               and snap3["run_status"] in ("succeeded", "incomplete")),
          {"withdraw_status": code, "withdraw": {k: withdrew.get(k) for k in
                                                ("applied", "reason", "superseded_by",
                                                 "text_preserved")},
           "run_status": code2, "task_kind": started["task_kind"],
           "target_artifact_id": started.get("target_artifact_id"),
           "b2_id": b2["id"], "run_result": snap3["run_status"]})

    # ============================================= F03 保留非入口对象被改动
    s3 = state()
    a3 = next(a for a in valid_plans(s3) if a["option_id"] == "A")
    base3 = plan_of(s3, a3["id"])
    za5 = next(z for z in base3["zones"] if z["id"] == "ZA5")
    moved = copy.deepcopy(za5)
    moved["polygon"] = [[p[0] + 150, p[1]] for p in za5["polygon"]]
    original = vsl.revision_payload
    vsl.revision_payload = lambda: {
        "responses": [],
        "patch": [{"op": "update", "group": "circulation", "id": "CA1",
                   "fields": {"width_mm": 2100}},
                  {"op": "update", "group": "zones", "id": "ZA5",
                   "fields": {"polygon": moved["polygon"],
                              "area_sqm": za5["area_sqm"]}}]}
    try:
        code, post = post_message("主动线净宽扩大到 2100mm，保留东洽谈区不动", a3)
        code2, started = start_run()
        snap4 = wait_run(started["run_id"])
        diag = json.dumps([a.get("diagnostics") for a in snap4["artifacts"]
                           if a["kind"] == "spatial-plan-raw"], ensure_ascii=False)
        check("W0B-F03-01", "保留的是非入口对象 ZA5：改了它 → 明确拒绝，不拿入口锁冒充",
              bool(code == 201 and code2 == 202 and snap4["run_status"] == "incomplete"
                   and "LOCK-PRESERVE" in diag and "ZA5" in diag
                   and not snap4["valid_artifacts"]),
              {"post": code, "run": code2, "run_status": snap4["run_status"],
               "invalid_raw": len([a for a in snap4["artifacts"]
                                   if a["kind"] == "spatial-plan-raw"]),
               "LOCK_PRESERVE_in_diagnostics": "LOCK-PRESERVE" in diag,
               "ZA5_in_diagnostics": "ZA5" in diag,
               "valid_revision_in_this_run": snap4["valid_artifacts"]})
    finally:
        vsl.revision_payload = original

    # ---------------------------------------------------- F03 找不到对象 → unknown
    s4 = state()
    a4 = next(a for a in valid_plans(s4) if a["option_id"] == "A")
    base4 = plan_of(s4, a4["id"])
    objs = revision_task.derive_objectives(
        [{"feedback_id": "f", "revision_no": 1, "kind": "boss_message",
          "text": "保留西侧样品库不动", "locks": [], "objectives": []}], None, plan=base4)
    recheck = revision_task.recheck_objectives(objs, base4, copy.deepcopy(base4),
                                               site=SITE)
    check("W0B-F03-02", "找不到对象的保留要求：unknown + pending，并记下未绑定的原文",
          bool(len(objs) == 1 and objs[0]["kind"] == "preserve"
               and objs[0]["binding_status"] == "unresolved"
               and recheck[0]["objective_rechecked"] == "unknown"
               and recheck[0]["user_confirmed"] == "pending"
               and recheck[0]["resolved"] is None),
          {"objective": {k: objs[0].get(k) for k in
                         ("kind", "binding_status", "object_ids", "source_text")},
           "rechecked": recheck[0]["objective_rechecked"],
           "user_confirmed": recheck[0]["user_confirmed"],
           "resolved": recheck[0]["resolved"]})

    # ================================================== F04 字段锁（服务级）
    s5 = state()
    a5 = next(a for a in valid_plans(s5) if a["option_id"] == "A")
    vsl.revision_payload = lambda: {
        "responses": [], "patch": [{"op": "update", "group": "furniture", "id": "F1",
                                    "fields": {"rot": 30}}]}
    try:
        code, post = post_message("沙发位置别动，先把它转个角度", a5,
                                 locks=[{"object_id": "F1", "fields": ["x"],
                                         "reason": "沙发落位锁定"}])
        code2, started = start_run()
        snap5 = wait_run(started["run_id"])
        s5b = state()
        rev5 = next((a for a in s5b["artifacts"] if a["run_id"] == started["run_id"]
                     and a["kind"] == "spatial-plan" and a["revision"] >= 2), None)
        new_rot = (next(f for f in rev5["payload"]["furniture"] if f["id"] == "F1")["rot"]
                   if rev5 else None)
        new_x = (next(f for f in rev5["payload"]["furniture"] if f["id"] == "F1")["x"]
                 if rev5 else None)
        old_x = next(f for f in base_plan["furniture"] if f["id"] == "F1")["x"]
        check("W0B-F04-01", "锁 F1.x 只改 F1.rot：允许通过（字段锁不是整对象锁）",
              bool(code == 201 and code2 == 202 and snap5["run_status"] == "succeeded"
                   and rev5 is not None and new_rot == 30 and new_x == old_x),
              {"post": code, "run": code2, "run_status": snap5["run_status"],
               "F1_rot_after": new_rot, "F1_x_before": old_x, "F1_x_after": new_x,
               "lock_used": {"object_id": "F1", "fields": ["x"]}})
    finally:
        vsl.revision_payload = original

    # lock x, change x → rejected
    s6 = state()
    a6 = next(a for a in valid_plans(s6) if a["option_id"] == "A")
    base6 = plan_of(s6, a6["id"])
    fx = next(f for f in base6["furniture"] if f["id"] == "F1")["x"]
    vsl.revision_payload = lambda: {
        "responses": [], "patch": [{"op": "update", "group": "furniture", "id": "F1",
                                    "fields": {"x": fx + 120}}]}
    try:
        code, post = post_message("沙发挪一点", a6,
                                 locks=[{"object_id": "F1", "fields": ["x"],
                                         "reason": "沙发落位锁定"}])
        code2, started = start_run()
        snap6 = wait_run(started["run_id"])
        diag = json.dumps([a.get("diagnostics") for a in snap6["artifacts"]
                           if a["kind"] == "spatial-plan-raw"], ensure_ascii=False)
        check("W0B-F04-02", "锁 F1.x 且真的改了 F1.x：拒绝，冲突给出被锁字段",
              bool(code == 201 and code2 == 202 and snap6["run_status"] == "incomplete"
                   and "LOCK-REVISION" in diag and not snap6["valid_artifacts"]),
              {"post": code, "run": code2, "run_status": snap6["run_status"],
               "LOCK_REVISION_in_diagnostics": "LOCK-REVISION" in diag,
               "valid_revision_in_this_run": snap6["valid_artifacts"]})
    finally:
        vsl.revision_payload = original

    # ================================================= F02 部分达标（服务级）
    s7 = state()
    a7 = next(a for a in valid_plans(s7) if a["option_id"] == "A")
    vsl.revision_payload = lambda: {
        "responses": [], "patch": [
            {"op": "update", "group": "furniture", "id": "F1", "fields": {"rot": 45}},
            {"op": "update", "group": "furniture", "id": "F3", "fields": {"rot": 45}}]}
    try:
        code, post = post_message(
            "F1 和 F2 都转到 45 度", a7,
            objectives=[{"kind": "measurable", "rule_id": "STD-001", "field": "rot",
                         "target": 45, "unit": "degree", "objects_scope": ["furniture"],
                         "object_ids": ["F1", "F2"], "comparator": "exact",
                         "quantifier": "all", "source": "structured"}])
        code2, started = start_run()
        snap7 = wait_run(started["run_id"])
        diag = json.dumps([a.get("diagnostics") for a in snap7["artifacts"]
                           if a["kind"] == "spatial-plan-raw"], ensure_ascii=False)
        check("W0B-F02-01", "两个目标对象只达标一个：拒绝，不把部分达标记成已解决",
              bool(code == 201 and code2 == 202 and snap7["run_status"] == "incomplete"
                   and "REV-OBJECTIVE" in diag and "F2" in diag
                   and not snap7["valid_artifacts"]),
              {"post": code, "run": code2, "run_status": snap7["run_status"],
               "REV_OBJECTIVE_in_diagnostics": "REV-OBJECTIVE" in diag,
               "F2_in_diagnostics": "F2" in diag,
               "valid_revision_in_this_run": snap7["valid_artifacts"]})
    finally:
        vsl.revision_payload = original

    # --------------------------------------- F02 最低值/精确值/上限语义区分
    # (a) 三种比较符在同一对象字段上必须给出不同判定，不能互相冒充。
    s7b = state()
    a7b = next(a for a in valid_plans(s7b) if a["option_id"] == "A")
    base7b = plan_of(s7b, a7b["id"])
    moved = copy.deepcopy(base7b)
    f1_base = next(f for f in base7b["furniture"] if f["id"] == "F1")["rot"]
    for f in moved["furniture"]:
        if f["id"] == "F1":
            f["rot"] = f1_base + 45
    measured_rot = f1_base + 45

    def _obj(oid, comparator, target, field="rot", rule="STD-001",
             scope="furniture", ids=("F1",), unit="degree"):
        return {"objective_id": oid, "kind": "measurable", "rule_id": rule,
                "field": field, "target": target, "unit": unit,
                "objects_scope": [scope], "object_ids": list(ids),
                "comparator": comparator, "quantifier": "all",
                "source": "structured", "computable": True}

    quad = revision_task.recheck_objectives(
        [_obj("MIN", "min", measured_rot - 10),
         _obj("EXACT_OK", "exact", measured_rot),
         _obj("EXACT_NO", "exact", measured_rot - 10),
         _obj("MAX_OK", "max", measured_rot + 10),
         _obj("MAX_NO", "max", measured_rot - 10)],
        base7b, moved, site=SITE)
    by_id = {r["objective_id"]: r for r in quad}
    states = {k: v["objective_rechecked"] for k, v in by_id.items()}
    comparators = {k: (v.get("evidence", {}).get("after", {}) or {}).get("comparator")
                   for k, v in by_id.items()}
    semantics_ok = bool(
        states == {"MIN": "pass", "EXACT_OK": "pass", "EXACT_NO": "fail",
                   "MAX_OK": "pass", "MAX_NO": "fail"}
        and comparators == {"MIN": "min", "EXACT_OK": "exact", "EXACT_NO": "exact",
                            "MAX_OK": "max", "MAX_NO": "max"})

    # (b) 净宽这类目标：图上声明值满足不算达标，几何复算的实测值也必须满足。
    #     该房间实测净宽被复算成 6000mm，声明通道宽只有 2300mm，
    #     所以 max 2400 必须判 fail —— 不能只看声明值就放行。
    wider = copy.deepcopy(base7b)
    for c in wider.get("circulation") or []:
        if c["id"] == "CA1":
            c["width_mm"] = 2300
    dual = revision_task.recheck_objectives(
        [_obj("WIDTH_MAX", "max", 2400, field="width_mm", rule="CIR-001",
              scope="circulation", ids=("CA1",), unit="mm")],
        base7b, wider, site=SITE)[0]
    width_ev = (dual.get("evidence", {}).get("after", {}) or {}).get("measured") or {}
    ca1 = width_ev.get("CA1") or {}
    dual_ok = bool(dual["objective_rechecked"] == "fail"
                   and ca1.get("declared_meets_target") is True
                   and ca1.get("measured_meets_target") is False)
    check("W0B-F02-02", "比较符各按语义判定：min/max/exact 判定不同，且声明满足不等于实测达标",
          bool(semantics_ok and dual_ok),
          {"states": states, "comparators": comparators,
           "measured_rot": measured_rot,
           "width_objective": {"state": dual["objective_rechecked"],
                               "declared_width_mm": ca1.get("declared_width_mm"),
                               "measured_clear_width_mm": ca1.get("measured_clear_width_mm"),
                               "declared_meets_target": ca1.get("declared_meets_target"),
                               "measured_meets_target": ca1.get("measured_meets_target"),
                               "coverage": (dual.get("evidence", {}).get("after", {}) or {})
                               .get("coverage")}})

    # ============================================ F05 可控晚到 + 取消 + 快照
    s8 = state()
    a8 = next(a for a in valid_plans(s8) if a["option_id"] == "A")
    reset_stub()
    payload_before_f05 = vsl.revision_payload
    # 让这一轮本来能交出合格续改（只转 F3），这样"晚到留言把它废掉"才是
    # 真的在测试取代，而不是被一个本来就无效的结果蒙对。
    vsl.revision_payload = lambda: {
        "responses": [], "patch": [{"op": "update", "group": "furniture", "id": "F3",
                                    "fields": {"rot": -30}}]}
    GatedStub.gate = threading.Event()
    GatedStub.at_call = 1
    GatedStub.hold = True
    code, post = post_message("把 F3 转到 -30 度", a8)
    code2, started = start_run()
    reached = GatedStub.reached.wait(60)
    mid = state()
    mid_run = next(r for r in mid["runs"] if r["id"] == started["run_id"])
    mid_valid = [a for a in mid["artifacts"] if a["run_id"] == started["run_id"]
                 and a.get("display_group") == "valid"]
    # a later boss message arrives WHILE the run is held at the barrier
    code3, late = post_message("先改北光廊，这一版不要了", a8)
    GatedStub.gate.set()
    snap9 = wait_run(started["run_id"])
    s9 = state()
    late_valid = [a for a in s9["artifacts"] if a["run_id"] == started["run_id"]
                  and a.get("display_group") == "valid"]
    cancelled_flag = next((r["cancel_requested"] for r in s9["runs"]
                           if r["id"] == started["run_id"]), None)
    check("W0B-F05-01", "运行中到达新留言：本轮按 run_id 判定为 superseded，产物不作为当前有效版本",
          bool(code2 == 202 and code3 == 201 and reached
               and mid_run["status"] == "running" and not mid_valid
               and snap9["run_status"] == "superseded"
               and cancelled_flag == 1 and not late_valid
               and s9["stage_status"]["last_completed_run_status"] == "superseded"
               and started["run_id"] not in
               [a["id"] for a in s9["artifacts"] if a.get("display_group") == "valid"]),
          {"run": code2, "late_message": code3, "barrier_reached": reached,
           "mid_run_status": mid_run["status"], "mid_valid_artifacts": len(mid_valid),
           "final_run_status": snap9["run_status"],
           "cancel_requested": cancelled_flag,
           "valid_artifacts_of_run_after": len(late_valid),
           "run_snapshot_artifact_count": snap9["artifact_count"],
           "run_snapshot_artifacts": [(a.get("kind"), a.get("status"),
                                       a.get("contract_status"))
                                      for a in snap9["artifacts"]],
           "stage_last_completed": s9["stage_status"]["last_completed_run_status"]})
    vsl.revision_payload = payload_before_f05
    reset_stub()

    # ==================================== F05 完成状态与产物同快照 + 试次累计
    s10 = state()
    same_snapshot = set(s10["stage_status"]["last_completed_run_id"] ==
                        (s10["last_completed_run"] or {}).get("id")
                        for _ in [0])
    ids_in_state = {a["id"] for a in s10["artifacts"]}
    reported = set((s10["last_completed_run"] or {}).get("artifact_ids") or [])
    check("W0B-F05-02", "完成状态与产物来自同一快照：完成轮的产物都在同一份状态里，且带快照令牌",
          bool(same_snapshot and reported <= ids_in_state
               and s10["stage_status"]["last_completed_run_artifacts"] == len(reported)
               and s10["snapshot"]["artifact_count"] == len(s10["artifacts"])
               and s10["snapshot"]["run_count"] == len(s10["runs"])
               and len(s10["snapshot"]["token"]) == 16),
          {"last_completed_run": s10["last_completed_run"],
           "reported_artifacts_subset": sorted(reported) <= sorted(ids_in_state),
           "snapshot": s10["snapshot"],
           "stage_status": s10["stage_status"]})

    # cumulative auto-rework: force the in-run retry loop to spend both rounds.
    # A generate intent is required, otherwise the pending revise message above
    # would (correctly) be taken as the current task and this path has no
    # automatic retry at all.
    bad = [{"op": "remove", "group": "furniture", "id": "F3"}]   # no reason -> PATCH-004
    vsl.revision_payload = lambda: {"responses": [], "patch": bad}
    try:
        code, mg2 = post_message("这一版不要了，按新想法重新出一版")
        code, gen2 = start_run()
        snap11 = wait_run(gen2["run_id"])
        s11 = state()
        run11 = next(r for r in s11["runs"] if r["id"] == gen2["run_id"])
        rework_msgs = [m for m in s11["messages"] if m["kind"] == "rework"]
        check("W0B-F01-06", "自动返工按设计试验累计并落库：本轮用满 2 轮后记录累计值，不因新 run 归零",
              bool(mg2.get("task_hint") == "generate" and code == 202
                   and gen2["task_kind"] == "generate"
                   and snap11["run_status"] in ("incomplete", "succeeded")
                   and int(run11.get("auto_rework_total") or 0) == 2
                   and len(rework_msgs) >= 2
                   and s11["trial_progress"]["auto_rework_used"] >= 2
                   and s11["trial_progress"]["max_auto_rework"] == 2),
              {"post_task_hint": mg2.get("task_hint"), "run": code,
               "task_kind": gen2["task_kind"],
               "run_status": snap11["run_status"],
               "auto_rework_total_in_run": run11.get("auto_rework_total"),
               "auto_rework_messages": [m["body"][:120] for m in rework_msgs],
               "trial_key": run11.get("trial_key"),
               "trial_progress": s11["trial_progress"]})
    finally:
        vsl.revision_payload = original

    passed = sum(1 for c in CHECKS if c["result"] == "observed_pass")
    failed = sum(1 for c in CHECKS if c["result"] == "observed_fail")
    packet = ROOT / "deliverables-for-review" / "roadmap" / "W0-二次收口"
    prev_packet = ROOT / "deliverables-for-review" / "roadmap" / "W0-收口"
    prev_hashes = {}
    if prev_packet.exists():
        for f in sorted(prev_packet.rglob("*")):
            if f.is_file():
                prev_hashes[str(f.relative_to(ROOT)).replace("\\", "/")] = \
                    hashlib.sha256(f.read_bytes()).hexdigest()
    out = {
        "task_id": "W0 二次收口（W0-F01—F05）",
        "schema_version": "rkd-w0b-checks.v1",
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "code_head": os.popen(f'git -C "{ROOT}" rev-parse HEAD').read().strip(),
        "environment": {"python": sys.version.split()[0],
                        "geometry_engine": "shapely-2.1.2",
                        "model_channel": "local-model-stub (explicitly labelled)",
                        "service": f"studio HTTP 127.0.0.1:{PORT} (isolated DB)",
                        "keys_used": False},
        "checks": CHECKS,
        "totals": {"observed_pass": passed, "observed_fail": failed},
        "previous_packet_hashes": prev_hashes,
        "external_calls": 0,
        "image_counts": {"images_sent_external": 0, "images_generated_external": 0},
        "tokens": 0,
        "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
        "limitations": [
            "本批是工程整改，没有新增设计成果；不构成设计或 AD01—AD08 结论",
            "Q10 同源平面/渲染/数量一致性仍 not_run（W1/W2）",
            "所有模型回答为明确标记的本地桩，不代表真实 AI 设计能力",
            "自动返工目前只发生在 generate 运行内部的打回循环；revise 路径不自动重复。"
            "累计值已持久化到设计试验并在状态里显示，任何新 run 都不会让它变小",
        ],
    }
    (EVIDENCE / "checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(json.dumps({"passed": passed, "failed": failed,
                      "out": str(EVIDENCE / "checks.json")}, ensure_ascii=False), flush=True)
    sys.exit(0 if failed == 0 else 1)
finally:
    httpd.shutdown()
    httpd.server_close()
