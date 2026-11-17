# W3 GPT-6 Astra 独立复核 R1—R5 限定整改复核包

基线提交：`72442c768c88dcb10fa67f6017e7422842c21aee`；整改代码提交：`86e3e363f71bbb1aa57b70bd4cab4cc222b7bbb3`（复现命令与稳定提交引用见 `commit-reference.md`）。
复核输入：GPT-6 Astra 对 `72442c7` 的独立复核结果（R1—R5），不是设计验收意见。

**这不是设计批准、不是客户成果、不放行真实模型试验、不推进阶段 2/3 或 W4，不改 AD01—AD08 与阶段结论。**

旧包 `W3-trust-remediation/`、`W3-control-trust-remediation/`、`W3-adapter-remediation/`、`W3-trust-architect/` 及更早证据只读保留，一字未改。底图原件 `deliverables-for-review/roadmap/W2-R4-表达收口/basemap/` 只读保留。本批一切运行写入新目录 `var/evidence/roadmap/W3-astra-remediation/`。

## 1. 做了什么 / 没有做什么

先在**冻结基线代码**（`git archive 72442c7`，存于 `var/evidence/roadmap/W3-astra-remediation/before/`）上用同一 harness 复现五项发现，再修复，再在工作树同例复跑。每一步都走真实代码：真实 provider 经协议桩（受控传输捕获实际字节）、真实隔离 SQLite、真实适配器、真实准入党、真实服务 submit/adopt、真实成果登记与下载。

修复：

- **R1 实际服务链**（`controlled_design_runtime.py` 新增；`ai_design_option_service.py`）：加入可注入的受控运行时，把「场地快照→provider→持久候选→受控 spatial 适配→可信准入→采用」接成**生产服务代码**的一条链。`_context` 注入 v2 快照（不再用 12×8 测试边界）；provider 只经服务绑定的 opener 发起交换；候选经真实仓储落库后，用同一运行记录做适配与准入；revision 记录不可变源候选与 provenance，**采用边界重新计算准入**而不是读一个持久化的布尔值。历史 v1 候选保持可读，`resolve_legacy_admission` 明确为 `engineering_only`，重新验证方式为走受控运行时重新提交生成新 v2。不支持的反馈路径显式 `CONTROLLED_FEEDBACK_PATH_UNSUPPORTED` 拒绝，保留原版本，不复用父版准入。
- **R2 伪真实签发**（`controlled_run_ledger.py`）：公开 `observe_exchange(project_id, transport, endpoint, request_bytes, response_bytes)` 关闭（`OBSERVE_EXCHANGE_CLOSED`）。签发只能由 `ControlledRunService` 的 `transport().send()` 完成：传输在受控流程内真实执行，观察的 request/response 摘要来自实际字节，`simulated` 由组合根注入的 opener 与端点推导，调用者无法自报 transport/endpoint/字节/摘要。`issue()` 只接受带私有执行令牌的观察。
- **R3 内容及身份绑定**（`admission.py`）：`admit_document` 接收来自**当前服务上下文**的 `organization_id`/`project_id`、`organization`/仓储提供的**不可变源候选**与 provenance；重算源候选摘要并与自报摘要对账；用不可变源候选重新适配并比对几何投影摘要，捕获「同步平移家具保留旧摘要」；`generation.real_model` 与 `design_origin.kind`/`origin_kind`/适配核验记录必须一致，捕获 fixture + real_model 冲突；跨项目文档被项目身份核对拒绝。无可信上下文的文档只能得到 `engineering_only`，不可采用。
- **R4 几何投影漏检**（`realmodel_spatial_adapter.py`）：`verify_geometry_projection_consistency` 从实际 `path_mm` + `width_mm` + `footprint_polygon_mm` **重建**占地矩形，再与声明矩形/legacy shape/source_rect 对账；覆盖横向、纵向、近方（footprint）、越界、零宽、对象缺失/多出、连接引用。只改 `path_mm` 而保留声明矩形会被 `GEOMETRY_PROJECTION_INCONSISTENT` 拒绝。
- **R5 登记保护未接通**（`ai_spatial_output_service.py`、`ai_spatial_outputs.py`）：完整性判定在打包**前**写入清单（`completeness_for_render` 双向共用），登记边界调用 `assert_complete_package`；无渲染包合法存在但显式 `preview_incomplete`/`complete=false`，`package_status()` 暴露状态，下载元数据带状态；下载 `package.zip` 时用 `check_zip_against_manifest` 重开校验实际下载字节。完整/无渲染/失败/取消四类均有证据。

**没有做**：未改变设计来源判定规则、未放宽任何检查、未把夹具冒充真实模型、未扩 W4/管理配套、未改 AD01—AD08、未改变阶段确认边界。外部调用 0、外发 0、费用 0、未使用真实密钥（`stub-not-a-real-key` 是字符串）。

## 2. 前后同例实测

