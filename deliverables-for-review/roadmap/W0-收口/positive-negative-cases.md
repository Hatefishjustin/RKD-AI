# W0 关键正负例（预期 / 实际 / 失败原因 / 复跑结果）

数据来源：`var/evidence/roadmap/W0-收口/{before,after}/reproduction.json`、
`var/evidence/roadmap/W0-收口/after/checks.json`、
`var/evidence/roadmap/W0-收口/after/browser/browser-observations.json`。
整改前 7/7 缺陷确认，整改后 0/7；W0 专项 7/7 observed_pass。
所有回路使用明确标记的本地模型桩 `local-model-stub`，0 外部调用、0 费用。

## A. R1 旧基线反馈续改

| 编号 | 类型 | 预期 | 整改前实际 | 整改后实际 |
| --- | --- | --- | --- | --- |
| R1-b | 正例 | 反馈指定旧基线 → 第二轮加载该旧稿续改；新修订 `parent_revision_uid` 指向选中旧版；不重新生成 A/B | 又生成 **2 个**全新 A/B；修订 `parent_revision_uid=revuid_10f811980d`（本轮新候选），与用户选中的 `revuid_ef1bc05689` 不符 | `second_run_fresh_A_B_count=0`；`runs[1].task_kind=revise`；`parent_revision_uid` 等于选中旧版 uid |
| R1-c | 正例 | 真实 `/messages` 尊重用户指定的旧基线，不按最新文件偷换 | HTTP 201 但把 `art_414dd516b2` 换成 `art_f35ba7261d`；无 `baseline_selection`、无冲突提示 | HTTP 201，`stored_baseline_artifact_id` = 用户指定值，`baseline_selection=user_selected`，`task_hint=revise` |
| W0-R1-01 | 正例（真实服务 + 浏览器） | 页面选中旧方案 → 反馈 → `/run` 返回 `task_kind=revise` → 新修订父版本指向选中旧版；无关对象保留；旧版字节不变 | 无此路径 | 全部通过；`fresh_AB_in_revise_run=0`，`page_shows_parent_uid=true`，重启持久化通过 |
| N1 跨候选 | 负例 | 产物 id 与 `revision_uid` 不属于同一版本 → 明确拒绝 | 无校验 | 409 `baseline_uid_mismatch` |
| N2 跨项目 | 负例 | 用另一项目的产物当本项目旧基线 → 拒绝，不偷换 | 无校验 | 409 `cross_project_baseline` |
| N3 基线不存在 | 负例 | 伪造 artifact id → 明确冲突 | 会被 `_latest_valid_plan` 兜底成"最新文件" | 409 `baseline_not_found` |
| N4 失败稿 / 失效稿 | 负例 | `invalid_raw` 或 `superseded` 产物不可作为续改基线 | 无区分 | 409 `baseline_invalid` |
| N5 旧反馈重放 | 负例 | 同一反馈已被消费，不得用新 run 重放绕过最多 2 轮自动返工 | 每轮都重新生成 A/B，天然可无限重跑 | 409 `feedback_already_consumed`；`MAX_AUTO_REWORK=2` 未改 |
| N6 并发新反馈 | 负例 | 运行开始时版本落后于当前有效需求 → 晚到结果不得成为当前版本 | 只有部分覆盖 | `resolve_task` 返回 `concurrent_new_feedback` conflict；`invalidate_artifacts` 标 `superseded` 且**字节不变** |
| N7 锁定条件 | 负例 | 结构化锁（对象/字段）被改动 → 报具体冲突与替代，不自行解锁 | 靠中文「保留」关键词命中对象名 | `structured_locks` 以 `role=arrival`、用户显式 locks、场地保留条件为准；`keyword_matching_used=false` |

## B. R2 问题复核不能只靠对象 diff

| 编号 | 类型 | 预期 | 整改前实际 | 整改后实际 |
| --- | --- | --- | --- | --- |
| R2-a / W0-R2-01 | **负例（伪修复）** | 「把主动线净宽调到 2100mm」却只改目标对象颜色/名称（或 `path` 微移），`width_mm` 仍 2000 → 不得记为已解决 | `verified=true`、`recheck="对象 diff 复核"`、`ok=true` | `objective_rechecked=fail`、`verified=false`、`resolved=false`、含 `REV-OBJECTIVE`；`ok=false` |
| W0-R2-04 | 负例（服务级） | 伪修复经真实 `/run` 应被拦，不生成新候选、不标 succeeded | 无目标复核，正常通过 | `final_run_status=incomplete`、`raw_invalid_artifacts>=1`、diagnostics 含 `REV-OBJECTIVE`、该 run 无有效修订 |
| W0-R2-02 | 正例 | 净宽真的改到 2100 且几何复算实测瓶颈达标 → 才记 `pass` | 只看对象是否出现在 diff | `objective_rechecked=pass`、`verified=true`、`resolved=true`、`ok=true` |
| W0-R2-03 | 正例 | 「更开放/更有设计感」等审美目标、以及未实现的 STD-004 视线规则 → `unknown` + `user_confirmed=pending` + `resolved=null`，只提供图面对比与模型意见 | 直接 `in_revision_input=true` 并把全部变化记为关联 | 四态字段齐备；`objective_recheck_summary.unknown>=2`；`linked_changes` 不再等于全部变化 |
| R2-b | 正例 | `boss_feedback_resolutions` 分离 `input_included / object_changed / objective_rechecked / user_confirmed` | 只有 `in_revision_input` + `linked_changes=全部变化` | 四态齐备；`boss_feedback_linked_changes_is_all_changes=false` |

**复跑结果**：`W0-R2-04` 第一次失败原因是测试脚本自身的副作用（前一步"晚到结果失效"把 C01
新修订标成 `superseded`，再拿它当基线被正确拒绝）；改用仍有效的 A/v1 旧基线后通过。
第二次调试发现文本启发式目标缺 `feedback_id`，导致伪修复的 `fail` 未关联到反馈；已补
`feedback_id` 映射并加全局 fail 兜底，最终 7/7 通过。这两次失败与修复过程如实保留，未删未粉饰。

## C. R3 证据日期与契约映射

| 编号 | 类型 | 预期 | 整改前 | 整改后 |
| --- | --- | --- | --- | --- |
| R3-a | 勘误 | 编制 / 执行 / 复跑补生成 / 提交分别标时间与代码基线；不推断造假、不混用、不回写历史证据 | 头部只有「日期：2026-11-12」，内含 11-14 事件 | 独立 `evidence-provenance-erratum.md` 时间轴；历史 `review-packet.md` 字节 SHA `8ac87bd7…` 未变 |
| R3-b | 勘误 | 按实际三份 schema 修正映射 | 适配说明把 `contract_version/project_id` 写成 Studio 提案字段与 `ai-design-option` 落点 | 勘误列明：proposal 无身份字段；draft 用 `contract_version=rkd-spatial-plan.v1`；主系统用 `schema_version=rkd-ai-design-option.v1` 且无 `project_id`；历史适配说明字节 SHA `cc451e8b…` 未变 |

## D. 回归负例（不拿旧通过数冒充本批结论）

- Q01—Q12 重新执行：**11 observed_pass / 0 fail / 1 not_run（Q10 属 W1/W2）**。
- 全量单测 **262/262 OK**；A1 管线 15/15 PASS；前端构建 EXIT=0。
- 浏览器 `page_errors=[]`、390px `scrollWidth=390`、无横向溢出。
- 本批没有把上一批 18 项或 262 项通过当作 R1/R2/R3 已解决：三个缺陷都是先独立复现、
  再实现、再用新的正负例分别验证。
