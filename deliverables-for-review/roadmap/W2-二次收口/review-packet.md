# W2 二次收口复核包（W2-C1 / C2 / C3 限定补修）

- 批次：W2-二次收口（架构复核 `W2-closeout-architect/review-and-next.md` 的定点补修）
- 审查基线：`82d2a66`（业务提交 `c4487fa`，上一批复核包提交 `655278a`）
- 本批结论口径：**R1 维持通过（轻量回归，不重开打包架构）；R2/R3 定点补修完成、待复核**
  ——W2 是否放行仍由架构决定；不进入 W3/W4，不改 AD01—AD08，不代替用户阶段确认
- 编制时间：2026-11-15（北京时间）；运行证据 `var/evidence/roadmap/W2-二次收口/`

## 1. 架构三条意见 → 本批落实

| 架构要求 | 位置 | 本批做法 | 状态 |
| --- | --- | --- | --- |
| C1 主量用经验证的精确几何；独立复算补齐边界交点，或明确限定支持几何；两条路径不一致时失败/待核，不继续输出 known 饰面量与金额 | `ai_spatial_outputs.py` `_finish_quantity` / `scanline_*` | 条带断点补齐**边-边交点**（`_event_abscissae`），条带内截面长度恢复线性、中点积分精确；饰面量改用 Shapely 精确并/差为主值，条带只做交叉校验，差值超容差（1e-3 ㎡）→ `known_status="disputed"`、value=null，成本不试算金额（`build_cost` 与 `cost_html` 都有 disputed 分支） | 已改 |
| C1 同批补 finish_scope 入口校验：单位、有限坐标、有效简单多边形、对象 ID、材料引用、扣除口径、同层重叠不得无说明重复相加 | `normalize_finish_scope` | 坐标只收 `mm`、面积只收 `m2`（`m`/`ft2` 拒绝，不做静默换算）；NaN/inf 与 ±1e6 mm 上限；自交/退化多边形拒绝；`object_id` 必须唯一；`deduction_basis` 只收 `keepouts_within_scope/none`；同层（`layer`）重叠无 `overlap_declaration` 直接拒绝，声明后按**并集**计量不重复相加 | 已改 |
| C2 恢复只识别上一实例遗留；status 普通读取不得靠"暂不在 _active"判定重启 | `recover()` | 任务创建时持久化 `config.run_instance`（进程实例标记）；恢复只回收 `run_instance ≠ 当前实例` 的 queued/running；`_active` 不再参与判定。取消/晚到渲染/显式重试语义不变 | 已改 |
| C2 验收：屏障 + 真实 HTTP；取消同窗口仍生效不复活；真遗留标中断可重试；不波及其他类型 | `w2_second_closeout_repro.py` | 见 `c2-race-evidence.md`（确定性接缝替换 `_launch`，不 sleep） | 已改 |
| C3 指定 job_id 只返回自己的 revision/artifacts；未完成/失败为空；按修订反查对应 job；两参数冲突拒绝；不从全局最新 50 条找显式 ID；列表先过滤类型后分页 | `status()` + 仓储 | 主键直查（`job()` / `revision()` / `revisions_by_job()`），显式查询**不回退**；类型/度量族过滤下沉 SQL（Postgres `config->>'kind'`、`measurement_version LIKE`）；无参数概览保留 `last_successful` 且 `revision_source` 明确标注；面板加 `spatial-previous-output` 提示 | 已改 |
| 只修 C1—C3，不重做 W1/R1，不增加管理平台 | 全批 | 5 个文件 +1100/−99，零迁移、零新表、无新服务；R1 打包路径未动 | 遵守 |

## 2. 先复现、后修复，同一负例（`scripts/w2_second_closeout_repro.py`，15 条）

| 编号 | 负例/正例 | 整改前（82d2a66） | 整改后 |
| --- | --- | --- | --- |
| W2C2-C1-01 | 三角形 18 扣 4.5：主量/独立/饰面 13.5、金额 13500 | fail（12.0 / 12 000 元） | pass（13.5 / 13 500 元） |
| W2C2-C1-02 | 扣除区斜穿斜边：净 17.405 | fail | pass |
| W2C2-C1-03 | 矩形/L 形回归 24/22 | pass（保护用例） | pass |
| W2C2-C1-04 | 单位契约：`m` / `ft2` / 未知扣除口径拒绝 | fail（照毫米算，12.0 known） | pass |
| W2C2-C1-05 | 自交 / NaN / 重复 object_id / 退化拒绝 | fail | pass |
| W2C2-C1-06 | 同层重叠：无声明拒绝；声明后按并集 22 而非 24 | fail（静默 24 相加） | pass |
| W2C2-C1-07 | 真实入口（架构口径）：13.5 ㎡ / 13 500 元，CSV/HTML/清单一致 | pass（保留区恰好覆盖整段条带，误差为 0 的巧合；见 c1-handcheck §2.1） | pass |
| W2C2-C1-08 | 真实入口（判别性）：竖直带内截断 → 9.4224 ㎡ / 9 422 元 | fail（10.842 ㎡ / 10 842 元） | pass |
| W2C2-C2-01 | 提交后/启动前状态查询不得终结正常任务 | fail（in-gap `failed/WORKER_RESTARTED`） | pass（`queued` → `succeeded`） |
| W2C2-C2-02 | 同一窗口取消生效、不复活、可显式重试 | fail | pass |
| W2C2-C2-03 | 真遗留标中断；本实例在跑不误杀；其他类型不动 | pass（保护用例） | pass |
| W2C2-C3-01 | 显式查失败任务只返回自己 | fail（借用任务 A 的 revision+6 个文件） | pass（revision=null、artifacts=[]） |
| W2C2-C3-02 | 按修订 ID 反查对应 job | fail（返回"最新任务"） | pass |
| W2C2-C3-03 | 两参数同时给 → 拒绝 | fail（200） | pass（400 `AMBIGUOUS_QUERY`） |
| W2C2-C3-04 | 55 条历史后按 ID 命中 | fail（404） | pass（200，返回自己的成果） |

