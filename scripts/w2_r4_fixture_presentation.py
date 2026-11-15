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
    "V2：玻璃为透明透射材质 + 窗框/窗洞深度；窗外是明确标注的本地程序化天空渐变"
    "（淡蓝天光 + 暖灰地平线带），不是现场照片或真实外景。",
    "V2：木饰面与地面的纹理比例、分缝与踢脚收边是版本化表达输入里的示意参数，"
    "不是材料规格、产品选型或施工排版。",
    "V3：display-wing 占位件替换为程序化展墙；新增展台/器物/品牌板/配套座椅"
    "是测试陈设（人工表达假设），保留对象 ID、位置与尺寸，不进工程量、不暗改源方案。",
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

    # 模型自带家具：保留原 object_id / 位置 / 朝向，映射到 CC0 资产。
    # V3：display-wing 没有对应 CC0 资产，替换为明确标注的程序化展墙，
    # 不再是黄色占位盒；对象 ID 与源模型位置一律不改，不暗改源方案。
    furniture: list[dict] = []
    for f in spatial["furniture"]:
        asset_id = CATALOG_TO_ASSET.get(str(f["catalog_id"]))
        item = {
            "object_id": f["object_id"], "catalog_id": f["catalog_id"],
            "asset_id": asset_id, "asset_dimensions_mm": dims(asset_id),
            "position_mm": [float(f["x_mm"]), float(f["y_mm"])],
            "rotation_deg": float(f.get("rot") or 0),
            "anchor": "center_floor", "kind": "model_furniture",
            "source": "manual_test_assumption:catalog_to_cc0_asset_mapping",
            "origin_kind": "source_model",
        }
        if str(f["catalog_id"]) == "display-wing":
            item.update({
                "asset_dimensions_mm": [450.0, 2300.0, 2400.0],
                "origin_kind": "procedural_expression",
                "expression_note": "程序化展墙（木饰面展板 + 展品托板）：替代原占位盒；"
                                   "人工表达假设，非 CC0 资产、非源方案对象，位置/ID 沿用源模型",
            })
        furniture.append(item)

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
            "origin_kind": "cc0_expression_asset",
            "source": "manual_test_assumption:presentation_prop_not_model_design",
        })

    # ---------------------------------------------------------------- V3 陈设
    # 全部按本布局的动线/分区中心派生位置（不是复制固定样板坐标），
    # 明确标为测试陈设或程序化表达，不进入工程量、不称 AI 设计。
    by_role_local = by_role
    route = (spatial["circulation"][0]["path_mm"]
             if spatial.get("circulation") else [[W * 0.3, H * 0.5], [W * 0.7, H * 0.5]])
    ped_specs = [
        (route[min(1, len(route) - 1)], "ceramic_vase_01"),
        (route[min(2, len(route) - 1)], "wooden_bowl_01"),
        (route[min(3, len(route) - 1)], "ceramic_vase_01"),
    ]
    for i, (anchor_pt, obj_asset) in enumerate(ped_specs, start=1):
        px = _clamp([float(anchor_pt[0]), float(anchor_pt[1]) - 2500], W, H)
        furniture.append({
            "object_id": f"R4-STG-PED-{i:02d}",
            "catalog_id": "presentation:display_pedestal",
            "asset_id": None, "asset_dimensions_mm": [900.0, 600.0, 750.0],
            "origin_kind": "procedural_expression",
            "expression_note": "程序化样板展台（石材台面 + 木饰面基座）；"
                               "人工表达假设，不是源方案对象、不是产品选型",
            "position_mm": px, "rotation_deg": 0.0, "z_offset_m": 0.0,
            "anchor": "center_floor", "kind": "test_staging_pedestal",
            "source": "manual_test_assumption:display_sequence_along_circulation",
        })
        furniture.append({
            "object_id": f"R4-STG-OBJ-{i:02d}",
            "catalog_id": f"presentation:{obj_asset}",
            "asset_id": obj_asset, "asset_dimensions_mm": dims(obj_asset),
            "origin_kind": "test_staging",
            "position_mm": px, "rotation_deg": 0.0, "z_offset_m": 0.75,
            "anchor": "center_floor", "kind": "test_staging_object",
            "source": "manual_test_assumption:sample_exhibit_not_client_product",
        })
    arrival_zone = (by_role_local.get("arrival") or spatial["zones"][:1])[0]
    ac = _zone_center(arrival_zone["polygon_mm"])
    furniture.append({
        "object_id": "R4-STG-BRAND-01", "catalog_id": "presentation:brand_panel",
        "asset_id": None, "asset_dimensions_mm": [2400.0, 120.0, 1800.0],
        "origin_kind": "procedural_expression",
        "expression_note": "品牌标识板为占位表达（抽象色块，不含客户品牌、不含文字设计）；"
                           "人工表达假设，不是 AI 自动设计成果",
        "position_mm": _clamp([ac[0] + 300, ac[1] + 1500], W, H),
        "rotation_deg": 0.0, "z_offset_m": 0.0,
        "anchor": "center_floor", "kind": "test_staging_brand_panel",
        "source": "manual_test_assumption:brand_content_placeholder",
    })
    gallery_zone = (by_role_local.get("gallery") or spatial["zones"][:1])[0]
    gc = _zone_center(gallery_zone["polygon_mm"])
    for i, (dx, seat_rot) in enumerate([(-1500, 90), (1500, -90)], start=1):
        furniture.append({
            "object_id": f"R4-STG-SEAT-{i:02d}",
            "catalog_id": "presentation:modern_arm_chair_01",
            "asset_id": "modern_arm_chair_01",
            "asset_dimensions_mm": dims("modern_arm_chair_01"),
            "origin_kind": "test_staging",
            "position_mm": _clamp([gc[0] + dx, gc[1] - 300], W, H),
            "rotation_deg": seat_rot, "z_offset_m": 0.0,
            "anchor": "center_floor", "kind": "test_staging_seat",
            "source": "manual_test_assumption:group_isolated_table_into_readable_setting",
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

    # ------------------------------------------------ V2/V3 有版本的表达输入
    # 材质纹理比例/分缝/收边、窗玻璃与窗外环境、陈设分类都在这里版本化，
    # 渲染器只读该输入，不手工改像素、不把参数写死在渲染脚本里。
    expression = {
        "schema_version": "rkd-spatial-expression.v1",
        "declared_by": "executor_manual_fixture_w2_r4_closeout",
        "declaration": "V2 窗光/材质与 V3 陈设的表达输入；人工测试假设，"
                       "非现场事实、非 AI 自动设计、非材料规格或施工排版",
        "material_finish": {
            "mat-oak": {
                "tile": 1.60, "joint_spacing_mm": 600, "joint_width_mm": 6,
                "edge_trim_mm": 80,
                "note": "主要木饰面：按 600mm 板宽示意竖向板缝，贴图重复倍率 1.6（人工假设）",
            },
            "mat-walnut": {
                "tile": 1.40, "joint_spacing_mm": 600, "joint_width_mm": 6,
                "edge_trim_mm": 80,
                "note": "次要木饰面：同尺度板缝，人工假设",
            },
            "mat-floor-microcement": {
                "tile": 0.50, "joint_spacing_mm": 1200, "joint_width_mm": 4,
                "edge_trim_mm": 80,
                "note": "主要地面：按 1200mm 示意分缝网格与 80mm 踢脚收边，不是施工排版",
            },
            "mat-stone": {
                "tile": 0.90, "joint_spacing_mm": 900, "joint_width_mm": 5,
                "edge_trim_mm": 60,
                "note": "石材台面/中岛：示意分缝，人工假设",
            },
        },
        "window_expression": {
            "glass_kind": "transparent",
            "frame_width_mm": 60, "reveal_depth_mm": 200, "mullion_count": 1,
            "outside_environment": "labelled_local_sky_gradient_assumption",
            "outside_note": "窗外为本地程序化天空/远景渐变（淡蓝天光 + 暖灰地平线带），"
                            "不是现场照片、不是真实外景，也不宣称照度合规",
            "exposure_ev": -0.15,
            "window_light_energy_scale": 0.62,
        },
        "staging_note": "V3 陈设按 furniture.origin_kind 分为 source_model / "
                        "cc0_expression_asset / test_staging / procedural_expression；"
                        "后两类只进入平面与场景表现，工程量与材料面切片恒为 0 影响",
        "assumptions": [
            "V2 玻璃改为透明透射材质，窗框/窗洞深度/窗外天空渐变均为本地程序化人工假设；"
            "采光方向仍只来自已建模窗洞口，不再用发光板掩盖窗口细节。",
            "V2 木饰面与地面分缝/收边为示意几何，参数是版本化表达输入，不是材料规格、"
            "产品选型或施工排版。",
            "V3 新增展台、器物、品牌板与配套座椅是测试陈设（人工表达假设），"
            "位置由本布局动线/分区派生，不复制固定样板坐标，不计工程量、不称 AI 设计。",
            "品牌板只放抽象色块，不含客户品牌、不含文字设计；展品为 CC0 器物示意，"
            "不是协诚产品清单。",
        ],
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
        "expression": expression,
        "assumptions": ASSUMPTIONS, "missing": MISSING,
    }
