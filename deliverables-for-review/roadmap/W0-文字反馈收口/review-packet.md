# W0 文字反馈收口 · 架构师复核包（TEXT-01）

编制时间：2026-11-14 18:05（北京时间）；证据实际执行时间见 `manifest.json` 时间轴。
上游依据：`deliverables-for-review/roadmap/W0b-architect-review/architect-review.md`（结论：原 17 例与 15 项 HTTP 已独立通过，W0 尚不放行，唯一集中阻断点 TEXT-01）与同目录 `text-feedback-cases.json`。
比较基线（base）：`5571e4ec82753539793e0ae7ecb046bf1c336a73`（`5571e4e`）；
复核命令：`git diff 5571e4e -- mvp scripts`（补丁在 `changes.patch`）。
性质：**工程缺陷整改与可复核证据**。不是设计完成，不是设计通过，**本包不宣布 W0 放行**，不改 AD01—AD08。

## 1. TEXT-01 到底改了什么（只改这一条）

架构师点名的三处错误，都是"普通文字反馈 → 结构化目标"这一步把用户意思改了：

| 架构师复现 | 旧行为（实测） | 本批处理 |
| --- | --- | --- |
| `把 F3 旋转到 -30 度，其他家具不动` | `object_ids=[]`、`objects_scope=[furniture]`、量词 all → 只改 F3 被判 fail，模型可能被诱导去转全部家具；"其他家具不动"只落成 unresolved | 句内点名 F3 → `object_ids=["F3"]`，只核 F3；"其他家具不动"按**消息内被点名对象的补集**绑定到 F1/F2 并整件锁定；误改 F1 直接 `LOCK-PRESERVE` 拒绝 |
| `主动线净宽不超过 2400mm` | `comparator=min`（套用 CIR-001 默认值，"不超过"被吃掉） | 识别 `不超过/不大于/最多/以内/上限/≤` → `max`；`至少/不小于/不少于/以上/≥` → `min`；`等于/恰好/正好/=` → `exact`；都没有才回落到规则默认值，并把 `source_text` 一起记录 |
| `主动线净宽至少 2100mm，同时整体更有设计感` | 只有 measurable，审美诉求消失（仅在整条留言完全没有产出时才补审美） | 每条留言按子句切分：数值 / 保留 / 审美或未解析**三类并存**，未消化子句一律写 `unknown + user_confirmed=pending` 并保留原句 |

配套的边界（同样按复核文件的最小范围）：

- **对象不存在**（`把 F9 旋转到 30 度`）：目标锁定为 F9 并报"对象缺失"判 fail，**不再退化成整类家具**。
- **同名歧义**（两个对象都叫「洽谈桌」）：报 `ambiguous` + 候选，不替用户挑一个。
- **一句多个数值**（`F1 和 F3 分别转到 30 和 -30 度`）：不取第一个，列为 `multiple_values_in_clause` 待确认；一句里除目标值外还有别的数值时，剩余数值单列 `extra_values_not_parsed`。
- **同一目标矛盾**（同基线合并后 `净宽至少 2400` + `净宽不超过 2100`）：`text_conflicts` 判定不可同时成立 → run 记 `conflict`，**不开模型、不用返工硬凑**，闸口列出两条出处等用户决定。
- **评审意见**只把 `suggest` 当要求，`evidence`（"声明净宽 2000mm"这类现状描述）不再被读成第二个目标——这是回归 Q08 时发现的必要修正。

没有做的事：没有新建语义平台、没有模型辅助解析、没有放宽任何断言；前端也没有改（`StudioView` 本来就不提交 `objectives`/`locks`，本次是让服务端从文字里正确解析）。

## 2. 先复现、再修复、再验证（同一脚本对两个版本各跑一次）

为了不靠"读代码判断"，本批把整改前代码单独检出到临时工作树（`git worktree`，`5571e4e`），
用**同一份脚本**跑两次：

