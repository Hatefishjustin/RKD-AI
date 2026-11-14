# W1 版本谱系收口 · 代码差异说明

比较基线：`080f63e`；复核命令 `git diff 080f63e -- mvp contracts scripts`；补丁 `changes.patch`。

总量：3 个既有文件 `+~370 / −~130`，新增 1 个验收脚本 `+540`。**零新增迁移、表、列**。

## 1. `mvp/rkd_mvp/ai_design_option_service.py`（主要改动）

| 位置 | 改动 |
| --- | --- |
| `_lineage_state(tx, option_id, source_parent_uid)`（新增） | 在**调用方事务内**读该候选全部修订，用每条 `model.spatial.source.revision_uid` 建 `source_uid → revision` 映射；父版本由 `parent_revision_uid` 查表得到，不再取 `latest_revision`；返回 `next_revision_no`、父修订、父 `spatial`、`parent_missing` |
| `import_studio_proposal` | 参数新增 `after_prepare`（并发测试接缝）与 `allow_orphan`；请求体也接受 `allow_orphan` |
| 身份 | `option_id = studio:{main}:{studio}:root:{root_revision_uid}`，删除原来按 A/B 字母构造 |
| 谱系解析 | 调 `source.lineage()`；`source_uid_missing` / `source_parent_missing` / `source_lineage_cycle` 分别 422/409/409，不猜 |
| 父链 | 首次读事务给出临时状态；父未导入且未 `allow_orphan` → 409 `SOURCE_PARENT_NOT_IMPORTED`；允许缺父时 `parent=null` + `parent_link_status=source_parent_not_imported`（不回填） |
| `prepare()`（内部函数） | 把"适配 + schema 复验 + unknown 未填值复验 + 渲染 SVG"集中一处，便于并发时在锁内重做 |
| 写事务 | ① 重查同源幂等键，命中即 `reused`（并清理本次自己的目录）；② 重算父与下一版本号；③ 与准备阶段不一致就在锁内重做 `prepare()` 并覆写 SVG；④ 三行同事务 insert；⑤ `on_before_commit` 仍可注入失败 |
| 文件清理 | `attempt_dir` 按本次 `set_id` 独立；`finally` 只在未提交时删除**本次**目录 |
| 返回值 | 增加 `root_revision_uid`、`lineage_chain`、`parent_link_status`、`design_origin`；`diff` 改为相对源父修订 |

## 2. `mvp/rkd_mvp/ai_design_studio_adapter.py`

| 位置 | 改动 |
| --- | --- |
| `StudioProposalSource.lineage()`（新增） | 沿 `parent_revision_uid` 回溯到无父的源修订；缺父/成环分别返回 `source_parent_missing` / `source_lineage_cycle` |
| `StudioProposalSource.design_origin()`（新增） | 只读源产物 `diagnostics.source` 的显式声明 → `real_model`/`human`/`fixture`/`unknown`，附 `declared_by`、原始声明、`run_refs`；未声明即 `unknown` |
| `adapt_proposal()` | 新增 `lineage` / `design_origin` / `parent_link_status` 参数；`spatial.source` 增加 `root_revision_uid`、`lineage_chain`、`parent_link_status`、`design_origin` |

字段映射、精确多边形校验、多边形 SVG、`field_ledger` 与 `losses` 均未改。

## 3. `contracts/v1/ai-design-option.schema.json`

- `$defs.studioSource` 的 `required` 增加 `root_revision_uid`、`lineage_chain`、
  `parent_link_status`、`design_origin`，并新增对应属性约束（`parent_link_status` 三值枚举）。
- 新增 `$defs.designOrigin`（`kind` 四值枚举、`declared_by`、`declaration`、`run_refs`），
  描述明确写"适配器不是 AI，不能把上游真实模型/人工产出改标"。
- 仍是候选文档的**可选** `spatial` 段；根必填项、`additionalProperties`、旧 `shape` 定义未动。

## 4. 新增 / 修改的验收脚本

| 文件 | 改动 |
| --- | --- |
| `scripts/verify_w1_lineage.py`（新增） | 13 项真实 HTTP：独立 A、同根 v1→v2、分叉、乱序、缺父（allow_orphan）、源链断裂、同源并发（Barrier）、同谱系并发（Barrier）、确定性并发接缝 ×2、设计/适配来源分离、精确 spatial 权威、采用 CAS |
| `scripts/verify_w1_unified_model.py` | `save_valid(..., parent_artifact=...)` 写入**真实 `parent_revision_uid`**；A→A2 改成真正的父子链。断言未放宽 |

## 5. 明确没有改的地方

- 没有重做适配器字段映射；没有新增表/列/迁移；`postgres_import.py` 与 PG 迁移未动。
- 没有改 `submit` / `revise` / `adopt` / `status` 的既有逻辑；没有改前端（页面复跑通过）。
- 没有改 `spatial` 精确几何与 `losses` 声明；没有据 bbox 增加任何计量。
- 没有启动 W2 制图/渲染/量价；没有新增外发、付费调用或基础设施。
- 没有改 AD 判定文档、`docs/26` 路线、用户原件与历史复核包。
