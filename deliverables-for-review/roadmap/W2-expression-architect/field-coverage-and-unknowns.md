# 等待期只读整理：真实模型输出 → 现有 spatial → 围合/开口/材料/家具表达

2026-11-16 · 依 `deliverables-for-review/roadmap/W2-expression-architect/review-and-gate.md` 等待期授权整理。

**性质**：只读字段对账与缺口清单，不是设计成果、不是验收、不是实现、不是执行委托。本文件只读取已交付文件与源码，未改任何业务代码、契约、原件、模型、成果或 AD；未调用外部模型、未生成用户项目阶段 2、未开始 W3/W4、未围绕同一人工夹具追加陈设或管理模块。外部模型/图像调用 0、外发 0、新增图 0、tokens 0、费用 0、密钥未使用未落盘。**V1—V3 的 20 项工程断言不是全链独立验收；W2 整体客户成果、AD01—AD08、用户阶段 1→2 仍未通过/未给。**

---

## 0. 先说清一条最重要的链路事实

「真实模型输出」与「现有 `spatial`」**目前没有接通**：

- 真实模型链由 `mvp/rkd_mvp/ai_design_option_provider.py` 的 `RealModelDesignOptionProvider` 承担（`REAL_DESIGN_SYSTEM_PROMPT` + `REAL_DESIGN_OUTPUT_SHAPE`，提示/适配器 v3）。它输出米制 `rect`（`x/y/width/length`）写入候选 `objects[].shape`，设计意图写在 `objects[].properties`；**该文件全文 `spatial` 只出现在模块说明 "spatial organisation" 一词，不构造 `spatial` 段**。
- 现有 `spatial`（`rkd-ai-design-option-spatial.v1`）由 `mvp/rkd_mvp/ai_design_studio_adapter.py` 从 **Studio 提案 `rkd-spatial-plan.v1`** 适配而来，是 mm 精确多边形。W2-R4 两布局 `outputs/layout-A|model.json` 实测 `generation.provider_kind=studio_proposal_adapter`、`real_model=false`、`spatial.source.design_origin.kind=fixture`、`boundary.boundary_source=manual_boundary_not_site_verified`。
- 因此 W2-R4 表达层吃的是**明确标注的人工夹具提案**，不是真实模型输出。把两条链说成「已贯通」是错的；两者之间的适配/投影层尚未实现，属后续真实设计验证范围，须架构师界定并取得费用/资料授权后才可做。

契约依据：`contracts/v1/ai-design-option.schema.json`（`$defs/spatialExtension`）。表达契约：`rkd-spatial-presentation-fixture.v1` + `rkd-spatial-expression.v1`（`mvp/rkd_mvp/spatial_presentation.py`、`scripts/w2_r4_fixture_presentation.py`）。

---

## 1. 三段链路的字段清单（只读摘录）

### A. 真实模型输出（`REAL_DESIGN_OUTPUT_SHAPE`，米制 rect）

`strategy_id / concept / statement / rationale / tradeoffs`；`narrative{theme, sequence, topology, climax, first_view}`；`entrance_side{left|right|top|bottom}`；`circulation_kind{loop|branch}`；`materials[]{material_id,name,intent}`（仅氛围意向，`status=intent_only`）；`zones[]{object_id,name,x,y,width,length,material_id,min_area_m2,zone_role,sequence_role,intent}`（`zone_role` 词表 `foyer|primary_display|deep_talk|buffer|service`）；`walls[]{object_id,name,x,y,width,length,wall_type}`（`solid|screen|curved_intent|feature`）；`furniture[]{object_id,name,x,y,width,length,furniture_type,parent_object_id}`（`reception_desk|island|table_chairs|sofa|plant|display_case|storage|pantry|service_counter|light_feature`）；`focal_point{...,furniture_type,statement}`；`entrance_buffers[]`；`paths[]{segment_id,x,y,width,length}`；`connections[]`；`relationships[]`；`cost_unknown[]`。

