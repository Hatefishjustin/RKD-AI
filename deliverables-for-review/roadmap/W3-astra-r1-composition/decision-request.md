# 待复核裁定事项（本轮不自行决定）

本轮不宣布 W3 通过、不宣布设计通过、不放行真实模型试验、不推进阶段或 W4。以下事项需架构师裁定：

## D1 生产注入点的形态是否可接受

现状：两个真实生产组合根（`ApiService` / `PostgresApiService`）在构造期加载配置、按需 `build_controlled_runtime`、并注入 `AIDesignOptionService`。调用方（HTTP 路由层）不感知 runtime，也不允许在请求里指定 transport/端点/字节。

请裁定：
1. 是否接受"组合根内按配置自动构建"而非"启动脚本显式注入"？若要求显式注入，需改 `run_api_server.py` / `run_postgres_api.py` / `run_team_api.py` 的命令行契约，属契约变更，需单独授权。
2. `spatial_renderer` 作为组合根接缝（默认 `None` → 生产 Blender 渲染器）是否需要改为显式必填？

## D2 PG 数据面未跑（not_run）

`PostgresApiService` 只验证了启动装配与 fail-closed（`test_postgres_composition_root_wires_runtime_and_fails_closed`），未在活动 PG 上跑 submit→adopt→成果下载。本机无 `rkd_team` 实例与凭据，未用桩冒充，故记 `not_run`。

请裁定：是否要求补 PG 数据面实测？若要求，需要活动实例与连接方式（本机是否允许起本地 PG 容器也需授权，涉及新增部署配套）。

## D3 反馈路径仍为"明确拒绝"

受控候选不支持自然语言反馈修订，本轮按要求保持 `CONTROLLED_FEEDBACK_PATH_UNSUPPORTED` 且原修订不变（`revision_no` 不变）。这是"明确拒绝"，不是"已实现"。

请裁定：反馈修订是否列入后续批次？它需要"修订后重新验证、不复用父版准入"的完整设计，属设计能力而非接线。

## D4 `api_key` 的进程内回落（残余风险，未改）

`AIDesignOptionService.__init__` 在未显式传参时 `api_key or os.environ.get("RKD_AI_API_KEY", "controlled-stub")`。真实模型配置在组合根已因 `API_KEY_REQUIRED` 被挡住，生产走不到该回落；但该类内回落仍存在。

请裁定：是否要求移除 `"controlled-stub"` 默认值（改动会波及第一轮已验证的桩路径与相关测试，需明确授权）。

## D5 真实模型试验授权

本轮**未申请、未使用**任何外部模型调用与费用（`external_calls=0`、`cost_cny=0`、`keys_used=false`）。真实模型试验的授权范围（外发类别/次数/费用上限）见 `W3-control-trust-remediation/decision-request.md`，本轮不新增请求。

## D6 本批的定性

- 全部候选来源 `fixture`、`simulated=True`，**不计 AD01—AD08**，不是 AI 自动设计，不是客户成果，不是阶段 2 候选。
- `succeeded` 只表示流程跑完；`adopted_draft` 只表示草稿采用，`formal_approval=false`。
- 未改 AD01—AD08、阶段确认、未知项与正式责任边界。
