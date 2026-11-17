# 代码差异说明（本轮 R1 组合根接线）

基线：`446a6f6`（第一轮整改交付）。完整补丁见 `changes.patch`（`git diff 446a6f6 -- 工作树`，含未跟踪新文件）。
统计：7 文件，+709 / −10。

## 按文件

### `mvp/rkd_mvp/controlled_design_runtime.py`（+73 / −10，本轮主要新增）

- 新增 `ControlledRuntimeSetupError(code, message)`：启动期配置不足的唯一异常类型，带稳定 `code`。
- `ControlledDesignRuntime.__init__` 新增 `transport` 参数（默认 `local_protocol_stub`），透传给 `ControlledRunService`；生产用 `live_http`，桩用默认值。原先 transport 被硬编码为桩，等于让生产也永远只能是模拟来源。
- `register_and_issue` 的 provenance 不再硬编码 `provider_kind="local_protocol_stub"` 与 `design_origin.kind="fixture"`：改为**由签名运行记录推导**（`real_model_run` 且 `simulated is False` 才允许声明 `real_model`，否则 `fixture`），`provider_kind` 取记录里的实际 transport。防止调用方或代码默认值把桩结果说成真实模型。
- 新增 `build_controlled_runtime(*, runtime_root, config, opener, basemap_dir, environ)`：组合根唯一入口。非 `openai_compatible` → `REAL_MODEL_REQUIRED`；`configuration_errors` 非空 → `DESIGN_CONFIG_INCOMPLETE`；无键 → `API_KEY_REQUIRED`；有 opener 用注入桩（全模拟），无 opener 用 `build_live_opener()`。键不复制进 runtime。

### `mvp/rkd_mvp/api_service.py`（+32 / −3）

- `__init__` 新增 4 个依赖接缝（58—61）：`design_option_config`、`design_transport_opener`、`controlled_runtime`、`spatial_renderer`。默认值均为 `None`，生产不传即走环境配置。
- 107—120：加载配置；`kind == "openai_compatible"` 且未注入 runtime 时**在组合根内创建**受控运行时；缺 `runtime_root` 抛 `RUNTIME_ROOT_REQUIRED`。
- 121—127：把 runtime 注入 `AIDesignOptionService`。这是全仓唯一生产注入点（第二轮意见指出的缺口）。
- 133—137：`AISpatialOutputService` 接 `renderer` 接缝，使成果四态可在组合根替换渲染器后验证。

### `mvp/rkd_mvp/postgres_api_service.py`（+17 / −2）

- `__init__` 新增 3 个接缝（48—49），88—101 同构完成 `load_design_option_config` → `build_controlled_runtime` → 注入。PG 与 SQLite 两个生产组合根行为一致，不存在"只有一条路径接了"的分裂。

### `mvp/rkd_mvp/ai_design_option_service.py`（+6）

- `submit()` 开头（259—264）：`self.config.real_model and self.controlled_runtime is None` → 503 `CONTROLLED_RUNTIME_REQUIRED`。这是"真实模型配置不得因 runtime 缺失而退回旧候选路径"的硬闸口；没有它，组合根接线可以被绕过而静默降级。

### `mvp/rkd_mvp/ai_spatial_output_service.py`（+12）

- 新增 `wait_for_idle(timeout_seconds=15)`（494—502）：公开生命周期等待，供组合根优雅收尾与测试在取消/失败后释放运行目录。此前只能靠 sleep 或访问私有集合，测试会因后台线程未结束而 teardown 失败。

### `mvp/tests/test_w3_composition_root.py`（新增，+311）

7 项永久回归，全部经 `ApiService` / `PostgresApiService` 组合根与公共 API。详见 `positive-negative-cases.md`。

### `scripts/w3_composition_findings.py`（新增，+268）

同例 before/after harness：只调公共 API，`--code-root` 指定冻结基线或工作树，`--expect` 决定退出码语义，输出 `findings.json`（含 `external_calls=0` / `cost_cny=0` / `keys_used=false`）。

## 未改动

- 契约 schema、`admission.py`、`realmodel_spatial_adapter.py`、`controlled_run_ledger.py`、`ai_spatial_outputs.py` 本轮一行未改（第一轮已交付）。
- 未改 HTTP 路由表、启动脚本命令行契约、数据库 schema、迁移。
