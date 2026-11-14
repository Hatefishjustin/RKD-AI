# W1 统一模型适配 · 代码差异说明

比较基线：`cb84581`；复核命令 `git diff cb84581 -- mvp contracts web`；完整补丁 `changes.patch`。

总量：生产/契约/前端 7 个既有文件 `+~500 / −~10`（其中契约新增 374 行为可选 `spatial` 定义），
新增 4 个文件（1 个适配器 + 3 个验收脚本）。**零新增 SQLite/PG 迁移、表或列**。

## 1. `contracts/v1/ai-design-option.schema.json`

- 根 `properties` 新增**可选** `spatial`（`$ref: #/$defs/spatialExtension`）。
  `required` 列表、`additionalProperties:false`、`schema_version` 常量、`shape{type:"rect"}`
  以及所有旧定义一字未改 → 旧候选文档仍然合法。
- 新增 8 个 `$defs`：`spatialExtension`、`spatialZone`、`unsupportedItem`、`studioSource`、
  `adaptationNote`、`objectIdMap`、`fieldLedgerRow`（以及关联的精确多边形 `polygon_mm` 约束）。
- `spatialExtension` 固定 `unit="mm"`、要求精确分区多边形、材料/天花/家具/动线/视图、
  命名缺项、来源、适配说明、字段对账、面积表与开放问题，`additionalProperties:false`。
- **没有**把 `project_id` 写进契约（勘误 §2 明确主系统契约无此字段），没有放宽必填项。

## 2. `mvp/rkd_mvp/ai_design_studio_adapter.py`（新增，W1 核心）

| 部分 | 内容 |
| --- | --- |
| 常量 | `ADAPTER_VERSION`、`SPATIAL_VERSION`、`MAPPING_VERSION="W0-erratum-2.3"`、`GEOMETRY_RULE_VERSION` |
| `StudioAdaptationError` | 带 `code/message/stage`，在任何写入之前抛出 |
| `validate_source()` | 校验 draft 契约版本、身份字段、单位（显式 mm）、对象 ID 唯一、目录引用、二维多边形点数、动线宽度；拒绝单位错配/缺引用/无法表达几何 |
| `exact_geometry_checks()` | shapely 对**精确 mm 多边形**做 8 项硬检查，专业检查 3 项一律 unknown |
| `adapt_proposal()` | 生成**一份** `rkd-ai-design-option.v1`：legacy `objects[]` 派生包围盒并标 `bbox_derived`；`spatial` 精确保留多边形、动线、平台、家具、天花、材料意图、命名缺项、来源/父版本/哈希；`generation` 记录确定性适配器；`cost` 保持 unknown；`diff` 由 `diff_spatial()` 按同一对象 ID 计算 |
| `_ledger()` | 45 行逐字段映射（mapped / preserved / unknown / unsupported），带源值、目标值、单位 |
| `render_spatial_svg()` | 从 `spatial.zones[].polygon_mm` 画精确多边形（非包围盒），标注源产物、目标版本、缺项 |
| `StudioProposalSource` | W1 唯一的 Studio 只读边界：`get_project` / `resolve_project_id` / `artifact_by_id` / `artifacts`，不直接读 Studio 表 |

## 3. `mvp/rkd_mvp/ai_design_option_service.py`

- `__init__` 新增可选 `studio_source`（懒加载时用 `RKD_STUDIO_DB`），不影响旧构造调用。
- `studio_sources()`：列出可导入的 Studio 有效候选 + 显式项目映射（只读）。
- `import_studio_proposal()`：
  - 单位守卫放在幂等查找之前；显式项目映射检查（`source_project_id` / `resolve`）、
    产物归属与 `contract_status=valid_candidate` 校验、`expected_source_sha256` 校验。
  - `idempotency_key = "studio-import:" + sha256(源项目/产物/sha/适配器/映射/主项目/组织)`；
    命中即返回 `reused=true`，不造版本。
  - 同一 `option_id` 上查最新修订 → `revision_no+1` / `parent_revision_id` / `previous_spatial`。
  - 适配结果经 `jsonschema` 复验 + unknown 未填值复验；写 SVG 到隔离 runtime；
    **单个 write 事务**里 `insert_set` + `insert_revision` + `insert_artifact`；
    `on_before_commit` 是给 W1 回滚测试用的显式故障接缝。
  - 异常时 `shutil.rmtree` 清理 SVG 目录，事务自动回滚；不触碰 `adoptions` / 生产 / 采购 / 发布。
- `list_studio_imports()` / `studio_import_detail()`：来源、父版本、缺项、diff、图面与字段对账。
- 未改 `submit` / `revise` / `adopt` / `status` / `mark_production_status` 的既有逻辑。

## 4. `mvp/rkd_mvp/api_service.py` / `api_server.py`

- `ApiService.__init__` 新增可选 `studio_source` 并透传给候选服务；新增 4 个方法
  （sources / import / imports / detail），导入异常统一转 `ApiError`（含 500 回滚说明）。
- `api_server.py` 新增 3 条 GET 路由 + 1 条 POST 路由；沿用 `re.fullmatch` 与既有
  `do_GET/do_POST` 异常处理，ASGI 复用同一 `ApiRoutes` 不受影响。
- `contracts/v1/openapi.v1.json`：按原排版插入 4 个 operation（16 行新增），未重排历史内容。

## 5. 前端

- `web/src/AiDesignOptionsPanel.tsx`：新增 `StudioSource/ImportItem/LedgerRow` 等类型，
  `studioSources / studioImports / selectedSource / importDetail` 状态；`load()` 并行拉取
  sources 与 imports；`importStudio()` 只发 `studio_project_id / studio_artifact_id /
  expected_source_sha256 / source_project_id / expected_unit`，**不注入结构化目标**；
  `openDetail()` 拉字段对账。新增 `studio-import-panel`（下拉、导入按钮、显式映射、
  已导入版本列表、目标图面链接、45 行对账表、缺项清单、几何模式说明）。
- `web/src/styles.css`：新增对应样式与 700px 窄屏规则。

## 6. 新增验收脚本

| 文件 | 作用 |
| --- | --- |
| `scripts/verify_w1_unified_model.py` | 22 项真实 HTTP / 隔离双库 / A、B 两种布局 / 逐字段对账 / 幂等 / 回滚 / 重启 / 旧格式兼容 |
| `scripts/verify_w1_browser.py` | 隔离主工作台 + 隔离 Studio + 真实 Edge 的驱动 |
| `scripts/verify_w1_browser.cjs` | 页面点击、API/页面/存储版本一致、多边形 SVG、缺项可见、390px 截图 |

## 7. 明确没有改的地方

- `mvp/persistence/sqlite/*`、`mvp/persistence/postgres/*`、`postgres_import.py`、
  `test_postgres_migrations.py`：全部未动（无新表/列/迁移）。
- `ai_design_geometry.py` 的旧 L1 矩形校验器与 `render_svg`：未动，旧合成候选仍按原路径工作（W1-19）。
- `ai_design_option_repository.py`：未动，沿用既有 `insert_set/insert_revision/insert_artifact` 事务。
- `source_kind` 枚举与 DB CHECK：未动；精确来源放在 `spatial.source`，限制见 `contract-mapping.md` §1。
- 用户原件、历史复核包、AD 判定文档、`docs/26` 路线：未动。
