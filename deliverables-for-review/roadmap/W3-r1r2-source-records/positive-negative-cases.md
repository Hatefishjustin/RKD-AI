# 正例与负例（来源记录两个 P1）

全部经真实组合根（`ApiService`）与公共 API，真实隔离 SQLite。负例的期望是「明确拒绝并保持可追责」，不是「抛任意异常」。

## R1 并发观测

### 负例（修复前会通过的错绑定）

| # | 构造 | 期望 | 修复前实测 | 修复后实测 |
| --- | --- | --- | --- | --- |
| N1 | 同一项目两组并发 `submit_ai_design_options`，第一次交换带 3MB 填充使解析变慢（第二个调用在第一个「已记录交换、未读取观测」窗口内完成） | 每个持久候选的运行记录只对应自己那次交换 | 同一候选集内两个候选分别绑定到 `A` 与 `B1` 两次交换；两组最终都指向最后那次响应 | 两组各自绑定 `A` / `B1`，同一集内一致，4 个 run_id 互不重复 |
| N2 | 用别的 invocation 的观测签发候选（`register_and_issue(observation=scope_b.latest(), scope=scope_a)`） | 拒绝：`OBSERVATION_NOT_FROM_INVOCATION` | 无 scope 概念，必然接受（读取项目最后一条） | 拒绝 |
| N3 | 该 invocation 没有任何交换，却要签发候选（`observation=None`，空 scope） | 拒绝：`CONTROLLED_EXCHANGE_MISSING` | 会取到项目中**其他**调用的观测（更危险） | 拒绝 |
| N4 | scope 与运行项目不一致 | 拒绝：`OBSERVATION_PROJECT_MISMATCH` | 无此校验 | 拒绝 |

### 正例

| # | 构造 | 期望 | 实测 |
| --- | --- | --- | --- |
| P1 | 一次 invocation 一次成功交换（可含更早的重试） | `scope.latest()` 即该次成功交换；签发记录的 `observation_id`/`response_sha256` 与之一致 | 满足 |
| P2 | 正常候选集（无并发） | 两个候选共享同一次交换，`input_hash` 等于候选集 input_hash，`candidate_sha256` 等于本人不可变来源重算摘要 | 满足 |

## R2 幽灵父修订

### 负例

| # | 构造 | 期望 | 修复前实测 | 修复后实测 |
| --- | --- | --- | --- | --- |
| N5 | 候选已 finalize（完成签发），但业务事务被丢弃（第二个组合根实例对同一库 reclaim 该 running 集 → `WORKER_RESTARTED`/`LATE_RESULT_DISCARDED`） | 业务修订 0 条，账本登记 0 条 | 业务修订 0 条，**账本登记 2 条** | 业务修订 0 条，账本登记 0 条 |
| N6 | 用 N5 里那个 revision_id 作 `parent_revision_id` | 拒绝：`PARENT_UNREGISTERED` | **接受**（幽灵父链可用） | 拒绝 |

### 正例

| # | 构造 | 期望 | 实测 |
| --- | --- | --- | --- |
| P3 | 正常成功的候选集 | 每个修订在提交后都已登记，登记摘要 = 该候选不可变来源摘要 | 满足 |
| P4 | 以已提交的修订作父修订 | 允许（`parent_candidate_sha256` 与登记一致） | 逻辑保持（本轮未改父链校验的通过路径，只改登记时机） |

## 不成立的「通过」

- 候选集 `succeeded` 只表示流程跑完；本轮全部 `simulated=True`、来源 `fixture`，不计 AD01—AD08。
- `run_id` 唯一不等于绑定正确：修复前的基线里 4 个 run_id 也不重复，但两个候选绑到了别人的交换。因此断言落在「响应/请求摘要 + input_hash + 候选摘要 + 同集一致性」上。
- 「账本没有登记」只有在业务仓储确实没有该修订时才算通过；负例同时断言业务侧 0 条，避免只为通过而通过。
- 未启动 HTTP 服务进程、未跑浏览器 UI、未跑 PG 数据面、未调用真实模型，均记 `not_run`。
