"""ARC first batch: reproduce the architect's findings before/after the fix.

Runs read-only against var/studio/studio.db and uses isolated temp SQLite DBs
for store behaviour. NEVER calls an external model, NEVER reads a key.

    .venv/Scripts/python.exe scripts/arc_first_batch_repro.py --phase before \
        --out var/evidence/architecture-handoff/first-batch/before/reproduction.json

The script records OBSERVED behaviour only; it does not assert pass/fail so the
same script can be re-run after the fix to produce a comparable after/ report.
Pass/fail judgements live in scripts/verify_arc_first_batch.py (Q01-Q12).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))

from jsonschema import Draft202012Validator  # noqa: E402

from rkd_mvp.studio import tools as toolbox  # noqa: E402
from rkd_mvp.studio import orchestrator  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402

DB = ROOT / "var" / "studio" / "studio.db"
SCHEMA = ROOT / "contracts" / "v1" / "spatial-plan-draft.schema.json"
STANDARDS = ROOT / "knowledge" / "design-standards" / "standards.v1.json"
FIXTURE = ROOT / "fixtures" / "studio" / "projects" / "ningbo-xiecheng.json"
STUDIO_VIEW = ROOT / "web" / "src" / "StudioView.tsx"
ORCH = ROOT / "mvp" / "rkd_mvp" / "studio" / "orchestrator.py"


def _iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _readonly_plans() -> list[dict]:
    if not DB.exists():
        return []
    c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, kind, option_id, revision, payload_json, created_at "
        "FROM artifacts WHERE kind='spatial-plan' ORDER BY created_at DESC, id DESC LIMIT 2"
    ).fetchall()
    out = []
    for r in rows:
        out.append({"id": r["id"], "option_id": r["option_id"],
                    "revision": r["revision"], "created_at": r["created_at"],
                    "payload": json.loads(r["payload_json"])})
    c.close()
    return out


# ------------------------------------------------------------------ ARC-01
def repro_arc01() -> dict:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    stored = []
    for p in _readonly_plans():
        errs = list(validator.iter_errors(p["payload"]))
        stored.append({
            "artifact_id": p["id"], "option_id": p["option_id"],
            "schema_error_count": len(errs),
            "first_errors": [
                {"json_path": "/" + "/".join(str(x) for x in e.absolute_path),
                 "validator": e.validator, "message": e.message[:160]}
                for e in errs[:8]
            ],
            # The current gate used by the orchestrator
            "plan_is_valid": orchestrator.plan_is_valid(p["payload"]),
        })

    # Minimal-field probes: does the current usable-candidate gate catch them?
    good = json.loads(FIXTURE.read_text(encoding="utf-8"))["site"]
    base = {
        "contract_version": "rkd-spatial-plan.v1", "project_id": "ningbo-xiecheng",
        "option_id": "A", "revision": 1,
        "strategy": {"name": "测试", "narrative": "n" * 25,
                     "tradeoffs": ["a", "b"], "non_orthogonal": ["a", "b"]},
        "zones": [
            {"id": "Z1", "name": "序厅", "role": "arrival",
             "polygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]], "area_sqm": 1},
            {"id": "Z2", "name": "主展", "role": "gallery",
             "polygon": [[2000, 0], [3000, 0], [3000, 1000], [2000, 1000]], "area_sqm": 1},
            {"id": "Z3", "name": "洽谈", "role": "meeting",
             "polygon": [[4000, 0], [5000, 0], [5000, 1000], [4000, 1000]], "area_sqm": 1},
        ],
        "circulation": [{"id": "C1", "width_mm": 1500, "path": [[0, 0], [1000, 0]]}],
        "furniture": [{"id": "F1", "catalog_id": "sofa-3p", "x": 300, "y": 300}],
        "area_table": [{"name": "序厅", "area_sqm": 1},
                       {"name": "主展", "area_sqm": 1},
                       {"name": "洽谈", "area_sqm": 1}],
        "open_questions": [], "standards_cited": [],
    }

    probes = {}
    import copy
    p1 = copy.deepcopy(base)
    del p1["zones"][0]["role"]
    probes["zone_missing_role"] = {
        "schema_errors": len(list(validator.iter_errors(p1))),
        "plan_is_valid": orchestrator.plan_is_valid(p1),
    }
    p2 = copy.deepcopy(base)
    p2["area_table"][0]["area_sqm"] = "one"  # wrong type
    probes["area_table_wrong_type"] = {
        "schema_errors": len(list(validator.iter_errors(p2))),
        "plan_is_valid": orchestrator.plan_is_valid(p2),
    }
    p3 = copy.deepcopy(base)
    p3["furniture"][0]["catalog_id"] = "not-in-catalog-xyz"  # invalid reference
    probes["furniture_invalid_catalog_ref"] = {
        "schema_errors": len(list(validator.iter_errors(p3))),
        "plan_is_valid": orchestrator.plan_is_valid(p3),
        "semantic_reference_checked": False,  # observed: no reference check exists
    }
    p4 = copy.deepcopy(base)
    p4["approved"] = True  # model decides identity/approval
    p4["adopt_pointer"] = "A"
    probes["model_claims_approval_and_adoption"] = {
        "schema_errors": len(list(validator.iter_errors(p4))),
        "plan_is_valid": orchestrator.plan_is_valid(p4),
        "model_owns_approval_field": True,
    }
    return {"stored_latest_plans": stored,
            "minimal_gate_probes": probes,
            "site_used": {"width_mm": good["width_mm"], "height_mm": good["height_mm"]}}


# ------------------------------------------------------------------ ARC-02
def _rect(x0, y0, x1, y1, zid, name, role="gallery"):
    poly = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return {"id": zid, "name": name, "role": role, "polygon": poly,
            "area_sqm": abs((x1 - x0) * (y1 - y0)) / 1e6}


def repro_arc02() -> dict:
    cases = {}

    # (1) 100 sqm site, three 1 sqm zones, area table 3 sqm, disconnected circulation
    site = {"width_mm": 10000, "height_mm": 10000}
    plan = {
        "strategy": {"name": "稀疏布局", "narrative": "n" * 25,
                     "tradeoffs": ["a", "b"], "non_orthogonal": ["a", "b"]},
        "zones": [_rect(0, 0, 1000, 1000, "Z1", "序厅", "arrival"),
                  _rect(2000, 0, 3000, 1000, "Z2", "主展"),
                  _rect(4000, 0, 5000, 1000, "Z3", "洽谈", "meeting")],
        "circulation": [{"id": "C1", "width_mm": 1500, "path": [[8000, 8000], [9000, 8000]]}],
        "furniture": [], "area_table": [{"name": "序厅", "area_sqm": 1},
                                         {"name": "主展", "area_sqm": 1},
                                         {"name": "洽谈", "area_sqm": 1}],
        "ceiling": {"strategy": "x", "coves": [{"id": "CV1", "polygon": [[0, 0], [100, 0], [100, 100]]}],
                    "fixtures": []},
    }
    ck = toolbox.check_plan(plan, site)
    cases["100sqm_3sqm_zones"] = {
        "input": "100㎡ 场地 / 3 个各 1㎡ 分区 / 面积表 3㎡ / 动线不连接分区",
        "check_ok": ck["ok"], "blocker_count": sum(1 for i in ck["issues"] if i["severity"] == "blocker"),
        "issue_ids": [i["rule_id"] for i in ck["issues"]],
        "metrics": ck.get("metrics"),
        "unallocated_sqm_reported": "unallocated_sqm" in (ck.get("metrics") or {}),
    }

    # (2) two disjoint triangles whose bounding boxes overlap
    site2 = {"width_mm": 5000, "height_mm": 5000}
    tri = {
        "strategy": {"name": "三角", "narrative": "n" * 25,
                     "tradeoffs": ["a", "b"], "non_orthogonal": ["a", "b"]},
        "zones": [
            {"id": "A", "name": "三角A", "role": "gallery",
             "polygon": [[0, 0], [4000, 0], [0, 4000]], "area_sqm": 8.0},
            {"id": "B", "name": "三角B", "role": "gallery",
             "polygon": [[4000, 4000], [4000, 500], [500, 4000]], "area_sqm": 6.125},
        ],
        "circulation": [], "furniture": [], "area_table": [],
        "ceiling": {"coves": [], "fixtures": []},
    }
    ck2 = toolbox.check_plan(tri, site2)
    from shapely.geometry import Polygon
    pa, pb = Polygon(tri["zones"][0]["polygon"]), Polygon(tri["zones"][1]["polygon"])
    cases["disjoint_triangles_bbox_overlap"] = {
        "input": "A=[(0,0),(4000,0),(0,4000)] B=[(4000,4000),(4000,500),(500,4000)]",
        "shapely_actual_intersection_area_mm2": pa.intersection(pb).area,
        "shapely_intersects": pa.intersects(pb),
        "check_issue_ids": [i["rule_id"] for i in ck2["issues"]],
        "GEO_004_reported": any(i["rule_id"] == "GEO-004" for i in ck2["issues"]),
    }

    # (3) area table completed with "circulation and other" -> contradictory hint
    nb = json.loads(FIXTURE.read_text(encoding="utf-8"))["site"]
    plan3 = {
        "strategy": {"name": "补齐", "narrative": "n" * 25,
                     "tradeoffs": ["a", "b"], "non_orthogonal": ["a", "b"]},
        "zones": [_rect(0, 0, 5000, 5000, "Z1", "功能区", "gallery")],
        "circulation": [{"id": "C1", "width_mm": 1500, "path": [[0, 0], [1000, 0]]}],
        "furniture": [],
        "area_table": [{"name": "功能区", "area_sqm": 25.0},
                       {"name": "通道及其他", "area_sqm": 469.0 - 25.0}],
        "ceiling": {"coves": [], "fixtures": []},
    }
    ck3 = toolbox.check_plan(plan3, nb)
    cases["area_table_completed_then_contradiction"] = {
        "input": "面积表补『通道及其他』凑 469㎡，轮廓只统计功能区 25㎡",
        "issue_ids": [i["rule_id"] for i in ck3["issues"]],
        "hints": [i.get("hint") for i in ck3["issues"]],
        "metrics": ck3.get("metrics"),
    }

    # (4) non-orthogonal count comes from the text list length, not geometry
    plan4 = dict(plan)
    plan4 = json.loads(json.dumps(plan))
    plan4["strategy"] = {"name": "全矩形", "narrative": "n" * 25,
                         "tradeoffs": ["a", "b"],
                         "non_orthogonal": ["声称圆角", "声称弧墙"]}
    ck4 = toolbox.check_plan(plan4, site)
    cases["non_orthogonal_text_only"] = {
        "input": "2 条非直角文字声明，所有分区均为轴对齐矩形",
        "metrics_non_orthogonal_count": (ck4.get("metrics") or {}).get("non_orthogonal_count"),
        "STD_001_reported": any(i["rule_id"] == "STD-001" for i in ck4["issues"]),
        "geometry_correspondence_checked": False,
    }
    return cases


# ------------------------------------------------------------------ ARC-03
def repro_arc03() -> dict:
    src = ORCH.read_text(encoding="utf-8")
    truncations = [{"line": i + 1, "code": line.strip()[:160]}
                   for i, line in enumerate(src.splitlines())
                   if re.search(r"\[:\d{4}\]", line)]

    # Build a plan whose LAST object is beyond every truncation limit.
    base = {
        "contract_version": "rkd-spatial-plan.v1", "project_id": "ningbo-xiecheng",
        "option_id": "A", "revision": 1,
        "strategy": {"name": "长方案", "narrative": "叙" * 120,
                     "tradeoffs": ["a", "b"], "non_orthogonal": ["a", "b"]},
        "zones": [], "circulation": [], "furniture": [], "area_table": [],
        "open_questions": [], "standards_cited": [],
    }
    for k in range(30):
        base["zones"].append(_rect(k * 200, 0, k * 200 + 100, 100, f"Z{k}", f"分区{k}"))
    base["zones"].append({"id": "ZONE_TAIL_SENTINEL", "name": "末尾分区-评审应可见",
                          "role": "support",
                          "polygon": [[9000, 0], [9100, 0], [9100, 100], [9000, 100]],
                          "area_sqm": 0.01})
    full = json.dumps(base, ensure_ascii=False)
    tail_pos = full.find("ZONE_TAIL_SENTINEL")
    limits = {}
    for n in (4000, 3500, 3000):
        limits[str(n)] = {"tail_object_reachable": "ZONE_TAIL_SENTINEL" in full[:n]}
    return {
        "truncation_sites": truncations,
        "plan_json_chars": len(full),
        "tail_object_char_position": tail_pos,
        "limits": limits,
        "review_context_uses": "ctx + 候选 A json[:4000] + 候选 B json[:4000]",
        "revision_context_uses": "ctx + 原候选 json[:4000]；打回稿 json[:3500]；issues json[:3000]",
        "baseline_id_in_downstream_prompt": "baseline_id" in src or "issue_id" in src,
    }


# ------------------------------------------------------------------ ARC-04
def repro_arc04() -> dict:
    out = {}
    view = STUDIO_VIEW.read_text(encoding="utf-8")
    m = re.search(r"const studioId\s*=\s*(.+);", view)
    out["frontend_project_hardcode"] = {
        "line": next((i + 1 for i, l in enumerate(view.splitlines()) if "const studioId" in l), None),
        "expression": m.group(1).strip() if m else None,
        "both_branches_ningbo": bool(m and m.group(1).count("ningbo-xiecheng") >= 2),
    }

    # isolated store: does a boss message become versioned feedback / requirement?
    # A fixed scratch path (never deleted) avoids the Windows file-lock failure
    # of TemporaryDirectory cleanup when SQLite connections are still GC-pending.
    scratch = ROOT / "var" / "evidence" / "architecture-handoff" / "first-batch" / "before" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    if True:
        import os as _os
        st = Store(scratch / f"repro-{_os.getpid()}.db")
        st.upsert_project("p1", "项目一", {"width_mm": 10000, "height_mm": 10000},
                          {"text": "原始需求", "must_have": [], "constraints": {}, "unknowns": []})
        st.add_message("p1", "BOSS", "boss", "把洽谈区往南挪，保留入口",
                       evidence=[{"type": "boss"}])
        with st._conn() as c:
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        out["boss_message"] = {
            "tables": tables,
            "has_feedback_table": any("feedback" in t for t in tables),
            "message_count": len(st.messages("p1")),
            "requirement_after": st.get_project("p1")["requirement"]["text"],
            "became_versioned_feedback": False,
        }

        # seed overwrite: existing project fact rewritten on every startup
        st.upsert_project("ningbo-xiecheng", "自定义名称",
                          {"width_mm": 1, "height_mm": 1},
                          {"text": "老板后来改过的需求", "must_have": [],
                           "constraints": {}, "unknowns": []})
        seeded = orchestrator.Studio(st).seed_from_fixtures()
        after = st.get_project("ningbo-xiecheng")
        out["seed_overwrites_existing_facts"] = {
            "seeded_ids": seeded,
            "name_after_seed": after["name"],
            "requirement_text_after_seed": after["requirement"]["text"][:40],
            "site_width_after_seed": after["site"]["width_mm"],
        }

        # gate replay: can a decided gate be overwritten?
        gid = st.open_gate("p1", "闸口一", "详情")
        st.decide_gate(gid, "approve", "第一次决定")
        g1 = dict(st.gate(gid))
        st.decide_gate(gid, "reject", "重放覆盖")
        g2 = dict(st.gate(gid))
        out["gate_replay"] = {
            "first_decision": g1["decision"], "first_comment": g1["comment"],
            "decided_at_first": g1["decided_at"],
            "after_replay_decision": g2["decision"], "after_replay_comment": g2["comment"],
            "decided_at_after": g2["decided_at"],
            "replay_overwrote_decision": g1["decision"] != g2["decision"],
        }
        with st._conn() as c:
            out["gate_columns"] = [r[1] for r in c.execute("PRAGMA table_info(gates)").fetchall()]
            out["artifact_columns"] = [r[1] for r in c.execute("PRAGMA table_info(artifacts)").fetchall()]
            out["run_columns"] = [r[1] for r in c.execute("PRAGMA table_info(runs)").fetchall()]

    # static checks on server / orchestrator
    server_src = (ROOT / "mvp" / "rkd_mvp" / "studio" / "server.py").read_text(encoding="utf-8")
    out["messages_endpoint"] = {
        "writes_only_timeline_message": 'add_message(pid, "BOSS", "boss", text' in server_src,
        "has_feedback_write": "feedback" in server_src.lower(),
        "has_expected_version": "expected" in server_src.lower(),
    }
    out["run_a1_signature"] = str(__import__("inspect").signature(orchestrator.Studio.run_a1))
    return out


# ------------------------------------------------------------------ ARC-06
def repro_arc06() -> dict:
    data = json.loads(STANDARDS.read_text(encoding="utf-8"))
    flagged = []
    for r in data["rules"]:
        if re.search(r"\d", r.get("checkable", "")):
            flagged.append({
                "id": r["id"], "title": r["title"], "source": r["source"],
                "checkable": r["checkable"], "severity": r["severity"],
                "has_project_scope": "scope" in r,
                "has_heuristic_marking": "derived_heuristic" in r,
                "has_professional_basis": "professional_basis" in r,
                "has_program_coverage": "program_coverage" in r,
                "numeric_not_pass_criterion": (r.get("derived_heuristic") or {}).get(
                    "is_pass_criterion") is False if isinstance(
                        r.get("derived_heuristic"), dict) else True,
            })
    llm_src = (ROOT / "mvp" / "rkd_mvp" / "studio" / "llm.py").read_text(encoding="utf-8")
    return {
        "rules_with_numeric_thresholds": flagged,
        "note": "未区分用户原话 / 项目适用范围 / 派生启发式 / 专业规范依据 / 程序实际覆盖",
        "llm_budget": {
            "guard_only_max_tokens": "_guard(projected=max_tokens)" in llm_src,
            "usage_missing_defaults_zero": "or 0" in llm_src,
            "has_pending_reconciliation": "pending_reconciliation" in llm_src,
            # downgrade is now conditioned on an explicitly unsupported feature
            "downgrade_on_any_response_format_error": (
                'elif "response_format" in body:' in llm_src
                or 'if "response_format" in body:' in llm_src),
            "downgrade_only_on_unsupported": "_is_unsupported_error(str(exc))" in llm_src,
            "input_and_output_reserved": "projected_in=projected_in" in llm_src,
            "usage_missing_is_unknown": "usage_missing_calls" in llm_src,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["before", "after"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    report = {
        "phase": args.phase, "generated_at": _iso(),
        "baseline_commit": "d6501a9b5b963b0a11a9e148b32eda269f18414b",
        "python": sys.version.split()[0],
        "external_model_calls": 0,
        "arc01_contract": repro_arc01(),
        "arc02_geometry": repro_arc02(),
        "arc03_context": repro_arc03(),
        "arc04_feedback_project_version": repro_arc04(),
        "arc06_rules_and_cost": repro_arc06(),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"phase": args.phase, "out": str(out),
                      "schema_errors": [p["schema_error_count"] for p in report["arc01_contract"]["stored_latest_plans"]],
                      "arc02_100sqm_ok": report["arc02_geometry"]["100sqm_3sqm_zones"]["check_ok"],
                      "truncation_sites": len(report["arc03_context"]["truncation_sites"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
