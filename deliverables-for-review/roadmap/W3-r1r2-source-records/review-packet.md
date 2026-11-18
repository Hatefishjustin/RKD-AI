# W3 来源记录两个 P1 整改复核包（R1 并发观测串线 / R2 幽灵父修订）

基线提交：`f473c92b2ee8f88ed4e7af61adb4d7ad53b07fb8`（上一轮 R1 组合根接线交付）。
本轮代码提交：见 `commit-reference.md`（提交后生成，避免写死易变 HEAD）。
复核输入：针对 `dbc907e` / `f473c92` 的两条 P1 意见（并发观测串线、幽灵父修订）。这是审查意见，不是设计验收意见。

**这不是设计批准、不是客户成果、不放行真实模型试验、不推进阶段 2/3 或 W4，不改 AD01—AD08 与阶段确认。**

旧包 `W3-astra-r1-composition/`、`W3-astra-remediation/`、`W3-control-trust-remediation/`、`W3-adapter-remediation/`、`W3-trust-architect/`、`W3-trust-remediation/` 及更早证据只读保留，一字未改。底图原件 `deliverables-for-review/roadmap/W2-R4-表达收口/basemap/` 未改（`git status` 无变化）。本批运行写入新目录 `var/evidence/roadmap/W3-r1r2-source-records/`。

## 1. 结论先说

两条意见都成立，且都能在冻结基线 `f473c92` 上稳定复现：

- **R1**：`_controlled_finalize` 用 `runtime.run_service.controlled_observations(project_id=…)` + `fresh_observation()` 取「该项目最后一条观测」。同一项目两个并发 provider invocation 时，其中一个候选会被签到另一个调用的交换上——基线实测里**同一个候选集内的两个候选分别绑定到两次不同交换**。
- **R2**：`register_and_issue` 在适配/准入/业务事务**之前**调用 `run_service.register_revision`。业务写入被丢弃后，账本仍留着这两个修订，后续拿它当 `parent_revision_id` 能通过 `PARENT_UNREGISTERED` 检查。

修复后同例复跑：三项检查全部 fixed，永久回归 4/4 通过。

## 2. 修复位置（文件 + 行号）

完整清单见 `outputs/entrypoints.json`。

**R1 每次 provider invocation 独立观测句柄**

| 位置 | 行号 | 作用 |
| --- | --- | --- |
| `mvp/rkd_mvp/controlled_run_ledger.py` | 264—300 | 新增 `ObservationScope`：`observations`/`latest()`/`owns()`/`opener()` |
| 同上 | 234—262 | `ControlledTransport.send(..., scope=)`：交换完成后只记入本次 invocation 的 scope |
| 同上 | 472—480 | `ControlledRunService.begin_invocation(project_id)` |
| 同上 | 557—566 | `issue(scope=…)` 归属校验：`OBSERVATION_NOT_FROM_INVOCATION`、`OBSERVATION_PROJECT_MISMATCH` |
| `mvp/rkd_mvp/controlled_design_runtime.py` | 84—92 | 组合根 `begin_invocation()`（生产唯一入口） |
| 同上 | 97—113 | `register_and_issue(..., scope=…)`；观测缺失即 `CONTROLLED_EXCHANGE_MISSING` |
| `mvp/rkd_mvp/ai_design_option_service.py` | 327—340 | `_run_set` 每次调用建 scope，provider 只拿 `scope.opener()` |
| 同上 | 204—253 | `_controlled_finalize(..., scope=…)` 读 `scope.latest()`；`fresh_observation` 已删除 |

设计要点：一次 invocation = 一次 scope；provider 重试产生的更早观测留在同一 scope 里，`latest()` 取成功的最后一条；跨 scope 的观测一律拒绝，不再有「项目最后一条」这条路。

**R2 只有业务候选提交后父链才可验证**

| 位置 | 行号 | 作用 |
| --- | --- | --- |
| `mvp/rkd_mvp/controlled_design_runtime.py` | 97—135 | `register_and_issue` **不再**登记修订；把 `revision_id` 写进运行记录 `details` 便于追责 |
| 同上 | 155—171 | 新增 `commit_revision(project_id, revision_id, candidate_sha256)`：提交后登记的唯一入口，必须带不可变来源摘要 |
| `mvp/rkd_mvp/ai_design_option_service.py` | 421—437 | `_run_set` 在仓储事务提交**之后**才 `commit_revision`；登记失败标 `REVISION_REGISTRATION_FAILED` 并抛错，不伪造父链 |
| `mvp/rkd_mvp/controlled_run_ledger.py` | 23—28 | 账本规则 3 更新为「父修订必须存在且已提交」 |

## 3. 前后同例实测

harness：`scripts/w3_r1r2_findings.py`。只走 `ApiService` 组合根公共 API + 真实 `ControlledDesignRuntime` + 真实隔离 SQLite；基线用 `git archive f473c92 mvp contracts scripts fixtures deliverables-for-review/roadmap/W2-R4-表达收口` 冻结到 `var/evidence/roadmap/W3-r1r2-source-records/before/`。

