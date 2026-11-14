# W1 字段映射表（按 W0 勘误 §2.3 与三份实际 schema）

依据：`deliverables-for-review/roadmap/W0-收口/evidence-provenance-erratum.md` §2；
`contracts/v1/spatial-plan-proposal.schema.json`（模型提案，无身份字段）、
`contracts/v1/spatial-plan-draft.schema.json`（程序装配的 Studio 交接文档）、
`contracts/v1/ai-design-option.schema.json`（主系统候选，W1 增加**可选** `spatial` 段）。

**归属**：主系统拥有有效模型、采用指针与派生成果；Studio 只保留协作记录与提案。
W1 没有新增第三套权威模型：`spatial` 是 `rkd-ai-design-option.v1` 文档内的可选投影段，
所有版本、采用、成果仍走主系统既有 `ai_design_option_*` 四张表（**零新增迁移/表/列**）。

## 1. 版本键与身份（勘误要求的显式映射）

| Studio proposal | Studio draft（程序注入） | 主系统候选 | W1 处理 |
| --- | --- | --- | --- |
| 无版本键 | `contract_version` = const `rkd-spatial-plan.v1` | `schema_version` = const `rkd-ai-design-option.v1` | 两套版本键并存，均在 `spatial.source.draft_identity` / `generation.schema_version` 留痕，互不覆盖 |
| 无 `project_id` | `project_id`（Studio 内部 id，如 `ningbo-xiecheng`） | **契约里没有 `project_id`**（`additionalProperties:false`） | 绝不写入文档；用 `source.resolve_project_id()` 显式映射到主系统 `project_id`，并写入 `spatial.source.{studio_project_id,main_project_id}`；跨项目引用 409 |
| 无 `option_id` | `option_id`（`^[A-Z]$`） | `option_id`（任意非空字符串） | 稳定 `studio:{main_project_id}:{studio_project_id}:{option_id}`，含主系统项目 id 以避免跨项目主键冲突；候选组仍用 `set_id` |
| 无 `revision` / `parent_revision` | `revision`（int）/ `parent_revision`（int\|null） | `revision_no`（int）/ `parent_revision_id`（string\|null） | int 版本号与字符串版本 ID 分开：`revision_no` 由导入链自增，`parent_revision_id` 指向上一条 `option_revision_id`；Studio 的 `revision_uid`/`parent_revision_uid` 原样存在 `spatial.source` |
| 无批准/采用字段 | 无 | `lifecycle_status` / `publication_status` / `formal_quote` | 导入一律 `candidate` + `not_approved` + `formal_quote=false`；不写 `adoptions` 表 |

> **已知的粗粒度枚举限制（如实记录）**：DB 列 `source_kind` 的 CHECK 只有
> `synthetic_design_adapter / real_model / human_feedback / human_edit`。为了不新增迁移、
> 不改旧契约语义、不制造第三套权威表，导入修订的列值沿用 `human_edit`（人工触发的显式导入，
> 非模型生成），**精确来源**由 `spatial.source.origin_kind = "studio_import"`、
> `generation.provider_kind = "studio_proposal_adapter"` 与 `generation.input_hash`（源字节哈希）
> 共同承担。W1 没有把 Studio 来源伪装成真实模型调用。

## 2. 单位、坐标与几何

| Studio 字段（mm / ㎡） | 主系统落点 | 换算 / 精度 |
| --- | --- | --- |
| `zones[].polygon` 点列（mm） | `spatial.zones[].polygon_mm`（**原样保留**） | 1:1，含非矩形 5 点轮廓；不离散、不取包围盒代替 |
| `zones[].polygon` | `objects[].shape`（legacy rect，m） | 派生包围盒，`objects[].properties.geometry_mode="bbox_derived"` + `exact_polygon_ref`；`spatial.adaptation.losses` 明列 `bounding_box_only`，**不宣称精确、不据包围盒算量** |
| `zones[].area_sqm` | `spatial.zones[].area_sqm` + `spatial.area_table` | 原样保留，标记 `area_source = studio_area_table_not_program_measured` |
| `circulation[].width_mm` | `circulation.min_width`（m，十进制字符串） | /1000；精确折线与原始 mm 宽度保存在 `spatial.circulation[].path_mm` |
| `circulation[].path` | `circulation.segments[].shape`（legacy rect） | 线段包围盒，标记 `centerline_bbox_only`；精确折线在 `spatial.circulation[]` |
| `furniture[].{x,y,rot}` | `spatial.furniture[].{x_mm,y_mm,rot}` | 原样 mm / 度；legacy 对象按目录 `w_mm/d_mm` 与旋转占地派生包围盒 |
| `furniture[].catalog_id` | `spatial.furniture[].catalog_id` + `objects[].properties.catalog_id` | 目录内真实尺寸；不存在的目录 id → 422 `UNKNOWN_CATALOG_REF` |
| `platforms[].{polygon,corner_radius_mm,height_mm}` | `spatial.platforms[]` | 原样 mm；圆角是造型参数，不自动变实体墙/工程量 |
| `site.{width_mm,height_mm,entrance}` | `boundary.{width,length,unit="m",entrance}` | /1000；入口侧来自结构化场地条件（西墙 `left`），`boundary_source=manual_boundary_not_site_verified` |
| `site.{stair,bath}` | `boundary.obstacles[]` | 结构化保留区，标 `keepout=true`；不是实测现场事实 |

