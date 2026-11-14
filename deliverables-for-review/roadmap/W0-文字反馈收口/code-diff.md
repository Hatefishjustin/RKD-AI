# W0 文字反馈收口 · 代码差异说明

比较基线：`5571e4e`（`docs: W0 二次收口复核包补提交号与证据时间轴`）。
复核命令：`git diff 5571e4e -- mvp scripts`；完整补丁：`changes.patch`。

总量：生产代码 2 个文件 `+502 / −58`；测试脚本 2 个文件小修 `+32 / −8`；新增验收脚本 4 个共 1083 行。

## 1. `mvp/rkd_mvp/studio/revision_task.py`（主改）

旧实现的问题不是"某个函数写错"，而是**从文字到结构化目标这段路根本不存在**：
`derive_text_objectives` 用 4 条正则在全句里 `search` 一次，对象范围一律取规则自带的 group，
比较符一律取规则默认值，未匹配的部分只有在"整条留言一个目标都没有"时才补一条 aesthetic。

新增/重写的内容：

| 位置 | 内容 |
| --- | --- |
| `_CMP_MAX/_CMP_MIN/_CMP_EXACT` | 中文比较表达词表：`不超过/不大于/最多/以内/上限/≤/＜/<=/<` → max；`至少/不少于/不小于/不低于/最少/起码/以上/下限/≥/＞/>=/>` → min；`等于/恰好/正好/就是/精确到/=/＝` → exact |
| `_comparator_from_clause` | 有明确比较词就按词，没有才回落到 `_DEFAULT_COMPARATOR`；返回的 comparator 会随目标落库，可回查 |
| `_clause_binding` | 一个子句里点名的对象：真实 id（词边界匹配）、对象 `name`（≥2 字）、以及**长得像 id 但基线里没有**的 token（单独记 `unknown_ids`） |
| `text_named_objects` | 整条留言点名的对象集合，供"补集绑定"和"是否该用整组"判断 |
| `_measurable_binding` | 绑定优先级：caller 显式 ids（评审意见）→ 句内 id/name → 对象不存在 → 上一子句唯一对象 → 同组被点名则 unresolved → 才用规则自带 group。**"点名了对象却被扩大成整组"从这条链上被删掉了** |
| `_numeric_values` / "分别/各自" | 去掉对象 id 后再数数值；`分别/各自` + 多个数值 → `multiple_values_in_clause`（不配对、不取第一个）；一句里除目标值外还有数值 → `extra_values_not_parsed` 单列 |
| `parse_text_requirements` | 新的共用入口：按子句切分，逐句产出 `measurable / preserve / pending`，并记录 `source_text`（原句）、`binding_status`、`binding_match`、`object_source`、`computable` |
| `_pending_object` | 未解析/审美统一构造：`kind=aesthetic|unparsed`、`rule_id=USER-JUDGEMENT|TEXT-UNPARSED`、`unparsed_reason`（aesthetic / no_deterministic_rule / multiple_values_in_clause / extra_values_not_parsed）、`computable=False` → 复核时必然 `unknown` + `user_confirmed=pending` |
| `derive_text_objectives` | 保留原签名（评审意见等调用方不变），内部改为"只取 measurable"，并新增可选 `plan=` 用于对象识别 |
| `resolve_preserve_binding` | 新增 `named` 与补集：`其他/其余/其它` + 组名词（家具/分区/动线/灯…）→ 绑定到"本消息已点名对象之外的同组对象"，`binding_match=complement_of_named_objects`，并记录 `excluded`；没有点名对象时明确 `complement_without_named_objects`，**不猜** |
| `resolve_preserve_bindings` | `named` 缺省时从文本自算，调用方无需改签名 |
| `derive_objectives` | 每条留言都跑新解析：measurable（与 structured 去重）+ structured locks + preserve + **pending（始终追加，不再只在"空"时补）**；`text_heuristic` 的 `source_text`/`unparsed_reason` 一并保留 |
| `derive_objectives` 的评审意见分支 | 只把 `suggest` 当要求；`suggest` 里解析不出目标时才退回 `evidence` —— 修 Q08 回归时发现 `evidence` 里的"声明净宽 2000mm"会被当成第二个目标 |
| `_compat` / `text_conflicts` | 同一目标（rule+field+对象集）上的 min/exact/max 两两比较：不同精确值、min 高于 max、exact 越界 → `contradictory_text_targets`，带双方出处与 `decision_needed`；`min/min`、`max/max` 不算矛盾（取更严的那条） |
| `recheck_objectives` 条目 | 增加 `source_text` / `unparsed_reason` 透出，页面与证据能显示"哪句话没被解析" |

## 2. `mvp/rkd_mvp/studio/orchestrator.py`（+32）

- 新增 `ContradictoryFeedback(RuntimeError)`，携带 `conflicts`。
- `_revise_from_baseline`：派生 objectives 后立即 `text_conflicts(...)`；有矛盾直接抛异常，
  **在任何模型调用之前**停下，不消耗 token，不进入返工循环。
- `work()` 新增 `except ContradictoryFeedback`：run 记 `status="conflict"`，写 `gate` 消息，
  逐条列出"目标 / 两条要求的比较符与数值 / 各自来自哪条留言"，并明确"请以哪条为准或给替代值"；
  `evidence.type = "text_conflict"`，含完整 `conflicts` 结构。旧版与两条留言都保留。

没有改的：任务选择（F01）、字段锁（F04）、快照（F05）、自动返工计数、`_resolved_text_locks`
的调用方式（它现在自动获得补集绑定结果）。

## 3. 测试脚本小修（不是业务改动）

| 文件 | 改动 | 原因 |
| --- | --- | --- |
| `scripts/verify_w0.py` | 新增可选 `--out/--runtime`（默认值不变） | 上批出现过重跑覆盖历史证据的事故（已披露）；本批不再重演 |
| `scripts/verify_w0b.py` | 同上 | 同上 |

这两处只改输出路径解析，断言与阈值一字未动。

## 4. 新增验收脚本（全部 0 外部调用）

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `scripts/text_feedback_cases.py` | 350 | 14 个函数级用例，`--phase before|after` 同一脚本可跑两个代码树；判定签名 defect/fixed/not_observable/crashed |
| `scripts/verify_text_http.py` | 395 | 12 项真实 HTTP，全部走 `/messages` 正常入口（只发 text + 基线），不注入 objectives/locks |
| `scripts/verify_text_browser.py` | 182 | 拉起隔离主工作台 + 隔离 Studio + Edge；驱动真实输入与点击 |
| `scripts/verify_text_browser.cjs` | 156 | Playwright 断言与截图；从产物 `diagnostics.integrity` 读取服务端解析出的目标 |

## 5. 明确没有改的地方

- 契约 schema（`contracts/`）未动；`geometry.py` 净宽口径未动（只在 `coverage` 里继续声明其有限性）。
- 前端 `StudioView.tsx` / `studio.css` 未动：页面本来就只提交 `text` 与选定基线，
  问题在服务端解析，改前端只会掩盖问题。
- `MAX_AUTO_REWORK` 未动；AD 判定文档未动；`docs/26` 路线未动。
- 没删除任何历史证据；本批证据全部写入新目录。
