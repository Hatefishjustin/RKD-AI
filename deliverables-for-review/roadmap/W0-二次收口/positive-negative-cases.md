# W0 二次收口 · 正负例与预期-实际对照

所有条目都是**实际执行**结果，不是设计意图。三类证据分开列：
(A) 缺陷复现/修复签名 17 项、(B) 真实 HTTP 15 项、(C) 真实浏览器路径 1 条链路 9 个观察点。

- 复现脚本：`scripts/w0b_repro.py --phase before|after --out <path>`，纯函数/Store 级，隔离临时库，**0 模型调用**。
- 整改前执行：2026-11-14T12:54:07+08:00，`git_head=0524d3d`，结果 `before/repro.json`。
- 整改后执行：2026-11-14T13:24:45+08:00，`git_head=0524d3d`（工作区含本批改动），结果 `after/repro.json`。

## A. 缺陷复现与修复签名（17/17 → 17/17）

判定签名：`defect_reproduced`（旧实现确实有这个问题）/ `fixed_signature`（新实现的行为签名正确）/
`not_observable` / `crashed`。整改前合计 `defect_reproduced=17, fixed=0, crashed=0`；
整改后 `defect_reproduced=0, fixed=17, crashed=0`。

| 用例 | 缺陷（架构师项） | 整改前实际观测 | 整改后实际观测 |
| --- | --- | --- | --- |
| F01-a | 旧反馈在最新一条被执行后复活（F01） | 先选较新留言执行 revise，再选较旧留言仍返回 `revise`（`after_latest_consumed_feedback=older`） | 返回 `feedback_already_consumed` 冲突，旧留言不复活 |
| F01-b | 已消费历史封死新的生成意图（F01） | 新留言被判定 `conflict/feedback_already_consumed`，无法再生成 | 识别为显式 generate 意图，正常生成，并记录被覆盖的历史留言 |
| F01-c | 跨候选两条待续改被无声合并/丢弃（F01） | `kind=revise`、`pending_listed=null`，较新一条被静默采用 | `multiple_pending_feedback` 冲突 + `pending_feedback` 列出两条，要求先决定 |
| F01-d | 同基线多条未显式合并（F01） | `merged_feedback_ids=[]`（实际只消费一条） | `merged_feedback_ids=[fb_98051fcc09, fb_c4bec30173]`，同 run 一次性消费 |
| F01-e | 自动返工未按设计试验累计（F05 附带） | `trial_key=null`、`auto_rework_used=null`、runs 无该两列 | `trial_key` 有值、累计值随设计试验持久化，新 run 继承 |
| F02-a | 多对象只一个达标即 pass（F02） | 只 F1 达标即 `objective_rechecked=pass, resolved=true`，无 `targets/passing/failing` 明细 | `fail`，`passing=[F1]`、`failing=[F2]`、量词 `all` |
| F02-b | 点名对象不存在仍 pass（F02） | `pass` + `resolved=true` | `fail`，`missing_object_ids=[F2]`，文案"对象缺失不算达标" |
| F02-c | 只有无关对象恰好达标即 pass（F02） | 命中 F3 即 `pass` | `fail`，目标对象集与命中对象集分开记录 |
| F02-d | 比较符被忽略（F02） | `min 2300` 与 `exact 2300` 都判 `pass`，无 `comparator` 记录、无 `coverage` | 五个目标给出 `min=pass / exact(相等)=pass / exact(不等)=fail / max(上限内)=pass / max(超上限)=fail`，逐条记录 `comparator` 与 `coverage` |
| F03-a | 保留非入口对象却校验入口锁（F03） | 改动 ZA5 仍 `rechecked=pass, resolved=true`，`target_objects=null` | `fail`，冲突对象为 ZA5 本身 |
| F03-b | 未绑定的保留要求被当通过/降级成空泛意见（F03） | 只剩 `aesthetic` 兜底（`preserve_count=0`），保留诉求本体丢失 | 保留目标存在、`binding_status=unresolved`、`unknown`+`pending`，原句留痕 |
| F03-c | 只有保留诉求时诉求被丢弃（F03） | `kinds=["aesthetic"]`、`has_preserve=false` | `kinds=["preserve"]`，保留目标保留 |
| F03-e | 混合留言的保留诉求被数值目标吞掉/未绑对象（F03） | `preserve_object_ids=[[]]`、`preserve_binding=[null]` | `preserve_object_ids=[["ZA5"]]`、`binding_status=resolved` |
| F04-a | 锁 x 也拦下改 rot、未知字段无诊断（F04） | 只改 `rot` 也报 1 条冲突；`x` 变更的 `changed_fields=null`；删除无 `object_deleted` 诊断 | 只改 `rot` → 0 冲突；改 `x` → 1 冲突且 `changed_fields=[["x"]]`；删除 → `object_deleted`；未知字段 → `unsupported_fields` |
| F04-b | 四级校验把字段锁升级为整对象锁（F04） | `stage=locks` 报"锁定对象 F1 在修订中被改动或删除"，`mode=whole_object_ids` | `stage=passed`、`mode=structured_fields`、`accepts_structured_locks=true` |
| F05-a | 状态混拼两个时间点（F05） | 快照里 `run_status=succeeded` 但 `artifacts_for_run=0`（实际该 run 有 1 份产物），`consistent=false` | `project_state(barrier=...)` 单事务内 `run_status=running`、`artifacts_for_run=0`；事务外再读为 1，`consistent=true`，`has_snapshot_meta=true` |
| F05-b | 只能靠 `runs[-1]` 猜本轮（F05） | 无按 run 的读取入口 | `run_snapshot(project, run)` 存在，`GET /runs/<id>` 可用 |