合计：**整改前 3 pass / 12 fail → 整改后 15 / 15**。
三个"整改前也通过"的用例如实标注：两个是保护性回归（矩形几何、恢复范围），
一个（C1-07）在该几何下旧算法误差恰为 0——所以另造了判别性的 C1-08。

## 3. 回归与真实链路

- **原 15 项**（上一批 `w2_closeout_repro.py`，含 R1 打包 6 项、取消/晚到/幂等/共用表/重启）：
  **15/15 通过**（`regression-15-repro-after.json`）。R1 结论维持，打包架构未重开。
- **真实 Blender 4.2.9 Cycles**（两种布局各渲一次）：**7/7 observed_pass**，
  `runtime/real-blender-checks.json`。
- **真实 Edge 浏览器**：`passed=true`，`page_errors=[]`，390px 无横向溢出，
  生成器版本 `rkd-spatial-outputs.v3`；下载字节与登记 SHA 一致（`browser/verification.json`）。
- **全量单测** 262 tests / 0 fail / 0 error（43 模块，逐模块加载入口，
  `runtime/full-unittest.log`）；前端 `tsc --noEmit` 与 `npm run build` EXIT=0。
- 唯一状态表 `PROJECT_STATUS.md` 已更新：**R1 通过、R2/R3 待复核，AD01—AD08 不变**。

## 4. 未做 / 未测（如实）

1. **多进程双活**：恢复按持久化实例标记判定，两个同时存活的实例仍会互相误判；
   原实现同样不能区分，本批不宣称解决，需要真实租约时另立工作项。
2. **PG 路径未实测**：类型过滤的 SQL 下沉写了 Postgres 分支（`config->>'kind'`），
   但本批只在 SQLite 隔离库跑过。
3. **`render.png` 仍不占独立成果行**：沿用上一批已复核接受的取舍（CHECK 白名单），
   只进清单与 ZIP，架构已认可，无需迁移。
4. **R4 表达质量未动**（架构已确认 C1—C3 之后的顺序）。
5. **本批修过一次自己的解析期望值**：第一版手算工具漏了一个断点（详见 `c1-handcheck.md` §5），
   把 9.4224 误算成 11.1124，一度把整改后判 FAIL；补齐断点后四个解析值与实现全部吻合。
   被测代码没有因此改动。

## 5. 仍然不像设计公司成果的地方（R4 待做）

- 平面：仍是概念分区图，无墙厚、门窗、柱网、洁具、隔断构造；尺寸链只到总尺寸与分区外包。
- 人眼图（本批真实渲染，已目检）：色块地面、灰盒/米色盒体家具、两个点光源，
  **无真实材质纹理、无门窗洞口、无软装绿植人物、无灯光层次** —— 内部试验级，
  不是客户可交付的图。
- 材料面切片是人工/夹具输入（`declared_by` 明确标注，`site_verified=false`），不是 AI 生成，
  不计入任何设计验收。
- 结论：本批只证明计量与任务生命周期是**对的**，不证明设计**成立**；
  AD01—AD08 与用户阶段确认不变，W3/W4 未启动。

## 6. 外部费用与图片

外部请求 0、密钥 0、外发 0、费用 ¥0。本批新增图片：
2 张本地 Blender 渲染（真实链路 layout-A/B 各 1，另有浏览器跑批 1 张，共 3 张本地渲染）
+ 2 张浏览器截图（桌面 / 390px）。无生成式图像调用。

## 7. 文件索引

- `index.html` — 离线评审入口（前后对照表、真实图面、证据文件）
- `c1-handcheck.md` — 解析手算全部期望值与推导（含断点修正记录）
- `c2-race-evidence.md` — 确定性接缝、前后数值、恢复语义
- `c3-id-and-history.md` — 按 ID 语义与 >50 条历史
- `checks.json` — 15 项前后对照 + 回归/真实链路汇总 + 包内文件 SHA
- `architect-boundary-before.py` / `boundary-results-before.json` — 架构脚本逐字副本与其在
  未改代码上的复跑结果（与架构自带 `boundary-results.json` 三项事实一致）
- `outputs/finish-13.5/`、`outputs/finish-band-9.4224/` — 两个真实入口成果包
  （plan.svg、quantity.csv/json、cost.html、manifest.json、package.zip、cases.json）
- `browser/` — 真实浏览器验证 JSON 与截图；`runtime/` — 单测/前端/真实 Blender 日志
- `code-diff.md` / `changes.patch` — 改动范围与可定位补丁（基线 `82d2a66`）
- `manifest.json` — 源码基线、提交号、包内字节与 SHA
