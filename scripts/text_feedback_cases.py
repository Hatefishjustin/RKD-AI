"""TEXT-01 文字反馈解析：整改前/后的函数级签名（同一脚本可复跑两个版本）。

只调用真实的 derive_objectives / recheck_objectives / text_conflicts 与现有有效
夹具，不调模型、不起服务、不写库。判定签名：
  defect_reproduced  旧实现确实把对象范围/比较符/未解析子句弄错
  fixed_signature    新实现的行为签名正确
  not_observable     该构建没有对应入口，无法观测
  crashed            调用直接抛异常（不能算复现已完成）

用法：python scripts/text_feedback_cases.py --phase before|after --out <path>
"""
from __future__ import annotations

import copy
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from arc_first_batch_stub import SITE, valid_proposal  # noqa: E402
from rkd_mvp.studio import revision_task as rt, validation  # noqa: E402

CASES: list[dict] = []


def record(case: str, finding: str, observed: dict, fixed: bool,
           verdict: str | None = None) -> None:
    verdict = verdict or ("fixed_signature" if fixed else "defect_reproduced")
    CASES.append({"case": case, "finding": finding, "observed": observed,
                  "verdict": verdict})
    print(f"{verdict:17s} {case} {json.dumps(observed, ensure_ascii=False)[:220]}",
          flush=True)


def base_plan() -> dict:
    rep = validation.validate_proposal(
        valid_proposal("A"), project={"id": "p", "site": SITE},
        option_id="A", revision=1, parent_revision=None)
    assert rep["ok"], rep["repair_feedback"][:500]
    return rep["plan"]


BASE = base_plan()


def derive(text: str, plan: dict | None = None) -> list[dict]:
    fb = [{"id": "fb_t", "feedback_id": "fb_t", "revision_no": 1,
           "kind": "boss_message", "text": text, "locks": [], "objectives": []}]
    return rt.derive_objectives(fb, None, plan=plan if plan is not None else BASE)


def recheck(text: str, mutate) -> tuple[list[dict], dict, list[dict]]:
    objs = derive(text)
    cand = copy.deepcopy(BASE)
    mutate(cand)
    integ = rt.recheck_objectives(objs, BASE, cand, site=SITE)
    return objs, cand, integ


def _rot(cand: dict, oid: str, value: float) -> None:
    for f in cand["furniture"]:
        if f["id"] == oid:
            f["rot"] = value


# --------------------------------------------------------------- 1 对象范围
def t01_named_object_not_widened() -> None:
    text = "把 F3 旋转到 -30 度，其他家具不动"
    objs = derive(text)
    meas = [o for o in objs if o["kind"] == "measurable"]
    pres = [o for o in objs if o["kind"] == "preserve"]
    objs2, _cand, integ = recheck(text, lambda c: _rot(c, "F3", -30))
    rows = [r for r in integ if r["kind"] == "measurable"]
    obs = {
        "measurable_object_ids": [o.get("object_ids") for o in meas],
        "measurable_scope": [o.get("objects_scope") for o in meas],
        "preserve_binding": [(o.get("binding_status"), o.get("binding_match"),
                             o.get("object_ids")) for o in pres],
        "recheck_targets": [r.get("target_objects") for r in rows],
        "recheck_states": [r.get("objective_rechecked") for r in rows],
    }
    fixed = (len(meas) == 1 and meas[0]["object_ids"] == ["F3"]
             and rows and rows[0]["target_objects"] == ["F3"]
             and rows[0]["objective_rechecked"] == "pass"
             and pres and all(o.get("binding_status") == "resolved"
                              for o in pres)
             and sorted(pres[0].get("object_ids") or []) == ["F1", "F2"])
    record("T01-a", "点名 F3 却被扩大成整类家具；「其他家具不动」未绑定", obs, fixed)


