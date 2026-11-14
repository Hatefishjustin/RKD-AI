# W0 文字反馈收口 · 正负例与预期-实际对照

三类证据分开写，都是**实际执行**结果：
(A) 函数级 14 例（同一脚本跑整改前/后两个代码树）、(B) 真实 HTTP 12 项、(C) 真实浏览器 1 条用户路径。

- 整改前代码：临时 `git worktree` 检出 `5571e4e`（整改前最后一个提交），不改工作区；
- 整改后代码：本批工作区（提交号见 `commit-reference.md`）；
- 全部 0 模型调用 / 0 外部请求 / 0 密钥 / 0 费用。

判定签名：`defect_reproduced`（旧实现确实错）/ `fixed_signature`（新实现行为正确）/
`not_observable`（该版本没有这个入口）/ `crashed`（调用抛异常）。

## A. 函数级 14 例（整改前 12 缺陷 / 1 已正确 / 1 无法观测 → 整改后 14 全对）

| 用例 | 输入（老板原话） | 整改前实际 | 整改后实际 |
| --- | --- | --- | --- |
| T01-a | 把 F3 旋转到 -30 度，其他家具不动 | `object_ids=[]`、`scope=[furniture]`、复核对 `["F1","F2","F3"]` 全组 → 只改 F3 被判 **fail**；"其他家具不动"= unresolved | `object_ids=["F3"]`、复核对 `["F3"]` → **pass**；"其他家具不动"绑定补集 `["F1","F2"]` |
| T01-b | 同上，但候选顺手改了 F1 | 保留对象集合为空，`lock_conflicts` **0 条**（拦不住） | 锁 `["F1","F2"]`，F1 改动 → `whole_object_changed` 冲突 |
| T02 | 把 F1 和 F3 都转到 30 度（只改 F3） | `object_ids=[]`，目标退化成整组，状态 `unknown` | 目标 `["F1","F3"]`，量词 all，**fail** |
| T03 | 把家具都转到 30 度 | 无对象信息（`scope=[]`），整组语义丢失 | `scope=["furniture"]`、`object_ids=[]`、all —— 用户明说整组才整组 |
| T04 | 把 F9 旋转到 30 度 | `scope=[furniture]`（**扩大成本组**），missing 为空 | 目标 `["F9"]`、`missing_object_ids=["F9"]`、**fail** |
| T05 | 保留洽谈桌不动（两个对象同名） | 已能报 `ambiguous` + 2 候选（旧实现本来就对） | 仍然 `ambiguous` + 2 候选（回归护栏） |
| T06 | 主动线净宽不超过 2400mm | `comparator=**min**`（"不超过"被吃掉） | `comparator=max`，并带 `source_text` |
| T07 | 净宽至少 2100mm / 旋转到恰好 30 度 | `at least`→min 碰巧对，但 `恰好` 完全没解析出目标 | `min` / `exact` 分别正确 |
| T08 | L1 色温不超过 4000K（3500K） / 不低于 4000K（3500K） | 两条都是 `exact` → **都 fail**（上限正例被误杀） | 上限 `max`→**pass**，下限 `min`→**fail**，方向相反 |
| T09 | F1 和 F3 分别转到 30 和 -30 度 | 无目标，只落一条兜底 aesthetic（`FB1-A`） | 无 measurable；`multiple_values_in_clause` 待确认，不替用户配对 |
| T10 | 净宽至少 2100mm，同时整体更有设计感 | 只有 measurable（**审美消失**） | measurable + aesthetic；审美 `unknown` + `pending` |
| T11 | 净宽扩大到 2100mm，保留东洽谈区不动，整体要更有呼吸感 | `measurable + preserve`，**审美消失** | 三类并存：`aesthetic / measurable / preserve`，审美 pending |
| T12 | 同基线"至少 2400" + "不超过 2100" | 没有矛盾判定入口（`not_observable`→按缺陷记） | `text_conflicts` 命中：`min 2400` 与 `max 2100` 不可同时成立 |
| T13 | 同基线"至少 2100" + "至少 2400" | 无入口（`not_observable`） | 0 矛盾（同向不误报） |

> 整改前 T05 就已经正确：本批没有把它算成成果，它在这里的作用是防止新解析把已经对的行为改坏。

## B. 真实 HTTP 12 项（整改前 1 pass / 11 fail → 整改后 12/12）

命令（两版同一条命令，只换 PYTHONPATH 指向的代码树）：

```
python scripts/verify_text_http.py --out <dir> --runtime <dir>
```

