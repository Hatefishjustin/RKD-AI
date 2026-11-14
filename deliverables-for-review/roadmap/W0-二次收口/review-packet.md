# W0 二次收口 · 架构师复核包（F01—F05 限定整改）

编制时间：2026-11-14 13:30（北京时间）；证据实际执行时间见每张表与 `manifest.json`。
上游依据：`deliverables-for-review/roadmap/W0-architect-review/architect-review.md`（结论"限定整改，暂不进入 W1"）、
`independent-negative-cases.json`、`w0-independent-rerun.json`。
比较基线（base）：`0524d3d87525eb1e05001d10574148e8b22f10bd`（`0524d3d`）；
本批业务实现提交：`27b389dcd23068d08657103d8f9be56a8abc8a44`（`27b389d`，2026-11-14 13:27:53 +08:00）。
**证据全部在提交前采集**，所以 `checks.json` / `repro.json` 里的 `code_head` 是 `0524d3d`；
时间轴与提交对照见 `commit-reference.md`。复核代码固定用 `git diff 0524d3d -- mvp web scripts`（补丁在 `changes.patch`）。
性质：**工程缺陷整改与可复核证据**。不是设计完成，不是设计通过，不是 AD 验收，**本包不宣布 W0 放行**。

## 1. 架构师五项整改的落地位置

| 编号 | 架构师要求 | 本批处理 | 主要代码位置 |
| --- | --- | --- | --- |
| W0-F01 | 当前任务与反馈覆盖关系 | 当前意图＝**最新一条版本化 feedback**；同基线多条 pending **显式合并、一次性消费**；跨基线 pending **显式冲突**（`multiple_pending_feedback`，不自动合并、不丢弃）；最新已消费**不复活**（`feedback_already_consumed`）；显式 generate 意图**不被历史 consumed 封死**；新增**作废**动作（`superseded` + `superseded_by`，正文保留） | `revision_task.resolve_task`（`revision_task.py:119`）、`_generate`（:229）、`_conflict`（:247）；`store.withdraw_feedback`（`store.py:420`）；`server.py` `POST /studio/projects/<pid>/feedback/<fid>/withdraw`；`orchestrator.run_a1` 合并消费 |
| W0-F02 | 多对象目标不能部分达标就通过 | 目标带 `objects_scope`/`object_ids` + `comparator`（min/exact/max）+ `quantifier`（默认 all）；**部分达标＝fail**、**对象缺失＝fail**、**空目标集＝unknown**；净宽同时校验声明值、几何实测值、绝对下限与 CIR 现场问题，并明写 `coverage` 有限范围 | `_measure`（`revision_task.py:569`）、`_cmp_ok`（:542）、`_aggregate`（:556）、`recheck_objectives`（:647） |
| W0-F03 | 未绑定的保留要求不能假通过 | 保留要求先**绑定对象**（对象 id 边界匹配，或对象 `name` 出现在该子句）；resolved → **按本条自己的对象**复核；unresolved/ambiguous → `unknown` + `user_confirmed=pending` + 原句 + 候选对象，**不拿入口锁顶替**；删除按关键词猜对象的旧路径 | `preserve_clauses`（:386）、`resolve_preserve_binding`（:392）、`resolve_preserve_bindings`（:420）、`_recheck_lock_objective`（:723）；`orchestrator._resolved_text_locks` |
| W0-F04 | 字段锁不能变整对象锁 | `lock_conflicts` 改为字段级：`fields:["*"]` 才锁整对象，否则只比较指定字段；删除必冲突；未知字段/对象不存在/基线无此对象各有独立 `diagnostic`；四级校验的锁定阶段复用同一函数，**不再静默升级** | `revision_task.lock_conflicts`（:294）；`validation.validate_proposal` 第 4 阶段；`revision.py` 完整性检查 |
| W0-F05 | 完成状态与产物快照必须一致 | `project_state` 在**单个读事务**内读完 messages/artifacts/runs/gates/feedback，返回 `snapshot.token`；新增 `run_snapshot(project, run)` 与 `GET /studio/projects/<pid>/runs/<run_id>`；页面按 **run_id** 轮询本轮，不再用 `runs[-1]` 猜；自动返工按**设计试验**累计落库（`runs.trial_key`、`runs.auto_rework_total`），新 run 继承不归零 | `store.project_state`（`store.py:793`）、`store.run_snapshot`（:854）、`trial_key_for`（:711）、`auto_rework_used`（:736）、`finish_run`（:765）；`server.py` 新增 GET 路由；`web/src/StudioView.tsx` 轮询 |