| 检查 | before（f473c92） | after（本批） |
| --- | --- | --- |
| `R1-binding`：同项目两个并发调用，每个持久候选的 run_id/请求/响应/input_hash/候选摘要对应自己那次调用 | **同一个候选集内两个候选绑定了两次不同交换**；两组调用全部落到最后那次响应（`B1`） | 两组各自绑定自己的响应（`A` / `B1`），4 个 run_id 互不重复，候选摘要均等于本人不可变来源摘要 |
| `R1-scope`：按 invocation 的句柄 + 缺失/串用观测 fail closed | 无 `begin_invocation`（只能取项目最后一条） | 外部观测 → `OBSERVATION_NOT_FROM_INVOCATION`；空观测 → `CONTROLLED_EXCHANGE_MISSING`；本人观测签发成功且 `response_sha256`/`observation_id` 与本次交换一致 |
| `R2-phantom`：强制候选持久化失败后，该 revision_id 不得作为父修订 | 业务修订 0 条，账本仍登记 **2** 条；以该 id 作父链**被接受** | 业务修订 0 条，账本登记 **0** 条；父链尝试 → `PARENT_UNREGISTERED` |

原始 JSON：`outputs/findings-before.json`、`outputs/findings-after.json`（同 schema `rkd-w3-r1r2-source-records.v1`，含 `external_calls=0`、`cost_cny=0`、`keys_used=false`）。

退出码即断言：before `--expect vulnerable` → 3/3 vulnerable、退出 0；after `--expect fixed` → 3/3 fixed、退出 0；任一项反向返回 2。

## 4. 永久回归测试

`mvp/tests/test_w3_r1r2_source_records.py`，**4 项**（修复前 3 失败 1 通过，修复后 4/4 通过）：

1. `test_concurrent_invocations_each_bind_their_own_exchange` —— 同项目两组并发 submit，逐候选断言：run 记录的 `response_sha256` 是本人调用那次交换、`request_sha256` 是实际发出的请求、`input_hash` 等于本人候选集的 input_hash、`candidate_sha256` 等于本人不可变来源重算摘要；同一候选集内不得绑到两次交换；两组必须各自绑定不同响应。
2. `test_observation_scope_isolated_and_missing_fails_closed` —— 两个 scope 互不共享观测；空观测 `CONTROLLED_EXCHANGE_MISSING`；他人观测 `OBSERVATION_NOT_FROM_INVOCATION`；本人观测签发成功且绑定本次交换。
3. `test_phantom_parent_revision_rejected` —— 真实制造「finalize 之后业务写入被丢弃」（第二个组合根实例对同一库 reclaim 该 running 集，触发 `WORKER_RESTARTED`/`LATE_RESULT_DISCARDED`）：业务修订 0、账本登记 0、以该 revision_id 作父链 → `PARENT_UNREGISTERED`。
4. `test_registration_happens_only_after_commit` —— 正例：成功候选集的每个修订都已登记，且登记摘要等于该候选不可变来源摘要。

测试全部经真实组合根与公共 API；对仓储只做只读查询（`revisions_for_set`）和只读 SQL（确认集合/状态），不手工插入记录。

## 5. 测试运行

- 新回归 `test_w3_r1r2_source_records.py`：**4/4 OK**
- 组合根回归 `test_w3_composition_root.py`：**7/7 OK**
- 设计候选 `test_ai_design_options.py`：**8/8 OK**
- 上一轮 Astra 回归 `test_w3_astra_remediation.py`：**4/4 OK**
- 全量单测：**277/277 OK**（上一批 273 + 本轮新增 4；日志 `var/evidence/roadmap/W3-r1r2-source-records/after/full-regression.log`）
- **not_run**：HTTP 服务进程级下载、浏览器 UI、PG 数据面、真实模型调用（0 授权/0 费用/0 密钥）、正式采用/发布、跨机验签、专业签核

## 6. 残余限制（请复核）

1. **登记失败的两阶段窗口**：`commit_revision` 在业务事务提交之后执行，写的是账本文件（非事务性）。若进程在「已提交、未登记」之间崩溃，业务修订存在但父链不可用——方向是 fail closed（后续父链被拒），不会伪造父链；但该候选也无法再当父修订，需要重跑。本批不做跨存储事务，也不扩 NAS/账号。
2. **幽灵父修订的等价验证**：负例通过「第二个组合根实例 reclaim 同一 running 集」制造提交前丢弃（真实业务路径、公共 API），不是直接往库里插一条失败记录；断言点同时覆盖「业务修订 0 条」与「账本登记 0 条」，避免只测一侧。
3. **每 invocation 一次成功交换的假设**：`scope.latest()` 取该次调用最后一条交换（重试更早的观测留在同一 scope）。若将来一个 invocation 内为多个候选各发一次请求，需要按候选下标绑定（本批 provider 是一次响应产出两个候选，未引入该形态）。
4. **`controlled_observations()` 仍在**：作为审计视图保留，但已无任何候选签发路径使用（签发必须带 scope 归属校验）。若认为应彻底移除，需架构师裁定。
5. 全部候选来源 `fixture`、`simulated=True`，不计 AD01—AD08，不是 AI 自动设计、不是客户成果。

## 7. 没有做什么

- 未改合同/契约 schema、准入判定口径、成果完整性判定、组合根接线方式。
- 未放宽任何检查；未把桩结果说成真实模型；未让「跑完」等于「方案通过」。
- 未扩 W4、管理配套、账号/NAS/KMS；未改 AD01—AD08、阶段确认、未知项与正式责任边界。
- 未调用任何外部模型，费用 0、外发 0、未使用真实密钥。
