# C2 竞态证据：状态查询误杀刚提交的正常任务

## 缺陷（架构复核指认，本批先原样复现）

`_create_job` 提交事务把任务写成 `queued` 并返回 → `_launch` 才把 job_id 登记进进程内
`_active` 集合 → `recover()` 把「queued/running 但不在 `_active`」判成重启残留，
直接写 `failed/WORKER_RESTARTED`。提交与登记之间的窗口里，任何一次状态查询都会杀死任务。

## 确定性接缝（不用 sleep 碰运气）

复现脚本把 `AISpatialOutputService._launch` 替换为：

```
提交事务已提交（任务=queued） ──► [接缝] 先发一次真实 HTTP GET /spatial-outputs?job_id=…
                              ──► 再调用原 _launch 登记并启动 worker
```

GET 走真实回环 HTTP、真实 handler，对库只读、不修改任何业务状态；
时序由接缝决定，与机器快慢无关。取消场景在同一接缝里插入一次真实 POST cancel。

## 整改前（工作树 = 82d2a66，`repro-before.json`）

| 用例 | 接缝时 GET 看到的状态 | 最终状态 |
| --- | --- | --- |
| W2C2-C2-01 | `failed` / `WORKER_RESTARTED` | `failed`（正常任务被误杀） |
| W2C2-C2-02 | `failed` / `WORKER_RESTARTED` | 随后取消返回 409 `CANNOT_CANCEL`（任务已被误杀，取消语义被破坏） |

## 修法（最小实现，不新增管理平台）

任务创建时把 `run_instance`（本进程实例标记）写进 `config` 并随事务持久化；
`recover()` 只回收 **`run_instance` ≠ 当前实例** 的 queued/running 任务。
"本进程刚提交、还没登记进 `_active`" 的任务属于当前实例，不再被回收；
`_active` 集合不再参与恢复判定。类型过滤不变（只回收 `config.kind=spatial_outputs`）。

## 整改后（`repro-after.json`）

| 用例 | 接缝时 GET 看到的状态 | 最终状态 | 断言 |
| --- | --- | --- | --- |
| W2C2-C2-01 | `queued`（无 error_code） | `succeeded` | 正常任务存活 |
| W2C2-C2-02 | `queued` → cancel 200 | `cancelled`，无成果登记，显式重试后 `succeeded` 且 `config.retry_of` 指原任务 | 取消在同一窗口仍生效、不复活、可重试 |
| W2C2-C2-03 | — | 真正遗留任务（`run_instance=spatial-worker-dead-…`）被标 `failed/WORKER_RESTARTED`；本实例渲染中任务不被回收（恢复时仍 `running`，最终 `succeeded`）；`ai_development_production` 类型的 running 任务原样不动 | 恢复只认上一实例、不波及其他类型 |

## 边界（如实）

- 多进程部署（两个**同时存活**的实例）不在此保证范围：第二个实例会把第一个实例的任务
  当成遗留。原实现同样不能区分，本批不宣称解决了它；需要真实租约/互斥时另立工作项。
- 不重做 R1 打包架构；R1 的 6 项在原 15 项回归中继续通过。
