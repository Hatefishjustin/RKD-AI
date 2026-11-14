# ARC 首批代码差异索引（基线 `d6501a9`）

**完整、未截断的差异请看同目录 `changes.patch`**（标准 git 差异，6455 行，含全部新增文件全文）。它是相对基线 `d6501a9` 的差异**快照记录**，不是待应用到当前工作区的补丁；如需机械校验，可在干净的基线检出副本上执行 `git apply --check changes.patch`。本文件只做变更索引与复核导航，不重复贴代码。

生成方式（在 `D:\Github\RKD AI` 下）：

```bash
git add -N <下列新增文件>
git diff --no-color -- . ':!web/dist' ':!deliverables-for-review' > changes.patch
```

基线 commit：`d6501a9b5b963b0a11a9e148b32eda269f18414b`（A1 收口）。
复核方式：若本批差异已提交，用 `git diff d6501a9..HEAD`；若仍为工作区差异，用 `git diff`。`changes.patch` 保留完整快照，两种状态都可逐段阅读。

## 1. 变更文件清单（20 个）

| 文件 | 类型 | 对应任务 | 复核要点 |
| --- | --- | --- | --- |
| `contracts/v1/spatial-plan-proposal.schema.json` | 新增 | ARC-01 | 模型提案契约；`additionalProperties:false`；不含身份/批准/采用字段；未放宽任何必填项 |
| `mvp/rkd_mvp/studio/validation.py` | 新增 | ARC-01/06 | `validate_proposal` 四级顺序：结构→语义引用→几何→锁定；`_schema_errors` 生成字段路径/期望类型/对象ID/建议；装配后复校 draft 契约；`substantive_difference`、`structural_summary` |
| `mvp/rkd_mvp/studio/geometry.py` | 新增 | ARC-02 | `check_geometry` 复用 shapely 2.1.2；唯一面积口径 `design_scope_sqm`；实际交集/自交/正面积/越界/保留区/入口可达/实测净宽/家具旋转占地；`unsupported` 覆盖声明 |
| `mvp/rkd_mvp/studio/revision.py` | 新增 | ARC-03 | `apply_patch` 白名单与身份字段拒绝；`verify_revision_integrity` 对象保留/删除理由/锁定/逐项 issue 对应；`revision_input_hash` |
| `mvp/rkd_mvp/studio/tools.py` | 修改 | ARC-02 | `check_plan` 改为委托 `geometry.check_geometry`，签名与 `ok/issues/metrics` 结构兼容；旧外接矩形与 width 自报逻辑整体移除 |
| `mvp/rkd_mvp/studio/orchestrator.py` | 修改 | ARC-01/03/04 | 删除 9 处 `[:4000]/[:3500]/[:3000]` 截断；候选四级校验与 `invalid_raw` 留存；评审/修订传基线 ID + 完整对象事实 + issue_id；patch 优先；`MAX_AUTO_REWORK=2` 不变；`SupersededRun` 与 CAS；闸口绑定基线；种子 `ensure_project` |
| `mvp/rkd_mvp/studio/store.py` | 修改 | ARC-04 | 追加列与 `feedback`/`gate_revisions`/`check_reports` 三表；`ensure_project`（insert-only）；`resolve_project_id` 显式映射；`decide_gate` append-only 且重放 `applied=false`；`effective_requirement`；`invalidate_artifacts`；`DB_PATH` 可由 `RKD_STUDIO_DB` 覆盖（仅隔离测试用路径，无密钥） |
| `mvp/rkd_mvp/studio/server.py` | 修改 | ARC-04 | 按映射解析项目、未映射 404；留言与驳回进入版本化反馈；取消在跑任务；决定语义 `allow_continue`/`direction_approval`；`_state` 分 `valid`/`history` 组与 `stage_status`；服务范围标注本机实验、不冒称团队/NAS |
| `mvp/rkd_mvp/studio/llm.py` | 修改 | ARC-06 | `Usage` 增加 `usage_missing_calls`/`pending_reconciliation`/预留与图片计数；`_guard` 同时预留输入+输出；`_reconcile` 缺失 usage 记 unknown；超时记待对账；兼容降级仅对明确不支持错误 |
| `mvp/rkd_mvp/studio/vision.py` | 未改 | — | 只在 orchestrator 提示中补充「图面可见范围声明」，未改发送范围（仍只发自家生成的图 + 冻结人工样板） |
| `knowledge/design-standards/standards.v1.json` | 修改 | ARC-06 | 每条拆 `source`/`scope`/`derived_heuristic`/`professional_basis`/`program_coverage`；「2 处非直角」「60% 天花覆盖」标 `is_pass_criterion=false`；STD-005 只查数据存在、不再要求覆盖率 |
| `fixtures/studio/projects/ningbo-xiecheng.json` | 修改 | ARC-04 | 仅新增 `source_project_id` 与 `id_mapping_note`（Studio 内部 id 与主系统 id 不同，显式映射） |
| `web/src/StudioView.tsx` | 修改 | ARC-04 | 移除 `studioId` 宁波硬编码；未映射项目显示限制提示；反馈列表、决定语义下拉、有效候选/历史分组、阶段状态栏 |
| `scripts/verify_studio_loop.py` | 修改 | 测试 | 旧桩数据违反契约（469㎡ 外框当面积表合计等），换成明确标记的本地模型桩合规数据；12→15 项检查；按 pid 隔离 scratch 库 |
| `scripts/arc_first_batch_stub.py` | 新增 | 测试 | **明确标注的本地模型桩**，非真实 AI、非人工方案；面积表按几何复算 |
| `scripts/arc_first_batch_repro.py` | 新增 | 测试 | `before`/`after` 同脚本复现；只读日常库 `mode=ro`；store 行为用隔离库 |
| `scripts/verify_arc_first_batch.py` | 新增 | 测试 | Q01—Q12 专项验收，产出 `checks.json`/`q-checks.json`；含真实正负例 |
| `scripts/verify_arc_browser.py` / `.cjs` | 新增 | 测试 | 隔离主工作台 + 隔离 Studio 服务 + 本地桩；Playwright 真实点击与截图 |
| `mvp/tests/test_arc_first_batch.py` | 新增 | 测试 | 18 项 unittest 回归护栏，纳入全量 discover |
| `PROJECT_STATUS.md` | 修改 | 状态 | 追加本批实际完成范围，不改 AD01—AD08 结论 |

