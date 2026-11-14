# W1 统一模型适配 · 正负例与预期-实际对照

所有条目都是 `scripts/verify_w1_unified_model.py` 的**实际 HTTP 执行**结果
（`after/checks.json`，22/22 `observed_pass`），浏览器条目来自
`scripts/verify_w1_browser.cjs`（`browser/verification.json`，`passed=true`）。

环境：隔离 `app.sqlite3` + 隔离 `studio.db`，端口由系统分配；源提案为**明确标记的本地夹具**
`arc_first_batch_stub.valid_proposal("A"/"B")`，经 Studio 的 `validate_proposal()` 装配成 draft
并作为 `valid_candidate` 产物落库；0 外部调用、0 密钥、0 费用。

## A. 正例

| 编号 | 输入 / 动作 | 预期 | 实际 |
| --- | --- | --- | --- |
| W1-01 | `GET .../studio-sources` | 显式映射 + 至少 2 份 Studio 有效候选 | 200；`ningbo-xiecheng → project_ningbo_xiecheng_2026`；2 份来源 |
| W1-02 | `POST .../import-studio`（布局 A，含 5 点非矩形 ZA1） | 产生主系统候选 v1，精确多边形保留，采用指针不变 | 200；`reused=false`、v1、parent null；6 个分区，ZA1 为 5 点；45 行 field ledger；6 项命名缺项；`adoption_unchanged=true` |
| W1-03 | `GET .../design-options` + SVG 下载 | API/存储/图面字节一致；`adoptions` 表为空 | 200；导入候选出现在正常候选列表；SVG 含 `<polygon>`，下载 sha == 存储 sha；`adoption=null`，adoptions 行数 0 |
| W1-04 | 布局 B 走同一适配器 | 不同 `option_id`、不同结构签名、不同入口多边形 | A/B `option_id` 不同；`structure_signature` 不同；`ZA1.polygon_mm != ZB1.polygon_mm` |
| W1-05 | 重复导入同一来源（相同 artifact id + sha） | 幂等，不造版本 | `reused=true`；导入前后 4 张候选表行数完全不变 |
| W1-06 | 修改 ZA1 多边形与 F3.rot 后生成新的 Studio 产物再导入 | 新版本、父版本指向旧版、同对象 diff 可追踪、旧字节保留 | v2，`parent_revision_id` = v1 的 `option_revision_id`；diff 含 `ZA1.polygon_mm` 与 `F3.rot`；v1 详情仍可 GET |
| W1-10 | 源提案缺少天花灯具点位（负例数据，正例行为） | 材料/灯具不静默丢失，作为命名缺项保留 | 200；`unsupported_items` 含「天花灯具点位」「材料规格/产品选型」 |
| W1-15 | 新建主系统仓储连接 + 新 Studio 连接（重启） | 导入版本、来源、字节、采用状态保持 | 两侧 revision id 列表一致；`adoption=null` |
| W1-16 | A/B 逐字段对账（不是计数或哈希） | 坐标/单位/对象 ID/来源/父版本/材料与视图缺项逐值相等或显式标注 | A、B 各 33 行 `all_equal=true`；各 1 个非矩形分区；各 45 行 ledger |
| W1-17 | 保存源/目标模型样本 | 文件存在且标注为本地夹具 | `models/` 下 6 份 JSON，`source_kind=labelled_local_fixture_not_real_AI` |
| W1-19 | 旧合成候选通道生成 + 旧 SVG 下载 | 旧格式与历史下载不被新导入破坏 | 2 个旧候选、SVG 可读；导入集合仍在；adoptions 0 行 |
| 浏览器 | 页面选源 → 点导入 → 查看目标模型与字段对账 | API/页面/存储版本一致、缺项可见、390px 无溢出 | `passed=true`；导入前 0/后 1；45 行对账可见；SVG 5523 字节且 sha 一致；`page_errors=[]` |

