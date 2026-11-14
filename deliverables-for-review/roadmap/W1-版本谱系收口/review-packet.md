# W1 版本谱系收口 · 架构师复核包（W1-R1 / W1-R2）

编制时间：2026-11-14 21:20（北京时间）；证据执行时间见 `manifest.json` 时间轴。
上游依据：`deliverables-for-review/roadmap/W1-architect-review/architect-review.md`
（W1 已有主系统正式导入/精确多边形/对账/页面，22 项 HTTP 已独立通过；但**暂不放行 W1 进入 W2**，
版本身份与父链仍按导入顺序推断）。
比较基线（base）：`080f63e`（W1 首版复核包补记 HEAD）；
本批业务实现提交：`b40b4fad7fe6d1a34702b5b49cd7928fc9c8a7de`（`b40b4fa`，2026-11-14 21:20:48 +08:00）。
**证据全部在提交前采集**，所以 JSON 里的 `code_head` 是 `080f63e`；时间轴见 `commit-reference.md`。
复核命令：`git diff 080f63e -- mvp contracts scripts`（补丁 `changes.patch`）。
性质：**限定整改 + 回归**。不重做适配器、不启动 W2、不改 AD。

## 1. 两个问题的修法

### W1-R1：候选身份与父链改由源谱系决定

| 旧行为（已复现） | 新行为 |
| --- | --- |
| `option_id = studio:{main}:{studio}:{A\|B}`，A/B 字母即身份 | `option_id = studio:{main}:{studio}:root:{root_revision_uid}`，A/B 只作显示名 |
| `parent_revision_id = latest_revision(该字母)`，即"上一次导入" | 父版本来自源 `parent_revision_uid` 经**已导入修订的 source UID → 主系统 revision id** 映射；映射在事务内重读 |
| 独立两组 A 会被串成 v1→v2 | 两个不同根 → 两个候选，各自 v1、`parent=null`（L01） |
| 分叉被串成父子 | 两个分叉的父都是共同父版本，彼此不是父子（L03） |
| 先导入子稿会把旧稿接在新稿后 | 父未导入 → 409 `SOURCE_PARENT_NOT_IMPORTED`；补齐父后链正确（L04） |
| 源父 UID 在 Studio 不存在时被当作根 | 409 `SOURCE_PARENT_MISSING`；父链成环 409 `SOURCE_LINEAGE_CYCLE` |
| 缺父只能猜 | 默认拒绝；显式 `allow_orphan=true` 时 `parent=null` + `parent_link_status=source_parent_not_imported`，**不回填**（L05） |

`revision_no` 仍是主系统内该候选的单调编号（`UNIQUE(option_id, revision_no)`），
`parent_revision_id` 来自源链；分叉是 DAG 的两个分支（同一父、编号 2 与 3），不是父子串联。
`diff` 也改成相对**源父修订**的 `spatial`，不再相对"上一条导入记录"。

### W1-R2：写事务内重检幂等与谱系预期版本

旧流程在读事务算好 `latest/revision_no/幂等`，生成 SVG 后直接写；并发会产生重复版本号或原始唯一约束异常。

新流程在**写事务内**依次：① 重新查同源幂等键（命中即复用并清理本次尝试自己的文件）；
② 重新计算父映射与 `next_revision_no`，若与准备阶段不同就在锁内重新适配、重绘、再写；
③ 缺父仍拒绝；④ set/revision/artifact 同事务提交，失败整体回滚。
没有新增锁服务、消息队列、后台任务或迁移。

### 设计来源与适配来源分开（W2 衔接约束）

`spatial.source.origin_kind` 固定 `studio_import`（传输路径）；新增
`spatial.source.design_origin = {kind: real_model|human|fixture|unknown, declared_by, declaration, run_refs}`。
只有源产物 `diagnostics.source` 明确声明时才判定，未声明一律 `unknown`（L09）。
适配器不是 AI，但这不会把上游真实模型产出改称人工；DB 的粗粒度 `source_kind=human_edit`
是已披露的兼容取舍，未新增迁移。

### 精确 spatial 权威与 bbox 损失声明

`spatial.zones[].polygon_mm` 与源多边形逐值相等；legacy `objects[].shape` 一律
`geometry_mode="bbox_derived"`，`losses` 含 `bounding_box_only`（L10）。本批没有放宽或删除这些声明，
也没有任何代码据 bbox 计算工程量。

