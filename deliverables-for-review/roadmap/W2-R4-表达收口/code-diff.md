# 提交差异

- 稳定基线：`8fd7948`（架构师 `review-next.md` 审查 HEAD）。补丁由 `git diff 8fd7948`（配合 `git add -N` 纳入新文件）生成，覆盖业务代码、脚本、状态表与复核输入；不含 `changes.patch` / `manifest.json` / `index.html` 自身，避免自引用。
- 最终提交号见 `commit-reference.md`（单独提交补记，不写死易变 HEAD）。

## `git diff --stat 8fd7948`

```
.../roadmap/W2-R4-architect/entry-independent.json | 407 +++++++++++++
 .../roadmap/W2-R4-architect/no-render-checks.json  | 288 +++++++++
 .../roadmap/W2-R4-architect/review-next.md         |  62 ++
 mvp/rkd_mvp/ai_spatial_outputs.py                  |  28 +-
 mvp/rkd_mvp/plan_layers.py                         | 676 +++++++++++++++++++++
 mvp/rkd_mvp/spatial_presentation.py                | 107 +++-
 scripts/build_w2_r4_closeout_review.py             | 620 +++++++++++++++++++
 scripts/capture_render_crops.cjs                   |  81 +++
 scripts/capture_w2_r4_visual.cjs                   | 169 ++++++
 scripts/render_spatial_scene_r4.py                 | 230 ++++++-
 scripts/verify_w2_r4.py                            | 142 ++++-
 scripts/verify_w2_r4_closeout.py                   | 216 +++++++
 scripts/w2_r4_fixture_presentation.py              | 140 ++++-
 13 files changed, 3114 insertions(+), 52 deletions(-)
```

## 改动摘要（不按行数衡量工作价值）

| 文件 | 改动 |
| --- | --- |
| `mvp/rkd_mvp/plan_layers.py` | 新增：分层平面、避让引线、短编号全局唯一、闭合尺寸链、完整索引 |
| `mvp/rkd_mvp/ai_spatial_outputs.py` | presentation 时委托分层平面；新增 `plan-index.json` 成果与清单摘要；表达式版本常量 |
| `mvp/rkd_mvp/spatial_presentation.py` | 新增 `expression` 契约校验、`origin_kind` 四类分类与计数 |
| `scripts/w2_r4_fixture_presentation.py` | 新增版本化表达输入、V3 测试陈设、display-wing 程序化替换 |
| `scripts/render_spatial_scene_r4.py` | V2 透明玻璃/窗框/窗外假设/分缝收边/曝光；V3 程序化表达对象与来源分组 |
| `scripts/verify_w2_r4.py` | `--no-render` 语义修正、验证分层、索引对账、下载 `plan-index.json` |
| `scripts/verify_w2_r4_closeout.py` | 新增：V1—V3 专项断言，自动与人工分列 |
| `scripts/capture_w2_r4_visual.cjs` | 新增：前后全图/局部/打印缩放与自动几何检查 |
| `scripts/capture_render_crops.cjs` | 新增：人眼图前后全图与窗区/功能区局部 |
| `scripts/build_w2_r4_closeout_review.py` | 新增：复核包组装 |
| `PROJECT_STATUS.md` | 追加本批受限结论与交付记录 |
