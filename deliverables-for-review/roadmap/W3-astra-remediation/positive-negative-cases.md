# 正负例与实测证据（W3 Astra R1—R5）

原始证据：`var/evidence/roadmap/W3-astra-remediation/`；综合验证 `checks.json`；前后复现 `outputs/findings-{before,after}.json`。

## A. before（72442c7 冻结代码，全部复现）

| 用例 | 真实调用 | 观察 |
| --- | --- | --- |
| R1 采用链 | 真实 provider(桩)→真实服务→SQLite | 生产 `run_verifier=None`；v1+real_model 被 `REAL_MODEL_REQUIRES_V2` 拒绝；v2 无 verifier 报 `RUN_VERIFIER_UNTRUSTED`；adopt `ADMISSION_NOT_VALIDATED` |
| R2 自报真实 | `observe_exchange(live_http, https://public..., b'x', b'y')` → `issue` → `verify` | 接受；`real_model_run`、`simulated=False`、验签通过 |
| R3a 家具平移 | 适配文档 spatial+legacy 家具 X+100mm，保留旧 `spatial.source.sha256` | admitted |
| R3b 来源冲突 | `design_origin.kind=fixture`、`run_refs=[]`、`generation.real_model=true` | admitted |
| R3c 跨项目 | 同一文档换项目上下文 | 自报 project_id 可被采用 |
| R4 中心线篡改 | `spatial.circulation[0].path_mm` X+100000mm，声明矩形/legacy 不变 | 投影检查通过、admitted |
| R5 登记保护 | 检查真实服务 import/调用 | `build_delivery_package`/`assert_complete_package` 只在验证脚本；无渲染包隐式完整 |

harness 输出：`{"R1":"vulnerable","R2":"vulnerable","R3":"vulnerable","R4":"vulnerable","R5":"vulnerable"}`。

## B. after（本批，全部关闭）

| id | 断言 | 结果 |
| --- | --- | --- |
| A-01 | 场地快照两摘要分离、可重算、随入口变化 | pass |
| A-02 | R2 自报 live_http 被拒；签发只由受控传输实际字节 | pass |
| A-03 | R1 真实 provider(桩)→服务→SQLite 候选集 succeeded | pass |
| A-04 | 候选 v2+spatial、来源 fixture、运行记录全模拟、admitted | pass |
| A-05 | R1 正常生成到采用闭环（adopt 不再 ADMISSION_NOT_VALIDATED） | pass |
| A-06 | R1 不支持反馈路径显式拒绝、保留原版本、不复用父准入 | pass |
| A-07 | R3 家具篡改/来源冲突/跨项目/父链声明全部拒绝，可信来源 admitted | pass |
| A-08 | R4 从实际几何重建；横/纵/近方/越界/零宽/缺失/连接核对 | pass |
| A-09 | R5 完整包 complete，下载字节与 ZIP/清单逐项一致 | pass |
| A-10 | R5 无渲染包 preview_incomplete/complete=false，不冒充完整 | pass |
| A-11 | R5 渲染失败/取消不登记完整包 | pass |
| A-12 | R5 单一文件集打包与 assert_complete_package 一致 | pass |
| A-13 | HTTP/浏览器下载 | not_run |

harness 输出：`{"R1":"fixed","R2":"fixed","R3":"fixed","R4":"fixed","R5":"fixed"}`。

## C. 负例失败码（after）

`OBSERVE_EXCHANGE_CLOSED`、`OBSERVATION_FORGED`、`SOURCE_DIGEST_MISMATCH`、`SOURCE_CONTENT_TAMPERED`、`SOURCE_DECLARATION_CONFLICT`、`PROJECT_IDENTITY_MISMATCH`、`GEOMETRY_PROJECTION_INCONSISTENT`、`PATH_WIDTH_INVALID`、`PATH_AXIS_INCONSISTENT`、`PATH_FOOTPRINT_MISSING`、`LEGACY_SEGMENT_EXTRA`、`LEGACY_ZONE_EXTRA`、`LEGACY_FURNITURE_EXTRA`、`CONTROLLED_FEEDBACK_PATH_UNSUPPORTED`、`ADMISSION_NOT_VALIDATED`、`PACKAGE_INTEGRITY_FAILED`。

说明：跨项目负例同时由 `TrustedRunVerifier` 的 `RUN_PROJECT_MISMATCH` 与 `PROJECT_IDENTITY_MISMATCH` 双重拒绝；父链变化由 `PARENT_REVISION_MISMATCH`/`PARENT_CANDIDATE_MISMATCH` 拒绝。