def t01b_unrelated_furniture_change_rejected() -> None:
    text = "把 F3 旋转到 -30 度，其他家具不动"
    objs = derive(text)
    cand = copy.deepcopy(BASE)
    _rot(cand, "F3", -30)
    _rot(cand, "F1", 45)
    pres = [o for o in objs if o["kind"] == "preserve"]
    locks = {"locks": [{"object_id": oid, "fields": ["*"], "source": "text_preserve",
                        "reason": "其他家具不动"}
                       for o in pres for oid in (o.get("object_ids") or [])]}
    conflicts = rt.lock_conflicts(BASE, cand, locks)
    obs = {"locked_ids": [o.get("object_ids") for o in pres],
           "conflict_object_ids": [c.get("object_id") for c in conflicts],
           "conflict_diagnostics": [c.get("diagnostic") for c in conflicts]}
    fixed = bool(pres and all(o.get("binding_status") == "resolved" for o in pres)
                 and any(c.get("object_id") == "F1" for c in conflicts))
    record("T01-b", "误改「其他家具」应被保留要求拦下，而不是只靠模型自觉", obs, fixed)


def t02_two_named_objects() -> None:
    text = "把 F1 和 F3 都转到 30 度"
    objs = derive(text)
    meas = [o for o in objs if o["kind"] == "measurable"]
    _o, _c, integ = recheck(text, lambda c: _rot(c, "F3", 30))
    states = [r.get("objective_rechecked") for r in integ]
    obs = {"object_ids": [o.get("object_ids") for o in meas],
           "quantifier": [o.get("quantifier") for o in meas],
           "states_when_only_F3_changed": states}
    fixed = (len(meas) == 1 and (meas[0].get("object_ids") or []) == ["F1", "F3"]
             and "fail" in states)
    record("T02", "点名两个对象时只改一个不能算达标", obs, fixed)


def t03_explicit_all_is_allowed() -> None:
    text = "把家具都转到 30 度"
    objs = derive(text)
    meas = [o for o in objs if o["kind"] == "measurable"]
    obs = {"scope": [o.get("objects_scope") for o in meas],
           "object_ids": [o.get("object_ids") for o in meas],
           "quantifier": [o.get("quantifier") for o in meas]}
    fixed = bool(meas and meas[0].get("objects_scope") == ["furniture"]
                 and not meas[0].get("object_ids")
                 and meas[0].get("quantifier") == "all")
    record("T03", "明确说「都/所有」时才允许整组范围", obs, fixed)


def t04_missing_object_not_widened() -> None:
    text = "把 F9 旋转到 30 度"
    objs = derive(text)
    meas = [o for o in objs if o["kind"] == "measurable"]
    _o, _c, integ = recheck(text, lambda c: _rot(c, "F3", 30))
    obs = {"object_ids": [o.get("object_ids") for o in meas],
           "scope": [o.get("objects_scope") for o in meas],
           "binding": [(o.get("binding_status"), o.get("binding_match")) for o in meas],
           "states": [r.get("objective_rechecked") for r in integ],
           "missing": [r.get("evidence", {}).get("after", {}).get("missing_object_ids")
                       for r in integ]}
    fixed = bool(meas and meas[0].get("object_ids") == ["F9"]
                 and not meas[0].get("objects_scope")
                 and integ and integ[0]["objective_rechecked"] == "fail"
                 and integ[0]["evidence"]["after"]["missing_object_ids"] == ["F9"])
    record("T04", "点名不存在的对象不能退回整类；应按对象缺失处理", obs, fixed)


def t05_same_name_ambiguity() -> None:
    plan = copy.deepcopy(BASE)
    for f in plan["furniture"]:
        if f["id"] in ("F1", "F2"):
            f["name"] = "洽谈桌"
    text = "保留洽谈桌不动"
    objs = derive(text, plan)
    pres = [o for o in objs if o["kind"] == "preserve"]
    obs = {"binding": [(o.get("binding_status"), o.get("binding_match"),
                        o.get("object_ids")) for o in pres],
           "candidates": [o.get("binding_candidates") for o in pres]}
    fixed = bool(pres and pres[0].get("binding_status") == "ambiguous"
                 and not pres[0].get("object_ids")
                 and len(pres[0].get("binding_candidates") or []) == 2)
    record("T05", "同名对象歧义应报候选，不能随便挑一个绑定", obs, fixed)


# --------------------------------------------------------------- 2 比较符
def t06_comparator_max() -> None:
    text = "主动线净宽不超过 2400mm"
    meas = [o for o in derive(text) if o["kind"] == "measurable"]
    obs = {"comparator": [o.get("comparator") for o in meas],
           "target": [o.get("target") for o in meas],
           "source_text": [o.get("source_text") for o in meas]}
    fixed = bool(meas and meas[0].get("comparator") == "max")
    record("T06", "「不超过」被当成默认下限（min）", obs, fixed)


