# 唯一权威契约演进方案（P2-4）

编制：2026-11-16。基线 `4d2ac76`；交架构复核。**不是已批准的正式接入，实验分支仍不可采用。**

## 1. 上一方案为什么被退回

上一批用 `rkd-ai-design-option.v1` 顶层版本 + 调用方选择另一份 `realmodel-spatial-option.schema.json`。同一文档按旧主 schema 校验仍有 26 项错误；消费者只加载旧主契约，因此既不是"单一权威版本"，也不是"additive 兼容"。本批同例复跑保留该证据（`before/repro/repro.json`：legacy_error_count=26、has_top_level_version_bump=false）。

## 2. 本次方案：显式顶层版本 v2

- 新增 `contracts/v2/ai-design-option.schema.json`，`schema_version` 的 `const` 为 **`rkd-ai-design-option.v2`**（可识别的顶层新版本）。
- v2 是 v1 的**版本化修订**：保留 v1 全部字段与含义；以 `spatial.oneOf` 正式纳入两个分支：
  1. Studio 投影 `rkd-ai-design-option-spatial.v1`（旧消费者熟悉的内容，v2 仍接受）；
  2. 真实模型适配 `rkd-realmodel-spatial.v1/.v2`（本批产物）。
- `boundary_source` 增列用户确认的 `rkd-site-basemap.v2`；`generation.schema_version` 接受 v1/v2；新增可选审计字段 `site_snapshot`、`source_revision`、`mapping_losses`，均非必填。
- 适配器输出声明 `schema_version=rkd-ai-design-option.v2`；持久化输入仍接受 v1（历史）与 v2。
- **旧 `contracts/v1/ai-design-option.schema.json` 未修改**：旧文档继续原样通过；旧消费者按 `schema_version` 遇到未知 v2 时明确拒绝，而不是被调用方偷偷换成另一份同名 schema。

## 3. 消费者 / 持久化 / 采用边界与回归证据

| 项 | 证据 | 结论 |
| --- | --- | --- |
| v2 schema 合法且版本可识别 | C-01 | pass |
| v1 文档仍由旧 schema 校验 | C-08（legacy_v1_errors=0） | pass |
| v2 文档按版本号被旧消费者拒绝 | C-08（v2_under_legacy_error_count>0） | pass：显式版本识别，非双验证器 |
| v2 候选通过唯一 v2 契约 | C-070 / C-071（0 错误） | pass |
| 存储路径 | C-04：真实 SQLiteAIDesignOptionRepository 写入读回（隔离库） | pass，仅隔离库 |
| 正式采用链 | 未测 | **未打通/禁止**：实验分支 `lifecycle_status=candidate`、`publication_status=not_approved` |

## 4. 迁移与 unknown 语义

- 迁移：新消费者按 `schema_version` 选择 v1/v2 验证器；v2 文档保持 v1 全部必填字段，旧字段含义不变；新增字段可缺省。
- unknown：底图未核项来自哈希验证的结构化数据；模型缺项保持 `value=null` + `unknown_reason`，不填 0；两者分列于 `site_snapshot.unverified_facts` 与 `spatial.unknown_items`。
- 真实性不可确认：`design_origin.kind` 保持 `unknown` / `fixture`；`real_model` 只能由受控账本中 `kind=real_model_run, simulated=false` 且验签/项目/父链一致的记录支持。本批 0 条此类记录。

## 5. 待架构决定

是否批准 `rkd-ai-design-option.v2` 为唯一权威版本并纳入正式消费者；旧 schema 是否转为只读历史；何时、以何权限允许实验分支进入持久化/采用链。执行方不自行宣布通过。