## 2. 实际验证（真实执行）

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `scripts/verify_w1_lineage.py --out ... --runtime ...` | **13/13 observed_pass**（真实 HTTP、隔离双库、线程屏障并发 + 确定性接缝） | `lineage-checks.json` |
| `scripts/verify_w1_unified_model.py`（原 22 项，夹具改为真实父 UID） | **22/22 observed_pass** | `after\regression-original22\checks.json` |
| `scripts/verify_w1_browser.py` | `passed=true`、`node_returncode=0`、`page_errors=[]` | `browser\verification.json` |
| 受影响 5 模块单测 | **55 tests OK** | `runtime\focused-unittest.log` |
| 全量 `unittest discover -s mvp/tests` | **262 tests OK** | `runtime\full-unittest.log` |

13 项谱系/并发用例：

| 编号 | 覆盖 | 关键实际结果 |
| --- | --- | --- |
| L01 | 独立两组 A（不同根，同字母） | 两个不同 `option_id`，各自 v1、parent null |
| L02 | 同根 v1→v2（真实 parent UID） | v2 `parent_revision_id` = v1 主系统修订 id，`root_uid=uid-A-1`，`link=resolved` |
| L03 | 同父两个分叉 | 两分叉父都 = v1 主 id，编号 3/4，互不为父 |
| L04 | 乱序（先子后父） | 首次 409 `SOURCE_PARENT_NOT_IMPORTED`；补齐父后 1→2→3 链正确 |
| L05 | 缺父 + `allow_orphan` | `parent=null`、`link=source_parent_not_imported`、`root=uid-A-orphan-1` |
| L06 | 源父 UID 不存在 | 409 `SOURCE_PARENT_MISSING` |
| L07 | 同源并发（`threading.Barrier` 同时发起真实 HTTP） | 两个 200；一个 `reused=false`、一个 `reused=true`；只 +1 版本、+1 SVG |
| L08 | 同谱系并发（两分叉同时） | 两个 200；版本号 2/3、父都指同一 v1、无 500/唯一冲突、+2 版本 +2 SVG |
| L09 | 设计来源 vs 适配来源 | `origin_kind=studio_import`；声明为夹具 → `fixture`；未声明 → `unknown`/`not_declared` |
| L10 | 精确 spatial 权威 | `polygon_mm` 与源逐值相等；legacy `bbox_derived`；`losses` 含 `bounding_box_only` |
| L11 | 采用指定分叉 / 旧版 CAS | 采用分叉最新版 200、`formal_approval=false`；再采用旧版 409 `STALE_OPTION_REVISION` |
| L12 | 确定性并发（同源，准备后提交前插入另一请求） | 外层 `reused=true`、内层 `created`；+1 版本、+1 SVG，无遗留文件 |
| L13 | 确定性并发（同谱系两分叉） | 写内重算编号 2/3、父均指 v1；+2 版本 +2 SVG |

> 并发用例没有用 sleep 制造概率；L07/L08 用 `threading.Barrier` 让两个真实 HTTP 请求同时发出，
> L12/L13 用服务方法显式提供的 `after_prepare` 接缝把"竞争写入"放在准备完成、提交之前，
> 从而确定性地走到写内重检分支。

## 3. 与架构师验收要求的对照

| 要求 | 证据 |
| --- | --- |
| 建立源项目 + 源 revision_uid → 主系统 revision ID 显式映射 | `lineage-mapping.md` §2；L02/L03 证据里的 `source_uid` / `parent_revision_id` |
| 候选身份依据稳定根谱系，A/B 仅显示名 | `option_id=...:root:{uid}`；L01 |
| 源父未导入：明确拒绝/要求导入父，或有清晰来源的缺父状态，不伪造 | L04（拒绝）、L05（显式缺父留痕） |
| 不同根的对象 ID 在候选范围隔离；同根修订对象稳定 | 每候选独立 `option_id`；同根修订沿用源对象 ID（L02/L03 的 `spatial`） |
| 同源重试幂等，分叉/乱序不改历史 | L07/L12（幂等）；L03/L04（不乱接） |
| HTTP 层验证源 UID→目标 ID 和父链，不只数字递增 | L02/L03/L04 直接断言 `parent_revision_id` 与 `source_parent_uid` 的对应 |
| 修正夹具真实父 UID，不靠改预期绕过失败 | `verify_w1_unified_model.save_valid(..., parent_artifact=...)`；原 22 项在新夹具下重跑通过 |
| 写事务内重检幂等与谱系预期版本；冲突可解释 | L12/L13；`_lineage_state` 在写事务内重算 |
| 屏障让两个导入读到相同前态；失败无半记录/遗留文件 | L07/L08 屏障；L12/L13 接缝；每项都检查行数与 SVG 文件数增量 |
| 文件清理只删失败尝试自身产物 | 每次尝试独立 `set_id` 目录；`finally` 仅删本次目录 |
| 设计来源与适配来源分开保留 | L09；`spatial.source.design_origin` |
| 保留精确 spatial 权威与 bbox 损失声明 | L10 |
| 不启动 W2 制图渲染、不扩基础设施、不新增外发/费用、不改 AD | 见 §5；本批无新增迁移/表/服务 |