def t07_comparator_min_and_exact() -> None:
    lo = [o for o in derive("主动线净宽至少 2100mm") if o["kind"] == "measurable"]
    eq = [o for o in derive("把 F1 旋转到恰好 30 度") if o["kind"] == "measurable"]
    obs = {"min": [o.get("comparator") for o in lo],
           "exact": [o.get("comparator") for o in eq]}
    fixed = bool(lo and lo[0].get("comparator") == "min"
                 and eq and eq[0].get("comparator") == "exact")
    record("T07", "「至少」→min、「恰好」→exact 未区分", obs, fixed)


def t08_comparator_reverse_negative() -> None:
    """上限/下限被执行时方向必须相反：4000K 上限在 3500K 上通过，在下限上失败。"""
    out = {}
    for label, text in (("max", "L1 色温不超过 4000K"), ("min", "L1 色温不低于 4000K")):
        objs = derive(text)
        cand = copy.deepcopy(BASE)
        for f in cand["ceiling"]["fixtures"]:
            if f["id"] == "L1":
                f["kelvin"] = 3500
        rows = rt.recheck_objectives(objs, BASE, cand, site=SITE)
        out[label] = [(o.get("comparator"), r.get("objective_rechecked"))
                      for o, r in zip(objs, rows)]
    fixed = (out["max"] and out["max"][0][0] == "max" and out["max"][0][1] == "pass"
             and out["min"] and out["min"][0][0] == "min" and out["min"][0][1] == "fail")
    record("T08", "上限与下限在执行时方向相反（不是只改标签）", out, fixed)


def t09_multiple_values_one_clause() -> None:
    text = "F1 和 F3 分别转到 30 和 -30 度"
    objs = derive(text)
    meas = [o for o in objs if o["kind"] == "measurable"]
    pend = [o for o in objs if o["kind"] in ("aesthetic", "unparsed")]
    obs = {"measurable": [o.get("target") for o in meas],
           "pending_reason": [o.get("unparsed_reason") for o in pend],
           "pending_ids": [o.get("objective_id") for o in pend]}
    fixed = not meas and any(o.get("unparsed_reason") == "multiple_values_in_clause"
                             for o in pend)
    record("T09", "同一句两个同类数值只取第一个", obs, fixed)


# --------------------------------------------------------- 3 未解析/审美
def t10_numeric_plus_aesthetic() -> None:
    text = "主动线净宽至少 2100mm，同时整体更有设计感"
    objs = derive(text)
    kinds = [o["kind"] for o in objs]
    cand = copy.deepcopy(BASE)
    for c in cand["circulation"]:
        if c["id"] == "CA1":
            c["width_mm"] = 2100
    rows = rt.recheck_objectives(objs, BASE, cand, site=SITE)
    flags = [(r["kind"], r["objective_rechecked"], r["user_confirmed"]) for r in rows]
    obs = {"kinds": kinds, "states": flags}
    fixed = ("aesthetic" in kinds and "measurable" in kinds
             and any(k == "aesthetic" and s == "unknown" and u == "pending"
                     for k, s, u in flags))
    record("T10", "数值目标把「更有设计感」吞掉，审美不 pending", obs, fixed)


def t11_numeric_preserve_aesthetic() -> None:
    text = "主动线净宽扩大到 2100mm，保留东洽谈区不动，整体要更有呼吸感"
    objs = derive(text)
    kinds = sorted({o["kind"] for o in objs})
    pres = [o for o in objs if o["kind"] == "preserve"]
    obs = {"kinds": kinds,
           "preserve": [(o.get("binding_status"), o.get("object_ids")) for o in pres],
           "pending": [o.get("source_text") for o in objs
                       if o["kind"] in ("aesthetic", "unparsed")]}
    fixed = ({"measurable", "preserve", "aesthetic"} <= set(kinds)
             and pres and pres[0].get("object_ids") == ["ZA5"])
    record("T11", "数值+保留+审美三类诉求必须同时存在", obs, fixed)


