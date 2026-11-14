# W0 收口 · 架构师复核包（R1 / R2 / R3）

编制日期：2026-11-14（北京时间）
执行委托：`docs/26-持续制作路线与周期复核计划.md` 第 3、4、6 节 + 第 8 节提示词。
源码基线（base）：`957cf775e1d835cf25bbdf196de4e7f3f51280fa`（`957cf77`）；主体实现 `eb6513c` 为上一批。
本批提交号：见同目录 `manifest.json` 与 `commit-reference.md`（补录提交仅追加清单，无业务代码改动）。
性质：**工程控制整改与可复核证据**。不是功能完成证明，不是设计通过，不是 AD 验收，不是阶段升级。

## 1. 需求映射（本批只做 W0，不越级）

| 架构师结论 | 本批处理 | 落到哪里 |
| --- | --- | --- |
| R1 旧方案反馈仍可能变成重新生成 | generate / revise / retry / conflict 四种任务分离；revise 加载反馈指定的旧产物完整基线，不先生成 A/B；不适用旧基线明确冲突，不偷换 | `revision_task.resolve_task`、`orchestrator.run_a1` / `_revise_from_baseline`、`server.do_POST(/messages|/run)`、`store`（additive 列 + CAS 消费） |
| R2 对象变化不能证明具体问题解决 | 四态分离 `input_included / object_changed / objective_rechecked / user_confirmed`；可计算目标由净宽/角度/色温/面积/锁定规则实测复核；审美与未实现写 `unknown` + `pending`；全局 fail 兜底拒绝伪修复 | `revision_task.recheck_objectives`、`revision.verify_revision_integrity` |
| R3 核对证据版本与语义 | 独立勘误记录：编制/执行/复跑补生成/提交分别标时间与代码基线；按**实际三份 schema** 修正契约映射；历史证据字节不回写 | `evidence-provenance-erratum.md`；`w0_repro.py` R3-a/R3-b |

明确未做（按 docs/26 硬节点）：
- **W1 统一模型适配、W2 同源平面/人眼效果图、W3 真实设计验证、W4 完整成果，一律未开始**。W0 收口完成是硬节点 1，须先交架构师复核。
- 未扩 A2 自由协作、未提高自动返工上限（`MAX_AUTO_REWORK = 2` 保持）、未拆成新 run 绕过上限（feedback CAS 消费 + `feedback_already_consumed` 冲突）。
- 未重跑付费模型、未新增外发授权、未扩 NAS/PG/账号/备份配套。

## 2. 本轮实际做了什么 / 没做什么 / 为什么

### 做了

1. **先复现再实现**：新增 `scripts/w0_repro.py`，整改前实测 7/7 缺陷确认，证据
   `var/evidence/roadmap/W0-收口/before/reproduction.json`。关键实测：
   - R1-b：反馈指定 `art_414dd516b2`（`revuid_ef1bc05689`），第二轮仍生成 **2 个全新 A/B**，修订的
     `parent_revision_uid=revuid_10f811980d` 指向本轮新候选，不是用户选中的旧版。
   - R1-c：真实 HTTP `/messages` 把用户指定的 `art_414dd516b2` **偷换成** `art_f35ba7261d`
     （`_latest_valid_plan` 按最新文件猜），返回 201 且无任何冲突提示。
   - R2-a：伪修复（只改 `CA1` 的颜色/标签，`width_mm` 仍 2000）被记为
     `verified=true`、`recheck="对象 diff 复核"`、`ok=true`。
   - R2-b：`boss_feedback_resolutions.linked_changes` 等于**全部**变化对象，且直接写
     `in_revision_input=true`。
   - R3-a：复核包编制 2026-11-12，执行 11-12T23:02/23:48，`checks.json` 复跑补生成
     11-14T11:21:20，代码提交 11-14T11:26:18/47，头部只有一个笼统日期。
   - R3-b：`spatial-plan-proposal.v1` 实际**不含** `contract_version` / `project_id`；
     `ai-design-option.v1` 用 `schema_version` 且 `additionalProperties:false`、**不含** `project_id`；
     而 `ARC-05-adaptation-note.md` 第 2 节把三者混写成一行。
