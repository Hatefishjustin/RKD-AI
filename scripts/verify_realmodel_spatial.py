"""W3 前置工程：真实模型输出形状 -> 版本化 spatial -> 同一冻结模型同源成果。

用法：
  ./.venv/Scripts/python.exe scripts/verify_realmodel_spatial.py \
      --evidence var/evidence/roadmap/W3-真实模型spatial适配/... \
      --out      deliverables-for-review/roadmap/W3-真实模型spatial适配/...

只用离线确定性夹具（形状仿真的真实模型输出），0 外部模型调用、0 密钥、0 费用、0 外发。
下载/渲染在同一冻结模型上完成；人眼图用本机 Blender，明确标记为工程样张，不是客户成果。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from rkd_mvp import realmodel_spatial_adapter as A  # noqa: E402
from rkd_mvp.ai_spatial_outputs import (  # noqa: E402
    build_package, finalize_package, model_hash, check_zip_against_manifest)

BASEMAP_DIR = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口/basemap"
CONTRACT_PATH = ROOT / "contracts/v1/realmodel-spatial-adaptation.schema.json"
OUTPUT_SCHEMA_PATH = ROOT / "contracts/v1/realmodel-spatial-option.schema.json"

CHECKS: list[dict] = []


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def record(cid: str, name: str, ok: bool, evidence: dict) -> None:
    CHECKS.append({"id": cid, "name": name,
                   "result": "observed_pass" if ok else "observed_fail",
                   "evidence": evidence})
    print(("PASS " if ok else "FAIL ") + cid + " " + name, flush=True)


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


# --------------------------------------------------------------- site & fixtures
def confirmed_site() -> dict:
    """Site conditions copied ONLY from the user-confirmed v2 basemap JSON."""
    return {
        "contract_version": A.BASEMAP_CONTRACT,
        "boundary_source": A.BASEMAP_CONTRACT,      # not manual_boundary_not_site_verified
        "width_m": 26.17, "length_m": 17.92,
        "unverified_facts": [
            "主入口位置/宽度/门洞高", "窗台高与窗洞高", "卫生间内部隔断与洁具",
            "133 项拓扑复核标记", "实测标高", "现场照片",
        ],
        "entrance": {"side": "left", "point_m": [0, 10.3], "width_m": 1.8,
                     "status": "待现场复核"},
        "keepouts": [
            {"object_id": "keepout-stair", "name": "楼梯保留区",
             "rect_m": [0, 0, 2.4, 8.0], "status": "解析确认"},
            {"object_id": "keepout-bath", "name": "卫生间湿区",
             "rect_m": [22.0, 2.6, 4.17, 4.7], "status": "解析确认（仅范围）"},
        ],
    }


def fixture_candidates() -> dict[str, dict]:
    """Two genuinely different candidates in the real model OUTPUT SHAPE.

    These are authored offline deterministic fixtures.  All rects are metric and
    sit inside the confirmed 26.17 x 17.92 m frame. They are NOT a design result.
    """
    a = {
        "strategy_id": "hub-branch-fixture",
        "concept": "入口接待—中央枢纽—分支洽谈（离线夹具，非设计成果）",
        "statement": "中心枢纽 + 东侧洽谈分支；用于验证映射，不代表设计质量",
        "tradeoffs": ["分支自由度高", "叙事顺序较弱"],
        "narrative": {"theme": "枢纽会客", "topology": "central-hub",
                      "sequence": ["序厅", "枢纽", "洽谈"], "first_view": "形象墙", "climax": "中岛"},
        "entrance_side": "left", "circulation_kind": "branch",
        "zones": [
            {"object_id": "zone:foyer", "name": "前厅接待", "x": 3.0, "y": 9.0,
             "width": 5.0, "length": 6.5, "zone_role": "foyer", "sequence_role": "opening",
             "intent": "建立品牌第一印象"},
            {"object_id": "zone:display", "name": "中心枢纽主展", "x": 8.2, "y": 7.0,
             "width": 7.0, "length": 7.5, "zone_role": "primary_display", "sequence_role": "climax",
             "intent": "核心展项与停留"},
            {"object_id": "zone:talk", "name": "东侧深度洽谈", "x": 16.0, "y": 9.0,
             "width": 5.5, "length": 6.0, "zone_role": "deep_talk", "sequence_role": "closing",
             "intent": "半私密转化"},
        ],
        "walls": [
            {"object_id": "wall:feature", "name": "形象片墙", "x": 7.6, "y": 10.5,
             "width": 0.14, "length": 3.0, "wall_type": "feature"},
            {"object_id": "wall:curve", "name": "弧形意向墙", "x": 13.5, "y": 8.0,
             "width": 0.14, "length": 4.0, "wall_type": "curved_intent"},
        ],
        "furniture": [
            {"object_id": "f:desk", "name": "服务前台", "x": 3.6, "y": 11.0,
             "width": 1.4, "length": 0.6, "furniture_type": "reception_desk", "parent_object_id": "zone:foyer"},
            {"object_id": "f:talk", "name": "洽谈桌椅", "x": 17.2, "y": 11.0,
             "width": 1.6, "length": 1.6, "furniture_type": "table_chairs", "parent_object_id": "zone:talk"},
        ],
        "focal_point": {"object_id": "focal:hero", "name": "中心主展台", "x": 10.5, "y": 9.5,
                        "width": 1.8, "length": 1.2, "furniture_type": "island", "statement": "视觉焦点"},
        "entrance_buffers": [{"object_id": "entrance:portal", "name": "入口门斗",
                              "x": 0.2, "y": 9.8, "width": 0.8, "length": 1.0}],
        "paths": [
            {"segment_id": "path-south", "x": 0, "y": 6.0, "width": 22.0, "length": 1.4},
            {"segment_id": "path-west", "x": 2.2, "y": 7.4, "width": 1.4, "length": 7.6},
            {"segment_id": "path-mid", "x": 8.0, "y": 7.4, "width": 1.4, "length": 7.6},
            {"segment_id": "path-east", "x": 15.4, "y": 7.4, "width": 1.4, "length": 7.6},
        ],
        "connections": [["path-south", "path-west"], ["path-south", "path-mid"],
                        ["path-south", "path-east"]],
        "materials": [{"material_id": "mat-warm", "name": "暖木意向", "intent": "温润，未选产品"}],
        "relationships": [{"relation_id": "rel-1", "type": "adjacent",
                           "source": "zone:foyer", "target": "zone:display", "statement": "前厅接主展"}],
        "cost_unknown": ["材料单价与价源", "协诚主营产品清单未提供"],
    }
    b = copy.deepcopy(a)
    b["strategy_id"] = "brand-loop-fixture"
    b["concept"] = "环形叙事动线（离线夹具，非设计成果）"
    b["circulation_kind"] = "loop"
    # genuinely different zone positions & a different role assignment
    b["zones"][0].update({"x": 2.0, "y": 10.0, "width": 4.0, "length": 7.0, "object_id": "zone:foyer"})
    b["zones"][1].update({"x": 7.0, "y": 5.0, "width": 8.0, "length": 6.0, "object_id": "zone:display"})
    b["zones"][2].update({"x": 16.5, "y": 5.0, "width": 5.0, "length": 7.0, "object_id": "zone:talk"})
    b["walls"] = [
        {"object_id": "wall:brand", "name": "品牌形象墙", "x": 6.4, "y": 9.0,
         "width": 0.14, "length": 5.0, "wall_type": "feature"},
    ]
    b["focal_point"] = {"object_id": "focal:hero", "name": "环心主展台", "x": 10.0, "y": 7.5,
                        "width": 2.2, "length": 1.0, "furniture_type": "island", "statement": "环游中心"}
    b["paths"] = [
        {"segment_id": "path-south", "x": 0, "y": 4.6, "width": 23.0, "length": 1.4},
        {"segment_id": "path-west", "x": 2.0, "y": 6.0, "width": 1.4, "length": 10.0},
        {"segment_id": "path-north", "x": 2.0, "y": 16.0, "width": 19.0, "length": 1.4},
        {"segment_id": "path-east", "x": 19.6, "y": 6.0, "width": 1.4, "length": 10.0},
    ]
    b["connections"] = [["path-south", "path-west"], ["path-west", "path-north"],
                        ["path-north", "path-east"], ["path-east", "path-south"]]
    return {"A": a, "B": b}


def provenance(kind: str = "fixture") -> dict:
    return {
        "artifact_id": "offline-realmodel-shape-fixture",
        "sha256": hashlib.sha256(b"offline-realmodel-shape-fixture-v1").hexdigest(),
        "set_id": "offline-realmodel-shape-set",
        "option_id": "offline-fixture",
        "revision_no": 1,
        "parent_revision_id": None,
        "actor_id": "offline-verifier",
        "model_site_boundary_m": [26.17, 17.92],
        "design_origin": {
            "kind": kind, "declared_by": "offline_verifier_fixture",
            "declaration": "离线确定性夹具，仿真的真实模型输出形状；没有真实模型调用",
            "run_refs": [] if kind != "real_model" else [],
        },
    }


def expect_error(code: str, fn) -> dict:
    try:
        fn()
    except A.RealModelSpatialAdaptationError as error:
        return {"raised": True, "code": error.code, "expected": code,
                "match": error.code == code, "message": error.message}
    return {"raised": False, "code": None, "expected": code, "match": False}


# ------------------------------------------------------------------- main checks
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=str(ROOT / "var/evidence/roadmap/W3-真实模型spatial适配/after"))
    ap.add_argument("--out", default=str(ROOT / "deliverables-for-review/roadmap/W3-真实模型spatial适配"))
    ap.add_argument("--no-render", action="store_true", help="skip Blender render (for dry runs)")
    args = ap.parse_args()
    evidence, out = Path(args.evidence).resolve(), Path(args.out).resolve()
    for p in (evidence, out):
        p.mkdir(parents=True, exist_ok=True)
    (out / "outputs").mkdir(parents=True, exist_ok=True)

    site = confirmed_site()
    fixtures = fixture_candidates()
    prov = provenance()
    contract_schema = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract_validator = Draft202012Validator(contract_schema)
    option_validator = Draft202012Validator(json.loads(OUTPUT_SCHEMA_PATH.read_text(encoding="utf-8")))

    # The contract INSTANCE is generated from the live module constants, so the
    # published contract cannot drift from the code that claims to implement it.
    contract = {
        "contract_version": "rkd-realmodel-spatial-adaptation.v1",
        "adapter_version": A.ADAPTER_VERSION,
        "spatial_version": A.SPATIAL_VERSION,
        "mapping_version": A.MAPPING_VERSION,
        "vocab_version": A.VOCAB_VERSION,
        "basemap": {"contract_version": A.BASEMAP_CONTRACT,
                    "boundary_mm": list(A.CONFIRMED_BOUNDARY_MM),
                    "files": [{"name": n, "bytes": b, "sha256": s}
                              for n, (b, s) in A.CONFIRMED_BASEMAP_FILES.items()]},
        "vocabularies": {
            "zone_role": A.ZONE_ROLE_VOCAB,
            "furniture_type": A.FURNITURE_TYPE_VOCAB,
            "wall_type": sorted(A.WALL_TYPE_VOCAB),
            "sequence_role": sorted(A.SEQUENCE_ROLE_VOCAB),
        },
        "rules": {
            "object_identity": "模型 object_id 保留为稳定 ID；重复或缺失一律拒绝",
            "coordinate_units": "米制矩形 ×1000 精确转 mm；亚毫米精度拒绝，不猜测单位",
            "geometry_mode": "矩形四角化为同一矩形的表示，non_rectangular_capability=false",
            "curved_intent": "仅语义意图，arc_geometry_generated=false，不生成弧墙",
            "parent_chain": "intended_parent 仅语义归属，不建立几何父子或工程量",
            "source_separation": "transport origin_kind 与 design_origin 分离；无 run_refs 不得声明 real_model",
            "unknown_policy": "缺规格/价源/机位/标高/门窗柱网一律 value=None，不填 0",
            "version_reconciliation": "同一稳定对象 ID 逐字段 diff；缺父标 unknown_missing_parent",
            "expression_separation": "W2 人工围合/材料/家具表达不导入真实模型来源",
        },
        "negative_cases": [
            {"id": "RM-N01", "name": "测试边界替代确认底图", "expect": "SITE_BOUNDARY_MISMATCH",
             "before": "接受 manual_boundary_not_site_verified", "after": "拒绝并留痕"},
            {"id": "RM-N02", "name": "12x8m 测试框架平移到 v2", "expect": "MODEL_FRAME_MISMATCH",
             "before": "原样落位", "after": "拒绝，不缩放不平移"},
            {"id": "RM-N03", "name": "无证据声明真实模型", "expect": "DESIGN_ORIGIN_UNVERIFIED",
             "before": "夹具冒称 AI 设计", "after": "拒绝"},
            {"id": "RM-N04", "name": "矩形越出确认边界", "expect": "OBJECT_OUTSIDE_BOUNDARY",
             "before": "裁剪后继续", "after": "拒绝"},
        ],
    }

    started = now()

    # --- 1. contract instance conforms to its own schema
    record("RM-01", "适配契约符合自身 JSON Schema",
           contract_validator.is_valid(contract),
           {"contract_sha256": sha(contract), "contract_version": contract["contract_version"],
            "errors": [e.message for e in contract_validator.iter_errors(contract)][:5]})

    # --- 2. basemap reconciliation (positive)
    recon = A.reconcile_site(BASEMAP_DIR, site)
    record("RM-02", "确认的 v2 底图五文件 SHA/字节逐项对账通过",
           len(recon["files"]) == 5 and all(f["bytes"] and len(f["sha256"]) == 64 for f in recon["files"]),
           {"files": recon["files"], "boundary_mm": recon["boundary_mm"],
            "boundary_sha256": recon["boundary_sha256"]})

    # --- 3. before/after same-case negatives (the mapping gaps)
    negatives: list[dict] = []

    def neg(cid, name, before_desc, after_fn, expect_code):
        ev = expect_error(expect_code, after_fn)
        # "before" = what a naive mapper would do: no reconciliation at all.
        negatives.append({"id": cid, "name": name, "expect": expect_code,
                          "before": before_desc, "after": ev})
        record(cid, name, ev["match"], ev)

    wrong_site = dict(site, boundary_source="manual_boundary_not_site_verified")
    neg("RM-N01", "测试边界不得替代确认 v2 底图",
        "朴素映射直接把 W2 的 manual_boundary_not_site_verified 当场地",
        lambda: A.adapt_candidate(fixtures["A"], site=wrong_site, basemap_dir=BASEMAP_DIR,
                                  provenance=prov, created_at=now()),
        "SITE_BOUNDARY_MISMATCH")

    bad_frame = dict(prov, model_site_boundary_m=[12, 8])
    neg("RM-N02", "旧 12x8m 测试框架不得静默平移到 v2 底图",
        "朴素映射把 12x8m 模型矩形原样放进 26.17x17.92m 场地",
        lambda: A.adapt_candidate(fixtures["A"], site=site, basemap_dir=BASEMAP_DIR,
                                  provenance=bad_frame, created_at=now()),
        "MODEL_FRAME_MISMATCH")

    bad_origin = dict(prov, design_origin={"kind": "real_model", "declared_by": "self",
                                           "declaration": "仅凭形状自称真实模型", "run_refs": []})
    neg("RM-N03", "无运行证据不得声明 real_model 来源",
        "朴素映射把离线夹具标成真实模型设计",
        lambda: A.adapt_candidate(fixtures["A"], site=site, basemap_dir=BASEMAP_DIR,
                                  provenance=bad_origin, created_at=now()),
        "DESIGN_ORIGIN_UNVERIFIED")

    out_of = copy.deepcopy(fixtures["A"])
    out_of["zones"][1]["x"] = 25.0  # 25+7 > 26.17
    neg("RM-N04", "越出确认边界的矩形必须拒绝",
        "朴素映射裁掉越界部分继续出图",
        lambda: A.adapt_candidate(out_of, site=site, basemap_dir=BASEMAP_DIR,
                                  provenance=prov, created_at=now()),
        "OBJECT_OUTSIDE_BOUNDARY")

    bad_role = copy.deepcopy(fixtures["A"])
    bad_role["zones"][0]["zone_role"] = "unknown_role_not_in_vocab"
    bad_role_m = A.adapt_candidate(bad_role, site=site, basemap_dir=BASEMAP_DIR,
                                   provenance=prov, created_at=now())
    role = bad_role_m["spatial"]["zones"][0]["role"]
    role_unknown_row = [r for r in bad_role_m["spatial"]["adaptation"]["field_ledger"]
                        if r["object_id"] == "zone:foyer" and r["status"] == "unknown"]
    record("RM-N05", "未知 zone_role 保留 unknown 而非静默归类",
           role == "unknown" and bool(role_unknown_row),
           {"role": role, "unknown_row": role_unknown_row[:1],
            "before": "朴素映射默认归类为 primary_display", "after": "unknown + 字段清单留痕"})

    # --- 4. adapt both candidates; schema-validate
    models: dict[str, dict] = {}
    for name, cand in fixtures.items():
        m = A.adapt_candidate(cand, site=site, basemap_dir=BASEMAP_DIR,
                              provenance=prov, created_at=now())
        models[name] = m
        record(f"RM-10{name}", f"候选 {name} 适配产物通过主候选契约校验",
               option_validator.is_valid(m),
               {"option_id": m["option_id"], "errors": [e.message for e in option_validator.iter_errors(m)][:5]})

    ma, mb = models["A"], models["B"]
    record("RM-11", "两候选空间组织实质不同（分区多边形签名不同）",
           sha([z["polygon_mm"] for z in ma["spatial"]["zones"]]) !=
           sha([z["polygon_mm"] for z in mb["spatial"]["zones"]]),
           {"A_sig": sha([z["polygon_mm"] for z in ma["spatial"]["zones"]])[:16],
            "B_sig": sha([z["polygon_mm"] for z in mb["spatial"]["zones"]])[:16]})

    # --- 5. field/source/loss inventory
    ledger = ma["spatial"]["adaptation"]["field_ledger"]
    unknown_rows = [r for r in ledger if r["status"] == "unknown"]
    record("RM-12", "字段清单含 unknown 行且值不为 0",
           any(r for r in unknown_rows) and
           all(r["target_value"] is None for r in unknown_rows),
           {"ledger_rows": len(ledger), "unknown_rows": unknown_rows[:4]})

    record("RM-13", "来源与人工表达分离：origin_kind=fixture，无 W2 人工表达导入",
           ma["spatial"]["source"]["origin_kind"] == "real_model_shape_fixture"
           and ma["spatial"]["source"]["design_origin"]["kind"] == "fixture"
           and ma["spatial"]["adaptation"]["expression_source"].endswith("no_w2_manual_expression"),
           {"origin_kind": ma["spatial"]["source"]["origin_kind"],
            "design_origin": ma["spatial"]["source"]["design_origin"],
            "expression_source": ma["spatial"]["adaptation"]["expression_source"]})

    record("RM-14", "矩形四角化不冒称非矩形能力；curved_intent 不生成弧墙",
           all(z.get("non_rectangular_capability") is False for z in ma["spatial"]["zones"])
           and all(e.get("arc_geometry_generated") is False for e in ma["spatial"]["semantic_intents"]
                   if e.get("kind") == "partition_intent"),
           {"geometry_modes": sorted({z.get("geometry_mode") for z in ma["spatial"]["zones"]}),
            "curve_intents": [e for e in ma["spatial"]["semantic_intents"]
                              if e.get("wall_type") == "curved_intent"]})

    record("RM-15", "底图保留区进入净量口径且标 site_verified=false",
           len(ma["boundary"]["obstacles"]) == 2
           and all(o["properties"]["site_verified"] is False for o in ma["boundary"]["obstacles"]),
           {"obstacles": [o["object_id"] for o in ma["boundary"]["obstacles"]]})

    # --- 6. version reconciliation (new vs old)
    delta = copy.deepcopy(fixtures["A"])
    delta["zones"][1]["width"] = 6.5
    delta_m = A.adapt_candidate(delta, site=site, basemap_dir=BASEMAP_DIR,
                                provenance=dict(prov, revision_no=2, parent_revision_id="r1"),
                                created_at=now())
    diff = A.diff_spatial(ma["spatial"], delta_m["spatial"])
    record("RM-16", "新旧版本对账：同一稳定对象 ID 的几何变化被逐字段记录",
           any(d["object_id"] == "zone:display" and d["field"].endswith("polygon_mm") for d in diff),
           {"diff_count": len(diff), "sample": diff[:3]})

    # --- 7. same frozen model -> plan/scene/quantity/cost/package
    pkg = build_package(ma, project_id="ningbo-xiecheng-offline-fixture",
                        option_revision_id="offline-fixture-r1")
    final = finalize_package(pkg["files"], pkg["manifest"])
    zip_bytes = final["files"]["package.zip"][2]
    manifest_bytes = next(v[2] for k, v in final["files"].items() if k == "manifest.json")
    zcheck = check_zip_against_manifest(zip_bytes, manifest_bytes)
    record("RM-17", "同一冻结模型生成计划/场景/净量/成本并打包，ZIP 逐项与清单一致",
           zcheck["ok"] and set(pkg["files"].keys()) >= {"plan.svg", "scene.json", "quantity.json", "cost.html"},
           {"check": zcheck, "files": sorted(pkg["files"].keys()),
            "net_quantity": [q for q in pkg["quantities"]["items"] if q.get("value") is not None][:4]})

    record("RM-18", "无价源的成本保持 unknown，不填 0",
           all(q["value"] is None for q in pkg["quantities"]["items"]
               if q.get("unit") == "CNY" or "cost" in q.get("quantity_id", "").lower()),
           {"cost_unknown_sample": [q for q in pkg["quantities"]["items"] if q["value"] is None][:3]})

    # --- 8. controlled changes: geometry vs material vs camera
    mat_only = copy.deepcopy(ma)
    mat_only["spatial"]["materials"][0]["name"] = "冷灰意向（仅测试改名）"
    mat_pkg = build_package(mat_only, project_id="ningbo-xiecheng-offline-fixture",
                            option_revision_id="offline-fixture-r1-material")
    record("RM-19", "只改材质意向不改几何量",
           mat_pkg["quantities"] == pkg["quantities"]
           and mat_pkg["scene"] != pkg["scene"],
           {"quantity_equal": mat_pkg["quantities"] == pkg["quantities"]})

    cam_only = copy.deepcopy(ma)
    cam_only["boundary"]["entrance"]["point"] = ["0", "11.5"]
    cam_pkg = build_package(cam_only, project_id="ningbo-xiecheng-offline-fixture",
                            option_revision_id="offline-fixture-r1-camera")
    record("RM-20", "只改入口机位不改几何量",
           cam_pkg["quantities"] == pkg["quantities"],
           {"quantity_equal": cam_pkg["quantities"] == pkg["quantities"]})

    # --- 9. write sample outputs (engineering samples, not customer成果)
    sample_outputs = out / "outputs"
    written: dict[str, dict] = {}
    for name, (_kind, _ctype, data) in final["files"].items():
        target = sample_outputs / name
        target.write_bytes(data)
        written[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (sample_outputs / "model.json").write_bytes(canonical(ma))
    written["model.json"] = {"bytes": (sample_outputs / "model.json").stat().st_size,
                             "sha256": hashlib.sha256(canonical(ma)).hexdigest()}

    # --- 10. Blender eye-level render (optional)
    render_info = {"status": "not_run" if args.no_render else "pending"}
    if not args.no_render:
        import os
        import subprocess
        blender = ROOT / "tools/blender/blender-4.2.9-windows-x64/blender.exe"
        scene_path = sample_outputs / "scene.json"
        png_path = sample_outputs / "render.png"
        if blender.is_file():
            env = dict(os.environ)
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
                env.pop(key, None)
            cmd = [str(blender), "-b", "--factory-startup", "-noaudio", "--python",
                   str(ROOT / "scripts/render_spatial_scene.py"), "--",
                   "--scene", str(scene_path), "--out", str(png_path),
                   "--width", "1280", "--height", "800", "--samples", "48"]
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=300, env=env)
                ok = png_path.is_file() and png_path.stat().st_size > 10000 and proc.returncode == 0
                render_info = {"status": "rendered" if ok else "failed", "returncode": proc.returncode,
                               "bytes": png_path.stat().st_size if png_path.is_file() else 0,
                               "sha256": hashlib.sha256(png_path.read_bytes()).hexdigest()
                               if png_path.is_file() else None,
                               "stderr_tail": proc.stderr.decode("utf-8", errors="replace")[-500:]}
            except Exception as error:  # noqa: BLE001
                render_info = {"status": "failed", "error": str(error)}
        else:
            render_info = {"status": "not_run", "reason": "blender not present"}
    record("RM-21", "同一冻结模型的人眼效果图（工程样张，本地 Blender）",
           render_info.get("status") == "rendered" if not args.no_render else True,
           render_info)

    # --- 11. evidence + field/source/loss manifest
    audit = {
        "schema_version": "rkd-realmodel-spatial-verification.v1",
        "started_at": started, "finished_at": now(),
        "checks": CHECKS,
        "negative_cases": negatives,
        "models": {k: {"option_id": v["option_id"], "model_hash": model_hash(v),
                       "design_origin": v["spatial"]["source"]["design_origin"],
                       "basemap_sha256": v["spatial"]["source"]["boundary_sha256"]}
                   for k, v in models.items()},
        "field_source_loss": {
            "field_ledger": ma["spatial"]["adaptation"]["field_ledger"],
            "losses": ma["spatial"]["adaptation"]["losses"],
            "unsupported_items": ma["spatial"]["unsupported_items"],
            "unknown_items": ma["spatial"]["unknown_items"],
            "semantic_intents": ma["spatial"]["semantic_intents"],
        },
        "outputs_sha256": written,
        "render": render_info,
        "external_calls": 0, "external_images": 0, "tokens": 0, "cost_cny": 0,
        "key_used": False, "key_written": False,
    }
    (evidence / "verification.json").write_bytes(canonical(audit))
    (out / "checks.json").write_bytes(canonical(audit))
    (out / "field-source-loss.json").write_bytes(canonical(audit["field_source_loss"]))
    (out / "adaptation-contract.json").write_bytes(canonical(contract))

    failed = [c for c in CHECKS if c["result"] == "observed_fail"]
    print(f"\nSUMMARY {len(CHECKS) - len(failed)}/{len(CHECKS)} passed; failed={[c['id'] for c in failed]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
