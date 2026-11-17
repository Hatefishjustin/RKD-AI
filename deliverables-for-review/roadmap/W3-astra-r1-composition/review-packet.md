# W3 Astra R1 追加整改复核包：真实应用组合根接通受控运行时

基线提交：`446a6f6526391e1dcc6313f8247760c883448063`（第一轮整改交付，含 `86e3e36` 的代码 + `446a6f6` 的复核包元数据）。
本轮整改代码提交：见 `commit-reference.md`（该文件在本批提交后生成，避免写死易变 HEAD）。
复核输入：第二轮意见——`86e3e36` 新增了 `ControlledDesignRuntime` 并让 `AIDesignOptionService` 支持注入，但**全仓只有类定义，没有任何生产创建/注入位置**，端到端证据可能只是验证脚本手工注入。这是审查意见，不是设计验收意见。

**这不是设计批准、不是客户成果、不放行真实模型试验、不推进阶段 2/3 或 W4，不改 AD01—AD08 与阶段确认。**

旧包 `W3-astra-remediation/`、`W3-control-trust-remediation/`、`W3-adapter-remediation/`、`W3-trust-architect/`、`W3-trust-remediation/` 及更早证据只读保留，一字未改。底图原件 `deliverables-for-review/roadmap/W2-R4-表达收口/basemap/` 只读保留。本批运行写入新目录 `var/evidence/roadmap/W3-astra-r1-composition/`。

## 1. 结论先说

第二轮的核心质疑成立：`86e3e36` 只提供了**可注入的类**，生产组合根没有构造它。上一批的端到端证据确实依赖验证脚本手工 `ControlledDesignRuntime(...)`，不能证明产品路径可用。

本轮把接线补在两个**真实生产组合根**里（`ApiService`、`PostgresApiService`），它们是 `run_api_server.py`、`run_postgres_api.py`、`run_team_api.py` 唯一使用的服务构造点。用户经真实 API 的 submit 现在**默认**走受控链；真实模型配置若拿不到受控运行时，submit 直接 503 `CONTROLLED_RUNTIME_REQUIRED`，不再退回旧候选路径，也不会产出无法采用的候选。启动配置不完整时在组合根抛 `ControlledRuntimeSetupError`，服务起不来，不伪造结果。

## 2. 组合根与启动入口（文件 + 行号）

完整清单见 `outputs/entrypoints.json`。要点：

| 位置 | 行号 | 作用 |
| --- | --- | --- |
| `mvp/rkd_mvp/api_service.py` | 58—61 | 组合根新增依赖接缝：`design_option_config` / `design_transport_opener` / `controlled_runtime` / `spatial_renderer` |
| 同上 | 107—111 | `load_design_option_config()` → `self.design_option_config`（生产读环境变量，不需调用方传） |
| 同上 | 112—120 | 真实模型配置且未注入 runtime 时 `build_controlled_runtime(...)`；缺 `runtime_root` 抛 `RUNTIME_ROOT_REQUIRED` |
| 同上 | 121—127 | `AIDesignOptionService(..., controlled_runtime=runtime)` —— 唯一生产注入点 |
| 同上 | 133—137 | `AISpatialOutputService(..., renderer=spatial_renderer)` |
| `mvp/rkd_mvp/postgres_api_service.py` | 48—49、88—101 | PG 组合根同构接线（配置→runtime→注入） |
| `mvp/rkd_mvp/controlled_design_runtime.py` | 160—200 | `build_controlled_runtime`：fail-closed 的唯一入口 |
| `mvp/rkd_mvp/ai_design_option_service.py` | 259—264 | submit 守卫：真实模型 + 无 runtime → 503 `CONTROLLED_RUNTIME_REQUIRED` |
| 同上 | 908 | 反馈守卫：`CONTROLLED_FEEDBACK_PATH_UNSUPPORTED`，原修订不变 |
| 同上 | 975—1008 | 采用边界复核：用持久化的不可变源候选 + provenance 重新准入 |
| `mvp/rkd_mvp/ai_spatial_output_service.py` | 494—502 | `wait_for_idle()` 公开生命周期，供组合根/测试在取消或失败后安全收尾 |

启动方式（生产入口未改，只是其内部组合根现在会建 runtime）：

