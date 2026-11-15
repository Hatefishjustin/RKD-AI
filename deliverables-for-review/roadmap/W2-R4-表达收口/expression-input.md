# 版本化表达输入（V2 窗光/材质 · V3 陈设分类）

契约 `rkd-spatial-expression.v1`，由 `scripts/w2_r4_fixture_presentation.py` 生成、`mvp/rkd_mvp/spatial_presentation.py` 校验、`scripts/render_spatial_scene_r4.py` 只读消费。参数不写死在渲染器，也不手工改像素。

## 窗表现

- `glass_kind` = `transparent`
- `frame_width_mm` = `60.0`
- `reveal_depth_mm` = `200.0`
- `mullion_count` = `1`
- `outside_environment` = `labelled_local_sky_gradient_assumption`
- `outside_note` = `窗外为本地程序化天空/远景渐变（淡蓝天光 + 暖灰地平线带），不是现场照片、不是真实外景，也不宣称照度合规`
- `exposure_ev` = `-0.15`
- `window_light_energy_scale` = `0.62`
- `source` = `executor_manual_expression_assumption`

## 材质收边/接缝

- **mat-oak**：`{"tile": 1.6, "joint_spacing_mm": 600.0, "joint_width_mm": 6.0, "edge_trim_mm": 80.0, "note": "主要木饰面：按 600mm 板宽示意竖向板缝，贴图重复倍率 1.6（人工假设）"}`
- **mat-walnut**：`{"tile": 1.4, "joint_spacing_mm": 600.0, "joint_width_mm": 6.0, "edge_trim_mm": 80.0, "note": "次要木饰面：同尺度板缝，人工假设"}`
- **mat-floor-microcement**：`{"tile": 0.5, "joint_spacing_mm": 1200.0, "joint_width_mm": 4.0, "edge_trim_mm": 80.0, "note": "主要地面：按 1200mm 示意分缝网格与 80mm 踢脚收边，不是施工排版"}`
- **mat-stone**：`{"tile": 0.9, "joint_spacing_mm": 900.0, "joint_width_mm": 5.0, "edge_trim_mm": 60.0, "note": "石材台面/中岛：示意分缝，人工假设"}`

## 调参留痕（人工目检驱动，非放宽检查）

1. 首版：透明玻璃 + 窗框 + 窗外渐变；曝光 -0.30、窗光系数 0.50、补光 32 → 人工看图判定偏暗、地面分缝过抢、展台基座突兀。
2. 二版：曝光 -0.15、窗光系数 0.62、补光 42、分缝调浅、展台基座改浅木 → 亮度与材质尺度改善；仍见 B 最左窗高亮。
3. 三版：面光源 `visible_camera=False`、窗外渐变整体压暗（emission 0.34）→ 窗框/玻璃/窗外层次可辨，最左窗扇仍有高亮残留，如实列为未解决项，未继续压暗掩盖。

## 陈设分类

`furniture[].origin_kind ∈ {source_model, cc0_expression_asset, test_staging, procedural_expression}`；后两类只进入平面与场景表现，工程量恒为 0 影响。位置由本布局动线/分区派生，不复制固定样板坐标；不暗改源方案、不称 AI 自动设计。
