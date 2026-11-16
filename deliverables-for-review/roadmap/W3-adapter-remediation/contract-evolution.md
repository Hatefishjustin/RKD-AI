# 主契约演进与兼容性决定所需证据（R03）

编制：2026-11-16。基线 `dcc11f7`；本批 v2 适配器与两份 v2 schema。**这是给架构师的演进方案与证据，不是已获批准的契约变更，也不是正式候选/采用路径。**

## 1. 事实：不是兼容扩展

- 权威候选文档版本仍为 `rkd-ai-design-option.v1`（`contracts/v1/ai-design-option.schema.json`）。
- 上一批新增了 `realmodel-spatial-option.schema.json`，用 `schema_version` 同为 `rkd-ai-design-option.v1` 的另一份 schema 声称兼容；架构师独立发现同一文档按旧 schema 有 **26 个错误**。本批复跑同样得到 **26**（`checks.json` V-17 逐条登记），不声称消除。
- 根因是旧契约把两处写死：`boundary.boundary_source` 只允许 `test_parameters_not_site_verified` / `manual_boundary_not_site_verified`（不含用户确认的 `rkd-site-basemap.v2`），且 `spatial` 只允许 Studio 专属分支 `rkd-ai-design-option-spatial.v1`（`origin_kind=studio_import`、`mapping_version=W0-erratum-2.3`）。真实模型适配结果无法在该版本下合法表达。

## 2. 本批采用的演进方案（待架构裁定）

**单一权威版本 + 可标识 additive 分支**，不再是"同一版本两份互不兼容 schema"：

1. 文档顶层仍为 `rkd-ai-design-option.v1`；空间段是显式版本 `rkd-realmodel-spatial.v2`（与 Studio 的 `rkd-ai-design-option-spatial.v1` 并列、可识别），由 `contracts/v1/realmodel-spatial-option.v2.schema.json` 校验。
2. 该 v2 schema 由旧主契约**派生**：仅对 `boundary_source` 增加 `rkd-site-basemap.v2` 枚举值、放宽 `entrance`/`material` 的附加属性（均向后兼容），并用独立 `$defs.realmodelSpatialExtension` 描述新空间段；**既有 schema 文件本身未修改**。
3. `contracts/v1/realmodel-spatial-adaptation.v2.schema.json` 是适配契约自身的 schema（契约版本、底图 SHA、词表、规则、负例），与候选文档 schema 分开，避免混淆"契约"与"被校验对象"。
4. 迁移语义：v2 候选属**实验分支**，`lifecycle_status=candidate`、`publication_status=not_approved`、`source.origin_kind` 明确为 `fixture_shape` / `human_edited` / `unknown_origin` / `real_model_output`；**不可作为正式候选持久化或被采用**，直到架构师把分支并入主契约并定义采用路径。本批只在隔离 SQLite（`var/.../after/runtime/app.sqlite3`）写入桩候选做路径验证，未触碰日常库。

## 3. 消费者 / 存储验证路径证据

| 环节 | 证据 | 结论 |
| --- | --- | --- |
| 旧 schema | V-17：26 项错误逐条登记 | 不宣称同名兼容 |
| v2 输出 schema | V-060/V-061：两候选 0 错误 | 新分支可独立校验 |
| 适配契约 schema | V-01：合法 Draft2020-12 schema；契约实例由代码常量生成 | 文档与实现不漂移 |
| 真实 provider | V-04：本地协议桩经真实 `generate()` 产出 2 候选、0 外部调用 | 真实入口可执行 |
| 真实仓储 | V-05：真实 `SQLiteAIDesignOptionRepository` 写入并读回 objects/segments | 持久化路径打通（隔离库） |
| 同源生成 | V-14/V-15/V-16 | 渲染进最终包并下载校验 |
| 主契约合并 | **未做** | 待架构师裁定是否把 `realmodelSpatialExtension` 并入 `ai-design-option.schema.json` 的 `spatial.oneOf`，并决定旧文档迁移与存储索引 |

## 4. unknown 语义（保持）

`unknown` 一律 `value=null` + `unknown_reason`，不填 0；底图未核项来自哈希验证的结构化数据（`V-02`），模型缺项来自输出本身；二者在 `spatial.source.site_source.unverified_facts` 与 `spatial.unknown_items` 分别登记，不互相冒充。

## 5. 需要架构师决定

- 是否接受 §2 的单一权威版本 + additive 空间段分支；若接受，是否合并进主 schema 的 `oneOf`。
- 是否允许该分支候选进入任何采用/生产链（本批默认禁止）。
- `boundary_source=rkd-site-basemap.v2` 是否纳入主契约枚举（当前只在 v2 分支）。
