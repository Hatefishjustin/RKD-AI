# W2 收口整改复核包（W2-R1 / R2 / R3）

- 批次：W2-收口整改（架构复核 `W2-architect-review/review-and-next-batch.md` 的限定整改）
- 审查基线：`b1f1747`（业务提交 `40049fd`）
- 本批结论口径：R1—R3 工程收口；**不等同 W2 放行、不进入 W3/W4、不改 AD01—AD08、不代替用户阶段确认**
- 编制时间：2026-11-14（北京时间）；证据目录 `var/evidence/roadmap/W2-收口整改/`

## 1. 架构意见 → 本批落实

| 架构要求 | 位置 | 本批做法 | 状态 |
| --- | --- | --- | --- |
| R1 同一文件集合生成登记、manifest 与 ZIP；有渲染必须打包 PNG | `ai_spatial_outputs.finalize_package` | 文件集 →（清单 + ZIP）一个来源；打包后重新解压逐项比对，自检不过直接失败不登记 | 已改 |
| R1 无渲染不得声明 PNG | 同上 | 清单完全由真实文件集重建，render=false 时不存在任何 PNG 条目 | 已改 |
| R1 下载前校验清单登记 SHA | `ai_spatial_output_service.file` | 读取 `manifest.json` 前先比对登记 SHA，不符返回 `MANIFEST_HASH_MISMATCH` | 已改 |
| R1 完成后再原子登记 | `_run` | 全部字节在内存生成 → 写盘 → 单事务写修订+成果+终态；失败/取消不登记 | 已改 |
| R2 候选预览 vs 当前采用版本 | `_binding_facts`、`status()` | 冻结提交时的采用版本事实；查询按**当前**采用版本判定 `current_adopted / historical_preview / candidate_preview` | 已改 |
| R2 按 job/修订查询、保留历史 | `status(job_id, production_revision_id)`、`revisions[]` | 不再「最新任务 + 全局最新成功成果再比 job_id」；返回全部本批修订并逐个带绑定状态 | 已改 |
| R2 取消为单调终态 | `cancel()`、`touch_job`、`close_job` | 阶段更新与终态写均带 `status` 条件；取消后晚到渲染丢弃、不登记 | 已改 |
| R2 失败不登记半份成果、显式重试关联原任务 | `_fail`、`retry()` | 失败只写终态；重试需显式调用，新任务 `config.retry_of` 指原任务，同幂等键不重跑 | 已改 |
| R2 只恢复本批中断任务 | `recover()` | 只扫 `config.kind=spatial_outputs` 且进程内非活跃的任务，标 `WORKER_RESTARTED` | 已改 |
| R3 几何量 ≠ 完成面工程量 | `measure()` | `Q-FLOOR-GEOMETRIC-NET`（know​n，标 `geometric_only_not_a_finish_quantity`）+ `Q-FLOOR-FINISH`（无依据时 unknown） | 已改 |
| R3 真正独立扣除复算 | `scanline_area` / `scanline_area_minus` | 竖条带区间并/差，只用原始顶点，不复用 Shapely `deducted`；差值单独给出 | 已改 |
| R3 材料面切片来源化 | `normalize_finish_scope` | 铺装范围 + 材料引用 + 计量单位 + 扣除依据 + 来源人/说明；才可进入 `Q-FLOOR-FINISH` | 已改 |
| R3 成本口径一致 | `build_cost` / `cost_html` | 金额必须同时有面积依据与显式假设单价；页面不再写「本页没有金额」却又列金额 | 已改 |
| R3 CSV/HTML/页面对齐 | `_quantity_csv`、`cost_html`、`AiSpatialOutputsPanel` | 三处使用同一 `quantity_id` 与同一 unknown 理由 | 已改 |
| 只改必要代码、不另建管理平台 | 全批 | 无新表、无迁移、无新服务；复用 `ai_development_*` 三表 | 遵守 |

## 2. 逐项结果（先复现、后修复，同一负例）

同一脚本 `scripts/w2_closeout_repro.py` 对整改前后各跑一次（隔离 SQLite + 真实 HTTP；
渲染用可控渲染桩，不用 sleep 碰运气）：

