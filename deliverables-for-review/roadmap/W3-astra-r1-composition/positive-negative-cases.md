# 正例与负例（本轮 R1 组合根）

全部经真实组合根（`ApiService` / `PostgresApiService`）与公共 API 执行。负例的期望是"明确失败且不产出可采纳结果"，不是"抛任意异常"。

## 正例

| # | 输入 | 路径 | 期望 | 实测 |
| --- | --- | --- | --- | --- |
| P1 | 完整真实模型配置 + 注入桩 opener（`127.0.0.1:9/stub`） | 组合根建 runtime → `submit_ai_design_options` → 快照 → 受控 provider → SQLite 候选 → 适配 → 准入 → `adopt_ai_design_option` | 候选集 `succeeded`；文档 `rkd-ai-design-option.v2` 带 `spatial`；来源 `fixture`；运行记录 `simulated=True`；`adopted_draft`、`formal_approval=false` | 全部满足（`test_real_composition_root_generates_and_adopts_through_controlled_chain`） |
| P2 | 同上 + 渲染成功 | `submit_ai_spatial_outputs` → 轮询 → 下载 `package.zip` | `complete=True`、`delivery_status=complete`；manifest 每条 SHA 与 ZIP 实际字节相符；含 render；ZIP 不含自身 | 6 条清单条目逐条相符，`zip_sha256=f69416dd…` |
| P3 | 同上 + `render=false` | 同上 | 包合法存在但 `complete=False`、`preview_incomplete`；清单 `package_completeness.status=incomplete`、`render_status=not_run` | 满足 |
| P4 | 未配置通道（`kind=unconfigured`） | 组合根构造 | 不创建受控运行时（走原非 AI 路径） | `controlled_design_runtime is None` |
| P5 | PG 组合根 + 完整真实配置 + 桩 opener | `PostgresApiService(...)` 启动装配 | runtime 创建并注入设计服务 | 满足（数据面未跑，见 not_run） |

## 负例

| # | 输入 | 期望 | 实测 |
| --- | --- | --- | --- |
| N1 | 真实模型配置，但服务层拿不到受控运行时（模拟组合根漏注入） | 503 `CONTROLLED_RUNTIME_REQUIRED`，**不生成任何候选**、不退回旧路径 | 抛出；守卫位于 `submit()` 开头、任何写库之前，故不产生候选集 |
| N2 | 真实模型配置但 `configuration_errors` 非空（缺 base_url/model） | 组合根**构造期**抛 `ControlledRuntimeSetupError` / `DESIGN_CONFIG_INCOMPLETE`，服务不可用 | 抛出 |
| N3 | 真实模型配置但无 `RKD_AI_API_KEY` | `API_KEY_REQUIRED` | `build_controlled_runtime` 构造期分支；本批未单列用例（环境无键即触发，未在本机运行以避免与真实调用混淆） |
| N4 | 真实模型配置但组合根无 runtime 根目录 | `RUNTIME_ROOT_REQUIRED` | `ApiService` 构造期分支；无 `db_path` 时的防御路径，本批未单列用例 |
| N5 | 对受控候选提交反馈修订 | 422 `CONTROLLED_FEEDBACK_PATH_UNSUPPORTED`，**原修订不变**（同一 `option_revision_id`、`revision_no=1`） | 满足 |
| N6 | 渲染器抛异常 | 任务 `failed`、`error_code ∈ {RENDER_FAILED, SPATIAL_OUTPUT_FAILED}`、**无 revision 登记**，不产生完整包 | 满足（`SPATIAL_OUTPUT_FAILED`） |
| N7 | 渲染中取消 | 任务终态 `cancelled`、**无 revision 登记** | 满足 |
| N8 | PG 组合根 + 不完整真实配置 | `DESIGN_CONFIG_INCOMPLETE`，不启动 | 满足 |
| N9 | PG 组合根 + 未配置通道 | 不创建 runtime | 满足 |

## 与第一轮负例的关系

第一轮的 R2—R5 负例（自报 `live_http` 被拒、内容篡改/声明冲突/跨项目拒绝、几何投影重建、完整性判定）在本轮**未修改，仍全部通过**（`mvp/tests/test_w3_astra_remediation.py` 4/4）。本轮只补"这些能力是否真的挂在产品路径上"。

## 不成立的"通过"

- 候选集 `succeeded` 只表示流程跑完，不等于方案通过；本批全部 `simulated=True`、来源 `fixture`，不计 AD01—AD08。
- `adopted_draft` 是采用草稿，`formal_approval=false`，不等于设计批准。
- 未启动 HTTP 服务进程、未跑浏览器 UI、未跑 PG 数据面，均记 `not_run`，不用测试总数替代。
