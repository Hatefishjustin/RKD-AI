# 本批复核包的提交定位

- 架构师审查 HEAD（本包差异基线）：`ffad892`
- 架构师列出的业务实现提交：`7425464`
- W2 二次收口复核包提交：`b877138` / `ffad892`
- **本批 W2-R4 代码与交付包提交：`84a7719`**
- 远程：`git@github.com:Hatefishjustin/RKD-AI.git`，分支 `master`

`changes.patch` 由 `git diff ffad892`（配合 `git add -N` 纳入新文件）生成，覆盖业务代码、
脚本、前端样式、状态表与架构师复核输入；补丁不含 `changes.patch`、`manifest.json`、
`index.html` 与本文自身，避免自引用。

`manifest.json` 的 `code_head_at_compile` 是组装复核包时的 HEAD（`ffad892`），
不是最终提交号；最终提交号以本文件为准。运行证据始终在
`var/evidence/roadmap/W2-R4-同源表达/`（本机保留，不进版本库）。

本文件单独提交，因此不计入 `manifest.json` 的文件清单与 SHA 对账。
