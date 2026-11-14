# W1 统一模型适配 · 架构师复核包

编制时间：2026-11-14 20:05（北京时间）；证据实际执行时间见 `manifest.json` 时间轴。
上游依据：`deliverables-for-review/roadmap/W0-final-architect/architect-review-and-W1.md`
（W0 在**受限工程范围**放行、批准 W1、给出 W1 顺序与退出标准）；`docs/26` 第 3/4/6 节；
W0 三份契约映射勘误 `deliverables-for-review/roadmap/W0-收口/evidence-provenance-erratum.md` §2。
比较基线（base）：`cb84581`（W0 放行时的 HEAD）；本批提交号见 `commit-reference.md`。
复核命令：`git diff cb84581 -- mvp contracts web`（补丁在 `changes.patch`）。
性质：**工程适配批**。不是设计完成，不是设计通过，**不自行宣布 W2 范围**，不改 AD01—AD08。

## 1. 需求映射（按架构师给的执行顺序）

| 顺序 / 要求 | 本批处理 | 落点 |
| --- | --- | --- |
| 1. 先核对主系统模型与三份契约，随后立即做可运行适配 | 核对 `ai-design-option.v1` / `spatial-plan-draft.v1` / `spatial-plan-proposal.v1` 的真实字段；按勘误 §2.3 写 `contract-mapping.md`；同批交付可运行适配器 | `contract-mapping.md`、`mvp/rkd_mvp/ai_design_studio_adapter.py` |
| 2. 最小模型表达：边界/洞/保留、功能空间、隔断门口依据、家具展台、材料面、高度标高、天花灯光意向、相机、需求引用与对象来源；未知保持 unknown | 在**同一份**主系统候选文档内新增可选 `spatial` 段：精确 mm 多边形、场地边界与 keep-out、家具目录引用、平台造型参数、天花灯具与色温意向、来源/需求引用、命名缺项；分区不自动变墙、活动包络不计实体量 | `contracts/v1/ai-design-option.schema.json`（`$defs/spatialExtension` 等）、适配器 `adapt_proposal()` |
| 3. 稳定对象 ID、显式项目映射、mm/m、父版本与来源哈希贯通；多边形不得静默矩形化 | 同名稳定 ID；`Store.resolve_project_id()` 显式映射；mm→m 用 Decimal /1000；`parent_revision_id` 指向上一条主系统修订 id；`generation.input_hash` 为源字节哈希；精确多边形原样保存在 `spatial`，legacy rect 一律标 `bbox_derived` 并列入 `losses` | `contract-mapping.md` §1/§2/§4、`field-reconciliation.json` |
| 4. 页面候选导入/查看状态，能看到源提案、目标版本、差异与缺项；采用显式且校验预期版本；导入不改生产/采购/发布 | `AiDesignOptionsPanel` 新增 Studio 来源下拉、导入按钮、已导入版本列表、字段对账表、缺项清单与目标图面链接；导入只写候选表，`adoptions` 表保持 0 行；旧采用 CAS 仍生效 | `web/src/AiDesignOptionsPanel.tsx`、`web/src/styles.css`、`api_server.py` / `api_service.py` |
| 5. 兼容旧格式与历史下载；隔离库验证失败回滚、幂等与重启；不开管理配套 | **零新增迁移/表/列**；旧合成候选生成与 SVG 下载回归通过；单事务写 set+revision+artifact，中途失败全回滚并清理 SVG；同源幂等；重启后版本/来源/字节保留 | W1-05 / W1-14 / W1-15 / W1-19，`after/checks.json` |

## 2. 实际做了什么

1. **正式适配入口**：`POST /api/v1/projects/{pid}/ai/design-options/import-studio` +
   `GET .../studio-sources`、`GET .../studio-imports`、`GET .../studio-imports/{revisionId}`。
   全部走 `StudioProposalSource`（Studio 自己的 `Store` 公共方法）这一显式只读边界，不直接读 Studio 表。
2. **一个权威模型**：产物仍是 `rkd-ai-design-option.v1`，存入既有
   `ai_design_option_sets / revisions / artifacts` 三张表（采用表不写）。`spatial` 是文档内可选段，
   不是第三套模型；DB 层零迁移，PG 导入白名单与快照版本范围未改。
