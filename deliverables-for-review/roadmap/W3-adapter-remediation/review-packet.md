# W3 前置适配 R01—R06 整改复核包

编制：2026-11-16（北京时间）· 交架构师复核 · **不是设计批准、不是客户成果、不是 W3 真实设计验证通过、不是正式候选/采用路径**

基线 `dcc11f7`（架构师复核提交）；委托见 `deliverables-for-review/roadmap/W3-adapter-architect/review-and-remediation.md`。执行时间与输入版本见 `manifest.json`、`checks.json`、证据目录 `var/evidence/roadmap/W3-adapter-remediation/{before,after}/`。

## 1. 结论概览

按 R01—R06 先复现、再修复、同例复跑。冻结的 `dcc11f7` 适配器代码保存在 `before/code/`（`realmodel_spatial_adapter.py` 39178B `a4fcc3d1…`、`verify_realmodel_spatial.py` 26909B `89444e59…`），同一复现脚本 `scripts/repro_w3_adapter_negatives.py` 对 before/after 各跑一次；结果分别在 `before/repro/repro.json` 与 `after/repro/repro.json`。整改后验证 `scripts/verify_w3_adapter_remediation.py`：**18/18 observed_pass，0 fail，0 not_run**（完整渲染运行）；`--no-render` 预跑为 15 pass / 0 fail / 3 not_run，渲染与下载项**不计通过**。全量单测 262/262 OK。

## 2. R01—R06 修复与同例前后

| 项 | 架构师负例（before，真实执行） | after（同例真实复跑） | 证据 |
| --- | --- | --- | --- |
| R01 | 空保留区被接受（输出 0 保留区）；入口改 `[0,1]` 被接受且写成底图入口；旧 ZIP 无 render | `KEEPOUT_SET_MISMATCH`；`ENTRANCE_ASSUMPTION_UNDECLARED`（未声明可替换假设时）；底图保留区从 SHA 验证的 JSON+SVG 提取并逐项核对 | `before/repro`、`after/repro`、V-02、V-03 |
| R02 | `run_refs=['invented']` 接受且 `design_origin=real_model` 与 `generation.real_model=false` 矛盾；错 SHA / 伪父链接受 | `RUN_RECORD_MISSING` / `CANDIDATE_SHA_MISMATCH` / `PARENT_UNVERIFIED`；来源字段一致 | V-09、V-10 |
| R03 | 仅手写夹具调用 `adapt_candidate`；无持久候选入口；契约分叉 | 本地协议桩经**真实 provider.generate** + **真实仓储**写入读回，再 `adapt_persisted_candidate`；契约演进方案见 `contract-evolution.md` | V-04/05/060/061、V-17 |
| R04 | 1.4×7.6m 纵向 `path-west` 变 1.4m 横线；`branch` 被固定为 `loop` | 主轴保真：横/纵正确，近方 `ambiguous_unknown` 标 unknown；`branch`/`loop` 不改写；净宽标 `model_declared_unverified` | V-07、V-08 |
| R05 | 旧 `outputs/package.zip` 仅 6 文件、无 render；ZIP 与清单"一致"只证明共同缺图 | 先渲染，再以单一文件集生成清单+ZIP；ZIP 8 文件含 `render.png`+meta，逐项重开校验；下载 ZIP 图像字节与独立渲染 SHA 一致 | V-13/14/15/16 |
| R06 | `diff_spatial` 覆盖 0 字段；`--no-render` 把 RM-21 记 pass | diff 展开到源/场地/父链/材料/语义与对象增删；pass/fail/not_run 分列，`--no-render` 只记 not_run | V-11/12、V-13—15 |

## 3. 本轮交付与变更路径

- 重写 `mvp/rkd_mvp/realmodel_spatial_adapter.py`（v2：底图结构化解析、来源核验、主轴动线、全字段 diff、持久候选入口）。
- 新增 `scripts/repro_w3_adapter_negatives.py`（同例前后复现）、`scripts/verify_w3_adapter_remediation.py`（18 项验证）。
- 新增 `contracts/v1/realmodel-spatial-adaptation.v2.schema.json`、`contracts/v1/realmodel-spatial-option.v2.schema.json`；**既有契约与主 schema 未修改**。
- 复核包：`review-packet.md`、`checks.json`、`manifest.json`、`code-diff.md`、`changes.patch`、`adaptation-contract.json`、`contract-evolution.md`、`positive-negative-cases.md`、`decision-request.md`、`outputs/`（10 文件）。
- 证据：`var/evidence/roadmap/W3-adapter-remediation/before/{code,repro}/`、`after/{repro,runtime,verification.json,full-regression.log,run-record-*.json,parent-evidence.json,scene-for-render.json}`。旧包 `W3-真实模型spatial适配/` 与旧证据保持只读。

## 4. 验证了什么 / 没验证什么

**验证了**：五文件哈希与边界/保留区/入口/未核项逐项对账；独立手算交叠 4.0㎡ 非零；真实 provider + 真实仓储的隔离桩路径；伪来源/错哈希/伪父链拒绝；横纵方动线、branch/loop、净宽口径；渲染进最终包与下载字节；字段损失与 unknown；来源分离（stub key 字符串不是真密钥）。

**未验证（如实）**：
- **真实模型调用**：0 次；没有费用/外发授权；历史调用与自报 `run_refs` 不作为本轮来源证明。
- **主契约合并**：v2 分支仍是实验；未并入 `ai-design-option.schema.json`，未定义正式采用路径（V-17 保留 26 项错误证据）。
- **真实浏览器 / 用户可操作路径**：未打通到 UI 的按钮与下载入口；只在隔离库与脚本层走通，**不作为用户可操作系统宣布**。
- **NAS / PG / 账号 / 租约 / 正式发布 / 报价 / 合同 / 施工**：未触碰。
- **AD01—AD08、阶段2/3、W4、客户设计**：未改判、未推进、未宣布。
- 架构师未独立重跑 262 单测与 Blender；本批这些为执行者证据。

## 5. 仍然不像设计公司成果的地方

渲染是灰盒工程样张：统一中性材质、无木纹/石材/微水泥、无产品细节/软装/绿植/人物、无窗光层次与软阴影；每候选仅 1 机位 1 张图；无天花灯具定位、立面、多视角、材料实物板、客户 PDF；平面分区仍为矩形，无墙门窗构造、洁具、闭合施工尺寸链；成本无价源全 unknown。来源是本地协议桩与离线夹具，**不是 AI 自动设计结果**。

## 6. 边界与下一步

外部模型试验仍需分别确认可外发资料与费用上限（见 `decision-request.md`）；未获授权不发起收费请求。请架构师复核 R01—R06 修复与契约演进方案；是否接受 v2 分支、是否并入主契约、是否允许进入采用链，由架构师/用户决定。执行方不自行宣布 W3 或客户设计通过。
