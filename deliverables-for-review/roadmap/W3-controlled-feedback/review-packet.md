# W3 受控 spatial 候选反馈修订闭环复核包（AI-DESIGN-03）

基线：`origin/master` = `902952ed31370852cbae58df2248d79c4d9e2237`（检查时工作区干净、HEAD 与 origin/master 一致）。
本批提交：见 `commit-reference.md`（提交后生成）。
**本批不自行推送交回审查，不宣布 W3 通过、不宣布设计通过。**

复核依据已读：`AGENTS.md`、`新对话交接文件.md`、`PROJECT_STATUS.md`、`docs/13` 第 12.7—12.9 节、`docs/21` 第 12.4 节 AI-DESIGN-03（03a—03e）与 AD01—AD08、最近 W3 复核包（`W3-r1r2-source-records`、`W3-r1r2-scope-required`、`W3-test-hygiene`）。

## 1. 做了什么

把 `CONTROLLED_FEEDBACK_PATH_UNSUPPORTED` 替换为**真实服务路径上的受控反馈修订闭环**：

1. **基线绑定**（`ai_design_option_service.py:1175-1210`）：受控候选反馈现在必须显式提供 `parent_revision_id`、`expected_version`、`expected_input_hash`；缺任一项 `INVALID_FEEDBACK_BASELINE`。逐项核对当前修订号、指定父修订是否为最新版、候选集状态、`adoption.expected_revision` 与项目输入摘要；过期输入 `STALE_INPUT_SNAPSHOT`、过期采用版本 `STALE_ADOPTION_VERSION`、过期父修订 `STALE_PARENT_REVISION`。
2. **新 invocation 与真实签发**（`:994-1085`）：每次反馈创建 `runtime.begin_invocation(project_id)`；provider 只拿 `scope.opener()`；新 run 绑定本次实际请求/响应、新的 `input_hash`（含父修订、反馈、锁定、项目输入摘要、采用版本）、当前场地快照、项目与父修订；`scope` 仍是必填，空/异服务 scope 走既有 fail closed。运行记录带 `parent_revision_id` 与父亲候选摘要；新记录使用自己的 `run_id`，不复用父版。
3. **先生成、后适配、再准入**：把父版**不可变源候选**（v1 provider 文档）交给 `RealModelDesignOptionProvider.revise()`，provider 改用当前权威 `runtime.provider_site()` 与本次任务书（新增可选 `site`/`brief` 参数，默认行为兼容旧调用），输出新源候选；经 `_validate_candidate` 契约/运行元数据检查、锁定检查，再经 `_controlled_finalize` 适配为 v2 spatial、跑几何投影/来源/场地/准入。任何失败不写库。
4. **锁定与冲突**（`:908-993`）：解析锁定令牌到父版权威对象；模型改写锁定字段 → `LOCK_FIELD_MODIFIED`，删除受保护对象 → `LOCK_OBJECT_DELETED`，改写入口 → `LOCK_FIELD_MODIFIED`，改写场地快照摘要 → `SITE_SNAPSHOT_MODIFIED`，mm 投影变化 → `LOCK_FIELD_MODIFIED`；provider 自报已恢复的 `lock-conflict-*` 也算失败而不是静默接受；反馈未解析（`FEEDBACK_UNPARSED`）或 locks 丢失（`FEEDBACK_LOCKS_MISMATCH`）同样拒绝。新 v2 记录回填真实的 `feedback`/`change_reason`。
5. **不可变父版与提交后父链**：写事务内二次 CAS（修订号/父 id、候选集状态、采用版本、父候选字节摘要），成功后才 `insert_revision`；**事务提交后**才 `runtime.commit_revision` 让新修订可作为后续父链；登记失败标 `REVISION_REGISTRATION_FAILED` 且不伪造父链。采用指针不被反馈隐式改写。
6. **接线**：`ApiService.revise_ai_design_option` 与 `PostgresApiService` 使用的同一 `AIDesignOptionService.revise` 接口，未新增路由或第二套服务。

## 2. 没有做什么 / 为什么

