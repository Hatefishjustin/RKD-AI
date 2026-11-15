"""W2-R4 入口小修：同层异材重叠不能靠声明文字变成 known 重复工程量。

架构师独立复现（review-and-R4.md §R4入口小修）：同一 floor_finish 层两块完全
相同的 2m×2m 材料面（material_id=wood/stone），附 overlap_declaration 说明文字，
normalize_finish_scope 放行，_finish_quantity 按 (layer, material_id) 分别并集再
相加输出 8㎡/known；实际同层铺装区域只有 4㎡。两条几何算法同时得到 8 不能证明
材料分配正确。

同一脚本对整改前/后各跑一次：
  PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe \
      scripts/verify_w2_r4_finish_conflict.py --label before --out <dir>
  ... --label after  --out <dir>

只用隔离 SQLite + 真实回环 HTTP + 可控渲染桩；0 外部模型调用、0 密钥、0 费用。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("RKD_VERIFY_ROOT") or
            Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import w2_closeout_repro as base  # noqa: E402
from rkd_mvp.ai_spatial_outputs import build_cost, measure  # noqa: E402

CHECKS: list[dict] = []
LABEL = "after"
ORG = base.ORG
SQUARE = [[0, 0], [2000, 0], [2000, 2000], [0, 2000]]        # 4.0 ㎡
RIGHT = [[2000, 0], [4000, 0], [4000, 2000], [2000, 2000]]    # 4.0 ㎡，与 SQUARE 不重叠


def record(cid: str, name: str, fn) -> None:
    try:
        result = fn()
    except Exception as error:  # noqa: BLE001
        result = {"signature": "error",
                  "error": f"{type(error).__name__}: {error}",
                  "trace": traceback.format_exc(limit=4).splitlines()[-4:]}
    CHECKS.append({"id": cid, "name": name, **result})
    print(f"{result.get('signature', '?'):<20} {cid} {name}", flush=True)


def model():
    return base.l_shape_model([])


def scope_base(areas, **extra):
    value = {"kind": "material_face_slice",
             "declared_by": "w2_r4_finish_conflict_fixture",
             "declaration": "解析夹具：同层材料面分配试验，未经现场复核",
             "unit": "mm", "deduction_basis": "none", "areas": areas}
    value.update(extra)
    return value


def face(oid, material_id, polygon=SQUARE, layer="floor_finish"):
    return {"object_id": oid, "name": oid, "polygon_mm": copy.deepcopy(polygon),
            "unit": "m2", "layer": layer,
            "material_ref": {"material_id": material_id, "name": material_id,
                             "spec_status": "assumption"}}


def outcome(scope, prices=None):
    try:
        qty = measure(model(), finish_scope=scope)
    except ValueError as error:
        # 整改前：结构化裁切字段被忽略，重叠又无自由文字声明 → 入口直接抛错。
        # 这也是「不能靠声明文字消歧」的缺陷表现之一，如实记为 rejected。
        return {"finish_status": "rejected", "finish_value": None,
                "reject_reason": str(error)[:240], "groups": [], "conflicts": None,
                "quantity_kind": None, "layer_scope_note": None,
                "allocation_applied": None, "known_items": [],
                "assumption_trial_total_cny": None, "basis": {}}
    finish = base.find_q(qty, "Q-FLOOR-FINISH") or {}
    cost = build_cost(qty, settings={"material_unit_prices": prices or
                                     {"wood": 1000, "stone": 1000}})
    return {"finish_status": finish.get("known_status"),
            "finish_value": finish.get("value"),
            "groups": [{"layer": g.get("layer"), "material_id": g.get("material_id"),
                        "area_m2": g.get("area_m2")}
                       for g in finish.get("material_groups") or []],
            "conflicts": finish.get("same_layer_material_conflicts"),
            "quantity_kind": finish.get("quantity_kind"),
            "layer_scope_note": finish.get("layer_scope_note"),
            "allocation_applied": (finish.get("basis_source") or {}).get("allocation_applied"),
            "known_items": cost["known_items"],
            "assumption_trial_total_cny": cost.get("assumption_trial_total_cny"),
            "basis": cost["pricing_basis"]}


# --------------------------------------------------------------- 函数级用例
def c01_mixed_material_overlap():
    """架构师负例：同层异材完全重叠 + 自由文字声明 → 不得产出 known 总量/试算。"""
    scope = scope_base([face("F-WOOD", "wood"), face("F-STONE", "stone")],
                       overlap_declaration="两块材料面有意搭接，按声明各自计量")
    got = outcome(scope)
    is_defect = (got["finish_status"] == "known" and got["finish_value"] == 8.0
                 and len(got["known_items"]) == 2)
    is_fixed = (got["finish_status"] == "conflict" and got["finish_value"] is None
                and got["known_items"] == []
                and got["assumption_trial_total_cny"] is None
                and isinstance(got["conflicts"], list) and got["conflicts"])
    return {"signature": "defect_reproduced" if is_defect else
            "fixed_signature" if is_fixed else "unexpected",
            "expected_before": "8㎡/known + 两笔试算（重复工程量）",
            "expected_after": "conflict/None + 0 笔试算 + 冲突明细",
            "observed": got}


def c02_same_material_declared():
    """回归护栏：同材同层重叠 + 声明仍按并集 4㎡，不得被误伤。"""
    scope = scope_base([face("F-A", "wood"), face("F-B", "wood")],
                       overlap_declaration="同材质搭接 2×2m，按并集计量")
    got = outcome(scope, {"wood": 1000})
    ok = (got["finish_status"] == "known" and abs((got["finish_value"] or -1) - 4.0) < 1e-6
          and len(got["known_items"]) == 1 and got["known_items"][0]["amount_cny"] == 4000.0)
    return {"signature": "regression_guard" if ok else "unexpected",
            "expected": "4㎡/known，按并集不重复相加，试算 4000 元",
            "observed": got}


def c03_mixed_material_disjoint():
    """正例：同层异材但不重叠 → 各自计量 4+4=8㎡ 合法。"""
    scope = scope_base([face("F-WOOD", "wood", SQUARE),
                        face("F-STONE", "stone", RIGHT)])
    got = outcome(scope)
    ok = (got["finish_status"] == "known" and abs((got["finish_value"] or -1) - 8.0) < 1e-6
          and len(got["groups"]) == 2)
    return {"signature": "regression_guard" if ok else "unexpected",
            "expected": "8㎡/known，两组各 4㎡（几何互斥，不是重复工程量）",
            "observed": got}


def c04_different_layers():
    """不同构造层分别计量，但合计不得叫单层地坪净面积。"""
    scope = scope_base([face("F-FLOOR", "wood", SQUARE, "floor_finish"),
                        face("F-WALL", "stone", SQUARE, "wall_finish")])
    got = outcome(scope)
    labelled = bool(got["quantity_kind"] == "multi_layer_sum"
                    and got["layer_scope_note"]
                    and "单层" in str(got["layer_scope_note"]))
    return {"signature": "fixed_signature" if labelled else "defect_reproduced",
            "expected_after": "分组计量 + quantity_kind=multi_layer_sum + 非单层净面积标注",
            "expected_before": "无多构造层口径标注（合计被当作单层净面积）",
            "observed": got}


def c05_explicit_disjoint_cut():
    """除非给出结构化互斥分配并实际裁切，才允许同层异材同时计量。"""
    cuts = [
        {"object_id": "CUT-WOOD", "material_id": "wood",
         "polygon_mm": [[0, 0], [1000, 0], [1000, 2000], [0, 2000]],
         "source_object_ids": ["F-WOOD", "F-STONE"], "layer": "floor_finish"},
        {"object_id": "CUT-STONE", "material_id": "stone",
         "polygon_mm": [[1000, 0], [2000, 0], [2000, 2000], [1000, 2000]],
         "source_object_ids": ["F-WOOD", "F-STONE"], "layer": "floor_finish"},
    ]
    scope = scope_base([face("F-WOOD", "wood"), face("F-STONE", "stone")],
                       overlap_declaration="自由文字不能消歧",
                       material_allocation={
                           "declared_by": "w2_r4_finish_conflict_fixture",
                           "method": "explicit_disjoint_cut",
                           "declaration": "把 2×2m 面按 x=1000 裁成互斥的两块，几何可复核",
                           "cuts": cuts})
    got = outcome(scope)
    ok = (got["finish_status"] == "known" and abs((got["finish_value"] or -1) - 4.0) < 1e-6
          and len(got["groups"]) == 2 and got["allocation_applied"])
    return {"signature": "fixed_signature" if ok else "defect_reproduced",
            "expected_after": "4㎡/known，wood 2㎡ + stone 2㎡，记录实际裁切",
            "expected_before": "结构化裁切字段被忽略，仍按重叠算 8㎡",
            "observed": got}


def c06_bad_allocation_rejected():
    """结构化分配若没有真正互斥/覆盖，也不能当消歧规则。"""
    cuts = [
        {"object_id": "BAD-1", "material_id": "wood",
         "polygon_mm": [[0, 0], [2000, 0], [2000, 2000], [0, 2000]],
         "source_object_ids": ["F-WOOD", "F-STONE"], "layer": "floor_finish"},
        {"object_id": "BAD-2", "material_id": "stone",
         "polygon_mm": [[0, 0], [500, 0], [500, 2000], [0, 2000]],
         "source_object_ids": ["F-WOOD", "F-STONE"], "layer": "floor_finish"},
    ]
    scope = scope_base([face("F-WOOD", "wood"), face("F-STONE", "stone")],
                       material_allocation={"declared_by": "fixture",
                                            "method": "explicit_disjoint_cut",
                                            "cuts": cuts})
    got = outcome(scope)
    fixed = (got["finish_status"] == "conflict" and got["finish_value"] is None
             and not got["allocation_applied"])
    defect = got["finish_status"] in {"known", "rejected"}
    return {"signature": "fixed_signature" if fixed else
            "defect_reproduced" if defect else "unexpected",
            "expected_after": "重叠裁切面被拒，仍为 conflict/待核，不产 known 总量",
            "expected_before": "裁切字段被忽略：要么按重叠算 8㎡，要么入口直接抛错",
            "observed": got}


# --------------------------------------------------------------- 真实 HTTP
def _http_case(stack, key: str, scope: dict):
    rev = stack.import_layout("A")
    stack.adopt(rev)
    code, gen, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                             {"option_revision_id": rev["option_revision_id"],
                              "settings": {"render": False, "finish_scope": scope,
                                           "material_unit_prices": {"wood": 1000,
                                                                    "stone": 1000}}},
                             {"Idempotency-Key": key})
    if code not in (200, 202):
        return {"signature": "unexpected", "submit_status": code, "submit_body": gen}
    _, state, job = _wait(stack, gen["item"]["job_id"])
    revision = state.get("revision") or {}
    if job.get("status") != "succeeded" or not revision:
        return {"signature": "unexpected", "job_status": job.get("status"),
                "error": job.get("error_code"), "message": job.get("error_message")}
    rid = revision["production_revision_id"]
    finish = base.find_q(revision["quantities"], "Q-FLOOR-FINISH") or {}
    cost = revision["cost"]
    csv_text = base.http("GET", f"{stack.base}/spatial-outputs/{rid}/files/quantity.csv")[2].decode("utf-8")
    html = base.http("GET", f"{stack.base}/spatial-outputs/{rid}/files/cost.html")[2].decode("utf-8")
    manifest = json.loads(base.http("GET", f"{stack.base}/spatial-outputs/{rid}/files/manifest.json")[2])
    observed = {"job_status": job.get("status"),
                "finish_status": finish.get("known_status"),
                "finish_value": finish.get("value"),
                "conflicts": finish.get("same_layer_material_conflicts"),
                "known_items": len(cost.get("known_items") or []),
                "assumption_trial_total_cny": cost.get("assumption_trial_total_cny"),
                "csv_has_conflict": "conflict" in csv_text,
                "html_has_pending": ("冲突" in html and "待核" in html),
                "html_has_amount": "8000" in html or "4000" in html,
                "manifest_conflict": bool((manifest.get("quantities") or {}).get("items"))}
    if LABEL == "after":
        ok = (observed["job_status"] == "succeeded" and observed["finish_status"] == "conflict"
              and observed["finish_value"] is None and observed["known_items"] == 0
              and observed["assumption_trial_total_cny"] is None
              and observed["csv_has_conflict"] and observed["html_has_pending"]
              and not observed["html_has_amount"])
        return {"signature": "fixed_signature" if ok else "unexpected",
                "expected_after": "任务成功但饰面量 conflict/None，CSV/HTML 标待核，0 笔试算",
                "observed": observed}
    defect = (observed["finish_status"] == "known" and observed["finish_value"] == 8.0
              and observed["known_items"] == 2 and observed["html_has_amount"])
    ok = observed["job_status"] == "succeeded" and defect
    return {"signature": "defect_reproduced" if ok else "unexpected",
            "expected_before": "8㎡/known + 两笔试算，冲突进入真实成果",
            "observed": observed}


def _wait(stack, job_id: str, timeout: float = 60.0):
    import time
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        code, data, _ = base.http("GET", f"{stack.base}/spatial-outputs?job_id={job_id}")
        last = data.get("job") or {}
        if last.get("job_id") != job_id:
            last = next((j for j in data.get("jobs") or [] if j["job_id"] == job_id), last)
        if last.get("status") in {"succeeded", "failed", "cancelled"}:
            return code, data, last
        time.sleep(0.02)
    raise AssertionError(f"等待任务超时：{job_id} 最后 {last.get('status')}")


def c07_http_conflict_negative(stack):
    return _http_case(stack, "w2r4-finish-http-conflict-0001",
                      scope_base([face("F-WOOD", "wood"), face("F-STONE", "stone")],
                                 overlap_declaration="自由文字声明不能消歧"))


def c08_http_same_material_positive(stack):
    rev = stack.import_layout("B")
    stack.adopt(rev)
    scope = scope_base([face("F-A", "wood"), face("F-B", "wood")],
                       overlap_declaration="同材质搭接，按并集计量")
    code, gen, _ = base.http("POST", f"{stack.base}/spatial-outputs",
                             {"option_revision_id": rev["option_revision_id"],
                              "settings": {"render": False, "finish_scope": scope,
                                           "material_unit_prices": {"wood": 1000}}},
                             {"Idempotency-Key": "w2r4-finish-http-positive-0002"})
    if code not in (200, 202):
        return {"signature": "unexpected", "submit_status": code, "submit_body": gen}
    _, state, job = _wait(stack, gen["item"]["job_id"])
    revision = state.get("revision") or {}
    finish = base.find_q(revision.get("quantities") or {}, "Q-FLOOR-FINISH") or {}
    cost = revision.get("cost") or {}
    ok = (job.get("status") == "succeeded" and finish.get("known_status") == "known"
          and abs((finish.get("value") or -1) - 4.0) < 1e-6
          and len(cost.get("known_items") or []) == 1
          and cost["known_items"][0]["amount_cny"] == 4000.0)
    return {"signature": "regression_guard" if ok else "unexpected",
            "expected": "同材声明后仍按并集 4㎡，真实入口试算 4000 元",
            "observed": {"job_status": job.get("status"),
                         "finish_status": finish.get("known_status"),
                         "finish_value": finish.get("value"),
                         "amount": (cost.get("known_items") or [{}])[0].get("amount_cny")}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="after", choices=("before", "after"))
    parser.add_argument("--out", default=str(ROOT / "var/evidence/roadmap/W2-R4-同源表达"))
    args = parser.parse_args()
    global LABEL
    LABEL = args.label
    raw = Path(args.out)
    out_dir = raw if raw.is_absolute() else (ROOT / raw)
    out_dir.mkdir(parents=True, exist_ok=True)

    record("R4F-01", "同层异材完全重叠 + 声明文字：不得产出 known 重复工程量",
           c01_mixed_material_overlap)
    record("R4F-02", "回归：同材同层重叠声明后仍按并集 4㎡", c02_same_material_declared)
    record("R4F-03", "正例：同层异材几何互斥 4+4=8㎡ 合法", c03_mixed_material_disjoint)
    record("R4F-04", "不同构造层分别计量，合计不得叫单层地坪净面积", c04_different_layers)
    record("R4F-05", "结构化互斥分配并实际裁切 → 4㎡ known", c05_explicit_disjoint_cut)
    record("R4F-06", "裁切不互斥/不覆盖 → 仍为 conflict 待核", c06_bad_allocation_rejected)

    runtime = out_dir / f"runtime-finish-{args.label}"
    stack = base.Stack(runtime)
    try:
        record("R4F-07", "真实 HTTP 负例：冲突不产生 known 总量/试算（修复前为缺陷）",
               lambda: c07_http_conflict_negative(stack))
        record("R4F-08", "真实 HTTP 回归：同材声明后并集 4㎡/4000 元",
               lambda: c08_http_same_material_positive(stack))
    finally:
        stack.close()

    expected = {"before": {"R4F-01": "defect_reproduced", "R4F-02": "regression_guard",
                           "R4F-03": "regression_guard", "R4F-04": "defect_reproduced",
                           "R4F-05": "defect_reproduced", "R4F-06": "defect_reproduced",
                           "R4F-07": "defect_reproduced", "R4F-08": "regression_guard"},
                "after": {"R4F-01": "fixed_signature", "R4F-02": "regression_guard",
                          "R4F-03": "regression_guard", "R4F-04": "fixed_signature",
                          "R4F-05": "fixed_signature", "R4F-06": "fixed_signature",
                          "R4F-07": "fixed_signature", "R4F-08": "regression_guard"}}[args.label]
    bad = [c["id"] for c in CHECKS if c.get("signature") != expected.get(c["id"])]
    payload = {
        "task_id": "W2-R4 入口小修：同层异材重叠冲突",
        "schema_version": "rkd-w2-r4-finish-conflict.v1",
        "label": args.label,
        "source_root": str(ROOT),
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "environment": {"python": sys.version.split()[0],
                        "stack": "isolated SQLite + real loopback HTTP + controllable render stub",
                        "external_calls": 0, "keys_used": False},
        "expected_signatures": expected,
        "unexpected_cases": bad,
        "all_as_expected": not bad,
        "checks": CHECKS,
        "external_calls": 0, "tokens": 0, "cost_amount_or_null": None,
        "cost_status": "no_external_calls_zero_cost",
    }
    target = out_dir / f"finish-conflict-{args.label}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"label": args.label, "all_as_expected": not bad,
                      "unexpected": bad, "out": str(target)}, ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