```
# SQLite
./.venv/Scripts/python.exe mvp/run_api_server.py            # -> ApiService(...) 第 29 行
# PostgreSQL
./.venv/Scripts/python.exe mvp/run_postgres_api.py          # -> PostgresApiService(store, root) 第 37 行
./.venv/Scripts/python.exe mvp/run_team_api.py              # -> PostgresApiService(store, runtime) 第 21 行
```

fail-closed 判据（`build_controlled_runtime`）：

- `REAL_MODEL_REQUIRED`：非 `openai_compatible` 配置不建受控链（合成通道保持原非 AI 路径）；
- `DESIGN_CONFIG_INCOMPLETE`：`configuration_errors` 非空（缺 base_url/model 等）启动即失败；
- `API_KEY_REQUIRED`：无 `RKD_AI_API_KEY` 不启动真实链（键只在进程环境，不落盘/不入日志/不入仓储）；
- `RUNTIME_ROOT_REQUIRED`：真实模型但组合根没有运行时根目录。

## 3. 前后同例实测（同一 harness，同一代码路径）

harness：`scripts/w3_composition_findings.py`，**只调用 `ApiService` 公共方法**（submit / get / adopt / revise / 成果 submit·cancel·get·download），依赖只在组合根接缝注入。基线用 `git archive 446a6f6 mvp contracts scripts …` 冻结到 `var/evidence/roadmap/W3-astra-r1-composition/before/`。

| 检查 | before（446a6f6 冻结代码） | after（本批工作树） |
| --- | --- | --- |
| `runtime_injected` | 组合根无接缝（`seam_supported=false`），`controlled_design_runtime` 不存在 | runtime 已创建，且 `ai_design_option_service.controlled_runtime` 就是它 |
| `chain`（submit→快照→受控 provider→持久候选→适配/准入→adopt） | 候选集 `status=failed`、`error_code=DESIGN_PROVIDER_NOT_CONFIGURED`（真实配置根本进不了产品路径） | `status=succeeded`；schema `rkd-ai-design-option.v2`；`spatial` 存在；来源 `fixture`；运行记录全 `simulated=True`；`adopt=adopted_draft` |
| `missing_runtime`（真实模型配置拿不到 runtime） | 无守卫，不会清晰失败 | 503 `CONTROLLED_RUNTIME_REQUIRED` |
| `feedback`（不支持的反馈路径） | 无候选可选（链已失败），两项均 false——基线连"拒绝且原版保留"都无从证明 | `CONTROLLED_FEEDBACK_PATH_UNSUPPORTED`，`option_revision_id` 与 `revision_no=1` 未变 |
| `outputs`（成果四态） | 全 false：链已失败、无候选，四态无从发生（且基线服务端本未接完整性判定） | 完整 `delivery_status=complete` 且 6 条清单条目逐条 SHA 相符、含 render；无渲染 `preview_incomplete` + 清单 `incomplete`；渲染失败 `failed`/`SPATIAL_OUTPUT_FAILED` 无 revision；取消 `cancelled` 无 revision |

原始 JSON：`outputs/findings-before.json`、`outputs/findings-after.json`（同 schema `rkd-w3-composition-findings.v1`，含 `external_calls=0`、`cost_cny=0`、`keys_used=false`）。

退出码即断言：before `--expect vulnerable` → 5/5 vulnerable，退出 0；after `--expect fixed` → 5/5 fixed，退出 0。任何一项反向都会返回 2，不会"看起来通过"。

## 4. 永久回归测试（经真实组合根，不调私有 helper）

`mvp/tests/test_w3_composition_root.py`，**7 项全通过**（本机约 18s）：