程序侧映射（`_to_model`）：`walls→objects[].kind=partition` + `properties.wall_type`；`furniture→display_object` + `properties.furniture_type`；`parent_object_id→properties.intended_parent`（**意图，不是几何父链**）；`focal_point→display_object` + `properties.focal=true`；`entrance_buffers→entrance_marker`；`paths→circulation.segments[].shape`（bbox）；材料/成本缺项 `value=null` + `unknown`。`boundary.boundary_source` 默认 `test_parameters_not_site_verified`。

### B. 现有 `spatial`（`rkd-ai-design-option-spatial.v1`，mm）

`origin{boundary_mm,coordinate_system,source_contract,unit,note}`；`zones[]{object_id,name,role,polygon_mm,area_sqm,finish_material?,source_refs}`（本批实测 role 词表：`arrival|gallery|island|meeting|scene|service`）；`circulation[]{object_id,path_mm,width_mm,source_refs}`；`platforms[]{object_id,polygon_mm,height_mm,corner_radius_mm}`；`furniture[]{object_id,catalog_id,x_mm,y_mm,w_mm,d_mm,rot,source_refs}`（实测 `catalog_id` 仅 `sofa-3p|dining-table|display-wing`）；`ceiling{strategy,fixtures[],coves[]}`（intent only，实测 `spot / 2700K`）；`materials[]{material_id,intent,known_status,value,unknown_reason}`（实测 3 条全为 `catalog_reference_only / unknown / value=null`）；`views[]`（**实测为空**）；`unsupported_items[]`；`unknown_items[]`；`source{origin_kind=studio_import,design_origin{kind,declared_by,declaration,run_refs},site_source{width_mm,height_mm,ceiling_mm,entrance_mm,source},sha256,lineage_chain,...}`；`adaptation{adapter_version,mapping_version,unit_conversion=mm_to_m_div_1000,geometry_mode,diff_baseline,object_id_map,losses,field_ledger}`；`area_table[]`；`open_questions[]`。

### C. 表达层（围合/开口/材料/家具，`presentation.json` 实测）

`walls[4] / partitions[2]`：`segment_mm,length_mm,thickness_mm,height_mm,material_slot,source,assumption=true,site_verified=false`；`openings[7]`：`kind{door|window},wall_object_id,center_mm,width_mm,height_mm,sill_mm`；`furniture[25]`：`catalog_id,asset_id,asset_dimensions_mm,origin_kind{source_model|cc0_expression_asset|test_staging|procedural_expression},placeholder,position_mm,rotation_deg,z_offset_m,z_offset_note,anchor`；`materials[6]`：`material_id,slot,hex,tile,tint,rough,normal_strength,zone_roles`；`cameras[1]`：`position_mm,target_mm,eye_height_mm,lens_mm`；`lighting{window_opening_ids[5],fixtures[3],coves[1],sun{azimuth,elevation,energy}}`；`expression{material_finish{tile,joint_spacing_mm,joint_width_mm,edge_trim_mm},window_expression{glass_kind,frame_width_mm,reveal_depth_mm,mullion_count,outside_environment,outside_note,exposure_ev,window_light_energy_scale}}`；`assumptions[15]`、`missing[8]`；顶层 `site_verified=false / not_ai_design=true / not_site_fact=true`。

---

## 2. 字段覆盖表