## 2. 先复现、再修复、再验证（同一脚本，可复跑）

`scripts/w0b_repro.py`：纯函数 / Store 级，**不起服务、不调模型**，隔离临时库；
判定签名固定为 `defect_reproduced / fixed_signature / not_observable / crashed`。

| 阶段 | 命令 | 结果 | 证据 |
| --- | --- | --- | --- |
| 整改前 | `scripts/w0b_repro.py --phase before --out .../before/repro.json` | **17/17 `defect_reproduced`**（0 fixed / 0 not_observable / 0 crashed），执行 2026-11-14T12:54:07+08:00，`git_head=0524d3d` | `before/repro.json` |
| 整改后 | 同一脚本 `--phase after --out .../after/repro.json` | **17/17 `fixed_signature`**（0 defect / 0 crashed），执行 2026-11-14T13:24:45+08:00 | `after/repro.json` |

17 例覆盖（每条都对应架构师点名的一类缺陷）：
F01-a 旧反馈在执行最新一条后复活；F01-b 已消费历史封死新生成；F01-c 跨候选两条待续改被无声合并/丢弃；
F01-d 同基线多条未显式合并；F01-e 自动返工未按设计试验累计；
F02-a 多对象只一个达标即 pass；F02-b 点名对象不存在仍 pass；F02-c 只有无关对象恰好达标即 pass；
F02-d 比较符被忽略（min/exact/max 混用）；
F03-a 保留的是非入口对象却校验了入口锁；F03-b 未绑定的保留要求被当通过/被降级成空泛意见；
F03-c 只有保留诉求时诉求被丢弃；F03-e 混合留言的保留诉求被数值目标吞掉或未绑对象；
F04-a 锁 `x` 也拦下改 `rot`、未知字段无诊断；F04-b 四级校验把字段锁升级成整对象锁；
F05-a 状态混拼两个时间点（run 已完成、同一快照却没有它的产物）；F05-b 只能靠 `runs[-1]` 猜本轮。

> 修正记录（不粉饰）：第一版复现脚本 4 个 F03 用例因 `derive_objectives` 当时不接受 `plan=` 参数而
> `crashed`；F05-a 与 F03-b/F03-e 的判定条件一开始判不出旧实现的缺陷（分别误判成 `fixed_signature`）。
> 已分别为 `_derive()` 加签名兼容、为 F05 改用 `project_state(barrier=...)` 同步接缝、为 F03 增加
> "必须存在 preserve 类型目标且 `binding_status ∈ {unresolved,ambiguous}`"、"preserve 必须带 `object_ids`"
> 的判定，整改前才拿到 17/17。判宽是**加严**，不是放宽。

## 3. 真实 HTTP 正负例（15 项，全部 `observed_pass`）

`scripts/verify_w0b.py`：真实 Studio HTTP 服务 + 隔离 SQLite（`runtime/w0b-verify.db`）+ 明确标注的本地模型桩；
晚到/取消用**可控屏障**（`GatedStub`：桩在指定调用处停住并置事件，释放后继续），**没有 sleep 制造通过**。
执行 2026-11-14T13:17（`after/checks.json`，`code_head=0524d3d`，`external_calls=0`）。

