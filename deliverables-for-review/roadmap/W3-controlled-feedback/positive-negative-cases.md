# 正例与负例（受控反馈修订）

全部经真实 `ApiService` 公共 API + 隔离 SQLite + 本地协议桩（`fixture`/`simulated=true`），无手工插入记录。

## 正例

| # | 场景 | 断言 |
| --- | --- | --- |
| P1 | 父版 v2 候选 + 自然语言反馈 + locks | 新 `revision_no=2`；`parent_revision_id` 为用户指定父版；新 `run_id`；run 的 request/response 摘要来自本次桩交换；`input_hash` 绑定父/反馈/locks/项目输入/采用版本；site snapshot 与父版一致；父版模型字节不变；新 admission 独立且 `adoptable=true`；提交后父链登记摘要 = provenance 摘要；run 的 `parent_candidate_sha256` = 父版 provenance 摘要；查询与 SVG 下载字节可见 |
| P2 | 反馈 locks 保留 | 新 v2 记录 `feedback.locks` 与请求一致 |
| P3 | 采用 CAS | 正确 `expected_version` 可采用；错误版本 `STALE_ADOPTION_VERSION` |

## 负例

| # | 场景 | 拒绝码 |
| --- | --- | --- |
| N1 | 模型改写锁定对象 `zone:display` 形状 | `LOCK_FIELD_MODIFIED` |
| N2 | 模型删除锁定对象 | `LOCK_OBJECT_DELETED`（或 provider 复核失败 `MODEL_REVISION_UNRESOLVED`） |
| N3 | 指定不存在的父修订 | `STALE_PARENT_REVISION` |
| N4 | 过期 `expected_input_hash` | `STALE_INPUT_SNAPSHOT` |
| N5 | 过期 `expected_version` | `STALE_ADOPTION_VERSION` |
| N6 | 过期 `expected_revision` | `STALE_OPTION_REVISION` |
| N7 | 两个并发反馈指向同一父版 | 一个成功、一个 `STALE_OPTION_REVISION`；只新增一条修订 |
| N8 | 非法几何（对象越界/重叠） | `MODEL_REVISION_UNRESOLVED`，不落库 |
| N9 | provider HTTP 500 / 超时 | `PROVIDER_HTTP_500` / `PROVIDER_TIMEOUT`，状态 503，不落库 |
| N10 | 省略 scope / 显式 `None` / 异服务 scope | `TypeError` / `OBSERVATION_SCOPE_REQUIRED` / `OBSERVATION_SCOPE_INVALID` |
| N11 | 模型调用期间采用基线被并发改写，写事务前失败 | `STALE_ADOPTION_VERSION`；账本父链登记集合不变（无幽灵父链） |
| N12 | 反馈未解析或 locks 丢失 | `FEEDBACK_UNPARSED` / `FEEDBACK_LOCKS_MISMATCH` |
| N13 | 采用 CAS 冲突 | `STALE_ADOPTION_VERSION` |
| N14 | 父候选内容在写前被改 | `PARENT_CONTENT_CHANGED`（CAS 内二次核对） |

## 不成立的「通过」

- `succeeded`/`adoptable=true` 只表示工程链和准入党通过；桩来源 `fixture`、`simulated=true`，不计 AD01—AD08。
- `revision_no=2` 不等于设计变好；本批没有真实用户评价。
- 不声称 PG 数据面或 HTTP/UI 已验证（not_run）。
