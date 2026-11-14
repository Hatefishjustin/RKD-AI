"""TEXT-01 保守判定边界：否定 / 并列缺失对象 / 同子句残余诉求。

同一份脚本可在「整改前」代码树与「整改后」代码树各跑一次：
  python scripts/boundary_cases.py --phase before|after --out <path>

只调用真实 parse_text_requirements / derive_objectives / recheck_objectives 与
现有 valid_proposal 夹具，不调模型、不起服务。
"""
from __future__ import annotations

import copy
import json
import subprocess
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


def record(case: str, finding: str, observed: dict, fixed: bool) -> None:
    verdict = "fixed_signature" if fixed else "defect_reproduced"
    CASES.append({"case": case, "finding": finding, "observed": observed,
                  "verdict": verdict})
    print(f"{verdict:17s} {case} {json.dumps(observed, ensure_ascii=False)[:240]}",
          flush=True)


def base_plan() -> dict:
    rep = validation.validate_proposal(
        valid_proposal("A"), project={"id": "p", "site": SITE},
        option_id="A", revision=1, parent_revision=None)
    assert rep["ok"], rep["repair_feedback"][:500]
    return rep["plan"]


BASE = base_plan()


def derive(text: str, plan: dict | None = None) -> list[dict]:
    fb = [{"id": "fb_b", "feedback_id": "fb_b", "revision_no": 1,
           "kind": "boss_message", "text": text, "locks": [], "objectives": []}]
    return rt.derive_objectives(fb, None, plan=plan if plan is not None else BASE)


def parse(text: str, plan: dict | None = None) -> dict:
    return rt.parse_text_requirements(text, plan if plan is not None else BASE,
                                      prefix="FB1-")


def measurable(objs):
    return [o for o in objs if o.get("kind") == "measurable"]


def pending(objs):
    return [o for o in objs if o.get("kind") in ("aesthetic", "unparsed")]


# ------------------------------------------------------------------ 否定
def b01_negation_not_reversed() -> None:
    text = "不要把 F3 旋转到 -30 度"
    objs = derive(text)
    m = measurable(objs)
    p = pending(objs)
    obs = {"measurable": [{"target": x.get("target"),
                           "ids": x.get("object_ids"),
                           "computable": x.get("computable")} for x in m],
           "pending_reason": [x.get("unparsed_reason") for x in p],
           "pending_state": [(x.get("objective_rechecked"), x.get("user_confirmed"))
                             for x in rt.recheck_objectives(
                                 objs, BASE, copy.deepcopy(BASE), site=SITE)
                             if x.get("kind") in ("aesthetic", "unparsed")]}
    fixed = (not m and any(x.get("unparsed_reason") == "negated_requirement" for x in p)
             and all(s == "unknown" and u == "pending" for s, u in obs["pending_state"]))
    record("B01", "否定要求被反转成正向可执行目标", obs, fixed)


def b02_supported_comparator_is_not_negation() -> None:
    out = {}
    for key, text in (("max", "主动线净宽不超过 2400mm"),
                      ("min", "L1 色温不低于 4000K"),
                      ("negated", "不要把主动线净宽扩大到 2400mm")):
        m = measurable(derive(text))
        p = pending(derive(text))
        out[key] = {"comparators": [x.get("comparator") for x in m],
                    "targets": [x.get("target") for x in m],
                    "reasons": [x.get("unparsed_reason") for x in p]}
    fixed = (out["max"]["comparators"] == ["max"] and out["max"]["reasons"] == []
             and out["min"]["comparators"] == ["min"] and out["min"]["reasons"] == []
             and out["negated"]["comparators"] == []
             and "negated_requirement" in out["negated"]["reasons"])
    record("B02", "「不超过/不低于」是支持的比较符，不能被当成否定拒绝；真否定仍要拒绝",
           out, fixed)