| 表达主题 | 真实模型输出字段 | 现有 `spatial` 字段 | 表达层字段 | 当前实际来源 | 覆盖判定 |
| --- | --- | --- | --- | --- | --- |
| 分区几何 | `zones[](x,y,width,length)` 米制 rect | `zones[].polygon_mm` 精确多边形 | 平面/场景由 `polygon_mm` 绘制 | Studio 人工夹具提案 | **断链**：模型未产出 mm 多边形，表达层用的多边形不是模型给的 |
| 分区角色 | `zone_role / sequence_role / intent` | `zones[].role`（另一套词表） | `materials[].zone_roles`、陈设按 `role` 分桶 | 人工夹具 role | **词表不一致**（`foyer/primary_display/deep_talk/buffer/service` ≠ `arrival/gallery/island/meeting/scene/service`），无显式映射表 |
| 围合/墙体 | `walls[](wall_type, 米制 rect)` | **无 `walls` 段**（契约未定义） | `walls[4]+partitions[2]` 的 `segment_mm/thickness_mm/height_mm/material_slot` | `w2_r4_fixture_presentation.py` 硬编码 4 段周界 + 2 段比例隔断，全部 `manual_test_assumption` | **完全人工**：`spatial_presentation.py` 明确「zone polygon 不是墙、不从分区边界自动造墙」；模型 `wall_type` 未落地 |
| 开口/门窗 | **无 openings 字段**（只有 `entrance_side`） | **无 openings 段**；`unsupported_items` 明列「门窗/柱网/构造」 | `openings[7]` 的 `kind/center_mm/width_mm/height_mm/sill_mm/wall_object_id` | 入口宽 1800 来自 `boundary.entrance` 测试参数；北/东窗带只借用阶段1底图节奏作 pattern；窗台 900、窗高 1800、门高 2400、隔断门 900×2200 均为人工假设 | **完全人工 + 部分 unknown**：程序校验只保证「洞口落在已建模墙段上、宽高不越界」，不保证尺寸属实 |
| 材料意向 | `materials[].intent`（`intent_only`，未选产品） | `materials[]`（`catalog_reference_only / unknown / value=null`） | `materials[6]` 的 `slot/hex/tile/tint/rough`、`expression.material_finish` 的分缝/收边 | 6 套 Poly Haven CC0 1k 贴图 + 人工 `zone_roles` 对应；分缝 600/1200mm、踢脚 80mm 为示意假设 | **意向未贯通**：模型意向 → spatial 仍为 unknown → 表达层只是可视化替身；无规格/产品/价源 |
| 家具 | `furniture[](furniture_type, parent_object_id→intended_parent)`、`focal_point` | `furniture[](catalog_id,x_mm,y_mm,w_mm,d_mm,rot)` | `furniture[25]` 的 `asset_id/position_mm/rotation_deg/z_offset_m/origin_kind` | `CATALOG_TO_ASSET` 3 条人工映射（`sofa-3p→sofa_02` 等）；其余 13 件 CC0 表达资产、5 件 `test_staging`、5 件 `procedural_expression` 均为人工道具，位置按分区中心+固定偏移或动线派生 | **部分人工**：`furniture_type` 词表与 `catalog_id` 无映射；仅 2 件标 `source_model`；后两类陈设不进工程量 |
| 动线 | `paths[] / connections[]`（米制矩形段） | `circulation[].path_mm`（中心线 mm） | 仅用于派生 V3 陈设位置；不生成开口 | Studio 夹具 | **部分**：几何口径不同（矩形段 vs 中心线），模型动线未进入 spatial |
| 天花/灯具 | **无 ceiling 输出** | `ceiling.fixtures/coves`（intent only） | `lighting.fixtures/coves/window_opening_ids/sun` | 点位来自夹具天花意向；`sun` 角度/强度、补光、曝光为人工假设 | **部分人工**：明确「未做照度/配光计算，不宣称合规」 |
| 视图/机位 | `narrative.first_view / climax / focal_point`（文字） | `views[]`（空）；`unsupported_items` 明列「相机与人眼视图」 | `cameras[1]`（1500mm 人眼、24mm） | 人工假设内部评审视点 | **断链**：文字叙事未转成有来源的 view 对象 |
| 场地来源 | `boundary_source=test_parameters_not_site_verified` | `source.site_source`（阶段1底图 DXF 26169.58×17920.17）、`design_origin.kind=fixture` | 顶层 `not_site_fact=true` | 解析确认，非现场实测 | **来源不同但数值相同**，卡片已声明不得当作同一冻结版本 |
| 成本 | `cost_unknown[]` | `cost.budget / total_project_estimate` `value=null + unknown` | 工程量/成本对账（去陈设不变） | 人工夹具 + 假设单价 | unknown 不补 0，`formal_quote=false` |