1. `test_real_composition_root_generates_and_adopts_through_controlled_chain` —— 经 `ApiService` 公共 API 生成 v2 站点绑定候选、来源 `fixture`、运行记录全模拟、`adopt=adopted_draft` 且 `formal_approval=false`。
2. `test_real_model_config_without_runtime_fails_clearly` —— 真实模型配置 + 无 runtime → `CONTROLLED_RUNTIME_REQUIRED`。
3. `test_incomplete_real_config_fails_at_composition_root` —— 配置不完整在**构造期**抛 `DESIGN_CONFIG_INCOMPLETE`。
4. `test_unconfigured_does_not_create_controlled_runtime` —— 未配置通道不得凭空建 runtime。
5. `test_unsupported_feedback_rejected_and_original_revision_preserved` —— 反馈拒绝且 `revision_no` 仍为 1。
6. `test_output_registration_and_download_four_states` —— 完整/无渲染/渲染失败/取消四态；完整态对每条 manifest 条目重算 SHA 与下载字节一致、ZIP 中不含 `package.zip` 自身；无渲染 `preview_incomplete` 且清单 `incomplete`；失败与取消均无 revision 登记。
7. `test_postgres_composition_root_wires_runtime_and_fails_closed` —— 第二个生产组合根（PG）启动期接线与 fail-closed（不完整配置抛错、真实配置注入 runtime、未配置不建 runtime）。**PG 数据面需活动实例，本机未测，记 not_run。**

测试只用组合根构造参数注入 opener/renderer（与生产注入点一致），所有模型交换走本地协议桩，`simulated=True`，无外部调用、无真实密钥。

## 5. 测试运行

- 组合根回归：`7/7 OK`
- 第一轮 Astra 回归 `test_w3_astra_remediation.py`：`4/4 OK`
- 全量单测：`273 tests OK`（上一批 266 + 本轮新增 7）。日志 `var/evidence/roadmap/W3-astra-r1-composition/after/full-regression.log`。
- **not_run**：HTTP 服务进程级下载、浏览器 UI 可操作链、PG 数据面（需活动实例）、真实模型调用（0 授权/0 费用/0 密钥）、正式采用与发布、跨机验签、专业签核。

## 6. 信任边界与残余风险（请复核）

- **谁能造候选**：只有组合根创建的 `ControlledDesignRuntime`；服务拿到的 `bound_opener(project_id)` 只能对绑定项目发起交换。调用者无法在交换时自报 transport/端点/字节（第一轮已关闭 `observe_exchange`）。
- **什么算真实**：只有生产 HTTP opener（`build_live_opener`，无注入 opener）且端点非环回/私网才可能 `simulated=False`。本批全部注入桩，`simulated=True`、来源 `fixture`，**不是 AI 自动设计**。
- **api_key 仍留在进程环境**：`AIDesignOptionService` 在未显式传参时读 `RKD_AI_API_KEY`；runtime 不复制、不落盘。真实配置缺键时组合根直接失败，走不到调用。
- **进程内边界**：不防御拥有任意进程执行权限者（与复核指示一致）；不扩建 KMS/账号/NAS。
- **残余风险 1**：持有运行目录写权限者可伪造签名记录——这是 OS 账户 + 目录 ACL 边界，本批不处理。
- **残余风险 2**：`AIDesignOptionService` 的 `api_key` 在未传参时回落到字符串 `controlled-stub`。真实模型配置在组合根已因 `API_KEY_REQUIRED` 挡住，故生产走不到；但该回落仍存在于类内，属于既有权衡，本轮未改（改动会波及第一轮已验证的桩路径）。

## 7. 没有做什么

- 未新增组合根、未新增 HTTP 路由、未改启动脚本的命令行契约。
- 未放宽任何检查，未把夹具/桩结果说成真实模型，未让"跑完"等于"方案通过"。
- 未扩 W4、管理配套、账号/NAS/KMS，未改 AD01—AD08、阶段确认、未知项与正式责任边界。
- 未调用任何外部模型，费用 0、外发 0、未使用真实密钥。

## 8. 未完成项 / 待复核裁定

1. **PG 数据面未跑**：`PostgresApiService` 只验证了启动装配与 fail-closed；真实 PG 上的 submit→adopt→成果下载需活动实例与本机未配置的 `rkd_team` 库，本批 not_run，未用桩冒充。
2. **HTTP/浏览器未跑**：未启动 HTTP 服务进程，下载只在服务层与内存字节层校验。
3. **真实模型调用未发生**：无本轮授权，`simulated=True`，不计 AD01—AD08。
4. **反馈路径仍是"明确拒绝"**：受控候选的反馈修订未实现，本轮按要求保持拒绝并保原版本，不是已完成能力。
5. 复核输入本身是审查意见，本轮不据此宣布 W3 通过或设计通过，交回审查。