# ------------------------------------------------------ 并列对象 / 完整引用
def b03_existing_plus_missing() -> None:
    text = "把 F1 和 F9 旋转到 -30 度"
    objs = derive(text)
    m = measurable(objs)
    cand = copy.deepcopy(BASE)
    for f in cand["furniture"]:
        if f["id"] == "F1":
            f["rot"] = -30
    rows = rt.recheck_objectives(objs, BASE, cand, site=SITE)
    obs = {"object_ids": [x.get("object_ids") for x in m],
           "all_refs": [x.get("all_object_references") for x in m],
           "binding": [(x.get("binding_status"), x.get("binding_match")) for x in m],
           "missing": [x.get("missing_object_ids") for x in m],
           "states": [(r.get("objective_rechecked"),
                       (r.get("evidence", {}).get("after", {}) or {})
                       .get("missing_object_ids")) for r in rows]}
    fixed = bool(m and m[0]["object_ids"] == ["F1", "F9"]
                 and m[0].get("binding_status") == "unresolved"
                 and m[0].get("all_object_references") == ["F1", "F9"]
                 and rows and rows[0]["objective_rechecked"] == "fail"
                 and rows[0]["evidence"]["after"]["missing_object_ids"] == ["F9"])
    record("B03", "存在+缺失对象并列时只留存在对象并宣布绑定成功", obs, fixed)


def b04_only_missing() -> None:
    text = "把 F9 旋转到 -30 度"
    m = measurable(derive(text))
    rows = rt.recheck_objectives(derive(text), BASE, copy.deepcopy(BASE), site=SITE)
    obs = {"object_ids": [x.get("object_ids") for x in m],
           "binding": [(x.get("binding_status"), x.get("binding_match")) for x in m],
           "state": [r.get("objective_rechecked") for r in rows]}
    fixed = bool(m and m[0]["object_ids"] == ["F9"] and rows
                 and rows[0]["objective_rechecked"] == "fail")
    record("B04", "仅缺失对象：按对象缺失阻断，不退化为整组", obs, fixed)


def b05_existing_plus_ambiguous_name() -> None:
    plan = copy.deepcopy(BASE)
    for f in plan["furniture"]:
        if f["id"] in ("F1", "F2"):
            f["name"] = "洽谈桌"
    text = "把 F1 和洽谈桌转到 30 度"
    m = measurable(derive(text, plan))
    obs = {"object_ids": [x.get("object_ids") for x in m],
           "binding": [(x.get("binding_status"), x.get("binding_match")) for x in m],
           "computable": [x.get("computable") for x in m],
           "candidates": [x.get("binding_candidates") for x in m]}
    fixed = bool(m and m[0].get("binding_status") == "unresolved"
                 and not m[0].get("computable")
                 and m[0].get("binding_match") == "ambiguous_object_names")
    record("B05", "存在对象 + 歧义名称并列：不能声称绑定成功", obs, fixed)


# ------------------------------------------------------------ 同子句残余
def b06_no_comma_compound() -> None:
    text = "把 F3 旋转到 -30 度并让整体更有设计感"
    objs = derive(text)
    m, p = measurable(objs), pending(objs)
    cand = copy.deepcopy(BASE)
    for f in cand["furniture"]:
        if f["id"] == "F3":
            f["rot"] = -30
    rows = rt.recheck_objectives(objs, BASE, cand, site=SITE)
    obs = {"measurable": [(x.get("target"), x.get("object_ids")) for x in m],
           "pending_reason": [x.get("unparsed_reason") for x in p],
           "residual": [x.get("residual_text") for x in p],
           "pending_states": [(r.get("kind"), r.get("objective_rechecked"),
                              r.get("user_confirmed")) for r in rows
                             if r.get("kind") in ("aesthetic", "unparsed")]}
    fixed = bool(len(m) == 1
                 and any(x.get("unparsed_reason") == "unparsed_remainder_in_clause"
                         for x in p)
                 and any("设计感" in str(x.get("residual_text")) for x in p)
                 and all(s == "unknown" and u == "pending"
                         for _k, s, u in obs["pending_states"]))
    record("B06", "无逗号复合句中，数值目标吞掉同子句剩余诉求", obs, fixed)