---

## 3. unknown 清单（按出处分组，均不补 0、不冒充已核实）

**契约/模型层**
1. `spatial.unsupported_items` 6 项，全部 `status=unsupported_unknown`：材料规格/产品选型；相机与人眼视图；照度/配光计算；实测标高/层高；门窗/柱网/构造；legacy rect 对象（`bbox_derived`，不得据其算量）。
2. `spatial.unknown_items` 1 项：`协诚的产品清单缺失，展品只能做示意`，`value=null / known_status=unknown`；`open_questions` 同一条。
3. `spatial.materials` 3 条：`catalog_reference_only / unknown / value=null`（「目录条目不含材料规格/产品选型/样板状态」）。
4. `spatial.views = []`。
5. `cost.budget`、`cost.total_project_estimate`：`value=null + unknown`；`formal_quote=false`。
6. `boundary.boundary_source`：`manual_boundary_not_site_verified`（夹具）/ `test_parameters_not_site_verified`（真实模型默认）。

**表达层**（`presentation.missing` 8 项）
柱网与结构构件；洁具与给排水；门窗产品与构造节点；材料规格/产品选型/价源；照度/配光计算与合规结论；消防/疏散/无障碍与施工图合规；现场实测标高与实测墙厚；客户可交付的多视角效果图/天花/立面/材料板/汇总 PDF。

**表达层人工假设**（`presentation.assumptions` 15 项，摘要）
周界墙厚 200mm / 高 3000mm；不从分区边界造墙；窗洞口仅借底图节奏、窗台 900/窗高 1800/门高 2400 皆假设；入口 1800mm 为测试参数、门扇门套未建模；贴图与 `role` 对应为材质意向；CC0 家具映射与统一 anchor/朝向；绿植器物为表达道具；1500mm/24mm 机位；`z_offset_m=0.72` 台面器物；贴图 tile 尺度；窗光只从已建模窗、太阳角度与强度是假设；柱网/洁具/节点/合规/实测标高/产品清单/现场照片一律不编；V2 透明玻璃与窗外本地程序化渐变；V2 分缝收边为示意；V3 陈设为人工表达、不计工程量。

**底图确认卡第四节（阶段1 已列、继续保留待核）**
主入口位置与宽度/高度；窗台高与窗洞高；卫生间湿区内部隔断与洁具位置；133 项拓扑复核标记；实测标高；现场照片。解析确认 ≠ 现场实测，允许继续设计不等于把任一项改成 `site_verified=true`。

**验收状态（`independent-checks.json` 的 `not_run`，不得换算成通过）**
用户项目阶段 2 设计生成；W3/W4；照度/配光合规计算；真实现场复核。`--no-render` 退出 0 只表示所执行检查未发现失败。

**顶层标识**：`site_verified=false`、`not_ai_design=true`、`not_site_fact=true`、`assumption=true`（每个墙/开口/材质/家具/机位项）。

---

## 4. 人工假设将如何被有来源的模型数据替换（只写路径，不实现、不宣称已完成）

**总前置**：须先有「真实模型输出 → `spatial`」的适配层，把米制 `rect` 投影为带来源的 mm 对象，并随字段携带 `design_origin.kind=real_model`、`run_refs`、`sha256`、`input_hash`、`prompt_version`、`source_refs`；不得沿用 `studio_import` / `fixture` 冒充真实模型。该适配层、契约扩展、模型调用额度与资料外发范围**都由架构师在用户确认具体底图版本后界定并授权**，本轮不做。

