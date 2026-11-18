# W3 来源记录小范围收尾复核包：invocation scope 必填

基线提交：`9dca78bc0166a696e71bf65eddf8c665eb3436e4`（上一批来源记录整改交付）。
本轮代码提交：见 `commit-reference.md`（提交后生成，避免写死易变 HEAD）。
范围：只把 `ControlledRunService.issue()` 与 `ControlledDesignRuntime.register_and_issue()` 的 `scope` 从可选改为**必填**，并补齐调用点、测试桩与负例。

**这不是设计批准、不是客户成果、不放行真实模型试验、不推进阶段 2/3 或 W4，不改 AD01—AD08、阶段确认、数据库/NAS/管理配套范围。**

旧包 `W3-r1r2-source-records/`、`W3-astra-r1-composition/`、`W3-astra-remediation/` 等及证据只读保留，一字未改；底图原件未改。本批新证据写入 `var/evidence/roadmap/W3-r1r2-scope-required/`。

## 1. 改动

| 位置 | 改动 |
| --- | --- |
| `mvp/rkd_mvp/controlled_run_ledger.py` | `issue(..., scope: ObservationScope)` 改为**无默认值的必填关键字参数**；显式 `scope=None` → `OBSERVATION_SCOPE_REQUIRED`；非本服务 `begin_invocation` 产生的句柄 → `OBSERVATION_SCOPE_INVALID`；原 `if scope is not None:` 归属校验改为无条件执行 |
| `mvp/rkd_mvp/controlled_design_runtime.py` | `register_and_issue(..., scope: Any)` 改为必填；显式 `None` → `OBSERVATION_SCOPE_REQUIRED`；仍把 scope 透传给 `issue()` |
| `scripts/w3_astra_findings.py` | 当前代码分支改用 `begin_invocation()` 产生 scope 并透传给 `issue()`；冻结基线分支保持原行为 |

**行为变化**：以前只带一个「本 ledger 见过的观测」就能签发（scope 可选，缺失时只做 observation 归属检查）；现在调用方遗漏 scope 会在**调用边界**被 Python 拒绝（`TypeError: missing required keyword-only argument: 'scope'`），显式传 `None` 被以稳定错误码拒绝，不退回旧行为。

## 2. 全部调用点与测试桩检查

| 调用点 | 处理 |
| --- | --- |
| `mvp/rkd_mvp/ai_design_option_service.py:228` | 生产路径，已通过 `scope=scope`；`_run_set` 每次 provider 调用前建 scope（`:332`），未受影响 |
| `mvp/rkd_mvp/controlled_design_runtime.py:118` | 透传 scope，已必填 |
| `mvp/tests/test_w3_r1r2_source_records.py` | 所有正例已带 scope；新增省略/None/异服务 scope 三类负例 |
| `scripts/w3_r1r2_findings.py:328,455` | 能力探测分支：当前树带 scope，冻结基线仍按旧签名调用（保持 before 可比性） |
| `scripts/w3_astra_findings.py:167` | **本轮修正**：当前树改走 `begin_invocation()` 并传 scope；冻结基线分支不变 |
| `scripts/w3_trust_findings.py:304,435,444`、`scripts/verify_w3_trust_remediation.py:243,321` | 旧版 before-only harness：使用已关闭的 `observe_exchange` / 旧 `ControlledRunLedger`，在当前树上根本走不到 `issue()`（实测在 `OBSERVE_EXCHANGE_CLOSED` 处终止）；本轮不改其基线语义，留作历史证据工具 |

全仓语法编译检查通过（`py_compile`：3 个生产模块 + 2 个测试/harness + 3 个历史 harness）。

## 3. 前后同例实测

harness：`scripts/w3_scope_required_findings.py`（真实 ApiService 组合根 + 真实隔离 SQLite + 本地协议桩）。基线用 `git archive 9dca78b mvp contracts scripts fixtures …` 冻结到 `var/evidence/roadmap/W3-r1r2-scope-required/before/`。

| 调用 | before（`9dca78b`，scope 可选） | after（本批，scope 必填） |
| --- | --- | --- |
| `runtime.register_and_issue(...)`（省略 scope） | **accepted** | `TypeError` |
| `runtime.register_and_issue(..., scope=None)` | **accepted** | `OBSERVATION_SCOPE_REQUIRED` |
| `run_service.issue(...)`（省略 scope） | **accepted** | `TypeError` |
| `run_service.issue(..., scope=None)` | **accepted** | `OBSERVATION_SCOPE_REQUIRED` |
| 另一个服务实例的 scope | `OBSERVATION_NOT_FROM_INVOCATION` | `OBSERVATION_SCOPE_INVALID` |
| 真实 ApiService 组合根 submit→adopt | 通过 | 通过（`product_path_also_passes=true`） |

原始 JSON：`outputs/findings-before.json`、`outputs/findings-after.json`（`external_calls=0`、`cost_cny=0`、`keys_used=false`）。
退出码即断言：before `--expect vulnerable` → vulnerable、退出 0；after `--expect fixed` → fixed 且产品路径通过、退出 0。

## 4. 测试

- 新增永久负例 `test_issuance_rejects_omitted_or_null_scope`（`mvp/tests/test_w3_r1r2_source_records.py`）：省略 scope → `TypeError`（两个 API）、显式 `None` → `OBSERVATION_SCOPE_REQUIRED`（两个 API）、异服务 scope → `OBSERVATION_SCOPE_INVALID`、带正确 scope 的正例仍能签发；并断言被拒调用没有留下任何登记。
- 来源记录 `test_w3_r1r2_source_records.py`：**5/5 OK**（原 4 项 + 新增 1 项）
- 组合根 `test_w3_composition_root.py`：**7/7 OK**（真实 `ApiService` 组合根路径继续通过）
- `test_ai_design_options.py`：**8/8 OK**
- `test_w3_astra_remediation.py`：**4/4 OK**
- 历史 harness `scripts/w3_astra_findings.py --expect fixed`：**5/5 fixed**（已更新调用点）
- 全量单测：**278/278 OK**（上一批 277 + 本轮新增 1；日志 `var/evidence/roadmap/W3-r1r2-scope-required/after/full-regression.log`）

## 5. 残余限制 / 未运行

- **兼容性**：`scope` 现在是破坏性签名变更，任何仓外调用方（若有）必须显式传 scope；仓内已全部检查更新。
- **错误形态**：省略参数由 Python 抛 `TypeError`（无领域码）；显式 `None` 才有 `OBSERVATION_SCOPE_REQUIRED`。若要求所有遗漏形态统一为领域错误码，需要改成「默认值 `None` + 运行时校验」而非签名必填，待复核裁定。
- **not_run**：HTTP 进程级下载、浏览器 UI、PG 数据面、真实模型调用（0 授权/0 费用/0 密钥）、正式采用/发布、跨机验签、专业签核。
- 全部候选来源 `fixture`、`simulated=True`，不计 AD01—AD08，不是 AI 自动设计或客户成果。

## 6. 没有做什么

- 未改准入判定、场地快照、适配几何、交付完整性、组合根接线方式。
- 未改数据库 schema/迁移、NAS、账号、KMS、W4；未调外部模型。
- 未改 AD01—AD08、阶段确认、未知项与正式责任边界；旧复核包与底图原件未覆盖。