def b07_generic_residual_not_a_special_case() -> None:
    text = "把 F3 旋转到 -30 度并复核北侧收口"
    p = pending(derive(text))
    obs = {"pending_reason": [x.get("unparsed_reason") for x in p],
           "residual": [x.get("residual_text") for x in p],
           "kinds": [x.get("kind") for x in p]}
    fixed = any(x.get("unparsed_reason") == "unparsed_remainder_in_clause"
                and "收口" in str(x.get("residual_text")) for x in p)
    record("B07", "残余检测必须通用（换一个非审美词也应留痕），不是「设计感」补丁",
           obs, fixed)


def b08_comma_compound_still_tracked() -> None:
    text = "把 F3 旋转到 -30 度，整体更有设计感"
    objs = derive(text)
    obs = {"kinds": sorted({x.get("kind") for x in objs}),
           "measurable": [(x.get("target"), x.get("object_ids")) for x in measurable(objs)]}
    fixed = ("aesthetic" in obs["kinds"] and len(measurable(objs)) == 1)
    record("B08", "有标点时审美仍 pending（回归护栏，不被新残余逻辑改坏）", obs, fixed)


def b09_keep_phrases_not_negation() -> None:
    text = "把 F3 旋转到 -30 度，其他家具不动"
    objs = derive(text)
    obs = {"measurable": [(x.get("target"), x.get("object_ids")) for x in measurable(objs)],
           "preserve": [(x.get("binding_status"), x.get("object_ids"))
                        for x in objs if x.get("kind") == "preserve"],
           "pending_reason": [x.get("unparsed_reason") for x in pending(objs)]}
    preserves = [x for x in objs if x.get("kind") == "preserve"]
    fixed = bool(len(measurable(objs)) == 1
                 and "negated_requirement" not in obs["pending_reason"]
                 and any(x.get("object_ids") == ["F1", "F2"] for x in preserves))
    record("B09", "保留表达（不动/保留）里的「不」不能被误判成否定", obs, fixed)


def b10_parsed_and_unparsed_spans_recorded() -> None:
    text = "把 F3 旋转到 -30 度并让整体更有设计感"
    result = parse(text)
    m = result["measurable"]
    obs = {"explained_text": [x.get("explained_text") for x in m],
           "source_text": [x.get("source_text") for x in m],
           "residual": [x.get("residual_text") for x in result["pending"]]}
    fixed = bool(m and m[0].get("explained_text")
                 and m[0].get("source_text") == text
                 and result["pending"])
    record("B10", "已解析片段 / 原句 / 残余片段都要留在证据里", obs, fixed)


RUNNERS = [b01_negation_not_reversed, b02_supported_comparator_is_not_negation,
           b03_existing_plus_missing, b04_only_missing, b05_existing_plus_ambiguous_name,
           b06_no_comma_compound, b07_generic_residual_not_a_special_case,
           b08_comma_compound_still_tracked, b09_keep_phrases_not_negation,
           b10_parsed_and_unparsed_spans_recorded]


def main() -> int:
    phase, out = "after", None
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
        except Exception:  # noqa: BLE001
            CASES.append({"case": fn.__name__, "finding": "调用直接抛异常",
                          "observed": {"traceback": traceback.format_exc()[-800:]},
                          "verdict": "crashed"})
            print("crashed           " + fn.__name__, flush=True)
    counts: dict[str, int] = {}
    for c in CASES:
        counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "task_id": "W0 文字反馈保守判定（TEXT-01 边界）",
        "schema_version": "rkd-boundary-cases.v1",
        "phase": phase,
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "git_head": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                   capture_output=True, text=True).stdout.strip(),
        "environment": {"python": sys.version.split()[0],
                        "model_calls": "none (pure functions)",
                        "fixture": "arc_first_batch_stub.valid_proposal('A')"},
        "cases": CASES, "summary": counts,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"phase": phase, "summary": counts, "out": str(out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
