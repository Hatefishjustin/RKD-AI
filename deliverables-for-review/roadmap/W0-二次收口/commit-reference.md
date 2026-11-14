# W0 二次收口 · 提交与时间对照

本文件是**事后补记**（复核包正文与证据在提交前已写定）。用途只有一个：
让复核者能用一条命令把"证据是什么时候采的、对着哪份代码"对上。

## 1. 代码基线

| 角色 | 提交 | 时间（+08:00） | 说明 |
| --- | --- | --- | --- |
| 比较基线（base） | `0524d3d87525eb1e05001d10574148e8b22f10bd` | 2026-11-14 12:4x | 上一批最后一次文档提交；本批所有证据的 `code_head` 都是它（证据在提交前采） |
| 上一批业务实现 | `4ef7c724d90bf2e0d9263a26368bde81fb628fae` | 2026-11-14 11:40 | 首次 W0 收口（R1/R2/R3），架构师复核的对象 |
| **本批业务实现** | **`27b389dcd23068d08657103d8f9be56a8abc8a44`** | **2026-11-14 13:27:53** | F01—F05 整改 + 4 个验收脚本 + 本复核包 |

复核命令（固定用 base，不用 HEAD）：

```
git diff 0524d3d -- mvp web scripts
```

等价补丁：本目录 `changes.patch`（197,602 字节，sha256 见 `manifest.json`）。

## 2. 证据时间轴（全部为实际执行时刻）

| 时刻（+08:00） | 事件 | 证据文件 |
| --- | --- | --- |
| 12:54:07 | 整改前复现：17/17 `defect_reproduced` | `before/repro.json` |
| 13:17 | 真实 HTTP 15/15 `observed_pass` | `after/checks.json` |
| 13:23 | 全量单测 262 OK；`tsc` / `npm run build` EXIT=0 | `runtime/full-unittest.log`、`runtime/frontend-*.log` |
| 13:24:16 | 真实 Edge 浏览器 `passed=true` | `browser/verification.json` |
| 13:24:45 | 整改后复现：17/17 `fixed_signature` | `after/repro.json` |
| 13:25 | 首批 Q01—Q12 回归 11 pass / 0 fail / 1 not_run | `after/arc-first-batch-regression-checks.json` |
| 13:27:53 | 本批代码与复核包提交 `27b389d` | 本文件 |

> 证据全部在提交**之前**采集，因此 `checks.json` / `repro.json` 里的 `code_head` 是 `0524d3d`，
> 与本批提交号不同。这不是矛盾：`code_head` 记录的是采证时的 HEAD，改动当时在工作区。
> `manifest.json` 的 `head_when_evidence_taken` 与 `batch_commit` 分开记这两件事。

## 3. 唯一一次证据覆盖与恢复

`scripts/verify_w0.py` 的输出路径写死在 `var/evidence/roadmap/W0-收口/after/checks.json`，没有 `--out`。
本次重跑把上一批那份文件覆盖了。处理：

1. 立即把重跑结果另存 `var/evidence/roadmap/W0-二次收口/runtime/verify_w0-rerun-checks.json`
   （sha256 前 16 位 `360d3ba01bd29b3e`）。
2. 用上一批交付包内副本 `deliverables-for-review/roadmap/W0-收口/after/checks.json` 把 `var/` 下文件
   恢复为原件（sha256 前 16 位 `cb87518bb3bb0652`，与包内一致）。
3. 复核包里如实写这件事（`review-packet.md` §5），没有把时间倒填、没有删证据。