3. **精确几何**：shapely 直接对 mm 多边形做 8 项硬检查；SVG 从精确多边形绘制（含 5 点非矩形入口区），
   legacy `objects[]` 的矩形仅作旧渲染兼容并显式标注 `bbox_derived` + `exact_polygon_ref`。
4. **保守拒绝与 unknown**：单位错配、缺失目录引用、无法表达的几何、错误项目映射、源 sha 变化、
   非有效候选、中途异常都在写入前拒绝或回滚；材料规格、相机/视图、照度、实测标高、门窗柱网
   作为**命名缺项**保留，`cost.budget` / `total_project_estimate` 的 `value` 保持 `None`，不补 0。
5. **版本链与幂等**：同一来源（产物 id + sha256 + 适配器/映射版本 + 项目/组织）重复导入返回
   `reused=true` 且不造版本；源内容变化形成 `revision_no+1`、`parent_revision_id` 指向旧版、
   `diff` 记录同一对象 ID 的字段变化；旧修订与旧 SVG 字节仍可下载。
6. **页面**：真实浏览器从"需求草稿 → AI 候选"页选中 Studio 有效提案 → 点导入 → 列表出现目标版本 →
   打开字段对账（45 行）→ 缺项与几何模式可见 → 目标模型图面为多边形 SVG → 390px 无溢出。

## 3. 验证结果（真实执行，非计划）

| 命令 / 入口 | 结果 | 证据 |
| --- | --- | --- |
| `scripts/verify_w1_unified_model.py --out ... --runtime ...` | **22 observed_pass / 0 fail**（真实 HTTP、隔离主系统库 + 隔离 Studio 库） | `checks.json`（原件 `after/checks.json`） |
| `scripts/verify_w1_browser.py --out ... --runtime ...` | `passed=true`、`node_returncode=0`、`page_errors=[]` | `browser/verification.json`、`browser/browser-observations.json`、2 张截图 |
| 逐字段对账 | 布局 A / B 各 **33 行逐值比较全部相等**，各含 1 个 5 点非矩形分区（ZA1 / ZB1），各 45 行 field ledger | `after/field-reconciliation.json`、`after/models/` |
| `python -m unittest -q mvp.tests.test_ai_design_options ...`（5 个受影响模块） | **55 tests OK** | `runtime/focused-unittest.log` |
| 全量 `python -m unittest discover -s mvp/tests -q` | **262 tests OK**（325.2 s） | `runtime/full-unittest.log` |
| `npx tsc --noEmit` / `npm run build` | EXIT=0 / EXIT=0 | `runtime/frontend-tsc.log`、`runtime/frontend-build.log` |

**22 项 HTTP 覆盖**：来源列表与显式映射；布局 A 导入；API/存储/SVG 字节一致且采用表为空；
布局 B 导入与结构签名/精确多边形不同；同源幂等；来源变更产生新版本与同对象 diff、旧版本可读；
单位错配、目录缺引用、伪多边形、错误项目映射（两种）、跨项目产物、源 sha 不符、非有效候选；
失败不半写入；旧版本并发采用 CAS 拒绝；中途失败单事务回滚 + SVG 清理；重启保留；
逐字段对账；源/目标模型样本；跨项目隔离；旧合成候选格式与历史下载兼容。

**页面证据关键实测**：显式映射 `ningbo-xiecheng → project_ningbo_xiecheng_2026`；
导入前 0 条、导入后 1 条；目标候选 v1、父版本 null、源产物 id 一致、6 项命名缺项；
目标模型 `spatial.zones=6`、非矩形 `["ZA1"]`、`unit="mm"`、`origin_kind="studio_import"`；
SVG 5523 字节、含 `<polygon>`、下载字节 sha 与存储一致；`adoption=null`；
字段对账 45 行可见、相机/材料缺项可见、几何模式可见；390px `scrollWidth=390`。

## 4. 与架构师退出标准的逐条对照

