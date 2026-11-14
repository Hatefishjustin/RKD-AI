"""W0 二次收口：W0-F01—F05 的独立复现（不依赖服务体系，只碰真实 Store/校验函数）。

用法：
    python scripts/w0b_repro.py --phase before --out <path/repro.json>
    python scripts/w0b_repro.py --phase after  --out <path/repro.json>

每个案例都同时给出「缺陷签名」与「修复签名」两种判定，脚本只如实记录观察到
哪一种；同一份脚本可以在整改前后各跑一次，不需要改断言。没有任何 sleep：
F05 的时序用事件 + 独立线程做可控屏障（写线程在快照读取期间提交），不是靠等待
制造通过。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

from arc_first_batch_stub import SITE, REQUIREMENT, valid_proposal  # noqa: E402
from rkd_mvp.studio import revision as R, revision_task, validation  # noqa: E402
from rkd_mvp.studio.store import Store, new_id  # noqa: E402

PID = "ningbo-xiecheng"
PROJ = {"id": PID, "name": "宁波", "site": SITE, "requirement": REQUIREMENT}
CASES: list[dict] = []
_RUNTIME = Path(tempfile.mkdtemp(prefix="rkd-w0b-repro-"))


def _store(tag: str) -> Store:
    st = Store(_RUNTIME / f"{tag}.db")
    st.ensure_project(PID, "宁波协诚展厅", SITE, REQUIREMENT,
                      source_project_id=PID, mapping_note="复现用隔离库")
    return st


def _seed_plan(st: Store, option: str = "A", revision: int = 1,
               parent_uid: str | None = None) -> dict:
    rep = validation.validate_proposal(valid_proposal(option), project=PROJ,
                                       option_id=option, revision=revision,
                                       parent_revision=None)
    assert rep["ok"], rep["repair_feedback"]
    uid = new_id("revuid")
    aid = st.save_artifact(PID, "spatial-plan", rep["plan"], "D2", option_id=option,
                           revision=revision, status="valid_candidate",
                           revision_uid=uid, parent_revision_uid=parent_uid,
                           contract_status="valid_candidate")
    return {"id": aid, "revision_uid": uid, "plan": rep["plan"]}


def record(case: str, finding: str, observed: dict, defect: bool | None,
           notes: str = "") -> None:
    verdict = ("not_observable" if defect is None
               else "defect_reproduced" if defect else "fixed_signature")
    CASES.append({"case": case, "finding": finding, "observed": observed,
                  "verdict": verdict, "note": notes})
    print(f"{verdict:18s} {case} {json.dumps(observed, ensure_ascii=False)[:220]}",
          flush=True)


# --------------------------------------------------------------- F01 任务语义
def f01_stale_resurrection() -> None:
    st = _store("f01a")
    art = _seed_plan(st)
    old = st.add_feedback(PID, "boss_message", "旧留言：把 F3 转到 -15 度",
                          baseline_artifact_id=art["id"],
                          baseline_revision_uid=art["revision_uid"],
                          baseline_selection="user_selected")
    new = st.add_feedback(PID, "boss_message", "新留言：把 F3 转到 -30 度",
                          baseline_artifact_id=art["id"],
                          baseline_revision_uid=art["revision_uid"],
                          baseline_selection="user_selected")
    r1 = revision_task.resolve_task(st, PID, st.feedback_revision(PID))
    first = ((r1.get("feedback") or {}).get("id"))
    st.consume_feedback(new["id"], "run_sim_1")
    r2 = revision_task.resolve_task(st, PID, st.feedback_revision(PID))
    second_kind = r2["kind"]
    second_fb = ((r2.get("feedback") or {}).get("id"))
    obs = {"first_selected": "newer" if first == new["id"] else first,
           "first_kind": r1["kind"],
           "after_latest_consumed_kind": second_kind,
           "after_latest_consumed_feedback": ("older" if second_fb == old["id"]
                                              else second_fb),
           "after_latest_consumed_code": r2.get("conflict_code")}
    defect = second_kind == "revise" and second_fb == old["id"]
    record("F01-a", "旧反馈在最新一条被执行后自动复活", obs, defect)


def f01_generate_blocked() -> None:
    st = _store("f01b")
    art = _seed_plan(st)
    fb = st.add_feedback(PID, "boss_message", "把 F3 转到 -15 度",
                         baseline_artifact_id=art["id"],
                         baseline_revision_uid=art["revision_uid"],
                         baseline_selection="user_selected")
    st.consume_feedback(fb["id"], "run_sim_1")
    st.add_feedback(PID, "boss_message", "不用旧方案了，重新做一版新方案",
                    baseline_selection="none_explicit", task_kind="generate")
    r = revision_task.resolve_task(st, PID, st.feedback_revision(PID))
    obs = {"kind": r["kind"], "code": r.get("conflict_code"),
           "reason": (r.get("reason") or "")[:80]}
    defect = r["kind"] == "conflict" and r.get("conflict_code") == "feedback_already_consumed"
    record("F01-b", "已消费历史封死新的生成意图", obs, defect)


def f01_cross_candidate_silent_merge() -> None:
    st = _store("f01c")
    a = _seed_plan(st, "A")
    b = _seed_plan(st, "B")
    st.add_feedback(PID, "boss_message", "A 的洽谈区再改一改",
                    baseline_artifact_id=a["id"], baseline_revision_uid=a["revision_uid"],
                    baseline_selection="user_selected")
    fb_b = st.add_feedback(PID, "boss_message", "B 的入口动线再改一改",
                           baseline_artifact_id=b["id"],
                           baseline_revision_uid=b["revision_uid"],
                           baseline_selection="user_selected")
    r = revision_task.resolve_task(st, PID, st.feedback_revision(PID))
    pending = [f.get("feedback_id") for f in (r.get("pending_feedback") or [])]
    obs = {"kind": r["kind"], "code": r.get("conflict_code"),
           "selected_feedback": (r.get("feedback") or {}).get("id"),
           "pending_feedback": pending,
           "pending_listed": r.get("pending_feedback_ids") or pending or None,
           "newer_feedback_was": fb_b["id"]}
    defect = (r["kind"] == "revise"
              and not r.get("pending_feedback_ids") and not pending)
    record("F01-c", "跨候选的两条待续改留言被无声合并/丢弃", obs, defect)


def f01_same_baseline_merge() -> None:
    st = _store("f01d")
    a = _seed_plan(st)
    f1 = st.add_feedback(PID, "boss_message", "F3 转到 -15 度",
                         baseline_artifact_id=a["id"], baseline_revision_uid=a["revision_uid"],
                         baseline_selection="user_selected")
    f2 = st.add_feedback(PID, "boss_message", "中岛圆角再收一点",
                         baseline_artifact_id=a["id"], baseline_revision_uid=a["revision_uid"],
                         baseline_selection="user_selected")
    r = revision_task.resolve_task(st, PID, st.feedback_revision(PID))
    merged = sorted(r.get("merged_feedback_ids") or [])
    obs = {"kind": r["kind"], "merged_feedback_ids": merged,
           "expected_merged": sorted([f1["id"], f2["id"]])}
    defect = r["kind"] == "revise" and merged != sorted([f1["id"], f2["id"]])
    record("F01-d", "同基线多条待续改留言未显式合并（旧条会晚点复活）", obs, defect)


def f01_rework_carry() -> None:
    st = _store("f01e")
    art = _seed_plan(st)
    has_api = hasattr(st, "auto_rework_used")
    trial_key = None
    used = None
    if has_api:
        trial_key = st.trial_key_for(art["id"])
        used = st.auto_rework_used(trial_key)
    cols = {r[1] for r in st._conn().execute("PRAGMA table_info(runs)").fetchall()}
    obs = {"cumulative_api": has_api, "trial_key": trial_key,
           "auto_rework_used": used,
           "runs_has_auto_rework_total": "auto_rework_total" in cols,
           "runs_has_trial_key": "trial_key" in cols}
    defect = not (has_api and "auto_rework_total" in cols and "trial_key" in cols)
    record("F01-e", "自动返工次数未按设计试验累计（新 run 从 0 重新开始）", obs, defect,
           notes="结构性观测：记录累计计数器是否存在且可查询；"
                 "行为侧的累计见 verify_w0b.py 的 F01-e 场景")


# ------------------------------------------------------------- F02 目标量词
def _integ(base: dict, cand: dict, objectives: list[dict], **kw) -> dict:
    return R.verify_revision_integrity(
        base, cand, objectives=objectives, site=SITE,
        locks=revision_task.structured_locks(base, SITE), **kw)


def _derive(fb: list[dict], plan: dict) -> list[dict]:
    """Call derive_objectives with the plan when the build supports binding.

    Before the fix the parameter does not exist; the call must still run so the
    actual (defective) behaviour is observed instead of a TypeError.
    """
    import inspect
    if "plan" in inspect.signature(revision_task.derive_objectives).parameters:
        return revision_task.derive_objectives(fb, None, plan=plan)
    return revision_task.derive_objectives(fb, None)


def _rot_obj(ids: list[str], target: float = 45) -> dict:
    return {"objective_id": "T1", "kind": "measurable", "rule_id": "STD-001",
            "field": "rot", "target": target, "unit": "degree",
            "objects_scope": ["furniture"], "object_ids": ids,
            "source": "structured", "computable": True}


def f02_partial_pass() -> None:
    st = _store("f02a")
    a = _seed_plan(st)
    base = a["plan"]
    cand = copy.deepcopy(base)
    for f in cand["furniture"]:
        if f["id"] == "F1":
            f["rot"] = 45          # F1 达标
        if f["id"] == "F2":
            f["rot"] = 0           # F2 未达标
    integ = _integ(base, cand, [_rot_obj(["F1", "F2"])])
    row = integ["objective_rechecks"][0]
    ev = row.get("evidence", {}).get("after", {})
    obs = {"objective_rechecked": row["objective_rechecked"],
           "resolved": row["resolved"],
           "targets": row.get("target_objects"),
           "passing": ev.get("passing_object_ids"),
           "failing": ev.get("failing_object_ids"),
           "quantifier": ev.get("quantifier")}
    defect = row["objective_rechecked"] == "pass" and row["resolved"] is True
    record("F02-a", "多对象目标只要一个对象达标就判 pass", obs, defect)


def f02_missing_object() -> None:
    st = _store("f02b")
    a = _seed_plan(st)
    base = a["plan"]
    cand = copy.deepcopy(base)
    for f in cand["furniture"]:
        if f["id"] == "F1":
            f["rot"] = 45
    integ = _integ(base, cand, [_rot_obj(["F1", "FX"])])
    row = integ["objective_rechecks"][0]
    ev = row.get("evidence", {}).get("after", {})
    obs = {"objective_rechecked": row["objective_rechecked"],
           "resolved": row["resolved"],
           "targets": row.get("target_objects"),
           "missing": ev.get("missing_object_ids"),
           "passing": ev.get("passing_object_ids")}
    defect = row["objective_rechecked"] == "pass"
    record("F02-b", "目标点名的对象不存在时仍判 pass", obs, defect)


def f02_unrelated_only() -> None:
    st = _store("f02c")
    a = _seed_plan(st)
    base = a["plan"]
    cand = copy.deepcopy(base)
    for f in cand["furniture"]:
        if f["id"] == "F3":
            f["rot"] = 45          # 只有一件（且非目标清单内）家具达标
    obj = {"objective_id": "T2", "kind": "measurable", "rule_id": "STD-001",
           "field": "rot", "target": 45, "unit": "degree",
           "objects_scope": ["furniture"], "object_ids": [],
           "source": "structured", "computable": True}
    integ = _integ(base, cand, [obj])
    row = integ["objective_rechecks"][0]
    ev = row.get("evidence", {}).get("after", {})
    obs = {"objective_rechecked": row["objective_rechecked"],
           "passing": ev.get("passing_object_ids"),
           "failing": ev.get("failing_object_ids")}
    defect = row["objective_rechecked"] == "pass"
    record("F02-c", "范围内只有无关对象恰好达标就判 pass", obs, defect)


def f02_comparator() -> None:
    st = _store("f02d")
    a = _seed_plan(st)
    base = a["plan"]
    cand = copy.deepcopy(base)
    for c in cand.get("circulation") or []:
        if c["id"] == "CA1":
            c["width_mm"] = 2300        # 高于 2100 的最低值要求，但不等于「精确 2100」
    minimum = {"objective_id": "M1", "kind": "measurable", "rule_id": "CIR-001",
               "field": "width_mm", "target": 2100, "unit": "mm",
               "objects_scope": ["circulation"], "object_ids": ["CA1"],
               "comparator": "min", "source": "structured", "computable": True}
    exact = dict(minimum, objective_id="M2", comparator="exact")
    integ = _integ(base, cand, [minimum, exact])
    rows = {r["objective_id"]: r for r in integ["objective_rechecks"]}
    obs = {"min_2300": rows["M1"]["objective_rechecked"],
           "exact_2300": rows["M2"]["objective_rechecked"],
           "min_comparator_recorded": rows["M1"].get("evidence", {}).get("after", {})
           .get("comparator"),
           "width_coverage": rows["M1"].get("evidence", {}).get("after", {}).get("coverage")}
    defect = obs["exact_2300"] == "pass" or obs["min_comparator_recorded"] is None
    record("F02-d", "最低值/精确值/上限语义混用（比较符被忽略）", obs, defect)


# --------------------------------------------------------- F03 保留要求绑定
PRESERVE_TEXT = "主动线净宽扩大到 2100mm，保留东洽谈区不动"


def _zone_change(plan: dict, zone_id: str, dx: int = 120) -> dict:
    out = copy.deepcopy(plan)
    for z in out["zones"]:
        if z["id"] == zone_id:
            z["polygon"] = [[p[0] + dx, p[1]] for p in z["polygon"]]
    return out


def f03_non_arrival_preserve() -> None:
    st = _store("f03a")
    a = _seed_plan(st)
    base = a["plan"]
    fb = [{"feedback_id": "fb_p1", "revision_no": 1, "kind": "boss_message",
           "text": PRESERVE_TEXT, "locks": [], "objectives": []}]
    objs = _derive(fb, base)
    cand = _zone_change(base, "ZA5")
    for c in cand.get("circulation") or []:
        if c["id"] == "CA1":
            c["width_mm"] = 2100
    integ = _integ(base, cand, objs, boss_feedback=fb)
    rows = [r for r in integ["objective_rechecks"] if r["kind"] in ("lock", "preserve")]
    obs = {"objectives": [{"kind": o.get("kind"), "object_ids": o.get("object_ids"),
                            "binding": o.get("binding_status")} for o in objs],
           "preserve_rows": [{"rechecked": r["objective_rechecked"],
                              "resolved": r["resolved"],
                              "target_objects": r.get("target_objects")} for r in rows],
           "ZA5_changed": "ZA5" in [c.split(":")[1] for c in integ["changed_objects"]],
           "overall_ok": integ["ok"]}
    defect = any(r["objective_rechecked"] == "pass" for r in rows) and obs["ZA5_changed"]
    record("F03-a", "保留非入口对象被改动，保留要求仍判 pass（实际校验的是入口锁）",
           obs, defect)


def f03_unresolved() -> None:
    st = _store("f03b")
    a = _seed_plan(st)
    base = a["plan"]
    fb = [{"feedback_id": "fb_p2", "revision_no": 1, "kind": "boss_message",
           "text": "保留西侧样品库不动", "locks": [], "objectives": []}]
    objs = _derive(fb, base)
    integ = _integ(base, copy.deepcopy(base), objs, boss_feedback=fb)
    rows = integ["objective_rechecks"]
    preserve = [o for o in objs if o.get("kind") in ("lock", "preserve")]
    obs = {"objective_kinds": [{"kind": o.get("kind"), "binding": o.get("binding_status"),
                                "object_ids": o.get("object_ids")} for o in objs],
           "preserve_count": len(preserve),
           "binding_status": [o.get("binding_status") for o in preserve],
           "states": [(r["objective_rechecked"], r["user_confirmed"]) for r in rows]}
    # unknown alone is not enough: the requirement must still be TRACKED as an
    # unresolved preserve claim, not silently converted into an aesthetic note.
    defect = (not preserve
              or any(r["objective_rechecked"] == "pass" for r in rows)
              or not any(o.get("binding_status") in ("unresolved", "ambiguous")
                         for o in preserve))
    record("F03-b", "找不到对象的保留要求被当通过 / 被降级成空泛意见（应为 unknown+pending 且留痕）",
           obs, defect)


def f03_preserve_only_text() -> None:
    st = _store("f03c")
    a = _seed_plan(st)
    base = a["plan"]
    fb = [{"feedback_id": "fb_p3", "revision_no": 1, "kind": "boss_message",
           "text": "保留东洽谈区不动", "locks": [], "objectives": []}]
    objs = _derive(fb, base)
    kinds = [o.get("kind") for o in objs]
    obs = {"kinds": kinds,
           "has_preserve": any(k in ("lock", "preserve") for k in kinds)}
    defect = not obs["has_preserve"]
    record("F03-c", "只有保留诉求时该诉求被丢弃（只剩审美兜底）", obs, defect)


def f03_mixed() -> None:
    st = _store("f03d")
    a = _seed_plan(st)
    base = a["plan"]
    fb = [{"feedback_id": "fb_p4", "revision_no": 1, "kind": "boss_message",
           "text": "净宽改到 2100mm，保留东洽谈区不动，整体要更有呼吸感",
           "locks": [], "objectives": []}]
    objs = _derive(fb, base)
    preserve = [o for o in objs if o.get("kind") in ("lock", "preserve")]
    obs = {"kinds": [o.get("kind") for o in objs],
           "has_numeric": any(o.get("kind") == "measurable" for o in objs),
           "has_preserve": bool(preserve),
           "preserve_object_ids": [o.get("object_ids") for o in preserve],
           "preserve_binding": [o.get("binding_status") for o in preserve],
           "has_aesthetic": any(o.get("kind") == "aesthetic" for o in objs)}
    # 文本里点名了「东洽谈」（ZA5 的名称），没有绑定就是没解析成功
    defect = (not (obs["has_numeric"] and obs["has_preserve"])
              or not any(o.get("object_ids") for o in preserve))
    record("F03-e", "混合留言的保留/审美诉求被其中一个数值目标吞掉或未绑定对象", obs, defect)


# --------------------------------------------------------------- F04 字段锁
def f04_field_lock() -> None:
    st = _store("f04a")
    a = _seed_plan(st)
    base = a["plan"]
    locks = {"locks": [{"object_id": "F1", "fields": ["x"], "source": "user_explicit",
                        "reason": "沙发位置锁定"}],
             "lock_object_ids": ["F1"]}

    def _cand(mutate) -> dict:
        c = copy.deepcopy(base)
        for f in c["furniture"]:
            if f["id"] == "F1":
                mutate(f)
        return c

    rot_only = revision_task.lock_conflicts(base, _cand(lambda f: f.update(rot=30)), locks)
    x_changed = revision_task.lock_conflicts(base, _cand(lambda f: f.update(x=f["x"] + 50)),
                                             locks)
    removed = copy.deepcopy(base)
    removed["furniture"] = [f for f in removed["furniture"] if f["id"] != "F1"]
    deleted = revision_task.lock_conflicts(base, removed, locks)
    star = {"locks": [{"object_id": "F1", "fields": ["*"], "source": "user_explicit",
                       "reason": "整件保留"}], "lock_object_ids": ["F1"]}
    star_rot = revision_task.lock_conflicts(base, _cand(lambda f: f.update(rot=30)), star)
    ghost = {"locks": [{"object_id": "F1", "fields": ["ghost_field"],
                        "source": "user_explicit", "reason": "拼错的字段"}],
             "lock_object_ids": ["F1"]}
    ghost_none = revision_task.lock_conflicts(base, copy.deepcopy(base), ghost)
    obs = {"rot_only_conflicts": len(rot_only),
           "rot_only_fields": [c.get("fields") for c in rot_only],
           "rot_only_changed_fields": [c.get("changed_fields") for c in rot_only],
           "x_changed_conflicts": len(x_changed),
           "x_changed_fields": [c.get("changed_fields") for c in x_changed],
           "deleted_conflicts": len(deleted),
           "deleted_diagnostic": [c.get("diagnostic") for c in deleted],
           "star_rot_conflicts": len(star_rot),
           "ghost_no_change_conflicts": len(ghost_none),
           "ghost_diagnostic": [c.get("diagnostic") for c in ghost_none]}
    defect = len(rot_only) > 0 or len(x_changed) == 0 or len(deleted) == 0 or \
        len(star_rot) == 0 or len(ghost_none) == 0
    record("F04-a", "字段锁实际按整对象比较：锁 x 也拦下改 rot；未知字段无人诊断",
           obs, defect)


def f04_validation_stage() -> None:
    """The whole-object lock must not come back through stage 4 of validation."""
    import inspect
    st = _store("f04b")
    a = _seed_plan(st)
    base = a["plan"]
    cand = copy.deepcopy(base)
    cand.pop("project_id", None)
    cand.pop("option_id", None)
    cand.pop("revision", None)
    cand.pop("author", None)
    cand.pop("contract_version", None)
    for f in cand["furniture"]:
        if f["id"] == "F1":
            f["rot"] = 30
    locks = {"locks": [{"object_id": "F1", "fields": ["x"], "source": "user_explicit",
                        "reason": "沙发位置锁定"}], "lock_object_ids": ["F1"]}
    accepts = "locks" in inspect.signature(validation.validate_proposal).parameters
    kw = {"locks": locks} if accepts else {"lock_object_ids": ["F1"]}
    rep = validation.validate_proposal(cand, project=PROJ, option_id="A", revision=2,
                                       parent_revision=1, previous_plan=base, **kw)
    lock_errors = [e["message"] for e in rep["errors"] if e["rule_id"] == "LOCK-REVISION"]
    obs = {"ok": rep["ok"], "stage": rep["stage"], "lock_errors": lock_errors,
           "accepts_structured_locks": accepts,
           "mode": "structured_fields" if accepts else "whole_object_ids"}
    defect = (not rep["ok"] and bool(lock_errors)) or not accepts
    record("F04-b", "四级校验的锁定阶段把字段锁升级为整对象锁", obs, defect)


# ------------------------------------------------------- F05 状态与产物快照
def f05_torn_read() -> None:
    """Controlled barrier: a writer commits EXACTLY between the artifact read and
    the run read. No sleep is used; the barrier is a thread join."""
    import inspect
    st = _store("f05a")
    art = _seed_plan(st)
    ih = "input-hash-sim"
    run_id = st.start_run(PID, "local-model-stub", input_hash_value=ih,
                          expected_feedback_revision=0, candidate_group_id="cg_sim",
                          task_kind="revise", target_artifact_id=art["id"],
                          target_revision_uid=art["revision_uid"])
    fired = {"done": False}
    writer_error: dict = {"error": None}

    def commit_new_version() -> None:
        """The run finishes and publishes its result (a normal writer thread)."""
        def work() -> None:
            try:
                st.save_artifact(PID, "spatial-plan", art["plan"], "D2",
                                 option_id="A", revision=2, status="valid_candidate",
                                 run_id=run_id, candidate_group_id="cg_sim",
                                 revision_uid=new_id("revuid"), parent_revision_uid=None,
                                 input_hash_value=ih,
                                 contract_status="valid_candidate")
                st.finish_run(run_id, "succeeded", 1, 1, None, calls=1)
            except Exception as exc:  # noqa: BLE001
                writer_error["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                fired["done"] = True

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(60)

    barrier_supported = "barrier" in inspect.signature(st.project_state).parameters
    if barrier_supported:
        state = st.project_state(PID, barrier=commit_new_version)
        mode = "in_snapshot_barrier"
    else:
        class RacingStore(Store):
            def runs(self, project_id: str):
                if not fired["done"]:
                    commit_new_version()   # writer commits BEFORE the run read
                return super().runs(project_id)

        state = RacingStore(st.path).project_state(PID)
        mode = "subclass_barrier"

    run = next((r for r in state["runs"] if r["id"] == run_id), None)
    in_snapshot = [a["id"] for a in state["artifacts"]
                   if a["run_id"] == run_id and a["kind"] == "spatial-plan"]
    run_status = run["status"] if run else None
    after = st.project_state(PID)
    after_has = [a["id"] for a in after["artifacts"] if a["run_id"] == run_id]
    consistent = (run_status == "succeeded") == bool(in_snapshot)
    obs = {"mode": mode,
           "snapshot_run_status": run_status,
           "snapshot_artifacts_for_run": len(in_snapshot),
           "consistent": consistent,
           "writer_error": writer_error["error"],
           "after_artifacts_for_run": len(after_has),
           "has_snapshot_meta": "snapshot" in state}
    defect = not consistent
    record("F05-a", "状态响应混拼两个时间点：run 已完成但同一快照里没有它的产物",
           obs, defect)


def f05_run_scope() -> None:
    st = _store("f05b")
    obs = {"run_scoped_reader": hasattr(st, "run_snapshot")}
    defect = not obs["run_scoped_reader"]
    record("F05-b", "客户端只能按 runs[-1] 猜测本轮结果，没有按 run_id 的读取边界",
           obs, defect, notes="结构性观测；HTTP 侧按 run_id 的读取见 verify_w0b.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="before")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    started = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds")
    for fn in (f01_stale_resurrection, f01_generate_blocked, f01_cross_candidate_silent_merge,
               f01_same_baseline_merge, f01_rework_carry,
               f02_partial_pass, f02_missing_object, f02_unrelated_only, f02_comparator,
               f03_non_arrival_preserve, f03_unresolved, f03_preserve_only_text, f03_mixed,
               f04_field_lock, f04_validation_stage,
               f05_torn_read, f05_run_scope):
        try:
            fn()
        except Exception:  # noqa: BLE001 - a crash is evidence too
            CASES.append({"case": fn.__name__, "verdict": "crashed",
                          "observed": {"traceback": traceback.format_exc()[-1200:]}})
            print("CRASHED            " + fn.__name__, flush=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {"defect_reproduced": sum(1 for c in CASES if c["verdict"] == "defect_reproduced"),
               "fixed_signature": sum(1 for c in CASES if c["verdict"] == "fixed_signature"),
               "not_observable": sum(1 for c in CASES if c["verdict"] == "not_observable"),
               "crashed": sum(1 for c in CASES if c["verdict"] == "crashed")}
    out.write_text(json.dumps({
        "task_id": "W0 二次收口（W0-F01—F05）",
        "schema_version": "rkd-w0b-repro.v1",
        "phase": args.phase,
        "executed_at": started,
        "git_head": os.popen("git -C \"%s\" rev-parse HEAD" % ROOT).read().strip(),
        "environment": {"python": sys.version.split()[0],
                        "model_calls": "none (pure function / store level)",
                        "isolated_dbs": str(_RUNTIME)},
        "cases": CASES, "summary": summary,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