## 4. 没有做，以及为什么

- **没有重做适配器**：字段映射、精确几何校验、多边形 SVG、对账 ledger 均沿用 W1 首版，只改身份/父链/并发。
- **没有启动 W2**：未出平面图、三维、效果图或量价；`Q10` 仍 `not_run`。W2 范围由架构师明确后再做。
- **没有新增基础设施**：无迁移/表/列、无消息队列、无锁服务、无后台任务；只复用既有 SQLite 事务。
- **没有新增外发或付费调用**：全部本地夹具与隔离库，0 外部调用、0 密钥、0 费用。
- **没有改 AD 与设计阶段结论**：AD01—AD08 未改判，用户设计确认未发生。
- **没有把缺父"补"成父子**：缺父要么拒绝，要么显式标记 `source_parent_not_imported` 且不回填。

## 5. 仍然不像设计公司成果的地方

本批是**版本身份与并发正确性**修复，没有新增任何设计成果：仍无客户级平面图、动线图、天花图、
立面图、材料灯光板、人眼效果图、汇总 PDF；目标图面仍是精确多边形的概念 SVG；相机/材料/照度/
实测高度仍 `unknown`；量价未接通。工程正确性提升不能抵扣这些设计差距。

## 6. 外部调用与费用

| 项 | 数值 |
| --- | --- |
| 外部模型调用 | **0** |
| 外部图像通道 | **0** |
| 外发/生成图片（外部） | **0 / 0** |
| 真实 tokens | **0** |
| 金额 | **0** |
| 密钥 | 未使用、未落盘 |

## 7. 风险与限制

- 主系统 `revision_no` 仍是"该候选内单调编号"，不是源修订号；对应关系看
  `spatial.source.revision_uid` / `revision`。这是刻意保留的双轨口径。
- 并发验证是**单进程多线程 + 隔离 SQLite**；没有验证多进程、PG 并发或断电恢复。
  写事务依赖 SQLite `BEGIN IMMEDIATE` 的写锁；PG 路径沿用同一事务内重检逻辑，但本批未跑 PG。
- `design_origin` 只能读源产物的显式声明；旧产物没有声明时为 `unknown`，不会追溯猜测。
- 源是明确标记的本地夹具，不计入 AD；真实模型与真实设计评价仍属 W3。

## 8. 分工边界

| 主体 | 本批 | 不可替代的边界 |
| --- | --- | --- |
| 执行 AI（本包） | 修身份/父链/并发、补谱系与并发正负例、回归、更新状态 | 未宣布 W2 放行、未改 AD、未把夹具说成 AI 设计 |
| 架构师 | 读 diff、独立复跑 `verify_w1_lineage.py` 与浏览器、核对父链与并发结论 | 不代替用户审美与专业签核 |
| 用户 | 设计阶段确认、AD01—AD08 | 工程 PASS 不代签用户确认 |

## 9. 完整文件路径（均在 `D:\Github\RKD AI\` 下）

复核包：`deliverables-for-review\roadmap\W1-版本谱系收口\`
- `review-packet.md`（本文件）、`lineage-mapping.md`、`positive-negative-cases.md`、
  `code-diff.md`、`changes.patch`、`manifest.json`、`commit-reference.md`
- `lineage-checks.json`（13 项）、`checks.json`（原 22 项回归便携副本）
- `browser\verification.json`、`browser\browser-observations.json`、2 张截图
- `runtime\focused-unittest.log`、`runtime\full-unittest.log`

运行证据：`var\evidence\roadmap\W1-版本谱系收口\`（`var/` 被 Git 忽略）

源码改动：
- `mvp\rkd_mvp\ai_design_option_service.py`（身份/父映射、写内重检、`allow_orphan`、`after_prepare` 接缝）
- `mvp\rkd_mvp\ai_design_studio_adapter.py`（`lineage()`、`design_origin()`、父链状态）
- `contracts\v1\ai-design-option.schema.json`（`studioSource` 增根谱系/父链状态/设计来源）
- `scripts\verify_w1_lineage.py`（新增 13 项）、`scripts\verify_w1_unified_model.py`（夹具真实父 UID）

唯一状态表：`PROJECT_STATUS.md`（已更新；AD 结论未改）。
