# W0 文字反馈收口 · 提交与时间对照

本文件为**事后补记**（复核包正文与证据在提交前已写定）。用途：让复核者用一条命令对上
"证据什么时候采的、对着哪份代码"。

## 1. 代码基线

| 角色 | 提交 | 时间（+08:00） | 说明 |
| --- | --- | --- | --- |
| 比较基线（base） | `5571e4ec82753539793e0ae7ecb046bf1c336a73` | 2026-11-14 13:3x | 上一批复核包文档补记；架构师审查的 HEAD |
| 上一批业务实现 | `27b389dcd23068d08657103d8f9be56a8abc8a44` | 2026-11-14 13:27 | W0-F01—F05 五项整改 |
| **本批业务实现** | **`48afd01af41286c44497bf1b0d03370102969e5f`** | **2026-11-14 17:58:35** | TEXT-01 文字反馈解析 + 4 个验收脚本 + 本复核包 |

复核命令（固定用 base）：

```
git diff 5571e4e -- mvp scripts
```

等价补丁：本目录 `changes.patch`（字节数与 sha256 见 `manifest.json`）。

**整改前证据的来源**：`git worktree add var/evidence/roadmap/W0-文字反馈收口/before-code 5571e4e`，
用同一份脚本在该代码树上执行，输出到 `before/`。该 worktree 在 `var/` 下（GiT 忽略），
复核结束后可删除；它不是分支，也不影响工作区。

## 2. 证据时间轴（全部为实际执行时刻）

| 时刻（+08:00） | 事件 | 证据 |
| --- | --- | --- |
| 17:36 | 整改前函数级 14 例：12 defect / 1 fixed / 1 not_observable | `before/text-cases.json` |
| 17:44 | 整改前真实 HTTP 12 项：1 pass / 11 fail | `before/http/checks.json` |
| 17:50 | 整改后函数级 14 例：14/14 fixed_signature | `after/text-cases.json` |
| 17:52 | 整改后真实 HTTP 12 项：12/12 observed_pass | `after/http/checks.json` |
| 17:53 | 真实 Edge 浏览器 passed=true | `browser/verification.json` |
| 17:51 | 回归：17/17 复现签名、15/15 HTTP、7/7 W0 专项、Q 11 pass/0 fail/1 not_run | `after/regression-*` |
| 17:58 | 全量单测 262 OK（296.5 s） | `runtime/full-unittest.log` |
| 18:05 | 复核包编制完成 | 本文件 |

> 证据在提交前采集，故 `checks.json` / `text-cases.json` 里的 `git_head` 是 `5571e4e`；
> `manifest.json` 用 `head_when_evidence_taken` 与 `batch_commit` 分开记这两件事。

## 3. 本批没有覆盖任何历史证据

- 新增目录 `var/evidence/roadmap/W0-文字反馈收口/`，与 `W0-收口/`、`W0-二次收口/`、
  `W0b-architect-review/` 完全分开。
- 为避免重演上批的覆盖事故，`scripts/verify_w0.py`、`scripts/verify_w0b.py` 增加了可选
  `--out/--runtime`；**默认值保持原样，断言与阈值一字未改**。
- 唯一一次早期误写：`verify_w0b.py` 第一次重跑时 `--out` 传了文件名而非目录，生成了
  `after/http-original15.json/checks.json`；已重命名为 `after/regression-w0b-http-early/`
  并在最终证据中使用 `after/regression-w0b-http/checks.json`。没有删除任何结果。
