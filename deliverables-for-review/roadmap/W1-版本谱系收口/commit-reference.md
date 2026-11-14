# W1 版本谱系收口 · 提交与时间对照

本文件为**事后补记**（复核包正文与证据在提交前已写定）。

## 1. 代码基线

| 角色 | 提交 | 时间（+08:00） | 说明 |
| --- | --- | --- | --- |
| 比较基线（base） | `080f63e` | 2026-11-14 20:1x | W1 首版复核包文档补记；架构师 W1 复核时的 HEAD |
| W1 首版业务实现 | `46e9c1b` | 2026-11-14 20:11 | 适配器 + 可选 spatial + 服务/API/页面 |
| **本批业务实现** | **`b40b4fad7fe6d1a34702b5b49cd7928fc9c8a7de`** | **2026-11-14 21:20:48** | 源谱系身份/父 UID 映射/写内并发重检 + 13 项谱系验收 + 本复核包 |

复核命令（固定用 base）：

```
git diff 080f63e -- mvp contracts scripts web
```

等价补丁：本目录 `changes.patch`（新增 `scripts/verify_w1_lineage.py` 通过 `git add -N`
纳入 diff，字节与 sha256 见 `manifest.json`）。

## 2. 证据时间轴（实际执行，未倒填）

| 时刻 | 事件 | 证据 |
| --- | --- | --- |
| 20:20 | 读 `W1-architect-review/architect-review.md`，确认 22 项已独立通过、只修 R1/R2 | 本包 |
| 20:35 | 契约补根谱系/父链状态/设计来源；适配器加 `lineage()` / `design_origin()` | `changes.patch` |
| 20:50 | 服务改为源谱系身份 + 写内重检；原 22 项夹具改真实父 UID | `scripts/verify_w1_unified_model.py` |
| 21:11:59+08:00 | 谱系/并发 13/13 `observed_pass` | `lineage-checks.json` |
| 21:12:13+08:00 | 原 22 项回归 22/22 `observed_pass` | `checks.json` |
| 21:12:26Z（=21:12+08） | 真实 Edge 浏览器 `passed=true` | `browser/verification.json` |
| 21:19 | 定向 55 OK、全量 262 OK | `runtime/*.log` |
| 21:20 | 复核包编制完成 | 本文件 |

> 证据在提交前采集，故 JSON 里的 `code_head` 是 `080f63e`；`manifest.json` 用
> `head_when_evidence_taken` 与 `batch_commit` 分开记这两件事。

## 3. 没有覆盖历史证据

- 新增 `var/evidence/roadmap/W1-版本谱系收口/`，与 `W1-统一模型适配/`、`W1-architect-review/`、
  W0 各批完全分开。
- 复查时可先跑 `scripts/verify_w1_lineage.py`（13 项），再跑 `scripts/verify_w1_unified_model.py`
  （22 项回归）；两者都用独立的 runtime 目录，不触碰历史证据。
- 没有新增迁移/表/列；没有改 `postgres_import.py` 白名单；没有动用户原件与 `fixtures/`。
