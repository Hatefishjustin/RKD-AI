# ARC-05 适配说明（首批只交说明，不实现）

日期：2026-11-12 · 范围：第 5 节「首批」中 ARC-05 的唯一交付物。
性质：字段映射与数据归属说明，不是功能完成证明，也不是新增权威项目事实。

## 1. 三条现有能力线的归属

| 能力线 | 权威数据 | 当前用途 | 本批处理 |
| --- | --- | --- | --- |
| 原工作台 M1/M2 与 AI-DESIGN-01—05 | 主系统 `var/` SQLite / PG，版本化契约 `contracts/v1/ai-design-*.schema.json` | 项目、文件、任务、候选、采用指针、工程量、量价、成果登记 | 不改动；仍是有效模型、采用指针与成果登记的责任方 |
| Studio A1 协作实验 | 独立 `var/studio/studio.db`（本机实验库） | 角色发言、评审、契约提案、闸口与反馈 | 本批新增版本化反馈/检查报告/修订链；**仍是提案与协作层，不是成果登记权威** |
| 人工方案 A 渲染 JSON | `var/deliverables/ningbo-xiecheng/2026-11-10/方案A_设计数据.json` + `scripts/render_blender.py` | 仅用于表达能力测试与案例对照，明确标注「人工编写/人工调整」 | 不改动、不接入系统自动设计、不计入 AD 验收 |

Studio 实验库暂留，但写入归属必须明确：**Studio 只写自己的实验库，不写主系统项目事实，不写采用指针，不写正式成果**。本批 `server.py` 已显式声明 `service_scope.mode = local_experiment`、`team_nas_supported = false`，不冒称团队/NAS 已支持。

## 2. 字段映射（Studio spatial-plan-proposal.v1 → 主系统候选模型）

复用现有 `contracts/v1/` 版本契约，不新建第三套权威项目事实。以下仅为**后续第二批纵向适配的映射草案**，本批未实现适配器、未写主系统表、未生成效果图。

| Studio 提案字段 | 单位/坐标系 | 主系统候选对象（建议落点） | 适配损失与处理 |
| --- | --- | --- | --- |
| `contract_version` / `project_id` | `rkd-spatial-plan.v1` / 与主系统项目 ID 显式映射（`source_project_id`） | `ai-design-option` 的 `schema_version` / `project_id` | 映射必须显式记录，不从名称推断；跨项目引用拒绝 |
| `strategy.{name,narrative,tradeoffs}` | 文本 | 候选 `strategy` / 设计意图 | 设计主张由模型给出；程序不改写 |
| `zones[].{id,role,polygon,area_sqm}` | mm，XY 平面，原点西南，右上为 +X/+Y | 空间对象 `option_object`（空间关系/功能区） | 分区是「空间」不是墙；多边形需保留，不能离散成近似矩形后宣称精确 |
| `circulation[].{id,width_mm,path}` | mm 折线 | 动线关系对象 | 路径带宽不等于实体墙；通行能力由本批 `geometry.check_geometry()` 复算 |
| `platforms[].{id,kind,corner_radius_mm,polygon,height_mm}` | mm | 展台/构件对象 | `rounded` 的圆角为造型参数，当前二维制图只画外轮廓，适配损失须标注 |
| `ceiling.{coves,fixtures}` | mm / K | 天花与灯具意向对象 | 照度、配光、间距未计算；草案缩略图未画天花，**不能据图面缺失推断数据缺失** |
| `furniture[].{id,catalog_id,x,y,rot}` | mm / 度 | 家具对象 + 目录引用 | 尺寸取目录 `w_mm/d_mm`；旋转占地用 shapely 复算；未知目录条目拒绝，不用 600×600 默认框 |
| `area_table` | ㎡ | 候选面积摘要 | 必须由程序按「可布置范围 = 外框 − 保留区」复算，不采信模型合计为既成事实 |
| `open_questions` / `standards_cited` | 文本 / STD id | 缺口与依据引用 | unknown 不填 0；引用编号必须存在于规范库 |

## 3. 单位、坐标系、版本与来源

- 单位：几何 mm，面积 ㎡，金额 ¥（CNY）；坐标：局部 XY 平面，原点 (0,0) 在场地西南角，+X 向东、+Y 向北（与现有 fixture `entrance=[0,10300,1800]` 一致）。Z/标高仅在 `height_mm` 出现，未建立完整三维坐标系。
- 对象 ID：同一修订内沿用稳定 ID；删除保留历史与替代关系；不同候选间不强行配身份（本批 `substantive_difference()` 只比较结构签名）。
- 版本：本批已落 `run_id` / `candidate_group_id` / `revision_uid` / `parent_revision_uid` / `input_hash` / `check_report_id`；模型不决定身份、批准或采用指针。
- 来源：每份候选标注 `author="D2"` 与 `contract_status`；本批验证数据一律标为「明确标记的本地模型桩」，不是真实 AI 结果，也不是人工方案。
- 模型/材质/相机版本：Studio 提案目前**没有**材质规格、产品、相机与灯光版本字段；映射时必须标 unsupported，不得静默丢弃或用默认值补齐。

## 4. 成果链与失效规则（后续第二批实现，本批 not_run）

1. 每份成果记录模型哈希（`payload.sha256`）、生成器版本、来源、文件 SHA；本批已在 Studio 产物上具备 `sha256` / `check_report_id` / `run_id` / `input_hash`，但**尚未跨平面/渲染/数量做同源一致性验证**（Q10 = not_run）。
2. 修改几何 / 材料 / 价格只使相关成果失效，旧文件保持可下载；失效通过追加状态与明确过滤表达，历史字节不删除（本批 `superseded` / `invalid_raw` / `legacy_unvalidated` 已提供分组语义）。
3. 不强塞新多边形模型进旧矩形约束，也不破坏旧成果解析；旧 `ai-design-option` 与 M2 矩形链保持兼容。
4. 未知成本不补零；净地坪小计不称全项目造价。
5. 纵向切片顺序：先「平面 + 一张人眼效果图」；不同时启动全部专业图纸或整库迁移。

## 5. 本批明确未做

- 未实现 Studio → 主系统候选模型的写入适配器；
- 未生成任何效果图、天花图、立面图、材料灯光板或汇总 PDF；
- 未做文件下载字节/哈希一致性跨成果验证；
- 未做真实模型调用或图像通道调用（0 次、0 费用）；
- 未改变 AD01—AD08 结论，未代替用户确认设计阶段。

复核要点：本文件只是**映射与归属说明**；若架构师复核发现字段语义与主系统现有契约冲突，应在第二批实现前修正映射，而不是回写 Studio 提案契约或放宽校验。