| 编号 | 负例 | 整改前 | 整改后 |
| --- | --- | --- | --- |
| W2C-R1-01 | 同一文件集 → 清单与 ZIP 完全对应 | fail（ZIP 无 render.png） | pass |
| W2C-R1-02 | render=false 不声明 PNG | pass（原本就无 PNG） | pass |
| W2C-R1-03 | 真实 HTTP 下载 ZIP→空目录解压→逐项核对 | fail（清单有 render.png，ZIP 无） | pass |
| W2C-R1-04 | 真实入口 render=false 无 PNG | pass | pass |
| W2C-R1-05 | 渲染无产出不得成功 | pass | pass |
| W2C-R1-06 | 清单被改动后拒绝据其交付 | fail（直接信任清单） | pass |
| W2C-R2-01 | 生成中取消 + 晚到渲染 | fail（无取消入口，任务变 succeeded） | pass |
| W2C-R2-02 | 换版后旧成果标历史预览 | fail（历史不可见） | pass |
| W2C-R2-03 | 失败后显式重试 | fail（无重试入口） | pass |
| W2C-R2-04 | 共用表不串页 | fail（本页成果被挤掉） | pass |
| W2C-R2-05 | A/B 反序完成 + 重启恢复 | fail（无恢复语义） | pass |
| W2C-R3-01 | L 形手算 24/22 + 独立复算路径 | fail（名为"地坪完成面净面积"，复算复用主算法扣除） | pass |
| W2C-R3-02 | 相交/外置/跨界扣除 | pass（Shapely 交集本已正确） | pass |
| W2C-R3-03 | 材料面切片需来源、单价不掩盖未知范围 | fail（无材料面概念，单价可套在未知面积上） | pass |
| W2C-R3-04 | 真实入口冻结材料面+单价并同页对账 | fail | pass |

合计：**整改前 4 pass / 11 fail → 整改后 15 / 15**。
原始记录：`var/evidence/roadmap/W2-收口整改/repro-before.json`、`repro-after.json`。

W2C-R3-02 在整改前也通过——这一点如实列出：旧的 Shapely 交集本身没有算错，
R3 的真实缺陷是**语义**（几何量被叫成完成面工程量）和**伪独立复算**（复算复用了同一个扣除值）。

## 3. 真实渲染与页面

- `scripts/verify_w2_spatial_outputs.py`（真实 Blender 4.2.9 Cycles CPU，两种布局各渲一次）：
  **7/7 observed_pass**，证据 `var/evidence/roadmap/W2-收口整改/after-w2-script/checks.json`。
  其中 W2-02 已按架构要求加强为「下载 ZIP → 空临时目录解压 → 逐项核对清单 sha/大小，
  PNG 与单独下载一致」。
- 真实浏览器（Edge，隔离库）：见 `var/evidence/roadmap/W2-收口整改/browser/verification.json`。
- 全量单测 **262 tests / 0 failures / 0 errors**（43 个模块）：`runtime/full-unittest.log`。
  入口说明：`mvp/tests` 没有 `__init__.py`，`unittest discover -s mvp/tests -t .` 会报
  "Start directory is not importable"，而 `-s mvp/tests`（顶层压到 tests）又会让
  `test_review_tasks.py` 的 `from mvp.tests import ...` 失败。最终用逐模块加载
  （`var/tmp/run_full_unittest.py`，等价全量）：
  `PYTHONPATH=".;mvp" .venv/Scripts/python.exe -B var/tmp/run_full_unittest.py`。
  这是**测试收集方式**问题，不是本批代码缺陷——`mvp/tests/test_review_tasks.py` 本批未改动
  （最后修改于 `ed6e32f`）。
- 前端 `tsc --noEmit` EXIT=0、`npm run build` EXIT=0：`runtime/frontend-build.log`。

## 4. 未做 / 未测（如实）

1. **没有新增付费模型调用**：全批 0 次外部请求、0 密钥、0 费用、0 外发图片。
2. **PG 路径未验证**：R2 的条件更新用 SQLite 的 `UPDATE ... WHERE status=?`；PostgreSQL 仓储共用同一
   `_DevelopmentTransaction`，但本批只在 SQLite 隔离库实测。
3. **多进程并发未验证**：取消/重试/恢复按单进程多线程 + 数据库条件更新设计；跨进程竞态未测。
4. **产物种类仍受既有 CHECK 约束**：`ai_development_artifacts.artifact_kind` 白名单里没有
   `render_png`，因此 `render.png` 没有独立成果行，只登记在 `manifest.json`（其自身 SHA 由
   `manifest_json` 成果行锚定）并打进 ZIP。若要把 PNG 做成独立成果行，需要新迁移，
   本批按「不另建管理平台/不加迁移」的边界选择前者，并在此披露。
5. **R4 表达质量未动**：平面仍是概念分区图，人眼图仍是灰盒内部试验级。
6. **材料面切片是人工/夹具输入**：`Q-FLOOR-FINISH` 的面积来源明确标为
   `executor_manual_fixture`、`site_verified=false`，不是现场实测，也不是 AI 生成。

## 5. 图面差距（R4，仍然存在）

- 平面：分区为多边形但仍无墙厚/门窗/柱网/洁具/隔断构造，尺寸链只到总尺寸与分区外包尺寸。
- 人眼图：色块地面、统一灰盒家具、无真实材质纹理/软装/绿植/人物，属内部试验级。
- 结论：**当前图面不是客户交付成果**，不得对外称设计成果；R4 仍在 W2 内推进。

## 6. 下一步（建议）

按架构复核结论决定是否继续 R4（同源表达质量），顺序建议：
墙体/门窗/柱网的真实几何与尺寸链 → 材质纹理与资产复用 → 灯光层次 → 一张可辨认功能组织的人眼图。
不进入 W3/W4，不重跑付费模型，不改 AD 判定。
