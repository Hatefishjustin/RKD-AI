# 代码差异说明（scope 必填小范围收尾）

基线：`9dca78b`。完整补丁见 `changes.patch`（`git diff 9dca78b..本批提交 -- mvp scripts PROJECT_STATUS.md`）。

## `mvp/rkd_mvp/controlled_run_ledger.py`

- `issue(..., scope: ObservationScope)`：`scope` 从 `ObservationScope | None = None` 改为**无默认值**的必填关键字参数。
- 新增入口校验：`scope is None` → `RunLedgerError("OBSERVATION_SCOPE_REQUIRED")`；`not isinstance(scope, ObservationScope)` 或句柄不属于本服务的 transport → `OBSERVATION_SCOPE_INVALID`。
- 原 `if scope is not None:` 包裹的项目一致性 / 观测归属校验改为无条件执行（`OBSERVATION_PROJECT_MISMATCH` / `OBSERVATION_NOT_FROM_INVOCATION`）。
- 效果：只带观测、不带 scope 的旧调用不再可能静默通过。

## `mvp/rkd_mvp/controlled_design_runtime.py`

- `register_and_issue(..., scope: Any)`：从 `scope: Any = None` 改为必填；显式 `None` → `OBSERVATION_SCOPE_REQUIRED`；仍把 scope 原样透传给 `run_service.issue()`。
- 生产调用方 `AIDesignOptionService._run_set` 已传 scope，无需改动。

## `scripts/w3_astra_findings.py`

- 当前代码分支不再用 `transport().send()` 后从项目级观测列表取值，改为 `begin_invocation(PROJECT)` → `scope.opener().open()` → `scope.observations`，并把 `scope` 传给 `issue()`。
- 冻结基线分支（`hasattr(run_service, "begin_invocation")` 为假）保持原行为，确保历史 before 证据仍可复现。

## `mvp/tests/test_w3_r1r2_source_records.py`

- 新增 `test_issuance_rejects_omitted_or_null_scope`：省略 scope（两个 API）、显式 `None`（两个 API）、异服务 scope、带正确 scope 正例；断言被拒调用未留下登记。

## 新增工具

- `scripts/w3_scope_required_findings.py`：scope 必填的 before/after 同例 harness；同时验证真实 ApiService 组合根仍生成并采用候选（`product_path_also_passes`）。

## 检查过但未改的调用点

- `scripts/w3_trust_findings.py`、`scripts/verify_w3_trust_remediation.py`：旧版 before-only harness，使用已关闭的 `observe_exchange` / 旧 `ControlledRunLedger`；当前树上在 `OBSERVE_EXCHANGE_CLOSED` 处即终止，走不到 `issue()`，不改其基线语义。
- `scripts/w3_r1r2_findings.py`：能力探测分支在当前树已带 scope，冻结基线仍按旧签名调用。