# --------------------------------------------------------------- 4 矛盾
def t12_contradiction() -> None:
    if not hasattr(rt, "text_conflicts"):
        record("T12", "同基线矛盾要求（min 2400 + max 2100）没有显式冲突入口",
               {"capability": "absent"}, False)
        return
    fbs = [{"id": "f1", "feedback_id": "f1", "revision_no": 1, "kind": "boss_message",
            "text": "主动线净宽至少 2400mm", "locks": [], "objectives": []},
           {"id": "f2", "feedback_id": "f2", "revision_no": 2, "kind": "boss_message",
            "text": "主动线净宽不超过 2100mm", "locks": [], "objectives": []}]
    objs = rt.derive_objectives([dict(f) for f in fbs], None, plan=BASE)
    conflicts = rt.text_conflicts(objs)
    obs = {"conflict_count": len(conflicts),
           "detail": [c.get("detail") for c in conflicts],
           "decision_needed": [c.get("decision_needed") for c in conflicts]}
    fixed = bool(conflicts and conflicts[0]["type"] == "contradictory_text_targets")
    record("T12", "同基线矛盾要求被一起交给返工硬凑，没有显式冲突", obs, fixed)


def t13_non_conflicting_pair() -> None:
    fbs = [{"id": "f1", "feedback_id": "f1", "revision_no": 1, "kind": "boss_message",
            "text": "主动线净宽至少 2100mm", "locks": [], "objectives": []},
           {"id": "f2", "feedback_id": "f2", "revision_no": 2, "kind": "boss_message",
            "text": "主动线净宽至少 2400mm", "locks": [], "objectives": []}]
    if not hasattr(rt, "text_conflicts"):
        record("T13", "两条同向要求（都加严）不该被误报成矛盾",
               {"capability": "absent"}, False, verdict="not_observable")
        return
    fbs = [{"id": "f1", "feedback_id": "f1", "revision_no": 1, "kind": "boss_message",
            "text": "主动线净宽至少 2100mm", "locks": [], "objectives": []},
           {"id": "f2", "feedback_id": "f2", "revision_no": 2, "kind": "boss_message",
            "text": "主动线净宽至少 2400mm", "locks": [], "objectives": []}]
    objs = rt.derive_objectives([dict(f) for f in fbs], None, plan=BASE)
    conflicts = rt.text_conflicts(objs)
    obs = {"conflict_count": len(conflicts)}
    fixed = len(conflicts) == 0
    record("T13", "两条同向要求（都加严）不该被误报成矛盾", obs, fixed)


RUNNERS = [t01_named_object_not_widened, t01b_unrelated_furniture_change_rejected,
           t02_two_named_objects, t03_explicit_all_is_allowed,
           t04_missing_object_not_widened, t05_same_name_ambiguity,
           t06_comparator_max, t07_comparator_min_and_exact,
           t08_comparator_reverse_negative, t09_multiple_values_one_clause,
           t10_numeric_plus_aesthetic, t11_numeric_preserve_aesthetic,
           t12_contradiction, t13_non_conflicting_pair]


def main() -> int:
    phase = "before"
    out = None
    for i, a in enumerate(sys.argv):
        if a == "--phase" and i + 1 < len(sys.argv):
            phase = sys.argv[i + 1]
        if a == "--out" and i + 1 < len(sys.argv):
            out = Path(sys.argv[i + 1]).resolve()
    if not out:
        raise SystemExit("--out is required")
    for fn in RUNNERS:
        try:
            fn()
        except Exception:  # noqa: BLE001 - a crash is a result, never hidden
            CASES.append({"case": fn.__name__, "finding": "调用直接抛异常",
                          "observed": {"traceback": traceback.format_exc()[-800:]},
                          "verdict": "crashed"})
            print("crashed           " + fn.__name__, flush=True)
    counts: dict[str, int] = {}
    for c in CASES:
        counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "task_id": "W0 文字反馈收口（TEXT-01）",
        "schema_version": "rkd-text-feedback-cases.v1",
        "phase": phase,
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "git_head": __import__("subprocess").run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip(),
        "environment": {"python": sys.version.split()[0],
                        "model_calls": "none (pure functions)",
                        "fixture": "arc_first_batch_stub.valid_proposal('A')"},
        "cases": CASES,
        "summary": counts,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"phase": phase, "summary": counts, "out": str(out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
