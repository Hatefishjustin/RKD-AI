# 代码改动摘要（W3 Astra R1—R5）

基线 `72442c7`。完整补丁 `changes.patch`。

| 文件 | 改动 |
| --- | --- |
| `mvp/rkd_mvp/controlled_run_ledger.py` | v3：关闭 `observe_exchange`；新增 `ControlledTransport`/`BoundControlledOpener`/`ControlledResponse`；`_record_exchange` 需私有执行令牌；`issue` 只接受受控观察；`controlled_observations()` 只读视图；`simulated` 由注入 opener+端点推导 |
| `mvp/rkd_mvp/controlled_design_runtime.py`（新增） | `ControlledDesignRuntime`：组合快照、provider(受控 opener)、仓储、受控运行签发、适配器、可信准入；`register_and_issue`/`adapt`/`admit` |
| `mvp/rkd_mvp/ai_design_option_service.py` | 注入 `controlled_runtime`/`api_key`；`_context` 注入 v2 快照；`_run_set` 受控 provider + `_controlled_finalize`（不可变源候选、运行绑定、适配、准入、revision 记录）；`adopt` 采用时重新核验；受控反馈路径显式拒绝 |
| `mvp/rkd_mvp/admission.py` | `admit_document` 新增服务上下文可信参数；`geometry_projection_digest`/`_origin_consistency_problems`；不可变源摘要重算 + 重新适配几何对账；项目身份核对；来源声明一致性；无可信上下文只能 `engineering_only` |
| `mvp/rkd_mvp/realmodel_spatial_adapter.py` | `rect_from_path_geometry`/`_rect_within`；`verify_geometry_projection_consistency` 从实际中心线/宽度/footprint 重建并双向核对对象、越界、零宽、连接 |
| `mvp/rkd_mvp/ai_spatial_outputs.py` | `completeness_for_render` 单一完整性判定，打包前写入清单 |
| `mvp/rkd_mvp/ai_spatial_output_service.py` | 导入并使用 `assert_complete_package`/`completeness_for_render`；登记存完整性/注册状态；`package_status()`；下载 ZIP 重开校验与状态标注 |
| `scripts/w3_astra_findings.py`（新增） | 同一 harness 对冻结基线与工作树复现/验证 R1—R5，`--expect vulnerable|fixed` |
| `scripts/verify_w3_astra_remediation.py`（新增） | 综合验证 12 pass / 1 not_run，真实服务/仓储/桩，前后证据 |
| `mvp/tests/test_w3_astra_remediation.py`（新增） | 4 项永久回归用例（R2/R3/R4/R5） |

未改：`contracts/`（契约未放宽）、`PROJECT_STATUS.md` 之外的历史状态文件、NAS/PG/账号/备份、底图原件、旧复核包。