## 2. 契约修改的语义与兼容说明（架构师重点）

- **新增** `spatial-plan-proposal.v1`：语义是「模型可以提交什么」。明确排除 `contract_version`/`project_id`/`option_id`/`revision`/`parent_revision`/`author` 等身份字段，以及 `status`/`approved`/`adopt_pointer`/`decision`/`published` 等批准与采用指针。`additionalProperties:false`，必填项一个没删。
- **原 `spatial-plan-draft.schema.json` 完全未改**：程序注入身份元数据后，再用原契约复校装配结果，旧成果解析保持兼容；模型回显的身份字段一律剥离、不采信，决定字段直接拒绝。
- 未通过补造未知字段消除错误：注入的是程序按版本链已知的元数据，不是设计推断值；`unknown` 仍为 unknown。
- 面积口径修改理由见 `geometry.py` 模块注释与 `ARC-05-adaptation-note.md`：旧口径把外框面积当计价面积、补「通道及其他」后又与功能区轮廓和自相矛盾；新口径为 `site_area − reserved_area`，未分配部分真实计算并显式显示。

## 3. 复核导航

1. 先看 `changes.patch` 中 `validation.py::validate_proposal`、`geometry.py::check_geometry`、`store.py::decide_gate`、`orchestrator.py::_scenario` 四段。
2. 抽查 `before-reproduction.json` 的失败样本，与 `after-reproduction.json` 逐项对比。
3. 看 `q-checks.json` 的 `cases`（21 个正负例）与 `checks.json` 的 `checks`（Q01—Q12 结果）。
4. 看 `browser-observations.json` 与 `browser-screenshots/*.png`。
5. 结论只报「可进入下一委托 / 需整改 / 证据不足」，不代替用户确认设计阶段或 AD 验收。