| 编号 | 覆盖点 | 关键断言 |
| --- | --- | --- |
| W0B-C00 | 基座 | 一次真实 generate 出 A/B 两份有效候选，按 `run_id` 读到同一快照 |
| W0B-F01-01 | 连续两条同基线留言 | 显式合并为一轮续改，两条被**同一个** run 消费（`merged_feedback_ids` 2 条） |
| W0B-F01-02 | 两条都已消费后再开轮 | 明确冲突 `feedback_already_consumed`；旧留言不复活、不偷换基线 |
| W0B-F01-03 | 续改之后要新生成 | 显式 generate 意图不被历史 consumed 封死，正常出新的 A/B |
| W0B-F01-04 | 跨候选两条待续改 | 拒绝自动合并（`multiple_pending_feedback`），要求先决定，且**不丢下更早那条** |
| W0B-F01-05 | 显式作废更早那条 | 按剩下那条续改；被作废留言正文与 `superseded_by` 保留在历史里 |
| W0B-F01-06 | 自动返工累计 | 同一设计试验用满 2 轮后 `runs.auto_rework_total=2`，新 run 不归零，上限仍是 2 |
| W0B-F02-01 | 两个目标只达标一个 | `REV-OBJECTIVE` 拒绝，诊断里点名未达标的 F2，本轮无有效修订 |
| W0B-F02-02 | 比较符语义 + 声明≠实测 | min/exact/max 五个目标给出 `pass/pass/fail/pass/fail`；净宽目标在"声明 2300mm 满足 max 2400、几何实测 6000mm 不满足"时**判 fail**（`declared_meets_target=true, measured_meets_target=false`） |
| W0B-F03-01 | 保留的是非入口对象 ZA5 | 改动 ZA5 → 明确拒绝，不拿入口锁冒充 |
| W0B-F03-02 | 找不到对象的保留要求 | `unknown` + `pending`，并记下未绑定原句 |
| W0B-F04-01 | 锁 F1.x 只改 F1.rot | **允许通过**（字段锁不是整对象锁） |
| W0B-F04-02 | 锁 F1.x 且真改了 F1.x | 拒绝，冲突给出被锁字段 `["x"]` 与 `LOCK-REVISION` |
| W0B-F05-01 | 运行中到达新留言 | 本轮先跑出**契约有效**的候选，随后被判 `superseded`：`run_snapshot` 里 2 份产物 `status=superseded`、有效产物 0；`cancel_requested=1`；`stage_status.last_completed_run_status=superseded` |
| W0B-F05-02 | 完成状态与产物同快照 | `last_completed_run_id` 与 `last_completed_run.id` 一致，其 `artifact_ids` 全部在同一 `artifacts` 里；`snapshot.token` 16 位 |

### 3.1 F05 的关键证据（这条最容易被"看起来过了"骗）

`after/checks.json` → `W0B-F05-01.evidence`：

```
final_run_status = superseded          run_snapshot_artifact_count = 2
run_snapshot_artifacts = [["spatial-plan","superseded","valid_candidate"],
                          ["plan-sketch","superseded",null]]
valid_artifacts_of_run_after = 0       cancel_requested = 1
```

即：这一轮**本来能交出合格修订**（`contract_status=valid_candidate`），因为老板在运行中又发了一条
"这一版不要了"，结果被标 `superseded`、不进当前版本；旧字节仍在，可追。这是"晚到不当前"的正证，
不是靠一个本来就无效的结果蒙对。

### 3.2 关于 `measured_clear_width_mm = 6000` 的口径说明

几何引擎对动线的实测净宽是"沿路径采样、取到最近障碍物距离 ×2 的最小值"，只算家具/障碍物，
**不覆盖门洞、墙体、家具遮挡与完整净宽合规**——这一点写在每条净宽目标的 `evidence.after.coverage` 里。
所以 6000mm 是"障碍物净距"，不是"门洞净宽"。本条用例正是用它证明：**声明值满足目标不能放行，
实测值不满足就是 fail**。该口径是上一批既有实现，本批没有改宽或改窄它。

## 4. 真实浏览器证据（用户实际路径）

`scripts/verify_w0b_browser.py` + `.cjs`，真实 Edge（`--headless`），隔离主工作台 + 隔离 Studio，
执行 2026-11-14T13:24:16+08:00，`passed=true`、`node_returncode=0`、21.2s、`page_errors=[]`。

