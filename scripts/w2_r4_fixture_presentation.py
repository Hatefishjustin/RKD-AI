"""W2-R4 受控样板「表达层人工假设」数据（不是设计、不是现场事实）。

这些墙段、洞口、隔断、材质贴图、家具资产映射、绿植软装、机位与灯光参数
全部由执行者人工编写，只用于补齐制图与渲染表达能力。精确分区、动线、平台、
天花意向与场地边界来自主系统候选修订的 spatial/zones 等对象；本模块不改动
权威模型，不把功能区多边形边界当墙，不把样板参数说成现场实测，也不冒充
「系统模型自动设计」。所有成果页与复核包都带同一段声明。
"""
from __future__ import annotations

import copy
from typing import Any

from rkd_mvp.spatial_presentation import load_asset_inventory

# Studio 目录 catalog_id → 本机 CC0 glTF 资产。None 表示明确占位，不冒充真实家具。
CATALOG_TO_ASSET = {
    "sofa-3p": "sofa_02",
    "dining-table": "dining_table",
    "display-wing": None,
}

ASSUMPTIONS = [
    "周界墙厚 200mm、高 3000mm 为人工测试假设；场地边界本身是标为 "
    "manual_boundary_not_site_verified 的测试参数，未现场复核。",
    "没有从任何功能区多边形边界自动生成墙体；两段隔断是独立显式给出的样板假设。",
    "北向/东向窗洞口的节奏只借用阶段1底图窗带的间距作示意，不作为本项目现场事实；"
    "窗台 900mm、窗高 1800mm、门高 2400mm 均为人工假设。",
    "入口门洞位置与 1800mm 宽度来自模型 boundary.entrance（测试参数），门扇/门套构造未建模。",
    "材质贴图来自 Poly Haven CC0 1.0 六套 1k PBR；贴图与分区 role 的对应是人工样板假设，"
    "只代表材质意向，不是材料规格、产品选型或价源。",
    "家具从 CC0 glTF 目录引用，真实尺寸取 assets/CC0-素材清单.json 的 dimensions_mm；"
    "统一 anchor=center_floor、0° 沿 +X、rotation_deg 逆时针；无对应资产的目录条目"
    "明确留程序化占位。",
    "绿植、器物、补充桌椅是表达层道具（presentation_prop），对象 ID 独立于模型家具，"
    "按分区中心加固定偏移摆放；不宣称是自动设计出的陈设。",
    "机位为 1500mm 人眼高度、24mm 镜头的内部评审视点（人工假设），不是设计决定也不是实测。",
    "中岛台面上的器物显式给出 z_offset_m=0.72（与平台 height_mm 一致），避免与平台实体穿插；"
    "该高度是表达层人工假设，不是展陈设计标高。",
    "贴图 tile 按 1k 贴图约 0.6—2m 重复尺度设置（人工假设），不是材料规格或施工排版。",
    "窗光只从已建模窗洞口发出；灯具点位/灯槽来自模型 ceiling 意向，太阳角度与强度是假设。"
    "未做照度/配光计算，不宣称照度合规。",
    "柱网、洁具、构造节点、消防/疏散/无障碍、实测标高、产品清单、现场照片均缺依据，"
    "一律不编造、不补 0、不在图上冒充。",
]

MISSING = [
    "柱网与结构构件（无依据，不编）",
    "洁具与给排水（无依据，不编）",
    "门窗产品与构造节点（只有洞口假设）",
    "材料规格、产品选型与价源（贴图只是材质意向）",
    "照度/配光计算与合规结论",
    "消防、疏散、无障碍与施工图合规",
    "现场实测标高与实测墙厚",
    "客户可交付的多视角效果图、天花、立面、材料板与汇总 PDF（本批不做）",
]


def _zone_center(polygon_mm: list) -> list[float]:
    xs = [float(p[0]) for p in polygon_mm]
    ys = [float(p[1]) for p in polygon_mm]
    return [round(sum(xs) / len(xs), 1), round(sum(ys) / len(ys), 1)]