| 阶段 | 命令（同一脚本，仅 PYTHONPATH 指向不同代码树） | 结果 | 证据 |
| --- | --- | --- | --- |
| 整改前 | `scripts/text_feedback_cases.py --phase before --out .../before/text-cases.json` | **12 `defect_reproduced` / 1 `fixed_signature` / 1 `not_observable`** | `before/text-cases.json` |
| 整改后 | 同一脚本 `--phase after` | **14/14 `fixed_signature`** | `after/text-cases.json` |
| 整改前 | `scripts/verify_text_http.py --out .../before/http` | **1 pass / 11 fail**（唯一 pass 是 TEXT-02，属"被过宽目标顺带拦下"，见 §4 注） | `before/http/checks.json` |
| 整改后 | 同一脚本 `--out .../after/http` | **12/12 `observed_pass`** | `after/http/checks.json` |

14 个函数级用例：T01-a/b（点名对象不被扩大、误改其他家具被拦）、T02（两个对象只改一个）、
T03（明确说"都/所有"才整组）、T04（对象不存在）、T05（同名歧义）、T06/T07（max/min/exact）、
T08（上限/下限执行方向相反）、T09（一句两值）、T10/T11（数值+审美、数值+保留+审美）、
T12/T13（矛盾要冲突、同向不误报）。

> 唯一在整改前就通过的 T05（同名歧义）是**回归护栏**，不是新修的能力：旧实现已经会报 ambiguous，
> 本批只是确保新解析路径不把它改坏。如实记录，没有把它算成"整改成果"。

## 3. 真实 HTTP 12 项（全部走正常文字入口）

`scripts/verify_text_http.py`：隔离 Studio 库 + 真实 HTTP 服务 + 明确标注的本地模型桩；
**每条留言都只发 `text` + 选定基线**，验收脚本不注入 `objectives`/`locks`（脚本里有 `entry_note` 声明）。

| 编号 | 输入（老板原话） | 断言 | 结果 |
| --- | --- | --- | --- |
| TEXT-01 | 把 F3 旋转到 -30 度，其他家具不动 | `succeeded`；`object_diff=["furniture:F3"]`；目标对象 `["F3"]`；pass | pass |
| TEXT-02 | 同上，但模型顺手改了 F1 | `incomplete`；无有效修订；诊断含 LOCK 冲突与 F1 | pass |
| TEXT-03 | 把 F1 和 F3 都转到 30 度（只改 F3） | `incomplete`；目标 `["F1","F3"]`；fail，failing 含 F1 | pass |
| TEXT-04 | 把家具都转到 30 度（只改 F3） | 目标 `["F1","F2","F3"]`（用户自己说的整组）；fail | pass |
| TEXT-05 | 把 F9 旋转到 30 度 | 目标是 F9；`missing_object_ids=["F9"]`；fail；不退化整组 | pass |
| TEXT-06 | 主动线净宽不超过 2400mm（改成 2600） | `comparator=max`；fail（实测超上限） | pass |
| TEXT-07 | L1 色温不超过 4000K（改成 3500） | `comparator=max`；pass —— 上限正例 | pass |
| TEXT-08 | L1 色温不低于 4000K（改成 3600） | `comparator=min`；fail —— 与上限相反 | pass |
| TEXT-09 | 净宽至少 2100mm，保留入口，整体更有设计感 | 三类目标并存；审美 `unknown+pending`；数值 pass；`succeeded` | pass |
| TEXT-10 | F1 和 F3 分别转到 30 和 -30 度 | 无 measurable 被"验证"；`multiple_values_in_clause` 待确认 | pass |
| TEXT-11 | 先"净宽至少 2400mm"，再"净宽不超过 2100mm"（同基线） | run `status=conflict`、0 产物、闸口同时列出 `min 2400` 与 `max 2100` | pass |
| TEXT-12 | 把 F1 旋转到 45 度 | 回归护栏：普通单对象仍然 `succeeded`、`object_diff=["furniture:F1"]`、`exact` | pass |

## 4. 真实浏览器（正常用户路径）