| 发现 | before（72442c7 冻结代码） | after（本批） |
| --- | --- | --- |
| R1 实际服务链 | `adopt` 返回 `ADMISSION_NOT_VALIDATED`；生产无 `run_verifier`；v1+real_model=`REAL_MODEL_REQUIRES_V2` | 真实 provider(桩)→服务→SQLite 候选集 `succeeded`，v2+spatial、来源 fixture、运行记录全模拟，`adopt=adopted_draft`；采用时重新核验；反馈路径显式拒绝保留原版 |
| R2 伪真实签发 | `observe_exchange(live_http, public, 任意字节)` → `real_model_run`/`simulated=False`，验签通过 | `OBSERVE_EXCHANGE_CLOSED`；签发只经受控传输实际字节，`simulated=True`、`kind=local_protocol_stub_run` |
| R3 内容/身份绑定 | 家具同步平移 100mm 保留旧摘要 → admitted；fixture+real_model+空 run_refs → admitted；跨项目可被接受 | 三类负例全部 `not_validated`：`SOURCE_CONTENT_TAMPERED`/`SOURCE_DECLARATION_CONFLICT`/`PROJECT_IDENTITY_MISMATCH`；可信来源 admitted |
| R4 几何投影漏检 | `path_mm` X +100000mm → 投影检查通过、admitted | `GEOMETRY_PROJECTION_INCONSISTENT`；横/纵/近方/越界/零宽/缺失/连接均核对 |
| R5 登记保护 | `build_delivery_package`/`assert_complete_package` 未被真实服务使用；无渲染包隐式完整 | 完整包 `complete=True` 且下载字节与清单一致；无渲染 `preview_incomplete`/`complete=False`；失败/取消不登记完整包 |

## 3. 测试与未运行

- 复现 harness `scripts/w3_astra_findings.py`：基线 `--expect vulnerable` 5/5；工作树 `--expect fixed` 5/5。原始 JSON：`outputs/findings-before.json`、`outputs/findings-after.json`。
- 综合验证 `scripts/verify_w3_astra_remediation.py`：**12 observed_pass / 0 fail / 1 not_run**（A-13 HTTP/浏览器），逐项证据见 `checks.json`。
- 新增回归用例 `mvp/tests/test_w3_astra_remediation.py`：4 项全通过（R2 关闭、R3 声明冲突/几何摘要、R4 几何重建、R5 完整性）。
- 全量单测 **266/266 OK**（基线 262 + 新增 4；日志 `var/evidence/roadmap/W3-astra-remediation/after/full-regression.log`）。
- **未测 / not_run**：HTTP 下载与浏览器 UI 可操作链；真实模型调用（0 授权/0 费用）；正式采用/发布；跨机/多实例验签；NAS/PG/账号；专业签核。

## 4. 信任边界（请复核）

- **谁能签发**：只有 `ControlledRunService`；`transport().send()` 实际执行传输与读字节；组合根在构造时注入 opener，调用者无法在交换时指定 transport/endpoint/响应字节。
- **什么算真实运行**：只有注入真实 HTTP opener（`build_live_opener`）且端点非环回/私网才可能 `simulated=False`。本批注入桩，全部 `simulated=True`、来源 `fixture`。
- **进程内边界**：普通调用者只拿只读 verifier；不防御拥有任意进程执行权限的攻击者（与复核指示一致），不扩建 KMS/账号/NAS。
- **残余风险**：持有服务目录写权限者可伪造签名记录——这是 OS 账户+目录 ACL 边界，不是硬件令牌；本批不处理。

## 5. 仍未接通 / 明确阻塞

1. 反馈修订的精确路径尚不支持：`CONTROLLED_FEEDBACK_PATH_UNSUPPORTED`，原版本保留；要走受控链重新提交生成新候选，不复用父版准入。
2. 真实模型运行未发生：无外发授权/费用额度；live HTTP 分支未用真实端点验证，只验证注入桩恒模拟。
3. HTTP/浏览器 UI 下载链：A-13 not_run；ZIP 仅真实服务下载 + 内存重开字节校验。
4. 正式采用/发布：仍只到 `adopted_draft`，`formal_approval=false`。
5. 重启/多实例验签：仅本机单进程 + 落盘密钥验证；无跨机/并发测试。

## 6. 仍然不像设计公司成果的地方

候选是本地协议桩 + 离线夹具的灰盒样张；分区仍为矩形投影，无墙门窗构造/洁具/闭合尺寸链；无真实材质纹理、软装、人物、窗光层次与产品选型；来源明确为 fixture/模拟，**不构成系统自动设计**，不计 AD01—AD08，不是阶段 2 方案。

## 7. 交付与费用

- 复核包：`deliverables-for-review/roadmap/W3-astra-remediation/`（`review-packet.md`、`checks.json`、`commit-reference.md`、`manifest.json`、`changes.patch`、`code-diff.md`、`positive-negative-cases.md`、`decision-request.md`、`outputs/`）。
- 证据：`var/evidence/roadmap/W3-astra-remediation/{before,after}/`，冻结基线代码 `before/`，前后 harness `*/harness/findings.json`，完整验证 `after/verification.json`，全量回归日志 `after/full-regression.log`。

外部调用 0、外发 0、tokens 0、费用 0、真实密钥未使用。请架构师复核；执行方不自行宣布 W3、阶段 2/3 或客户设计通过。