## B. 真实 HTTP 正负例（15 项全 pass）

命令：`PYTHONPATH="mvp;scripts;." .venv/Scripts/python.exe scripts/verify_w0b.py`
环境：真实 Studio HTTP（`127.0.0.1`）+ 隔离 SQLite `runtime/w0b-verify.db` + 标注的本地模型桩；
`external_calls=0`、`keys_used=false`；执行 2026-11-14T13:17，`code_head=0524d3d`。

| 编号 | 类型 | 预期 | 实际 |
| --- | --- | --- | --- |
| W0B-C00 | 正 | 一次 generate 出 A/B 两份有效候选，按 run_id 读同一快照 | pass：`artifact_count>0`、A/B 均 `valid`、`snapshot.token` 16 位 |
| W0B-F01-01 | 正 | 同基线两条连续留言合并成一轮，两条都被同一 run 消费 | pass：`merged_feedback_ids` 2 条，`consumed_by_run` 同一 run |
| W0B-F01-02 | 负 | 两条都已消费后再开轮 → 明确冲突，不复活、不换基线 | pass：`feedback_already_consumed`，无新 run 产出 |
| W0B-F01-03 | 正 | 已消费历史不封死显式 generate | pass：`task_kind=generate`，产出新的 A/B |
| W0B-F01-04 | 负 | 跨候选两条待续改 → 拒绝自动合并，不丢更早那条 | pass：`multiple_pending_feedback` + 两条都在 `pending_feedback` |
| W0B-F01-05 | 正 | 作废更早那条后按剩下那条续改，正文与历史保留 | pass：`status=superseded`、`superseded_by` 有值、`text_preserved=true` |
| W0B-F01-06 | 正 | 自动返工按设计试验累计，新 run 不归零 | pass：`auto_rework_total=2`、`trial_progress.auto_rework_used>=2`、上限 2 |
| W0B-F02-01 | 负 | 两个目标只达标一个 → 拒绝 | pass：`REV-OBJECTIVE`，诊断含 F2，本轮无有效修订 |
| W0B-F02-02 | 正/负 | min/exact/max 各自按语义判定；声明满足 ≠ 实测达标 | pass：`pass/pass/fail/pass/fail`；净宽 `declared_meets_target=true` 而 `measured_meets_target=false` → `fail` |
| W0B-F03-01 | 负 | 保留的是非入口对象 ZA5，改它就拒绝 | pass：冲突对象 ZA5，不引用入口锁 |
| W0B-F03-02 | 负 | 找不到对象的保留要求 → unknown + pending + 原句 | pass：`binding_status=unresolved`、`user_confirmed=pending` |
| W0B-F04-01 | 正 | 锁 F1.x 只改 F1.rot → 允许 | pass：`status=succeeded`、无 `LOCK-REVISION` |
| W0B-F04-02 | 负 | 锁 F1.x 且真改 F1.x → 拒绝并给出被锁字段 | pass：`LOCK-REVISION`、`changed_fields=[x]`、无有效修订 |
| W0B-F05-01 | 负（时序） | 运行中到达新留言 → 本轮 `superseded`，产物不作当前版本 | pass：见下 |
| W0B-F05-02 | 正 | 完成状态与产物同一快照，带 token | pass：`last_completed_run_id` 与 `last_completed_run.id` 一致，`artifact_ids ⊆ artifacts`，counts 一致 |

