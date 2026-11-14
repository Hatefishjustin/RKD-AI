# W0 代码差异与复核定位

- **base**：`957cf775e1d835cf25bbdf196de4e7f3f51280fa`（`957cf77`）
- **业务代码主体提交**：`4ef7c724d90bf2e0d9263a26368bde81fb628fae`（`4ef7c72`）
- **当前 HEAD**：`666f7d0cabef17464641786353fc2a4f8138e0a4`（`666f7d0`，仅追加清单/补丁/提交号，
  无业务代码改动；复核代码差异请用 `git diff 957cf77..4ef7c72`）
- 复核差异命令：`git diff 957cf77..HEAD -- mvp/rkd_mvp/studio web/src scripts`
- 标准补丁：同目录 `changes.patch`（由 `git diff 957cf77..<本批主体提交>` 导出，可 `git apply --check`）
- 本批**未** reset / checkout / 删除用户既有改动；`source/` 原件与上一批历史成果字节未动。

## 1. 修改的已跟踪文件（7 个）

| 文件 | 改动 | 架构师优先抽查点 |
| --- | --- | --- |
| `mvp/rkd_mvp/studio/store.py` | additive 列：`feedback`（`baseline_selection/locks_json/objectives_json/task_kind/consumed_by_run`）、`runs`（`task_kind/target_*/conflict_code`）；`add_feedback` 扩展；`feedback()` 解析结构化字段；新增 `artifact_by_id()`（跨项目精确查询）与 `consume_feedback()`（CAS） | `_MIGRATIONS`、`consume_feedback`、`artifact_by_id` |
| `mvp/rkd_mvp/studio/server.py` | `/messages` 严格校验用户指定旧基线（409 冲突，不偷换）；`/run` 对 conflict 返回 409；`_state` 暴露 `task_resolution` / `revision_history` / `latest_run` / `last_completed_run` | `Handler.do_POST` 的 `/messages` 分支、`_state` |
| `mvp/rkd_mvp/studio/orchestrator.py` | `run_a1` 同步 `resolve_task` 分流（generate / revise / conflict）并写 run 元数据；feedback CAS 消费；新增 `_revise_from_baseline()`；`_scenario` boss_feedback 保留基线指针/锁/目标；修订完整性调用传入 site/catalog/objectives/locks | `run_a1`、`_revise_from_baseline`（重点：不生成 A/B、`parent_revision_uid=base_uid`）、`_scenario` 第 3—5 步 |
| `mvp/rkd_mvp/studio/revision.py` | `verify_revision_integrity` 四态分离 + 确定性目标复核 + 全局 `REV-OBJECTIVE` 兜底；返回 `objective_rechecks` / `objective_recheck_summary` | `verify_revision_integrity` 的 accept 分支与 boss_feedback 循环 |
| `scripts/verify_arc_first_batch.py` | Q07/Q08 三处 `verify_revision_integrity` 传入 `site=SITE`（**启用**几何实测复核，非放宽）；伴生 `q-checks.json` 改为写到 `--out` 同目录，避免回归覆盖上一批历史证据 | `q07_q08()` 与 `main()` 末尾 |
| `web/src/StudioView.tsx` | 新增「续改哪份旧方案」下拉（`data-testid=baseline-select`）、任务条（上一轮/本轮/版本链）、成果栏父版本 uid；`send()` 提交 `baseline_artifact_id` / `baseline_revision_uid` | `send()`、`studio-taskbar`、`studio-input` |
| `web/src/studio.css` | `.baseline-pick` 与 620px 以下换行，避免 390px 横向溢出 | `@media (max-width: 620px)` |

## 2. 新增文件

| 文件 | 职责 |
| --- | --- |
| `mvp/rkd_mvp/studio/revision_task.py` | `resolve_task()` 任务分流/冲突、`structured_locks()` 结构化锁、`derive_objectives()`、`recheck_objectives()` 确定性目标复核 |
| `scripts/w0_repro.py` | R1/R2/R3 整改前后复现（`--phase before\|after`），只读历史证据 + 隔离库 |
| `scripts/verify_w0.py` | W0 专项正负例 + 真实 HTTP 服务验收，产出 `checks.json` |
| `scripts/verify_w0_browser.py` / `.cjs` | 真实浏览器：选中旧方案 → 反馈 → 续改 → 父版本对比 → 390px 检查 |
| `deliverables-for-review/roadmap/W0-收口/*` | 本复核包（含独立勘误记录） |

## 3. 契约与语义变更说明（不含放宽）

- **未修改** `contracts/v1/spatial-plan-proposal.schema.json` 与
  `contracts/v1/spatial-plan-draft.schema.json`：必填项、`additionalProperties:false` 与身份边界均未动。
- 未新增第三套权威项目事实：Studio 仍只写自己的实验库；主系统候选模型、采用指针、成果登记未改。
- `feedback` / `runs` 新增列全部为 **additive**，旧行保留原值；旧草案解析不变。
- `MAX_AUTO_REWORK = 2` 保持；新增 `consume_feedback` CAS 与 `feedback_already_consumed` 冲突，
  明确阻止"拆成新 run 绕过上限"。
- `unknown` 不补 0：目标复核无法计算时写 `objective_rechecked=unknown` + `user_confirmed=pending`，
  不写 `resolved=true`，不把"引用到变化"记为已解决。
- 未触碰 PG/NAS/账号/备份；未改日常 `var/studio/studio.db`（所有验证使用 `RKD_STUDIO_DB` 隔离库）。

## 4. 复核时建议的顺序

1. `git diff 957cf77..HEAD` 看真实差异，重点读 `revision_task.resolve_task`、
   `orchestrator._revise_from_baseline`、`revision.verify_revision_integrity`、
   `server.Handler.do_POST` 的 `/messages` 分支。
2. 读 `before/reproduction.json`（7 个缺陷实测）与 `after/reproduction.json`（0 个）。
3. 抽查 `after/checks.json` 的 `W0-R1-02`（负例集合）、`W0-R2-01`、`W0-R2-04`。
4. 看 `browser/w0-revision-desktop.png`（任务条 + 父版本 + 单一待决闸口）与
   `browser/browser-observations.json`。
5. 核对 `evidence-provenance-erratum.md` 的时间轴与历史字节 SHA。
