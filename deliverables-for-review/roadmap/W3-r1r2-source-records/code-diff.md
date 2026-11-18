# 代码差异说明（来源记录两个 P1）

基线：`f473c92`。完整补丁见 `changes.patch`（`git diff f473c92..本批提交 -- mvp scripts PROJECT_STATUS.md`）。

## `mvp/rkd_mvp/controlled_run_ledger.py`

- 新增 `ObservationScope`（264—300）：一次 provider invocation 的观测句柄，`observations` / `latest()` / `owns()` / `opener()`，带锁。
- `ControlledTransport.send(..., scope=None)`（234—262）：交换完成后把观测记入**该 invocation 的 scope**；不再有「谁最后写谁赢」的读取路径。
- `BoundControlledOpener`（304—322）：构造时绑定一个 scope，`open()` 把 scope 透传给 `send()`；`self.observations` 改为该 scope 的视图。
- `ControlledRunService.begin_invocation(project_id)`（472—480）：产出 scope。
- `issue(..., scope=None)`（541—570）：当调用方带 scope 时校验项目一致与观测归属，违规 `OBSERVATION_NOT_FROM_INVOCATION` / `OBSERVATION_PROJECT_MISMATCH`。
- 模块文档规则 3 改为「父修订必须存在且已提交」，新增规则 6「一次 invocation 一个观测 scope」。

## `mvp/rkd_mvp/controlled_design_runtime.py`

- 新增 `begin_invocation()`（84—92）。
- `register_and_issue(..., scope=None)`（97—135）：**删除 `register_revision` 调用**（R2 根因）；空观测 fail closed（`CONTROLLED_EXCHANGE_MISSING`）；`details` 增加 `revision_id` 供追责与负例定位。
- 新增 `commit_revision()`（155—171）：提交后登记的唯一入口，缺候选摘要即 `REVISION_REGISTRATION_INVALID`。
- 删除 `fresh_observation()`（「取项目最后一条」的入口，已无合法调用方）。

## `mvp/rkd_mvp/ai_design_option_service.py`

- `_run_set`（327—340）：每次 provider 调用前 `scope = controlled_runtime.begin_invocation(project_id)`，provider 只拿 `scope.opener()`。
- `_controlled_finalize(..., scope)`（204—253）：读 `scope.latest()`；把 scope 传给 `register_and_issue`。
- `_run_set` 提交后登记（421—437）：事务 `with` 退出（已提交）之后才逐个 `commit_revision`；失败写 `REVISION_REGISTRATION_FAILED` 并抛错，不补登记、不伪造父链。

## 测试与工具

- `mvp/tests/test_w3_r1r2_source_records.py`（新增）：4 项永久回归，全走组合根 + 公共 API。
- `scripts/w3_r1r2_findings.py`（新增）：before/after 同例 harness，能力探测（`hasattr(runtime, "begin_invocation")` / `inspect.signature(ApiService.__init__)`），使同一脚本能在冻结基线与工作树上运行并给出相反结论。

## 未改动

- 契约 schema、`admission.py`、`realmodel_spatial_adapter.py`、`ai_spatial_outputs*.py`、API 路由、启动脚本、数据库 schema/迁移。
- 组合根接线方式（上一轮 `dbc907e`）保持不变。
