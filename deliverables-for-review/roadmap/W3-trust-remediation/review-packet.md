# W3 信任边界与场地贯通整改复核包

编制：2026-11-17 · 基线 `2253899` · 交架构复核。**不是设计批准、不是客户成果、不放行真实模型试验、不推进阶段3/W4、不改 AD01—AD08 与阶段结论。**

委托：`deliverables-for-review/roadmap/W3-trust-architect/review-and-next.md`。旧包 `W3-control-trust-remediation/` 与更早的 `W3-adapter-remediation/`、`W3-真实模型spatial适配/` 及其证据只读保留，本批一切运行写入新目录 `var/evidence/roadmap/W3-trust-remediation/`。

## 1. 做了什么

先在**冻结的基线代码**上复现六项发现，再修复并用同一 harness 复跑。前置证据：

- 基线代码快照：`var/evidence/roadmap/W3-trust-remediation/before/code/`（`git archive 2253899 mvp/rkd_mvp mvp/persistence contracts`）。
- 同一 harness `scripts/w3_trust_findings.py` 对 before/after 各跑一次；输出 `before/findings.json`、`after/findings.json`。
- 复现不是读字段：每一步都走真实 provider 调用（协议桩捕获**实际请求字节**）、真实 SQLite 仓储、真实适配器、真实打包器与真实清单校验。

修复：

1. **动线矩形方向可逆**（`realmodel_spatial_adapter.py`）：删掉"一律按横向重构"的写法，新增 `axis_preserving_rect_mm()`，按声明主轴从中心线+宽度反推矩形，并要求反推结果**逐位等于源矩形**，否则 `LEGACY_RECT_NOT_REVERSIBLE` 拒绝输出。legacy 段落新增 `properties.source_rect_mm / axis / exact_path_ref`。
2. **运行来源的真实信任边界**（`controlled_run_ledger.py` 重写）：公开 `issue(kind=real_model_run)` 被删除。现在只有 `ControlledRunService` 能把**自己观测到的请求/响应字节**（`observe_exchange`）签成记录；`simulated` 由传输方式推导（注入桩恒为模拟；只有 live HTTP 且非环回/私网才可能是真实运行）。父修订必须在持久仓储登记（`register_revision`），否则 `PARENT_UNREGISTERED`。消费者只拿 `TrustedRunVerifier` 只读能力，`verify_source` 拒绝任何自建账本/字典/鸭子类型（`RUN_VERIFIER_UNTRUSTED`）；第二个独立服务实例无法核验第一个实例的记录（`RUN_ID_NOT_IN_LEDGER` / issuer 固定）。密钥与记录持久化在服务目录（0600）以支持重启核验；密钥缺失时旧记录只能保持 unknown。**残余风险已在代码与本文第 3 节写明：能写服务目录者可伪造，边界是系统账户+目录 ACL，不是硬件令牌。**
3. **两套摘要分开命名并贯通**：新增 `site_snapshot.py`。
   - `site_snapshot_sha256`：完整快照（边界、保留区、入口事实、概念假设、140 项未核项、底图文件清单）的规范化摘要。
   - `basemap_files_sha256`：五个已确认底图文件的字节摘要。
   同一对摘要贯穿：provider 请求正文（`boundary.site_snapshot_sha256` + 完整 `site_snapshot` 块）→ 受控运行记录 → 持久候选（v2 `site_snapshot`）→ 适配输出（`spatial.source` / `site_snapshot`）→ 成果清单（ZIP 内 `manifest.json.site_snapshot`）与包内 `model.json`。改入口/改假设理由/改保留区都会改摘要，任何一处对不上即拒绝。
4. **请求携带场地、删除 12×8 示例**（`ai_design_option_provider.py`）：`_design_messages` 现在发送入口点、概念假设、保留区、两套摘要与 140 项未核项；硬编码 `LEGAL_PATH_EXAMPLE` 整体删除，规则改为"禁止套用任何非本场地的固定示例坐标"；`site.width/length` 缺失时 `SITE_BOUNDARY_MISSING`，不再回落 12×8。带快照的候选以 `rkd-ai-design-option.v2` 输出并按 v2 校验（此前一律按 v1 校验）。
5. **场地门槛不可绕过**（`adapt_persisted_candidate`）：`skip_site_integrity` 参数删除。新增 `verify_geometry_projection_consistency()`，逐段核对源矩形、legacy shape、spatial 投影与连接引用，并新增 `admission.py` 作为唯一准入党（契约版本→快照绑定→几何→源证据）。`ADMISSION_NOT_VALIDATED` 的候选不能采用。
6. **单一文件集打包**（`ai_spatial_outputs.py`）：新增 `build_delivery_package()`，完整/不完整都只调用一次 `finalize_package(files, manifest, completeness=...)`；`package_completeness` 写进**打包前**的清单，ZIP 不再包含自身；新增 `assert_complete_package()` 作为登记边界，不完整包即使清单校验通过也不能冒充完整。

