# 代码变更清单（基线 2253899 → 本批）

完整补丁：`changes.patch`（仅 `mvp/`、`contracts/`、`scripts/`）。`var/evidence/` 不入库。

## 新增

| 文件 | 作用 |
| --- | --- |
| `mvp/rkd_mvp/site_snapshot.py` | 单一场地快照；`basemap_files_sha256` 与 `site_snapshot_sha256` 分离；`snapshot_from_site()` 用同一份数据重算摘要后比对，摘要不能脱离数据自证 |
| `mvp/rkd_mvp/admission.py` | 版本分发注册表、旧消费者替身、唯一准入党、历史修订回退规则 |
| `scripts/w3_trust_findings.py` | 六项发现的 before/after 同一 harness（真实 provider/仓储/适配/打包） |
| `scripts/verify_w3_trust_remediation.py` | 本批 17 项流水线验证 |

## 修改

| 文件 | 关键变更 |
| --- | --- |
| `mvp/rkd_mvp/controlled_run_ledger.py` | 重写为 `ControlledRunService` + `TrustedRunVerifier`；签发需真实观测；`simulated` 由传输推导；父链需仓储登记；持久密钥+append-only 记录；`isolated_test` 只能 `not_validated` |
| `mvp/rkd_mvp/realmodel_spatial_adapter.py` | `axis_preserving_rect_mm()` 方向可逆重构；legacy 段落带源矩形/主轴；`reconcile_site` 强制快照重算比对；`verify_source` 只接受受控 verifier 并绑定快照；`verify_persisted_site_snapshot` 校验两套摘要；`verify_geometry_projection_consistency()`；删除 `skip_site_integrity`；输出改双摘要命名 |
| `mvp/rkd_mvp/ai_design_option_provider.py` | 请求发送完整快照与入口；删除 `LEGAL_PATH_EXAMPLE`；宽度缺失即失败；按版本选择校验器；`on_exchange` 把实际请求/响应交给受控服务；v2 产物带 `site_snapshot` |
| `mvp/rkd_mvp/ai_design_option_service.py` | 注册表化消费者；`_admission_for` 生成准入党；采用闸口校验 `validation.admission`；准入块只写修订元数据，不写进版本化文档（避免 revise 再次校验失败） |
| `mvp/rkd_mvp/ai_spatial_outputs.py` | `finalize_package(completeness=...)`；`build_delivery_package()` 单一文件集；`assert_complete_package()`；成果清单写入 `site_snapshot`；包内附 `model.json` |
| `mvp/rkd_mvp/ai_design_geometry.py` | `validate_model` 接受 v1/v2，未知版本报 `UNSUPPORTED_SCHEMA_VERSION` |
| `contracts/v2/ai-design-option.schema.json` | 见 `contract-evolution.md` 的三处收紧 |

## 未改

`contracts/v1/*`、`deliverables-for-review/roadmap/W2-*`（底图与阶段1 绑定）、`docs/26` 路线、`web/`、NAS/Postgres/账号相关代码。

## 基线代码快照

`var/evidence/roadmap/W3-trust-remediation/before/code/` 由 `git archive 2253899 mvp/rkd_mvp mvp/persistence contracts` 生成；`before/findings.json.code_root` 记录该路径。