| 编号 | 输入 | 整改前 | 整改后 |
| --- | --- | --- | --- |
| TEXT-01 | 把 F3 旋转到 -30 度，其他家具不动 | `incomplete`；目标 `["F1","F2","F3"]`；fail | `succeeded`；`object_diff=["furniture:F3"]`；目标 `["F3"]`；pass |
| TEXT-02 | 同上 + 误改 F1 | `incomplete`（**顺带**被过宽目标拦下，不是保留要求起作用） | `incomplete`；`LOCK-PRESERVE` 命中 F1 |
| TEXT-03 | 把 F1 和 F3 都转到 30 度（只改 F3） | `incomplete`，但目标退化成整组 | `incomplete`；目标 `["F1","F3"]`；failing 含 F1 |
| TEXT-04 | 把家具都转到 30 度（只改 F3） | 无整组目标（解析不到） → 判 fail 的理由不对 | 目标 `["F1","F2","F3"]`（用户明说整组）→ fail |
| TEXT-05 | 把 F9 旋转到 30 度 | 退化成整类家具 | 目标 `["F9"]`、`missing=["F9"]`、fail |
| TEXT-06 | 主动线净宽不超过 2400mm（改 2600） | `comparator=min` | `comparator=max`；fail（实测超上限） |
| TEXT-07 | L1 色温不超过 4000K（改 3500） | `exact` → fail（上限正例被误杀） | `max` → **pass** |
| TEXT-08 | L1 色温不低于 4000K（改 3600） | `exact` → fail | `min` → fail（方向与上限相反） |
| TEXT-09 | 净宽至少 2100mm，保留入口，整体更有设计感 | 无 aesthetic，`pending=0` | 三类并存，审美 `unknown+pending`，数值 pass |
| TEXT-10 | F1 和 F3 分别转到 30 和 -30 度 | 无未解析项，等同于"没听懂但也不说" | `multiple_values_in_clause` 待确认；无 measurable 被冒充通过 |
| TEXT-11 | 至少 2400 + 不超过 2100（同基线） | 无冲突机制，进模型 → 返工 | `status=conflict`、0 产物、闸口列出两条出处 |
| TEXT-12 | 把 F1 旋转到 45 度（回归护栏） | `incomplete`（旧解析把单对象也扩大成整组） | `succeeded`；`object_diff=["furniture:F1"]`；`exact` |

> TEXT-02 整改前的 pass 是**巧合**：旧实现把目标扩大到整组，F3 转了、F1/F2 没转，于是因为
> "部分达标"失败，看起来"拦住了"。它不是保留要求在起作用——所以本批用 TEXT-02 的整改后证据
> 明确要求 `LOCK-PRESERVE` 命中 F1，而不是只要 `incomplete` 就算过。

## C. 真实浏览器（Edge headless，隔离环境）

命令：`python scripts/verify_text_browser.py --out var/evidence/roadmap/W0-文字反馈收口/after/browser`
结果：`passed=true`、`node_returncode=0`、12.1 s、`page_errors=[]`。

| 观察点 | 预期 | 实际 |
| --- | --- | --- |
| 入口 | 选「候选 A v1」+ 只输入文字 | `task_resolution.kind=revise`，目标 = 选中旧版 |
| 本轮 | 旧基线续改，不是重生成 A/B | `task_kind=revise`、`status=succeeded` |
| 版本 | 新修订父版本 = 选中旧版 | `parent_revision_uid=revuid_401d86c00c` = 选中 uid |
| 目标（服务端解析） | 只认 F3；"其他家具"绑定 F1/F2 | measurable `STD-001/-30/["F3"]/pass`；preserve `LOCK-PRESERVE/["F1","F2"]/pass` |
| 改动 | 只改 F3 | `object_diff=["furniture:F3"]` |
| 页面 | 无红色告警 | `alert_count=0` |
| 窄屏 | 390px 不横向溢出 | `scrollWidth=390` |
| 截图 | — | `text-f3-desktop.png`、`text-f3-mobile.png` |

## D. 本批没有覆盖的负例（如实列出）

- **真实模型（非桩）在文字解析歧义下的行为**：未测（无付费授权）。本批只证明服务端的解析与拦截。
- **多语言/口语化表达**（"别太挤""往北挪一点"）：一律 `unknown+pending`，没有语义推断，也未做召回率评测。
- **并发两条互相矛盾留言先后到达**：只在合并后做矛盾检测，没有做竞态压测。
- **模型辅助解析提案的核验**：本批不做（架构师列为可选，W1 再议）。
- **W1—W4**：未开始。`Q10` 仍 `not_run`。
