# W0 文字反馈保守判定 · 架构师复核包（TEXT-01 最后收口）

编制时间：2026-11-14 18:50（北京时间）；证据实际执行时间见 `manifest.json` 时间轴。
上游依据：`deliverables-for-review/roadmap/TEXT-architect-review/architect-review.md`（结论：原 14 个函数案例与 12 项 HTTP 已独立通过，W0 仍不放行，剩余三处共用解析边界）与同目录 `boundary-cases.json`。
比较基线（base）：`db9121e0abecb6d5cbe3941ec73aab2fe578e6b1`（`db9121e`）；
复核命令：`git diff db9121e -- mvp scripts`（补丁在 `changes.patch`）。
性质：**工程正确性整改与可复核证据**。不是设计完成，不是设计通过，**本包不宣布 W0 放行**，不改 AD01—AD08。

## 1. 三处边界怎么修的（共用解析路径，不是逐句补丁）

架构师点名的三个输入在整改前的实际输出（`before/boundary-cases.json`）：

| 输入 | 整改前 | 本批 |
| --- | --- | --- |
| `不要把 F3 旋转到 -30 度` | `computable=true`、`exact -30`、`object_ids=["F3"]`、**pending=[]** —— 反转成可执行目标 | **不生成 measurable**；整项 `negated_requirement` → `unknown + pending`，保留原句；且 revise 路径直接 `conflict` 闸口、**不交出修订稿**，避免模型按相反目标改动 |
| `把 F1 和 F9 旋转到 -30 度` | `object_ids=["F1"]`、`binding_status=resolved`、pending=[] —— 缺失的 F9 被吞 | 保留**全部点名引用** `["F1","F9"]`，`binding_status=unresolved`、`missing_object_ids=["F9"]`、复核 **fail**（对象缺失不算达标）；`all_object_references` 一并进证据 |
| `把 F3 旋转到 -30 度并让整体更有设计感` | 只有数值目标、pending=[] —— 同子句尾部被吞 | 记录**已解释片段**（`explained_text=["旋转到 -30 度"]`）与**残余片段**（`residual_text="更有设计感"`），残余单独 `unparsed_remainder_in_clause` → `unknown + pending`；有逗号无逗号都生效 |

### 实现的是"已解析片段 / 未解析片段 + 完整对象引用"的保守判定

1. **否定**：`_clause_is_negated()` 先把**已支持的比较表达**（`不超过/不得超过/不要超过/不大于/不少于/不小于/不低于/最多/以内…`）和**保留表达**（`保留/不动/保持/原样/不改/不要改/别动…`）整体剔除，再判断剩下的 `不要/别/不得/不能/不可/不许/勿/禁止/避免` 是否作用于整句。所以 `不超过 2400mm` 仍是 max、`不低于 4000K` 仍是 min、`其他家具不动` 仍是保留约束；只有像"不要把…旋转到…"这种**没有对应可计算规则**的否定被判为未解析。程序没有"不等于/不得改为"规则，就不生成正向目标。
2. **完整对象引用**：`_clause_binding` 同时记录真实 id、对象名命中、以及**形如对象 id 但基线里不存在**的 token；`_measurable_binding` 在有缺失引用时不再提前返回已找到的 ids，而是把全部引用一起交给复核（缺失 → fail）。另补两类歧义：一句里出现多个对象名、或显式 id 与"该 id 也叫这个名字"的名称混用 → `ambiguous_object_names` + 候选、`computable=false`，不挑一个冒充绑定成功。
3. **片段记账**：`_explained_spans()` 收集本句里被规则真正解释的字符区间（数值规则命中、对象 id/名称、比较词、保留词），`_substantive_residual()` 掩掉这些区间并去掉结构性/主语词，**只要还有汉字就当作未解释的诉求** → 单列 pending 并附 `source_text` + `residual_text`。这是通用残余判定，不依赖用户打标点，也不是给"设计感"加一条补丁：`并复核北侧收口` 同样会留痕（CONS-08 / B07）。
4. **保守拒绝**：`orchestrator` 新增 `UnresolvedRequirement`——只要留言里出现 `negated_requirement`（即"看起来像数值目标但被否定"），run 记 `conflict`、0 产物、闸口列出原句与 `unknown + pending`，**不用返工硬凑**、不把这种输入变成成功修订。纯粹审美/无规则的留言仍按既有行为走（流程可跑完，但待确认项在时间线与页面里明确可见）。