**几何校验**：`exact_geometry_checks()` 用 shapely 对**精确 mm 多边形**做 8 项硬检查
（有效多边形、边界内、精确非重叠、最小面积、对象 ID 唯一、动线在界内且宽度 ≥900mm、
家具定位在界内、入口来自场地条件），写入 `validation.rule_version = rkd-studio-import-geometry.v1`。
`professional_checks` 三项一律 `unknown`（消防疏散 / 无障碍 / 实测门洞净宽），不宣称合规。

## 3. 材料、天花、视图、成本与缺口

| Studio 字段 | 主系统 / `spatial` 落点 | 状态 |
| --- | --- | --- |
| `strategy.{name,narrative,tradeoffs}` | `strategy.{strategy_id,statement,tradeoffs,source_refs}` | mapped；`source_refs` 用真实 Studio 产物 id |
| `ceiling.{strategy,coves,fixtures}` | `spatial.ceiling`（原样含 `kelvin`、点位） | preserved 为**意向**；主系统候选契约没有天花/灯具对象，不塞进 `objects[]` |
| 材料规格 / 产品选型 / 样板 | `materials[]` 只放一条 `studio-material-unspecified`；`spatial.materials[]` 记录目录引用 | `unknown` + 命名 `unsupported_items`；不补默认值 |
| 相机 / 人眼视图 / 视向 | `spatial.views = []` | 命名缺项 `相机与人眼视图`（unknown），**不生成假设机位** |
| 照度 / 配光 / 间距 | 无数值 | 命名缺项 `照度/配光计算`；色温是意向，不是计算结果 |
| 实测标高 / 层高 | `spatial.source.site_source.ceiling_mm`、`spatial.platforms[].height_mm` | 给定条件/造型参数，不升级成实测事实；命名缺项 `实测标高/层高` |
| 门窗 / 柱网 / 构造 | `site.windows_*` 仅作为场地条件留在 `spatial.source.site_source` | 命名缺项；不凭空补构件 |
| `area_table` | `spatial.area_table` + `cost.unknown_items` | 原样保留；程序不采信模型合计，不生成完整项目估价 |
| `open_questions` | `spatial.open_questions` / `spatial.unknown_items` / `cost.unknown_items` | `value=None`、`known_status="unknown"`，**不填 0** |
| 预算 / 总价 | `cost.budget` / `cost.total_project_estimate` | `value=None` + `unknown_reason`；`formal_quote=false` |

## 4. 来源、父版本与逐项对账

| 项 | 落点 |
| --- | --- |
| 源产物 id / `sha256` / `revision_uid` / `parent_revision_uid` / `run_id` / `candidate_group_id` | `spatial.source`（`origin_kind="studio_import"`） |
| 源字节哈希 → 运行记录 | `generation.input_hash`（源文档字节哈希）；`config_hash` 为适配器/映射版本哈希 |
| 幂等键 | `studio-import:` + sha256(源项目 + 产物 id + sha256 + 适配器版本 + 映射版本 + 主系统项目 + 组织) |
| 父版本 | `parent_revision_id` = 同一 `option_id` 上一条 `option_revision_id`；旧版本与旧 SVG 字节保留 |
| 对象 ID 映射 | `spatial.adaptation.object_id_map`（源 id → 目标 id → group），**保持同名稳定 ID** |
| 字段对账 | `spatial.adaptation.field_ledger`（source_field / target_field / object_id / source_value / target_value / unit / status ∈ mapped\|preserved\|unknown\|unsupported），本次每份布局 45 行 |
| 几何模式与损失 | `spatial.adaptation.geometry_mode = polygon_exact_in_spatial_bbox_derived_in_legacy_objects` + `losses[]` |
| 单位换算 | `spatial.adaptation.unit_conversion = mm_to_m_div_1000`；`spatial.unit = "mm"`；`boundary.unit = "m"` |

## 5. 明确拒绝 / 不静默处理的情况

| 情况 | 返回 | 不写入 |
| --- | --- | --- |
| 调用方声明单位不是 mm，或源文档声明 `unit != mm` | 422 `UNIT_MISMATCH` | set / revision / artifact / SVG |
| 目录引用不存在、对象缺 id/坐标 | 422 `UNKNOWN_CATALOG_REF` / `MISSING_OBJECT_REFERENCE` | 同上 |
| 多边形点数 <3、点非二维数值、自交/面积为零/越界/精确重叠 | 422 `UNSUPPORTED_GEOMETRY` / `GEOMETRY_CHECK_FAILED` | 同上 |
| 项目映射不显式一致、产物跨项目、源 sha 不符、非有效候选 | 409 / 422 对应错误码 | 同上 |
| 适配中途异常（文件已写、事务未提交） | 500 `STUDIO_IMPORT_FAILED`，单事务回滚 + 清理 SVG 目录 | 同上 |

## 6. W1 没有做的事

- 没有把多边形改成矩形后称无损；没有生成相机、材料规格、照度或实测数值。
- 没有改 `ai-design-option` 的必填项，没有放宽 `additionalProperties:false`（只新增可选 `spatial`）。
- 没有新增 SQLite/PG 迁移、表或列；`postgres_import.py` 白名单与快照版本范围**未改动**。
- 没有把 Studio 提案说成系统模型自动设计；本批源是明确标记的本地测试夹具。
- 没有触发采用、生产同步、量价、采购、批准或发布。
