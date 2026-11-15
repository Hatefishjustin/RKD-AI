"""W2-R4 表达收口 V1—V3 专项自动断言（与人工目检严格分列）。

用法：PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe \
        scripts/verify_w2_r4_closeout.py --evidence <完整验证目录> --out <输出目录>

只读取完整验证产物做几何/契约对账，并做一次生成器级「去掉测试陈设后工程量不变」
的受控对比。人工目检（前后图与局部可读性）在复核包 manual-visual-review.md 单列，
本脚本绝不代替人工看图，也不以非空 SVG / 亮度阈值宣布通过。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from rkd_mvp.ai_spatial_outputs import build_package  # noqa: E402

CHECKS: list[dict] = []


def check(cid: str, name: str, ok: bool, detail: dict, *, layer: str = "automatic") -> None:
    CHECKS.append({"id": cid, "name": name, "result": "observed_pass" if ok else "observed_fail",
                   "layer": layer, "evidence": detail})
    print(("PASS " if ok else "FAIL ") + cid + " " + name, flush=True)


def jload(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--visual-observations", default=None)
    args = parser.parse_args()
    evidence = Path(args.evidence).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    visual = (Path(args.visual_observations).resolve() if args.visual_observations
              else evidence / "visual" / "capture-observations.json")

    for letter in ("A", "B"):
        base = evidence / "outputs" / f"layout-{letter}"
        svg = (base / "plan.svg").read_text(encoding="utf-8")
        index = jload(base / "plan-index.json")
        scene = jload(base / "scene.json")
        qty = jload(base / "quantity.json")
        pres = jload(base / "presentation.json")
        scope = jload(base / "finish-scope.json")
        model = jload(base / "model.json")
        meta = jload(base / "render-meta.json")

        # ------------------------------------------------------------- V1 平面
        layers = [f'id="layer-{name}"' for name in
                  ("geometry", "ids", "annotations")]
        check(f"V1-{letter}-01", "平面几何/编号/注释三层分离，坐标度量可复核",
              all(token in svg for token in layers)
              and "data-plan-metrics=" in svg
              and "data-plan-layers-version=" in svg,
              {"layers_present": [t for t in layers if t in svg],
               "svg_bytes": len(svg)})

        chain = index["dimension_chain"]
        x_closed = chain["x"]["closed"] and abs(
            chain["x"]["sum_delta_mm"] - chain["x"]["total_mm"]) < 0.2
        y_closed = chain["y"]["closed"] and abs(
            chain["y"]["sum_delta_mm"] - chain["y"]["total_mm"]) < 0.2
        check(f"V1-{letter}-02", "受控尺寸链 X/Y 从边界经开口/平台站点闭合到总尺寸",
              bool(x_closed and y_closed),
              {"x": {k: chain["x"][k] for k in ("total_mm", "sum_delta_mm", "closed")},
               "y": {k: chain["y"][k] for k in ("total_mm", "sum_delta_mm", "closed")},
               "x_stations": len(chain["x"]["stations"]),
               "y_stations": len(chain["y"]["stations"]),
               "note": chain["note"]})

        required_kinds = {"zone", "wall", "opening", "camera", "circulation",
                          "keepout", "furniture"}
        got_kinds = {v["kind"] for v in index["labels"].values()}
        check(f"V1-{letter}-03", "编号索引覆盖墙体/开口/相机/分区/动线/家具，引用可对账",
              required_kinds <= got_kinds
              and all(v.get("object_id") for v in index["labels"].values()),
              {"label_count": len(index["labels"]),
               "kinds": sorted(got_kinds),
               "expression_accounting": index["expression_accounting"]})

        geo = {}
        if visual.is_file():
            obs = jload(visual)
            geo = (obs.get("auto_geometry_check") or {}).get(f"{letter}-after") or {}
        check(f"V1-{letter}-04", "自动几何检查：图面标注无互相压叠、无出界、字号不低于 8",
              bool(geo and geo.get("overlap_count") == 0
                   and geo.get("outside_count") == 0
                   and (geo.get("min_font_size") or 0) >= 8
                   and (geo.get("annotation_count") or 0) > 20),
              {"source": str(visual), "annotation_count": geo.get("annotation_count"),
               "overlaps": geo.get("overlap_count"), "outside": geo.get("outside_count"),
               "min_font": geo.get("min_font_size"),
               "note": "自动几何检查不代替人工目检"})

        # ------------------------------------------------------- V2 窗光 / 材质
        expr_meta = meta.get("expression") or {}
        win = expr_meta.get("window_expression") or {}
        finish = expr_meta.get("material_finish_applied") or {}
        check(f"V2-{letter}-01", "玻璃为透明透射，发光玻璃板为 0，窗外为标注的本地假设",
              bool(win.get("glass_kind") == "transparent"
                   and win.get("emissive_glass_panels") == 0
                   and (win.get("outside_panels") or 0) >= 5
                   and "assumption" in str(win.get("outside_environment") or "")),
              {"glass_kind": win.get("glass_kind"),
               "emissive_glass_panels": win.get("emissive_glass_panels"),
               "outside_panels": win.get("outside_panels"),
               "outside_environment": win.get("outside_environment"),
               "outside_note": win.get("outside_note")})
        check(f"V2-{letter}-02", "木饰面与地面的纹理比例/分缝/收边来自版本化表达输入",
              bool(expr_meta.get("schema_version") == "rkd-spatial-expression.v1"
                   and len(finish.get("materials") or []) >= 2
                   and (finish.get("floor_joint_lines") or 0) > 0
                   and (finish.get("wood_panel_joint_lines") or 0) > 0
                   and (finish.get("skirting_segments") or 0) > 0
                   and abs(float(win.get("exposure_ev") or 0)
                           - float(pres["expression"]["window_expression"]["exposure_ev"])) < 1e-4),
              {"schema_version": expr_meta.get("schema_version"),
               "materials": finish.get("materials"),
               "floor_joint_lines": finish.get("floor_joint_lines"),
               "wood_panel_joint_lines": finish.get("wood_panel_joint_lines"),
               "skirting_segments": finish.get("skirting_segments"),
               "exposure_ev": win.get("exposure_ev"),
               "window_light_energy_scale": win.get("window_light_energy_scale")})
        check(f"V2-{letter}-03", "场景保留模型来源与假设标识，采光仍只来自已建模窗口",
              bool(scene.get("presentation_disclaimer")
                   and scene["presentation"].get("site_verified") is False
                   and scene["presentation"].get("not_ai_design") is True
                   and meta.get("lights", {}).get("window_area_lights", 0) >= 5
                   and set(scene["lighting"]["window_opening_ids"])
                   <= {o["object_id"] for o in scene["enclosure"]["openings"]
                       if o["kind"] == "window"}),
              {"window_lights": meta.get("lights", {}).get("window_area_lights"),
               "window_ids": scene["lighting"]["window_opening_ids"],
               "site_verified": scene["presentation"].get("site_verified")})

        # ---------------------------------------------- V3 功能表达 / 陈设分类
        origins = expr_meta.get("origin_counts") or {}
        placeholder_list = (meta.get("assets") or {}).get("placeholders") or []
        check(f"V3-{letter}-01", "对象分为源模型/CC0 表达资产/测试陈设/程序化表达四类",
              all(origins.get(k, 0) > 0 for k in
                  ("source_model", "cc0_expression_asset", "test_staging",
                   "procedural_expression")),
              {"origin_counts": origins,
               "expression_accounting": index["expression_accounting"]})
        check(f"V3-{letter}-02", "display-wing 占位件已替换为程序化展墙，黄色占位盒清零",
              bool("F3" in (expr_meta.get("procedural_expression_objects") or [])
                   and "F3" not in placeholder_list
                   and expr_meta.get("engineering_quantity_effect") == 0),
              {"procedural_objects": expr_meta.get("procedural_expression_objects"),
               "placeholders": placeholder_list,
               "engineering_quantity_effect": expr_meta.get("engineering_quantity_effect")})

        # 生成器级受控对比：拿掉全部测试陈设/程序化表达，工程量与成本必须完全不变
        full = build_package(model, project_id="closeout", option_revision_id="r",
                             settings={"presentation": pres}, finish_scope=scope)
        reduced_pres = copy.deepcopy(pres)
        reduced_pres["furniture"] = [
            f for f in pres["furniture"]
            if f.get("origin_kind") in ("source_model", "cc0_expression_asset")]
        reduced = build_package(model, project_id="closeout", option_revision_id="r",
                                settings={"presentation": reduced_pres}, finish_scope=scope)
        check(f"V3-{letter}-03", "去掉全部测试陈设后：工程量/成本完全不变，平面与场景确实变化",
              bool(full["quantities"] == reduced["quantities"]
                   and full["cost"] == reduced["cost"]
                   and full["plan"] != reduced["plan"]
                   and full["scene"] != reduced["scene"]
                   and qty == reduced["quantities"]),
              {"full_furniture": len(pres["furniture"]),
               "reduced_furniture": len(reduced_pres["furniture"]),
               "quantities_identical": full["quantities"] == reduced["quantities"],
               "cost_identical": full["cost"] == reduced["cost"],
               "plan_changed": full["plan"] != reduced["plan"],
               "scene_changed": full["scene"] != reduced["scene"]})

    passed = sum(1 for c in CHECKS if c["result"] == "observed_pass")
    failed = sum(1 for c in CHECKS if c["result"] == "observed_fail")
    payload = {
        "task_id": "W2-R4 表达收口 V1—V3 专项自动断言",
        "schema_version": "rkd-w2-r4-closeout-checks.v1",
        "executed_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "automatic_assertions": {"checks": CHECKS,
                                 "observed_pass": passed, "observed_fail": failed},
        "manual_visual_review": {
            "status": "reported_in_review_packet",
            "evidence": "deliverables-for-review/roadmap/W2-R4-表达收口/manual-visual-review.md",
            "note": "前后全图/入口·洽谈区局部/打印缩放/窗区与功能区局部由人工看图判定；"
                    "自动断言只做几何、编号、闭合、契约与工程量对账，绝不代表人工目检通过",
        },
        "not_run": ["用户项目阶段2设计生成（阶段1具体版本确认前停止）",
                    "W3/W4", "照度/配光合规计算", "真实现场复核"],
        "external_calls": 0, "tokens": 0, "cost_amount_or_null": None,
        "not_customer_design_approval": True,
    }
    (out / "closeout-checks.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"observed_pass": passed, "observed_fail": failed,
                      "out": str(out / "closeout-checks.json")}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
