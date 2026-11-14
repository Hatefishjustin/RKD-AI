# ARC 首批工程整改 · 架构师复核交付包

日期：2026-11-12（北京时间）
执行委托：`docs/25-架构师交接与执行AI质量约定.md` 第 5 节「首批」（ARC-01—04、直接相关的 ARC-06 规则修正；ARC-05 只交适配说明）
基线 commit：`d6501a9b5b963b0a11a9e148b32eda269f18414b`（A1 收口）；本批已提交并推送为 `eb6513c`，复核差异请用 `git diff d6501a9..eb6513c` 或随附 `changes.patch`。
工作区基线状态：仅 `docs/25` 一个未跟踪文件；本批未 reset / checkout、未清理任何既有改动或原件。完整差异见 `deliverables-for-review/arc-first-batch/changes.patch` 与 `code-diff.md`；若已提交可用 `git diff d6501a9..HEAD` 复核，未提交时可用工作区 `git diff`。
性质：工程控制整改与可复核证据。**不是功能完成证明，不是设计通过，不是 AD 验收。**

---

## 1. 分工与边界（本批复核用）

| 主体 | 本批做了什么 | 明确没有做 |
| --- | --- | --- |
| 执行 AI | 复现缺陷、改实现与必要测试、跑正负例 / 浏览器 / 持久化、留证据、更新状态 | 未宣布设计成立、未改 AD 分母、未把人工方案包装成系统自动设计 |
| 架构师 | 读实际 diff、抽查失败样本、核对来源/版本/字节、给工程结论 | 不代替用户审美与专业签核 |
| 用户 | 设计阶段确认、AD01—AD08 | 本批未获得任何新的设计阶段确认 |

本批 **0 次外部模型/图像调用、0 费用、0 密钥**。密钥未写入任何文件、日志、Git、截图或报告；所有回路验证使用 `scripts/arc_first_batch_stub.py` 中明确标注的**本地模型桩**（`local-model-stub`）。真实设计效果仍待后续授权验证。

## 2. 缺陷复现（整改前，只读 + 隔离库）

证据：`var/evidence/architecture-handoff/first-batch/before/reproduction.json`
复现脚本：`scripts/arc_first_batch_repro.py --phase before`（只读 `var/studio/studio.db` 用 `mode=ro`；store 行为用隔离临时库）

| 编号 | 整改前实测 | 对应 |
| --- | --- | --- |
| 契约未执行 | 库内最新两份 spatial-plan 用 `Draft202012Validator.iter_errors` 各 **66** 条 Schema 错误，但 `plan_is_valid()` 返回 `[True, ""]`；缺 role / 错误类型 / 无效 catalog 引用 / 模型自称批准全部被放行 | ARC-01 |
| 100㎡/3㎡ 误判 | 100㎡ 场地 3 个各 1㎡ 分区、面积表 3㎡、不连接动线，`check_plan()` 返回 `ok=True`、0 blocker，且**不报告**未分配面积 | ARC-02 |
| 外接矩形误报 | 三角形 A/B 实际 Shapely 交集 `0.0`、`intersects=False`，但报 `GEO-004` 重叠 | ARC-02 |
| 面积表矛盾 | 补「通道及其他」凑 469㎡ 后，仍报 `STD-003` 且提示「补『通道及其他』」 | ARC-02 |
| 非直角只数清单 | 2 条文字声明 + 全轴对齐矩形，`non_orthogonal_count=2` 且无 issue | ARC-02 |
| 结构化数据截断 | orchestrator 内 **9 处** `[:4000]/[:3500]/[:3000]`；末尾对象在三种长度下均不可达 | ARC-03 |
| 项目硬编码 | `StudioView.tsx:47` 两分支都是 `ningbo-xiecheng` | ARC-04 |
| 留言不进修订 | `/messages` 只 `add_message`；无 feedback 表；项目需求不变 | ARC-04 |
| 种子重写事实 | 每次 `seed_from_fixtures()` 覆盖已有项目名称 / 需求 / 场地 | ARC-04 |
| 闸口重放覆盖 | 对已决定闸口再次 `decide_gate`，决定与理由被改写 | ARC-04 |
| 规范数值失真 | 6 条规则的数值阈值把来源标题包装成用户明确数值 / 普遍规范；`_guard` 只预留 max_tokens；usage 缺失记 0；任意错误无差别降级重发 | ARC-06 |

