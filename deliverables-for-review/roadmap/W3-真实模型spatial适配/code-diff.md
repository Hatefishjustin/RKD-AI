# 本批代码差异（基准 5823cf7）

基准提交：`5823cf74d91fe18aefa1881e47483035086775f4`（docs: bind confirmed stage1 basemap version and local runtime scope）。编制时这些文件是工作区新增、尚未提交；完整补丁见同目录 `changes.patch`。

| 文件 | 类型 | 作用 | 改动量 |
| --- | --- | --- | --- |
| `mvp/rkd_mvp/realmodel_spatial_adapter.py` | 新增 | 真实模型输出形状→版本化 spatial 的离线确定性适配器；输入对账、词表、单位、来源/父链、字段清单、unknown、负例、版本 diff；0 网络调用 | +687 行 |
| `scripts/verify_realmodel_spatial.py` | 新增 | 20 项校验、前后同例负例、同一冻结模型同源成果、ZIP 复核、本地 Blender 人眼图、证据落盘 | +481 行 |
| `contracts/v1/realmodel-spatial-adaptation.schema.json` | 新增 | 适配契约自身 Schema；约束契约版本、底图 SHA、词表、规则、负例 | +76 行 |
| `contracts/v1/realmodel-spatial-option.schema.json` | 新增 | additive 输出文档 Schema：仍是 `rkd-ai-design-option.v1`，但允许 `boundary_source=rkd-site-basemap.v2` 和 `spatial.schema_version=rkd-realmodel-spatial.v1`；不改既有主 schema | 生成文件 |

**没有改动**：`ai_design_option_provider.py`、`ai_design_studio_adapter.py`、`ai_spatial_outputs.py`、任何 `contracts/v1` 既有文件、数据库迁移、前端、AD、旧复核包/证据。

**给复核者的定位建议**：先看 `realmodel_spatial_adapter.py` 的 `reconcile_site()`（底图对账）、`adapt_candidate()`（映射与 unknown）和 `diff_spatial()`（版本对账），再看 `verify_realmodel_spatial.py` 的 RM-N* 负例与 RM-17—20 同源断言。补丁行数不作为工作价值证据。