2. **R1 实现**：
   - `resolve_task()` 只从**版本化反馈**决定任务；有显式旧基线且未被消费 → `revise`，否则 `generate`；
     冲突情形（跨项目、uid 不匹配、失败稿/失效稿、旧反馈已消费、并发新反馈、晚到结果）
     一律返回带 `conflict_code` + 替代建议的 **409**，绝不回退到"最新文件"或重新生成 A/B。
   - `run_a1` 同步判定任务并写 `runs.task_kind / target_artifact_id / target_revision_uid`；
     `feedback.consume_feedback` 用 CAS 保证一条反馈只驱动一个 revise run。
   - `_revise_from_baseline()` 加载 `spatial-plan-draft.v1` **完整旧稿**（含 `sha256`），
     白名单 patch 由程序应用、四级契约校验、确定性目标复核，产出新修订的
     `parent_revision_uid` 指向用户选中的旧版本；旧版字节保持可下载。不生成 A/B。
   - `/messages` 严格接受并校验 `baseline_artifact_id` / `baseline_revision_uid`，
     记录 `baseline_selection=user_selected`；未指定时明确 `none_explicit` + generate，**不再猜最新文件**。
   - 结构化对象/字段锁 `structured_locks()`（来源为 `role=arrival`、用户显式 locks 与场地保留条件），
     **不靠中文关键词命中对象名**；冲突给替代建议，不自行解锁。
   - 前端新增「续改哪份旧方案」下拉，页面显示上一轮任务、本轮预判、版本链（新→父）、父版本 uid。
3. **R2 实现**：可计算目标由 `geometry.check_geometry` 复算实测瓶颈与瓶颈规则，
   角度/色温/面积按对象字段实测；`objective_rechecked` 只有规则实测达标才是 `pass`；
   审美与未实现目标写 `unknown` + `user_confirmed=pending` + `resolved=null`；
   任何 fail 都触发 `REV-OBJECTIVE` 并阻止修订入库。
4. **R3 实现**：独立勘误记录（时间轴 + 三份 schema 真实边界 + 修正映射草案供 W1 使用），
   历史 `review-packet.md` / `ARC-05-adaptation-note.md` 字节 SHA 记录且未改动。
5. **验证**：W0 专项 7/7、整改后复现 0/7 缺陷、首批 Q01—Q12 回归 11 pass / 0 fail / 1 not_run、
   全量单测 262/262、A1 管线 15/15、前端生产构建通过、真实浏览器验收 `passed=true`。

### 没做，以及为什么

- 没有做 W1—W4：docs/26 第 3、5 节规定 W0 收口完成先复核，未收口不把反馈链标完成；
  用户确认设计阶段之前不得越级。本批停在硬节点 1。
- 没有把 W0 的工程 PASS 写成"反馈链已完成"或设计通过：`succeeded` 只表示流程跑完。
- 没有回写上一批历史证据（R3 明确要求"补充勘误记录即可"）；也没有把 11-14 事件倒填成 11-12。
- 没有重跑首批浏览器脚本：它的输出路径固定，会覆盖上一批历史截图；W0 浏览器验收在**同一
  StudioView** 上覆盖了更严格的交互（选中旧方案 → 反馈 → 续改 → 父版本对比 → 390px 无溢出），
  且共用服务由 Q 回归、全量单测、A1 管线覆盖。
- 没有把本地桩结果说成真实 AI 设计，没有改 AD 分母，没有替用户给任何阶段结论。

## 3. 验证结果与命令（真实执行，非计划）