| 观察点 | 实测 |
| --- | --- |
| 选中候选 A v1 后连续两条留言 | 页面任务条显示"**合并 2 条同基线留言**"，并显示"设计试验累计：第 1 轮 · 自动返工 0/2" |
| 开一轮后续改 | `runs[-1].task_kind=revise`、`status=succeeded`；新修订 `parent_revision_uid=revuid_c3a96672d3`（= 选中旧版）；`consumed_feedback_revisions=[1,2]` |
| 已消费后再开一轮 | 页面上出现中性提示（`studio-note`）"已经执行过"，**弹窗数 0**（`alert_count_after_run=0`）——不再冒充"新任务已接住" |
| 跨候选两条待续改 | 页面显示冲突告警与"先决定"的要求；待办清单 1 条 |
| 点"作废这条" | 任务回到 `revise`、目标回到 A；被作废留言在页面上以删除线 + `superseded_by` **保留**（`page_shows_withdrawn=true`） |
| 390px | `scrollWidth=390`，无横向溢出 |
| 重启后 | 新 `Store` 读同一隔离库，反馈/任务/闸口/修订链/旧基线字节全部保留（`old_baseline_bytes_preserved=true`） |

截图：`browser/w0b-merged-desktop.png`、`browser/w0b-pending-desktop.png`、`browser/w0b-mobile.png`。

## 5. 回归与构建（实际执行）

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `PYTHONPATH=mvp;scripts;. .venv/Scripts/python.exe -m unittest discover -s mvp/tests -q` | **262 tests OK**（362.9s） | `runtime/full-unittest.log`。日志开头一行 `request failed: RuntimeError` 是既有用例**主动触发失败通道**时的打印，不是失败；末尾 `OK` |
| `scripts/verify_arc_first_batch.py --out .../after/arc-first-batch-regression-checks.json` | Q01—Q09、Q11、Q12 **PASS**；Q10 **NOT_RUN**；11 pass / 0 fail / 1 not_run | `after/arc-first-batch-regression-checks.json`、`after/q-checks.json` |
| `scripts/verify_w0.py`（上一批 R1/R2/R3 专项） | **7/7 PASS**（含此前偶发的 W0-R1-01 现在稳定通过） | 本次重跑结果另存 `runtime/verify_w0-rerun-checks.json`（sha256 前 16 位 `360d3ba01bd29b3e`）；**历史证据已恢复为上一批原件**（`var/evidence/roadmap/W0-收口/after/checks.json`，sha256 前 16 位 `cb87518bb3bb0652`） |
| `npx tsc --noEmit`（`web/`） | EXIT=0（无输出即通过，日志 0 字节） | `runtime/frontend-tsc.log` |
| `npm run build`（`web/`） | EXIT=0（保留既有 chunk >500kB 告警） | `runtime/frontend-build.log` |

> 事故与处理（如实）：`verify_w0.py` 输出路径写死在上一批证据目录、没有 `--out` 参数，
> 我直接重跑时覆盖了 `var/evidence/roadmap/W0-收口/after/checks.json`。
> 上一批交付包内的副本字节未变，已用该副本把 `var/` 下的文件**恢复为原件**（sha256 与包内一致），
> 本次重跑结果单独留档到本批 `runtime/`。没有回填、没有改历史结论；该脚本的输出路径问题留给下一批决定是否加参数。

## 6. 仍然不像设计公司成果的地方（逐条）

1. **本批没有新增任何设计成果**：没有封面/设计说明、正式平面布置图、动线分析图、泡泡图、天花图、
   立面图、材料与灯光板、人眼效果图、可发客户 PDF。与上一批相比，设计差距**一点也没减少**。
2. **图面仍是概念平面草案**：只画分区轮廓/名称/面积、展台、动线、家具方框；没有墙体围合、柱网、
   门窗、楼梯构造、洁具、尺寸链、材料色块。
3. **天花与灯光仍不上图**：数据里有灯槽/灯具点位，制图器未画；照度、配光、间距未算，也未编造。
4. **0 张人眼效果图**：案例参照图仍是人工编写的手工样板，明确标注，不计入系统自动生成成果。
5. **设计来源不是系统自动设计**：全部回路用明确标记的本地模型桩（`local-model-stub`）；
   真实 AI 设计能力、真实用户设计评价、专业签核均未完成。本批是工程修复批。
