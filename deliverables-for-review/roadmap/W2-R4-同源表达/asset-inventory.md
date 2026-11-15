# W2-R4 可复用资产与人工假设清单（检查点 1）

本批**不新增任何外部调用、不下载新资产**。所有资产来自项目既有 `tools/assets/`
（Poly Haven，CC0 1.0 公共领域，商业使用允许，清单 `assets/CC0-素材清单.json`，
SHA-256 `593d84554d4778ad6b247a2206d5c6fd081e70f06dcefa3cd02108a6d83ee08d`），二进制文件被 .gitignore 排除、不进版本库。

## 可复用能力（只复用能力，不抄样板方案坐标）

| 类别 | 既有资产 / 能力 | 来源与许可 | 单位/尺度 | R4 用法 |
| --- | --- | --- | --- | --- |
| 渲染器 | Blender 4.2.9 LTS 免安装版 `tools/blender/` | 本机既有，GPL | Cycles CPU | 两布局各渲 1 张人眼图 |
| 材质加载 | `scripts/render_blender.py` 的 `pbr_mat()`（TexCoord/Object → Mapping → Diffuse/Rough/nor_gl） | 项目既有样板 | 1k PBR，tile 为倍率 | 复写为 `render_spatial_scene_r4.py` 的同名能力 |
| 家具加载 | `scripts/render_blender.py` 的 `load_template()`/`place_model()`（`bpy.ops.import_scene.gltf`） | 项目既有样板 | glTF 真实尺寸 mm | 统一 anchor=center_floor、0° 沿 +X、rotation_deg 逆时针 |
| 灯光能力 | 既有样板的窗发光板 / 太阳 / 筒灯 / 环形灯槽 | 项目既有样板 | W / K（假设） | 窗光只从已建模窗洞口发出；灯具/灯槽来自模型 `ceiling` 意向 |

- 纹理 6 套：fabric, floor_microcement, oak, stone, wall_plaster, walnut
- glTF 家具/器物 10 件，真实尺寸来自清单 `dimensions_mm`：
  - `bar_chair_round_01` — 0.483m/0.486m/0.751m — CC0 1.0 — https://polyhaven.com/a/bar_chair_round_01
  - `ceramic_vase_01` — 0.205m/0.206m/0.401m — CC0 1.0 — https://polyhaven.com/a/ceramic_vase_01
  - `dining_chair_02` — 0.434m/0.576m/0.973m — CC0 1.0 — https://polyhaven.com/a/dining_chair_02
  - `dining_table` — 2.256m/1.390m/0.877m — CC0 1.0 — https://polyhaven.com/a/dining_table
  - `modern_arm_chair_01` — 0.820m/0.987m/1.023m — CC0 1.0 — https://polyhaven.com/a/modern_arm_chair_01
  - `modern_coffee_table_01` — 1.202m/0.600m/0.390m — CC0 1.0 — https://polyhaven.com/a/modern_coffee_table_01
  - `potted_plant_01` — 0.589m/0.637m/1.351m — CC0 1.0 — https://polyhaven.com/a/potted_plant_01
  - `round_wooden_table_01` — 1.399m/1.399m/1.005m — CC0 1.0 — https://polyhaven.com/a/round_wooden_table_01
  - `sofa_02` — 1.807m/0.818m/0.709m — CC0 1.0 — https://polyhaven.com/a/sofa_02
  - `wooden_bowl_01` — 0.313m/0.309m/0.094m — CC0 1.0 — https://polyhaven.com/a/wooden_bowl_01

## 表达层人工测试假设（不是现场事实，不是 AI 设计）

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

## 明确缺资产的占位

- `display-wing`（展墙翼）：Studio 目录有条目，但本机 CC0 glTF 目录没有对应模型。
  保留为**明确占位盒**，在 scene/meta 里列 `placeholders`，不冒充真实家具。

## 几何字段审计

| 字段 | 权威来源 | 是否自动推导墙/柱/洁具 |
| --- | --- | --- |
| `spatial.zones[].polygon_mm` | 主系统候选修订（精确 mm） | 只用于地坪/计量，不生成墙 |
| `spatial.platforms[].corner_radius_mm` | 同一修订 | 平面与三维用同一圆角算法，不退化成方块 |
| `spatial.ceiling.fixtures/coves` | 同一修订（意向） | 只驱动灯具点位/灯槽，不生成吊顶构造 |
| `boundary.entrance` | 同一修订（测试参数） | 仅门洞位置/宽度 |
| `presentation.walls/partitions/openings` | **执行者人工编写的样板假设** | 独立显式对象，不从分区多边形生成 |
| 柱网 / 洁具 / 构造节点 / 实测标高 | 无依据 | 不编造、不补 0 |
