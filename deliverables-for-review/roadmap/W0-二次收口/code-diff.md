# W0 二次收口 · 代码差异说明

比较基线：`0524d3d`（`docs: W0 复核包不再把易变文档 HEAD 写成权威基线`）。
复核命令：`git diff 0524d3d -- mvp web scripts`；完整补丁：`changes.patch`（含 4 个新增脚本）。

总量：生产与前端 **8 个文件，`+1082 / −270`**；另有 4 个新增验收脚本共 1604 行（不参与生产逻辑，见 §3）。
`git diff 0524d3d -- mvp web scripts` 的合计是 12 文件 `+2686 / −270`。

## 1. 生产代码

### 1.1 `mvp/rkd_mvp/studio/revision_task.py`（+460 / −139，本批主要改动）

| 位置 | 改动 | 对应 |
| --- | --- | --- |
| `resolve_task`（:119） | 重写任务解析：以**最新一条版本化 feedback** 为当前意图；同基线多条 pending 返回 `merged_feedback`/`merged_feedback_ids` 并一次性消费；跨基线返回 `multiple_pending_feedback` 冲突并带 `pending_feedback`；最新已消费返回 `feedback_already_consumed`（不复活）；显式 generate 意图返回 `_generate(...)`，带 `overridden_feedback_ids` 与 `superseded_intent` | F01 |
| `_generate` / `_conflict`（:229 / :247） | 新增内部构造器，统一冲突码、替代建议、`task_kind` 文案 | F01 |
| `_iter_objects` / `_index` / `_object_signature`（:94 / :109 / :113） | 对象遍历与字段签名，供字段级锁与保留复核共用 | F03/F04 |
| `lock_conflicts`（:294） | 由"整对象比较"改为**字段级**：`fields:["*"]` 才是整对象；其余只比较指定字段。诊断类型区分 `locked_object_not_found` / `locked_object_missing_in_baseline` / `object_deleted` / `whole_object_changed` / `unsupported_fields` / `field_changed`，并给 `changed_fields` 与 `message` | F04 |
| `preserve_clauses` / `resolve_preserve_binding` / `resolve_preserve_bindings`（:386 / :392 / :420） | 把"保留…"拆成子句，按**对象 id 边界匹配**或**对象 `name` 出现在子句**绑定；多命中记 `ambiguous`，零命中 `unresolved`，并回填 `binding_match` / `binding_candidates` / `source_text` | F03 |
| `derive_objectives`（:424） | 增加结构化锁目标（`FB{rev}-LK{i}`）与保留目标（`FB{rev}-P{i}`，带 `binding_status`）；新增 `plan=` 入参，用于绑定对象名 | F02/F03 |
| `_cmp_ok` / `_aggregate`（:542 / :556） | 比较符实现（`min`/`exact`/`max`，容差 1e-6）与聚合（默认量词 `all`：缺失→fail，空集→unknown，部分通过→fail） | F02 |
| `_measure`（:569） | 返回 `comparator`/`quantifier`/`target_objects`/`missing_object_ids`/`declared_object_ids`/`passing_object_ids`/`failing_object_ids`/`coverage`；净宽同时校验声明值、几何实测值、绝对下限 `MIN_CLEAR_WIDTH_MM` 与 CIR 现场问题；`coverage` 明写"不覆盖门洞、家具遮挡与完整净宽合规" | F02 |
| `recheck_objectives`（:647） | 四态判定不变，但 `kind ∈ {lock,preserve}` 走 `_recheck_lock_objective`：未绑定 → `unknown`+`pending`；已绑定 → **用本条对象自己的锁**复核；失败文案区分"对象缺失"与"只满足部分对象" | F02/F03 |
| `_recheck_lock_objective`（:723） | 保留要求的独立复核，不再借用入口锁 | F03 |

### 1.2 `mvp/rkd_mvp/studio/orchestrator.py`（+108 / −59）

