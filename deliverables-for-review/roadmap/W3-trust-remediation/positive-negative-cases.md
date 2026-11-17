# 正负例与实测证据

所有条目来自 `scripts/w3_trust_findings.py`（六项）与 `scripts/verify_w3_trust_remediation.py`（流水线）的实际执行，原始 JSON 在 `var/evidence/roadmap/W3-trust-remediation/{before,after}/findings.json` 与 `after/verification.json`。

## A. before（2253899，冻结代码）

| 用例 | 调用 | 观察 |
| --- | --- | --- |
| C1 纵向矩形 | provider 桩 → SQLite 仓储 → `adapt_persisted_candidate` | `path-west` 空间 `path_mm=[[3600,10900],[3600,15000]]`、宽 1200mm；legacy `shape.width="0"`、`length="1.2"` |
| C2 自签真实运行 | `ControlledRunLedger().issue(kind="real_model_run", simulated=False, parent_revision_id="invented-parent-uid", ...)` → `adapt_candidate(run_ledger=同一实例)` | 接受；`generation.real_model=true`；`parent_link_status="resolved"`；签名存在 |
| C3 摘要混用 | 审计 `snap["sha256"]` vs 适配输出 `site_snapshot.sha256` | `4001a426…` vs `db6c0b9a…`（后者等于底图文件清单摘要） |
| C4 请求缺入口 | 捕获桩收到的 `request.data` | 设计 payload 的 `boundary` 只有 `width/length/unit/boundary_source/note/obstacles`；`entrance=null`；正文含 `legal_path_example` 与 12×8 说明 |
| C5 绕过 | `adapt_persisted_candidate(..., skip_site_integrity=True)`，候选入口改为 `[0,2.24]` | 接受；输出入口 `[0,10.3]`（静默重绑）；`site_snapshot_integrity.status="not_run"` |
| C6 无渲染包 | 2253899 `--no-render` 代码路径（`finalize_package` 后再改清单并重建 ZIP） | ZIP 名单含 `package.zip`；`check_zip_against_manifest` → `ok=false`，`problems=["ZIP 有未登记文件：['package.zip']"]` |

## B. after（本批）

### 六项（全通过）

- **C1**：`path-entry 24000×1200mm`、`path-west 1200×4100mm`、`path-north 17000×1200mm`，三者 `declared_rect_mm == legacy == source_rect_mm`；零宽/不一致列表为空；横/竖两类都被覆盖。
- **C2**：四个攻击面全部拒绝——
  `ExchangeObservation(...)` 手构造 → `OBSERVATION_FORGED`；
  `issue(parent_revision_id="invented-parent-uid")` → `PARENT_UNREGISTERED`；
  另建 `ControlledRunService` 验证首个服务的 `run_id` → `RUN_ID_NOT_IN_LEDGER`；
  用桩记录声明 `design_origin.kind=real_model` → `RUN_RECORD_NOT_REAL`。
- **C3**：`site_snapshot_sha256=6d25bc49…` 在审计、请求、运行记录、持久候选、`spatial.source`、成果清单、包内 `model.json` 全部一致；`basemap_files_sha256=db6c0b9a…` 单独命名；入口改 9.4m → `cc3976f8…`。
- **C4**：请求设计 payload 含 `boundary.entrance.point=[0,10.3]`、`boundary.site_snapshot_sha256`、`boundary.basemap_files_sha256`、`site_snapshot.keepouts`（2）、`site_snapshot.unverified_facts`（140）；`legal_path_example`/12×8 字样不再出现。
- **C5**：`inspect.signature` 中已无 `skip_site_integrity`；篡改候选 → `PERSISTED_ENTRANCE_MISMATCH`（`(0,2240)mm` 与快照假设不符）。
- **C6**：不完整包 7 文件、`zip_check.ok=true`、`registration.ok=false`、`status=incomplete`、无嵌套；完整包（真实 render）8 文件、`registration.ok=true`。

### 流水线（16 pass / 1 not_run）

| id | 断言 | 结果 |
| --- | --- | --- |
| D-01 | 两套摘要可重算、互不相等、随入口变化 | pass |
| D-02 | 实际请求带入口/快照/保留区/未核项，无固定示例 | pass |
| D-03 | 候选 v2 且带同一快照 | pass |
| D-04 | SQLite 写入读回仍绑定同一快照 | pass |
| D-05 | 记录由服务观测实际字节签发，simulated、非真实 | pass |
| D-06 | 同运行适配成功，场地与投影一致性执行 | pass |
| D-07 | 横/竖 legacy 矩形无零宽且逐项等于源 | pass |
| D-08 | 未登记父链/跨项目/自建服务/桩冒充真实全拒绝 | pass |
| D-09 | 旧消费者对 v2 报 `UNSUPPORTED_SCHEMA_VERSION`；新消费者读 v2；真实 v1 文档仍通过 | pass |
| D-10 | 真实服务注册表含 v2、provider 的 v2 经服务校验、`not_validated` 被采用闸口拒绝 | pass |
| D-11 | 同源候选 `admitted/site_bound`；改快照摘要后 `adoptable=false` | pass |
| D-12 | 人眼图（Blender 灰盒工程样张） | pass |
| D-13 | 完整包：render 在 ZIP 内、清单一致、可登记 | pass |
| D-14 | 不完整包：清单一致但不可登记为完整、无嵌套 | pass |
| D-15 | HTTP 下载 | not_run（未启动服务/浏览器） |
| D-16 | 图面不称净宽、近方标未验证 | pass |
| D-17 | 成果清单/包内模型/请求/运行记录同一对摘要 | pass |

无渲染独立复跑（`--no-render`，证据 `var/evidence/roadmap/W3-trust-remediation/no-render/`）：**14 pass / 0 fail / 3 not_run**（D-12 渲染、D-13 完整包、D-15 HTTP）。D-14 与 D-17 在不完整包上照常执行并通过，未因缺少 render 被放过。

## C. 负向用例覆盖的失败码

`OBSERVATION_FORGED`、`PARENT_UNREGISTERED`、`RUN_ID_NOT_IN_LEDGER`、`RUN_RECORD_NOT_REAL`、`PERSISTED_ENTRANCE_MISMATCH`、`PERSISTED_SNAPSHOT_MISMATCH`、`PERSISTED_BASEMAP_MISMATCH`、`SNAPSHOT_SHA_MISMATCH`、`SNAPSHOT_DATA_MISMATCH`、`LEGACY_RECT_NOT_REVERSIBLE`、`GEOMETRY_PROJECTION_INCONSISTENT`、`UNSUPPORTED_SCHEMA_VERSION`、`ADMISSION_NOT_VALIDATED`、`REAL_MODEL_REQUIRES_V2`。

其中 `PERSISTED_SNAPSHOT_MISMATCH`/`PERSISTED_BASEMAP_MISMATCH`/`SNAPSHOT_DATA_MISMATCH`/`LEGACY_RECT_NOT_REVERSIBLE` 由 D-11 与投影一致性实现路径覆盖，未单独计为独立检查项；若复核要求逐码单列，下一批补成独立用例。