未改：任务选择、字段锁、事务快照、累计返工、四类可计算规则、几何净宽口径、契约 schema、前端交互、AD 判定文档。

## 2. 前后对照（同一脚本，两个代码树）

整改前代码由 `git worktree` 单独检出 `db9121e`，与当前工作区互不干扰；两组脚本**完全相同**，只换 PYTHONPATH。

| 阶段 | 命令 | 结果 | 证据 |
| --- | --- | --- | --- |
| 整改前 | `scripts/boundary_cases.py --phase before --out .../before/boundary-cases.json` | **7 `defect_reproduced` / 3 `fixed_signature`** | `before/boundary-cases.json` |
| 整改后 | 同一脚本 `--phase after` | **10/10 `fixed_signature`** | `after/boundary-cases.json` |
| 整改前 | `scripts/verify_conservative_http.py --out .../before/conservative-http` | **5 pass / 5 fail** | `before/conservative-http/checks.json` |
| 整改后 | 同一脚本 `--out .../after/conservative-http` | **10/10 `observed_pass`** | `after/conservative-http/checks.json` |

> 执行顺序是先跑整改后、再跑整改前，两个 JSON 的 `executed_at` 反映了这一顺序，时间轴如实记录。
> 整改前就通过的 B04（仅缺失对象）、B08（有标点审美）、B09（保留词不误判）、CONS-02/03（支持比较符）、
> CONS-06/09/10 都是**回归护栏**，不算本批成果；它们的作用是证明新逻辑没有把已经对的行为改坏。

10 个函数级边界：B01 否定不反转、B02 否定与支持比较符区分、B03 存在+缺失、B04 仅缺失、
B05 存在+歧义名称、B06 无逗号复合句、B07 通用残余（非审美词）、B08 有标点复合句、
B09 保留词不误判、B10 已解析/原句/残余片段都留痕。

## 3. 真实 HTTP 10 项（全部走正常文字入口）

`scripts/verify_conservative_http.py`：隔离 Studio 库 + 真实 HTTP 服务 + 明确标注的本地模型桩。
所有留言 `POST /messages` 只发 `text` + 选定基线，**不注入 objectives/locks**（脚本 `entry_note` 有声明）。

| 编号 | 老板原话 | 断言 | 结果 |
| --- | --- | --- | --- |
| CONS-01 | 不要把 F3 旋转到 -30 度 | `status=conflict`、0 产物、闸口含原句与"否定要求"/`unknown + pending`；无相反目标 | pass |
| CONS-02 | 主动线净宽不超过 2400mm（改 2600） | 仍是 `max`、判 fail；**不**被否定守卫误杀 | pass |
| CONS-03 | L1 色温不低于 4000K（改 3600） | 仍是 `min`、判 fail；不被否定守卫误杀 | pass |
| CONS-04 | 不要把主动线净宽扩大到 2400mm | `conflict`、0 产物；不变成 `min 2400` 正向目标 | pass |
| CONS-05 | 把 F1 和 F9 旋转到 -30 度（只改 F1） | `incomplete`；`target_objects=["F1","F9"]`、`all_object_references=["F1","F9"]`、`missing=["F9"]`、fail | pass |
| CONS-06 | 把 F9 旋转到 30 度 | `incomplete`；仅缺失对象仍按缺失阻断（回归护栏） | pass |
| CONS-07 | 把 F3 旋转到 -30 度并让整体更有设计感 | `succeeded`；数值 pass **且** 审美残余 `unknown+pending`、`residual_text` 含"设计感"；时间线写明"还有 N 条未验证" | pass |
| CONS-08 | 把 F3 旋转到 -30 度并复核北侧收口 | 非审美残余同样留痕（"收口"），证明残余判定是通用的 | pass |
| CONS-09 | 把 F3 旋转到 -30 度，整体更有设计感 | 有标点时审美仍 pending（回归护栏） | pass |
| CONS-10 | 把 F3 旋转到 -30 度，其他家具不动 | `succeeded`；保留约束照常生效，否定守卫不误判 | pass |

