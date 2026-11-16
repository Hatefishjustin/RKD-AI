# W3 受控运行与场地快照整改复核包

编制：2026-11-16 · 基线 `4d2ac76` · 交架构复核。**不是设计批准、不是客户成果、不放行真实模型试验、不推进阶段3/W4、不改 AD。**

委托：`deliverables-for-review/roadmap/W3-remediation-architect/review-and-next.md`。旧包 `W3-adapter-remediation/`、`W3-真实模型spatial适配/` 与本批以前的证据均未覆盖；本批一切脚本在 `var/evidence/roadmap/W3-control-trust-remediation/` 新目录运行。

## 1. 做了什么

先复现六项架构师负例（冻结 `4d2ac76` 代码存 `before/code/`，同一 harness `scripts/repro_w3_control_trust_negatives.py` 对 before/after 各跑一次），再修复：

- **P1 场地快照贯通**：新增 `rkd-site-snapshot.v1` 单一快照，含经 SHA 验证的底图事实、入口概念假设（标 `site_verified=false`/可替换）与现场未知项；同一快照哈希贯通 provider 请求、几何校审、适配器、成果清单。修复 provider 硬编码入口 [0,2.24] 忽略站点入口的缺陷（`ai_design_option_provider.py` 现使用站点声明的入口点）。持久候选入口/保留区必须与快照逐项一致，动线不得压保留区且入口必须连通，否则拒绝。
- **P1 来源可信边界**：新增 `mvp/rkd_mvp/controlled_run_ledger.py`——受控运行账本，进程内密钥签发 HMAC、按 run_id 查表验签，核验项目/候选摘要/输入/输出/父修订/父候选/父项目；自报 JSON 与自算 SHA 不再算证据。`real_model` 需要账本中 `simulated=false` 的真实运行记录；本批 0 条，故全部来源保持 `fixture`/`generation.real_model=false`。
- **P1 持久候选完整映射**：`candidate_from_persisted` 现传递 relationships、对象级 material_id、focal 结构与来源；未知 kind / 非矩形几何显式标 unsupported/unknown 并带字段清单，不再静默跳过。
- **P2 唯一权威契约**：新增顶层 `rkd-ai-design-option.v2`（`contracts/v2/ai-design-option.schema.json`），`spatial.oneOf` 正式纳入 Studio 与真实模型两类分支；旧 v1 schema 不改，旧文档继续通过、旧消费者按版本拒绝 v2。详见 `contract-evolution.md`。
- **P2 图面口径**：图例改为"主动线（模型声明宽度，非实测净宽）"；近方/主轴未知路径不再画零长连线冒充连通，改画轮廓并标"主轴未定/连通未验证"。
- **P2 验收边界**：HTTP 下载明确记 not_run（C-13）；`--no-render` 仍可出包但清单显式标 `package_completeness=incomplete`，不登记完整成果；复跑脚本只用新目录；底图按尺寸匹配仅适用于固定已确认字节，同尺寸歧义拒绝。

## 2. 六项负例：前后同例实测

| 项 | before（4d2ac76 实测） | after（同例复跑） |
| --- | --- | --- |
| 入口错位/保留区交叠 | 入口标注 [0,10.3] 与动线端点 [0,2.24] 相距 **8.06m**；path-south 与楼梯保留区交 **3.072㎡** | 距离 **0m**；交叠 **0**；C-05 逐项匹配通过 |
| 完整自校验伪来源/伪父链 | 接受：`design_origin=real_model`、`generation.real_model=true`、任意父 ID 标 `resolved` | 拒绝 `RUN_LEDGER_ABSENT`；账本验签/跨项目/错误父 ID 负例全拒绝（C-09） |
| 关系/材料/focal/未知对象损失 | relationships 0、材料绑定全 null、focal 丢失、未知 kind 静默 | relationships 1、材料绑定 mat-specific、focal 保留、未知 kind 与非矩形显式 unsupported（C-10） |
| 契约冲突 | 顶层仍 v1，旧 schema 26 错误，无版本升级 | 顶层 v2，旧 v1 文档仍通过、v2 被旧消费者按版本拒绝（C-08） |
| 净宽图例 | "主动线（净宽 mm）"；近方零长中心线 | "主动线（模型声明宽度，非实测净宽）"；近方标未验证（C-14） |
| `--no-render` 完整包 | 有 manifest+ZIP、无 render、未声明不完整 | 清单显式 `package_completeness=incomplete`，不登记完整成果（C-12） |

## 3. 测试与未运行

- 综合验证 `scripts/verify_w3_control_trust.py`：**14/14 observed_pass，0 fail，1 not_run**（C-13 HTTP 下载）。完整渲染运行；本机 Blender 出人眼图 1 张（1,041,510 字节），ZIP 8 文件含 `render.png`，重开逐项一致。
- `--no-render` 独立预跑：13 pass / 0 fail / 2 not_run（渲染、HTTP 下载）；渲染与下载不计通过。
- 全量单测 **262/262 OK**（日志见证据 `after/full-regression.log`），执行者实测、架构师未独立重跑。
- **未测**：真实模型调用、HTTP 下载与浏览器/UI 可操作链、正式采用/持久化到运行库、NAS/PG/账号/发布、专业签核。C-13 明确 not_run，不用内存 ZIP 字节比对冒称 HTTP 下载。

## 4. 仍然不像设计公司成果的地方

人眼图是灰盒内部样张：中性材质、无真实木纹/石材/软装/产品细节/人物/窗光层次；每候选仅 1 机位；平面分区仍矩形，无墙门窗构造、洁具、闭合尺寸链；成本无价源全 unknown。来源是本地协议桩与离线夹具，不是系统自动设计，不计 AD01—AD08。

## 5. 交付路径

复核包：`deliverables-for-review/roadmap/W3-control-trust-remediation/`（review-packet.md、checks.json、manifest.json、contract-evolution.md、positive-negative-cases.md、decision-request.md、code-diff.md、changes.patch、outputs/ 10 文件）。证据：`var/evidence/roadmap/W3-control-trust-remediation/{before,after,no-render}/`。变更路径与 SHA 见 `manifest.json`；字段损失见 `checks.json` C-10 与 `after/verification.json`；外部调用 0、外发 0、tokens 0、费用 0、密钥未使用未落盘（stub key 字符串非真密钥）。真实模型试验外发/费用边界仍未获授权，见 `decision-request.md`。请架构师复核；执行方不自行宣布 W3 或客户设计通过。