6. **几何能力仍受限**：单层、多边形分区，无曲面/多层/异形；门窗/柱网/消防疏散/无障碍标 `unsupported`，
   不宣称合规；净宽实测只算障碍物净距（见 3.2）。
7. **量价**：本批未做同源量价；`unknown` 保持 `unknown`，未补 0。
8. **工程 PASS 不等于设计成立**：闸口仍等用户；`AD01—AD08` 未改判；`Q10` 仍 `not_run`；
   **`flow succeeded` 只表示流程跑完**。

## 7. 外部调用与费用（本批实测）

| 项 | 数值 |
| --- | --- |
| 外部模型调用 | **0** |
| 外部图像通道调用 | **0** |
| 外发图片 / 生成图片（外部） | **0 / 0** |
| 真实模型 tokens | **0**（桩计数只用于台账演练） |
| 金额 | **0**（`cost_status=no_external_calls_zero_cost`，无价表不推测单价） |
| 密钥 | 未使用、未写入任何文件/日志/Git/截图 |

本提示词未新增费用或外发授权，本批也未申请任何新授权；未重跑付费模型。

## 8. 风险、限制与边界（不做的事）

- **未做 W1—W4**：docs/26 硬节点；W0 是否放行由架构师复核后决定，**本包不自行宣布放行**，也不开始 W1。
- **未扩 A2 自由协作**、**未提高自动返工上限**（`MAX_AUTO_REWORK=2` 未动）、**未拆新 run 绕过上限**
  （改为按设计试验累计，新 run 继承旧值）。
- **自动返工只在 generate 运行的内部打回循环里发生**，revise 路径不自动重复：
  续改是老板点名改一份旧稿，自动重试容易偏离指示，改为把失败原因落到闸口交人决定。
  这是**已知限制**，不是"已经解决"。
- **`feedback` / `runs` 新列是 Studio 实验库的 additive 迁移**；Studio 仍不是主系统成果登记权威。
- 浏览器验收用固定端口与隔离 CORS 白名单，只用于本地验收，不当生产能力。
- 本批没有删除任何失败证据、没有调宽任何断言、没有用 sleep 制造通过。

## 9. 分工边界

| 主体 | 本批 | 不可替代的边界 |
| --- | --- | --- |
| 执行 AI（本包） | 复现、修复、正负例、服务/浏览器验收、证据与状态更新 | 未宣布设计成立、未宣布 W0 放行、未改 AD 分母、未把桩方案包装成自动设计 |
| 架构师 | 读实际 diff、独立复跑 `w0b_repro.py` / `verify_w0b.py` / 浏览器脚本、核对字节与时间 | 不代替用户审美与专业签核 |
| 用户 | 设计阶段确认、AD01—AD08 | 工程 PASS 不代签用户确认 |

## 10. 完整文件路径（均在 `D:\Github\RKD AI\` 下）

复核包：`deliverables-for-review\roadmap\W0-二次收口\`
- `review-packet.md`（本文件）、`manifest.json`、`code-diff.md`、`changes.patch`、
  `positive-negative-cases.md`、`commit-reference.md`
- `before\repro.json`（整改前 17/17 缺陷）
- `after\repro.json`、`after\checks.json`、`after\arc-first-batch-regression-checks.json`、`after\q-checks.json`
- `browser\verification.json`、`browser\browser-observations.json`、3 张截图
- `runtime\full-unittest.log`、`runtime\frontend-build.log`、`runtime\frontend-tsc.log`

运行证据：`var\evidence\roadmap\W0-二次收口\`（`var/` 被 Git 忽略，不进仓库）

源码改动（生产与前端 8 个文件，+1082/−270；另有 4 个新增验收脚本 1604 行）：
- `mvp\rkd_mvp\studio\revision_task.py`（主要）、`orchestrator.py`、`revision.py`、`validation.py`、`store.py`、`server.py`
- `web\src\StudioView.tsx`、`web\src\studio.css`
- `scripts\w0b_repro.py`、`scripts\verify_w0b.py`、`scripts\verify_w0b_browser.py`、`scripts\verify_w0b_browser.cjs`（新增）

唯一状态表：`PROJECT_STATUS.md`（本批已更新顶部为"W0 架构复核要求限定整改"，未改 AD 结论）。
