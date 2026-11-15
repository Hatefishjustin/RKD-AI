# 资产、来源与人工假设清单（V2/V3 更新）

本批**未下载任何新资产、未新增外部调用**。资产仍来自项目既有 `tools/assets/`（Poly Haven，CC0 1.0）。渲染器只读版本化表达输入，不手工改像素。

## 可复用资产

| 类别 | 内容 | 来源/许可 | 本批用法 |
| --- | --- | --- | --- |
| 渲染器 | Blender 4.2.9 LTS 免安装版 | 项目既有，GPL | Cycles CPU，两布局各 1 张人眼图 |
| PBR 贴图 | 6 套 1k：floor_microcement / wall_plaster / oak / walnut / stone / fabric | Poly Haven CC0 1.0，清单 `assets/CC0-素材清单.json` | 真实贴图 + 版本化 tile |
| glTF 家具/器物 | 10 件，尺寸取清单 `dimensions_mm` | Poly Haven CC0 1.0 | 统一 anchor=center_floor、0° 沿 +X、rotation_deg 逆时针 |
| 窗外环境 | 本地程序化天空/地平线渐变 | **执行者人工假设**，非外部素材 | 透过透明玻璃可见，明确标 `labelled_local_sky_gradient_assumption` |
| 程序化表达 | 展墙 / 展台 / 品牌板 | **执行者人工假设几何**，非 CC0 资产 | 替代 display-wing 占位盒，保留对象 ID/位置/尺寸 |

## V2/V3 版本化表达输入

- 契约：`rkd-spatial-expression.v1`；声明来源 `executor_manual_fixture_w2_r4_closeout`。
- 材质收边/接缝：mat-floor-microcement, mat-oak, mat-stone, mat-walnut （tile / joint_spacing_mm / joint_width_mm / edge_trim_mm，均为人工假设）。
- 窗表现：`glass_kind=transparent`，发光玻璃板 0，窗框宽 60.0 mm，洞口深度 200.0 mm，窗外为标注的本地天空渐变。
- 完整输入见 `outputs/expression-input-A.json` / `-B.json` 与 `expression-input.md`。

## 对象来源分类（不计工程量）

- 布局 A：`{"source_model": 2, "procedural_expression": 5, "cc0_expression_asset": 13, "test_staging": 5}`；`engineering_quantity_effect=0`
- 布局 B：`{"source_model": 2, "procedural_expression": 5, "cc0_expression_asset": 13, "test_staging": 5}`；`engineering_quantity_effect=0`

源模型对象、CC0 表达资产、测试陈设、程序化表达在 `plan-index.json` 的 `expression_accounting` 与场景 `origin_kind` 中分列；**新增陈设不进入 measure() 的工程量、材料面切片或试算金额**（专项断言 V3-*-03 证明）。

## 明确假设（不编现场事实）

- 周界墙厚 200mm、高 3000mm 为人工测试假设；场地边界本身是标为 manual_boundary_not_site_verified 的测试参数，未现场复核。
- 没有从任何功能区多边形边界自动生成墙体；两段隔断是独立显式给出的样板假设。
- 北向/东向窗洞口的节奏只借用阶段1底图窗带的间距作示意，不作为本项目现场事实；窗台 900mm、窗高 1800mm、门高 2400mm 均为人工假设。
- 入口门洞位置与 1800mm 宽度来自模型 boundary.entrance（测试参数），门扇/门套构造未建模。
- 材质贴图来自 Poly Haven CC0 1.0 六套 1k PBR；贴图与分区 role 的对应是人工样板假设，只代表材质意向，不是材料规格、产品选型或价源。
- 家具从 CC0 glTF 目录引用，真实尺寸取 assets/CC0-素材清单.json 的 dimensions_mm；统一 anchor=center_floor、0° 沿 +X、rotation_deg 逆时针；无对应资产的目录条目明确留程序化占位。
- 绿植、器物、补充桌椅是表达层道具（presentation_prop），对象 ID 独立于模型家具，按分区中心加固定偏移摆放；不宣称是自动设计出的陈设。
- 机位为 1500mm 人眼高度、24mm 镜头的内部评审视点（人工假设），不是设计决定也不是实测。
- 中岛台面上的器物显式给出 z_offset_m=0.72（与平台 height_mm 一致），避免与平台实体穿插；该高度是表达层人工假设，不是展陈设计标高。
- 贴图 tile 按 1k 贴图约 0.6—2m 重复尺度设置（人工假设），不是材料规格或施工排版。
- 窗光只从已建模窗洞口发出；灯具点位/灯槽来自模型 ceiling 意向，太阳角度与强度是假设。未做照度/配光计算，不宣称照度合规。
- 柱网、洁具、构造节点、消防/疏散/无障碍、实测标高、产品清单、现场照片均缺依据，一律不编造、不补 0、不在图上冒充。
- V2：玻璃为透明透射材质 + 窗框/窗洞深度；窗外是明确标注的本地程序化天空渐变（淡蓝天光 + 暖灰地平线带），不是现场照片或真实外景。
- V2：木饰面与地面的纹理比例、分缝与踢脚收边是版本化表达输入里的示意参数，不是材料规格、产品选型或施工排版。
- V3：display-wing 占位件替换为程序化展墙；新增展台/器物/品牌板/配套座椅是测试陈设（人工表达假设），保留对象 ID、位置与尺寸，不进工程量、不暗改源方案。