- **未调用真实模型**：本轮无任何外部模型授权；全部交换是本地协议桩，`simulated=True`、来源 `fixture`。因此这不是设计公司成果，不构成 AI 自动设计，不计 AD01—AD08。
- **未跑 PG 数据面**：本机无活动 PG 实例，记 `not_run`；没有把 SQLite 结果冒充 PG 验证。PG 组合根沿用上一批接线，语义上共享同一服务方法，但本批未实测。
- **未跑 HTTP/UI**：只驱动 `ApiService` 公共方法，未启动 HTTP 服务进程或浏览器，记 `not_run`。
- **未扩大范围**：未改 W4、NAS/PG/账号/KMS、数据库迁移、阶段确认、AD01—AD08、正式责任边界；未推送远端。
- **未移除既有限制**：`controlled_observations()` 审计视图、`issue(scope=…)` 必填与提交后父链登记语义均保持。

## 3. 前后同例复现

`scripts/w3_feedback_revision_findings.py`（同一 harness、真实 ApiService 公共 API + 真实隔离 SQLite + 本地桩）：

- before（冻结 `902952e`）：`CONTROLLED_FEEDBACK_PATH_UNSUPPORTED`（422），桩修订调用 0 次，`summary=vulnerable`。
- after（本批）：新修订 `revision_no=2`、`parent_revision_id` 指向用户指定父版、新 `run_id`、父版字节不变、新 admission 与父版不同、`adoptable=true`、查询可见，`summary=fixed`。

证据：`outputs/findings-before.json`、`outputs/findings-after.json`；原始运行证据 `var/evidence/roadmap/W3-controlled-feedback/{before,after}/`。

## 4. 永久回归（`mvp/tests/test_w3_controlled_feedback.py`，9 项）

正常修订成功（含 run/parent/摘要/场地/准入/父版字节/下载可见性）、锁定字段改写拒绝、锁定对象删除拒绝、父版/输入/采用版本/修订号过期拒绝、两个并发反馈只有一个成功、非法几何与 provider 500/超时不落库、scope 缺失/串用 fail closed、提交前基线变化丢弃后无幽灵父链、提交后父链登记摘要匹配与采用 CAS 冲突。

断言覆盖真实 revision、`parent_revision_id`、`run_id`、request/response 摘要、`input_hash`、site snapshot digest、来源状态、admission、业务仓储登记与查询/下载字节；没有手工插入记录替代产品路径。

## 5. 测试结果（实际命令 / 退出码 / 日志）

全部命令均实际运行、退出码 0：

| 命令 | 结果 |
| --- | --- |
| `-m unittest discover -s mvp/tests -p "test_w3_controlled_feedback.py"` | `Ran 9 tests ... OK`，exit 0 |
| `-p "test_w3_composition_root.py"` | `Ran 7 tests ... OK`，exit 0（已把旧「反馈不支持」断言改为「缺基线被拒且父版保留」） |
| `-p "test_ai_design_options.py"` | `Ran 8 tests ... OK`，exit 0 |
| `-p "test_w3_r1r2_source_records.py"` | `Ran 5 tests ... OK`，exit 0 |
| `-p "test_w3_astra_remediation.py"` | `Ran 4 tests ... OK`，exit 0 |
| 全量 `discover -s mvp/tests` | `Ran 287 tests in 532.470s ... OK`，exit 0（`var/evidence/roadmap/W3-controlled-feedback/after/full-regression.log`） |

## 6. 仍然不像设计公司成果的地方（如实列）

1. 修订候选由本地桩产出，仍是矩形分区与 4 条动线，不是真实设计师的布局；空间组织没有叙事层级或墙体围合。
2. 图面由程序 `render_svg` 确定性绘制，只有概念平面，没有材料实物、软阴影、家具细节或人眼高度效果图。
3. 锁定令牌目前只覆盖入口、展陈对象与显式 object_id；没有覆盖客户口头上的全部自然语言保留语义。
4. 反馈解析只保留 `parsed_intents` 与 `locks`，没有形成可审阅的"需求条款→对象变更"逐条对照报告。
5. 本批没有任何真实用户评价；AD08 的负例（用户否决）仍有效，未获新认可。

## 7. 调用、外发、费用、图片

| 项 | 本批 |
| --- | --- |
| 外部模型调用 | 0 |
| 项目资料外发 | 0 |
| tokens | 0（桩响应无真实用量） |
| 费用 | ¥0 |
| 生成图片张数 | 0（只写 SVG 概念图，不是效果图） |
| 真实密钥 | 未使用 |

设计数据来源：本地协议桩按 `w3_trust_findings.candidate()` 夹具生成，来源标记 `fixture`、`simulated=true`；不是人工编写，也不是系统模型自动生成的设计成果；不计 AD 验收。
