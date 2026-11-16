# W3 前置工程复核包：真实模型输出 → 版本化 spatial → 同源成果

编制：2026-11-16（北京时间）· 交架构师复核 · **不是设计批准、不是客户成果、不是 W3 真实设计验证通过**

基准提交 `5823cf74d91fe18aefa1881e47483035086775f4`；本批新增 4 个源码/契约文件（见 `code-diff.md`、`changes.patch`），未改任何既有业务程序、迁移、AD 或旧证据。

## 1. 需求映射与边界

执行负责人收到的下一批主线（来自 `W2-stage1-binding-architect/stage1-binding-and-next.md`）：真实模型输出 → 版本化 spatial → 同一冻结模型生成可读平面、人眼效果图和受支持净量；先在离线确定性夹具上验证映射（对象身份、`zone_role`/`furniture_type` 词表、坐标单位、父链/来源、字段损失、unknown、负例、新旧版本对账）；在用户确认的 v2 底图上对账；矩形四角化不冒称非矩形能力；`curved_intent` 不生成弧墙；W2 人工表达与真实来源分离；先交架构复核。

本批对应实现：

| 要求 | 本批交付 | 结论 |
| --- | --- | --- |
| 适配契约 | `contracts/v1/realmodel-spatial-adaptation.schema.json`（契约本身 schema）+ `adaptation-contract.json`（由代码常量生成，避免契约与实现漂移） | 已交付，RM-01 |
| 离线确定性映射 | `mvp/rkd_mvp/realmodel_spatial_adapter.py`，0 网络调用 | 已交付，RM-10A/10B |
| 前后同例负例 | `scripts/verify_realmodel_spatial.py` 的 RM-N01—N05、RM-16 | 已交付，见 `positive-negative-cases.md` |
| 字段/来源/损失清单 | `field-source-loss.json`、`checks.json` RM-12—15 | 已交付 |
| 阶段2样张工程路径 | `outputs/` 9 个文件（model/plan/scene/render/quantity/cost/manifest/zip） | 已交付，见 `stage2-samples.md` |
| v2 底图输入对账 | 五文件字节+SHA 逐项复核；边界 26170×17920mm；拒绝测试边界 | 已交付，RM-02/N01/N02 |
| 正交关系 | 几何改动→量/平面变；材质、机位改动→量不变；无价源 unknown | 已交付，RM-17—20 |

## 2. 做了什么 / 没做什么

**做了**：定位到真实模型 provider 只输出米制矩形、不产出 `spatial`，因此其候选无法进入 W2 同源成果链；在离线确定性夹具上补这一层映射并把它做成版本化契约与可执行校验；把用户确认的 v2 底图作为唯一合法输入来源（文件 SHA + 边界 + 模型原生框架对账）；用同一冻结模型生成平面、场景、净量、成本草稿、本地人眼渲染与 ZIP，逐项登记字节/SHA；保留字段清单、来源分离与 unknown 口径。

**没做且原因**：
- **没有调用任何真实模型**：本提示词不新增费用/外发授权；历史真实调用只作证据，不能充当本轮授权。所有样本是离线夹具，来源标 `fixture`，`generation.real_model=false`。
- **没有生成用户项目阶段 2 候选**：阶段 2 具体候选须由系统自动设计并交用户评价；本批是工程适配样张，不是用户项目设计。
- **没有把 W2 人工围合/材料/家具表达搬进真实模型来源**：两者在 `spatial.source.origin_kind`、`design_origin`、`adaptation.expression_source` 分离（RM-13）。
- **没有启动 W4、未改 AD、未扩 PG/NAS/账号/租约、未发布/报价/下单/付款**。
- **未覆盖旧证据**：新证据只在 `var/evidence/roadmap/W3-真实模型spatial适配/after/` 与 `deliverables-for-review/roadmap/W3-真实模型spatial适配/`；旧复核包与运行证据字节未动。

## 3. 验证结果

全量脚本 `scripts/verify_realmodel_spatial.py` 真实执行：**20/20 observed_pass，0 fail**（`checks.json`、证据 `var/evidence/roadmap/W3-真实模型spatial适配/after/verification.json`）。契约实例符合自身 schema；两候选适配产物符合 additive 输出 schema；确认底图五文件与绑定卡字节/SHA 一致；ZIP 与清单逐项一致；本地 Blender 4.2.9 Cycles 出图 1 张（1,024,095 字节）。回归：既有全量单测 **262/262 OK**（364.299 秒，日志 `var/evidence/roadmap/W3-真实模型spatial适配/after/full-regression.log`）、相关模块 `test_ai_design_options` + `test_real_design_provider` 16/16 通过。这两项都是执行者本批真实执行，架构师未独立重跑。

**说明**：20 项是**函数级 + 离线生成链**证据，架构师应在自己的会话独立复跑关键负例；它不等于 AD01—AD08 通过、不等于用户认可设计、不等于专业签核。`succeeded`/`observed_pass` 只表示所执行检查未发现失败。

## 4. 仍然不像设计公司成果的地方（逐条）

1. 人眼图是**内部工程样张**：统一灰材质、无木纹/石材/微水泥真实贴图、无家具产品细节、无软装/绿植/人物、无窗光层次与软阴影，明显达不到客户交付级；已如实保留在 `outputs/render.png`，不包装为成果。
2. 每候选只有 1 个机位 1 张人眼图；缺天花/灯具定位、立面、多视角、材料实物板、汇总客户 PDF。
3. 平面来自矩形四角化：分区仍是矩形，没有真实多边形/弧墙能力；没有柱网、门窗洞口构造、洁具、闭合施工尺寸链；`non_rectangular_capability=false` 已写进模型与清单。
4. 底图保留区边界与入口宽高仍待现场复核，`site_verified=false`；不据此宣称合规或实测。
5. 成本无价源，全部 unknown；没有正式报价、税务或采购事实。
6. 来源是离线确定性夹具；**没有系统模型自动设计**，不计入 AD01—AD08，也不代表 AI 接替设计能力已成立。

## 5. 风险与下一步（需架构师复核）

- 契约中 `rkd-ai-design-option-spatial.v1`（Studio）与新增 `rkd-realmodel-spatial.v1` 并存于同一文档家族；是否接受该 additive 变体、是否要把 `realmodel-spatial-option.schema.json` 提升为正式主契约分支，请架构师判定。本批未修改既有 schema。
- 需要确认 `rkd-realmodel-spatial-adapter.v1` 的字段口径（`bbox_derived` legacy objects、semantic_intents、unknown 清单、design_origin 证据要求）是否满足后续真实模型接入。
- **真实模型试验**：见 `decision-request.md`。未获足够授权前不发起收费请求。
- 用户阶段 1→2 确认条件已满足，但阶段 2 具体候选仍须交用户评价；本批不推进阶段 3。

## 6. 报告口径

外部模型调用 0 次、外发图片 0 张、生成图片 1 张（本地 Blender，内部样张）、tokens 0、新增费用 0；密钥未使用、未落盘。AD01—AD08 未改判，阶段设计结论由用户给。