**失败/未解析在证据中可见**：CONS-01/04 的闸口消息带 `evidence.type=unresolved_requirement`（原句、
`unparsed_reason`、对象引用、待确认状态）；CONS-05 的 raw 产物 `integrity.objective_rechecks`
带 `missing_object_ids`；CONS-07/08/09 的成功修订产物里保留 `user_confirmed=pending` 与
`residual_text`，完成 note 明确写"还有 N 条目标未验证/等用户确认"。

## 4. 真实浏览器（正常文字输入，未注入结构化目标）

`scripts/verify_conservative_browser.py` + `.cjs`，真实 Edge（headless），隔离主工作台 + 隔离 Studio，
`passed=true`、`node_returncode=0`、`page_errors=[]`（证据 `browser/verification.json`、
`browser-observations.json`、2 张截图）。

| 观察点 | 实测 |
| --- | --- |
| 页面输入 | 选「候选 A v1」→ 输入框打**无逗号复合句**「把 F3 旋转到 -30 度并让整体更有设计感」→ 发给公司 → 开一轮 |
| 任务/版本 | `task_resolution.kind=revise`；`task_kind=revise`、`status=succeeded`；新修订 v2 的父版本 uid = 选中旧版 |
| 目标 | measurable `STD-001 / -30 / ["F3"] / pass`；另有 `aesthetic` 项 `unparsed_remainder_in_clause`、`residual_text="更有设计感"`、`unknown + pending` |
| 对象 diff | `["furniture:F3"]` |
| 页面可见的待确认 | `page_has_pending_note=true`，页面文字含「未验证/待你确认：1 项（FBFB1-U0）——程序没有把它们算成通过」 |
| 告警/窄屏 | 红色告警 0 条；390px `scrollWidth=390` |
| 截图 | `conservative-desktop.png`、`conservative-mobile.png` |

## 5. 回归（保留 14/12，并覆盖受影响测试）

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `scripts/text_feedback_cases.py --phase after` | **14/14 `fixed_signature`** | `after/regression-14.json` |
| `scripts/verify_text_http.py` | **12/12 `observed_pass`** | `after/regression-12/checks.json` |
| `scripts/w0b_repro.py --phase after` | **17/17 `fixed_signature`** | `after/regression-w0b-repro.json` |
| `scripts/verify_w0b.py` | **15/15 `observed_pass`** | `after/regression-w0b-http/checks.json` |
| `scripts/verify_w0.py` | **7/7 PASS** | `after/regression-w0/checks.json` |
| `scripts/verify_arc_first_batch.py` | Q01—Q09、Q11、Q12 **PASS**；Q10 **NOT_RUN**；11 pass / 0 fail / 1 not_run | `after/regression-arc-first-batch.json`、`after/q-checks.json` |
| `scripts/verify_text_browser.py`（上一批浏览器路径） | `passed=true` | `after/browser-previous/verification.json` |
| `PYTHONPATH=mvp;scripts;. .venv/Scripts/python.exe -m unittest discover -s mvp/tests -q` | **262 tests OK**（454.0 s） | `runtime/full-unittest.log` |
| `npx tsc --noEmit`（`web/`） | EXIT=0（无输出即通过） | `runtime/frontend-tsc.log` |

证据全部写入新目录 `var/evidence/roadmap/W0-文字反馈保守判定/`，
**没有覆盖** `W0-收口` / `W0-二次收口` / `W0-文字反馈收口` / `TEXT-architect-review` 的任何历史文件。

## 6. 仍然不像设计公司成果的地方（逐条）

1. **本批没有新增任何设计成果**：无封面/设计说明、正式平面布置图、动线分析图、泡泡图、天花图、
   立面图、材料与灯光板、人眼效果图、可发客户 PDF。与前几批相比设计差距**一点没变**。
2. 图面仍是概念平面草案：无墙体围合、柱网、门窗、楼梯构造、尺寸链、材料色块。
3. 0 张人眼效果图；案例参照图仍是人工编写的手工样板，明确标注，不计入系统自动生成成果。
4. 设计来源仍是明确标记的本地模型桩（`local-model-stub`）；真实 AI 设计能力、真实用户设计评价、
   专业签核均未完成。本批是**文字理解的保守正确性**修复。
5. 语义覆盖仍然很窄：只支持净宽/旋转/色温/面积四类可计算规则与有限的比较/保留表达；
   **范围外一律 `unknown+pending`**，包括否定要求、一句多值、复合句尾部、未建模修饰语
   （如"顺时针"）。这是刻意的保守取舍，不是"任意普通文字都能正确理解"。