| 退出标准 | 本批证据 |
| --- | --- |
| 两种实质不同布局（含非矩形分区）通过同一个适配器；对象/坐标/单位/材料/来源逐项对账，不只计数或哈希 | W1-02/04/16；`field-reconciliation.json` 每布局 33 行逐值 `equal=true`，A/B 的 5 点入口区坐标不同，`structure_signature` 不同 |
| 同一来源重复导入不重复造版本；来源改变形成新版本，旧字节保留；同对象后续修改可追踪，跨候选/跨项目不串用 | W1-05/06/18；`diff` 含 `ZA1.polygon_mm` 与 `F3.rot` |
| 单位错配、缺失对象引用、无法表达几何/材料、错误项目映射、旧版本并发采用、适配中途失败；失败不半写入、不污染采用/量价/采购 | W1-07/08/09/10/11a-d/12/13/14；失败后行数与 SVG 文件数不变，`adoptions` 始终 0 行 |
| 页面触发一次真实导入并查看目标模型，API/页面/存储版本一致；明确测试夹具与真实 AI 来源 | `browser/verification.json`；所有源标为 `labelled_local_fixture_not_real_AI`，不计入 AD |
| 提交字段映射、两份源/目标模型、逐项对账、命令与正负例、页面证据和源码基线 | `contract-mapping.md`、`after/models/`、`after/field-reconciliation.json`、`checks.json`、`positive-negative-cases.md`、`manifest.json` |

## 5. 没有做，以及为什么

- **没有做 W2**：W2 的同源平面、人眼效果图、量价贯通与 `Q10` 仍 `not_run`；当前批准范围只有 W1，
  交回架构师后再明确 W2 实施范围。
- **没有做 W3/W4**：真实付费设计试验、阶段 2/3 成果需用户对具体版本确认，未获确认不越级。
- **没有新增第三套权威模型 / 没有新增迁移**：`spatial` 是既有候选文档的可选段；DB 表/列、
  `postgres_import.py` 白名单、PG 迁移版本均保持不变，旧格式与历史下载经 W1-19 验证。
- **没有把 Studio 提案说成系统自动设计**：本批源是明确标记的本地测试夹具；真实模型效果留 W3。
- **没有把多边形改成矩形后称无损**：legacy rect 显式标注 `bbox_derived`，精确多边形与损失清单都在 `spatial`。
- **没有编 unknown 数值**：材料规格、相机、照度、实测标高、预算与总价都是命名缺项或 `value=None`。
- **没有开管理配套**：未动 NAS/PG 切库/账号/备份；只在隔离 SQLite 里验证本批仓储路径。
- **没有改用户原件**：`fixtures/` 与 `source/` 原件只读，证据全部写新目录。

## 6. 仍然不像设计公司成果的地方（逐条）

1. **本批没有新增任何客户级设计成果**：无封面与设计说明、正式平面布置图、动线分析图、天花图、
   立面图、材料与灯光板、人眼效果图、汇总 PDF。W1 是工程适配批。
2. 目标图面是从精确多边形绘制的**概念平面 SVG**：没有墙体围合、柱网、门窗构造、洁具、
   尺寸链、材料实物色块；天花灯具只用圆点示意，照度/配光未算。
3. **0 张人眼效果图**；相机/视图在 `spatial.views` 为空并作为命名缺项，未生成假设机位。
4. 设计来源仍是明确标记的本地夹具；真实 AI 设计能力、真实用户设计评价、专业签核均未完成。
5. 量价只保留 `unknown`，没有同源工程量、单价、报价；候选阶段不生成完整项目估价。
6. 分区不是实体墙、活动包络不计实体工程量；消防/无障碍/实测门洞净宽全部 `unknown`，不宣称合规。
7. `succeeded`/导入成功只表示工程流程跑完；`AD01—AD08` 未改判；`Q10` 仍 `not_run`；
   用户设计阶段确认与正式责任闸口不变。

## 7. 外部调用与费用（本批实测）

| 项 | 数值 |
| --- | --- |
| 外部模型调用 | **0** |
| 外部图像通道调用 | **0** |
| 外发图片 / 生成图片（外部） | **0 / 0** |
| 真实模型 tokens | **0** |
| 金额 | **0**（`cost_status=no_external_calls_zero_cost`） |
| 密钥 | 未使用、未写入任何文件/日志/Git/截图 |

