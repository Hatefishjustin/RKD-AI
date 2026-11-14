# W0 文字反馈保守判定 · 代码差异说明

比较基线：`db9121e`（`docs: W0 文字反馈收口复核包补提交号与时间轴`）。
复核命令：`git diff db9121e -- mvp scripts`；完整补丁：`changes.patch`。

总量：生产代码 2 个文件 `+315 / −64`；新增验收脚本 4 个共 975 行。
没有改前端、契约、几何、AD 文档或 `docs/26`。

## 1. `mvp/rkd_mvp/studio/revision_task.py`（主改）

| 位置 | 内容 |
| --- | --- |
| `_SUPPORTED_CMP_PHRASES` / `_KEEP_PHRASES` / `_NON_NEGATION_RE` / `_NEGATION_RE` | 先把**已支持的比较表达**与**保留表达**整体剔除，再判 `不要/别/不得/不能/不可/不许/勿/禁止/避免/莫/休` 是否作用于整句。`不超过/不低于` 仍是比较符，`保留/不动/不要改` 仍是保留约束，只有"不要把…旋转到…"这类没有对应可计算规则的否定被判为未解析 |
| `_STRUCTURAL_WORDS` / `_STRUCTURAL_RE` / `_CJK_RE` | 结构性/主语词表，供"残余片段"判定使用；不是诉求词表，也不是同义词补丁 |
| `_clause_is_negated(clause)` | 返回整句是否为否定要求。命中时**不生成 measurable** |
| `_explained_spans(clause, hits, index)` | 收集本句被规则真正解释的字符区间：数值规则命中、对象 id 形 token、对象名、比较词、保留词；同时返回 `explained_text` 便于证据回查 |
| `_substantive_residual(clause, spans)` | 掩掉已解释区间、去掉结构性/主语词；**只要还有汉字就视为未解释的诉求**，返回残余文本。与标点无关、与具体词无关 |
| `_clause_binding` | 新增 `name_hits` 与 `ambiguous_names`：多个对象名命中，或显式 id 与"该 id 也叫这个名字"的名称混用，都标记为歧义；`unknown_ids` 继续单独保留 |
| `_measurable_binding` | 有缺失引用时**不再提前返回已找到的 ids**：`refs = 已有 + 缺失`，`binding_status=unresolved`、`missing_object_ids`、`all_object_references`，`verifiable=True` → 复核按对象缺失判 fail；歧义名称 → `ambiguous_object_names` + 候选、`verifiable=False`（不验证） |
| `parse_text_requirements` | 命中数值规则的子句：先判否定 → `negated_requirement` 待确认（不建目标）；否则建目标时写 `explained_text` / `all_object_references` / `source_text`；子句尾部若有 `_substantive_residual` 结果，追加 `unparsed_remainder_in_clause`（带 `residual_text`、`source_text`、原句对象引用）。`分别/各自`、多值、额外数值的既有逻辑保持不变 |
| `_pending_object` | 增加 `residual_text` 字段（缺省为整句），保证"未解析片段"和"完整原句"都能在证据里看到 |
| `recheck_objectives` 条目 | 透出 `residual_text` / `all_object_references` / `missing_object_ids`，页面与 HTTP 证据能显示未解析片段与缺失对象 |

## 2. `mvp/rkd_mvp/studio/orchestrator.py`（+39）

- 新增 `UnresolvedRequirement(RuntimeError)`，携带未解析项。
- `_revise_from_baseline`：派生 objectives 后，若存在 `unparsed_reason == "negated_requirement"`，
  在**任何模型调用之前**抛异常。理由：这类句子"看起来像数值目标但被否定"，程序没有
  "不等于"规则，若照常跑模型，可能交出与原句相反的修订。
- `work()` 新增 `except UnresolvedRequirement`：run 记 `status="conflict"`，闸口逐条列出原句、
  `unparsed_reason` 与 `unknown + pending`，明确"请改写成允许值或说明要保留什么"；
  `evidence.type = "unresolved_requirement"` 带 `run_id` 与完整条目。旧版本与留言都保留。

没有改：`ContradictoryFeedback`（矛盾要求）、任务选择、锁、快照、累计返工、几何复核。

## 3. 新增验收脚本（全部 0 外部调用）

| 文件 | 行数 | 作用 |
| --- | --- | --- |
| `scripts/boundary_cases.py` | 277 | 10 个函数级边界（B01—B10），`--phase before|after` 同一脚本可跑两个代码树 |
| `scripts/verify_conservative_http.py` | 346 | 10 项真实 HTTP（CONS-01—10），全部 `/messages` 正常文字入口，不注入 objectives/locks |
| `scripts/verify_conservative_browser.py` | 182 | 隔离主工作台 + 隔离 Studio + Edge；无逗号复合句的真实输入/点击 |
| `scripts/verify_conservative_browser.cjs` | 170 | Playwright 断言：数值 pass、残余 pending、页面"未验证/待你确认"可见、390px、截图 |

## 4. 明确没有改的地方

- 没有实现"不等于/不得改为"规则；否定要求只做保守拒绝。
- 没有把残余片段自动翻译成可计算目标，也没有为"设计感""收口"等词加专门规则。
- 没有改 `StudioView.tsx` / `studio.css`：页面本来就只提交文字与选定基线，问题在服务端解析。
- 没有改 `MAX_AUTO_REWORK`、契约 schema、几何净宽口径、AD 判定文档、`docs/26`。
- 没有删除任何历史证据；本批证据全部写入新目录。