- 删除 `_locked_ids()`（按中文关键词猜被锁对象），改为 `_resolved_text_locks(plan, feedback_rows)`：
  只对**已绑定**的保留要求生成锁，并带留言原文与 `binding_match` 作为理由。→ F03
- `run_a1`：`merged_fb = resolution.get("merged_feedback") or [target_fb]`；revise 时
  `all(st.consume_feedback(f["id"], run_id) for f in merged_fb)`（一次性消费，失败整体不消费）。→ F01
- `trial_key = st.trial_key_for(...)`、`carried_rework = st.auto_rework_used(trial_key)`；
  `start_run(..., trial_key=, auto_rework_total=carried_rework)`；`finish_run(..., trial_key=)`。→ F05
- `_revise_from_baseline`：`locks = structured_locks(...) + merged_fb 的锁 + _resolved_text_locks(...)`；
  `objectives = derive_objectives(..., plan=base)`；integrity/validation 都传 `locks=`（不再传 `lock_object_ids`）。→ F02/F03/F04
- `_scenario`：打回判断改为"本轮已用 ≥ 上限 **或** 本轮已用 ≥ 剩余额度"；
  `stats["auto_rework_total"] = carried_rework + rework_count`；
  `stats["trial_key"]` 在候选生成后取根候选组，A/B 与其后续 revise 共用同一设计试验。→ F01/F05
- `finally`：仍只把 `succeeded` 翻成 `superseded`；**不把别的失败原因改写成 superseded**
  （避免用"被取代"掩盖真实失败）。→ F05

### 1.3 `mvp/rkd_mvp/studio/store.py`（+244 / −23）

- 新列（`_SCHEMA` + `_MIGRATIONS`，additive）：`runs.trial_key TEXT`、`runs.auto_rework_total INTEGER DEFAULT 0`。
- `trial_key_for(artifact_id)`（:711）：沿 `parent` 链回溯到根，取根候选的 `candidate_group_id`，
  返回 `"{project_id}|{root_group_or_uid}"`；`auto_rework_used(trial_key)`（:736）、`trial_rounds(trial_key)`。
- `start_run(..., trial_key, auto_rework_total)` / `finish_run(..., auto_rework_total, trial_key)`：
  `COALESCE(?, col)` 写入，读旧值为空时不覆盖。→ F05
- `withdraw_feedback(project_id, feedback_id, reason, by_run)`（:420）：写 `status='superseded'` +
  `superseded_by`，**正文与 evidence 原样保留**，返回 `{applied, reason, superseded_by, text_preserved}`。→ F01
- `project_state(project_id, *, barrier=None)`（:793）：单事务 `BEGIN … COMMIT`，读 messages/artifacts/
  reviews/gates/runs/feedback；`barrier` 是**验证接缝**（artifacts 读完、runs 未读之间插入），
  仅测试使用；返回 `snapshot`（`taken_at`/`isolation`/各表 counts/`latest_run_id`/`token[:16]`）与
  `feedback_history`（含已作废，正文保留）。→ F05
- 连接级读取器 `_messages_on` / `_artifacts_on` / `_reviews_on` / `_gates_on` / `_runs_on` /
  `_feedback_on` / `_checks_on`：保证所有表在**同一连接、同一事务**里读。→ F05
- `run_snapshot(project_id, run_id)`（:854）：单事务返回该 run 与其**精确属于该 run** 的产物、
  `run_status`、`finished`、`artifact_count`、`valid_artifacts`。→ F05
- `PRAGMA journal_mode=WAL`（best-effort）。→ 并发读

### 1.4 `mvp/rkd_mvp/studio/server.py`（+85 / −8）

- 新增 `GET /studio/projects/<pid>/runs/<run_id>` → `store.run_snapshot`（404 不存在）。→ F05
- 新增 `POST /studio/projects/<pid>/feedback/<fid>/withdraw`：必须给 `reason`（否则 400），
  不可作废（已 superseded / 不存在）返回 409。→ F01