配套：`ai_design_geometry.validate_model` 接受 v1/v2；`ai_design_option_service` 改为**按版本分发的消费者**（注册表 v1+v2），采用闸口读取修订上的 `validation.admission`。

## 2. 六项发现：前后同例实测

| 发现 | before（2253899 实测） | after（同 harness 复跑） |
| --- | --- | --- |
| 纵向 legacy 矩形零宽 | `path-west` 空间 4.1m 纵线，legacy `width=0m, length=1.2m` | `path-west` legacy `1.2×4.1m`，与源矩形 `[3000,10900,1200,4100]mm` 逐位相等；横向 `path-entry 24×1.2m`、`path-north 17×1.2m` 同样相等；零宽列表为空 |
| 公开 issue 自签伪真实运行 + 任意父链 | `issue(real_model_run, simulated=False, parent="invented-parent-uid")` 被接受；适配后 `generation.real_model=true`、`parent_link_status=resolved` | 伪造观测 `OBSERVATION_FORGED`、任意父链 `PARENT_UNREGISTERED`、自建服务 `RUN_ID_NOT_IN_LEDGER`、桩记录冒充真实 `RUN_RECORD_NOT_REAL`，4/4 拒绝 |
| 完整快照哈希不一致 | 审计 `4001a426…` vs 模型 `db6c0b9a…`（后者是底图文件摘要） | 审计/请求/运行记录/持久候选/适配/成果清单全部为 `6d25bc49…`；底图文件摘要独立为 `db6c0b9a…`；入口改到 9.4m 后快照变为 `cc3976f8…` |
| 请求缺入口 + 旧 12×8 示例 | 请求边界只有宽/长/障碍；无入口、无快照；正文含 `legal_path_example`（12×8 基线） | 请求含入口 `[0,10.3]`、快照 `6d25bc49…`、2 个保留区、140 项未核项；`ships_12x8_example=false` |
| 绕过场地校验 | `skip_site_integrity=True` 接受入口被改为 `[0,2.24]` 的候选，输出入口仍重绑为 `[0,10.3]`，`site_integrity=not_run` | 参数已不存在；同一篡改候选走正常入口被 `PERSISTED_ENTRANCE_MISMATCH` 拒绝（`(0,2240)mm` 与快照不符） |
| 无渲染 ZIP 内嵌自身 | ZIP 含 `package.zip`，`check_zip_against_manifest` 返回 `ok=false`，问题"ZIP 有未登记文件：['package.zip']" | 不完整包 7 文件、无嵌套、清单逐项一致（`ok=true`），但 `registration_ok=false`、状态 `incomplete`；完整包含 render 且 `registration_ok=true` |

## 3. 信任边界与残余风险（请复核这一节）

- **谁可以签发**：只有 `ControlledRunService`。签发需要 (a) 本进程 `observe_exchange()` 产生的观测对象（身份级校验，构造/复制无效）；(b) 候选摘要与项目；(c) 两套摘要；(d) 父修订已在仓储登记。
- **什么算真实运行**：`transport=live_http` 且端点非环回/私网，且服务未处于 isolated 模式。注入 opener 的本地桩一律 `simulated=true`，因此本批 0 条真实运行，`generation.real_model=false`、来源 `fixture`。
- **重启**：密钥与 append-only 记录落盘，重启后可继续验签；密钥丢失/不可读时服务进入 `unknown_missing_key`，历史记录不得升级为真实。
- **残余风险（未解决，需裁定）**：密钥与服务目录同机，拥有该目录写权限者可以伪造记录。本批没有、也不应顺手扩展账号/NAS/KMS。若复核要求更强边界，需要单独的"运行签发在进程外/受 OS 服务保护"任务，不在本批范围。
- **隔离测试**：`isolated_test=True` 的服务只能签发 `admission_scope=not_validated`，不能签发真实运行。

## 4. 测试与未运行

- 综合验证 `scripts/verify_w3_trust_remediation.py`：**16 observed_pass / 0 fail / 1 not_run**（D-15 HTTP 下载）。完整渲染运行：本机 Blender 出图 1 张（1,041,510 字节），完整包 8 文件含 `render.png`、`model.json`，ZIP 重开逐项一致。
- 无渲染独立运行：**14 pass / 0 fail / 3 not_run**（D-12 渲染、D-13 完整包、D-15 HTTP），不完整包同样通过清单校验且不可登记为完整；D-17（成果清单/包内 `model.json`/请求/运行记录同一对摘要）在不完整包上同样通过，不因缺少 render 而豁免。
- 六项负例：before **0/6**、after **6/6**。
- 全量单测 **262/262 OK**（日志 `after/full-regression.log`），与基线同数；执行者实测。
- **未测**：真实模型调用（0 授权/0 费用）、HTTP 下载与浏览器 UI 可操作链、正式采用/发布、跨机/多实例验签、NAS/PG/账号、专业签核。