| 命令 / 入口 | 结果 | 证据 |
| --- | --- | --- |
| `.venv/Scripts/python.exe -B scripts/w0_repro.py --phase before` | 7/7 缺陷确认 | `before/reproduction.json` |
| 同上 `--phase after` | 0/7 缺陷（7 项均 `not_reproduced`） | `after/reproduction.json` |
| `.venv/Scripts/python.exe -B scripts/verify_w0.py` | **7 observed_pass / 0 fail** | `after/checks.json` |
| `scripts/verify_arc_first_batch.py --out var/evidence/roadmap/W0-收口/after/arc-first-batch-regression-checks.json` | Q01—Q12：**11 pass / 0 fail / 1 not_run（Q10）** | `after/arc-first-batch-regression-checks.json`、`after/q-checks.json` |
| `PYTHONPATH=mvp .venv/Scripts/python.exe -B -m unittest discover -s mvp/tests -q` | **262/262 OK** | `after/full-unittest-final.log` |
| `scripts/verify_studio_loop.py` | A1 管线 **15/15 PASS** | `after/studio-loop.log` |
| `npm run build`（`web/`） | EXIT=0（保留既有 PDF.js 大包告警） | `after/frontend-build.log`（如附） |
| `scripts/verify_w0_browser.py` + `verify_w0_browser.cjs` | `passed=true`，`page_errors=[]`，390px `scrollWidth=390` | `after/browser/verification.json`、`browser-observations.json`、3 张截图 |

> 首批 Q08 脚本新增 `site=SITE` 入参以**启用**确定性净宽复核（加强，不是放宽校验）；
> 同时把伴生 `q-checks.json` 改为写到 `--out` 同目录，避免回归运行覆盖上一批历史证据。
> 这两处改动在 `code-diff.md` 中逐项列出。

## 4. 真实浏览器证据（W0 关键用户动作）

`var/evidence/roadmap/W0-收口/after/browser/`（`deliverables-for-review/roadmap/W0-收口/browser/` 有副本）

- 页面在下拉中**显式选中** `候选 A v1`（`art_…`），提交「把主动线净宽扩大到 2100mm，保留入口」。
- `/messages` 返回 `baseline_selection=user_selected`；`/state.task_resolution.kind=revise`，
  `target_revision_uid` 等于选中旧版 uid。
- 「开一轮」后 `runs[-1].task_kind=revise`、`status=succeeded`；该 run 内
  `fresh_AB_in_revise_run=0`，新修订 `parent_revision_uid` **等于选中旧版 uid**。
- 页面任务条显示「上一轮：revise（流程走完，未验收）」、版本链（新→父）与父版本 uid；
  待决闸口**只有 1 个**，标题已更新为「旧方案续改完成：请决定是否继续」。
- 重启后新 `Store` 读同一隔离库，反馈/任务/闸口/修订链/旧基线字节全部保留。
- 截图：`w0-feedback-desktop.png`、`w0-revision-desktop.png`、`w0-mobile.png`。

## 5. 仍然不像设计公司成果的地方（逐条，如实）

1. **本轮没有新增任何设计成果**：没有封面/设计说明、正式平面布置图、动线分析图、功能泡泡图、
   天花布置图、2 张立面图、材料与灯光板、3 张人眼效果图、可发客户 PDF。既有设计差距**完全没有消除**。
2. **图面仍是概念平面草案**：`sketch.render` 只画分区轮廓/名称/面积、展台、动线、家具方框；
   没有真实墙体围合、柱网、门窗、楼梯构造、洁具、尺寸链、材料实物色块。浏览器截图里的成果栏
   只是草案缩略图，不是能发客户的图纸。
3. **天花与灯光在平面上看不出来**：`ceiling` 数据里有灯槽与灯具点位，但制图器未画；
   照度、配光、间距未计算，未编造数值。
4. **没有人眼效果图/真实材质/软阴影/窗光/绿植/展品**：本批 0 张渲染。案例参照图是
   **人工编写的手工样板**，明确标注、不计入系统自动生成成果。
5. **设计来源不是系统自动设计**：本批全部回路用明确标记的本地模型桩（`local-model-stub`）；
   真实 AI 设计能力、真实用户设计评价、专业签核均未完成。W0 是工程修复批。
6. **几何能力仍受限**：单层、多边形分区，无曲面/多层/异形构造；门窗/柱网/消防疏散/无障碍
   标 `unsupported`，不宣称合规。
7. **成本与量价**：本批未做同源量价；`unknown` 保持 `unknown`，未补 0，未把净地坪小计叫全项目造价。
8. **工程 PASS 不等于设计成立**：闸口仍在等待用户；`AD01—AD08` 未自行改判；
   `Q10`（同源平面/渲染/数量一致性）仍为 `not_run`。