## B. 负例（每条都检查"没有半写入"）

| 编号 | 输入 | 预期 | 实际 |
| --- | --- | --- | --- |
| W1-07 | `expected_unit="m"` | 单位错配，不猜测换算 | 422 `UNIT_MISMATCH`；行数不变 |
| W1-08 | 家具 `catalog_id="ghost-item"`（注入的损坏源） | 缺失对象引用，不静默丢弃 | 422 `UNKNOWN_CATALOG_REF`；行数不变 |
| W1-09 | 分区多边形只有 2 个点 | 不能静默矩形化 | 422 `UNSUPPORTED_GEOMETRY`；行数不变 |
| W1-11a | 请求 `source_project_id` 与 URL 项目不一致 | 错误项目映射拒绝 | 409 `PROJECT_MAPPING_MISMATCH` |
| W1-11b | 另一 Studio 项目（映射到别的主系统项目）的产物 | 跨项目不串用 | 409 `PROJECT_MAPPING_MISMATCH` |
| W1-11c | `expected_source_sha256` 与源字节不符 | 来源已变，需重新确认 | 409 `SOURCE_SHA_MISMATCH` |
| W1-11d | `invalid_raw` 产物 | 非有效候选不能导入 | 422 `NOT_VALID_STUDIO_CANDIDATE` |
| W1-12 | 汇总上述失败 | 除 W1-10 的正例外不产生新版本 | `ai_design_option_revisions` 只 +1（来自 W1-10）；其余表无变化 |
| W1-13 | 对 v2 的 `option_id` 用 `expected_revision=1` 采用 | 旧版本并发采用被 CAS 拒绝 | 409 `STALE_OPTION_REVISION`；adoptions 表仍 0 行 |
| W1-14 | 在写 SVG 之后、事务提交之前注入异常 | 单事务回滚 + SVG 清理 + 采用不变 | 抛错；4 张表行数前后一致；SVG 文件数前后一致；adoptions 0 行 |
| W1-18 | 在另一个主系统项目查 `studio-imports` | 跨项目隔离 | 200 且 `items=[]` |

## C. 预期-实际差异与修正记录（如实）

1. **W1-07 第一次失败**：`expected_unit="m"` 的请求因为幂等键不含单位而命中"已导入"复用路径，
   返回 200。没有放宽断言，而是把单位守卫前移到幂等查找之前（语义上单位校验本就应早于复用）。
2. **W1-14 第一次失败**：回滚用例用了已导入过的源，同样命中复用路径，故障接缝没被调用。
   改为新建一份未导入过的 Studio 产物再注入失败，才真正走到"写文件后、提交前"。
3. **负例夹具构造**：Studio 自身的 `validate_proposal()` 会在入库前拒绝未知目录或非法多边形，
   所以 W1-08/09/10 用 `mutated_plan()` 在**已校验 draft 的副本**上注入损坏数据并写入隔离 Studio 库，
   用于测适配器本身的拒绝能力；这一点在脚本注释和本文件里都明确标注，没有伪装成 Studio 正常产物。
4. **OpenAPI 差异**：第一版用 `json.dumps` 重排了整个文件（1165 行 diff）；已恢复原文件，
   改为按原排版插入 4 个 operation（16 行），避免无关差异。

## D. 未覆盖 / 证据待审

- PG 仓储路径、正式切库、NAS/账号/备份专项：本批未验证（按委托只验证本批触及的隔离 SQLite 路径）。
- 真实模型（非桩）生成的设计候选：未调用，未计入 AD01—AD08。
- 任意 CAD/BIM、任意非矩形曲面/多层几何：只支持 `spatial-plan-draft.v1` 的二维多边形。
- 适配中途失败用的是**显式故障接缝**（服务方法 `on_before_commit`），不是随机崩溃注入；
  它证明单事务与文件清理逻辑，不宣称覆盖所有崩溃/断电场景。
