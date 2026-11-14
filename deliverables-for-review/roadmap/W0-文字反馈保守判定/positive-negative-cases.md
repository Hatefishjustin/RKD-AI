# W0 文字反馈保守判定 · 正负例与预期-实际对照

三类证据，全部实际执行：(A) 10 个函数级边界（同一脚本跑整改前/后两个代码树）、
(B) 10 项真实 HTTP、(C) 1 条真实浏览器用户路径。
整改前代码：`git worktree` @ `db9121e`；0 模型调用 / 0 外部请求 / 0 密钥 / 0 费用。

判定签名：`defect_reproduced` / `fixed_signature` / `crashed`。

## A. 函数级 10 例（整改前 7 缺陷 / 3 已正确 → 整改后 10 全对）

| 用例 | 输入 | 整改前实际 | 整改后实际 |
| --- | --- | --- | --- |
| B01 | 不要把 F3 旋转到 -30 度 | `computable=true`、`exact -30`、`ids=["F3"]`、**pending=[]** | 无 measurable；`negated_requirement` → `unknown+pending`，保留原句 |
| B02 | 净宽不超过 2400 / 色温不低于 4000 / 不要把净宽扩大到 2400 | 前两者正常，但否定句生成 `min 2400` 正向目标 | 前两者仍 `max`/`min`；否定句整项 pending |
| B03 | 把 F1 和 F9 旋转到 -30 度 | `ids=["F1"]`、`resolved`、复核 **pass**（F9 被吞） | `ids=["F1","F9"]`、`all_object_references=["F1","F9"]`、`unresolved`、复核 **fail**（`missing=["F9"]`） |
| B04 | 把 F9 旋转到 -30 度 | 已正确：目标 F9、fail | 保持（回归护栏） |
| B05 | 把 F1 和洽谈桌转到 30 度（F1/F2 同名） | `ids=["F1","F2"]`、`resolved`、`computable=true` | `ambiguous_object_names`、候选 `[F1,F2]`、`computable=false` |
| B06 | 把 F3 旋转到 -30 度并让整体更有设计感 | 只有数值目标，pending=[] | 数值目标 + `unparsed_remainder_in_clause`，`residual_text="更有设计感"`、`unknown+pending` |
| B07 | 把 F3 旋转到 -30 度并复核北侧收口 | pending=[] | 残余 `"复核北侧收口"` 留痕（证明不是"设计感"补丁） |
| B08 | 把 F3 旋转到 -30 度，整体更有设计感 | 已正确：aesthetic pending | 保持（回归护栏） |
| B09 | 把 F3 旋转到 -30 度，其他家具不动 | 已正确：measurable + preserve `[F1,F2]` | 保持，且否定守卫不误判（回归护栏） |
| B10 | 同 B06，看片段记账 | `explained_text=null`、`residual=[]` | `explained_text=["旋转到 -30 度"]`、`source_text`=整句、`residual_text="更有设计感"` |

> 整改前就正确的 B04 / B08 / B09 是回归护栏，不计为本批修复成果。

## B. 真实 HTTP 10 项（整改前 5 pass / 5 fail → 整改后 10/10）

命令（两版同一条命令，只换 PYTHONPATH 指向的代码树）：

```
python scripts/verify_conservative_http.py --out <dir> --runtime <dir>
```

| 编号 | 输入 | 整改前 | 整改后 |
| --- | --- | --- | --- |
| CONS-01 | 不要把 F3 旋转到 -30 度 | 模型按 `exact -30` 目标改 F3 → **reversal**，无 pending | `status=conflict`、0 产物、闸口含原句与 `unknown + pending` |
| CONS-02 | 主动线净宽不超过 2400mm | 已正确 `max` | 仍 `max`、fail；未被否定守卫误杀 |
| CONS-03 | L1 色温不低于 4000K | 已正确 `min` | 仍 `min`、fail；未被误杀 |
| CONS-04 | 不要把主动线净宽扩大到 2400mm | 生成 `min 2400` 正向目标 | `conflict`、0 产物 |
| CONS-05 | 把 F1 和 F9 旋转到 -30 度 | 只认 F1，复核 pass（漏 F9） | `target_objects=["F1","F9"]`、`missing=["F9"]`、fail、无有效修订 |
| CONS-06 | 把 F9 旋转到 30 度 | 已正确：fail | 保持 |
| CONS-07 | 把 F3 旋转到 -30 度并让整体更有设计感 | 只有 measurable，pending=[] | 数值 pass + 残余 `unknown+pending`，时间线写"还有 N 条未验证" |
| CONS-08 | 把 F3 旋转到 -30 度并复核北侧收口 | pending=[] | 残余"收口"留痕 |
| CONS-09 | 把 F3 旋转到 -30 度，整体更有设计感 | 已正确 | 保持 |
| CONS-10 | 把 F3 旋转到 -30 度，其他家具不动 | 已正确 | 保持，否定守卫不误判 |

**失败/未解析在证据中的可见位置**：
- CONS-01/04：`state.messages` 的 gate 消息，`evidence.type=unresolved_requirement`（原句 +
  `unparsed_reason` + 对象引用 + 待确认状态）。
- CONS-05：raw 产物 `diagnostics.integrity.objective_rechecks[0]` 的
  `missing_object_ids=["F9"]`、`all_object_references=["F1","F9"]`、`objective_rechecked="fail"`。
- CONS-07/08/09：成功修订产物的 `integrity.objective_rechecks` 含
  `unparsed_reason=unparsed_remainder_in_clause`、`residual_text`、`user_confirmed="pending"`；
  完成 note 明确"还有 N 条目标未验证/等用户确认"。

## C. 真实浏览器（Edge headless，隔离环境）

命令：`python scripts/verify_conservative_browser.py --out var/evidence/roadmap/W0-文字反馈保守判定/after/browser`
结果：`passed=true`、`node_returncode=0`、`page_errors=[]`。

| 观察点 | 预期 | 实际 |
| --- | --- | --- |
| 入口 | 选候选 A v1 + 只输入**无逗号复合句** | `task_resolution.kind=revise`，目标 = 选中旧版 |
| 本轮 | 旧基线续改 | `task_kind=revise`、`status=succeeded` |
| 版本 | 父版本 = 选中旧版 | `parent_revision_uid=revuid_3a4691176e` = 选中 uid |
| 目标 | 数值只认 F3 | `STD-001 / -30 / ["F3"] / pass` |
| 残余 | 尾部诉求不吞 | `aesthetic`、`unparsed_remainder_in_clause`、`residual_text="更有设计感"`、`unknown+pending` |
| 页面待确认 | 用户能看到 | `page_has_pending_note=true`，页面含「未验证/待你确认：1 项（FBFB1-U0）——程序没有把它们算成通过」 |
| 改动 | 只改 F3 | `object_diff=["furniture:F3"]` |
| 告警/窄屏 | 无 | `alert_count=0`、`scrollWidth=390` |
| 截图 | — | `conservative-desktop.png`、`conservative-mobile.png` |

## D. 本批没有覆盖的负例（如实列出）

- **真实模型（非桩）在否定/歧义输入下的行为**：未测（无付费授权）。本批只证明服务端不生成反转目标、
  不交出这种修订。
- **名称歧义组合的 HTTP/浏览器层**：只在函数级用改造过的夹具验证（B05）；隔离库对象名固定，
  未构造同名场景，未冒称 HTTP/浏览器实测。
- **"不等于/不得改为"规则**：未实现，整项 pending；架构师允许未知表达保持 unknown。
- **多进程/崩溃恢复、并发否定留言**：未做。
- **W1—W4**：未开始；`Q10` 仍 `not_run`。