| 类别 | 替换来源（须带出处） | 目标字段 | 必须保持的边界 |
| --- | --- | --- | --- |
| 分区几何 | 真实模型输出的精确多边形（或经声明的 `rect→polygon` 投影并记入 `losses`） | `spatial.zones[].polygon_mm` → 平面/场景/净量 | 投影损失写 `adaptation.losses` + `field_ledger`，不得静默矩形化；`design_origin` 与 `origin_kind` 分开 |
| 分区角色 | 模型 `zone_role/sequence_role/intent` | `spatial.zones[].role` 及表达层 `zone_roles` | 需一张**显式词表映射表**（`foyer↔arrival` 等）并对账，不能靠字符串巧合；`narrative` 单独留痕 |
| 围合 | 模型 `walls[].wall_type` + 几何 | `spatial` 新增 `walls`（契约需扩展）→ `presentation.walls/partitions` 的 `segment_mm` | `thickness_mm/height_mm/material_slot` 不是模型能凭空给的：须来自已确认的具体 v2 底图或现场依据，否则保持 unknown；`curved_intent` 须有对应弧/斜几何表示，不能落成直线段；仍不从 zone 边界自动造墙 |
| 开口 | 模型输出的门窗意图 + 用户确认的 v2 底图窗带/门洞几何（带完整 SHA） | `presentation.openings` 的 `center_mm/width_mm/sill_mm/height_mm/wall_object_id` | 窗台高、窗洞高属现场待核；用户不背书则保留 unknown，**不填 900/1800**；`sill_mm` 等不再用「只作 pattern」的示意值冒充 |
| 材料 | 模型 `materials[].intent`（`source_refs`）+ 有来源的产品/规格/价源目录 | `spatial.materials` 的 `known_status/value` → `presentation.materials` 的 `slot/hex` | 贴图仅为可视化替身；无规格/产品/价源时继续 `unknown + value=null`；`expression.material_finish` 分缝/收边在拿到材料排版依据前仍是示意假设，不称施工排版 |
| 家具 | 模型 `furniture_type` + 尺寸/位置 + 有来源的目录（`furniture_type → catalog_id → asset_id`） | `spatial.furniture[].catalog_id/x_mm/y_mm/...` → `presentation.furniture` | 需显式目录映射契约；`origin_kind` 区分 `source_model` 与表达资产，后者不进工程量；`intended_parent` 保持为意图而非几何父链；`focal_point` 落成有来源对象 |
| 动线/视图 | 模型 `paths/connections` 与 `narrative.first_view/climax/focal_point` | `spatial.circulation[].path_mm`、`spatial.views[]`（现为空）→ `presentation.cameras` | 几何口径统一并记 losses；机位/镜头仍标注为表达假设，不冒充现场或设计批准 |
| 天花/照明 | 模型天花意向（若新增）+ 专业照度依据 | `spatial.ceiling` → `presentation.lighting` | 未做照度/配光计算前不得宣称合规；`sun`/补光/窗外渐变保持标注假设 |
| 底图/场地 | 用户明确确认的 `rkd-site-basemap.v2` + 完整文件 SHA-256 + 确认范围 | `spatial.source.site_source`、`boundary.boundary_source` | 解析确认仍 ≠ 现场实测；`site_verified` 仅在确实影响对应设计决定且完成真实现场复核后逐项置位；133 项拓扑标记与现场照片不作全部前置条件 |
| 工程量/成本 | 有来源的价源与材料规格 | 量价对账 | 保持「去掉全部表达陈设后 quantities/cost 完全不变」；unknown 不填 0；`formal_quote=false` 直至正式责任闸口 |

**替换顺序不可越级**：用户对具体底图 v2 给明确结论 → 保存原话/完整 SHA/允许假设/仍待核项 → 送架构师界定下一批真实设计验证范围及费用/资料授权依据 → 才允许真实模型调用与契约扩展。本文件不新增任何授权，也不代替架构师决定范围。

---

## 5. 核对用完整路径（均为只读引用）