本批未新增付费调用或资料外发授权；未读取其他软件密钥。

## 8. 风险、限制与下一步

- **粗粒度 `source_kind` 限制**：DB CHECK 里没有 `studio_import` 值，为避免新增迁移/第三套表，
  列值沿用 `human_edit`；精确来源由 `spatial.source.origin_kind` / `generation` / `input_hash` 承担。
  若架构师要求把精确来源也落到列级枚举，需要单独安排一次迁移（本批未做）。
- **legacy rect 只作显示**：旧渲染器与 `structure_signature` 仍基于包围盒；精确几何在 `spatial`。
  W2 若要用同一模型出正式平面/量价，必须直接读 `spatial`，不能读 `objects[].shape`。
- **PG 路径未验证**：本批只在隔离 SQLite 验证（按 W1 委托"仅验证本批触及的仓储路径"）；
  未正式切库、未跑 PG 专项。契约与仓储列没有变化，但没有把 SQLite 结果外推成 PG 通过。
- **适配范围有限**：只接受 `spatial-plan-draft.v1` 的**有效候选**；其他 Studio 产物、自由协作
  记录、失效稿一律拒绝。未支持任意 CAD/BIM。
- **下一步**：交架构师复核；W0 工程放行与 W1 结果都只覆盖已验证场景。W2 范围由架构师明确后再实施；
  阶段 1→2 / 2→3 仍只接受用户对具体版本的明确确认。

## 9. 分工边界

| 主体 | 本批 | 不可替代的边界 |
| --- | --- | --- |
| 执行 AI（本包） | 契约扩展、适配器、服务/API/页面、正负例、对账、回滚与重启证据、状态更新 | 未宣布设计成立、未宣布 W2 范围、未改 AD 分母、未把夹具说成 AI 设计 |
| 架构师 | 读实际 diff、独立复跑 `verify_w1_unified_model.py` / 浏览器脚本、核对映射与字节 | 不代替用户审美与专业签核 |
| 用户 | 设计阶段确认、AD01—AD08 | 工程 PASS 不代签用户确认 |

## 10. 完整文件路径（均在 `D:\Github\RKD AI\` 下）

复核包：`deliverables-for-review\roadmap\W1-统一模型适配\`
- `review-packet.md`（本文件）、`contract-mapping.md`、`positive-negative-cases.md`、
  `code-diff.md`、`changes.patch`、`manifest.json`、`commit-reference.md`
- `checks.json`（22 项 HTTP 结果，便携副本；原件 `var\evidence\roadmap\W1-统一模型适配\after\checks.json`）
- `field-reconciliation.json`（A/B 逐字段对账）、`models\layout-{A,B}.{source,target}.json`、
  `models\layout-A-v2.{source,target}.json`
- `browser\verification.json`、`browser\browser-observations.json`、
  `browser\w1-import-desktop.png`、`browser\w1-import-mobile.png`
- `runtime\full-unittest.log`、`runtime\focused-unittest.log`、
  `runtime\frontend-tsc.log`、`runtime\frontend-build.log`

运行证据：`var\evidence\roadmap\W1-统一模型适配\`（`var/` 被 Git 忽略）

源码改动：
- `contracts\v1\ai-design-option.schema.json`（新增可选 `spatial` 段，未改必填项）
- `contracts\v1\openapi.v1.json`（新增 4 个接口声明，保持原排版）
- `mvp\rkd_mvp\ai_design_studio_adapter.py`（新增：适配器、精确几何校验、多边形 SVG、Studio 只读边界）
- `mvp\rkd_mvp\ai_design_option_service.py`（新增导入/列表/详情、幂等、单事务、回滚）
- `mvp\rkd_mvp\api_service.py`、`mvp\rkd_mvp\api_server.py`（接口与路由）
- `web\src\AiDesignOptionsPanel.tsx`、`web\src\styles.css`（页面导入与字段对账）
- `scripts\verify_w1_unified_model.py`、`scripts\verify_w1_browser.py`、
  `scripts\verify_w1_browser.cjs`（新增验收脚本）

唯一状态表：`PROJECT_STATUS.md`（本批已更新：W0 受限放行 + W1 结果；AD 结论未改）。