`scripts/verify_text_browser.py` + `.cjs`，真实 Edge（headless），隔离主工作台 + 隔离 Studio（前端写死 8099，故用同一端口），
`passed=true`、12.1 s、`page_errors=[]`（证据 `after/browser/verification.json`、`browser-observations.json`、2 张截图）。

| 观察点 | 实测 |
| --- | --- |
| 页面操作 | 选「候选 A v1」→ 在输入框打「把 F3 旋转到 -30 度，其他家具不动」→ 点「发给公司」→ 点「开一轮」 |
| 任务判定 | `task_resolution.kind=revise`，`target_artifact_id` 等于选中旧版 |
| 本轮结果 | `task_kind=revise`、`status=succeeded`；新修订 v2 的 `parent_revision_uid` 等于选中旧版 uid |
| 结构化目标（服务端解析，非页面注入） | measurable `STD-001 target=-30`，`target_objects=["F3"]`，pass；preserve `LOCK-PRESERVE`，`target_objects=["F1","F2"]`，pass |
| 对象 diff | `["furniture:F3"]` —— 只改 F3 |
| 页面 | 红色告警 0 条；390px `scrollWidth=390`；无 JS 错误 |
| 截图 | `text-f3-desktop.png`、`text-f3-mobile.png` |

## 5. 回归（原 17 例、原 15 项、上批专项、首批 Q、全量单测）

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `scripts/w0b_repro.py --phase after --out .../after/regression-w0b-repro.json` | **17/17 `fixed_signature`**（0 defect / 0 crashed） | `after/regression-w0b-repro.json` |
| `scripts/verify_w0b.py --out .../after/regression-w0b-http --runtime ...` | **15/15 `observed_pass`** | `after/regression-w0b-http/checks.json` |
| `scripts/verify_w0.py --out .../after/regression-w0` | **7/7 PASS** | `after/regression-w0/checks.json` |
| `scripts/verify_arc_first_batch.py --out .../after/regression-arc-first-batch.json` | Q01—Q09、Q11、Q12 **PASS**；Q10 **NOT_RUN**；11 pass / 0 fail / 1 not_run | `after/regression-arc-first-batch.json`、`after/q-checks.json` |
| `PYTHONPATH=mvp;scripts;. .venv/Scripts/python.exe -m unittest discover -s mvp/tests -q` | **262 tests OK**（见 `runtime/full-unittest.log` 末行） | `runtime/full-unittest.log` |
| `npx tsc --noEmit`（`web/`） | EXIT=0（无输出即通过） | `runtime/frontend-tsc.log` |

> 证据目录全部新建在 `var/evidence/roadmap/W0-文字反馈收口/`，**没有覆盖** `W0-收口`、`W0-二次收口`、
> `W0b-architect-review` 的任何历史文件。
> 为避免再出现上批的覆盖事故，本批给 `verify_w0.py`、`verify_w0b.py` 增加了可选 `--out/--runtime`
> （默认值不变，属测试脚本小修，不影响业务断言）。

## 6. 仍然不像设计公司成果的地方（逐条）

1. **本批没有新增任何设计成果**：无封面/设计说明、正式平面布置图、动线分析图、泡泡图、天花图、
   立面图、材料与灯光板、人眼效果图、可发客户 PDF。与上批相比设计差距**一点没变**。
2. 图面仍是概念平面草案：只画分区轮廓/名称/面积、展台、动线、家具方框；无墙体围合、柱网、门窗、
   楼梯构造、尺寸链、材料色块。
3. 0 张人眼效果图；案例参照图仍是人工编写的手工样板，明确标注，不计入系统自动生成成果。
4. 设计来源仍是明确标记的本地模型桩（`local-model-stub`）；真实 AI 设计能力、真实用户设计评价、
   专业签核均未完成。本批是**文字理解层**的工程修复。
5. 语义理解仍然是受限的确定性解析，不是通用语言理解：只覆盖净宽 / 旋转 / 色温 / 面积四类可计算规则，
   以及"保留/不动/其余"这类保留表达。**其余说法一律 unknown+pending**，这是刻意的：宁可说没懂，
   也不用默认值冒充理解。复杂表达（一句多值、分别/各自）目前只能报未解析，需要用户拆句。