## 5. 仍未接通的路径（明确阻塞，不用脚本冒充）

1. **用户 submit 路径的场地绑定未接通**：`AIDesignOptionService.submit()` 的 site 仍来自 `context_provider`，尚未把 v2 快照注入提交流程；因此真实模型候选进入用户可操作路径时仍会走 v1 测试边界（或直接失败），本批只在受控验证流水线里贯通。这是下一步必须先解决的产品链缺口。
2. **真实模型运行未发生**：无外发授权、无费用额度；`live_http` 分支未被真实端点验证过，只做了"注入桩永远模拟"的负向验证。
3. **HTTP 下载 / 浏览器 UI**：D-15 记 not_run；ZIP 只做了内存重开字节校验。
4. **正式采用/发布**：仍只到 `adopted_draft`，`formal_approval=false`；v2 精确模型修订被既有 `SPATIAL_MODEL_REQUIRES_PRECISE_PATH` 挡住，未改动。
5. **重启/多实例验签**：只在本机单进程+落盘密钥上验证，没有做跨机、多实例、并发签发测试。
6. **旧适配器验证脚本** `scripts/verify_realmodel_spatial.py`（v1/v2 实验分支）未在本批重跑：它的输入不含场地快照，已被新门槛按设计拒绝；保留只读，不代表通过。

## 6. 仍然不像设计公司成果的地方

`outputs/render.png` 是灰盒内部样张：灰白墙地、彩色地块与两个深色体块，**无材质纹理、无家具细节、无软装、无人物、无窗光层次、无产品选型**；平面仍是矩形分区，无墙门窗构造、洁具、闭合尺寸链；每候选 1 机位；成本无价源全 unknown。来源是本地协议桩与离线夹具，**不是系统自动设计**，不计 AD01—AD08、不构成阶段2方案。

## 7. 交付与费用

复核包：`deliverables-for-review/roadmap/W3-trust-remediation/`（`review-packet.md`、`checks.json`、`manifest.json`、`changes.patch`、`code-diff.md`、`contract-evolution.md`、`positive-negative-cases.md`、`decision-request.md`、`outputs/`）。
证据：`var/evidence/roadmap/W3-trust-remediation/{before,after,no-render}/`；基线代码 `before/code/`；服务与仓储运行库 `after/runtime/`。

外部调用 0、外发 0、tokens 0、费用 0、未使用真实密钥（`stub-not-a-real-key` 是字符串）。真实模型试验仍需单独授权，见 `decision-request.md`。请架构师复核；执行方不自行宣布 W3、阶段2 或客户设计通过。

## 8. 口径核对（对照 `PROJECT_STATUS.md`）

逐条核对，本批不改动任何既有结论：

| 口径 | 出处 | 本批处理 |
| --- | --- | --- |
| 阶段1 底图确认有效（`rkd-site-basemap.v2`，宁波协诚 26.17×17.92 m 五文件，2026-11-16 用户明确确认） | 状态文件"用户确认阶段 1 具体底图版本"条 | 只读沿用；`basemap_files_sha256=db6c0b9a…` 是这五文件的字节摘要，未改文件、未升级版本 |
| 阶段2 具体设计、阶段2→3、AD01—AD08 均未通过 | 状态文件 W3 复核条、`当前下一步` | 未改判；`outputs/` 明确为非设计成果，AD 仍 0/8 |
| 未知项保留、假设显式标注 | 状态文件"未知项保留"、`site_verified=false` | 快照携带 140 项未核项，入口点为 `concept_replaceable` 假设，`site_verified=false` 贯穿请求/候选/成果 |
| 成本/费用未知不填 0；本地试用口径 600,000 元含税、税率 5% | 状态文件"用户口径与后续验证边界" | 本批无价源，成果 `cost.html` 全 unknown；未使用也未改写试用口径 |
| 不扩 NAS/账号/W4，不调用外部模型 | 用户任务书边界 | 0 外部调用、0 外发、0 费用；未改 NAS/PG/账号/备份代码与配置 |
| 旧包只读保留 | 仓库惯例 | 旧包 `W3-trust-architect/`、`W3-control-trust-remediation/` 等未改一字，本批证据只写新目录 |

