# 本批代码差异（基线 dcc11f7）

基准 `dcc11f7`；本批相对基线修改/新增如下（编制时工作区尚未提交；完整补丁 `changes.patch`）。

| 文件 | 类型 | 作用 | 行数 |
| --- | --- | --- | --- |
| `mvp/rkd_mvp/realmodel_spatial_adapter.py` | 重写为 v2 | 底图结构化解析与逐项对账（R01）、来源证据核验（R02）、持久候选入口（R03）、主轴/类型保真（R04）、全字段 diff（R06） | 955 |
| `scripts/repro_w3_adapter_negatives.py` | 新增 | 同例负例复现 harness，加载指定 adapter 文件，before/after 共用夹具 | 230 |
| `scripts/verify_w3_adapter_remediation.py` | 新增 | 真实 provider + 本地协议桩 + 真实仓储 + 渲染 + ZIP/下载校验 + 契约演进证据，18 项 | 543 |
| `contracts/v1/realmodel-spatial-adaptation.v2.schema.json` | 新增 | 适配契约自身 schema v2 | 212 |
| `contracts/v1/realmodel-spatial-option.v2.schema.json` | 新增 | additive 输出文档 schema v2（旧主契约不改） | 1463 |

**未改**：`ai_design_option_provider.py`、`ai_design_studio_adapter.py`、`ai_spatial_outputs.py`、既有 `contracts/v1/*`、数据库迁移、前端、AD、用户底图确认、旧复核包与证据。补丁行数不作为价值证据；复核重点：`_load_basemap_facts`/`reconcile_site`、`verify_source`、`path_centreline`、`adapt_persisted_candidate`、`diff_spatial`，以及两个脚本的同例断言。
