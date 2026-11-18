# 代码差异说明（受控反馈修订闭环）

基线：`902952e`。完整补丁见 `changes.patch`（`git diff 902952e..本批工作树 -- mvp scripts PROJECT_STATUS.md`）。

## `mvp/rkd_mvp/ai_design_option_service.py`

- `_controlled_finalize`（`:204-253`）：新增 `parent_revision_id` / `parent_evidence`，透传到 `register_and_issue`，供新 run 绑定父链与父候选摘要。
- 新增 `_feedback_lock_targets`（`:908-925`）、`_check_feedback_locks`（`:927-992`）：锁定令牌解析、v1 源候选与 v2 mm 投影双重锁定核对、场地快照不可改写。
- 新增 `_controlled_revise`（`:994-1166`）：基线绑定 → 新 scope/受控 provider → 新源候选 → 契约/反馈锁定检查 → `_controlled_finalize` 适配与准入 → 父链/来源/运行记录复核 → CAS 写入 → 提交后 `commit_revision`。
- `revise`（`:1169+`）：受控候选走新路径且要求三个基线参数；非受控旧路径保持原矩形反馈语义。
- 新增错误码：`INVALID_FEEDBACK_BASELINE`、`STALE_INPUT_SNAPSHOT`、`STALE_ADOPTION_VERSION`、`STALE_PARENT_REVISION`、`LOCK_FIELD_MODIFIED`、`LOCK_OBJECT_DELETED`、`SITE_SNAPSHOT_MODIFIED`、`PARENT_LINK_UNVERIFIED`、`RUN_REUSE_DETECTED`、`FEEDBACK_UNPARSED`、`FEEDBACK_LOCKS_MISMATCH`、`PARENT_CONTENT_CHANGED`、`REVISION_REGISTRATION_FAILED`。

## `mvp/rkd_mvp/ai_design_option_provider.py`

- `revise()` 新增可选关键字参数 `site`、`brief`（`:1144-1157`）：受控服务传入权威场地快照和本次任务书；不传时保持旧行为。

## `mvp/rkd_mvp/controlled_design_runtime.py`

- `register_and_issue()` 新增 `parent_evidence`（`:102`），provenance 记录父修订 id 与父候选摘要（`:147`）；`scope` 必填与提交后登记语义未改。

## 测试与工具

- `mvp/tests/test_w3_controlled_feedback.py`（新增，9 项永久回归）。
- `mvp/tests/test_w3_composition_root.py`：旧「受控反馈不支持」用例改为「缺基线拒绝且父版保留」。
- `scripts/verify_w3_astra_remediation.py`、`scripts/w3_composition_findings.py`：反馈拒绝断言同时接受 `CONTROLLED_FEEDBACK_PATH_UNSUPPORTED` 与 `INVALID_FEEDBACK_BASELINE`，保持历史 harness 可用。
- `scripts/w3_feedback_revision_findings.py`（新增）：同一公共 API 的 before/after 复现 harness。

## 未改

- 契约 schema、`admission.py`、几何适配器、scope 必填、组合根接线、数据库迁移、PG/NAS、启动脚本、阶段/AD 文档。