## 3. 实际实现（不推倒重写，复用 shapely / jsonschema / 现有 Studio 模块）

| 任务 | 改动 | 关键落点 |
| --- | --- | --- |
| ARC-01 | 新增**模型提案契约**（身份字段不属于模型）与四级校验器：结构 Schema → 语义引用 → 几何/面积 → 锁定；原始输出与完整诊断保存为 `invalid_raw`，绝不作为有效候选；修复反馈含字段路径 / 期望类型 / 对象 ID / 可操作建议；通过后再用原 draft 契约复校装配结果 | `contracts/v1/spatial-plan-proposal.schema.json`、`mvp/rkd_mvp/studio/validation.py`、`orchestrator.py` |
| ARC-02 | 复用项目锁定 `shapely==2.1.2`，替换外接矩形与 width 自报逻辑：多边形合法性/自交/正面积/越界/**实际交集**、保留区 keep-out、入口可达、动线实测净宽与瓶颈、家具目录引用与旋转占地、非直角声明与几何对应；唯一面积口径 = `design_scope_sqm`（外框 − 保留区），程序复算未分配并显式显示，`layout_complete=false` 不冒充完整布局；无法验证项标 `unsupported/unknown` | `mvp/rkd_mvp/studio/geometry.py`、`tools.py`（`check_plan` 委托同一实现） |
| ARC-03 | 删除全部字符截断；评审/修订拿基线 artifact id / revision_uid / 完整对象事实 / issue_id；优先白名单 patch（程序应用并复算生成完整新版本），完整输出也走对象保留、删除理由、锁定与逐项对应复核；B 候选拿 A 结构摘要并确定性检查实质差异；`MAX_AUTO_REWORK=2` 保持、不拆 run | `mvp/rkd_mvp/studio/revision.py`、`orchestrator.py` |
| ARC-04 | 版本化 feedback（老板留言/驳回理由进有效需求）、CAS/预期版本与持久取消（晚到结果标 `superseded`）、显式项目 ID 映射、闸口绑定具体成果基线且决定 append-only、区分「允许继续试验 / 认可设计方向」且都不等于设计通过、阶段状态四分开、种子 insert-only | `store.py`、`server.py`、`StudioView.tsx`、`fixtures/studio/projects/ningbo-xiecheng.json` |
| ARC-06 | 规范库按用户原话 / 适用范围 / 派生启发式 / 专业依据 / 程序覆盖分开；「2 处非直角」「60% 天花覆盖」标为不作判据的启发式；看图说明图面可见范围；调用前预留输入+输出额度、调用后按实际 usage 对账、usage 缺失记 unknown、超时记 pending_reconciliation、兼容降级只对明确不支持错误；每轮记录调用数/图片数/tokens/金额(unknown) | `knowledge/design-standards/standards.v1.json`、`llm.py` |
| ARC-05 | **只交短小适配说明**，未实现纵向适配 | `deliverables-for-review/arc-first-batch/ARC-05-adaptation-note.md` |

契约修改说明（按要求记录语义/版本/兼容理由）：
- 新增 `spatial-plan-proposal.v1`：语义是"模型提案边界"，把身份/批准/采用字段从模型输出中剥离；`additionalProperties:false`，未放宽任何必填项。
- 原 `spatial-plan-draft.schema.json` **未改动**：程序注入身份元数据后再用它复校完整交接文档，旧成果解析保持不变。
- 未通过移除必填项、全面允许额外字段或补造未知字段消除错误；身份字段是程序按版本链注入的已知事实，不是设计推断值。

## 4. Q01—Q12 复核结果（工程结论，不是 AD 验收）

证据：`var/evidence/architecture-handoff/first-batch/after/checks.json`、`q-checks.json`、`after-reproduction.json`

| 编号 | 结果 | 主要证据 |
| --- | --- | --- |
| Q01 | observed_pass | 7 类契约负例全拒（含字段路径/类型/对象ID/建议），正例四级通过；`invalid_raw` 历史字节保留、`valid_candidate` 与历史分组区分 |
| Q02 | observed_pass | 100㎡/3㎡ 显式报 **97㎡ 未分配**且 `layout_complete=false`；完整布局对账 gap<0.75㎡；补通道不再自相矛盾；外框 469㎡ ≠ 可布置 430.167㎡ |
| Q03 | observed_pass | 分离三角形不报相交；真实交集/自交/越界/零面积均被拒绝 |
| Q04 | observed_pass | 断路、入口不可达、障碍穿越、实测瓶颈、保留卫生间、旋转家具占地、未知目录引用均有定位 |
| Q05 | observed_pass | orchestrator 截断处 0；>4000 字符方案末尾对象在完整对象事实中可达；基线 ID / issue_id 明确 |
| Q06 | observed_pass | 换名 / 换色 / 顺序 / 20mm 位移均不算新拓扑；A/B 结构签名实质不同 |
| Q07 | observed_pass | 「调整洽谈区、保留入口」进入版本化有效需求；patch 产生 4 个对象 diff、无关对象保留率 1.0、绑定原基线 |
| Q08 | observed_pass | 4/4 接受意见均有对应对象 diff；拒绝有理由；无 diff / 无理由删除 / 锁定改动 / 身份 patch 全被拒；返工上限仍 2 且不拆 run |
| Q09 | observed_pass | 切项目 404 + 不显示宁波；晚到结果 `superseded`（字节保留）；决定重放 `applied=false`、原决定不变、修正作新记录 |
| Q10 | **not_run** | ARC-05 纵向适配属第二批；本批只交字段映射说明，未做平面/渲染/数量同源一致性验证 |
| Q11 | observed_pass | 重启后反馈/任务/闸口/检查报告/产物保留；种子不重写项目事实、不重复事实 |
| Q12 | observed_pass | `succeeded` 仅表示流程跑完；来源标 `local-model-stub`；`design_approved_by_user=false`；未生成下一阶段交付；AD 不改判 |

合计：**11 observed_pass / 0 observed_fail / 1 not_run**。
正负例明细：`after/q-checks.json` 的 `cases` 数组；`after/checks.json` 的 `positive_negative_cases`。

## 5. 验证命令、环境与结果

环境：Windows / Python 3.12.14（`.venv`）、`jsonschema==4.25.1`、`shapely==2.1.2`、Node v22.22.2、Playwright（Edge headless）。
所有命令均未设置任何密钥环境变量；无外部网络调用。

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `.venv/Scripts/python.exe scripts/arc_first_batch_repro.py --phase before` | 复现全部缺陷 | `before/reproduction.json` |
| `.venv/Scripts/python.exe scripts/arc_first_batch_repro.py --phase after` | 66 条契约错误全部拦截、100㎡/3㎡ 拒绝并显式 97㎡、三角形不误报、截断 0、硬编码/重放消失 | `after/after-reproduction.json` |
| `.venv/Scripts/python.exe scripts/verify_arc_first_batch.py` | Q01—Q12：11 pass / 0 fail / 1 not_run | `after/checks.json`、`q-checks.json` |
| `.venv/Scripts/python.exe scripts/verify_studio_loop.py` | A1 管线 15/15 PASS；本地桩回路产出 3 份有效候选、v2 修订、绑定基线的闸口 | 控制台 + `after/scratch/` |
| `PYTHONPATH=mvp .venv/Scripts/python.exe -m unittest mvp.tests.test_arc_first_batch -q` | 18/18 OK | 控制台；另见 `after/full-unittest-final.log` |
| `PYTHONPATH=mvp .venv/Scripts/python.exe -m unittest discover -s mvp/tests -q` | **262/262 OK**（含新增 18 项；未设 `PYTHONPATH=mvp` 时会报 3 个导入错误，属环境配置问题非回归） | `after/full-unittest-final.log` |
| `npm run build`（web/） | EXIT=0（保留既有 PDF.js 大包告警） | `after/frontend-build.log` |
| `.venv/Scripts/python.exe scripts/verify_arc_browser.py` | `passed=true`；真实浏览器点击 + 截图 + 重启持久化 | `after/browser/verification.json`、`browser-observations.json` |

### 浏览器证据（真实操作，不是字节说明的替代）

`var/evidence/architecture-handoff/first-batch/after/browser/`

- `arc-feedback-desktop.png`：提交「调整洽谈区、保留入口」后显示版本化有效需求 v1、绑定基线、阶段状态（设计认可：否）
- `arc-revision-desktop.png`：本轮修订、逐条回应与对象 diff
- `arc-other-project.png`：切到未映射项目显示限制提示，**不显示宁波结果**（HTTP 404）
- `arc-reload-desktop.png`、`arc-mobile.png`：刷新后反馈与有效候选分组保留；390px `scrollWidth<=390` 无横向溢出
- `browser-observations.json`：项目显式映射、闸口基线、决定重放（`applied=false`、原决定不变）、`page_errors=[]`
- `verification.json`：`passed=true`、`external_calls=0`、`keys_used=false`、重启持久化（反馈 v2 / 已决定闸口 1 / 历史字节保留 / 6 份有效候选）

> 隔离说明：浏览器验证使用独立 `RKD_STUDIO_DB` 与新建主工作台 SQLite，**日常 `var/studio/studio.db` 与 NAS 未被写入或改动**。

## 6. 外部调用与费用

| 项 | 本批实测 |
| --- | --- |
| 外部模型调用 | **0** |
| 外部图像通道调用 | **0** |
| 外发图片 | **0 张**（A1 看图步骤向本地桩传入 3 张占位字节，不是外发） |
| 生成图片 | **0 张**（本批无效果图/渲染产出） |
| 真实模型 tokens | **0**；桩计数仅用于台账演练，不代表真实用量 |
| 金额 | **unknown / 0 外部费用**（无价表且无调用，`cost_status=no_external_calls_zero_cost` 或 `unknown_no_price_table`） |
| 密钥 | 未使用、未写入任何文件/日志/Git/截图/报告 |

未批准第三轮真实模型重跑，未进入 A2，未越过设计阶段确认。

## 7. 变更清单（完整路径，均为 `D:\Github\RKD AI\` 下相对路径）

修改（9 个已跟踪文件）：
- `mvp/rkd_mvp/studio/geometry.py` 为新增；实际修改：`mvp/rkd_mvp/studio/orchestrator.py`、`store.py`、`server.py`、`tools.py`、`llm.py`
- `contracts/v1/` 未改旧契约；新增 `contracts/v1/spatial-plan-proposal.schema.json`
- `knowledge/design-standards/standards.v1.json`
- `fixtures/studio/projects/ningbo-xiecheng.json`（仅加显式 ID 映射字段）
- `web/src/StudioView.tsx`
- `scripts/verify_studio_loop.py`

新增（11 个）：
- `mvp/rkd_mvp/studio/geometry.py`、`validation.py`、`revision.py`
- `contracts/v1/spatial-plan-proposal.schema.json`
- `mvp/tests/test_arc_first_batch.py`
- `scripts/arc_first_batch_repro.py`、`arc_first_batch_stub.py`、`verify_arc_first_batch.py`、`verify_arc_browser.py`、`verify_arc_browser.cjs`
- `deliverables-for-review/arc-first-batch/ARC-05-adaptation-note.md`

交付物：
- `deliverables-for-review/arc-first-batch/changes.patch`（**标准 git 补丁，含全部新增文件，可直接 `git apply --check` 或逐段复核**）
- `deliverables-for-review/arc-first-batch/code-diff.md`（可读版差异说明）
- `deliverables-for-review/arc-first-batch/checks.json`、`q-checks.json`、`review-packet.md`、`positive-negative-cases.md`
- `deliverables-for-review/arc-first-batch/before-reproduction.json`、`after-reproduction.json`
- `deliverables-for-review/arc-first-batch/browser-verification.json`、`browser-observations.json`、`browser-screenshots/*.png`
- `deliverables-for-review/arc-first-batch/ARC-05-adaptation-note.md`
- `var/evidence/architecture-handoff/first-batch/review-packet.md`、`checks.json`（架构师指定路径）
- `PROJECT_STATUS.md`（追加本批实际完成范围，不改 AD 结论）

## 8. 仍然不像设计公司成果的地方（逐条，如实）

1. **本轮没有新增设计成果**：没有封面/设计说明、平面布置图（正式）、动线分析图、功能泡泡图、天花布置图、2 张立面图、材料与灯光板、3 张人眼效果图、可发客户 PDF。既有设计差距仍未消除。
2. **候选仍是概念平面草案**：分区多为矩形/多边形色块，没有真实墙体围合、柱网、门窗、楼梯构造、洁具、尺寸链、材料实物色块；缩略图明确标注"仅用于讨论，不是成果图纸"。
3. **没有天花与灯光表达**：图面未画天花/灯具；本批已明确"图面没画 ≠ 模型数据没有"，但表达缺口本身未补。照度、色温、配光、间距未计算，不编造数值。
4. **没有效果图/材质/软阴影/窗光/绿植/展品**：本批 0 张渲染；案例参照图是人工编写的手工样板，明确标注、不计入系统自动生成成果。
5. **设计来源不是系统自动设计**：本批所有验证数据都是明确标记的本地模型桩；真实 AI 设计能力、真实用户设计评价、专业签核仍未完成。
6. **几何能力仍受限**：单层、多边形分区、无曲面/多层/异形构造；门窗/柱网/消防疏散/无障碍标 unsupported，不宣称合规。
7. **成本与量价**：本批未做同源量价；unknown 保持 unknown，未补 0，未把净地坪小计叫全项目造价。
8. **工程 PASS 不等于设计成立**：`succeeded` 只表示回路跑完；闸口仍在等待用户；AD01—AD08 未自行改判，仍以用户结论为准。

## 9. 未测 / 限制 / 需要用户介入

- **未测（not_run）**：Q10 同源平面+渲染+数量一致性、旧成果失效与文件哈希对账（ARC-05 第二批）；真实模型调用通道与费用；真实 PG/NAS/账号/备份专项（管理配套冻结，本批未重跑，仅做共用服务的全量单测回归）；专业审图与消防/无障碍合规。
- **未做**：A2 自由协作与 3 概念发散、第三轮真实模型重跑、阶段 2/3 设计成果、任何外部付费或资料外发。
- **需要用户介入的下一节点**（本批不自行推进）：对首批工程结论复核后，决定是否给出下一份有限委托；真实调用须另给费用与资料外发授权；设计阶段确认与 AD01—AD08 只能由用户给出。
- **已知工程限制**：`check_reports` / `feedback` / `gate_revisions` 是 Studio 实验库内的追加表；Studio 仍不是主系统成果登记权威（见 ARC-05 说明）；浏览器验证使用固定 8099 端口与隔离 CORS 白名单，仅用于本地验收。

---

复核方式建议：先读 `deliverables-for-review/arc-first-batch/code-diff.md` 的 `validation.py` / `geometry.py` / `store.py::decide_gate` / `orchestrator.py::_scenario`，再抽查 `before/reproduction.json` 的失败样本与 `after/q-checks.json` 的 `cases`，最后看 `after/browser/*.png`。工程结论只报「可进入下一委托 / 需整改 / 证据不足」，不代替用户确认设计阶段或 AD 验收。