- 架构复核：`deliverables-for-review/roadmap/W2-expression-architect/review-and-gate.md`
- 独立断言副本：`deliverables-for-review/roadmap/W2-expression-architect/independent-checks.json`
- 唯一状态表：`PROJECT_STATUS.md`（2026-11-16 条）
- 底图确认卡：`deliverables-for-review/roadmap/W2-R4-表达收口/basemap-confirmation-card.md`
- 候选契约：`contracts/v1/ai-design-option.schema.json`
- 真实模型输出：`mvp/rkd_mvp/ai_design_option_provider.py`、`mvp/rkd_mvp/design_reference.py`
- Studio→spatial 适配：`mvp/rkd_mvp/ai_design_studio_adapter.py`
- 表达契约/夹具：`mvp/rkd_mvp/spatial_presentation.py`、`scripts/w2_r4_fixture_presentation.py`
- 实测产物：`deliverables-for-review/roadmap/W2-R4-表达收口/outputs/layout-A/model.json`、`outputs/layout-A/presentation.json`、`expression-input.md`、`asset-inventory.md`、`design-gaps.md`、`manifest.json`

**仍然不像设计公司成果**（不因本文件改变）：每布局仅 1 机位 1 张内部评审级人眼图，偏暗偏灰、天花占比大、B 左窗高亮残留、陈设偏稀疏、品牌内容弱、窗外为本地程序化渐变、无人物/软装细节；平面无闭合施工尺寸链/柱网/洁具/构造节点；无天花、立面、多视角、材料实物板、汇总客户 PDF；围合/开口/材料/家具表达全部是标注的人工假设，人工样板不计系统自动设计。这些差距保留到下一真实方案评审，不靠本轮代签。

---

## 附：本批文书变更的 SHA 留痕（勘误式，不回写历史证据）

本批只改两份已存在文书、新增本文件，不改任何业务代码/契约/原件/成果：

| 文件 | 变更前（HEAD `f6b8145` 实测） | 变更后（本批实测） |
| --- | --- | --- |
| `PROJECT_STATUS.md` | 210,487 字节 | 215,127 字节 · `dcd961d9bc72a5ebcfff3a7be017e495f870f36c3ce23364c9e5f941b9f64b0e`（顶部新增 2026-11-16 边界条；`更新时间` 改 2026-11-16） |
| `W2-R4-表达收口/basemap-confirmation-card.md` | 4,761 字节 · `4b7cb1d76d3c6f88d78df5f7d51a03f5989abe92ba5e1595f752cf01aece42f5` | 7,778 字节 · `9ef6aa30986ed30af54338bfbbb9ac998eea55b0f8e1bf71a91c636cfb7729c4` |
| `W2-expression-architect/field-coverage-and-unknowns.md` | 不存在 | 本文件新增；自身 SHA 不做自引用记录，由提交/复核包 manifest 或复核时按字节计算 |

- 确认卡只改第五节确认口径与新增一行修订留痕；第一至四、六节的版本/边界/入口/未知项/图面事实与哈希未改。该卡旧 SHA 仍记录在上一批 `W2-R4-表达收口/manifest.json`（作为已复核版本的历史快照），按 docs/26「不为文案一致回写历史证据，补充勘误记录即可」**不回写覆盖**；`scripts/verify_w2_r4_closeout.py` 不读取该 manifest 或确认卡，本批未重跑、20 项断言与本次文书修改无关。
- 阶段 1 底图 5 份文件（PDF/HTML/SVG/JSON/PNG）两处副本字节完全一致、完整 SHA-256 见确认卡第五节，本批未改、未重新生成、未重新打印。
- 本批 `review-and-gate.md` / `independent-checks.json` 为架构师既有复核文件，只读引用，字节未改（`review-and-gate.md` SHA-256 `a6d8f48c0d30a1add10cc6107e5dcf90fc2b646650c0eec179e57423449051f4`）。
