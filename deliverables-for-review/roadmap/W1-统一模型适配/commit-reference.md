# W1 统一模型适配 · 提交与时间对照

本文件为**事后补记**（复核包正文与证据在提交前已写定）。用途：让复核者用一条命令对上
"证据什么时候采的、对着哪份代码"。

## 1. 代码基线

| 角色 | 提交 | 时间（+08:00） | 说明 |
| --- | --- | --- | --- |
| W0 放行审查 HEAD / 本批比较基线 | `cb84581`（`db9121e` 为更早的 W0 实现基线） | 2026-11-14 18:5x | W0 文字反馈保守判定复核包补记；架构师 W0 放行时审查的 HEAD |
| W0 业务实现 | `3688cd4` | 2026-11-14 18:48 | W0 保守判定 |
| **W1 业务实现** | **`46e9c1bbd0251f7bf8a5de062daff6147da9f88a`** | **2026-11-14 20:11:32** | 适配器 + 契约可选 spatial 段 + 服务/API/页面 + 本复核包 |

复核命令（固定用 base，不用易变的 HEAD）：

```
git diff cb84581 -- mvp contracts web scripts
```

等价补丁：本目录 `changes.patch`（含新增文件，字节数与 sha256 见 `manifest.json`）。
新增文件通过 `git add -N` 纳入 diff，因此补丁里能看到 `ai_design_studio_adapter.py`
与三个 `verify_w1_*` 脚本的完整内容。

## 2. 证据时间轴（实际执行时刻，未倒填）

| 时刻 | 事件 | 证据 |
| --- | --- | --- |
| 19:35 | 读 W0-final-architect 放行文件、PROJECT_STATUS、docs/13、21、26、W0 三契约勘误 | 本包 `contract-mapping.md` |
| 19:40 | PROJECT_STATUS 记录 W0 受限工程放行 + W1 批准范围 | `PROJECT_STATUS.md` 首条 |
| 19:50 | 契约可选 `spatial` 段 + 适配器 + 精确多边形校验/SVG | `changes.patch` |
| 19:55 | 服务单事务导入、4 个 API、页面导入与字段对账；`tsc`/`build` EXIT=0 | `runtime/frontend-*.log` |
| 19:58:44Z（= 19:58 +08:00） | 真实 Edge 浏览器 `passed=true` | `browser/verification.json` |
| 20:00:48+08:00 | 真实 HTTP **22/22 observed_pass** | `checks.json` |
| 20:03 | 受影响 5 模块 55 OK、全量 262 OK | `runtime/focused-unittest.log`、`runtime/full-unittest.log` |
| 20:05 | 复核包编制完成 | 本文件 |

> 证据在提交前采集，故 JSON 里的 `code_head` 是 `cb84581`；`manifest.json` 用
> `head_when_evidence_taken` 与 `batch_commit` 分开记这两件事。

## 3. 本批没有覆盖任何历史证据

- 新增目录 `var/evidence/roadmap/W1-统一模型适配/`，与 `W0-收口/`、`W0-二次收口/`
  `W0-文字反馈收口/`、`W0-文字反馈保守判定/`、`W0b-architect-review/`、
  `TEXT-architect-review/`、`W0-final-architect/` 完全分开。
- 没有新增 SQLite/PG 迁移、表或列；`postgres_import.py` 白名单与快照版本范围未改，
  旧格式与历史下载由 W1-19 验证。
- `source/` 与 `fixtures/` 原件未改动；不新增付费调用、不外发资料。
