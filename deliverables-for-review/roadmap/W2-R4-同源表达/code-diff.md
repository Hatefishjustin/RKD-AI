# 提交差异

- 稳定基线：`ffad892`（架构师 `review-and-R4.md` 的审查 HEAD）；架构师列出的业务实现提交为 `7425464`。
- 本包 `changes.patch` 由 `git diff ffad892`（含 `git add -N` 的新文件）生成，覆盖业务代码、脚本、前端样式、状态表与架构师复核输入；补丁不包含 `changes.patch` / `manifest.json` / `index.html` 自身，避免自引用。
- 实际 HEAD 以 `git rev-parse HEAD` 为准；本包不写死易变的 HEAD。

## `git diff --stat ffad892`

```
PROJECT_STATUS.md                                  |   4 +
 .../W2-second-architect/independent-checks.json    | 377 +++++++++++
 .../roadmap/W2-second-architect/review-and-R4.md   |  51 ++
 mvp/rkd_mvp/ai_spatial_output_service.py           |  50 +-
 mvp/rkd_mvp/ai_spatial_outputs.py                  | 704 ++++++++++++++++++---
 mvp/rkd_mvp/spatial_presentation.py                | 362 +++++++++++
 scripts/build_w2_r4_review.py                      | 630 ++++++++++++++++++
 scripts/render_spatial_scene_r4.py                 | 496 +++++++++++++++
 scripts/verify_w2_r4.py                            | 607 ++++++++++++++++++
 scripts/verify_w2_r4_browser.cjs                   | 141 +++++
 scripts/verify_w2_r4_browser.py                    | 160 +++++
 scripts/verify_w2_r4_finish_conflict.py            | 371 +++++++++++
 scripts/w2_r4_fixture_presentation.py              | 271 ++++++++
 web/src/styles.css                                 |   9 +-
 14 files changed, 4143 insertions(+), 90 deletions(-)
```

## 本批新增文件（git 未跟踪，纳入补丁）

- `deliverables-for-review/roadmap/W2-R4-同源表达/asset-assumptions.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/asset-inventory.md`
- `deliverables-for-review/roadmap/W2-R4-同源表达/before-after/w2-graybox-layout-A.png`
- `deliverables-for-review/roadmap/W2-R4-同源表达/browser/browser-observations.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/browser/browser-stderr.log`
- `deliverables-for-review/roadmap/W2-R4-同源表达/browser/browser-stdout.log`
- `deliverables-for-review/roadmap/W2-R4-同源表达/browser/plan-preview-A.png`
- `deliverables-for-review/roadmap/W2-R4-同源表达/browser/plan-preview-B.png`
- `deliverables-for-review/roadmap/W2-R4-同源表达/browser/r4-outputs-desktop.png`
- `deliverables-for-review/roadmap/W2-R4-同源表达/browser/r4-outputs-mobile.png`
- `deliverables-for-review/roadmap/W2-R4-同源表达/browser/verification.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/changes.patch`
- `deliverables-for-review/roadmap/W2-R4-同源表达/checks.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/design-gaps.md`
- `deliverables-for-review/roadmap/W2-R4-同源表达/entry-fix/after.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/entry-fix/before.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/entry-fix/regression-15.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/geometry-material-reconciliation.md`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/changes/geometry-material-reconciliation.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/cost.html`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/finish-scope.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/manifest.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/model.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/package.zip`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/plan.svg`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/presentation.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/quantity.csv`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/quantity.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/render-meta.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/render.png`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/scene.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-A/source-note.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/cost.html`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/finish-scope.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/manifest.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/model.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/package.zip`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/plan.svg`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/presentation.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/quantity.csv`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/quantity.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/render-meta.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/render.png`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/scene.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/outputs/layout-B/source-note.json`
- `deliverables-for-review/roadmap/W2-R4-同源表达/positive-negative-cases.md`
- `deliverables-for-review/roadmap/W2-R4-同源表达/review-packet.md`
- `deliverables-for-review/roadmap/W2-R4-同源表达/runtime/full-unittest.log`

## 改动摘要（不按行数衡量工作价值）

| 文件 | 改动 |
| --- | --- |
| `mvp/rkd_mvp/ai_spatial_outputs.py` | finish_scope v3 冲突/裁切/多构造层口径；plan/scene/package 支持表达层；圆角轮廓；conflict 成本与 HTML |
| `mvp/rkd_mvp/ai_spatial_output_service.py` | settings.presentation 校验；按 presentation 选择真实资产渲染器；revision 记录表达层对象与材质 |
| `mvp/rkd_mvp/spatial_presentation.py` | 新增：表达层契约校验（人工假设、对象 ID、资产引用、洞口/机位/灯光） |
| `scripts/render_spatial_scene_r4.py` | 新增：CC0 PBR + glTF + 围合开口 + 窗光/灯槽 + 人眼机位 |
| `scripts/w2_r4_fixture_presentation.py` | 新增：A/B 人工测试假设样板数据（明确非 AI 设计） |
| `scripts/verify_w2_r4*.py/.cjs` | 新增：入口小修复现、完整验证、浏览器验收 |
| `scripts/build_w2_r4_review.py` | 新增：复核包组装 |
| `web/src/styles.css` | 修长对象 ID 撑破 390px 窄屏 grid 轨道 |
| `PROJECT_STATUS.md` | 追加架构复核受限结论与 W2-R4 结果 |