- `_state`：新增 `arts_by_run`；`stage_status` 增 `last_completed_run_id/status/artifacts/valid_artifacts`；
  `task_resolution` 增 `target_feedback_id`/`merged_feedback_ids`/`overridden_feedback_ids`/`pending_feedback`；
  新增 `pending_queue`、`trial_progress`（`trial_key`/`rounds`/`auto_rework_used`/`max_auto_rework`/
  `last_run_auto_rework_total`）、`snapshot`、`feedback_history`；`latest_run`/`last_completed_run`
  带 `trial_key`/`auto_rework_total`/`artifact_ids`/`valid_artifact_ids`。

### 1.5 `mvp/rkd_mvp/studio/validation.py`（+30 / −19）与 `revision.py`（+15 / −8）

- `validate_proposal(..., lock_object_ids=None, locks=None, previous_plan=None)`；第 4 阶段改调
  `revision_task.lock_conflicts`，把明细写进 `facts["lock_conflict_details"]`；
  `lock_ids` 仍兼容整对象语义，但**不再静默把字段锁升级成整对象锁**。→ F04
- `revision.py`：`derive_objectives(feedback_rows, issues, plan=base)`；锁定阶段复用
  `revision_task.lock_conflicts`，与校验阶段同一判定源。→ F02/F04

## 2. 前端

### `web/src/StudioView.tsx`（+132 / −14）、`web/src/studio.css`（+8）

- 类型扩展：`stage_status`/`task_resolution`/`pending_queue`/`trial_progress`/`snapshot`/
  `feedback_history`/`latest_run`/`last_completed_run` 的新字段。
- 新增 `notice` 状态：成功/中性提示走 `role="status"`，与红色 `alert` 分离；
  `feedback_already_consumed` 渲染为中性说明，不再弹窗冒充新任务。→ F01
- 新增 `activeRun`/`activeRunStatus` + `useEffect` 轮询 `GET .../runs/<id>`：页面按 **run_id**
  跟踪本轮，不再读 `runs[-1]`。→ F05
- 任务条新增：本轮自动返工次数、合并条数（"合并 2 条同基线留言"）、设计试验累计
  （"第 N 轮 · 自动返工 x/2"）、正在跑的 run_id。
- 待办清单 `.studio-pending`（含"作废这条"按钮，走 `prompt` 收理由 → POST withdraw）；
  已作废留言 `.studio-withdrawn`（删除线 + `superseded_by`，正文保留可查）。→ F01
- CSS 新增 `.studio-note`、`.studio-pending`（strong/ul/li/button）、`.studio-withdrawn`。

## 3. 新增验收脚本（不参与生产逻辑，全部 0 外部调用）

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `scripts/w0b_repro.py` | 579 | 17 例缺陷复现/修复签名，纯函数与 Store 级，隔离临时库；`--phase before|after --out` |
| `scripts/verify_w0b.py` | 624 | 真实 HTTP 15 项正负例；`GatedStub` 可控屏障做晚到/取消；`wait_run` 按 run_id 等 |
| `scripts/verify_w0b_browser.py` | 193 | 拉起隔离主工作台 + 隔离 Studio + 真实 Edge，驱动实际用户路径 |
| `scripts/verify_w0b_browser.cjs` | 208 | Playwright 侧断言与截图；从 `feedback_history` 校验作废留言仍可见 |

## 4. 明确没有改的地方

- 未改 `MAX_AUTO_REWORK = 2`，未加新的"重试绕过"路径。
- 未改契约 schema 文件（`contracts/`），未改 `geometry.py` 的净宽口径（只把它的有限范围写进证据）。
- 未改 AD01—AD08 的任何判定文档，未改 `docs/26` 路线，未动 `source/` 原件。
- 未删除任何历史证据；唯一一次误覆盖已恢复（见 `review-packet.md` §5 事故记录）。
