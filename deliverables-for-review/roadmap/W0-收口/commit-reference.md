# W0 复核包 · 提交号与差异定位

- 源码基线（base）：`957cf775e1d835cf25bbdf196de4e7f3f51280fa`（`957cf77`）
- 本批**主体提交**：`4ef7c724d90bf2e0d9263a26368bde81fb628fae`（`4ef7c72`）
  `W0 收口：R1 反馈旧基线续改、R2 确定性目标复核、R3 证据时间与契约映射勘误`
  （35 files changed；包含全部业务代码、验证脚本、复核包主体文档、证据副本与浏览器截图）
- 本批**补录提交**：`666f7d0cabef17464641786353fc2a4f8138e0a4`（`666f7d0`，
  2026-11-14T12:35:53+08:00）`docs: W0 复核包补提交号、标准补丁与文件清单`
  —— 仅追加本文件、`changes.patch`、`manifest.json`，并把 `4ef7c72` 写进
  `review-packet.md` / `code-diff.md` 的表头；**不含任何业务代码改动**。
- **复核包文档提交序列**（均不含业务代码改动）：`666f7d0`（清单/补丁）→ `622cca6`（定稿）→
  后续纯文档补录以 `git rev-parse HEAD` 取实际值。**不把易变的文档 HEAD 写成权威基线**：
  `manifest.json` 只记录稳定的 `code_head` = `4ef7c724d90bf2e0d9263a26368bde81fb628fae`。
  复核代码差异固定用 `git diff 957cf77..4ef7c72`。

复核差异命令：

```bash
git diff 957cf77..HEAD -- mvp/rkd_mvp/studio web/src scripts
git show --stat 4ef7c72
# 在 957cf77 的干净检出上校验补丁：
git apply --check deliverables-for-review/roadmap/W0-收口/changes.patch
# 在当前（已应用的）HEAD 上校验补丁一致性：
git apply --reverse --check deliverables-for-review/roadmap/W0-收口/changes.patch
```

> 在当前 HEAD 上直接 `git apply --check` 会报 `already exists` / `does not apply`，
> 因为补丁已经应用过了；这不是补丁损坏。本批已实测
> `git apply --reverse --check` **EXIT=0**，证明补丁与 `957cf77..4ef7c72` 的真实差异一致。

`changes.patch` 是从 `957cf77..4ef7c72` 导出的**标准 git 补丁**，范围是业务代码、
验证脚本、状态表、路线文件与复核包文本（`*.md` + `checks.json`）。
证据 JSON 副本、日志与 PNG 截图不进补丁（二进制与非源码），其路径与 SHA-256 逐项列在
`manifest.json`；完整差异始终以 `git diff 957cf77..HEAD` 为准。

提交与推送按项目长期约定执行（`master` → `git@github.com:Hatefishjustin/RKD-AI.git`），
未 reset / checkout，未清理用户既有改动或原件；`var/` 运行证据仍被忽略、不进版本库。
