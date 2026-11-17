# 契约演进（v1 不变，v2 收紧 + 版本分发）

基线 `2253899` 已有顶层 `rkd-ai-design-option.v2`，但当时 v2 只是"另一份 schema"：服务仍固定加载 v1，v2 只在验证脚本里被检查，且 `site_snapshot.sha256` 实际装的是底图文件摘要。本批做三件事。

## 1. v1 不动

`contracts/v1/ai-design-option.schema.json` 零修改。v1 仍只允许 `test_parameters_not_site_verified` / `manual_boundary_not_site_verified` 两种边界，`boundary.additionalProperties=false`，因此**v1 在结构上无法承载场地快照**——这正是"真实模型候选必须走 v2"的契约理由，而不是执行方偏好。

旧消费者（只注册 v1）对 v2 的行为现在是**显式版本拒绝**：

```
UnsupportedSchemaVersion.code == "UNSUPPORTED_SCHEMA_VERSION"
supported == ["rkd-ai-design-option.v1"]
```

不是"schema 校验碰巧报错"。D-09 用 `ContractRegistry(versions=("…v1",))` 实测该码，同时用真实合成通道产出的 v1 文档验证旧消费者仍通过。

## 2. v2 的三处收紧（additive 但更严格）

| 位置 | 变更 | 原因 |
| --- | --- | --- |
| `properties.site_snapshot` | 存在时必须带 `sha256`、`basemap_files_sha256`、`boundary_mm`、`entrance_assumption`（`kind=concept_replaceable`、`site_verified=false`） | 防止再出现"字段名叫快照、内容其实是底图摘要" |
| `$defs.realmodelSpatialExtension.properties.source.required` | 用 `site_snapshot_sha256` + `basemap_files_sha256` 取代 `boundary_sha256` | 两套摘要分开命名；旧名不再作为来源字段 |
| `$defs.circulation.properties.segments.items` | 允许 `properties`（来源矩形、主轴、精确路径引用） | legacy 段落必须能自证与源矩形可逆，否则又会退化成零宽 |

`generation.schema_version` 仍允许 v1/v2；带快照的 provider 产物写 v2 并同步 `generation.schema_version`。

## 3. 版本分发与准入党

- `admission.ContractRegistry`：版本→schema 注册表。服务构造时注册 v1+v2；`_validate_candidate` 走注册表，未知版本抛 `UNSUPPORTED_SCHEMA_VERSION`。
- `admission.admit_document`：唯一准入党。
  - v1 且 `generation.real_model=true` → `REAL_MODEL_REQUIRES_V2`（不可采用）。
  - v1 合成（边界为测试参数）→ `engineering_only`，可采用，但明确 `site_bound=false`，只作工程桥回归。
  - v2 → 快照绑定（`site_snapshot_sha256` + `basemap_files_sha256`）→ 几何（保留区、入口连通）→ 投影一致性 → 源证据（受控 verifier，逐条 run_ref 核验并绑定同一快照）→ `admitted/site_bound`。
  - 任一失败 → `not_validated`，`adoptable=false`，`ADMISSION_NOT_VALIDATED`。
- 服务采用闸口（`adopt()`）读取修订上的 `validation.admission`；历史修订没有该块时按文档版本回退（v1 合成→engineering；v2 或真实声明→not_validated）。

## 4. 明确没有做的事

- 没有把 v2 声明为"已被架构师接受的权威生产契约"；本批只证明它能被真实服务读写、旧消费者按版本拒绝，是否升级为唯一生产契约由复核裁定。
- 没有删除或改写 v1；没有让旧消费者静默接受 v2。
- 没有为 v2 增加非矩形几何能力声明（`non_rectangular_capability` 仍为 false）。