6. 净宽实测口径仍是"沿动线到最近障碍物距离 ×2"，不覆盖门洞/墙体/家具遮挡，`coverage` 里明写；
   因此 `净宽不超过 2400mm` 这类上限在本项目几何下会一直 fail —— 这是口径限制，不是程序反转。
7. `succeeded` 只表示流程跑完。`AD01—AD08` 未改判；`Q10` 仍 `not_run`；用户设计阶段确认未发生。

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

- **未做 W1—W4**：W0 是否放行由架构师复核决定，本包不自行宣布；不开始统一模型适配。
- 未扩 A2、未提高自动返工上限（仍 `MAX_AUTO_REWORK=2`）、未拆新 run 绕过上限。
- 未改契约 schema、未改几何净宽口径、未改前端交互、未改 AD 判定文档。
- 文字解析仍**只支持四类可计算规则**；模型辅助解析（需要对象/字段/范围/来源核验）留到 W1，
  本批明确不做，也没有用桩冒充真实语义理解。
- 一句话若同时包含多个值且用"分别/各自"表达，只能报未解析；建议用户一条一句。
- 矛盾检测只覆盖**同一目标（规则+字段+对象集）**上的 min/exact/max 不可兼容；跨字段的
  设计取舍（例如"更宽"与"更多展位"）仍由用户判断。

## 9. 分工边界

| 主体 | 本批 | 不可替代的边界 |
| --- | --- | --- |
| 执行 AI（本包） | 复现、修复、函数级/HTTP/浏览器正负例、回归、证据与状态更新 | 未宣布设计成立、未宣布 W0 放行、未改 AD 分母、未把桩结果说成真实设计 |
| 架构师 | 读实际 diff、独立复跑三套脚本、核对前后证据与字节 | 不代替用户审美与专业签核 |
| 用户 | 设计阶段确认、AD01—AD08 | 工程 PASS 不代签用户确认 |

## 10. 完整文件路径（均在 `D:\Github\RKD AI\` 下）

复核包：`deliverables-for-review\roadmap\W0-文字反馈收口\`
- `review-packet.md`（本文件）、`manifest.json`、`code-diff.md`、`changes.patch`、
  `positive-negative-cases.md`、`commit-reference.md`
- `before\text-cases.json`、`before\http\checks.json`（整改前，临时工作树 `5571e4e`）
- `after\text-cases.json`、`after\http\checks.json`
- `after\regression-w0b-repro.json`、`after\regression-w0b-http\checks.json`、
  `after\regression-w0\checks.json`、`after\regression-arc-first-batch.json`、`after\q-checks.json`
- `browser\verification.json`、`browser\browser-observations.json`、`browser\text-f3-desktop.png`、`browser\text-f3-mobile.png`
- `runtime\full-unittest.log`、`runtime\frontend-tsc.log`

运行证据：`var\evidence\roadmap\W0-文字反馈收口\`（`var/` 被 Git 忽略，不进仓库；整改前代码树在该目录下 `before-code/`，为临时 worktree，复核后可删）

源码改动（2 个生产文件 + 2 个测试脚本小修 + 4 个新增验收脚本）：
- `mvp\rkd_mvp\studio\revision_task.py`（主改：共用子句解析、对象绑定、比较符、未解析待办、矛盾检测）
- `mvp\rkd_mvp\studio\orchestrator.py`（矛盾 → `conflict`，不开模型、不用返工硬凑）
- `scripts\verify_w0.py`、`scripts\verify_w0b.py`（仅新增可选 `--out/--runtime`）
- `scripts\text_feedback_cases.py`、`scripts\verify_text_http.py`、
  `scripts\verify_text_browser.py`、`scripts\verify_text_browser.cjs`（新增）

唯一状态表：`PROJECT_STATUS.md`（本批已更新，未改 AD 结论）。
