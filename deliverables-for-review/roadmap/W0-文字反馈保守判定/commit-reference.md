# W0 文字反馈保守判定 · 提交与时间对照

本文件为**事后补记**（复核包正文与证据在提交前已写定）。用途：让复核者用一条命令对上
"证据什么时候采的、对着哪份代码"。

## 1. 代码基线

| 角色 | 提交 | 时间（+08:00） | 说明 |
| --- | --- | --- | --- |
| 比较基线（base） | `db9121e0abecb6d5cbe3941ec73aab2fe578e6b1` | 2026-11-14 18:0x | 文字反馈收口复核包文档补记；架构师审查的 HEAD |
| 上一批业务实现 | `48afd01af41286c44497bf1b0d03370102969e5f` | 2026-11-14 17:58 | TEXT-01 文字反馈解析 |
| **本批业务实现** | **`3688cd41c597703560bdcd626600e9325d88d258`** | **2026-11-14 18:48:48** | 保守判定 + 4 个验收脚本 + 本复核包 |

复核命令（固定用 base）：

```
git diff db9121e -- mvp scripts
```

等价补丁：本目录 `changes.patch`（字节数与 sha256 见 `manifest.json`）。

**整改前证据的来源**：`git worktree add var/evidence/roadmap/W0-文字反馈保守判定/before-code db9121e`，
用同一份脚本在该代码树上执行，输出到 `before/`。该 worktree 在 `var/` 下（Git 忽略），
复核结束后可删除；它不是分支，也不影响工作区。

## 2. 证据时间轴（全部为实际执行时刻）

| 时刻（+08:00） | 事件 | 证据 |
| --- | --- | --- |
| 18:32:36 | 整改后 10 个函数级边界：10/10 | `after/boundary-cases.json` |
| 18:33:13 | 整改前代码树：7 defect / 3 fixed | `before/boundary-cases.json` |
| 18:34:15 | 回归原 14 例 14/14、原 12 项 12/12 | `after/regression-14.json`、`after/regression-12/checks.json` |
| 18:36:05 | 整改后 HTTP 10/10 | `after/conservative-http/checks.json` |
| 18:36:22 | 整改前 HTTP 5 pass / 5 fail | `before/conservative-http/checks.json` |
| 18:37 | 真实 Edge 浏览器 passed=true | `browser/verification.json` |
| 18:40 | 回归 17/17、15/15、7/7、Q 11 pass/0 fail/1 not_run、上一批浏览器 passed=true | `after/regression-*` |
| 18:45 | 全量单测 262 OK（454.0 s）、tsc EXIT=0 | `runtime/full-unittest.log`、`runtime/frontend-tsc.log` |
| 18:50 | 复核包编制完成 | 本文件 |

> **执行顺序是先跑整改后、再跑整改前**，两个 JSON 的 `executed_at` 如实反映了这一顺序；
> 没有把时间倒填、没有改历史结论。
> 证据在提交前采集，故 JSON 里的 `git_head` 是 `db9121e`；`manifest.json` 用
> `head_when_evidence_taken` 与 `batch_commit` 分开记这两件事。

## 3. 本批没有覆盖任何历史证据

- 新增目录 `var/evidence/roadmap/W0-文字反馈保守判定/`，与 `W0-收口/`、`W0-二次收口/`、
  `W0-文字反馈收口/`、`TEXT-architect-review/` 完全分开。
- 所有本批脚本都带 `--out/--runtime`，回归脚本沿用上批加的路径参数；默认值未改、断言未动。