## 6. 外部调用与费用（本批实测）

| 项 | 数值 |
| --- | --- |
| 外部模型调用 | **0** |
| 外部图像通道调用 | **0** |
| 外发图片 | **0 张** |
| 生成图片（外部） | **0 张** |
| 真实模型 tokens | **0**；桩计数仅用于台账演练 |
| 金额 | **0 外部费用**（`cost_status=no_external_calls_zero_cost`），无价表时不推测单价 |
| 密钥 | 未使用、未写入任何文件/日志/Git/截图/报告 |

本提示词未新增费用或资料外发授权，本批也未申请任何新授权。

## 7. 风险、限制与下一步

- **硬节点 1**：W0 收口完成，停在交付点等架构师复核。未收口前不把反馈链标完成，不自行开始 W1。
- 待架构师独立复跑的关键负例：`W0-R1-02`（跨候选/跨项目/旧反馈/并发/失败稿/晚到）、
  `W0-R2-01` 与 `W0-R2-04`（伪修复）、`W0-R3-01`（历史字节与勘误）。
- 已知工程限制：`feedback` / `runs` 新列为 Studio 实验库 additive 字段；Studio 仍**不是**主系统
  成果登记权威；浏览器使用固定 8099 端口与隔离 CORS 白名单，仅用于本地验收。
- 复核包里 `decision-request.md` **省略**：本批没有需要用户选择的事项（用户已授权 W0，
  下一节点是架构师复核，不是用户决定）。
- 架构师复核后可继续的范围建议：W1 统一模型适配（须以勘误记录的**修正后映射表**为准）。
  W2→W3 之间还有同源工程链复核与真实调用额度硬节点；阶段 1→2 / 2→3 只接受用户对具体版本的明确确认。

## 8. 分工边界

| 主体 | 本批 | 不可替代的边界 |
| --- | --- | --- |
| 执行 AI（本包） | 复现、实现、正负例、服务/浏览器验收、证据与状态更新 | 未宣布设计成立、未改 AD 分母、未把人工/桩方案包装成自动设计 |
| 架构师 | 读实际 diff、独立复跑关键负例、核对来源/版本/字节、给工程结论 | 不代替用户审美与专业签核 |
| 用户 | 设计阶段确认、AD01—AD08 | 工程 PASS 不代签用户确认 |
| 专业责任 | 本批未涉及 | 施工图发布/正式报价/合同/下单/付款不在本批范围 |

## 9. 完整文件路径（均为 `D:\Github\RKD AI\` 下）

复核包：`deliverables-for-review\roadmap\W0-收口\`
- `review-packet.md`（本文件）、`checks.json`、`code-diff.md`、`changes.patch`、`manifest.json`
- `positive-negative-cases.md`、`evidence-provenance-erratum.md`、`commit-reference.md`
- `before\reproduction.json`、`after\reproduction.json`、`after\checks.json`
- `after\arc-first-batch-regression-checks.json`、`after\q-checks.json`、`after\full-unittest-final.log`、`after\studio-loop.log`
- `browser\browser-observations.json`、`browser\verification.json`、
  `browser\w0-feedback-desktop.png`、`browser\w0-revision-desktop.png`、`browser\w0-mobile.png`

运行证据：`var\evidence\roadmap\W0-收口\`（同名批次，被 `var/` 忽略，不进 Git）

源码改动：
- `mvp\rkd_mvp\studio\revision_task.py`（新增）
- `mvp\rkd_mvp\studio\orchestrator.py`、`revision.py`、`server.py`、`store.py`
- `web\src\StudioView.tsx`、`web\src\studio.css`
- `scripts\w0_repro.py`、`scripts\verify_w0.py`、`scripts\verify_w0_browser.py`、
  `scripts\verify_w0_browser.cjs`（新增）、`scripts\verify_arc_first_batch.py`（回归适配）

唯一动态状态表：`PROJECT_STATUS.md`（本批已追加 W0 范围，不改 AD 结论）。