6. 净宽实测口径仍是"沿动线到最近障碍物距离 ×2"，不覆盖门洞/墙体/家具遮挡，`coverage` 里明写。
7. `succeeded` 只表示流程跑完；`AD01—AD08` 未改判；`Q10` 仍 `not_run`；用户设计阶段确认未发生。

## 7. 外部调用与费用（本批实测）

| 项 | 数值 |
| --- | --- |
| 外部模型调用 | **0** |
| 外部图像通道调用 | **0** |
| 外发图片 / 生成图片（外部） | **0 / 0** |
| 真实模型 tokens | **0**（桩计数仅用于台账演练） |
| 金额 | **0**（`cost_status=no_external_calls_zero_cost`） |
| 密钥 | 未使用、未写入任何文件/日志/Git/截图 |

没有新增付费调用，没有新增外发授权，没有扩管理配套。

## 8. 已知限制与边界（不做的事）

- **未做 W1—W4**：W0 是否放行由架构师复核决定，本包不自行宣布。
- 未扩 A2、未提高自动返工上限（仍 `MAX_AUTO_REWORK=2`）、未拆新 run 绕过上限。
- 未改契约 schema、几何净宽口径、前端交互、AD 判定文档、`docs/26` 路线。
- **否定要求没有被翻译成"不等于"规则**：程序没有这个能力，所以整项 pending 且 revise 直接停下；
  这不是"支持了否定"，而是"确认无法正确理解时保守拒绝"。
- 残余片段只做留痕，**不会自动翻译成可计算目标**；用户要把它变成要求，需要另写可解析的句子。
- 名称歧义组合（如"F1 和洽谈桌"）只在函数级做夹具验证，HTTP 层因隔离库对象名固定未构造同名场景；
  没有把它说成浏览器实测。
- `snapshot.token` 仍是诊断标签（架构师非阻断说明），本批未改。

## 9. 分工边界

| 主体 | 本批 | 不可替代的边界 |
| --- | --- | --- |
| 执行 AI（本包） | 复现、共用解析路径修复、函数级/HTTP/浏览器正负例、回归、证据与状态更新 | 未宣布设计成立、未宣布 W0 放行、未改 AD 分母、未把桩结果说成真实设计 |
| 架构师 | 读实际 diff、独立复跑三套脚本、核对前后证据与字节 | 不代替用户审美与专业签核 |
| 用户 | 设计阶段确认、AD01—AD08 | 工程 PASS 不代签用户确认 |

## 10. 完整文件路径（均在 `D:\Github\RKD AI\` 下）

复核包：`deliverables-for-review\roadmap\W0-文字反馈保守判定\`
- `review-packet.md`（本文件）、`manifest.json`、`code-diff.md`、`changes.patch`、
  `positive-negative-cases.md`、`commit-reference.md`
- `before\boundary-cases.json`、`before\conservative-http\checks.json`（整改前，临时工作树 `db9121e`）
- `after\boundary-cases.json`、`after\conservative-http\checks.json`、
  `after\regression-14.json`、`after\regression-12\checks.json`、
  `after\regression-w0b-repro.json`、`after\regression-w0b-http\checks.json`、
  `after\regression-w0\checks.json`、`after\regression-arc-first-batch.json`、`after\q-checks.json`
- `browser\verification.json`、`browser\browser-observations.json`、
  `browser\conservative-desktop.png`、`browser\conservative-mobile.png`
- `runtime\full-unittest.log`、`runtime\frontend-tsc.log`

运行证据：`var\evidence\roadmap\W0-文字反馈保守判定\`（`var/` 被 Git 忽略；`before-code/` 是临时 worktree，复核后可删）

源码改动（2 个生产文件 + 4 个新增验收脚本）：
- `mvp\rkd_mvp\studio\revision_task.py`（主改：否定判定、完整对象引用、已解释/残余片段记账）
- `mvp\rkd_mvp\studio\orchestrator.py`（`UnresolvedRequirement` → conflict 闸口，否定要求不交稿）
- `scripts\boundary_cases.py`、`scripts\verify_conservative_http.py`、
  `scripts\verify_conservative_browser.py`、`scripts\verify_conservative_browser.cjs`（新增）

唯一状态表：`PROJECT_STATUS.md`（本批已更新，未改 AD 结论）。