def _clamp(point: list[float], width: float, height: float) -> list[float]:
    return [round(min(max(point[0], 800), width - 800), 1),
            round(min(max(point[1], 800), height - 800), 1)]


def build_fixture_presentation(model: dict, layout: str) -> dict:
    """Return an UNNORMALISED raw presentation fixture (validated by the service)."""
    spatial = model["spatial"]
    width, height = [float(v) for v in spatial["origin"]["boundary_mm"]]
    ceiling_mm = float(((spatial["source"].get("site_source") or {})
                        .get("ceiling_mm")) or 3000)
    ent = model["boundary"]["entrance"]
    ent_y = float(ent["point"][1]) * 1000 + float(ent["width"]) * 1000 / 2
    inventory = load_asset_inventory()
    models = inventory["models"]

    def dims(asset_id: str | None):
        return ([round(float(v), 3) for v in models[asset_id]["dimensions_mm"]]
                if asset_id else None)

    W, H = width, height
    walls = [
        {"object_id": "R4-W-S", "segment_mm": [[0, 0], [W, 0]],
         "thickness_mm": 200, "height_mm": ceiling_mm,
         "material_slot": "wall_plaster", "kind": "perimeter",
         "source": "manual_test_assumption:perimeter_enclosure"},
        {"object_id": "R4-W-E", "segment_mm": [[W, 0], [W, H]],
         "thickness_mm": 200, "height_mm": ceiling_mm,
         "material_slot": "wall_plaster", "kind": "perimeter",
         "source": "manual_test_assumption:perimeter_enclosure"},
        {"object_id": "R4-W-N", "segment_mm": [[W, H], [0, H]],
         "thickness_mm": 200, "height_mm": ceiling_mm,
         "material_slot": "wall_plaster", "kind": "perimeter",
         "source": "manual_test_assumption:perimeter_enclosure"},
        {"object_id": "R4-W-W", "segment_mm": [[0, H], [0, 0]],
         "thickness_mm": 200, "height_mm": ceiling_mm,
         "material_slot": "wall_plaster", "kind": "perimeter",
         "source": "manual_test_assumption:perimeter_enclosure"},
    ]
    # 两段隔断是独立显式假设，位置不取自任何 zone 多边形边
    partitions = [
        {"object_id": "R4-P-GLASS", "segment_mm": [[W * 0.72, H * 0.44],
                                                   [W * 0.72, H * 0.72]],
         "thickness_mm": 120, "height_mm": 2700,
         "material_slot": "stone", "kind": "partition",
         "source": "manual_test_assumption:free_standing_partition"},
        {"object_id": "R4-P-SCREEN", "segment_mm": [[W * 0.30, H * 0.20],
                                                    [W * 0.52, H * 0.20]],
         "thickness_mm": 150, "height_mm": 2400,
         "material_slot": "oak", "kind": "partition",
         "source": "manual_test_assumption:free_standing_partition"},
    ]

    openings = [{
        "object_id": "R4-D-ENTRY", "kind": "door", "wall_object_id": "R4-W-W",
        "center_mm": [0.0, round(ent_y, 1)],
        "width_mm": round(float(ent["width"]) * 1000, 1),
        "height_mm": 2400, "sill_mm": 0,
        "source": "model_boundary_entrance:test_parameter",
    }]
    # 阶段1底图窗带节奏仅作示意；坐标按本样板边界换算，不作为现场事实
    north_bands = [[2688, 8154], [8778, 14228], [14867, 20317]]
    east_bands = [[231, 3037], [5742, 8273]]
    for index, (start, end) in enumerate(north_bands, start=1):
        openings.append({
            "object_id": f"R4-WIN-N{index}", "kind": "window",
            "wall_object_id": "R4-W-N",
            "center_mm": [round((start + end) / 2, 1), H],
            "width_mm": round(end - start, 1), "height_mm": 1800, "sill_mm": 900,
            "source": "manual_test_assumption:stage1_window_rhythm_as_pattern_only",
        })
    for index, (start, end) in enumerate(east_bands, start=1):
        openings.append({
            "object_id": f"R4-WIN-E{index}", "kind": "window",
            "wall_object_id": "R4-W-E",
            "center_mm": [W, round((start + end) / 2, 1)],
            "width_mm": round(end - start, 1), "height_mm": 1800, "sill_mm": 900,
            "source": "manual_test_assumption:stage1_window_rhythm_as_pattern_only",
        })
    # 隔断上留一处门洞，使「围合 + 开口」在平面与三维都读同一对象 ID
    openings.append({
        "object_id": "R4-D-PARTITION", "kind": "door",
        "wall_object_id": "R4-P-GLASS",
        "center_mm": [round(W * 0.72, 1), round(H * 0.58, 1)],
        "width_mm": 900, "height_mm": 2200, "sill_mm": 0,
        "source": "manual_test_assumption:opening_in_explicit_partition",
    })

    # 模型自带家具：保留原 object_id，映射到 CC0 资产（缺资产明确占位）
    furniture: list[dict] = []
    for f in spatial["furniture"]:
        asset_id = CATALOG_TO_ASSET.get(str(f["catalog_id"]))
        furniture.append({
            "object_id": f["object_id"], "catalog_id": f["catalog_id"],
            "asset_id": asset_id, "asset_dimensions_mm": dims(asset_id),
            "position_mm": [float(f["x_mm"]), float(f["y_mm"])],
            "rotation_deg": float(f.get("rot") or 0),
            "anchor": "center_floor", "kind": "model_furniture",
            "source": "manual_test_assumption:catalog_to_cc0_asset_mapping",
        })

    # 表达层道具：绿植 / 器物 / 补充桌椅，全部按分区中心加固定偏移，明确标注来源
    by_role: dict[str, list] = {}
    for z in spatial["zones"]:
        by_role.setdefault(str(z.get("role") or "other"), []).append(z)
    props = [
        ("arrival", "potted_plant_01", [1200, 900], 0, 0.0),
        ("island", "ceramic_vase_01", [-1800, 200], 0, 0.72),
        ("island", "wooden_bowl_01", [900, 300], 0, 0.72),
        ("island", "potted_plant_01", [2200, -900], 0, 0.0),
        ("scene", "modern_arm_chair_01", [-1600, 0], 20, 0.0),
        ("scene", "modern_arm_chair_01", [1600, 0], -20, 0.0),
        ("scene", "modern_coffee_table_01", [0, -300], 0, 0.0),
        ("service", "bar_chair_round_01", [-500, 0], 0, 0.0),
        ("service", "bar_chair_round_01", [500, 0], 0, 0.0),
        ("meeting", "dining_chair_02", [-900, 0], 180, 0.0),
        ("meeting", "dining_chair_02", [900, 0], 180, 0.0),
        ("gallery", "round_wooden_table_01", [-1200, 500], 0, 0.0),
        ("gallery", "potted_plant_01", [1200, 500], 0, 0.0),
    ]
    for index, (role, asset_id, offset, rotation, z_offset) in enumerate(props, start=1):
        zones = by_role.get(role) or spatial["zones"][:1]
        zone = zones[index % len(zones)]
        center = _zone_center(zone["polygon_mm"])
        position = _clamp([center[0] + offset[0], center[1] + offset[1]], W, H)
        furniture.append({
            "object_id": f"R4-PROP-{index:02d}", "catalog_id": f"presentation:{asset_id}",
            "asset_id": asset_id, "asset_dimensions_mm": dims(asset_id),
            "position_mm": position, "rotation_deg": rotation,
            "z_offset_m": z_offset,
            "anchor": "center_floor", "kind": "presentation_prop",
            "source": "manual_test_assumption:presentation_prop_not_model_design",
        })

    materials = [
        {"material_id": "mat-floor-microcement", "slot": "floor_microcement",
         "name": "微水泥地坪", "hex": "#b9b3a8", "tile": 0.50,
         "tint": [0.62, 0.60, 0.57], "rough": 0.42, "normal_strength": 0.22,
         "zone_roles": ["gallery"], "source": "manual_test_assumption:material_intent"},
        {"material_id": "mat-wall-plaster", "slot": "wall_plaster",
         "name": "乳胶漆墙面", "hex": "#e6e2d9", "tile": 0.50,
         "tint": [1.10, 1.08, 1.05], "rough": 0.85, "normal_strength": 0.22,
         "zone_roles": [], "source": "manual_test_assumption:material_intent"},
        {"material_id": "mat-oak", "slot": "oak",
         "name": "白橡木饰面", "hex": "#c8a06a", "tile": 1.60,
         "tint": [1.22, 1.18, 1.12], "rough": 0.58, "normal_strength": 0.30,
         "zone_roles": ["arrival"], "source": "manual_test_assumption:material_intent"},
        {"material_id": "mat-walnut", "slot": "walnut",
         "name": "玫瑰木饰面", "hex": "#7a5238", "tile": 1.40,
         "tint": [0.52, 0.42, 0.35], "rough": 0.52, "normal_strength": 0.32,
         "zone_roles": ["scene"], "source": "manual_test_assumption:material_intent"},
        {"material_id": "mat-stone", "slot": "stone",
         "name": "石材", "hex": "#d7d2c8", "tile": 0.90,
         "tint": [1.05, 1.02, 0.98], "rough": 0.30, "normal_strength": 0.18,
         "zone_roles": ["island", "service"], "source": "manual_test_assumption:material_intent"},
        {"material_id": "mat-fabric", "slot": "fabric",
         "name": "羊毛圈绒", "hex": "#c8bba6", "tile": 1.00,
         "tint": [1.00, 0.92, 0.80], "rough": 0.70, "normal_strength": 0.45,
         "zone_roles": ["meeting"], "source": "manual_test_assumption:material_intent"},
    ]

    # 相机：入口内侧人眼视点，看向中岛/最大分区（同一套规则用于两种布局）
    island = next((z for z in spatial["zones"] if z.get("role") == "island"),
                  max(spatial["zones"], key=lambda z: len(z["polygon_mm"])))
    target = _zone_center(island["polygon_mm"])
    cameras = [{
        "object_id": "R4-CAM-01",
        "position_mm": [1200.0, round(ent_y, 1)],
        "target_mm": target,
        "eye_height_mm": 1500, "lens_mm": 24,
        "source": "manual_test_assumption:eye_level_review_camera",
    }]

    ceiling = spatial.get("ceiling") or {}
    fixtures = [{
        "object_id": str(fx.get("id") or f"R4-L{index}"),
        "position_mm": [float(fx.get("x") or 0), float(fx.get("y") or 0)],
        "type": str(fx.get("type") or "downlight"),
        "kelvin": float(fx.get("kelvin") or 3000),
        "source": "model_ceiling_fixtures:intent_only",
    } for index, fx in enumerate(ceiling.get("fixtures") or [], start=1)]
    coves = [{
        "object_id": str(cove.get("id") or f"R4-CV{index}"),
        "polygon_mm": copy.deepcopy(cove.get("polygon") or []),
        "kelvin": float(cove.get("kelvin") or 3000),
        "source": "model_ceiling_coves:intent_only",
    } for index, cove in enumerate(ceiling.get("coves") or [], start=1)]
    lighting = {
        "window_opening_ids": [o["object_id"] for o in openings
                               if o["kind"] == "window"],
        "fixtures": fixtures, "coves": coves,
        "sun": {"azimuth_deg": 200, "elevation_deg": 38, "energy": 2.0},
    }

    return {
        "unit": "mm",
        "declared_by": "executor_manual_fixture_w2_r4",
        "declaration": (f"W2-R4 布局 {layout} 表达层人工测试假设；用于平面与三维同源表达，"
                        "不是设计成果、不是现场事实、不是 AI 自动设计"),
        "site_verified": False,
        "not_ai_design": True,
        "asset_manifest_sha256": inventory["sha256"],
        "walls": walls, "partitions": partitions, "openings": openings,
        "furniture": furniture, "materials": materials, "cameras": cameras,
        "lighting": lighting,
        "assumptions": ASSUMPTIONS, "missing": MISSING,
    }
