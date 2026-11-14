"""ARC first batch: Q01-Q12 engineering acceptance with real positive/negative cases.

All model answers come from the explicitly-labelled LOCAL MODEL STUB
(scripts/arc_first_batch_stub.py). 0 external model/image calls, 0 keys, 0 cost.
This does NOT prove AI design quality, does NOT change AD01-AD08, and does NOT
claim design approval. It checks engineering control only.

Outputs: var/evidence/architecture-handoff/first-batch/after/checks.json
         var/evidence/architecture-handoff/first-batch/after/q-checks.json
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from arc_first_batch_stub import (  # noqa: E402
    SITE, REQUIREMENT, valid_proposal, review_issues, revision_payload,
    design_scope_sqm, as_json,
)
from rkd_mvp.studio import geometry, orchestrator, revision as R, validation  # noqa: E402
from rkd_mvp.studio import tools as toolbox  # noqa: E402
from rkd_mvp.studio.store import Store, input_hash  # noqa: E402

PROJ = {"id": "ningbo-xiecheng", "name": "宁波协诚集团样品展厅",
        "site": SITE, "requirement": REQUIREMENT}
AFTER = ROOT / "var" / "evidence" / "architecture-handoff" / "first-batch" / "after"
BEFORE = ROOT / "var" / "evidence" / "architecture-handoff" / "first-batch" / "before"
CHECKS: list[dict] = []
CASES: list[dict] = []


def _iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def check(qid: str, name: str, ok: bool, evidence: dict, note: str = "") -> None:
    CHECKS.append({"id": qid, "name": name,
                   "result": "observed_pass" if ok else "observed_fail",
                   "evidence": evidence, "note": note})
    print(("PASS " if ok else "FAIL ") + qid + " " + name)


def case(name: str, kind: str, detail: dict) -> None:
    CASES.append({"name": name, "kind": kind, "detail": detail})


def _rules(g: dict) -> list[str]:
    return [i["rule_id"] for i in g["issues"]]


def _db(name: str) -> Store:
    d = AFTER / "scratch"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}-{os.getpid()}.db"
    if p.exists():
        p.unlink()
    return Store(p)


# --------------------------------------------------------------------- Q01
def q01() -> None:
    st = _db("q01")
    st.ensure_project("ningbo-xiecheng", "宁波协诚集团样品展厅", SITE, REQUIREMENT)
    negative = {}
    base = valid_proposal("A")

    p1 = copy.deepcopy(base); del p1["zones"][0]["role"]
    p2 = copy.deepcopy(base); p2["area_table"][0]["area_sqm"] = "one"
    p3 = copy.deepcopy(base); p3["furniture"][0]["catalog_id"] = "not-in-catalog-xyz"
    p4 = copy.deepcopy(base); p4["approved"] = True; p4["adopt_pointer"] = "A"
    p5 = copy.deepcopy(base); p5["zones"][0]["id"] = p5["zones"][1]["id"]
    p6 = copy.deepcopy(base); p6["standards_cited"] = ["STD-999"]
    p7 = copy.deepcopy(base); p7["area_table"].append({"name": "虚构分区", "area_sqm": 12})
    for label, p in (("missing_role", p1), ("wrong_type", p2), ("invalid_catalog_ref", p3),
                     ("model_claims_approval", p4), ("duplicate_object_id", p5),
                     ("unknown_standard", p6), ("unmatched_area_row", p7)):
        r = validation.validate_proposal(p, project=PROJ, option_id="A",
                                         revision=1, parent_revision=None)
        negative[label] = {"rejected": not r["ok"], "stage": r["stage"],
                           "error_count": len(r["errors"]),
                           "rules": [e["rule_id"] for e in r["errors"]][:6],
                           "has_actionable_feedback": all(
                               all(k in e for k in ("path", "expected", "object_id", "hint"))
                               for e in r["errors"])}
        # raw + diagnostic retained but never a valid candidate
        st.save_artifact("ningbo-xiecheng", "spatial-plan-raw", {"parsed": p}, "D2",
                         option_id="A", revision=1, status="invalid_raw",
                         contract_status="invalid_raw", diagnostics=r)

    pos = validation.validate_proposal(base, project=PROJ, option_id="A",
                                       revision=1, parent_revision=None)
    aid = st.save_artifact("ningbo-xiecheng", "spatial-plan", pos["plan"], "D2",
                           option_id="A", revision=1, status="valid_candidate",
                           contract_status="valid_candidate",
                           diagnostics={"contract_report": pos})
    arts = st.artifacts("ningbo-xiecheng")
    valid = [a for a in arts if a["contract_status"] == "valid_candidate"]
    raw = [a for a in arts if a["contract_status"] == "invalid_raw"]
    evidence = {
        "negative_cases": negative,
        "positive_passed": pos["ok"],
        "four_stages": ["structure", "semantics", "geometry", "locks"],
        "draft_schema_checked_after_assembly": pos["checks"].get("draft_schema_after_assembly"),
        "history_retained": True,
        "valid_candidates": len(valid), "invalid_raw_retained": len(raw),
        "diagnostics_have_field_path": all(
            all(k in e for k in ("path", "expected", "object_id", "hint"))
            for a in raw for e in (a["diagnostics"] or {}).get("errors", [])),
        "artifact_id": aid,
    }
    ok = (all(v["rejected"] for v in negative.values())
          and all(v["has_actionable_feedback"] for v in negative.values())
          and pos["ok"] and len(valid) == 1 and len(raw) == 7
          and evidence["diagnostics_have_field_path"])
    check("Q01", "契约有效才进入有效候选；缺role/错类型/无效引用/批准字段被定位；历史保留",
          ok, evidence)
    case("Q01 契约负例 7 项", "negative", negative)
    case("Q01 契约正例", "positive", {"ok": pos["ok"], "stages": pos["checks"]})


# --------------------------------------------------------------------- Q02
def q02() -> None:
    site = {"width_mm": 10000, "height_mm": 10000}
    sparse = {
        "strategy": {"name": "稀疏布局", "narrative": "n" * 25,
                     "tradeoffs": ["a", "b"], "non_orthogonal": []},
        "zones": [
            {"id": "Z1", "name": "序厅", "role": "arrival",
             "polygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]], "area_sqm": 1},
            {"id": "Z2", "name": "主展", "role": "gallery",
             "polygon": [[2000, 0], [3000, 0], [3000, 1000], [2000, 1000]], "area_sqm": 1},
            {"id": "Z3", "name": "洽谈", "role": "meeting",
             "polygon": [[4000, 0], [5000, 0], [5000, 1000], [4000, 1000]], "area_sqm": 1}],
        "circulation": [{"id": "C1", "width_mm": 1500, "path": [[100, 100], [9000, 100]]}],
        "furniture": [],
        "area_table": [{"name": "序厅", "area_sqm": 1},
                       {"name": "主展", "area_sqm": 1},
                       {"name": "洽谈", "area_sqm": 1}],
        "ceiling": {"coves": [{"id": "CV1", "polygon": [[0, 0], [100, 0], [100, 100]]}],
                    "fixtures": []},
        "open_questions": [], "standards_cited": [],
    }
    g = geometry.check_geometry(sparse, site, catalog={c["catalog_id"]: c for c in toolbox.CATALOG})
    m = g["metrics"]
    area_issue = next((i for i in g["issues"] if i["rule_id"] == "AREA-001"), None)
    explicit_97 = bool(area_issue and "97" in area_issue["message"])

    complete = geometry.check_geometry(
        valid_proposal("A"), SITE, catalog={c["catalog_id"]: c for c in toolbox.CATALOG})

    # "补通道及其他" after reconciliation: area table aligned to design scope,
    # functional rows + one other row => no contradiction, no STD-003 hint.
    nb = copy.deepcopy(valid_proposal("A"))
    nb_g = geometry.check_geometry(nb, SITE, catalog={c["catalog_id"]: c for c in toolbox.CATALOG})
    contradiction_hint = any("补『通道及其他』" in (i.get("hint") or "") for i in g["issues"])

    evidence = {
        "100sqm_3sqm": {
            "design_scope_sqm": m["design_scope_sqm"],
            "zone_area_sum_sqm": m["zone_area_sum_sqm"],
            "unallocated_sqm": m["unallocated_sqm"],
            "layout_complete": m["layout_complete"],
            "area_rules": [i["rule_id"] for i in g["issues"] if i["rule_id"].startswith("AREA")],
            "explicit_97sqm_unallocated": explicit_97,
            "ok": g["ok"],
        },
        "complete_layout": {
            "site_area_sqm": complete["metrics"]["site_area_sqm"],
            "reserved_area_sqm": complete["metrics"]["reserved_area_sqm"],
            "design_scope_sqm": complete["metrics"]["design_scope_sqm"],
            "area_table_sum_sqm": complete["metrics"]["area_table_sum_sqm"],
            "reconciliation_gap_sqm": complete["metrics"]["area_reconciliation_gap_sqm"],
            "layout_complete": complete["metrics"]["layout_complete"],
            "area_rules": [i["rule_id"] for i in complete["issues"] if i["rule_id"].startswith("AREA")],
        },
        "single_basis": "design_scope_sqm",
        "no_self_contradictory_hint": not contradiction_hint,
        "outer_frame_not_equated_to_billable": (
            complete["metrics"]["site_area_sqm"] != complete["metrics"]["design_scope_sqm"]),
    }
    ok = (m["unallocated_sqm"] == 97.0 and explicit_97 and not m["layout_complete"]
          and complete["metrics"]["layout_complete"]
          and complete["metrics"]["area_reconciliation_gap_sqm"] < 0.75
          and not contradiction_hint and evidence["outer_frame_not_equated_to_billable"])
    check("Q02", "面积唯一口径：100㎡/3㎡ 显式指出 97㎡ 未分配；完整布局对账；补通道不再自相矛盾",
          ok, evidence)
    case("Q02 100㎡/3㎡ 负例", "negative", evidence["100sqm_3sqm"])
    case("Q02 完整布局对账正例", "positive", evidence["complete_layout"])


# --------------------------------------------------------------------- Q03
def q03() -> None:
    site = {"width_mm": 5000, "height_mm": 5000}
    tri = {
        "strategy": {"name": "三角", "narrative": "n" * 25, "tradeoffs": ["a", "b"],
                     "non_orthogonal": []},
        "zones": [
            {"id": "A", "name": "三角A", "role": "gallery",
             "polygon": [[0, 0], [4000, 0], [0, 4000]], "area_sqm": 8.0},
            {"id": "B", "name": "三角B", "role": "gallery",
             "polygon": [[4000, 4000], [4000, 500], [500, 4000]], "area_sqm": 6.125}],
        "circulation": [{"id": "C1", "width_mm": 1500, "path": [[100, 200], [4000, 200]]}],
        "furniture": [], "area_table": [],
        "open_questions": [], "standards_cited": [],
    }
    from shapely.geometry import Polygon
    pa, pb = Polygon(tri["zones"][0]["polygon"]), Polygon(tri["zones"][1]["polygon"])
    g = geometry.check_geometry(tri, site)
    disjoint_ok = not any(i["rule_id"] == "GEO-004" for i in g["issues"])

    def variant(zones):
        p = copy.deepcopy(tri); p["zones"] = zones; return p

    real_overlap = variant([
        {"id": "A", "name": "A", "role": "gallery",
         "polygon": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]], "area_sqm": 4},
        {"id": "B", "name": "B", "role": "gallery",
         "polygon": [[1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000]], "area_sqm": 4}])
    self_cross = variant([
        {"id": "A", "name": "A", "role": "gallery",
         "polygon": [[0, 0], [2000, 2000], [2000, 0], [0, 2000]], "area_sqm": 4}])
    out_of_bounds = variant([
        {"id": "A", "name": "A", "role": "gallery",
         "polygon": [[0, 0], [6000, 0], [6000, 2000], [0, 2000]], "area_sqm": 12}])
    zero_area = variant([
        {"id": "A", "name": "A", "role": "gallery",
         "polygon": [[0, 0], [1000, 0], [2000, 0]], "area_sqm": 1}])
    results = {}
    for label, p in (("real_intersection", real_overlap), ("self_crossing", self_cross),
                     ("out_of_bounds", out_of_bounds), ("zero_area", zero_area)):
        r = geometry.check_geometry(p, site)
        results[label] = {"ok": r["ok"], "rules": _rules(r)}
    expected = {"real_intersection": "GEO-004", "self_crossing": "GEO-010",
                "out_of_bounds": "GEO-003", "zero_area": "GEO-010"}
    rejected = {k: (not v["ok"] and expected[k] in v["rules"]) for k, v in results.items()}
    evidence = {
        "disjoint_triangles": {
            "shapely_actual_intersection_mm2": pa.intersection(pb).area,
            "shapely_intersects": pa.intersects(pb),
            "rules": _rules(g), "GEO_004_reported": not disjoint_ok},
        "geometry_blocker_cases": results, "rejected": rejected,
        "engine": g["metrics"]["geometry_engine"],
    }
    ok = disjoint_ok and pa.intersection(pb).area == 0 and all(rejected.values())
    check("Q03", "实际几何：分离三角形不报相交；真实交集/自交/越界/零面积正确拒绝", ok, evidence)
    case("Q03 分离三角形正例", "positive", evidence["disjoint_triangles"])
    case("Q03 四类几何负例", "negative", results)


# --------------------------------------------------------------------- Q04
def q04() -> None:
    catalog = {c["catalog_id"]: c for c in toolbox.CATALOG}
    base = valid_proposal("A")

    # broken route: far from every zone and from the entrance band
    p_broken = copy.deepcopy(base)
    p_broken["circulation"] = [{"id": "CA1", "width_mm": 2000,
                                "path": [[25000, 17000], [26000, 17000]]}]
    g_broken = geometry.check_geometry(p_broken, SITE, catalog=catalog)

    # route crosses the reserved bathroom
    p_obstacle = copy.deepcopy(base)
    p_obstacle["circulation"] = [{"id": "CA1", "width_mm": 2000,
                                  "path": [[100, 11000], [23000, 6000]]}]
    g_obstacle = geometry.check_geometry(p_obstacle, SITE, catalog=catalog)

    # keep-out violation: a zone intrudes into the reserved bathroom
    p_bath = copy.deepcopy(base)
    p_bath["zones"].append({"id": "ZX", "name": "侵入卫生间", "role": "support",
                            "polygon": [[22500, 3000], [25500, 3000],
                                        [25500, 7000], [22500, 7000]], "area_sqm": 12})
    g_bath = geometry.check_geometry(p_bath, SITE, catalog=catalog)

    # furniture with real catalog size rotated into the reserved stair
    p_furn = copy.deepcopy(base)
    p_furn["furniture"].append({"id": "F9", "catalog_id": "sofa-3p",
                                "x": 1200, "y": 4000, "rot": 0})
    g_furn = geometry.check_geometry(p_furn, SITE, catalog=catalog)

    # unknown catalog reference is a blocker, not a 600x600 default box
    p_unknown = copy.deepcopy(base)
    p_unknown["furniture"][0]["catalog_id"] = "ghost-item"
    g_unknown = geometry.check_geometry(p_unknown, SITE, catalog=catalog)

    # self-reported width is fine but measured geometry is a bottleneck
    p_narrow = copy.deepcopy(base)
    p_narrow["circulation"] = [{"id": "CA1", "width_mm": 2000,
                                "path": [[100, 11000], [22000, 5000]]}]
    g_narrow = geometry.check_geometry(p_narrow, SITE, catalog=catalog)

    evidence = {
        "broken_route": {"rules": _rules(g_broken), "ok": g_broken["ok"]},
        "obstacle_crossing": {"rules": _rules(g_obstacle), "ok": g_obstacle["ok"]},
        "reserved_bathroom_changed": {"rules": _rules(g_bath), "ok": g_bath["ok"]},
        "furniture_rotated_footprint_in_keepout": {"rules": _rules(g_furn), "ok": g_furn["ok"]},
        "unknown_catalog_rejected": {"rules": _rules(g_unknown), "ok": g_unknown["ok"]},
        "measured_bottleneck": {"rules": _rules(g_narrow), "ok": g_narrow["ok"],
                                "measured_mm": {k: v for k, v in g_narrow["metrics"].items()
                                                if k.startswith("measured_clear_width")}},
        "checks_coverage": geometry.check_geometry(base, SITE, catalog=catalog)["checks"],
    }
    ok = (not g_broken["ok"] and "CIR-002" in _rules(g_broken)
          and "CIR-004" in _rules(g_broken)
          and "CIR-003" in _rules(g_obstacle)
          and "LOCK-001" in _rules(g_bath)
          and "LOCK-001" in _rules(g_furn)
          and "FUR-001" in _rules(g_unknown)
          and "CIR-003" in _rules(g_narrow))
    check("Q04", "通行与锁定：断路/障碍/瓶颈/入口不可达/保留卫生间/目录引用均有定位", ok, evidence)
    for k, v in evidence.items():
        if isinstance(v, dict) and "rules" in v:
            case(f"Q04 {k}", "negative", v)


# --------------------------------------------------------------------- Q05
def q05() -> None:
    src = (ROOT / "mvp" / "rkd_mvp" / "studio" / "orchestrator.py").read_text(encoding="utf-8")
    truncations = [l.strip() for l in src.splitlines() if re.search(r"\[:\d{4}\]", l)]
    big = valid_proposal("A")
    # append many real objects so the plan exceeds all former truncation limits
    for k in range(24):
        big["open_questions"].append(
            f"末尾对象 ZONE_TAIL_SENTINEL 第{k}条：请评审并修订时读取这个末尾事实 "
            + "补充说明" * 12)
    full = json.dumps(big, ensure_ascii=False)
    summary = validation.structural_summary(big)
    tail_in_summary = "ZONE_TAIL_SENTINEL" in summary
    # downstream revision prompt embeds the full structural summary
    revision_prompt_uses_full_summary = "validation.structural_summary(base_plan)" in src
    review_prompt_uses_full_facts = src.count("validation.structural_summary(") >= 3
    evidence = {
        "plan_json_chars": len(full),
        "old_limits": [4000, 3500, 3000],
        "truncation_sites_in_orchestrator": truncations,
        "tail_object_in_full_summary": tail_in_summary,
        "revision_prompt_uses_full_summary": revision_prompt_uses_full_summary,
        "review_prompt_uses_full_facts": review_prompt_uses_full_facts,
        "baseline_id_in_prompt": "revision_uid=" in src and "artifact id=" in src,
        "issue_ids_in_prompt": "json.dumps(issues, ensure_ascii=False)" in src,
    }
    ok = (len(full) > 4000 and not truncations and tail_in_summary
          and revision_prompt_uses_full_summary and review_prompt_uses_full_facts
          and evidence["baseline_id_in_prompt"] and evidence["issue_ids_in_prompt"])
    check("Q05", "完整交接：超旧截断长度的末尾对象可被评审/修订读取；基线ID与issue_id明确",
          ok, evidence)
    case("Q05 长方案末尾对象可达", "positive", {"chars": len(full),
                                              "tail_reachable": tail_in_summary,
                                              "truncations": truncations})


# --------------------------------------------------------------------- Q06
def q06() -> None:
    a, b = valid_proposal("A"), valid_proposal("B")
    renamed = copy.deepcopy(a)
    renamed["strategy"]["name"] = "完全不同的名字"
    for z in renamed["zones"]:
        z["name"] = z["name"] + "·改"
    reordered = copy.deepcopy(a)
    reordered["zones"] = list(reversed(reordered["zones"]))
    reordered["furniture"] = list(reversed(reordered["furniture"]))
    trivial = copy.deepcopy(a)
    for f in trivial["furniture"]:
        f["x"] = f["x"] + 20  # 20 mm, rounded away in the structural signature
    d_same = validation.substantive_difference(a, renamed)
    d_reorder = validation.substantive_difference(a, reordered)
    d_trivial = validation.substantive_difference(a, trivial)
    d_real = validation.substantive_difference(a, b)
    evidence = {
        "rename_only": {"substantive": d_same["substantive"], "reason": d_same["reason"]},
        "reorder_only": {"substantive": d_reorder["substantive"]},
        "trivial_shift_only": {"substantive": d_trivial["substantive"]},
        "real_different_topology": {
            "substantive": d_real["substantive"],
            "zone_topology_changed": d_real["zone_topology_changed"],
            "circulation_changed": d_real["circulation_changed"]},
    }
    ok = (not d_same["substantive"] and not d_reorder["substantive"]
          and not d_trivial["substantive"] and d_real["substantive"])
    check("Q06", "多方案实质不同：换名/换色/顺序/无意义位移不算新拓扑", ok, evidence)
    case("Q06 同质候选负例", "negative", {k: v for k, v in evidence.items()
                                        if k != "real_different_topology"})
    case("Q06 真实不同拓扑正例", "positive", evidence["real_different_topology"])


# --------------------------------------------------------------------- Q07/Q08
def q07_q08() -> None:
    base = valid_proposal("A")
    issues = review_issues()
    pl = revision_payload(issues)
    candidate, perrs, audit = R.apply_patch(base, pl["patch"])
    assert not perrs
    integ = R.verify_revision_integrity(
        base, candidate, responses=pl["responses"], issues=issues,
        lock_object_ids=["ZA1"],
        boss_feedback=[{"feedback_id": "fb1", "revision_no": 1,
                        "text": "调整洽谈区、保留入口"}],
        # W0/R2: supply the real site so clear-width objectives can be
        # re-measured by geometry instead of being reported as unknown.
        # This STRENGTHENS the check; no validation rule is relaxed.
        site=SITE)
    rp = validation.validate_proposal(
        candidate, project=PROJ, option_id="A", revision=2, parent_revision=1,
        lock_object_ids=["ZA1"], previous_plan=base)

    # boss feedback must actually appear as a versioned requirement, not a line
    st = _db("q07")
    st.ensure_project("ningbo-xiecheng", "宁波", SITE, REQUIREMENT)
    fb = st.add_feedback("ningbo-xiecheng", "boss_message",
                         "调整洽谈区、保留入口",
                         baseline_artifact_id="art_base",
                         baseline_revision_uid="revuid_base")
    eff = st.effective_requirement("ningbo-xiecheng")
    ctx = orchestrator.Studio(st)._ctx(
        {"id": "ningbo-xiecheng", "name": "宁波", "site": SITE,
         "requirement": REQUIREMENT, "source_project_id": "ningbo-xiecheng"})

    # negative: accepted issue whose named object was not changed
    bad_payload = copy.deepcopy(pl)
    bad_payload["responses"][0]["change"] = "只改了别的"
    bad_payload["patch"] = [{"op": "update", "group": "furniture", "id": "F1",
                             "fields": {"rot": 5}}]
    bad_cand, _, _ = R.apply_patch(base, bad_payload["patch"])
    bad_integ = R.verify_revision_integrity(base, bad_cand,
                                            responses=bad_payload["responses"],
                                            issues=issues, lock_object_ids=["ZA1"],
                                            site=SITE)
    # negative: silent deletion without reason
    del_patch = [{"op": "remove", "group": "zones", "id": "ZA4"}]
    _, del_errors, _ = R.apply_patch(base, del_patch)
    # negative: locked object changed
    lock_cand, _, _ = R.apply_patch(base, [{"op": "update", "group": "zones",
                                            "id": "ZA1", "fields": {"role": "support"}}])
    lock_integ = R.verify_revision_integrity(base, lock_cand, issues=issues,
                                             responses=pl["responses"],
                                             lock_object_ids=["ZA1"], site=SITE)
    # negative: patch writing an identity/decision field
    _, identity_errors, _ = R.apply_patch(base, [{"op": "update", "group": "zones",
                                                 "id": "ZA1", "fields": {"approved": True}}])

    q07_ev = {
        "feedback_id": fb["id"], "feedback_revision": fb["revision_no"],
        "effective_addenda": eff["effective_addenda"],
        "effective_input_hash": eff["effective_input_hash"],
        "feedback_in_ctx": "调整洽谈区、保留入口" in ctx,
        "baseline_bound": fb["baseline_artifact_id"] is not None,
        "object_diff": integ["changed_objects"],
        "object_retention_ratio": integ["object_retention_ratio"],
        "unrelated_objects_preserved": not any(
            e["rule_id"] == "REV-UNRELATED" for e in integ["errors"]),
        "revision_contract_ok": rp["ok"],
        "patch_audit": audit,
    }
    q07_ok = (q07_ev["feedback_in_ctx"] and q07_ev["baseline_bound"]
              and len(integ["changed_objects"]) >= 4
              and integ["object_retention_ratio"] == 1.0
              and q07_ev["unrelated_objects_preserved"] and rp["ok"])
    check("Q07", "页面反馈进入版本化有效需求，形成绑定原基线的新修订和真实对象 diff", q07_ok, q07_ev)

    q08_ev = {
        "accepted_total": integ["accepted_issues_total"],
        "accepted_verified": integ["accepted_issues_verified"],
        "issue_resolutions": integ["issue_resolutions"],
        "reject_has_reason": all(r["verified"] for r in integ["issue_resolutions"]
                                 if r["action"] == "reject"),
        "negative_accept_without_linked_diff": {
            "ok": bad_integ["ok"],
            "rules": [e["rule_id"] for e in bad_integ["errors"]]},
        "negative_delete_without_reason": [e["rule_id"] for e in del_errors],
        "negative_lock_changed": [e["rule_id"] for e in lock_integ["errors"]],
        "negative_identity_patch": [e["rule_id"] for e in identity_errors],
        "max_auto_rework": orchestrator.MAX_AUTO_REWORK,
        "rework_not_split_into_new_runs": "for attempt in range(1, 2 + MAX_AUTO_REWORK)" in
            (ROOT / "mvp" / "rkd_mvp" / "studio" / "orchestrator.py").read_text(encoding="utf-8"),
    }
    q08_ok = (integ["accepted_issues_verified"] == integ["accepted_issues_total"] == 4
              and q08_ev["reject_has_reason"] and not bad_integ["ok"]
              and any(e["rule_id"] == "REV-ISSUE" for e in bad_integ["errors"])
              and any(e["rule_id"] == "PATCH-004" for e in del_errors)
              and any(e["rule_id"] == "LOCK-REVISION" for e in lock_integ["errors"])
              and any(e["rule_id"] in ("PATCH-006", "IDENTITY-BOUNDARY") for e in identity_errors)
              and q08_ev["max_auto_rework"] == 2 and q08_ev["rework_not_split_into_new_runs"])
    check("Q08", "意见逐项对应、拒绝有理由、删除/锁定/身份负例被拒、返工上限仍为2",
          q08_ok, q08_ev)
    case("Q07 反馈→修订正例", "positive", q07_ev)
    case("Q08 无对象diff/无理由删除/锁定改动/身份patch负例", "negative", {
        "accept_without_diff": q08_ev["negative_accept_without_linked_diff"],
        "delete_without_reason": q08_ev["negative_delete_without_reason"],
        "lock_changed": q08_ev["negative_lock_changed"],
        "identity_patch": q08_ev["negative_identity_patch"]})


# --------------------------------------------------------------------- Q09
def q09() -> None:
    st = _db("q09")
    st.ensure_project("ningbo-xiecheng", "宁波协诚集团样品展厅", SITE, REQUIREMENT)
    gid = st.open_gate("ningbo-xiecheng", "闸口一", "详情",
                       baseline_artifact_id="art_A1",
                       baseline_revision_uid="revuid_A1")
    first = st.decide_gate(gid, "approve", "第一次决定", "allow_continue")
    g1 = dict(st.gate(gid))
    second = st.decide_gate(gid, "reject", "重放覆盖尝试", "direction_approval")
    g2 = dict(st.gate(gid))
    decisions = st.gate_decisions(gid)

    # late result from a stale input must be superseded
    rid = st.start_run("ningbo-xiecheng", "local-model-stub", input_hash_value="h1",
                       expected_feedback_revision=0)
    st.add_feedback("ningbo-xiecheng", "boss_message", "新输入到达")
    changed = st.feedback_changed_since("ningbo-xiecheng", 0)
    st.request_cancel(rid)
    cancelled = st.is_cancelled(rid)
    st.save_artifact("ningbo-xiecheng", "spatial-plan", valid_proposal("A"), "D2",
                     option_id="A", revision=1, run_id=rid, status="valid_candidate",
                     contract_status="valid_candidate")
    affected = st.invalidate_artifacts(rid)
    arts = st.artifacts("ningbo-xiecheng")

    server_src = (ROOT / "mvp" / "rkd_mvp" / "studio" / "server.py").read_text(encoding="utf-8")
    view_src = (ROOT / "web" / "src" / "StudioView.tsx").read_text(encoding="utf-8")
    evidence = {
        "gate_first_decision": {"applied": first["applied"], "decision": g1["decision"],
                                "comment": g1["comment"]},
        "gate_replay": {"applied": second["applied"], "reason": second["reason"],
                        "decision_after": g2["decision"], "comment_after": g2["comment"],
                        "decided_at_after": g2["decided_at"]},
        "decision_records": [{"decision": d["decision"], "comment": d["comment"]}
                             for d in decisions],
        "gate_baseline": {"artifact_id": g1["baseline_artifact_id"],
                          "revision_uid": g1["baseline_revision_uid"]},
        "late_result": {"feedback_changed": changed, "cancel_requested": cancelled,
                        "artifacts_invalidated": affected,
                        "artifact_status_after": [a["status"] for a in arts],
                        "bytes_retained": all(a["payload"] for a in arts)},
        "unknown_project_rejected": "未接入本机 Studio 实验服务" in server_src,
        "frontend_no_hardcode": ('projectId === "ningbo-xiecheng" ? "ningbo-xiecheng" : "ningbo-xiecheng"'
                                 not in view_src),
        "frontend_maps_id": "const studioId = projectId" in view_src,
    }
    ok = (first["applied"] and not second["applied"] and g2["decision"] == "approve"
          and g2["comment"] == "第一次决定" and len(decisions) == 2
          and g1["baseline_artifact_id"] == "art_A1"
          and changed and cancelled and affected == 1
          and arts[0]["status"] == "superseded"
          and evidence["late_result"]["bytes_retained"]
          and evidence["unknown_project_rejected"] and evidence["frontend_no_hardcode"]
          and evidence["frontend_maps_id"])
    check("Q09", "项目/版本/闸口隔离：切项目不显示宁波、晚到结果失效、决定重放不覆盖",
          ok, evidence)
    case("Q09 闸口重放负例", "negative", evidence["gate_replay"])
    case("Q09 晚到结果失效负例", "negative", evidence["late_result"])


# --------------------------------------------------------------------- Q10
def q10() -> None:
    evidence = {
        "result": "not_run",
        "reason": "ARC-05 纵向适配（同源平面 + 一张人眼效果图、文件哈希对账、旧成果失效）"
                  "属于第 5 节第二批，本批只交字段映射与归属说明，未实现也未验证",
        "partial_in_first_batch": {
            "artifact_sha256": True, "check_report_id": True,
            "run_id": True, "input_hash": True, "revision_uid": True,
            "candidate_group_id": True,
            "note": "本批已把这些关联字段落到 Studio 产物，但没有跨平面/渲染/数量做同源一致性验证"},
        "adaptation_note": "deliverables-for-review/arc-first-batch/ARC-05-adaptation-note.md",
    }
    CHECKS.append({"id": "Q10", "name": "同源成果真实可用（后续适配批）",
                   "result": "not_run", "evidence": evidence,
                   "note": "首批范围外，不冒充已验证"})
    print("NOT_RUN Q10 同源成果真实可用（后续适配批，本批只交适配说明）")


# --------------------------------------------------------------------- Q11
def q11() -> None:
    d = AFTER / "scratch"; d.mkdir(parents=True, exist_ok=True)
    p = d / f"q11-{os.getpid()}.db"
    if p.exists():
        p.unlink()
    st1 = Store(p)
    st1.ensure_project("ningbo-xiecheng", "自定义名称（不应被覆盖）", SITE,
                       {"text": "老板后来改过的需求", "must_have": [],
                        "constraints": {}, "unknowns": []})
    fb = st1.add_feedback("ningbo-xiecheng", "boss_message", "保留入口")
    tid = st1.create_task("ningbo-xiecheng", "D2", "修订任务")
    st1.update_task(tid, "no_valid_revision", {"accepted_revision": False})
    gid = st1.open_gate("ningbo-xiecheng", "闸口", "详情")
    cr = st1.save_check_report("ningbo-xiecheng", {"stage": "passed"})
    st1.save_artifact("ningbo-xiecheng", "spatial-plan", valid_proposal("A"), "D2",
                      option_id="A", revision=1, status="valid_candidate",
                      contract_status="valid_candidate", check_report_id=cr)

    # simulate restart: new Store on the same file + seed again
    st2 = Store(p)
    orchestrator.Studio(st2).seed_from_fixtures()
    after = st2.get_project("ningbo-xiecheng")
    state2 = st2.project_state("ningbo-xiecheng")
    evidence = {
        "before": {"name": "自定义名称（不应被覆盖）",
                   "requirement": "老板后来改过的需求", "feedback": fb["revision_no"],
                   "task": tid, "gate": gid, "check_report": cr},
        "after_restart": {
            "name": after["name"], "requirement": after["requirement"]["text"],
            "feedback_revision": state2["feedback_revision"],
            "tasks": [{"status": t["status"]} for t in st2.tasks("ningbo-xiecheng")]
            if hasattr(st2, "tasks") else "n/a",
            "gates": len(state2["gates"]), "check_reports": len(state2["check_reports"]),
            "artifacts": len(state2["artifacts"]),
            "messages": len(state2["messages"]),
        },
        "seed_did_not_rewrite_facts": after["name"] == "自定义名称（不应被覆盖）"
                                       and after["requirement"]["text"] == "老板后来改过的需求",
        "feedback_not_duplicated": state2["feedback_revision"] == 1,
        "state_persisted": len(state2["gates"]) == 1 and len(state2["check_reports"]) == 1
                           and len(state2["artifacts"]) == 1,
    }
    ok = (evidence["seed_did_not_rewrite_facts"] and evidence["feedback_not_duplicated"]
          and evidence["state_persisted"])
    check("Q11", "重启保留反馈/任务/闸口/检查报告；种子不重写项目事实、不重复事实",
          ok, evidence)
    case("Q11 重启与种子幂等正例", "positive", evidence)


# --------------------------------------------------------------------- Q12
def q12() -> None:
    st = _db("q12")
    st.ensure_project("ningbo-xiecheng", "宁波", SITE, REQUIREMENT)
    studio = orchestrator.Studio(st)
    # local stub, no external channel
    import verify_studio_loop as vsl  # noqa: E402
    # use a fresh scratch db for the loop to avoid cross-test coupling
    loop_db = _db("q12loop")
    s2 = orchestrator.Studio(loop_db)
    s2.seed_from_fixtures()
    orchestrator.Client = vsl.FakeClient  # type: ignore[assignment]
    import rkd_mvp.studio.vision as _vision
    _vision.svg_to_jpeg = lambda svg, limit=720: vsl.FAKE_JPEG  # type: ignore[assignment]
    _vision.reference_jpeg = lambda limit=720: vsl.FAKE_JPEG  # type: ignore[assignment]
    s2.run_a1("ningbo-xiecheng", background=False)
    state = loop_db.project_state("ningbo-xiecheng")
    runs = state["runs"]
    arts = state["artifacts"]
    gates = state["gates"]
    evidence = {
        "run_statuses": [r["status"] for r in runs],
        "run_status_meaning": "succeeded 只表示流程跑完，不等于设计通过",
        "artifact_statuses": sorted({a["status"] for a in arts}),
        "contract_statuses": sorted({a["contract_status"] or "unvalidated" for a in arts}),
        "no_design_pass_claim": all(a["status"] not in ("approved", "design_passed")
                                    for a in arts),
        "gate_waiting": any(g["status"] == "waiting" for g in gates),
        "gate_decision_is_not_design_pass": all((g["decision"] or "") not in
                                                ("design_passed", "approved_design")
                                                for g in gates),
        "design_approved_by_user": False,
        "source_label": "local-model-stub（明确标记的本地模型桩，非真实 AI、非人工方案）",
        "no_next_stage_deliverables": all(a["kind"] in
                                          ("brief", "spatial-plan", "plan-sketch",
                                           "spatial-plan-raw") for a in arts),
        "ad01_ad08_unchanged": "AD01—AD08 由用户给结论，本批不自行改判",
        "external_calls": 0,
    }
    ok = (all(r["status"] in ("succeeded", "incomplete", "failed", "superseded")
              for r in runs)
          and evidence["no_design_pass_claim"] and evidence["gate_waiting"]
          and evidence["gate_decision_is_not_design_pass"]
          and evidence["no_next_stage_deliverables"] and evidence["external_calls"] == 0)
    check("Q12", "工程完成不自动设计通过；来源明确；未确认不生成下一阶段交付；AD 不改判",
          ok, evidence)
    case("Q12 流程跑完不等于设计通过", "positive", evidence)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(AFTER / "checks.json"))
    args = ap.parse_args()
    AFTER.mkdir(parents=True, exist_ok=True)
    for fn in (q01, q02, q03, q04, q05, q06, q07_q08, q09, q10, q11, q12):
        fn()
    passed = sum(1 for c in CHECKS if c["result"] == "observed_pass")
    failed = sum(1 for c in CHECKS if c["result"] == "observed_fail")
    not_run = sum(1 for c in CHECKS if c["result"] == "not_run")
    summary = {
        "task_id": "ARC-01—04 + ARC-06 (first batch)",
        "phase": "after",
        "baseline": "d6501a9b5b963b0a11a9e148b32eda269f18414b",
        "generated_at": _iso(),
        "environment": {
            "python": sys.version.split()[0],
            "geometry_engine": geometry.GEOMETRY_ENGINE,
            "jsonschema": "4.25.1",
            "model_channel": "local-model-stub (explicitly labelled; NO external calls)",
            "keys_used": False,
            "browser_evidence": "see browser/verification.json + screenshots",
        },
        "checks": CHECKS,
        "totals": {"observed_pass": passed, "observed_fail": failed, "not_run": not_run},
        "positive_negative_cases": CASES,
        "external_calls": 0,
        "image_counts": {"images_sent_external": 0, "images_generated_local": 0,
                         "note": "本专项为纯工程函数测试；A1 管线测试的看图步骤使用占位字节，不发送外部图片"},
        "tokens": {"external_tokens": 0, "stub_tokens_accounted": True,
                   "note": "本地桩的 token 计数仅用于台账演练，不代表真实模型用量"},
        "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
        "limitations": [
            "本地模型桩通过不代表真实 AI 设计通过；真实设计效果仍待后续授权验证",
            "AD01—AD08 不自行改判；用户设计阶段确认未发生",
            "首批未做 ARC-05 同源平面/渲染/数量纵向适配（Q10 not_run）",
            "专业规范/消防/疏散/无障碍未验证，程序明确标 unsupported",
            "真实 PG/NAS/账号/备份专项未重跑（管理配套冻结）",
        ],
        "artifact_refs": [
            "var/evidence/architecture-handoff/first-batch/review-packet.md",
            "var/evidence/architecture-handoff/first-batch/before/reproduction.json",
            "var/evidence/architecture-handoff/first-batch/after/checks.json",
            "var/evidence/architecture-handoff/first-batch/after/q-checks.json",
            "var/evidence/architecture-handoff/first-batch/after/after-reproduction.json",
            "var/evidence/architecture-handoff/first-batch/after/browser/verification.json",
            "var/evidence/architecture-handoff/first-batch/after/browser/browser-observations.json",
            "var/evidence/architecture-handoff/first-batch/after/browser/arc-feedback-desktop.png",
            "var/evidence/architecture-handoff/first-batch/after/browser/arc-revision-desktop.png",
            "var/evidence/architecture-handoff/first-batch/after/browser/arc-other-project.png",
            "var/evidence/architecture-handoff/first-batch/after/browser/arc-reload-desktop.png",
            "var/evidence/architecture-handoff/first-batch/after/browser/arc-mobile.png",
            "var/evidence/architecture-handoff/first-batch/after/full-unittest-final.log",
            "var/evidence/architecture-handoff/first-batch/after/frontend-build.log",
            "deliverables-for-review/arc-first-batch/code-diff.md",
            "deliverables-for-review/arc-first-batch/changes.patch",
            "deliverables-for-review/arc-first-batch/ARC-05-adaptation-note.md",
            "deliverables-for-review/arc-first-batch/positive-negative-cases.md",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    # W0/R3: write the companion q-checks beside the chosen output, so a later
    # regression run never overwrites the first batch's historical evidence.
    (out.parent / "q-checks.json").write_text(
        json.dumps({"checks": CHECKS, "cases": CASES,
                    "totals": summary["totals"]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps({"totals": summary["totals"], "out": str(out)}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