### B.1 W0B-F05-01 的时序构造（没有 sleep）

1. 先把桩设成"本轮只转 F3（-30°）"——保证**这一轮本来会交出合格修订**。
2. `GatedStub.gate=Event(); at_call=1; hold=True`：桩在**第一次模型调用处停住**，并 `reached.set()`。
3. 服务端 `/run` 返回 `run_id`；测试**按 run_id** 轮询 `/runs/<id>`，确认 `status=running`、有效产物 0。
4. 此时发第二条留言"先改北光廊，这一版不要了"（HTTP 201），再 `gate.set()` 放行。
5. 结果：`final_run_status=superseded`；`run_snapshot` 里 2 份产物 `status=superseded`
   （其中 `spatial-plan` 的 `contract_status` 仍是 `valid_candidate`）；有效产物 0；`cancel_requested=1`。

> 第一版这条例题里桩返回的 patch 与基线一致（F3 本来就是 -15°），被正确判成"没有对象变化"→`incomplete`，
> 用例失败。这里**没有**去放宽断言，而是改成"确实能成功的一轮"再验证取代语义，并记录该轮产物确实合格。

## C. 真实浏览器（Edge headless，隔离环境）

命令：`PYTHONPATH="mvp;scripts;." .venv/Scripts/python.exe scripts/verify_w0b_browser.py`
结果：`passed=true`、`node_returncode=0`、21.2s、`page_errors=[]`；`browser/verification.json`。

| 观察点 | 预期 | 实际 |
| --- | --- | --- |
| 选 A v1 → 连发两条留言 | 页面显示合并 2 条、任务为 revise | `taskbar_merged` 含"合并 2 条同基线留言"；`task_resolution.kind=revise`，`merged_feedback_ids` 2 条 |
| 开一轮 | 一个 run 消费两条留言，新修订父版本=选中旧版 | `consumed_feedback_revisions=[1,2]`；`new_revision_parent_uid=revuid_c3a96672d3` |
| 已消费后再开一轮 | 中性说明，不弹窗 | `alert_count_after_run=0`，状态文本含"已经执行过" |
| 跨候选两条待续改 | 冲突告警 + 待办清单 | `task_resolution_conflict` 有值；`pending_count=1` |
| 点"作废这条" | 任务回到 revise、目标回 A、正文保留 | `after_withdraw.task_kind=revise`；`page_shows_withdrawn=true` |
| 390px | 无横向溢出 | `mobile_scroll_width=390`、`inner_width=390` |
| 重启 | 反馈/任务/闸口/修订链/旧基线字节保留 | `old_baseline_bytes_preserved=true`、`snapshot_isolated` 有值 |
| 页面错误 | 0 | `page_errors=[]` |

## D. 本批"没有做"的负例（如实列出，防止被误读成已覆盖）

- **并发两个 run 抢同一基线**：只在任务解析层覆盖（`multiple_pending_feedback` / 消费 CAS），
  没有做双 run 真并发的压测；`_running` 仍是进程内互斥。
- **网络/磁盘故障注入**：未做。
- **真实模型（非桩）在晚到/取消时序下的行为**：未做（无付费授权）。
- **W1 统一模型适配、W2 同源平面/效果图、W3 真实设计验证、W4 完整成果**：一律未开始。
