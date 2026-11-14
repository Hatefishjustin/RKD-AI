# 室内设计公司自主生产系统：项目进度

更新时间：2026-11-14

## 当前阶段

**2026-11-14 W2 同源成果切片已交付（交架构师复核；Q10 与含扣除区独立案例仍是缺口，不宣布 W2 通过）：**按 `W1-lineage-architect/review-and-W2.md` 的顺序完成"精确模型→可读平面→人眼效果图→受支持净量/已知成本→页面下载"，同一执行器处理两种布局，**未启动 W3/W4、未新增付费调用或外发、未改 AD**。**实现**：新增 `ai_spatial_outputs.py`（冻结输入清单；从精确 `spatial.zones[].polygon_mm` 出平面，含分区/面积表/图例/总尺寸与分区尺寸/动线/保留区/灯位/机位视线/未建模缺项/"不是施工图"声明；场景 JSON 米制化；净量用 shapely 精确多边形并做独立鞋带公式复核、bbox 结果并列仅作对照；成本无价源一律 unknown、`formal_quote=false`）与 `ai_spatial_output_service.py`（复用既有 `ai_development_jobs/revisions/artifacts` 三表，**零迁移/零新表**，任务分阶段、渲染在数据库事务外、失败不登记半份成果、按登记 SHA 校验下载）；新增 `scripts/render_spatial_scene.py` 用本机 Blender 4.2.9 Cycles CPU 出人眼图（机位/材质/家具高度为标注假设）；`AiSpatialOutputsPanel` + "同源成果"页签与 3 个接口。**验证**：`verify_w2_spatial_outputs.py` 真实 HTTP **7/7**（两份布局各渲染一次：A 精确净量 **233.03㎡**、独立复算 233.03、bbox 234.31（+1.28，不用于计量）、B **229.08㎡**；四种受控变更：几何 ZA2 收进 800mm→净量 229.19 且平面/场景改变、材料改配色/材质而净量不变、只改相机不改量、假设单价 1000→1200 金额 233,030→279,636 而平面/场景/净量不变；逐文件下载 SHA 与登记一致）；真实 Edge 浏览器 `passed=true`（页面选修订→生成→平面 10,022B/人眼图 1.03MB/7 行净量/缺项可见/zip 下载 SHA 一致/390px 无溢出/`page_errors=[]`）；定向 5 模块 **55 OK**、全量 **262 OK**、`tsc`/`npm run build` EXIT=0。**如实缺口**：①**Q10 未闭环**——只做到同一次生成内平面/场景/净量/机位同源与下载 SHA 一致，**旧包字节不变、生成中变更/取消、失败重试**未实现未测；②**含扣除区的独立案例缺失**——两份标准夹具的楼梯/卫生间在分区之外，扣除额为 0，只有几何变更用例体现面积变化，未单独构造"保留区落在分区内"的源；③人眼图是**内部试验级**（色块地面、统一灰家具盒、无真实材料/产品/软装/绿植/人物），平面无墙体/门窗/柱网/洁具/隔断构造，材料无规格与价源；④设计来源是明确标记的本地夹具，不是真实 AI 设计，不计入 AD01—AD08。**结论**：本批是有效的同源表达能力切片，**但按架构师退出标准尚未完成 Q10 与含扣除区案例，不能算 W2 通过**；交架构师复核并明确下一步。复核包 `deliverables-for-review/roadmap/W2-同源成果切片/`（`index.html` 评审入口、`review-packet.md`、`checks.json`、`outputs/layout-A|B`、`browser/`、`code-diff.md`、`changes.patch`、`manifest.json`），运行证据 `var/evidence/roadmap/W2-同源成果切片/`。**AD01—AD08 与用户设计阶段确认不变；不自行宣布 W2 放行。** 下方 W1 放行与各批记录保留为历史。**

**2026-11-14 W1 架构复核通过（本机 SQLite 受限范围）→ 批准 W2；W2 入口边界已先行落实：**架构师 `deliverables-for-review/roadmap/W1-lineage-architect/review-and-W2.md` 结论"W1 在本机 SQLite、明确来源、完整源谱系的已验证范围通过复核，允许开始下述 W2"，审查 HEAD `0654701`、业务实现 `b40b4fa`；独立复跑 `verify_w1_lineage.py` **13/13** 通过。**放行边界**：不保证任意损坏源数据、多进程、PG 或断电恢复，不批准正式切库；AD01—AD08 与用户设计阶段确认不变。**W2 只批准"同源成果切片"**：精确模型→可读平面→人眼效果图→受支持净量/已知成本→页面下载，同一执行器处理两种布局；不自行启动 W3 付费真实模型试验或 W4 全套成果。按架构师"先落实小边界再推进可见成果"的顺序，本步已完成 W1→W2 入口边界：①**精确 spatial 消费者**——旧矩形反馈/补丁链（`revise`）与旧深化/量价链（`ai/development-production`）对含 `spatial` 的候选一律 422 `SPATIAL_MODEL_REQUIRES_PRECISE_PATH`，**不据 bbox 算量、不静默降级**（L15/L16）；②**缺父差量禁止伪造**——新增 `spatial.adaptation.diff_baseline ∈ {source_parent, none_root, unknown_missing_parent}`，缺父且 `allow_orphan` 时不再回退到无关分支作差量，`diff=[]` 且基线标 unknown（L05/L02）；③**布尔开关严格校验**——`allow_orphan` 必须是布尔，字符串 "false" 返回 400 `INVALID_BOOLEAN`（L14）。验证：`verify_w1_lineage.py` 扩至 **16/16 observed_pass**（真实 HTTP、隔离双库、本地夹具，0 外部调用/0 密钥/0 费用），证据 `var/evidence/roadmap/W2-同源成果切片/before-boundaries/`。**尚未开始** W2 可见成果（可读平面、人眼效果图、净量/成本、页面下载、四种变更对账、Q10），下一步按架构师顺序推进；本步不构成 W2 完成，也不宣布 W2 放行。下方 W1 谱系收口与各批记录保留为历史。**

**2026-11-14 W1 版本谱系收口已交付（交架构师复核；W1 仍不放行，W2 未开始）：**架构师复核结论"W1 是有效进展，22 项 HTTP 已独立通过，但暂不放行进入 W2：版本身份与父链仍按导入顺序推断"。本批按 W1-R1/W1-R2 限定整改，**不重做适配器、不启动 W2、不改 AD**。**W1-R1 身份与父链**：候选 `option_id` 从"Studio 项目+字母"改为 `studio:{主项目}:{Studio项目}:root:{源根 revision_uid}`，A/B 只作显示名；新增 `StudioProposalSource.lineage()` 沿源 `parent_revision_uid` 回溯根谱系，缺父/成环分别 409 `SOURCE_PARENT_MISSING` / `SOURCE_LINEAGE_CYCLE`；父版本由**已导入修订的 `spatial.source.revision_uid → 主系统 revision id` 显式映射**决定，不再取"该字母最新导入"；源父未导入默认 409 `SOURCE_PARENT_NOT_IMPORTED`，显式 `allow_orphan=true` 时 `parent=null` + `parent_link_status=source_parent_not_imported` 且**不回填**；分叉两条修订共享同一父、编号仍单调（DAG 而非父子串联）；`diff` 改为相对源父修订。**W1-R2 写内并发重检**：写事务内依次重查同源幂等键、重算父映射与下一版本号，不一致则在锁内重新适配/重绘再写；set/revision/artifact 同事务提交，失败整体回滚；文件清理只删本次 `set_id` 自己的目录；无新增锁服务/队列/迁移。**来源口径**：`spatial.source.origin_kind=studio_import` 只表示传输路径，新增 `design_origin{kind: real_model|human|fixture|unknown, declared_by, declaration, run_refs}` 保留上游设计来源，未声明一律 `unknown`（适配器不是 AI，但不把上游真实模型/人工产出改标）；DB `source_kind=human_edit` 是已披露兼容取舍，未新增迁移；精确 `spatial` 仍是权威，legacy bbox 一律 `bbox_derived` 且保留 `bounding_box_only` 损失声明。**验证（全部本地夹具，0 外部调用/0 密钥/0 费用）**：`scripts/verify_w1_lineage.py` 真实 HTTP **13/13 observed_pass**（独立两组 A 不串版本；同根 v1→v2 父=源父；同父两分叉父都指 v1；乱序先子后父 409、补齐后 1→2→3；缺父 allow_orphan 留痕；源链断裂拒绝；线程屏障同源并发只出一版、同谱系并发 2/3 编号且父同一；确定性接缝同源复用/同谱系锁内重算；设计/适配来源分离；精确 spatial 与 bbox 损失；采用分叉成功、旧版 CAS 拒绝）；原 W1 22 项在**真实父 UID 夹具**下 **22/22** 回归（未放宽断言）；真实 Edge 浏览器 `passed=true`（`option_id` 含 root、45 行对账、多边形 SVG sha 一致、`adoption=null`、390px 无溢出、`page_errors=[]`）；受影响 5 模块 **55 OK**、全量 **262 OK**。**未做/未测**：W2 制图/渲染/量价与 `Q10` 未开始；多进程/PG/断电并发未验证（只单进程多线程 + 隔离 SQLite）；真实模型与真实设计评价属 W3；`revision_no` 是主系统内单调编号，与源修订号的双轨口径见 `lineage-mapping.md`。**AD01—AD08 未改判，用户设计阶段确认与正式责任闸口不变；本批不自行宣布 W2 放行。** 复核包 `deliverables-for-review/roadmap/W1-版本谱系收口/`（`review-packet.md`、`lineage-mapping.md`、`lineage-checks.json`、`positive-negative-cases.md`、`code-diff.md`、`changes.patch`、`manifest.json`、`browser/`、`runtime/`），运行证据 `var/evidence/roadmap/W1-版本谱系收口/`。下方 W1 首版与 W0 各批记录保留为历史。**

**2026-11-14 W1 统一模型适配已交付（交架构师复核；当前批准范围只有 W1）：**按 `W0-final-architect/architect-review-and-W1.md` 的顺序一次推进整批。**复用主系统、不新增第三套权威模型**：产物仍是 `rkd-ai-design-option.v1`，存入既有 `ai_design_option_sets / revisions / artifacts`；只在契约里新增**可选** `spatial` 段（精确 mm 多边形、场地/keep-out、功能分区、平台造型、家具目录引用、天花灯具与色温意向、来源/父版本/哈希、命名缺项、字段对账），**零新增 SQLite/PG 迁移、表、列**，`postgres_import.py` 白名单与快照版本未改。新增 `mvp/rkd_mvp/ai_design_studio_adapter.py`（确定性适配器 + shapely 精确多边形校验 + 多边形 SVG + `StudioProposalSource` 只读边界）；`AIDesignOptionService.import_studio_proposal` 单事务写 set/revision/artifact、幂等键按源产物 id+sha+适配器+映射+项目/组织、来源变更形成新版本且 `parent_revision_id` 指向旧版、`diff` 按同一稳定对象 ID 记录、失败全回滚并清理 SVG；4 个接口（sources / import / imports / detail）与 `AiDesignOptionsPanel` 的导入、已导入版本、字段对账、目标图面入口。**单位/对象/来源口径**：mm→m 用 Decimal /1000，稳定对象 ID 同名保留，显式 `resolve_project_id` 映射，legacy rect 一律标 `bbox_derived` 并列入 `losses`（没有把多边形静默矩形化）；材料规格、相机/视图、照度、实测标高、门窗柱网为命名缺项，`cost.budget`/`total_project_estimate` 的 `value` 保持 `None`，**unknown 不填 0**。**验证（全部本地夹具，0 外部调用/0 密钥/0 费用）**：`scripts/verify_w1_unified_model.py` 真实 HTTP **22/22 observed_pass**（布局 A/B 两种实质不同布局含 5 点非矩形分区走同一适配器、逐字段对账 A/B 各 33 行全相等且各 45 行 ledger、API/存储/SVG 字节一致、幂等、来源变更与旧字节保留、单位错配/目录缺引用/伪多边形/错误项目映射/跨项目/sha 不符/非有效候选/旧版本并发采用/中途失败回滚/重启/跨项目隔离/旧格式与历史下载兼容）；真实 Edge 浏览器 `passed=true`（页面选 Studio 源→导入→目标 v1、6 项缺项、45 行对账可见、多边形 SVG 5523 字节 sha 一致、`adoption=null`、390px 无溢出、`page_errors=[]`）；受影响 5 模块单测 **55 OK**、全量 **262 OK**、`tsc`/`npm run build` 均 EXIT=0。**候选未污染采用/生产/采购/发布**：`adoptions` 表始终 0 行，正式批准/发布/量价/订单未触发。**明确未做/未测**：W2 同源平面、人眼效果图、量价与 `Q10` 仍 `not_run`；W3/W4 未开始（真实付费设计与阶段 2/3 须用户确认）；PG 路径与正式切库未验证；源提案是明确标记的本地测试夹具，不是系统模型自动设计，不计入 AD01—AD08；`source_kind` 粗粒度枚举沿用 `human_edit`（精确来源在 `spatial.source.origin_kind=studio_import`），未为此新增迁移。**AD01—AD08 不自行改判，用户设计阶段确认与正式责任闸口不变。** 复核包 `deliverables-for-review/roadmap/W1-统一模型适配/`（`review-packet.md`、`contract-mapping.md`、`checks.json`、`field-reconciliation.json`、`models/`、`positive-negative-cases.md`、`code-diff.md`、`changes.patch`、`manifest.json`、`browser/`、`runtime/`），运行证据 `var/evidence/roadmap/W1-统一模型适配/`。**交回架构师后再明确 W2 实施范围，本批不自行宣布 W2 通过或启动 W3。** 下方 W0 受限放行及各批记录保留为历史。**

**2026-11-14 W0 工程复核通过（受限范围）→ 开始 W1 统一模型适配：**架构师 `deliverables-for-review/roadmap/W0-final-architect/architect-review-and-W1.md` 结论"W0 按当前受限工程范围通过架构复核，允许进入 W1"，审查 HEAD `cb84581`、业务实现 `3688cd4`、比较基线 `db9121e`；独立复跑 `boundary_cases.py` 10/10 `fixed_signature`、`verify_conservative_http.py` 10/10 `observed_pass`，静态核对否定/残余/绑定与 `UnresolvedRequirement` 路径，读取执行者浏览器证据（页面只输入文字、只改 F3、父版本一致、残余 pending 可见、390px 无溢出）。**放行的有限范围**：已验证的文字反馈解析边界与原 17 例/15 项/14 例/12 项等工程回归；**不是**任意中文理解证明、整库无缺陷保证、用户设计认可、AD01—AD08 通过、施工发布或生产切库许可。`Q10` 仍 `not_run`（留给 W2）；文字自动复核只支持净宽/旋转/色温/面积等有限规则，未支持否定保持 pending 且不交修订，残余诉求留痕不自动解决；净宽是有限障碍范围测量，不是门洞/墙体/家具遮挡或专业合规证明；真实模型在这些情况下的效果仍须 W3 验证。**AD01—AD08 不自行改判，用户设计阶段确认与正式责任闸口不变；阶段 1→2 / 2→3 仍只接受用户对具体版本的明确确认。** 按 docs/26 与 W0 三份契约勘误（`deliverables-for-review/roadmap/W0-收口/evidence-provenance-erratum.md` §2）执行 W1：Studio 有效提案经正式适配入口进入主系统版本化候选模型，不手搬 JSON、不新增第三套权威模型、不把多边形静默矩形化。当前批准范围**只有 W1**，交回架构师后再明确 W2 实施范围。下方 11-14 保守判定及各批记录保留为历史过程证据。**

**2026-11-14 W0 文字反馈保守判定（TEXT-01 最后收口；架构师独立确认 14 例与 12 项 HTTP 通过，W0 仍不放行）：**架构师复核结论"限定整改，不推翻已有五项整改；原三项复现已修复，但同一共用解析路径仍会反转或遗漏要求"，并给出三处边界：`不要把 F3 旋转到 -30 度` 反转为 `exact -30` 可执行目标且无 pending；`把 F1 和 F9 旋转到 -30 度` 只留 F1 并宣布 `resolved`；`把 F3 旋转到 -30 度并让整体更有设计感` 数值匹配后把整子句 consumed、尾部诉求消失。**实际整改（共用路径，不堆句子补丁）**：`revision_task` 新增"已解析片段/未解析片段 + 完整对象引用"的保守判定——`_clause_is_negated()` 先剔除已支持的比较表达（`不超过/不大于/不少于/不低于…`）与保留表达（`保留/不动/不要改…`）再判否定，命中则整项 `negated_requirement` → `unknown+pending`、**不生成相反目标**；`_clause_binding`/`_measurable_binding` 保留全部点名引用，存在+缺失并列时 `object_ids=["F1","F9"]`、`missing=["F9"]`、复核 fail，存在+名称歧义时 `ambiguous_object_names` 不验证；`_explained_spans()`/`_substantive_residual()` 按字符区间记账，掩掉已解释片段并去结构性词后**只要还有汉字就单列 `unparsed_remainder_in_clause`**（`source_text` + `residual_text`），不依赖标点、不针对"设计感"加规则；`recheck_objectives` 透出 `residual_text`/`all_object_references`/`missing_object_ids`。`orchestrator` 新增 `UnresolvedRequirement`：**规则形状的否定句在模型调用前停下**，run 记 `conflict`、0 产物、闸口列原句与 `unknown+pending`，不交出可能相反的修订。**验证（0 外部调用/0 密钥/0 费用）**：用 `git worktree` 检出整改前 `db9121e`，同一脚本对两版各跑一次——函数级 10 例：整改前 **7 defect / 3 fixed（回归护栏）** → 整改后 **10/10 fixed_signature**；真实 HTTP 10 项（全部普通 text 入口、不注入 objectives/locks）：整改前 **5 pass / 5 fail** → 整改后 **10/10**（否定与"不超过/不低于"区分、并列缺失、仅缺失、无逗号复合句、通用残余、有标点回归、保留词不误判；失败/未解析在闸口、raw 诊断与完成 note 里可见）；真实 Edge 浏览器 `passed=true`：无逗号复合句输入→数值只认 F3 且 pass、残余 `更有设计感` 为 `unknown+pending`、页面显示"未验证/待你确认：1 项"、只改 F3、无告警、390px 无溢出。**回归**：原 14 例 **14/14**、原 12 项 **12/12**、原 17 例 **17/17**、原 15 项 **15/15**、W0 专项 **7/7**、首批 Q **11 pass/0 fail/1 not_run(Q10)**、上一批浏览器 `passed=true`、全量单测 **262 OK**、`tsc` EXIT=0。证据全部写入新目录 `var/evidence/roadmap/W0-文字反馈保守判定/`，未覆盖历史。**明确未做**：未实现"不等于/不得改为"规则（否定要求只做保守拒绝）、残余片段不自动翻译成目标、名称歧义组合只在函数级夹具验证未冒称 HTTP/浏览器实测、真实模型在歧义输入下未测（无付费授权）；W1—W4 一律未开始；未改契约/几何口径/前端/AD 判定；本批**没有新增任何设计成果**，0 张人眼效果图，`Q10` 仍 not_run。**AD01—AD08 未改判；W0 是否放行由架构师复核决定，本批不自行宣布放行。** 复核包 `deliverables-for-review/roadmap/W0-文字反馈保守判定/`。下方 11-14 文字反馈收口记录保留为上一批过程证据。**

**2026-11-14 W0 文字反馈收口（架构师点名 TEXT-01；已独立复核：14 例与 12 项通过，仍有保守判定边界，见上条）：**架构师复核结论为"原五项整改有实质成效，不推翻，但普通文字反馈到结构化目标的转换会改变用户意图"，并给出三处独立复现：①`把 F3 旋转到 -30 度，其他家具不动` 被解析成 `objects_scope=[furniture]`、`object_ids=[]`、量词 all，只改 F3 反而判 fail，模型可能被诱导去转全部家具，"其他家具不动"只落成 unresolved；②`主动线净宽不超过 2400mm` 的 `comparator` 被套成默认 `min`（"不超过"被吃掉）；③`主动线净宽至少 2100mm，同时整体更有设计感` 只剩 measurable，审美诉求消失。**实际整改（只改这一条，不新建语义平台、不引入模型辅助解析）**：`revision_task` 新增共用子句解析 `parse_text_requirements`——按子句切分，逐句产出 measurable / preserve / pending 三类并保留 `source_text`、`binding_status`、`binding_match`、`object_source`；对象绑定优先级为"评审意见显式 ids → 句内 id/对象名 → 对象不存在（按缺失判 fail，不退化成整组）→ 上一子句唯一对象 → 同组被点名则 unresolved → 才用规则自带 group"；比较符识别 `不超过/不大于/最多/以内/上限/≤` → max、`至少/不小于/不少于/不低于/以上/≥` → min、`等于/恰好/正好/=` → exact，无词才回落默认值；`其他/其余/其它` + 组名词按**本消息点名对象的补集**绑定（`complement_of_named_objects`），并在 `orchestrator._resolved_text_locks` 生效为整件锁；未消化子句一律 `unknown + user_confirmed=pending` 并保留原句；`分别/各自` + 多个数值 → `multiple_values_in_clause`（不配对、不取第一个），一句里多出的数值 → `extra_values_not_parsed`；新增 `text_conflicts` 检测同一目标上不能同时成立的 min/exact/max，`orchestrator` 抛 `ContradictoryFeedback`，run 记 `conflict`、**不开模型、不用返工硬凑**、闸口列出两条出处。修 Q08 回归时发现评审意见的 `evidence`（"声明净宽 2000mm"）会被当成第二个目标，改为只把 `suggest` 当要求。**验证（真实执行；0 外部调用/0 密钥/0 费用）**：用 `git worktree` 检出整改前 `5571e4e`，同一脚本对两版各跑一次——函数级 14 例：整改前 **12 defect / 1 fixed（T05 旧实现本就正确，作回归护栏）/ 1 not_observable**，整改后 **14/14 fixed_signature**；真实 HTTP 12 项（全部走 `/messages` 正常文字入口，只发 text + 选定基线，验收脚本不注入 objectives/locks）：整改前 **1 pass / 11 fail**，整改后 **12/12 observed_pass**（含点名 F3 只改 F3、误改其他家具被 `LOCK-PRESERVE` 拦、两个对象只改一个 fail、明确"都"才整组、F9 不存在按缺失 fail、`不超过`→max 且上限正例通过、下限负例失败、数值+保留+审美三类并存且审美 pending、一句两值不冒充、同基线矛盾 `conflict`、普通单对象回归通过）；真实 Edge 浏览器 `passed=true`（选旧方案→只打文字→开一轮→只改 F3、父版本=选中旧版、无告警、390px 无溢出、`page_errors=[]`）；原 17 例复现 **17/17 fixed_signature**、原 15 项 HTTP **15/15**、上批 W0 专项 **7/7**、首批 Q01—Q12 **11 pass / 0 fail / 1 not_run(Q10)**、全量单测 **262/262 OK**、`tsc --noEmit` EXIT=0。证据全部写入新目录 `var/evidence/roadmap/W0-文字反馈收口/`，未覆盖历史；为避免重演上批覆盖事故，`verify_w0.py`/`verify_w0b.py` 只新增了可选 `--out/--runtime`（默认值不变，断言未动）。**未做/未测**：W1—W4 一律未开始；未改契约 schema、几何净宽口径、前端交互与 AD 判定；文字解析仍只覆盖净宽/旋转/色温/面积四类可计算规则，其余说法一律 `unknown+pending`（宁可说没懂，不用默认值冒充理解）；真实模型在歧义输入下的行为未测（无付费授权）；本批**没有新增任何设计成果**，0 张人眼效果图，`Q10` 仍 not_run。**AD01—AD08 未改判；W0 是否放行由架构师复核决定，本批不自行宣布放行。** 复核包 `deliverables-for-review/roadmap/W0-文字反馈收口/`（review-packet、code-diff、positive-negative-cases、changes.patch、manifest、before/、after/、browser/、runtime/）。下方 11-14 二次收口记录保留为上一批过程证据。**

**2026-11-14 W0 二次收口（架构师五项限定整改 W0-F01—F05；已复核：五项有实质成效，但文字反馈仍阻断放行，见上条）：**架构师复核结论为**"限定整改，暂不进入 W1"**（`deliverables-for-review/roadmap/W0-architect-review/architect-review.md`，其独立复跑上一批 `verify_w0.py` 得 6 pass / 1 fail，失败项 W0-R1-01 表现为"快照内找不到本 run 的新修订、parent=null"，而隔离库中该修订确实存在且 parent 正确；另附 `independent-negative-cases.json` 五类独立负例）。按用户委托**先复现、再修复、再验证**，五项一次做完：①**F01 当前任务与反馈覆盖关系**——`resolve_task` 以最新一条版本化 feedback 为当前意图，同基线多条 pending **显式合并并一次性消费**，跨基线 pending 返回 `multiple_pending_feedback` 冲突且不丢更早那条，最新已消费返回 `feedback_already_consumed`（不复活），显式 generate 意图不被历史 consumed 封死，新增 `store.withdraw_feedback` 与 `POST /studio/projects/<pid>/feedback/<fid>/withdraw` 做**显式作废**（`superseded` + `superseded_by`，正文保留）；②**F02 多对象目标不能部分达标就通过**——目标带 `objects_scope/object_ids` + `comparator`(min/exact/max) + `quantifier`(默认 all)，部分达标＝fail、对象缺失＝fail、空目标集＝unknown，净宽同时校验声明值、几何实测值、绝对下限与 CIR 现场问题并明写 `coverage` 有限范围；③**F03 未绑定的保留要求不能假通过**——`resolve_preserve_binding` 按对象 id 边界或对象 `name` 绑定，resolved 按本条对象复核，unresolved/ambiguous 写 `unknown`+`pending` 并留原句，删掉按中文关键词猜对象的 `_locked_ids`；④**F04 字段锁不能变整对象锁**——`lock_conflicts` 改字段级（`fields:["*"]` 才锁整对象），删除必冲突，未知字段/对象不存在/基线无此对象各有独立 `diagnostic`，四级校验与完整性检查复用同一函数、不再静默升级；⑤**F05 完成状态与产物快照必须一致**——`project_state` 单事务读全表并返回 `snapshot.token`，新增 `run_snapshot()` 与 `GET /studio/projects/<pid>/runs/<run_id>`，页面按 **run_id** 轮询不再读 `runs[-1]`，自动返工按**设计试验**累计落库（`runs.trial_key`、`runs.auto_rework_total`，新 run 继承不归零，上限仍为 2）。**验证（全部本地模型桩，0 外部调用、0 密钥、0 费用）**：新增 `scripts/w0b_repro.py` 17 例，整改前 **17/17 `defect_reproduced`**（`var/evidence/roadmap/W0-二次收口/before/repro.json`，12:54:07），整改后同一脚本 **17/17 `fixed_signature`**（`after/repro.json`，13:24:45）；新增 `scripts/verify_w0b.py` 真实 HTTP **15/15 `observed_pass`**（连续反馈合并、已消费不复活、续改后新生成、跨候选冲突、显式作废、非入口保留对象、找不到对象的保留要求、字段锁正负例、部分达标、比较符语义、可控晚到/取消、同快照、累计返工；用 `GatedStub` 屏障不用 sleep；其中 F05-01 证明一轮**已产出 `valid_candidate`**的修订被晚到留言判 `superseded`、有效产物 0）；真实 Edge 浏览器 `scripts/verify_w0b_browser.py` **passed=true**（合并 2 条留言、`consumed_feedback_revisions=[1,2]`、已消费后弹窗 0、冲突告警、作废后正文以删除线保留、390px 无横向溢出、`page_errors=[]`、重启持久化）；全量单测 **262/262 OK**；首批 Q01—Q12 回归 **11 pass / 0 fail / 1 not_run（Q10）**；上一批 W0 专项 **7/7 PASS**；`tsc --noEmit` 与 `npm run build` 均 EXIT=0。**事故如实记录**：`verify_w0.py` 输出路径写死且无 `--out`，重跑时覆盖了上一批 `var/evidence/roadmap/W0-收口/after/checks.json`，已用上一批交付包内副本**恢复原件字节**（sha256 前 16 位 `cb87518bb3bb0652`），本次重跑结果另存 `var/evidence/roadmap/W0-二次收口/runtime/verify_w0-rerun-checks.json`；未删除失败证据、未调宽断言、未用 sleep 制造通过。**未做/未测**：W1 统一模型适配、W2 同源平面与人眼效果图、W3 真实设计验证、W4 完整成果一律未开始；未扩 A2、未提高返工上限、未重跑付费模型；本批**没有新增任何设计成果**，图面仍是概念平面草案，0 张人眼效果图，`Q10` 仍 not_run；自动返工只在 generate 内部循环（revise 不自动重复，属已知限制）。**AD01—AD08 未改判，阶段设计结论仍由用户给；W0 是否放行由架构师复核决定，本批不自行宣布放行。** 复核包 `deliverables-for-review/roadmap/W0-二次收口/`（`review-packet.md`、`code-diff.md`、`positive-negative-cases.md`、`changes.patch`、`manifest.json`、`before/`、`after/`、`browser/`、`runtime/`），运行证据 `var/evidence/roadmap/W0-二次收口/`。下方 11-14 首次收口记录保留为上一批过程证据。**

**2026-11-14 W0 第一次收口（docs/26 第 3、4、6 节；已由架构师复核要求限定整改，见上条）：**按用户最新委托，先按接管约定读 AGENTS/交接/PROJECT_STATUS/docs/13、21、24、25、26 并核对真实 Git（base `957cf77`，工作区仅 `docs/26` 未跟踪），然后**先复现再实现**架构师 R1/R2/R3。整改前实测证据 `var/evidence/roadmap/W0-收口/before/reproduction.json`：7/7 缺陷确认——反馈指定旧基线后第二轮仍生成 2 个全新 A/B、修订 `parent_revision_uid` 指向本轮新候选；真实 `/messages` 把用户指定的 `art_414dd516b2` 偷换成 `art_f35ba7261d`；伪修复（只改目标对象颜色/名称、`width_mm` 仍 2000）被记 `verified=true`；`boss_feedback_resolutions.linked_changes` 等于全部变化；复核包编制 11-12 却内含 11-14 事件且未分别标时间；适配说明把 proposal / draft / `ai-design-option` 三份契约字段混写。**实际整改**：新增 `mvp/rkd_mvp/studio/revision_task.py`——`resolve_task()` 从版本化反馈分离 generate / revise / retry / conflict（跨候选、跨项目、旧反馈已消费、并发新反馈、失败稿、晚到结果均带 `conflict_code` 明确拒绝，不偷换不重生成 A/B），`structured_locks()` 结构化对象/字段锁（不靠中文关键词），`derive_objectives()` / `recheck_objectives()` 确定性目标复核；`orchestrator.run_a1` 同步分流并写 `runs.task_kind/target_*`，新增 `_revise_from_baseline()` 加载指定旧稿完整基线、产出新修订的 `parent_revision_uid` 指向用户选中旧版、旧版字节可下载；`store.py` additive 列 + `artifact_by_id()` + `consume_feedback()` CAS（阻止拆 run 绕过 `MAX_AUTO_REWORK=2`）；`server.py` `/messages` 严格校验用户指定旧基线（`baseline_selection=user_selected`）、`/run` 冲突返回 409、`/state` 暴露任务/版本链；`revision.verify_revision_integrity` 四态分离 `input_included / object_changed / objective_rechecked / user_confirmed`，可计算目标由几何净宽/角度/色温/面积/锁定规则实测，审美与未实现写 `unknown` + `user_confirmed=pending`，任何 fail 触发 `REV-OBJECTIVE` 全局兜底；前端新增「续改哪份旧方案」下拉与任务条/父版本对照。**R3 只补勘误不回写历史**：`deliverables-for-review/roadmap/W0-收口/evidence-provenance-erratum.md` 分别标明编制/执行/复跑补生成/提交时间及代码基线，按实际三份 schema 修正映射（proposal 无 `contract_version`/`project_id`；draft 用 `rkd-spatial-plan.v1`；`ai-design-option.v1` 用 `schema_version` 且无 `project_id`），历史 `review-packet.md` 与 `ARC-05-adaptation-note.md` 字节 SHA 记录且未改。**验证（全部本地模型桩，0 外部调用、0 密钥、0 费用）**：整改后复现 0/7 缺陷；W0 专项 **7/7 observed_pass**（含真实 HTTP 服务入口 `parent_revision_uid` 指向旧版、跨候选/跨项目/旧反馈/并发/失败稿/晚到负例、伪修复单元级与服务级被拦）；首批 Q01—Q12 回归 **11 pass / 0 fail / 1 not_run（Q10）**；全量单测 **262/262 OK**；A1 管线 15/15 PASS；前端生产构建 EXIT=0；真实浏览器 `passed=true`（页面选中旧方案→反馈→续改→父版本对照，待决闸口仅 1 个，`page_errors=[]`，390px `scrollWidth=390`，重启持久化通过）。**未做/未测**：W1 统一模型、W2 同源平面与人眼效果图、W3 真实设计验证、W4 完整成果一律未开始；Q10 仍 not_run；没有新增设计成果（无封面/正式平面/天花/立面/材料灯光板/人眼效果图/汇总 PDF）；设计来源仍是明确标记的本地桩，不是真实 AI 自动设计；AD01—AD08 不自行改判，阶段设计结论仍由用户给；未扩 A2、未提高返工上限、未重跑付费模型、未扩 NAS/PG/账号/备份配套。**停在硬节点 1**：W0 收口完成先交架构师复核，未收口不把反馈链标完成，不自行开始 W1。复核包 `deliverables-for-review/roadmap/W0-收口/`（含 review-packet.md、checks.json、code-diff.md、manifest.json、positive-negative-cases.md、证据与浏览器截图），运行证据 `var/evidence/roadmap/W0-收口/`。工程 PASS 不等于设计通过；`succeeded` 只表示流程跑完。下方 11-12 记录保留为上一批过程证据。**

**2026-11-12 ARC 首批工程整改（架构师交接 `docs/25` 第 5 节）已交付，停在交付点等架构师复核，不自行开始第二批：**本批只做 ARC-01—04 与直接相关的 ARC-06 规则修正；ARC-05 只交短小适配说明。**先复现真实缺陷**：基线 `d6501a9`，只读复现证据 `var/evidence/architecture-handoff/first-batch/before/reproduction.json`——库内最新两份 spatial-plan 各有 **66** 条 Schema 错误却被最小字段检查全部放行；100㎡ 场地 3 个各 1㎡ 分区仍判 `ok=True` 且不报告未分配；分离三角形因外接矩形被误报重叠；面积表补「通道及其他」后提示自相矛盾；非直角只数文字清单；orchestrator 有 **9 处** `[:4000]/[:3500]/[:3000]` 截断；`StudioView.tsx:47` 不论项目都选宁波；老板留言不进修订、种子每次启动重写项目事实、闸口决定重放覆盖旧记录；规范库把 469㎡/2 处非直角/60% 天花覆盖等数值包装成用户明确要求或普遍规范。**实际整改**：新增 `spatial-plan-proposal.v1` 模型提案契约（原 draft 契约未改、未放宽必填项）+ `validation.py` 四级校验（结构→语义引用→几何→锁定，原始输出与诊断存 `invalid_raw` 不作有效候选）+ `geometry.py`（复用锁定 shapely 2.1.2：真实交集/自交/越界/保留区/入口可达/实测瓶颈/家具旋转占地；唯一面积口径 `design_scope_sqm=外框−保留区`，显式输出未分配，无法验证项标 unsupported）+ `revision.py`（白名单 patch、对象保留/删除理由/锁定/逐项对应复核）+ `store.py`（版本化 feedback、CAS/预期版本与持久取消、闸口绑定基线且决定 append-only、insert-only 种子、最小增加 run_id/候选组/revision_uid/input_hash/check_report_id）+ `server.py`/`StudioView.tsx`（项目显式 ID 映射、限制入口、有效候选与历史分组、决定语义区分）+ `standards.v1.json` 与 `llm.py`（用户原话/适用范围/启发式/专业依据/程序覆盖分开；输入+输出额度预留、usage 缺失记 unknown、超时待对账、兼容降级只对明确不支持错误）。**验证（全部本地模型桩，0 外部调用、0 密钥、0 费用）**：整改前后复现对比见 `after/after-reproduction.json`（66 条契约错误全部拦截、100㎡/3㎡ 显式报 97㎡ 未分配、三角形不误报、截断 0、硬编码与重放消失）；Q01—Q12 专项 **11 observed_pass / 0 fail / 1 not_run（Q10 属第二批）**，证据 `after/checks.json`；A1 管线 15/15 PASS；新增专项单测 18/18；全量单测与前端构建通过；真实浏览器验收 `passed=true`（提交「调整洽谈区、保留入口」→版本化有效需求 v1→新修订 4 个对象 diff、切项目不显示宁波、闸口重放不覆盖、刷新持久化、390px 无溢出），截图与 `verification.json` 在 `after/browser/`。**未做/未测**：ARC-05 纵向同源适配（Q10 not_run）、真实模型第三轮重跑、A2、任何设计成果（无封面/正式平面/天花/立面/材料灯光板/人眼效果图/汇总 PDF）、专业签核、PG/NAS/账号/备份专项（管理配套冻结，仅做共用服务全量回归）。**AD01—AD08 不自行改判，仍以用户结论为准；工程 PASS 不等于设计通过；`succeeded` 只表示流程跑完**。交付包：`var/evidence/architecture-handoff/first-batch/review-packet.md` 与 `checks.json`，便携副本与代码差异在 `deliverables-for-review/arc-first-batch/`（含 `ARC-05-adaptation-note.md`、`code-diff.md`、`positive-negative-cases.md`、浏览器截图）。本批未 reset/checkout、未清理既有改动或原件，日常 `var/studio/studio.db` 与 NAS 未改动；完整差异另存 `deliverables-for-review/arc-first-batch/changes.patch`，架构师可用 `git diff d6501a9..eb6513c` 复核。下方 11-11 及更早记录保留为历史。**

**2026-11-11 A1 收口 · 补上「修订变差自动打回 + 总监看图自评」并跑完真实回路验证，方案仍未通过：按老板追加要求落地程序硬校验判据（`_qc()` / `_worse()` 比 blocker、major、面积对账差，契约无效也算变差）、`MAX_AUTO_REWORK = 2` 自动打回（第 3 轮必须交老板）、无效稿不入库不进成果栏、`Store.amend_gate()` 复用同一个待决闸口；新增 `Client.chat_vision()` 与 `mvp/rkd_mvp/studio/vision.py`，总监只发本项目自己生成的 3 张图（候选 A / B 平面草案 + 一张冻结的宁波方案 A 第 3 版效果图作案例参照，明确标注是人工手工样板），不发 CAD/PDF/预算表/现场照片，输出结构化观感并写明「观感不作判据、不得据此宣布通过」。网页新增「自动打回」「看图自评（观感，不作判据）」标签与图片数/来源/字节/token 依据。真实模型又跑三轮：21:52 轮 `incomplete`（评审意见没落实）、22:06 轮 `failed`（模型把 `area_table` 写成 dict / 条目写成 str，旧 `check_plan()` 抛 `AttributeError`）、22:21–22:33 最终轮 `succeeded`（仅指流程跑完）。崩溃已修：`check_plan()` 重写为不可信输出防御版，格式错转成结构化 blocker；`_qc()` 兜底捕获工具异常；`plan_is_valid()` 要求面积表是非空对象数组；`sketch.py` 跳过非 dict 条目；失败记录保留在闸口详情里不删。最终一轮实数：2 个候选、17 条评审意见、看图自评 3 张图、自动打回 2 次、被接受的修订版 0 个、相对 v1 改动 0 个对象，最后拦下原因「分区少于 3 个（或根本不是列表）」；基准 v1 硬伤 blocker 1 / major 1 / 面积差 250.9㎡（面积表 430.1㎡ vs 分区轮廓 179.2㎡）。闸口标题「自动打回已用尽 2 轮仍无有效修订：请决定第 3 轮怎么做」，等待中的闸口只有 1 个，成果栏只有 A/B 两份候选。token 实测：三轮 183,947 / 245,937 / 245,868，项目累计 **1,001,374 / 2,000,000**（单次上限 600,000 未触发）。`scripts/verify_studio_loop.py` 假模型管线 12 项全 PASS（测试把位图转换换成占位字节，与本机浏览器/Pillow 解耦，不冒充真实看图）；看图自评需要 Pillow，`.venv` 未装时会写「看图自评没能完成」的 note 而不假装看过图。证据：`docs/evidence/a1-studio-rework-vision.png`、`a1-studio-vision-review.png`、`a1-studio-auto-rework.png`、`a1-studio-rework-vision-detail.png`，完整记录 `docs/24-A1-设计公司骨架.md`。**如实说明**：打回机制跑通了，但模型仍交不出契约合规的修订稿，不能拿流程跑完当设计达成；自由协作、3 个概念发散、顶面图落成、schema 级契约校验、费用单价仍未做。密钥仍只在当前会话环境变量、不落盘不提交。**A1 到此停下，等老板决定第 3 轮，不进 A2。**下方 11-10 记录保留为过程证据。**

**2026-11-10 A1 收口 · 真实回路已跑通，但方案未通过（闸口等老板）：用本会话此前提供的 `api.codelink.chat` / `gpt-5.6-sol` 密钥（只在会话环境变量，不落盘）跑了两轮真实模型回路。第 1 轮失败：D2 用光工具轮次没交出候选 JSON，旧代码仍把空方案存成产物、照常评审、开闸口并标 succeeded；失败记录保留，闸口归档为「未经老板决定」，运行记录更正为 incomplete。修了四处：产物有效性校验（无效即 incomplete，不进评审）、发言末轮强制禁工具给结论、修订必须有逐条回应且 v1→v2 真有对象变化、token 台账改按 runs 表计项目累计（旧口径把累计值写进每条消息，页面虚高到 51.8 万）。第 2 轮跑通完整往返：任务书、D2↔D3 讨论、两个拓扑不同候选（A 11 分区/5 家具、B 9 分区/4 家具）、R 12 条结构化评审（挂对象、引 STD 编号、给改法、结论 revise 且不写通过）、D2 逐条回应 10 条接受 4 条、v2 实际改动 17 个对象、闸口交老板。**程序硬校验如实报忧**：A v1 0 blocker/1 major，A v2 反而 1 blocker/9 major（面积表 430.2㎡ 对不上轮廓 692.5㎡），因此闸口标题改为「本轮成果仍有硬伤：请决定是否继续打回」，不宣布可用。token 实测：第 1 轮 152,952、第 2 轮 172,670、看图探测 9,870，项目累计 325,622 / 2,000,000。**看图能力确认支持**：只发自家生成的效果图与平面草案各 1 张，模型均正确描述图中内容。网页新增按轮次分隔、失败轮标记、JSON 交付物转可读摘要、闸口补充硬校验数字；截图 `docs/evidence/a1-studio-final.png`，完整记录 `docs/24-A1-设计公司骨架.md`。仍未做：自动返工（A3）、自由协作与概念发散（A2）、案例库对照、正式出图（M1）、schema 级契约校验。按约定停在 A1，不进 A2。**

**2026-11-10 A1 · 设计公司骨架（已搭好，等密钥跑真实回路）：用户明确系统是"AI 组成的室内设计公司"，不是固定流水线；停止手工打磨宁波。本批落地 `mvp/rkd_mvp/studio/`（独立 SQLite `var/studio/studio.db`，不碰冻结的生产库与服务）：6 个角色（P 项目经理 / D1 需求任务书 / D2 空间规划 / D3 概念与天花灯光 / D4 深化出图 / R 设计总监）、共享工作台（任务、消息含依据、产物版本、评审、闸口、运行与 token 台账）、工具层（场地/需求/规范/家具目录/几何校验）、`contracts/v1/spatial-plan-draft.schema.json` 交接契约、`knowledge/design-standards/standards.v1.json` 规范库种子 10 条（每条带老板原话出处与可校验方式）。A1 回路脚本：P 拆活 → D1 任务书 → D2↔D3 动手前讨论（STD-007）→ D2 两个拓扑不同候选并自检 → R 逐条评审（问题挂对象、引规范、给改法）→ D2 逐条回应并出修订 v2 → P 开闸口等老板。网页新增「设计公司」页（`/?view=studio`）：花名册实时状态、时间线每条可展开依据、成果栏（候选草案缩略图 + 版本化 JSON）、闸口批准/驳回（驳回必须写理由）。**已验证**：管线用假模型回答跑通 9/9（`scripts/verify_studio_loop.py`）、网页渲染与 CORS 实测、无密钥时明确返回 409 不假装跑。**未验证**：真实模型回路（本会话无 `RKD_AI_API_KEY`，0 次调用、0 费用）、真实评审质量、token 实测。按用户要求 A1 完成后停下，不进入 A2；出图仍归 M1 通用生成器。**

**2026-11-10 第十批 · 方案A 第3版（六视角 + CC0 真实素材，停下等用户验收）：用户判第2版“所有图都一样：同一个视角看同一个中岛”，要求 5 个画面覆盖各功能区、光线要有变化、相机写进数据并标在平面图上，同时上真实 PBR 贴图与 CC0 家具模型。本批完成：① **6 个机位**（C0 序厅·接待 / C1 入口看中岛 / C2 中岛特写 / C3 北光廊 / C4 南侧生活场景 / C5 整体鸟瞰），机位 eye/target/lens/光线预设全部写入 `方案A_设计数据.json` 的 `cameras`，平面图用橙色相机符号 + 虚线扇形视域 + 右侧「效果图视点 VIEWS」表（C0–C5，18/19/26/22/26/18 mm）标出，可逐张对照；**5 套光线预设**（morning / bright / afternoon / evening / aerial）只调光照不动设计。② **CC0 素材**：`scripts/fetch_cc0_assets.py` 从 Poly Haven 下载 6 套 PBR 贴图（白橡木饰面、玫瑰木饰面、莱姆石、乳胶漆、微水泥底、羊毛圈绒）与 10 件家具/器物 glTF 模型（沙发、单椅、餐椅、餐桌、茶几、圆桌、吧椅、绿植、陶罐、木碗），全部 CC0 1.0，来源/作者/授权/SHA-256 记入 `assets/CC0-素材清单.json`（进版本库），二进制存 `tools/assets/`（33 MB，已 gitignore）。③ **场景升级**：家具按设计数据尺寸缩放替换几何体；地面加 3 m 分缝、90 mm 踢脚、墙顶 20 mm 阴影缝；玻璃隔断改细铜框；接待台改实体前台；补出保留楼梯踏步；四组展台样品重做（石材样块/木饰面板样/金属型材段/织物样册）；入口门洞补日光板。④ **展品如实**：施工图、预算 xls、3 张现场照片里都没有协诚的产品清单（照片是毛坯），因此不做猜产品，按本项目主材做四组示意样品并在数据与页面写明。⑤ 交付：6 张 1400 × 880 Cycles 110 采样效果图、1:100 平面图（含 C0–C5）、`阶段2_方案A.pdf`（10 页 A3）、18 个文件 26.8 MB 副本在 `deliverables-for-review/ningbo-xiecheng/2026-11-10/`。**如实说明**：比第2版在看得懂上前进一大步（六个功能区各自成立、光线有区别、材质是真实贴图），但仍**不是客户交付级**——石材台面偏奶白且纹理被压平、家具是缩放通用模型款式不对、展品是几何体搭的示意样品、翼墙像木盒子且挂画无内容、窗户过曝、无人物与软装细节、鸟瞰是揭掉天花而非轴测、仍缺立面/天花/材料板/节点 4 类成果；差距逐条写在核对页第⑧节，不宣称通过。本轮**外发图片 0 张、费用 0**（未使用图像通道）。系统自动生成设计按用户要求本轮不动。管理配套继续冻结。**

**2026-11-10 第九批 · 方案A 第2版（已被六视角版本取代，保留为过程记录）：用户对第1版平面与效果图给出四条意见——中岛不要方正、平面图整理（全部图元命名／区域名放大／卫生间画洁具／面积表补「通道及其他」凑 469 ㎡）、效果图「没有材质、没有家具和展品、像白模」、验收要达到设计公司交付级。① 中岛外轮廓仍 7.0 × 4.8 m，改为三级圆角台 R1560 / R1360 / R1180（逐级内收 360 mm，抬高 180 / 420 / 720 mm），吊顶 R2400 圆角环形灯槽与之同形；另加 3 处非直角：入口 R4660 弧形胡桃木品牌墙（凹面正对入口）、展墙翼 02 与 04 各斜 12°，全场共 4 处非直角。② 平面图重排：6 道墙/玻璃隔断、45 件家具、4 个展台、6 件洁具、5 组窗全部进 18 项图例或家具清单，无名线全删；区域名 360–440 pt 带白色描边光晕并挪到空地，每区加一行说明；卫生间重画 3 组坐便器（水箱 + 内外椭圆 + 隔断）、台盆 ×2、淋浴间 1.5 × 1.5 m，共 6 件与「洁具 6 件」一致；面积表 11 行合计 **469.0 ㎡**（含「通道及其他」117.4）。③ 效果图改由**真 Blender**：Blender 4.2.9 LTS 免安装版下载到 `tools/blender/blender-4.2.9-windows-x64/blender.exe`（386.9 MB，未装进系统），`scripts/render_blender.py` 从同一份 `方案A_设计数据.json` 程序化建 461 个对象——微水泥／暖白橡木／胡桃木／石材／布艺／哑光铜／长虹玻璃 7 类程序化材质，北向 3 段窗做发光天空板 + 太阳光，4 组筒灯 + 5 只轨道射灯 + 环形灯槽 + 铜质吊灯，45 件家具、4 组展品（车削陶瓶／立石／铜钵／叠放布样）、4 株绿植；相机 1.52 m 人眼高度、30 mm、从入口看向中岛；Cycles CPU 128 采样、1400 × 880、用时 424 s。④ 交付：`var/deliverables/ningbo-xiecheng/2026-11-10/打开我看.html` + `阶段2_方案A.pdf`（5 页 A3），非忽略目录副本 `deliverables-for-review/ningbo-xiecheng/2026-11-10/`（12 个文件，9.26 MB，SHA-256 已逐个核对）。**如实说明**：这版效果图比第1版有材质、有家具、有展品、有窗光与灯槽，但仍**达不到设计公司客户交付级**——石材台面像抹灰无纹理拼缝、四个展台是圆柱加车削体、家具仍是几何体、左三分之一偏暗偏空、地面无批刀痕无反射、无人物与软装细节、只有 1 个视角；这些差距已逐条写进核对页第 ⑥ 节，不宣称通过。本轮**外发图片 0 张、费用 0**：`RKD_IMAGE_API_KEY` 在本会话环境中不存在，路线 B（图像通道）未调用。管理配套继续冻结。⑤ 诚实披露：方案 A 的设计数据（分区、动线、家具、材料）是**我手工编写**的常量，不是系统模型从需求自动生成的；改造计划见本批对话回复。**

**2026-11-10 第八批 · 阶段2 方案A 第1版（已被用户否决，保留为负例）：按用户对阶段1的核对意见完成两件事。① 底图只改标注：要素拆成三组（建筑固有条件／奥创原设计仅参考／待现场复核），补北墙 3 段 5400 窗带与 4 处 600 窗间垛、东墙 2 段三线窗；原「8 个疑似柱」核实为同一六边形展台内 1 个圆环 + 4 个 20 mm 圆心标记，明确写「未发现结构柱」；`底图数据.json` 升为 v2，`阶段1_底图核对.html/.pdf` 重出。② 方案 A「中央中岛 + 环游叙事」：一份 `方案A_设计数据.json` 同时驱动 `02_方案A_平面布置图.svg`（1:100，三级中岛 7.0×4.8 m、2 m 环游、5 道垂直展墙翼、南北两个生活场景、两间玻璃隔断洽谈室、材料/图例/标题栏）与 `03_方案A_效果图_01.png`（1600×1000，本机自研 CPU 光栅渲染器 `scripts/render3d.py`：透视相机、近平面裁剪、z-buffer、窗洞日光追迹、灯槽阴影、SSAO、泛光）。评审入口 `var/deliverables/ningbo-xiecheng/2026-11-10/打开我看.html`（+`阶段2_方案A.pdf`），非忽略目录副本 `deliverables-for-review/ningbo-xiecheng/2026-11-10/`（12 个文件，4.7 MB）。**如实说明**：`RKD_IMAGE_API_KEY` 在本会话环境中不存在，`tokeasy.ai` 通道未测（0 请求、0 费用、0 外发），效果图完全是本地 3D 直出，属"体块 + 光"级别，达不到 V-Ray/Enscape 照片级；天花、立面、情绪板、另外 2 张渲染图按用户"阶段2只出两张"的要求未做；方案 B 未动。管理配套继续冻结。

**阶段 1 可见交付（2026-11-10，已由用户核对认可，第2版见上）：双击 `var/deliverables/ningbo-xiecheng/2026-11-10/打开我看.html`，可看到 `00_原始平面图_正向.png`（宁波 A3 原图转正）、`01_真实场地底图.svg`（26.17×17.92m 真实场地，绿色=解析确认／橙色虚线=待现场复核）、`01b_几何叠加层.svg`（叠在原图上，可滑块微调）、`阶段1_底图核对.pdf`（5 页汇总）、`底图数据.json`、`图像通道测试.json`。阶段 1 只出底图，未产出设计方案成果；用户确认后才进阶段 2。管理配套冻结，进度只按「能打开什么」记录。**

**当前主线（2026-11-10 第七批 · 按用户否决返工）：用户对第六批两个真实 AI 候选明确回复「两个都完全不可以」，要求「去参考网络上真实的平面图，先学习真实的设计师怎么设计布局」。这是 AD08 真实负例，已如实记录，不代签、不改分母。本批实际查看公开展厅平面图并研究规范/教材/案例/同行评议论文，新增带来源、版本化的 `design_reference.py`；把「先叙事→选拓扑→排功能层级与节奏→落几何」写进真实模型提示，输出形状扩展为叙事、zone_role/sequence_role、片墙、家具（前台/吧椅/洽谈桌椅/储藏茶水/绿植/中岛焦点）与入口门斗；重写 `render_svg` 为接近真实平面图的概念图纸（粗实线墙体、门洞与门扇弧线、动线箭头、家具轮廓、尺寸线、图例、指北针、标题栏、中英文图注）。真实模型在 v2 提示下重新产出两个通过全部硬检查的方案（`hub-branch` / `brand-loop`，各 15 个对象，含前厅/主展/深度洽谈层级、服务前台、洽谈桌椅、片墙、绿植、储藏茶水与视觉焦点），端到端 `passed=true`；评审页 `var/review/2026-11-10/real-design-review.html`（+PDF）用当前制图程序从持久模型现场重绘图面，消除文字重叠，零额外模型调用。**剩余限制如实说明**：分区仍为矩形、边界仍是测试参数、未表达柱网/门窗/楼梯，右侧留白来自模型布局选择；图面是概念平面不是施工图，未宣称消防/疏散/无障碍合规；v3 提示（更多片墙围合）将在下次生成生效。仍需用户对这版具体图面再给反馈，未认可前不宣称设计通过。下方为第六批历史。**

**2026-11-09 第六批历史 · 真实 AI 接替设计：用户明确要求「真实 AI 接替需要设计的地方，像真实设计团队一样，只是把设计师换成 AI」，并临时提供 OpenAI 兼容通道。**已落地：需求理解、两个概念候选、自然语言反馈修订全部改由真实语言模型（`gpt-5.6-sol`，`https://api.codelink.chat/v1`）完成；程序仍只做几何硬检查、落模、工程量、图纸与责任边界，不再拿合成/规则适配器冒充设计能力。真实模型做概念、动线、分区、材料氛围与取舍；校审不通过时程序把错误与修复建议退回模型限次重画，仍不通过则明确失败、不写入候选。新增 `RealModelDesignOptionProvider`、真实通道配置/运行日志台账、需求理解输出模板与有限传输重试；`start-ai-real` 启动方式；`scripts/verify_real_design.py` 端到端 **passed=true**（真实需求理解→两个真实候选→真实反馈修订→同源深化/7 类技术成果），负例专项 **8/8** 用本地协议桩验证未配置/401/超时/畸形/同质候选均不回退合成。密钥只在服务端进程环境变量，不进任何文件、数据库、日志、前端或 Git；默认不外发项目资料（`RKD_AI_EXTERNAL_CONTEXT=false`）。真实候选评审页 `var/review/2026-11-09/real-design-review.html`（含 PDF、真实 SVG、模型用量、AD08 四问）。**AD01—AD08 仍按固定验收逐项判定，本批不自行改判通过数**：AD01/AD03 工程证据已齐备，AD02/05/06/07 待补证，AD08 只能由用户对具体图面给出；不以工程测试数或模型自评代替设计与专业验收。仍需用户决定调用费用上限与资料外发范围，并对真实候选给反馈。下方为第五批历史。**

**2026-11-09 第五批历史：用户未给模型通道或图面反馈，本批自主补齐真实环境证据，并修复由此暴露的缺陷。① `postgres_import.JSON_FIELDS` 漏 014 三表 jsonb 列（真实 PG 导入必失败）；② `postgres_api_service` 未装配两项新服务且路由白名单缺 3 条（PG/团队模式新页不可用）；③ 新增迁移后 4 处硬编码版本未同步；④ 账号浏览器脚本登录后未等项目列表加载的竞态；⑤ 沙箱代理打断回环浏览器请求；⑥ 新页 390px 窄屏横向溢出 9px。新增可复跑 `scripts/verify_postgres_delivery.py`（隔离 PG17：014 三表 jsonb 往返、RLS、租户隔离、伪造写入拒绝、PG 仓储分支、成果字节对账）与 `scripts/verify_delivery_browser.py`/`.cjs`（真实点击解析原件→查看来源片段→生成 7 类成果→UI 下载校验→桌面/移动截图）。专项 **17/17**、全量 **236/236**、严格环境检查、前端构建通过；完整 `verify_postgres.py` **passed=true**（live 16/45/8、57 表/733 行/74 文件导入对账、75 表完整恢复、真实数据库重启、账号浏览器全流程）。设计策略仍是明确非 AI 的合成适配器；真实模型调用、用户实际设计评价、专业技术签核与 **AD01—AD08 仍为 0/8**。仍需用户按 `var/review/2026-11-08/design-review-2026-11-08.html` 给图面反馈并决定模型通道/费用/资料外发范围；内部继续 AD01—AD07 留证与 P3 技术深度。日常 SQLite 权威库与 NAS 未改动。下方各日期记录保留为对应批次证据。**

目标仍是“自主运行的数字化室内设计公司操作系统”。用户已确认先交付本地可操作系统，再根据实测迭代。M1 提供项目、原件、任务、预算和真实导出；M2 受控空间链已形成真实成果包。M3 首个矩形展厅场景已接通需求编辑→规则分区→可编辑二维模型→硬约束检查→同基线成果→历史/重启恢复；M4 两条闭环已完成工程验收。M5-01 本机账号/项目角色/文件授权切片完成 MA01—MA08 工程验收。M5-02 已完成当前计划内各业务域的 PostgreSQL 适配及本机工程验收：45/45 业务、8/8 身份、16/16 内核，40 张表/733 行/74 个文件迁入对账通过。M5-03 的 SQLite/PG 完整本地恢复及应用/数据库重启通过；日常业务入口仍使用 SQLite，NAS 候选部署按 M5-04 推进，尚未正式切库。M5 整体、团队上线及专业生产批准仍未完成；规则草稿不冒称 AI 或正式施工成果。

当前实施基线：[`docs/13-产品交付执行计划与设计.md`](docs/13-产品交付执行计划与设计.md)第12.7—12.9节；详细目标/架构/任务附件：[`docs/21-平台最终目标与总体架构实施蓝图.md`](docs/21-平台最终目标与总体架构实施蓝图.md)。本文件是唯一动态进度台账。`AGENTS.md`约束后续接管，旧文档的资料索取和封板顺序不阻塞当前AI设计主线。

**2026-10-30 历史部署基线（当前增量见任务台账）：首位个人管理员已实际初始化；FN NAS 私有 HTTPS 入口正常：`https://fnos-nas.tailcca6f8.ts.net:9443/`。密码现为8–128字符。NAS Linux全量182/182、ASGI专项4/4、PG16业务45/45+身份8/8+内核16/16，后续身份9/9通过。含个人账号的新在线完整备份、58表/74文件/252应用文件隔离恢复及Windows异机副本校验通过；凌晨03:15备份、每分钟7项巡检已安装且巡检由cron实际触发通过。M5-04仍未整体验收：主动外部通知、定期异机备份/恢复及团队持续试用未计完成；本机SQLite仍是原日常权威库，未正式切库。**

### 2026-11-08 AI-DESIGN-01a/01b/01d 本地工程切片（已交付，未计 AD 通过）

- 新增 `contracts/v1/ai-design-brief.schema.json`、SQLite 021 / PostgreSQL 011 迁移、SQLite/PG 显式仓储、服务端 ModelProvider 边界和持久 AI 需求理解作业。任务记录输入快照、来源清单、配置版本、提示版本、尝试、用量摘要、费用已知状态、错误和候选任务书修订；模型调用在短数据库事务外。新表已纳入 PostgreSQL 导入映射，未切库或改动 NAS。
- 真实 OpenAI 兼容通道由服务端环境变量显式配置；未配置、限额、超时、HTTP 错误、畸形输出及未知来源 ID 均产生可见失败记录，不退回合成/规则结果冒充 AI。密钥不进入数据库、日志、前端或 Git。默认不外发项目资料，本切片不解析原件内容；费用未知保持 unknown，超时可能计费保留 pending_reconciliation。
- `web/src/AiRequirementPanel.tsx` 已接“需求”页：自然语言输入、立即返回作业编号、真实阶段状态、任务书来源/假设/冲突/最少补问/成本缺项、模型运行记录和人工编辑保存。默认 `start` 显示真实模型未配置；`scripts/rkd.ps1 start-ai-synthetic` 只启用明确标记的本地合成测试通道（非真实 AI），不联网、不读取其他软件密钥。`mvp/README.md` 已记录运行与真实通道配置边界。
- 新任务书是候选，不改变当前设计、量价、成果、采购草稿、批准或发布状态；旧 `showroom-layout.v1`与设计保存→生产同步链保持只读兼容。相反需求现在会在结构化任务书中产生不同设计意图，但**尚未造成实际设计模型差异**，因此 AD02/AD03 不通过。AD01—AD08 仍为 **0/8**。
- 真实验证：专项 **11/11**、严格环境检查通过、全量 **203/203、0 失败/0 跳过**、前端生产构建成功（保留既有 PDF.js 大包告警）、OpenAPI JSON 与新增模块语法检查通过。OpenAI 兼容适配器只用本地协议桩验证解析/用量/错误路径；**没有真实付费模型调用、没有真实 PG AI 作业、没有浏览器设计候选、没有 NAS 部署**。证据 `var/evidence/ai-design-01/2026-11-08/verification.json`。
- 当前无需用户补资料或提供密钥。下一工程动作仍是 01c/01e→02a—e/03a—e：把任务书交给候选生成，形成实质不同的可计算图面、材料意向/已知成本缺项、自然语言反馈、锁定与显式采用；真实模型通道、费用或商业资料外发范围需要实际联调时，再提出具体接入方案。此切片不新增无关管理配套。

### 2026-11-08 AI-DESIGN-02/03 本地候选与反馈切片（已交付，未计 AD 通过）

- 新增 `contracts/v1/ai-design-option.schema.json`、SQLite 022 / PostgreSQL 012 迁移、显式仓储、L1 通用几何校验器、候选集/修订/采用/成果模型及工作台“AI 候选”页。新模型支持不同入口侧、障碍、环形/支状通路、功能区、展台和隔断意向；验证边界、避障、非重叠、通路宽度、连通、入口可达、足够连接区段、最小面积和稳定对象 ID，不再要求所有区域接触旧底边通道。新表已纳入 PostgreSQL 导入映射。
- 明确标记的合成设计适配器从已保存结构化任务书生成两个实质不同、可计算、带真实 SVG 字节/哈希的候选；同边界相反需求会改变入口侧、材料意向和结构签名。反馈可生成新修订，“更开放但保留入口”改变实际对象并保留入口，冲突/锁定/旧版本/障碍/窄通路/同质候选均明确拒绝。对象 diff、策略取舍、材料意向、成本已知部分与缺项、硬检查均可查看。
- 显式采用用 CAS 写入“当前草稿”指针，`production_task_status=not_started`、`formal_approval=false`；候选生成、反馈和采用均不触发 `design_service.create_design`、`production_service.sync`、量价、采购、订单、批准或发布。旧规则模型/成果保持兼容，SQLite/PG 新表进入完整恢复范围。
- 真实验证：专项 **8/8**、严格环境检查通过、全量 **211/211、0 失败/0 跳过**、前端生产构建成功、OpenAPI/新契约/新模块语法检查通过。证据 `var/evidence/ai-design-02-03/2026-11-08/verification.json`。HTTP 实测候选提交与 SVG 下载通过。
- 边界：设计策略仍来自明确非 AI 的本地合成适配器；没有真实付费设计模型调用、真实 PG AI 作业、浏览器截图、真实用户设计评价或同源量价成果。**AD01—AD08 仍 0/8**；工程负例通过不等于固定验收项通过。
- 当前无需用户补密钥或资料。下一工程动作转为 AI-DESIGN-04↔05：在已采用的有效候选上逐类增加构件/材料/三维表达，并复用同一对象集接回受支持工程量、量价和真实成果；真实模型通道/费用/外发范围实际联调时再提出具体接入方案。

### 2026-11-08 AI-DESIGN-04/05 同源深化与量价草稿（已交付，未计 AD 通过）

- 新增 `contracts/v1/ai-development-package.schema.json`、SQLite 023 / PostgreSQL 013 迁移、显式仓储、确定性深化/计量/计价模块、独立作业服务和“深化量价”工作台。新表已纳入 PostgreSQL 导入映射；不调用旧 `design_service.create_design` 或 `production_service.sync`，不创建采购订单、付款、正式报价或发布。
- 只有“已采用且硬检查通过”的候选可提交深化量价。同源包从该候选派生材料表面、展陈/家具、隔断与入口对象，生成模型驱动 glTF（节点 extras 保留对象 ID）、等轴测 SVG、平面 SVG、对象工程量 CSV、量价 HTML、development JSON、manifest 和 ZIP；每个成果登记字节数与 SHA-256，下载再次校验。采用基线被反馈修订或重新采用后，旧包标记 `source_outdated` 但保留可读。
- 功能分区净地坪面积由 Decimal 确定性计算并进入本地试算；成本加成默认 0.20、试用税率默认 0.05，单位成本缺失时所有金额保持 unknown，不填 0。展示对象仅计数、隔断仅记录二维长度；通路、材料产品、损耗/包装/起订量、天花灯具、正式税务和专业审签保持缺项。地坪小计不冒充全项目总价，5% 税率不冒充正式税务结论。
- 采用指针的生产任务状态从 `not_started` 推进到 `queued/succeeded/failed`；并发旧采用版本、同键异设置、未采用、采用过期、成果字节篡改均明确拒绝。候选、采用、当前草稿、正式批准、发布、采购事实继续分开。
- 真实验证：专项 **8/8**、严格环境检查通过、全量 **219/219、0 失败/0 跳过**、前端生产构建成功、OpenAPI/新契约/新模块语法检查通过；HTTP 实测提交、状态与成果下载通过。证据 `var/evidence/ai-design-04-05/2026-11-08/verification.json`。
- 边界：仍是确定性工程链，没有真实付费设计模型调用、真实 PG AI 作业、浏览器截图、真实用户设计评价、完整专业图纸/全项目量价或正式责任验收；**AD01—AD08 仍 0/8**。当前无需用户补密钥或资料；下一阶段仅在实际模型通道/费用/资料外发、具体图面反馈、专业责任或正式切换需要时提出具体问题。

## 当前任务台账

### 2026-11-10 按用户否决返工：参考真实平面图重学布局（已交付，设计仍待用户评价）

- **用户真实反馈（AD08 负例）**：对第六批两个真实 AI 候选（`branch-salon` / `loop-core`）明确回复「两个都完全不可以；我需要你去参考网络上真实的平面图先学习真实的设计师怎么设计布局的」。已写入评审页第 0 节与本台账；不是认可、不是待调整，是明确否决并要求返工。不由模型自评或自动测试代签，AD 通过数不自行改判。
- **诊断**：旧 `render_svg` 只画彩色矩形 + 文字 + 抽象动线；布局逻辑是「先画动线骨架再塞矩形分区」，与真实设计师「先定叙事 → 选拓扑原型 → 排前厅/主展/深度洽谈/后勤层级与节奏 → 最后落几何」相反。这与用户此前多次反馈的「块状分区缺少设计思考」是同一问题。
- **网络研究（真实执行）**：`domain_search` 综合 + WebSearch 定向 + WebFetch 提取图片 URL + 实际下载并查看 2 张公开平面图（金堂奖「往来无白」300㎡ 一层/二层），另研究设计本 560㎡ 平面布置图/轴测图说明、600㎡「一轴四区」、MiSUMi 单向叙事、南京博物院二期、WW/T 0089-2018、《展示设计》教材、《博物馆设计：故事、语调及其他》、行业指南与 FOAR 2025 视域图论文。来源清单与要点在 `mvp/rkd_mvp/design_reference.py`（12 项，`rkd-design-reference.v1`），图片只存 `var/evidence/design-research/2026-11-10/` 不外发。
- **落地改动**：新增 `design_reference.py`（来源化要点 + 4 类拓扑原型 + 7 条原则 + 图纸表达约定，经 `prompt_brief()` 注入真实模型提示）；`ai_design_option_provider.py` 的提示与输出形状扩展（narrative / zone_role / sequence_role / walls / furniture / focal_point / entrance_buffers），`_to_model` 把设计意图映射到版本化对象的 `properties`，`parent_object_id` 改为 `properties.intended_parent` 以避免 Shapely 浮点贴边伪失败；提示与适配器版本升到 `v3`（v2 为已通过证据所用）。重写 `ai_design_geometry.render_svg` 为概念平面图：粗实线墙体、入口门斗与门扇弧线、动线虚线箭头、按 `furniture_type` 画前台/吧椅/洽谈桌椅/中岛/绿植/储藏轮廓、`zone_role` 材质填充、尺寸线、图例、指北针、标题栏与中英文图注；第二轮又去掉堆叠的家具文字标签、把分区名与面积分置上下、移开焦点标签以消除重叠。
- **真实模型新候选**：`scripts/verify_real_design.py` 端到端 **passed=true**（证据 `var/evidence/real-design/2026-11-10/run-20261109T231902-f19989/verification.json`），两个方案 `hub-branch`（中心枢纽 + 分支口袋）与 `brand-loop`（叙事环游），各 **15 个对象**、`zone_roles` = foyer / primary_display / deep_talk、含服务前台、洽谈桌椅、储藏茶水、绿植、中岛视觉焦点、片墙与入口门斗，并写出「入口第一眼看到什么、高潮放在动线约 2/3 处」；反馈修订与同源深化/7 类技术成果均通过。设计模型台账 5 条、累计输入 69325 / 输出 18914 tokens，金额 unknown。
- **评审材料**：`var/review/2026-11-10/real-design-review.html`（+ PDF、JSON 快照），由 `scripts/build_real_design_review.py` 生成；新增第 0 节说明用户否决、实际看过的真实平面图、提炼的 5 条方法与来源边界。图面改为**从持久模型用当前制图程序现场重绘**，不改模型、不改已登记成果字节与哈希，避免展示旧渲染器的重叠标签。
- **版本差异（如实）**：已通过的真实调用使用 v2 提示/适配器；当前代码为 v3（增加片墙围合要求与父引用规范化），下一次生成才会生效。最后一次 v3 完整链重跑被长任务超时中断，未产出新证据，未重复计费。
- **剩余限制**：分区仍为矩形、边界仍是明确标记的测试参数、未表达柱网/门窗/楼梯/结构，右侧留白来自模型布局选择；概念平面不是施工图，未宣称消防/疏散/无障碍合规，专业复核 pending；参考数值仅作方法学习，不替代当地规范与审图意见。用户尚未对这版图面给反馈，设计质量未获认可。
- **下一步**：请用户按评审页对 `hub-branch` / `brand-loop` 两张新图面再给具体评价；若仍不认可，需继续补几何能力（多边形分区、墙体围合、柱网/门窗与真实尺度校验），而不是继续加管理配套。内部可继续把研究要点扩到深化图与材料做法、补 AD02/05/06/07 证据；仍需用户决定费用上限与资料外发范围。

### 2026-11-09 真实 AI 接替设计（已交付，AD 按固定验收逐项判定）

- **方向变更**：用户要求真实 AI 承担设计判断，而不是继续用合成适配器。提供临时 OpenAI 兼容通道后，需求理解 / 双概念候选 / 反馈修订三处全部改由真实模型完成；`SyntheticDesignOptionProvider` 只保留为工程回归通道，不再是唯一设计能力。
- **实现**：`ai_design_option_provider.py` 新增 `RealModelDesignOptionProvider`（真实调用、结构化输出映射、几何校审退回与限次重画、运行台账）、真实通道 `DesignOptionConfig` 字段与 `load_design_option_config`；`ai_design_option_service.py` 放开三处合成通道硬编码（`submit` 配置判定、`_validate_candidate` 的 `real_model` 校验、`status.configured`）；`ai_model_provider.py` 增加契约有效的 `BRIEF_OUTPUT_TEMPLATE`、明确字段纪律与失败详情；`ai_requirement_service.py` 增加一次有界网络重试并记录 `transport_attempts`。候选契约 `ai-design-option.schema.json` 无需改动，其 `real_model` / `source_kind` 预留值生效。
- **像设计团队一样工作**：模型输出设计概念、动线形态、功能区划分与邻接、展陈/隔断、材料氛围、设计取舍与成本缺项；程序把决策落为版本化模型并逐条复算边界、避障、非重叠、连通、入口可达、通路宽度、最小面积与稳定 ID；不通过时把错误与可操作修复建议退回模型（最多 `RKD_AI_DESIGN_MAX_ATTEMPTS` 次），仍不通过则明确失败且不写入任何候选。反馈修订保留锁定入口与展陈对象，程序强制恢复被模型擅自改动的锁定几何。
- **真实验证**：`scripts/verify_real_design.py` 端到端 **passed=true**（217 秒）：真实需求理解（6024/903 tokens）→ 两个真实候选 `branch-salon`（分支）与 `loop-core`（环游），均通过全部几何硬检查且结构签名不同 → 真实反馈修订（移除隔断、动线从 branch 改 loop，产生对象 diff）→ 采用后同源深化与 7 类技术成果。设计模型运行台账 5 条，含模型/提示版本/用量/请求 ID，金额保持 unknown、超时保留 pending_reconciliation。负例专项 `mvp/tests/test_real_design_provider.py` **8/8**（未配置、401、超时、畸形输出、同质候选、密钥不序列化、契约元数据、真实 Provider 构造），全部用本地协议桩，不联网不计费。
- **运行入口**：`pwsh -NoProfile -File .\scripts\rkd.ps1 start-ai-real`，要求先在终端设置 `RKD_AI_API_KEY`（仅当前会话）；可用 `RKD_AI_BASE_URL` / `RKD_AI_MODEL` 覆盖地址与模型，默认 `RKD_AI_EXTERNAL_CONTEXT=false`。密钥不写入任何文件。`mvp/README.md` 已记录。
- **评审材料**：`var/review/2026-11-09/real-design-review.html`（+ PDF、JSON 快照）由 `scripts/build_real_design_review.py` 从真实运行留下的隔离成果生成，内嵌两个真实候选 SVG 与技术平面，附对比、模型原文摘要、反馈 diff、真实用量、AD08 四问与仍需用户决定的两件事，不再调用模型、不读取密钥。
- **证据**：`var/evidence/real-design/2026-11-09/run-20261109T150958-477f22/verification.json` 与同目录 `design-model-runs.jsonl`。
- **AD 逐项事实（不自行改判通过数，仍以固定验收为准）**：AD01 真实调用与四类失败负例证据齐备；AD02 尚未跑同边界相反需求对照；AD03 两个真实可计算候选与几何复算证据齐备；AD04 真实反馈产生新版本与锁定保护，冲突/晚到结果负例仍属既有工程测试；AD05 图面与对象版本一致性有同源包但未做跨版本专项；AD06 采用后量价/下载一致有上一批工程证据，真实模型链未单独复跑；AD07 浏览器与重启证据来自上一批，真实模型链未单独复跑；**AD08 只能由用户对 `real-design-review.html` 的具体图面给出，不得由模型自评或自动测试代签**。
- **边界**：密钥只在服务端进程环境变量，不进文件/数据库/日志/前端/Git；默认只向模型发送自然语言输入、明确标记的测试边界与必要提示，项目原件、本地解析文本、项目决策、预算、现场照片均不外发；候选仍不触发生产同步、采购订单、正式报价或发布；日常 SQLite 权威库与 NAS 未改动；技术包仍非施工图，专业复核 pending。用户尚未给费用上限与资料外发范围，本批按小额联调执行并如实记录用量。

### 2026-11-09 真实 PG 联调、PG 模式接入与浏览器验收（已交付，未计 AD 通过）

- **修复真实缺陷**：`postgres_import.py` 的 `JSON_FIELDS` 补 `record` / `handover` / `source_extraction_ids`（否则 014 三表 SQLite→PG 导入因 jsonb 未包装或行对账失败）；`postgres_api_service.py` 补 `ai_source_extraction_service` / `ai_technical_delivery_service` 装配、`runtime_info.capabilities` 与 GET/POST 共 5 条路由白名单（否则 PG/团队模式新页 501 或属性错误）；`verify_postgres.py:247` 与 `mvp/integration/test_postgres_live.py` 的 1..13 断言、重复版本 `011_failure.sql`→`015_failure.sql`、`max(version)==9`→14 共 4 处同步；`verify_m5_browser.cjs` viewer 登录后增加项目列表 `waitFor` 消除竞态；`postgres_api_probe.py` 浏览器子进程清除沙箱 `HTTP(S)_PROXY`；`web/src/styles.css` 让新页两列网格在 980px 以下确实变单列（原来高优先级选择器未覆盖）。为 PG 路由白名单新增负例/正例回归测试。
- **新增可复跑脚本**：`scripts/verify_postgres_delivery.py` 起隔离 PG17 集群，构造含 1 条抽取、1 条交付、3 份成果字节的 schema-24 SQLite 快照并导入真实 PG，实测迁移 1..14、jsonb 字典往返（`record->>'status'='extracted'`）、3 表 RLS 与 3 条策略、同租户可见/异项目不可见、伪造租户写入被拒、`PostgresAIProfessionalDeliveryRepository` 插入回读、4 个文件 SHA-256/字节对账；`scripts/verify_delivery_browser.py` + `verify_delivery_browser.cjs` 起隔离本地服务并用 Playwright/Edge 真实点击「资料与技术交付」页。
- **真实验证**：专项 **17/17**、全量 **236/236（0 失败/0 跳过）**、严格环境检查、前端生产构建通过。完整 `verify_postgres.py` **passed=true**：live RLS/并发/回滚/租约 **16/16**、业务 **45/45**、身份 **8/8**，SQLite 快照导入 57 表/733 行/74 文件对账通过，完整恢复 75 表/48 文件与每日恢复 75 表/74 文件/8 项目 HTTP 通过，归档应用 API 重启与真实数据库重启（84 事件保留）通过，账号浏览器登录/角色/上传下载/退出/响应式全流程通过。
- **浏览器证据**：`delivery-browser.json` 记录来源片段 `line:1-2`、7 类成果类型清单、UI 下载 ZIP 8865 字节与登记一致、390px 视口 `document.scrollWidth=390` 无横向溢出、无 console 错误；附 `delivery-desktop.png` / `delivery-mobile.png` / `technical-delivery.zip`。
- 证据：`var/evidence/postgres-delivery/2026-11-09/run-*/verification.json`、`var/evidence/delivery-browser/2026-11-09/run-*/verification.json`、`var/evidence/m5-postgres/run-20261109T131231-7b59d0/verification.json`（含各 live 日志、runtime-reconciliation、恢复报告）。
- 边界：仍是确定性工程链与合成适配器；PG/浏览器证据只支撑工程回归与 AD07 的部分条件，**不能据此判定 AD01—AD06/AD08 通过**，AD01—AD08 仍 **0/8**；未调用真实付费模型、未做专业审签、未收集用户设计评价、未改动日常 SQLite 权威库或 NAS、未正式切库。

### 2026-11-08 AI-DESIGN-01c / DELIVERY-01a/01b 原件解析与技术交付草稿（已交付，未计 AD 通过）

- 新增 `contracts/v1/ai-source-extraction.schema.json`、`ai-technical-handover.schema.json`，兼容扩展 `ai-design-brief.schema.json` 的来源状态/来源类型/内容状态，并在 `openapi.v1.json` 登记 3 条新路径。新增 SQLite 024 / PostgreSQL 014 迁移，共 3 张表（`ai_source_extractions`、`ai_technical_deliveries`、`ai_technical_artifacts`），PG 全部带 RLS 策略；`postgres_import.py` 增加 3 条表映射与快照版本 24。**未改动已执行的 021—023 / 011—013 迁移、旧表或旧成果**。
- `source_content.py` 从已保存且哈希校验通过的原件字节确定性抽取：纯文本类按行给出 `line:N-M` 定位，PDF 只读取可可靠解码的文本层并标注内容流/文本块定位与页码未核验；扫描件、CID 字体、CAD、电子表格、图片明确记录 `no_extractable_text_layer` / `unsupported_format`，`segments` 为空、文本摘要为 null，**不编内容**。记录绑定 `file_sha256` 与抽取器版本，原件变化后旧记录标记非当前。
- `AIRequirementService` 可选注入 01c 读取器：任务书输入清单对已解析文件标记 `content_extracted`、`file_content_extraction`、`selected_content_extracted` 与本地片段索引；未注入时保持旧语义，旧测试/旧数据不受影响。默认 `RKD_AI_EXTERNAL_CONTEXT=false` 时真实模型仍只收到自然语言输入；本地片段索引从 `provider_manifest` 剥离，不外发项目资料。
- `AITechnicalDeliveryService` 只从当前「已采用且未过期」的深化包生成 7 类成果：技术平面 SVG（对象 ID、边界尺寸、材料图例）、材料做法 CSV、节点示意 SVG、技术交接说明 HTML、交接数据 JSON、成果清单与 ZIP。全部绑定同源对象集、采用版本和输入哈希；材料规格/产品/做法、构造参数、机电消防接口、现场实测、损耗、正式税务与专业审签保持 unknown 不补 0；复核待办按角色列出且恒为 `pending`。成果登记字节/SHA-256 并在下载时复验；采用基线变化后旧包 `source_outdated` 保留可读。不调用旧 `design_service.create_design` / `production_service.sync`，不创建订单、正式报价或发布。
- 工作台「资料与技术交付」页可逐个解析原件、查看来源片段与原件链接、生成并下载技术成果；前端生产构建通过（保留既有 PDF.js 大包告警）。
- 真实验证：专项 **16/16**、全量 **235/235、0 失败/0 跳过**、严格环境检查、前端构建、契约解析、7 类成果字节/哈希校验、篡改拒绝、陈旧基线拒绝、幂等、跨项目拒绝；`local_backup` 完整备份/隔离恢复实测包含 3 张新表与 7 份技术成果字节。证据 `var/evidence/professional-delivery/2026-11-08/verification.json`（含各命令日志）。PG 侧只做迁移连续性/RLS/导入映射与快照版本的结构验证，**未跑真实 PG 联调作业**。
- 评审材料：`scripts/build_design_review.py` 在隔离库跑完整链，生成单文件可打印评审页 `var/review/2026-11-08/design-review-2026-11-08.html`（内嵌两个真实候选 SVG 与技术平面，附对比、成本已知/缺项、AD08 反馈四问和模型接入三项决定），数据快照 `var/evidence/professional-delivery/2026-11-08/review-data.json`。两个候选策略 `private-branch` / `open-loop` 结构签名不同、硬检查均通过；图面来自真实运行成果，不是手写描述。
- 边界：仍是确定性工程链与明确非 AI 的合成适配器；**没有真实付费模型调用、真实用户设计评价、专业技术审签或完整专业施工图**，AD01—AD08 仍 **0/8**。真实模型通道、费用上限与资料外发范围、以及对具体图面的偏好，需用户按评审页给出具体决定；本批不新增无关管理配套，不改动 NAS 或日常 SQLite 权威库。

### 2026-11-04 ARCH-PLAN-02 最终目标与总体架构详细规划

按用户要求完成规划交付：docs/21共16个主题章节，定义T01—T12最终能力、F01—F11业务流程、五个人工责任闸口、统一工作台、模块化单体、语义模型/专业表示/成果分层、数据与来源/版本、AI真实设计与反馈、几何/三维/图纸、成本采购经营、可靠任务/事务、权限/知识、NAS兼容迁移与运行保障。第12节细化AI-DESIGN-01—05的子项及P1—P5交付路径，第13—16节定义评估、防偏离、风险和目标追踪。docs/13第12.9节已纳入附件，AGENTS/交接及旧Agent/统一模型文件入口已同步澄清。

本轮定向复核实际代码和契约，确认须优先处理：旧设计保存直接sync生产/条件采购，不适用于候选探索；旧布局验证固定底边条带；需求备注不驱动布局；旧契约UUID/必需成果凭据与运行ID/合成文本输入存在需显式适配的差异。均已写成具体工作包，不宣称本轮已修复程序。现有Git HEAD为83ca002且有大量既有未提交修改，纠正“当前无提交历史”旧说法，未重置或提交用户工作。

新增后续工作包仅细化原总目标，状态如下，不阻塞当前AI主线：

| 编号 | 状态 | 依赖/交付 |
| --- | --- | --- |
| BUSINESS-02 | 待实施 | BUSINESS-01及履约事实后的合同、应收应付、实际成本/现金与经营视图 |
| PLATFORM-01 | 待实施；已有M5资产复用 | 两端事实对账、单一权威库切换方案、真实团队持续运行，不重做部署 |
| KNOWLEDGE-01 | 待实施 | 最小来源/策略版本随AI-01做，后续完善获准知识库与反馈复用 |
| SCENARIO-01 | 待实施 | 首场景真实反馈后扩第二场景及跨场景验证 |

本轮仅文档修改，无业务代码、数据库、机器契约或NAS部署变更，无新增功能测试通过项；AD01—AD08仍0/8，原工程证据保留。规划交付不表示AI或专业生产已可用。下一工程项AI-DESIGN-01a/01b/01d，随后立即推进02/03形成图面候选/反馈/采用闭环；当前不需用户补资料、税率或审核人姓名。

文档完整性检查通过：本批7份文档本地链接可解析、代码围栏配对、表格列数一致、无替换乱码；蓝图16节连续、12个目标与11个流程节点完整，父任务在执行计划/状态表均有入口，当前下一步一致、AD仍0/8。检查证据 `var/evidence/architecture-plan-20261104/document-validation.json`。范围仅限文档结构/追踪及人工一致性复核，不冒称代码回归、专业设计或生产验收。

### 2026-11-04 设计公司公开流程研究与业务可行性复核

研究完成，报告 `docs/20-设计公司流程研究与项目可行性复核.md`：查阅 RIBA/AIA/BIID/RICS 官方工作流程与室内设计实务、巨潮披露的杰恩设计 2024 年流程、Gensler 实际案例及中国设计合同示范文本。结论为总体方向合理但当前尚不能完成真实公司交付；核心原创/深化不足，不能用现有管理底座或一个模型接口推断闭环成立。

执行计划增加 12.8：保持 AI-DESIGN-01 最高优先级；01—03 即纳入场地来源、可视候选、材料意向、成本/缺项和反馈，04/05 深化与量价迭代。明确 G2 前可探索草稿，未削弱正式责任；已有单地坪净量链不当作全项目估算/真实采购。原业务状态机已有部分迭代与正式边界，本轮主要把其落到当前交付任务，不误报全部缺失。

| 编号 | 状态 | 执行节点 |
| --- | --- | --- |
| BUSINESS-01 | 待实施 | 真实收费项目准备前完成设计委托/服务范围和服务费事实；不阻塞内部 AI 草稿 |
| DELIVERY-01 | 待实施 | AI 候选与深化后补技术成果/专业交接，按具体受限对象验收 |
| DELIVERY-02 | 待实施 | 真实采购前落实项目角色、样板/询比价、需求至订货转换和供应资料 |
| DELIVERY-03 | 待实施 | 真实施工交付前落实现场澄清、变更与交付维护资料 |

本轮为研究、定向代码核对及计划修订；没有业务代码/数据库/线上变更，没有重新运行全量测试或新增功能通过项，AD01—AD08 仍为 0/8。研究不能证明 AI 设计质量或现场可施工性。无需用户重新补资料、税率或固定审核人；下一工程动作仍为 AI-DESIGN-01，并以 01—03 的实际设计闭环交付。

### 2026-11-04 AI 设计能力复核与优先级调整

审核完成：`docs/19-AI设计能力与执行方向复核.md`。确认原 docs/01、03、04 明确要求需求分析、空间规划和概念设计；现 docs/13 的受限 M3 清单没有排入真实模型设计后续任务，执行优先级偏离。M3 原 DA01—06 规则工程结果保留，不能计为 AI 设计验收。

隔离实际应用服务/SQLite/文件复现：`var/evidence/design-audit-20261104/run-9418f8262f/observations.json`，可重跑脚本同目录上级 `replay.py`。相反自然语言设计备注生成相同模型，需求哈希/设计版本却已变化；两版六项硬检查均通过，14份成果字节哈希一致。入口/动线/风格额外字段被旧规范化丢弃。该结果证明缺口，不计产品验收通过；本轮未修改业务代码、NAS或日常数据，未重复全量测试。

| 编号 | 当前状态 | 下一交付/依赖 |
| --- | --- | --- |
| AI-DESIGN-01 | 待实施；当前最高优先级 | 真实模型通道、自然语言与来源明确的设计任务书；先合成案例，无法确认可用通道/费用时才请求具体决定 |
| AI-DESIGN-02 | 待实施，依赖 01 | 至少两种真实空间组织候选及通用几何验证，不能只换文案/颜色 |
| AI-DESIGN-03 | 待实施，依赖 02 | 自然语言反馈驱动新模型，保留决定/冲突/历史 |
| AI-DESIGN-04 | 待实施，依赖候选模型 | 材料、展陈/家具、隔断及同源三维表达；概念图来源单独标记 |
| AI-DESIGN-05 | 待实施，依赖采用的有效候选 | 复用并扩展同源量价与真实成果交接 |

新 AD01—AD08 尚无通过项（0/8）；这是新定义的核心能力验收，不撤销已有工程证据。用户已提供产品反馈：“现有地坪图像堆叠方块，缺少设计”。该反馈不是 M5-06 整体验收通过，也不是尚未反馈；下一步应解决设计响应能力，而非继续催用户走旧流程。

### 2026-11-03 M5-05d 逐项审查与当前版本汇总（已部署工程切片）

最终Windows192/192通过（169.426秒，`final-full-tests.log`），NAS Linux192/192通过（106.232秒，`linux-full-tests.log`）；真实PG隔离5项流程通过，最终浏览器重新跑新版逐项填写/保存通过。NAS迁移010、镜像`sha256:860445cb4e3fb42c11157ef0c61ba336218b857a5e68417f497f82bb4fd7a1a3`已上线；HTTPS新资源200、匿名审查401及7/7巡检通过。更新后完整备份`online-20261103T143716-ddfd06/complete.zip` SHA `faf07e9ba1f2b92428450560038508ea816f9a08f4f159213b55baefdde1f7b1`；恢复62表、74运行文件、276应用文件11.571秒，8项目、归档应用与账号保护通过（`recovery.json`）。旧镜像before-review-checklists及checklists-before.zip保留，无现用库替换/正式切库。线上新增表当前无真实审查记录，不能把空表恢复当成人员专业验收。隔离浏览器服务已停止。

用户已选择“我先亲自试用草稿流程”。当前进入M5-06个人先行试用，具体操作单`docs/18-团队草稿试用操作单.md`；只要求需求→设计→量价→下载→送审前检查的真实使用反馈，不要求同账号自审或立即提供固定审核人。岗位专业审查和正式签署仍不计完成。现在需要的介入是用户实际试用，不能通过更多脚本代填该验收结果。当前新版完整包已通过Windows计划任务复制并逐成员校验成功，退出码0，SHA与NAS一致（`offsite-backup.json`）。

两岗位各3个检查项，unknown/checked/needs_changes分离；填写依据，已核对必需本次成果引用，异版/跨项目引用、缺项/重复项、结论与需修改冲突均拒绝。检查表与意见同事务，保存前再次核对生产证据、变化整笔回滚，审核包包含检查表；当前版汇总待审/修改/已记录未知及历史事项，岗位改名会用于任务显示。正式发布恒为false，无专业批准替代。

SQLite020/PG010新增review_checklist表及项目RLS，导入保留文本JSON与SQLite20。真实NAS PG16非owner隔离库5项流程通过（`final-pg-tests.log`），覆盖基线变化回滚、未知/引用/冲突、持久与ZIP及原权限流程；末次补充畸形输入类型400校验另以最终全量/目标Linux核验。浏览器桌面及390px实际逐项填写→意见保存通过，无JS错误/溢出（`review-browser.json`及截图）。第一轮全量191项失败1项为迁移数量断言未更新，后续191项复跑通过，但最后新增竞态用例及输入类型校验后全量最终结果待另记，不混用旧结果。

证据`var/evidence/m5-checklists-20261103/`。部署前61表/74运行文件/272应用文件完整在线备份`online-20261103T143154-b4b129/complete.zip`，SHA `aa3aae1d910f20a4d6ba4a488144edd412edaf8735def7bac36e8dc3ef17fce8`。本批尚在部署/恢复验收阶段，不能称已上线。


### 2026-11-03 M5-05c 岗位审查的实际成果交接

NAS已更新上线，真实HTTPS入口/新资源200、匿名审核包401。更新后完整备份`online-20261103T142038-768bbf/complete.zip`，SHA `c01ff13688deeba132608b1780ad7d97916298f291cbd257f9fa6f5c37154250`；新空库/目录恢复61表、74运行文件、272应用文件，12.463秒，8项目及归档API账号保护通过，最终巡检7/7通过（`https.json`、`recovery.json`）。未正式切库。下一步继续专业评估的具体检查项/证据关联能力，不因尚未配置真实审核人员停止开发，也不自动开放正式发布。


新增任务级草稿审核ZIP下载：送审时8份真实成果字节、逐文件摘要/大小、任务冻结基线及当前审查记录一起交接，历史任务保留原成果并显示source_outdated，不能用新版替换。服务器生成档内路径，32MiB上限，缺失/变化拒绝；实时项目权限和账号保护保持。待办新增“下载本版草稿审核包”。OpenAPI同步，无数据库迁移。

Windows全量190/190通过（174.230秒），前端构建通过；真实NAS PG16普通应用账号隔离库3/3场景通过，覆盖实际ZIP/8文件哈希、历史原版、篡改拒绝、匿名及跨项目拒绝和原岗位流程，未修改个人NAS账号。证据`var/evidence/m5-review-evidence-20261103/full-tests.log`、`pg-tests.log`。本批未新增登录浏览器操作验收；不能把ASGI下载验收当作真实个人账号使用。

部署前在线完整备份`online-20261103T141720-85338b/complete.zip`，SHA `20cc80811cac58aa493535246245feed08bd4856e00da377150548e09902852a`，61表/74运行文件/270应用文件。旧源码evidence-before.zip、旧镜像before-review-evidence保留。正式发布始终关闭，审核包是内部专业审查输入，不是签署或批准。


### 2026-11-03 Windows计划任务安装复核

本批最终：两个计划任务手动触发均退出码0。初次新包SSH流传输7MB中断并正确记失败，保留旧成功包及失败partial；已改256KiB分块、每块3次重试及完整摘要/归档校验，不需重装任务。计划任务再跑实际复制11月3日03:15新包22,575,641字节，SHA `b4d3e1e6e6124b34d1e1171bceacabe409374b8b04d6f1d71c997ed5bc5e9e95`。随后恢复任务对这个新包实测61表/74运行文件/270应用文件、8项目、归档API及账号保护通过，数据库恢复阶段8.14秒，测试API/集群停止，现用运行库未替换。证据`backup.json`、`recovery-latest.json`、`tasks-final.json`。不再把自动任务安装记为待用户处理；未来每日/每周按时触发的长期记录仍待观察，当前无新的用户操作要求。



用户已在管理员终端成功安装两个计划任务。本机核验执行路径、当前用户交互登录方式、每日04:15复制及周日04:45恢复（北京时间）正确；下一次计划时间为11月4日04:15、11月8日04:45。本轮通过Start-ScheduledTask实际启动两项；恢复任务退出码0，61表/74运行文件/270应用文件、8项目、归档应用及账号保护再次通过，恢复服务/集群已停止。恢复使用启动时已验证的11月2日包，不能冒称已恢复尚在复制的11月3日凌晨新包。备份任务正在传输，最终结果待另记。

该证据证明注册及任务计划程序手动触发执行，不代表已经观察到未来定时触发；电脑需保持当前用户登录且Tailscale可达。NAS11月3日03:15自动完整备份成功，7/7巡检正常。记录`var/evidence/m5-scheduled-20261103/`。此前任务注册权限阻塞已经解决，不再要求用户重复安装。



### 2026-11-02 M5-04 异机完整恢复与自动任务安装阻塞（最新）

新增`scripts/sync_nas_backup.py`，复用既有受信SSH密钥读取最近成功备份，以SSH字节流复制到Windows `var/backups/nas/`；校验完整SHA及归档逐成员大小/摘要后才发布完整包。已有同包重新执行不重复传输；进程锁、防路径注入、失败与最近成功分开记录，空间少于2GiB拒绝、不删除任何既有备份。当前最新61表/74运行文件/270应用文件完整包已复制并验证，第二次幂等重跑通过。状态见`var/backups/nas/latest-success.json`，SHA与本批NAS恢复一致。

新增`scripts/verify_offsite_restore.py`，在Windows新建回环PG17独立集群，把NAS PG16归档恢复到空库和新目录，全表摘要一致、74个实际文件/8项目验证通过，实际运行归档应用ready200、账号初始化保留、匿名401、恢复副本旧会话撤销。数据库恢复阶段5.328秒；归档API和集群已停止，未切日常SQLite、未替换NAS数据。证据`var/evidence/m5-offsite/restore-20261102T144850-6808cc/verification.json`及`var/backups/nas/latest-recovery-success.json`。这是真实跨机器/跨系统数据库恢复，不再仅为安全解包。

自动安装脚本`scripts/install_nas_backup_tasks.ps1`已写成可审查结果：Windows当地每日04:15复制、周日04:45隔离恢复；当前用户交互登录、错过后补跑、每任务最多一实例和30分钟超时，使用pythonw不弹窗，无密码写入计划任务。不把Windows离线或未登录时当作仍会执行。实际Register-ScheduledTask返回Access is denied，两个任务尚未成功注册；此为操作系统权限阻塞，需用户在管理员PowerShell运行该现成脚本。未冒称已建立自动异机任务，更未宣称已观察到定时触发成功。未使用开机自启或额外常驻程序绕过任务计划权限。

M5-04仍未整体验收：定时异机复制/恢复任务安装与未来触发证据尚缺；外部通知按用户决定暂缓；M5-06仍需实际团队试用及责任人确认。上述权限动作是本轮继续所需的用户参与，不重复索要专业审核人姓名。

### 2026-11-02 M5-05b 岗位送审与内部待办（最新）

已新增当前生产草稿按岗位送审、项目审查历史、登录后个人待办与草稿意见记录。仅负责人可提交，提交绑定不可变生产版本/源版本/文件摘要；同一证据和岗位重复提交不重复建任务。岗位成员必须账号有效且有当前项目访问权限；岗位停用/换人/撤权即时影响路由，制作者和提交者禁止自审。无有效接收人明确“等待配置”，不计已送达；旧成果/篡改文件会使事项失效并拒绝记录，已审查不等于已批准，正式发布始终关闭。外部通知仍按用户决定暂缓。

SQLite019、PG009新增项目域review_task表及RLS，导入适配支持SQLite19且保留完整证据JSON。OpenAPI已同步。Windows全量189/189通过（`tasks-full-tests.log`），部署后NAS Linux全量189/189通过（`tasks-linux-full.log`，94.806秒）；实际NAS PG16非owner隔离数据库两组端到端通过（`tasks-pg-verification.log`），涵盖幂等、防自审、只读成员仅写审查、岗位换人/撤权、缺成本/旧基线/空意见拒绝和跨组织RLS。真实Edge浏览器完成负责人提交→审核人员待办→保存意见，桌面与390px手机无页面溢出、无JS错误（`review-browser.json`及截图）。浏览器仅使用隔离测试数据，未登录个人NAS账号。

NAS实际迁移009，镜像`sha256:1732342d32b93470be7182eeebe30790720db54e00925f1cc503c0dc0fe41e3a`已更新；真实HTTPS新资源200、匿名业务/岗位/审查401（`tasks-https.json`）。部署前源码`tasks-before.zip`、旧镜像`rkd-ai:before-review-tasks`及完整备份保留。未给任何真实用户分配审核岗位，现有NAS项目尚无地坪生产记录，不用测试数据填充真实项目。

更新后完整在线备份`online-20261102T144437-49624b/complete.zip`，SHA256 `b7ddf0bb3d8d411bc3a8db23cecea51d42001f1e9d022a5b268afb0836ceb09d`；新空库/新目录实际恢复61表、74运行文件、270应用文件，8.114秒，8项目/全部文件、归档API与账号保护通过（`tasks-recovery.json`）。恢复副本撤销1条旧会话；未停线上备份服务或替换现用库，部署应用本身有正常重建切换。线上review_task当前为空，因此不把空表恢复当真实审查内容验收。

最终NAS容器healthy、7/7巡检通过；隔离浏览器HTTP及Windows恢复应用/数据库进程均已停止。

本批证据统一在 `var/evidence/m5-nas/20261102-scheduled/`。M5-05专业样本评估、正式签署/成果发布及M5-06真实人员试用仍未完成；岗位配置不代替有权专业批准。下一步继续M5-04异机备份与跨机恢复，不索要固定审核人姓名。


2026-11-02用户明确改为按岗位配置审核责任，管理员后续自行分配或调整人员。已新增“设计/图纸审核”“报价/税务核验”两个固定职责键，显示名称可修改、启停、多个成员和版本冲突控制；账号管理页可操作，只有管理员可修改，有效本组织成员才可分配，变更同事务审计。岗位不自动授予项目访问或专业签署权限，也不创建默认人员；尚未实现送审待办推送，外部通知仍按用户要求暂缓，不把岗位配置说成已发消息。

SQLite018、PG008新增两张组织域RLS表；只读迁移适配已增加岗位表和SQLite18版本，未来导入不丢岗位。真实非owner PG隔离库 `rkd_positions_b70605b3` 验证分配持久化、旧版本拒绝、跨组织RLS及审计通过（`positions-pg-verification.json`）；账号传输专项7/7通过，前端构建通过；前轮全量失败为新增用例岗位顺序断言及迁移版本数量断言未更新，失败日志保留、复跑另记。

岗位批次最终复核口径：`positions-full-recheck.log` 中185个实际测试通过，但一个测试模块因更新版本断言时缩进错误未导入，不能称整轮通过；缩进已修正，该模块另跑2/2通过（`positions-sqlite-threading-recheck.log`）。新增ASGI专项7/7（`positions-asgi-recheck.log`），迁移断言已更新到PG8/SQLite18；本批不冒称原“186全量通过”覆盖了岗位新代码。后续功能再变更时继续完整回归。

NAS已应用PG008并独立构建应用镜像 `sha256:1b2de8c362aaf846dc7fc175a599c399cfe728847c1993bcb5f25d5a1211406f`；真实HTTPS新前端资源和匿名岗位401通过。没有替用户分配任何真实账号。新完整备份 `online-20261102T142052-2cfa15/complete.zip`，SHA `4e8d238cac82fb795704ccf30d17322660535dbf56e66384372962834bcc9ec1`，60表/74文件/262应用文件；新库/新目录实际恢复9.628秒，归档应用及8项目74文件检查通过，旧会话仅恢复副本撤销，线上未停机/切库。新表当前为空（岗位默认目录由代码提供），不能据此宣称实际人员分配已恢复验证；真实隔离库分配持久化已单独验证。旧镜像 `rkd-ai:before-review-positions`、NAS补丁前源码 `positions-before.zip` 保留，schema为增加表，不自动降级删除。

2026-11-02 M5-05a 送审前检查切片已实现并部署：生产区域“检查当前生产草稿”实际核对当前生产/来源基线、成本是否已知和全部成果大小/SHA，列出现场边界、专业合规、正式税务/商务和责任人签署未核验事项；可下载本次未签署JSON（基线/文件摘要/检查项/证据摘要/时间）。永不自动formal_release_allowed=true，不创建审批记录。检查期间生产版本/来源状态变化返回409；读取经过当前项目权限，匿名401、无项目权限404。真实API用例覆盖只读账号及跨项目拒绝，接口专项6/6，生产链含缺成本/无生产/过期/同大小文件篡改/重复摘要专项12/12；前端构建通过。

本批最终全量186/186通过，0失败（`review-full-regression.log`），最终NAS镜像 `sha256:b3aa277082c81c99295e960d54f407dc71fa1a4fbe17bc7a6f0fa349c73ee31f` healthy，运维7/7通过。OpenAPI已补送审前只读接口；未替用户登录NAS，未声称本批新增页面已做实际登录浏览器验收。已异步请求实际设计/图纸及报价/税务审核责任安排，用于下一正式审查切片；在责任与权限明确前保持发布关闭，不把管理员账号自动当专业签署人。

NAS实际8项目检查已完成，但现有8项目没有地坪production记录，均正确显示缺项，不伪造空的通过结果。证据 `var/evidence/m5-nas/20261102-scheduled/pre-review-nas-projects.json`、`pre-review-tests.log`、`pre-review-asgi-tests.log`；真实HTTPS新资源及匿名接口401通过。部署前在线完整备份 `online-20261102T141103-d6f7a3/complete.zip`（58表/74文件/257应用文件），SHA `a3286751483c036f3d0c2f2b181d02aa9715b293017583b5b5cc50f1f68fc183`，包含上一运维提示切片；旧镜像 `rkd-ai:before-pre-review` 和NAS `review-before.zip` 保留。没有数据库结构迁移、无个人账号改动、未向第三方发送消息、未正式切库。

2026-11-02用户明确暂用工作台内提示、外部通知稍后配置。已新增管理员专用 `/api/v1/operations/status` 及登录后状态条，每分钟刷新，显示检查时间/备份时间、异常项及超过3分钟未更新的陈旧状态；读取失败明确告警，不冒称正常。后台仅返回白名单状态，不暴露主机路径/秘密，匿名401、普通账号403。新增传输用例覆盖授权、脱敏、陈旧和损坏记录，ASGI 5/5通过、前端构建通过。NAS应用已重建更新，真实HTTPS新资源与匿名401、非root容器读取运维投影通过，证据 `operations-asgi-tests.log`、`operations-notice-https.json`、`operations-notice-container.json`。更新期间容器starting曾被巡检记录为异常，不忽略或伪报正常；最终巡检另复验。只读挂载 `operations/public`，其父部署目录仍700；旧镜像保留 `rkd-ai:before-operations-notice`、补丁前文件保留NAS `operations-before.zip`。现有完整备份早于此界面补丁，不冒称已包含最新功能。

外部主动通知依用户选择暂缓，不作为反复索要账号的阻塞；页面只在工作台打开且能连接时提示，不能检测NAS全机失联后向用户主动发消息。M5-04仍待相应持续使用/异机任务验收，M5-05专业闸口及正式切库未批准。

最新复核（2026-11-02）：NAS当地10月31日、11月1日、11月2日03:15三次cron备份均成功；两个容器持续运行约3天，当前7/7巡检通过。Windows实际HTTPS证书/ready200、账号initialized=true、匿名业务401复验通过。证据 `var/evidence/m5-nas/20261102-scheduled/continuity.json`、`https.json`；不推断三天每秒可用。

最新定时包 `/home/Justin/rkd-ai/backups/online-20261101T191501-4c2c9b/complete.zip`，SHA256 `6b364d516fc7bcf77a04e9dcd2044bc6177761f861361274a372187b8a63bafa`，北京时间11月2日03:15快照。新增 `scripts/deploy/verify_scheduled_recovery.py`，实际新库/新目录恢复58表、74运行文件、252应用文件，8项目全部引用文件校验通过，10.588秒；管理员保留，恢复副本1条旧会话撤销，实际归档应用ready及匿名401通过。线上服务未停止或替换。证据 `recovery.json`；恢复目录 `/home/Justin/rkd-ai/recovery-checks/scheduled-20261102T135901`。该脚本在release新增，尚未构建进应用镜像，不冒称旧备份含新验证器。

已询问用户外部告警接收渠道，未收聊天密钥或发送第三方消息。M5-04外部主动通知、定期异机任务/跨机数据库恢复及真实团队持续试用仍未验收，不以工程检查替代正式切库/专业批准。

最新cron包已另复制Windows：`var/evidence/m5-nas/20261102-scheduled/scheduled-complete.zip`，21,651,076字节，SHA与NAS一致；Windows安全解包逐成员校验通过（58表/74运行文件/252应用文件），`off-nas.json`。这是第二个时点的实际异机副本，仍不冒称已部署自动异机复制或完成Windows数据库恢复。

| 编号 | 任务 | 状态 | 证据/下一动作 |
| --- | --- | --- | --- |
| PLAN-01 | 固化产品交付计划、AI 接管约定及状态口径 | 已完成文档交付 | `AGENTS.md`、`docs/13-产品交付执行计划与设计.md`、本文件、交接文件；不计入功能验收 |
| M1-01 | 固定运行依赖、准备/启动自检、运行数据隔离 | 已完成 | `requirements.lock`、`web/package-lock.json`、`scripts/rkd.ps1`、`var/logs/environment-check.json`；严格检查通过，该批次 97/97 测试通过、0 跳过；最新全量 139/139 见 2026-10-29 整改；运行数据位于忽略的 `var/` |
| M1-02 | 关系存储、事务、连接线程边界、真实项目 API | 已完成当前项目范围 | SQLite 项目关系表及 001/002 迁移；线程独立连接、事务回滚、版本冲突测试；真实 HTTP 创建/编辑和服务重启通过，OpenAPI 已同步。其他业务域仍沿用参考快照，按后续任务推进 |
| M1-03 | 前端首屏、项目操作和单入口启动 | 已完成 | `web/` 构建由 `scripts/rkd.ps1 start` 自动执行；浏览器在 `http://127.0.0.1:8080` 创建、编辑、刷新和两次服务重启后项目名称与 v1 保留；静态资源越界测试通过 |
| M1-04 | 文件接收/下载/预览与宁波种子导入 | 已完成 | `file_service.py`、SQLite 003/004 迁移、资料页；宁波 7 份原件经清单哈希核对只读复制；浏览器上传/预览/下载、同名文件 v1/v2、错误哈希、中断流、跨项目拒绝、重启及重复导入已验证；决策和源表冲突分别保存 |
| M1-05 | 持久任务恢复、CAD 结果接入与问题处理 | 已完成 | `005_operations.sql`、`task_service.py`、问题/任务页；4 份宁波 CAD 派生报告实际导入为 1 条持久任务和 5 条来源问题，重试不重复问题，运行中重启转可重试，取消持久化；处置有版本、理由、操作者和追加动作记录，`approved` 不可用；浏览器重载后显示状态 |
| M1-06 | 预算导入/编辑、成本加成与税计算 | 已完成 | `scripts/extract_budget_xls.ps1` 只读抽取宁波 `.xls` 为 112 条来源定位明细；`006_estimates.sql`、`estimate_service.py` 和预算页支持工作副本编辑、不可变修订、Decimal 金额、施工/设计成本加成和本地试用税率；源总额 ¥616,308.50 与明细对账差 ¥0.00，未知设计成本不按 0；浏览器实测参数保存生成 v4，精度修复后重新试算生成 v5 |
| M1-07 | 真实报告/明细导出及成果版本 | 已完成 | `010_estimate_artifacts.sql`、`estimate_service.py`、预算导出 API 与页面按钮；当前预算修订真实生成 HTML/CSV，入库 SHA-256/字节数/修订号，HTTP 下载和重复导出复用已通过 |
| M1-08 | 完整浏览器验收与交付 | 工程验收完成，用户试用待执行 | U01—U10 按隔离 SQLite/HTTP、文件哈希、任务恢复、事务/幂等、成果下载及既有浏览器记录验收；后续浏览器验证使用 Playwright/Edge；M5 准入复跑 123 项全量通过，用户实际试用仍未计通过 |
| M2-01 | 参数几何与稳定对象 ID | 已完成当前切片；AUD-02 修复复验通过 | 恢复历史尺寸生成新修订；仅当前输入完全相同才复用。真实 HTTP 10→12→10 后重启仍为 10/v4（含一次价格升版），证据见 2026-10-29 整改 |
| M2-02 | 面积规则及扣除 | 已完成 | 确定性 Decimal 面积公式、扣除区越界/重叠校验和 `QuantityItem` 已持久化；46.00㎡→56.00㎡测试与全量测试通过 |
| M2-03 | 几何图面与清单文件 | 已完成当前切片；AUD-03/04 修复复验通过 | 新成果使用服务器生成的唯一修订目录；manifest/CSV 引用实际入库工程量 ID；HTTP 下载 ZIP 和成员哈希对账通过 |
| M2-04 | 修改传播及版本验收 | 当前受控链整改复验通过 | 只改成本 100→200，含税价 ¥6,300→¥12,600；加成/税率/unknown/零成本/来源变化、历史值恢复、当前无变化复用、真实进程重启均验证 |
| M2-05 | 成果生命周期与旧版追踪 | 当前受控链整改复验通过 | 多空间/组织文件目录隔离，旧 6/6 文件不变；下载检查大小及 SHA-256；注入生成失败时数据库回滚，重试不覆盖旧成果。历史已损坏文件和崩溃孤儿文件未自动修复 |
| M3-01 | 结构化需求草稿与来源交接 | 已完成受限场景 | `011_requirements.sql`、`requirement_service.py`；宁波 5 条决策/7 份原件的来源及预算/范围冲突保留在需求快照，未知不补 0；规则生成不覆盖人工修订 |
| M3-02 | 编辑需求与不可变修订 | 已完成 | `PATCH /requirements`、`DesignWorkspace.tsx`；外框、通道、分区最小面积/名称、备注及理由可保存，版本冲突返回 409，来源快照随修订保留 |
| M3-03 | 规则布局与硬约束 | 已完成 | `design_rules.py`、Shapely 拓扑/Decimal 面积/毫米网格；六类硬检查，非法/无解布局不入库；现场/消防/结构检查保持 unknown |
| M3-04 | 可编辑二维模型 | 已完成 | 分区选择及 X/Y/宽长编辑，校验后保存新版本；浏览器接待分区 19.5→13㎡，越界修改拒绝且版本仍为 v2 |
| M3-05 | 图面/清单/报告成果 | 已完成 | `012_design_layout.sql`、`design_service.py`、`design_outputs.py`；每修订七份真实成果，浏览器下载匹配哈希，ZIP 六份文件与同一模型/需求基线一致 |
| M3-06 | 修改传播、历史、重启验收 | 已完成工程验收 | 宽度 12→16m 后需求 v3、设计 v3，分区 78→104㎡；旧成果 superseded 可下载；实际服务进程重启后修订/模型/七份成果不变；DA01—DA06 全部通过 |
| M4-01 | 材料订单草稿、收货与分派 | 已完成工程验收 | `013_procurement.sql`、`procurement_service.py`、采购施工页和采购 API；MP01—MP04 已由服务/HTTP 测试及浏览器实测覆盖，实际外部下单/付款保持关闭 |
| M4-02 | 问题、变更、影响分析、新成果与验收 | 已完成工程验收 | `014_changes.sql`、`change_service.py`、采购施工页变更区和变更 API；MC01—MC04 已由服务/HTTP/浏览器测试覆盖，旧成果保留，正式发布和外部签证保持关闭 |
| M5-01 | 本机真实账号、项目角色与文件授权 | 本机切片工程验收完成；正式运行库待首次启用 | `015_identity.sql`、`account_identity.py`、登录/账号成员页面及 `start-secure`；MA01—MA08 8/8；7 项专项及真实浏览器/进程重启；无默认密码；10 月 1 日启用及旧进程记录见历史证据，不据此推断当前进程状态 |
| M5-02 | 完整 PostgreSQL 存储、事务及迁移 | 计划内业务域本机工程验收通过；正式切库待部署 | PostgreSQL 001—007；业务45/45、身份8/8、内核16/16；实际HTTP、浏览器、并发/RLS/整笔回滚/API与数据库重启，40表/733行/74文件对账；最新证据 `var/evidence/m5-postgres/run-20261030T124442-b4b134/`。旧模拟命令不开放，日常SQLite未替换 |
| M5-02a | PostgreSQL 项目/文件业务 API | 工程切片通过 | 同一文件字节流程配显式 SQLite/PG Repository，无 SQL 翻译或隐式回退；8/8 业务专项、16/16 内核，真实 HTTP/并发/回滚/API 与数据库重启；最新全量 159/159。证据 `var/evidence/m5-postgres/run-20261029T124059-73a82b/`；未切日常库 |
| M5-02b | PostgreSQL 需求/设计/地坪生产/采购服务接入 | 当前生产链切片通过 | 共用现有领域规则及显式仓储，同笔 PG 事务驱动需求/设计/量价/采购；业务专项 24/24、内核 16/16，实际 HTTP 78→104㎡/¥9,828→¥13,104、旧成果及进程重启通过；全域切库仍未完成 |
| M5-02c | PostgreSQL 任务/预算/M2/变更/身份等剩余域 | 全计划内域及本机浏览器工程验收通过 | 共用计算/鉴权规则和显式仓储；45业务+8身份+16内核通过，真实登录、角色、上传下载、延迟旧响应丢弃及重启；不混用权威库 |
| M5-03 | 完整备份与恢复演练 | SQLite/PG本地完整恢复通过；NAS环境待复验 | 一致数据库快照、全部引用文件、未提交应用基线及锁定依赖；新目录/空PG库恢复，旧会话撤销，密码/角色和业务幂等保留；损坏/已有目标/部分RLS备份拒绝；不代替NAS灾备和异机持续备份 |
| M5-03a | 当前 SQLite 模式的完整本地备份恢复 | 本地恢复切片实测通过 | 35 张表/74 个运行文件/233 个应用基线文件校验；恢复后的归档代码实际服务 8 项目、31 次下载及进程重启；独立账号恢复验证旧会话失效、密码/角色保留和只读写拒绝。备份源码、锁定依赖、种子及构建前端，不含可重建的 .venv/node_modules；不代替 PostgreSQL 恢复验收 |
| M5-03b | PostgreSQL完整应用备份与隔离恢复 | 本机实际工程验收通过 | 58表；独立生产链48文件、实际8项目74文件及归档应用逐字节/行摘要对账，原密码/角色及业务幂等保留、旧会话失效；归档代码API与真实数据库重启通过；证据 `run-20261030T124442-b4b134` |
| LINK-02 | 受控变更复核后再生产设计/地坪成果 | 当前尺寸场景工程验收通过 | LC01—LC06 6/6；真实浏览器 78→104㎡/¥9,828→¥13,104，复核前不改模型、证据必填；旧 8 文件保留，下载/独立重启/完整恢复通过；基线变化、未知成本、并发与整笔回滚均覆盖 |
| LINK-01 | 需求/设计地坪→同源工程量/量价/图面→采购草稿 | 地坪切片工程验收通过 | LP01—LP06 6/6；设计保存同笔事务计算/报价/生成 8 份成果及本地采购草稿；78→104㎡、¥9,828→¥13,104，8 份旧文件不变；浏览器、重启及完整恢复见下方证据。复杂材料损耗不计完成；尺寸变更再生产见 LINK-02 |
| M5-04 | 团队部署、HTTPS、监控及故障演练 | 进行中；NAS定时备份巡检及Windows实际异机恢复通过，自动任务已注册并手动触发验证 | NAS→Windows PG16→17实际完整恢复通过；每日复制/每周恢复安装脚本已备，11月3日管理员安装成功，两任务实际退出0，最新完整包跨机恢复通过；未来定时触发仍待观察。外部通知暂缓，真实团队试用未验收，未正式切库 |
| M5-05 | 专业质量评估与正式发布闸口 | 进行中；送审前检查、岗位路由及草稿待办已上线 | 当前切片189项回归、真实PG及浏览器通过；岗位实时权限与防自审已验证；专业样本、正式签署/发布尚未完成 |
| M5-06 | 团队持续试用与受控生产验收 | 待实施 | 不把本地脚本、测试账号及规则模型计为团队/专业验收 |

## 可验收进度

- M1 工程验收：**10/10 项已通过**（U01—U10）。这是工程验收分母，不代表用户已经完成试用或正式生产批准。
- 用户试用：2026-11-04已收到核心反馈，规则分区缺少设计思考，按 AI-DESIGN 主线整改；尚无完整流程或设计质量验收通过记录。
- M2：受控几何→面积→量价→真实成果基础链的 AUD-01—04 **4/4 修复复验通过**，对应专项 9/9。该结论限定当前参数地坪链；多空间后端隔离不等于已交付多空间编辑界面。宁波 CAD 候选仍不自动升级为专业对象。
- M3：**DA01—DA06 工程验收 6/6 通过**，限定矩形展厅规则分区场景，具体分母见执行计划 12.1；用户试用及专业批准未计通过。复杂 CAD 对象化、BIM、效果图、自动施工详图及模型 API 未实现。M4-01：**MP01—MP04 工程验收 4/4 通过**；M4-02：**MC01—MC04 工程验收 4/4 通过**，覆盖基线绑定、影响分析、三份新成果、旧成果保留、验收历史、HTTP 和浏览器链路；M5 已进入开发，M5-01 本机账号切片 **MA01—MA08 8/8 通过**。M5 整体尚未验收，团队/生产批准仍未获得。
- 不再以历史 95%/96% 表达当前系统进度；未建立可核验分母的阶段不报推测百分比。

## 2026-10-30 M5-03b 完成与 M5-04 NAS 准备

### NAS 实际部署与最终复核（优先于下方准备期记录）

- 继续推进后实际HTTPS `auth/config.initialized=true`；个人账号现已创建，不需再跑初始化助手。含账号的新在线完整备份在不停止应用条件下执行成功：`/home/Justin/rkd-ai/backups/online-20261030T143506-f688d9/complete.zip`，快照2026-10-30T14:35:06Z，SHA256 `431a7e648e5a0c2ce9ecea0220553e622ba22e3a3f9cd97986892bd468ea3f45`，21,651,078字节；58表/74文件/252应用文件（取实际容器/app，区别于旧release源码清单），归档逐成员解包校验通过。未读取/显示个人密码或摘要值。
- 新包恢复至新空库 `rkd_restore_accounts_8086455c2f` 和新目录，9.299秒；个人管理员记录及密码哈希随全表对账保留，恢复副本1条旧会话撤销，实际归档应用ready/账号初始化状态/匿名业务401通过；在线现用会话未撤销。`maintenance-latest-recovery-verification.json`。新包已复制Windows为 `nas-with-admin-complete.zip`，SHA/全部成员/1账号记录核对通过，`with-admin-off-nas-verification.json`；不据此宣称用户实际登录试用或Windows数据库恢复通过。
- 新增 `scripts/deploy/nas_maintenance.py`，NAS助手 `/home/Justin/rkd-ai/nas-maintenance.py`，只在可信主机维护进程持owner凭证；无Docker socket或owner秘密加入应用。在线备份复制实际容器runtime及/app后取PG一致只读快照，逐引用SHA检查；并发出现缺失/变化则失败，不发表不完整成功包。成功/最近尝试独立记录，失败目录保留，进程锁防重叠，磁盘不足2GiB拒绝，不自动删用户备份。
- Justin crontab独立标记段已安装：NAS当地（UTC+8）03:15每日完整备份，每分钟巡检；旧任务完整保留。实际cron在14:40:01Z执行成功，7项为应用ready、两个容器healthy、私有Serve目标/Funnel关闭、磁盘、备份≤26小时且文件存在、最近备份尝试成功。错误路由/缺备份真实负例、异常首次记录/相同异常不重复/恢复关闭验证通过；本机事件写 `operations/events.jsonl` 和syslog，`maintenance-monitor-fault-verification.json`。此前错误探针试图宿主回连自身用户态Tailscale地址失败，已改为Serve实际配置检查；宿主配置检查不冒称外部HTTPS可达监测，Windows实际HTTPS另已通过。
- 当前边界：每日备份已安装并同一命令手动实跑，但尚未经历次日03:15触发；没有自动删除/保留天数策略，空间不足会记录告警。已具备NAS本地异常/恢复日志，尚无对人的主动通知渠道；不把syslog写入算成外部告警闭环。未正式切库，不替代用户/团队持续试用和专业批准。详细操作见 `scripts/deploy/README.md`。

- 按用户最新要求，密码策略改为 **8–128字符**，后台统一校验、可信终端及网页创建账号的minLength/说明一致。原先创建失败已由用户终端输出定位为不足15字符，非NAS服务故障；当前已修正操作助手失败时输出长Python traceback的问题。9项身份测试通过（原8项+7/8/128/129边界及真实HTTP创建/登录），前端构建通过。NAS已重建并只更新应用容器，镜像 `sha256:7aea1958e6792086fe26d5be74206fa191d779e45763ef0670941dbcad8f8f85`；实际新镜像在临时库以随机8位密码创建/登录成功、7位拒绝，HTTPS及全部首页资源200、匿名业务401。证据 `password-identity-tests.log`、`password-boundary-tests.log`、`password8-nas-image.json`、`password8-https.json`。个人账号尚未创建，请用户重跑原助手；没有代设密码或改动个人账号。旧应用镜像另保留 `rkd-ai:20261030-before-password8`，本次源码补丁前文件存于NAS `password8-before.zip`，release manifest已记录策略补丁。此前完整备份不包含该新策略，恢复旧包后需重新应用本补丁。

- 用户回复“已创建”后的实际复核：HTTPS auth/config仍为 `initialized:false`，通过实际应用账号仓储亦确认尚无个人账号。可信SSH交互命令已实测正常进入用户名提示后主动取消，未填写/创建任何测试个人账号。已请用户提供创建命令最后几行提示（不含密码），等待定位其操作结果；不能只凭回复把个人初始化或登录试用计为通过。证据 `personal-admin-recheck.json`。
- 已把NAS完整归档复制到当前Windows机器：`var/evidence/m5-nas/20261030-130245-a70474/nas-complete-20261030T135735.zip`，21,714,299字节，与NAS原SHA256完全一致；Windows实际安全解包并校验全部成员，58表/74运行文件/284应用文件，见 `off-nas-copy-verification.json`。这是单次异机副本与包完整性验证，不是Windows数据库恢复/定期异机备份验收；该快照仍在个人账号创建之前。

- 用户sudo已成功，新SSH确认Justin属于docker组。独立 `rkd-ai-app-1` / `rkd-ai-database-1` 均healthy；应用18080、数据库15432仅回环。私有Tailscale Serve9443转发应用，现有443/8443及Funnel配置保留，9443未启用Funnel。Windows实测证书校验通过、首页/ready/auth-config均200，未登录项目401，账号未初始化；`https-final.json`、`tailscale-https-isolation.json`。
- Docker Hub及替代源相同层持续下载失败，明确采用 `scripts/deploy/compose.nas-cache.yaml`：固定摘要的官方MCR Debian基础镜像安装Python3.11.2，以及缓存的官方PG16.15；NAS宿主/其他服务未改。应用镜像 `sha256:55d0d4869eadfd80f70f2e6c5c91248645669f58afd4a608fe8e72f12ab0af01`，PG镜像 `sha256:6a2e324ebe59af6031c4c1cd96c1d5072c2ebc36563d2196365e43b8297c062d`。NAS原生Linux完整回归182/182、ASGI4/4，真实PG16的16内核+45业务+8身份=69/69，均无跳过；`pg16-live.json` 和 NAS `qa/*tests.log`。原Python3.12/PG17配置及本机既有通过证据保留，不冒称实际NAS用了PG17。
- 修复首次初始化snapshot挂载指向错误及Windows成果路径分隔符在Linux导入失败；只在PG目标规范化安全相对路径，源SQLite和原件不改，路径穿越在连接数据库前拒绝。初始化真实40表/733行/74文件通过；中间路径诊断库独立保留为 `rkd_team_path_probe_20261030`，最终业务库全新初始化。`portable-path-negative.json` 与 `nas-runtime-recheck.json` 证明重启后8项目74文件大小/SHA一致；前次容器停止期间的校验错误日志保留，不计通过。
- `operations.json` 实测容器内部应用进程退出→Docker自动重启（RestartCount=1），再实际重启独立数据库，ready和账号闸口恢复。最初验证器使用docker kill，属于操作员停止而抑制restart policy；改为内部信号并等待StartedAt变化，修正旧进程ready造成的竞争，保留失败记录，不将失败运行计通过。健康探针与日志轮转已生效；尚未完成外部告警闭环。
- NAS完整备份 `/home/Justin/rkd-ai/backups/20261030T135735/complete.zip`，SHA256 `fd30ba0fd977fb2438abb12e2e49c0659b19285119095358d89c8adb2fa788cb`。恢复至新空库/新目录，58表、74引用文件、284应用文件通过，8项目全部文件逐项校验；实际启动归档FastAPI代码，ready200、匿名业务401。`nas-recovery.json`；恢复10.296秒，未覆盖运行数据。首次个人账号尚不存在，因此不宣称本次NAS包验证了个人密码恢复；此前PG17身份恢复证据另列。现另有Windows副本并已验证全包，异机数据库恢复和定期备份仍未计通过。
- 原355文件ZIP保持原SHA不变；暂存目录后续配置/导入器/运维脚本更新已记录 `final-release-verification.json`，当前清单360文件，snapshot完全未变。应用镜像构建早于最后运维验证脚本，不宣称全部运维文件已进入该镜像；服务业务修复已实际构建并完成运行验证。
- 当前用户步骤：Windows PowerShell执行 `ssh -t -i "$env:USERPROFILE\.ssh\id_ed25519_nas" Justin@100.73.240.73 "python3 /home/Justin/rkd-ai/setup-admin.py"`，自己输入用户名/显示名/8–128字符密码两次（隐藏回显）。密码不交给AI；没有默认账号或HTTP注册入口。完成后实际个人登录/团队试用再推进，未正式切换日常权威库。

### 准备期历史（以下“未启动/待授权”描述仅代表当时，不是当前状态）

- 完整恢复最新真实证据 `var/evidence/m5-postgres/run-20261030T124442-b4b134/verification.json`：58表；独立生产链48文件/272应用文件，实际8项目74文件/275应用文件；归档代码下载、应用重启及数据库实际重启均通过。112预算行、5问题、104㎡/¥13,104、收货和变更再生产幂等保留；原密码/角色保留、旧会话失效。源运行数据未替换。
- 浏览器旧请求延迟后切换新项目的真实反例已通过：旧响应不覆盖新项目需求/预算/采购，不触发旧预算后续请求；1440/390无横向溢出，登录/只读/撤权/退出/上传下载通过。证据同目录 `account-browser/accounts-browser.json`。10-29 `143512` 运行在最终数据库重启复核中遇 Windows 进程异常退出，不计整轮通过；修正验证器在失败时仍写通过、清理错误掩盖原错的问题，失败记录保留，以10-30复验为准。
- 新增 `ApiRoutes` 共用业务派发、FastAPI ASGI 传输和账号专用 `run_team_api.py`；Uvicorn负责HTTP解析，受限请求流/临时文件、固定Host/Origin、Secure Cookie、拒绝伪造代理头；不复制业务授权规则。4/4新传输专项通过，完整回归182/182，严格环境检查通过。真实PostgreSQL/浏览器及应用/DB重启组合已通过：`var/evidence/m5-team-transport/20261030T130512-bd0fce/verification.json`，直接执行NAS初始化程序，迁入8项目74文件、已有目标拒绝、初始无账号401、随后可信终端初始化测试管理员、登录/角色/上传下载及桌面手机通过；API和DB重启后原会话与74文件均有效。早期失败为测试头名大小写假设及未等拦截请求收尾，均修正后完整复验；不计失败运行的中间通过JSON。
- 用户明确指定经Tailscale部署FN NAS。只读确认在线Linux节点 `100.73.240.73`、Debian12、23GiB内存、现有Docker/Compose；已用现有密钥作为Justin连接。NAS现有8080/8081/8082、5432等端口已有服务，候选选择独立回环15432/18080、独立Compose项目/named volume，不改旧服务、代理、用户数据。最初Docker组无Justin、socket拒绝，用户已在可信终端执行sudo授权；新SSH已确认docker组及Docker28.5.2可用。
- 部署脚本位于 `scripts/deploy/`，源码/依赖/构建前端及真实数据通过完整备份、隔离恢复后形成SHA校验包；密码仅NAS生成且不输出，应用不挂载数据库owner凭证。候选只是快照，账号模式不自动退回免登录，首位个人管理员只通过可信终端交互设置；团队HTTPS、故障重启和NAS备份仍待实测。
- NAS已实际暂存到 `/home/Justin/rkd-ai/releases/20261030-130245-a70474`；ZIP SHA-256 `a2a670230e1304f68e3da493ff3a4f8bd8eebf1de8669cdff3bc6c745631e391` 与本机一致，355文件/74运行文件逐项验证；`docker compose config --quiet`=0，部署根/凭证目录700，独立凭证仅目标容器可读。证据 `var/evidence/m5-nas/20261030-130245-a70474/` 的 release-report、nas-staging及nas-config-verification。容器未启动，网络端口未开放；包内代码基线对应13:02快照，后续浏览器验证脚本收尾修正及动态文档只在当前仓库更新，业务服务代码一致。
- 部署配置已把Python/PostgreSQL固定为上游已核对manifest digest，并增加启动前暂存文件摘要复核及40秒正常停止期；4文件配置补丁在NAS应用前复核原355文件，旧配置单独保留 `configuration-before-pin.zip`，随后更新候选manifest。`nas-config-pin-verification.json`及`nas-config-pinned-check.log`证明确认，Compose再次校验通过；未启动容器。原ZIP仍为未修改基线，不冒称补丁后配置与旧ZIP逐字节相同。
- 额外NAS原生Linux依赖兼容性试装位于 `/home/Justin/rkd-ai/qa-venv`，日志 `/home/Justin/rkd-ai/qa/dependencies.log`；当前仍下载，不计测试通过，不是生产运行环境（生产固定Python3.12容器）。本机执行会话91947在等待SSH内pip结束；接管先检查进度，无需重复安装或删除目录。
- 准备期曾需用户通过sudo加入Docker组；现已在新SSH核实成功，详见上方最终复核，无需重复授权。
- 日常本机入口 `http://127.0.0.1:8080` 在完整备份后已加载当前代码，实际PID35360，SQLite schema17、0个人账号；8项目/74文件下载大小与SHA复核通过。证据 `var/evidence/m5-business/2026-10-29/daily-entry-20261030.json` 与 `pre-nas-local-start-backup.json`。历史PID不代表当前进程。

## 2026-10-29 M5-03b 首轮恢复与浏览器发现

- 首轮完整 PG 恢复已通过：`var/evidence/m5-postgres/run-20261029T142058-6a57bf/`，58表/48原件与成果/268应用基线文件逐项核对；112预算明细、5问题、104㎡/¥13,104生产、采购收货及变更幂等保留。旧会话401、原密码/只读角色保留，损坏包在数据库写入前拒绝、非空库/已有目录/部分RLS备份拒绝；归档代码实际HTTP下载48份、API及数据库重启均通过。当前全量178/178。日常库未替换。
- PG 浏览器登录/账号/角色/上传下载/退出、1440及390无溢出通过。但截图发现旧项目慢请求可能回写新项目计数，属于真实前端状态缺陷；正在修复失效响应、隔离项目组件，并加延迟响应浏览器反例。下一轮同时恢复现有8项目/74文件的PG包；通过前不将整个恢复/浏览器最新批次计完成。

## 2026-10-29 M5-02c 账号、会话与角色接入

- AccountIdentityProvider 共用原 PBKDF2、会话、CSRF、角色和管理规则，静态命名 SQL 的 SQLite/PG AccountRepository 分开执行；没有 SQLite 回退。007 新增组织登录限流表，不放开旧全局限流表；角色目录函数仅返回当前组织活动账号的项目/角色，固定 search_path、撤销 PUBLIC 执行，底层成员表保持项目 RLS。
- 还修复可信终端启用账号后旧本机进程继续免登录的缺口：每次 API 请求（包括无头的旧签名下载）先检查账号模式；启用后立即 401，重启自动账号模式。两种启动器均拒绝显式降级，无默认密码；`postgres-accounts` 只在用户终端交互设置密码，未操作日常账号。
- `var/evidence/m5-postgres/run-20261029T140937-ae82be/` **业务45/45、身份8/8、内核16/16**；真实非 owner PG 上八类账号 HTTP/并发/限流/撤销/到期/整笔回滚/跨组织测试通过。API 子进程实际由本机模式切账号模式，老进程访问即时关闭、显式降级拒绝、只读写入403/撤权下载404；API 和数据库重启后原会话/角色及全业务成果保留。40表/733行/74文件只读迁移对账通过，测试实例已停止。
- 全量 **175/175，0失败/0跳过**（`regression-after-identity-retry.log`），环境、前端构建通过。第一次验证的旧迁移数量断言已跟007更新；Windows PowerShell 5 中文脚本加 UTF-8 BOM，失败日志保留。
- PostgreSQL 启动器已接构建工作台和现有登录页面，真实浏览器复核待下一批与完整恢复一起验证；未宣称已切库或团队上线。下一工程项 M5-03b 完整 PostgreSQL 备份/恢复（含全部文件、应用基线、角色和会话撤销）。日常入口仍为之前已验收进程，账号变更待下一完整批次后重载。

## 2026-10-29 M5-02c 独立参数几何链接入

- SpatialService 使用同一 Decimal/扣除约束/量价/六份成果规则与显式 SQLite/PG 仓储。项目事务串行化 CAS、仅当前完全不变复用、恢复旧尺寸成为新修订；真实量 ID 进入 manifest/CSV。没有增加模拟 BIM 或正式专业对象。
- 修复默认空间编号仅含项目 ID 的冲突：新默认编号包含组织/项目范围摘要，旧默认对象优先识别并沿用，原历史和哈希不重写；显式占用编号返回 409，不读取其他项目。SQLite 新增组织同名项目及历史编号反例通过。
- PG `var/evidence/m5-postgres/run-20261029T135232-274516/`：业务 **45/45**、内核 **16/16**；46㎡/¥5,796 扣除量价、真实六成果/量 ID、仅成本修改、旧尺寸恢复、新旧价格/unknown/零、后置写失败整笔回滚、两个并发 CAS、作用域与同大小篡改、M2→变更基线和六份受影响成果通过；同步覆盖上一批新增预算篡改直接拒绝断言。前轮仅测试错写 not-approved 与既有 not_approved 枚举不符，已修正，失败日志保留。
- 实际 HTTP 10→12→10，再只改成本 100→200，当前 v4/¥12,600、无变化复用；旧/新 12 文件下载和实际 ZIP，API 与数据库重启后全部保留。迁入 40 表/733 行/74 文件对账通过，测试实例均停止。
- SQLite M2 专项 **10/10**；全量 **174/174，0 跳过/0 失败**，见 `var/evidence/m5-business/2026-10-29/regression-after-spatial.log`。完整备份记录 `pre-business-load-backup.json` 后仅重启本次自启的已核对进程，默认入口已加载任务/预算/M2 重构。`daily-entry.json` 实际读取 8 项目并下载核验全部 74 个当前组织运行文件（8 原件、15 M2、42 设计、9 变更），旧字节/大小/哈希均匹配。SQLite schema17、本机身份，未切 PG 或启用个人账号。
- 下一任务：M5-02c 账号/会话/角色接入；登录限流、组织级成员摘要需专用持久边界，不放宽项目业务 RLS。用户尚无需补资料，首次正式启用个人账号仍由用户设置密码。

## 2026-10-29 M5-02c 预算接入与成果保护

- EstimateService 使用显式 SQLite/PG 仓储，共用实际 XLS 规范化导入和 Decimal 计算；源字节哈希、112 明细、成本加成/试用税率、unknown 与来源标签沿用。并发导入/编辑/试算/导出按项目事务串行；版本与明细/计算失败一起回滚。没有运行时 SQL 翻译或存储回退。
- 一起修复预算成果的旧目录缺口：新导出使用服务器独立目录，不再按项目名/修订号拼接共用路径；同一事务读取并导出当前修订，重试验证已有文件大小/SHA-256，下载拒绝同大小篡改。新导出失败不残留元数据、不覆盖旧文件；异常/崩溃孤儿目录暂不自动回收。
- `var/evidence/m5-postgres/run-20261029T134034-f4eb29/` 业务 **40/40**、内核 **16/16**：真实源明细合计 ¥616,308.50/差 ¥0；单行数量 6→7.5、成本精确变化 ¥157.50；设计成本 ¥1,000 按加成 60%/试用税 5% 得 ¥1,680；旧版不可变、整笔回滚、并发 CAS/导入/导出及两个组织同项目 ID 导出目录隔离通过。
- `api-verification.json` 实际 HTTP 接收 XLS 字节，再经可信测试设置导入既有规范化明细（没有新增通用预算上传解析器）；读取/编辑/试算至 v3，下载 v1/v3 共 4 份真实 HTML/CSV，API 和数据库重启后文件/计算保留。40 表/733 行/74 文件迁入对账通过，测试实例停止。追加 PG 预算篡改直接拒绝断言将在下一轮独立 M2 接入复跑时覆盖。
- SQLite 预算/导出专项 **9/9**；全量 **173/173，0 跳过/0 失败**，见 `var/evidence/m5-business/2026-10-29/regression-after-estimates.log`。默认日常服务保留上一已加载批次，任务/预算待下一完整批次通过后一并重载；入口仍可操作 LINK-02。下一工程项：独立 M2 参数几何/量价/成果的 PG 接入。

## 2026-10-29 M5-02c 任务/问题接入

- TaskService 共用 CAD 派生报告导入、来源哈希、问题处置规则，显式 SQLite/PG TaskRepository；不模拟重新解析 CAD，不提升候选专业状态。PG 所有操作限定当前项目，写事务锁定项目；可见孤儿 running 在取得项目锁后恢复，未绕过 RLS 全局扫描。
- 修复两个实际缺口：失败导入的业务数据通过保存点整笔撤回，失败 attempt 仍保存可重试；重试从同一批实际读取字节计算哈希并解析，变化后的报告不能沿用旧任务输入标识。问题处置及追加历史同笔事务，CAS 串行并发，一个赢家。
- PG `var/evidence/m5-postgres/run-20261029T133112-cdeed8/`：业务 **34/34**、内核 **16/16**；真实 SQL 错误注入后 0 残留问题，重试成功 5 条，双并发导入只执行一次；项目隔离、问题/动作回滚、并发 CAS、孤儿恢复/取消通过。`api-verification.json` 记录真实 HTTP 读任务/5 问题、处置 v1→v2、拒绝旧版、任务重试至第 2 次及拒绝取消完成任务；服务端操作者不可伪造。API/数据库实际重启后状态/来源/历史保留，40 表/733 行/74 文件迁入对账；测试实例停止。
- SQLite 任务专项 **6/6**；全量 **171/171，0 跳过/0 失败**，环境及前端构建通过，见 `var/evidence/m5-business/2026-10-29/regression-after-tasks.log`。日常服务尚未重载任务重构，待下一批完整回归后一起加载；LINK-02 页面已可用。下一工程项是预算服务/真实成果的 PG 适配。

## 2026-10-29 LINK-02 复核后模型再生产与 PG 变更域

- LC01—LC06 **6/6 工程验收**：结构化尺寸变更绑定当前设计；同一几何/Decimal 计量规则计算候选分区及真实差量；分析冻结需求/设计/量价参数；负责人提交检查项与证据后记录通过/需修改/拒绝；单独生成新需求→设计→量价/采购草稿；旧成果、并发幂等、失败回滚及独立重启。正式审签、发布、真实采购与付款未执行。
- 全量 **169/169，0 跳过/0 失败**，含严格环境检查/前端构建：`var/evidence/m5-business/2026-10-29/regression-after-changes.log`；SQLite 变更/旧 M4/地坪专项 23/23。编辑者/只读用户调用再生产返回 403，操作者由服务端身份确定。
- 浏览器证据 `var/evidence/change-reproduction/run-20261029T132157-3883a0/verification.json`：实际页面提交、查看候选图、填写复核证据、生成新草稿；78→104㎡、未税成本变化 ¥2,600、含税 ¥9,828→¥13,104；原 8/8 成果哈希不变，分析 HTML 和新 ZIP 实际下载，桌面 1440/手机 390 无溢出，截图已人工查看；两次独立 API 进程及完整恢复 43 表/41 文件通过。前轮流程已通过但控制台 GBK 输出失败，改为 ASCII JSON 后复验，失败日志保留。
- PostgreSQL `var/evidence/m5-postgres/run-20261029T131956-109942/`：业务 **29/29**、内核 **16/16**，显式 ChangeRepository；同笔事务驱动需求/模型/量价/订单/变更事件。包括末尾写失败整笔回滚、两个并行请求只生成一组版本、价格变更拒绝旧结论、手填差量来源未验证、跨项目与篡改拒绝。真实 HTTP 在原 104㎡基础再变更到 130㎡/¥16,380；3 分析文件、8 新生产文件及 16 旧生产文件，API/数据库重启后全部保留。迁入 40 表/733 行/74 文件逐项对账；测试 API/数据库均已停止。首轮仅旧式测试误传 v0 被正确拒绝，修正读取实际版本后整轮通过。
- 默认入口 `http://127.0.0.1:8080` 已加载本批；schema17、本机固定身份、8 项目/8 原件下载核对，见 `var/evidence/m5-business/2026-10-29/daily-entry.json`。只重启本次自启且已核对命令行的服务；重启前完整包记录 `pre-link02-load-backup.json`。未切换 PG 或启用个人账号。应用包/原件/已有未提交工作保留。
- 当前限制：仅规则矩形分区/地坪，重新生成分区会重排人工位置；UI 已说明。普通异常回滚数据库且不覆盖旧文件；进程崩溃遗留的无引用目录尚未自动回收。其余专业构件、复杂损耗、施工详图、团队/专业验收仍待实施。下一工程任务是 M5-02c 任务/问题接入。

## 2026-10-29 M5-02b 地坪生产链接入完成

- DesignService/ProductionService 共用原有几何检查、Decimal 算量及量价公式，配显式 SQLite/PG ModelRepository；需求/设计/量价/采购由同一 PG 事务及项目行锁串行化。没有 SQL 文本转换或 SQLite 回退；草稿仍未专业批准。
- 证据 `var/evidence/m5-postgres/run-20261029T125904-791e54/`：业务专项 **24/24**、内核 **16/16**；新增自动工程量/未知成本/真实成果、78→104㎡/¥9,828→¥13,104、整个设计/订单/生产失败回滚、设计及量价并发 CAS、旧收货基线及有事实后待核对、越权与同大小篡改拒绝。
- `api-verification.json` 记录真实子进程 HTTP：需求、设计、价格、地坪生产/采购自动传播，8 份当前成果和 8 份旧成果逐字节核对；实际下载 `postgres-production-v3.zip`；API 重建和 PostgreSQL 重启后全链 ID/量价/成果保留。此次全部测试进程已停止。
- SQLite 模型/需求/生产专项 **25/25**；重构后的全量日志 `var/evidence/m5-business/2026-10-29/regression-after-model.log`。早一轮需求/采购后的全量 **160/160** 已通过，见 `regression-after-requirements-procurement.log`。M5-02 整体仍缺任务/预算/独立 M2/变更/身份等域，团队上线及专业评估未完成。
- 下一工程项按计划 12.5 扩展 LINK-02 变更后的再生产，同时接入变更 PG 服务；已经贯通的地坪链可以作为确定性执行器，避免用户验收后仍需重新录入尺寸和价格。日常运行继续 SQLite。

## 2026-10-29 M5-02b 需求与采购接入（设计/量价继续中）

- 需求使用同一 RequirementService 规则与显式仓储：实际上传文件和决策冲突进入来源快照；并行首次生成复用同一修订、编辑 CAS、无变化复用、旧版不可变、修订与当前指针失败整笔回滚。真实 PG 需求专项新增 5 项，通过后继续采购接入。
- 采购使用同一 ProcurementService 的数量守恒、幂等及旧设计基线保护，配显式两种 Repository；PG 项目行锁序列化新订单/收货/分派。修复一次多行分派被旧唯一键阻止的缺陷，SQLite 017/PG 006 保留旧记录，将每行事实键限定为命令键+行 ID，整笔幂等仍由采购事件负责。
- 证据 `var/evidence/m5-postgres/run-20261029T125044-2c0aaa/`：业务专项累计 **18/18**，内核 **16/16**；真实 HTTP 生成需求 v1→v2、拒绝旧版本、两材料收货/分派；API 和数据库实际重启后需求来源及分派记录保留。迁入对账仍 40 张目标表/733 行/74 文件，另用新库验证新增域；测试进程已停。SQLite 采购专项 **5/5**；全量变更后回归进行中，不提前计通过。
- 日常服务本次在 8080 无监听时启动自己的进程，启动前完整包 `var/evidence/m5-business/2026-10-29/pre-start-backup.json`；入口 `http://127.0.0.1:8080`，固定本机身份、SQLite；8 个项目及 8 原件真实下载哈希复核通过，见 `daily-entry.json`。仅从 schema14 升级至16；017 尚待完整回归后重启加载。未切 PG、未启用真实账号、无外部动作。
- 下一项：同源设计/地坪生产接入，使保存设计与生成量价/采购仍在同笔 PostgreSQL 事务。M5-02b 整项未完成。

## 2026-10-29 M5-02a 项目/文件真实 PostgreSQL API

- `postgres_api_service.py` 与显式 `PostgresFileRepository` 接入同一 `FileService` 验证、落盘和哈希流程；日常 SQLite 也使用显式适配器。项目名/版本规则共享，PG 项目修改、事件、Outbox 和审计同笔提交；并发 CAS 只接受一个版本。上传行锁及项目级文件修订锁保证竞争请求不能删除赢家文件；失败清除自己的新原件链接，保留 staged 字节可重试。
- 新 PostgreSQL 005 提供显式组织级项目摘要函数，固定搜索路径、撤销 PUBLIC 执行，应用角色由可信初始化器单独授权；原项目及子域严格 RLS 不放宽。固定本地身份忽略伪造头；账号域未接入前试点入口拒绝当前组织已有账号的数据，其他域返回 501，不伪装已完成。入口 `scripts/rkd.ps1 postgres-api` 需要显式 DSN/独立运行目录，只监听回环，不改变默认 start。
- 真实证据 `var/evidence/m5-postgres/run-20261029T124059-73a82b/`：`business-tests.log` **8/8**（组织摘要与项目 RLS、项目并发 CAS、4 个并发同名版本、同会话并行接收、文件/项目事件回滚、错误哈希/中断/跨项目、显式未接入拒绝）；内核 **16/16**。`api-verification.json` 记录子进程实跑 GET/POST/PUT/PATCH、两份文件字节及签名下载；API 重建、数据库重启后名称 v1/文件版本与哈希保留，未产生 SQLite。测试 API/数据库均已停止。
- 全量 **159/159，0 跳过/0 失败**，含严格环境检查和前端构建；日志 `var/evidence/m5-business/2026-10-29/regression.log`。新增 SQLite 两项反例验证并发上传与插入失败后的重试；初轮重构造成中文种子路径编码错误，修正后宁波导入/下载及全量通过。PG 初轮失败仅因新迁移 005 后回滚测试仍断言 4，已修正并整轮复跑，失败目录保留。
- 目前只接通项目与文件 API；需求/设计/量价/采购/任务/预算/身份域逐项继续。日常 SQLite 权威数据未切换，M5-02 整体和团队运行未验收。

## 2026-10-29 LINK-01 地坪贯通与复验

- 同一保存的设计模型自动驱动地坪量、成本加成/试用税率报价、图面、采购需求及 8 份成果；分区对象 ID 稳定，生产修订引用真实需求/设计基线和自身持久工程量 ID。默认计功能区，可选择通道；未分配区不计，损耗未知。成本空白保持 unknown，显式 0 独立处理。
- 材料规格/供应商/到货地点齐全时，同一数据库事务生成 M4 本地草稿；参数、设计、量价及订单失败整笔回滚。旧基线禁止新增收货；已有收货/分派事实时最新需求标记待核对，保留原事实，避免重复整单采购。没有真实外部下单或付款。
- LP01—LP06 **6/6**：保存设计自动计量；量价参数/unknown；尺寸修改传播；8 份成果同源引用及历史完整性；采购草稿与旧事实保护；真实浏览器/下载/独立重启/恢复。证据 `var/evidence/production-chain/run-20261029T122244-9ef4b8/verification.json`：78→104㎡、含税 ¥9,828→¥13,104，旧 8/8 文件哈希不变，ZIP 成员和工程量引用一致；桌面 1440×1000/手机 390×844 无溢出，截图已人工查看；两次隔离服务均已停止。
- 增加 SQLite 016、PostgreSQL 004；生产专项 **11/11**，全量 **157/157，0 跳过/0 失败**，日志 `var/evidence/production-chain/2026-10-29/regression.log`，含环境严格检查及前端构建。首次 HTTP 新测试漏传开发身份头导致失败，补齐后全量通过，失败日志保留。生产链完整恢复另校验 43 张表、38 文件。
- PostgreSQL 复验 `var/evidence/m5-postgres/run-20261029T122319-f9139c/verification.json`：内核 **16/16**，40 张目标表/733 行/74 文件逐行及字节对账；独立新生产链导入保留 78㎡/¥9,828、8 成果和采购来源引用；数据库重启通过，测试实例已停。初轮末尾仍断言旧迁移数 3，修正为 4 后整轮通过，失败目录保留。
- 本地运维入口也已实跑 backup/restore，证据位于恢复演练目录的 `operator-backup.json`、`operator-restore.json`；35 张表/74 文件/241 应用文件恢复通过。首次恢复包验证仍为 233 个应用文件，新增文件导致后续基线数量增加，均按各自 manifest 对账。
- 该切片只实现净地坪数量、试用量价和未批准草稿；墙/顶/构件、损耗规则、模型 API、专业图纸及变更验收后自动改模型仍未实现。规则计算不冒称 AI 或专业审核。

## 2026-10-29 M5-03a 本地完整备份恢复

- `scripts/rkd.ps1 backup` / `restore -Archive <包> -Destination <新目录>` 已接入；核心 `local_backup.py` 使用 SQLite 一致快照，按库内引用校验所有原件/成果字节，并归档当前未提交代码、锁定依赖、种子资料和已构建前端，形成独立可检查的应用基线。实际 Git HEAD 为 `83ca002`，与早期“无提交历史”的历史描述不同；本批没有重置/提交既有改动。
- 完整证据：`var/evidence/local-backup/run-20261029T121047-6219c6/verification.json`；`daily-complete.zip` / `daily-restored/` 为真实包和恢复目录。35 张源表逐行摘要一致，74/74 运行文件、233 个应用文件校验通过；恢复使用的是包内代码/前端，真实 HTTP 读取 8 个项目、各域列表和 31 次原件/当前成果下载，服务重建后项目一致。恢复耗时 0.844 秒，数据时点 `2026-10-29T12:10:47.408314+00:00`。
- 独立账号源库验证：密码哈希与 viewer 角色保留；恢复清除旧会话，旧 Cookie 返回 401；重新登录后下载成功、写入返回 403。恢复只写新目录，不改变原库会话。中断上传恢复为 failed，明确重新上传；运行任务由现有恢复机制转可重试，历史修订/幂等事实保留。
- 专项 7/7 通过，覆盖恢复目录无 Git 时重新归档应用基线、完整恢复、篡改文件/包拒绝、路径越界/Windows 路径冲突拒绝、已有目标拒绝及未提交事务不进入快照。初轮 HTTP 辅助脚本因开发身份没有 mode 属性退出，修正读取默认值后上述完整演练通过，失败目录保留。
- 没有替换日常库/服务，原件只读；不打包系统 Python、.venv、node_modules、环境秘密或整台机器。恢复代码的依赖按包内锁定文件重建；本次使用本机已固定的 Python 依赖。M5-03 PostgreSQL 恢复、团队灾备及恢复点目标评估仍待后续验证。

## 2026-10-29 M2 审核缺陷修复与复验

- 业务修复：`spatial_service.py` 将价格、公式与父修订纳入新生产输入哈希，仅与当前修订做无变化比较；回到旧尺寸创建新版本。旧行/哈希/文件不改写，兼容旧几何哈希，无数据库结构迁移。
- 新成果目录只使用服务器生成的唯一修订 ID；从 `quantity_items` 查询真实 ID 写入 manifest/CSV。下载核对大小及 SHA-256，同大小内容篡改也拒绝。
- M2 专项 **9/9**（新增 7 项业务反例）：价格/税率/加成/unknown/零成本/来源、历史值恢复与当前复用、旧哈希兼容、多空间/组织隔离、工程量引用、同大小篡改及失败回滚重试。日志 `var/evidence/m2-audit-fixes/2026-10-29/focused.log`。初轮新增测试因 Windows SQLite 测试连接未关闭导致清理失败，已修正连接关闭后复跑通过，不将失败轮计为通过。
- 真实 HTTP/进程证据：`var/evidence/m2-audit-fixes/run-20261029T115816-f40c53/verification.json`，四个缺陷及篡改拒绝均通过。成本 100→200 后含税价为 ¥12,600；10→12→10 后停止并重建隔离服务，当前仍为 v4/10m/¥12,600；第二空间生成后旧 6/6 文件字节和哈希不变；下载 ZIP 的 manifest/CSV 引用实际库内工程量，成员哈希一致。实际下载文件 `downloaded-production-v4.zip` 位于同目录。
- `pwsh -NoProfile -File scripts/rkd.ps1 test`：环境严格检查、前端生产构建及全量 **139/139、0 跳过、0 失败**；日志 `var/evidence/m2-audit-fixes/2026-10-29/regression.log`。保留既有 PDF.js 大包提示。本批没有新增浏览器验收；通过的是实际 HTTP、文件和进程验证。
- 仅启动/停止本脚本创建的两个隔离服务进程，未替换日常服务或运行库；`source/` 原件未改写。既有已损坏历史成果不自动修复，异常遗留文件清理/完整崩溃恢复仍待落实。日常 API 仍使用 SQLite，M5 整体及跨域生产链未宣称完成。

## 2026-10-28 全面审核与缺陷登记（状态更新至 10-29）

审核报告：`docs/16-全项目目标对齐与执行效率审核.md`。重新执行全量回归 **132/132、0 跳过、0 失败**，前端构建通过，日志 `var/evidence/project-audit/2026-10-28/regression.log`。隔离复现使用实际应用服务、SQLite 和文件，结果 `var/evidence/project-audit/2026-10-28/replay-e9c58ad2/audit-observations.json`；日常库只读检查正常，未改业务代码。

| 编号 | 优先级 | 问题与实际反例 | 状态 |
| --- | --- | --- | --- |
| AUD-01 | P1 | 10×5m 成本 100→200，仅改价格仍返回含税 ¥6,300，正确应为 ¥12,600 | 已修复，HTTP 复验 ¥12,600；其余价格字段反例通过 |
| AUD-02 | P1 | 尺寸 10→12→10，第三次返回 v1/10，但重新读取仍 v2/12 | 已修复，新修订成为当前；独立进程重启复验通过 |
| AUD-03 | P1 | 同项目两个空间均 v1，第二空间覆盖第一空间 6/6 文件，下载查询未拒绝哈希变化 | 已修复，旧 6/6 文件不变；下载完整性拒绝及跨组织隔离通过 |
| AUD-04 | P2 | manifest/CSV 工程量 ID 与实际 `quantity_items` 主键不一致 | 已修复，真实下载 ZIP 的两个引用与库内 ID 一致 |

业务断点另记：M3 分区面积 78→104㎡生成真实图面/CSV，但未生成统一量价/采购/作业记录；M4 分析复制手填差量，验收不再生产模型。它们符合当前受限验收范围，尚不满足最初跨域自动生产目标。上述四个缺陷已于 10-29 修复，业务断点保留，按执行计划 12.5 补齐真实生产链与 M5 接入。

## 2026-10-28 M5-02 真实 PostgreSQL 与迁移证据

- 本地准备：从 PostgreSQL 官方 Windows 页面指向的 EDB 下载固定 17.11-5 压缩包，完整 SHA-256 为 `80379b2c04d51c30225532e0ae04509899141e9957ed096fe749d7fd9df8f82f`；工具仅位于 `var/tools/`，没有注册系统服务。可选驱动及依赖锁定于 `mvp/requirements-postgres.txt`。不再将“没有实例/客户端”列为当前阻塞。
- 新迁移 `003_tenant_integrity.sql` 补齐四类子表的租户列/RLS、项目级项目读取策略及关联表的复合 FK；收货行/分派绑定同一订单。迁移器加会话锁、文件校验和、历史连续性、降级及旧无校验和历史拒绝；真实 DDL 中途失败不留下表或迁移记录。
- Repository 修复：同键异内容冲突、预期版本检查、首次插入的项目事务锁、命令类型纳入幂等范围、审计与命令/聚合/事件/Outbox 同笔提交；重复初始化不重命名既有项目。生产连接工厂拒绝 owner、超级用户、BYPASSRLS 及角色/数据库管理权限；Outbox 在连接关闭前读取结果，过期/错误租约不能确认。
- `pwsh -NoProfile -File scripts/rkd.ps1 postgres-test`：最终证据 `var/evidence/m5-postgres/run-20261028T140604-ee17c0/verification.json`，**真实数据库专项 16/16，0 跳过、0 失败**。测试源 `mvp/integration/test_postgres_live.py`；专门显式运行，未塞入普通测试后跳过。
- 只读 SQLite 备份为本次目录的 `runtime-before.sqlite3`，源版本 14；导入器对 37 张目标表的 **733 行**逐行规范化比较，包括原金额/数量文本、修订号和 JSON 数据；**74/74 文件**核对字节数/SHA-256。具体表行数及文件清单见 `runtime-reconciliation.json`。8 个项目/8 份原件、560 行预算修订明细、M2/M3/M4 记录及 1 条旧审计均保留；本次没有替换日常数据库，也没有移动原件/成果。
- 独立身份源库验证用户/密码哈希、viewer 成员及审计导入；旧会话不迁入。补验 JSON null/字符串/数字保留、非空目标拒绝、文件哈希变动拒绝及导入末尾注入失败后整笔回滚。检测到非空旧快照域缺少适配时直接拒绝，不能静默丢弃。
- 实际 PostgreSQL 进程重启：启动时间由北京时间 22:06:12 变为 22:06:39，6 条内核事件、迁移记录及导入项目仍保留；结束时测试实例已停止，见 `lifecycle.log`。Windows 沙箱初始化超时及初次 stdout 管道等待的失败目录保留，修复后两轮完整实测通过，最终以上述目录为准。
- 完整本地回归 `pwsh -NoProfile -File scripts/rkd.ps1 test`：**132/132，0 跳过、0 失败**；环境严格检查及前端生产构建成功。PDF.js 既有大包提示保留。详细本批说明 `docs/15-M5-02真实数据库验证与迁移演练.md`。
- 验收边界：共享内核与数据迁移演练已通过，M1—M4 服务、身份登录及 HTTP API 尚未改用 PostgreSQL；没有进行团队/生产切库或 M5-03 完整备份恢复。M5-02 整体保持进行中，下一步是逐域 Repository/服务接入及真实 API 链路验收。

## 2026-10-01 M5 准入复核及 M5-01 首批证据（历史）

- 结论：**可以进入 M5 开发，已开始并交付 M5-01 本机账号切片**。核对计划、代码、原件、历史产物后，先复跑原基线 115/115，再修复准入缺陷并验证最终全量 **123/123、0 跳过、0 失败**；前端生产构建成功。日志：`var/evidence/m5-entry/baseline-tests.log`、`final-tests-rerun.log`。首轮全量曾因旧测试把迁移数量写死为 14 而失败，已更新为 15，并保证断言失败也释放连接；没有把失败运行计为通过。
- M4 补齐：验收幂等先于状态守卫；分析/验收同键校验目标与操作类型；验收必须有非空检查项；收货/分派拒绝重复订单行，写事务从读取数量之前获得锁，并发守恒回归通过；拒绝量化后变为 0 的正数；变更成果页面改为带身份请求真实下载。M4 专项 **7/7**，新增并发/重复行回归不取代 MP/MC 的业务验收分母。
- M3/M4 浏览器复跑：`run-1790859835809/m3/` 包含新需求、96/18/78㎡、19.5→13㎡编辑、16m→104㎡、七成果/旧版下载及实际进程重启；成果检查六个 ZIP 成员、五个内容哈希、104㎡ CSV、米单位 DXF/16×8m 均匹配。`run-1790859835809/m4/` 包含采购链和变更链截图及三份变更文件实际下载哈希；变更绑定测试问题及几何基线。旧工程证据保留，未覆盖用户运行数据。
- M5-01：`test_m5_identity.py` **7/7**，覆盖 MA01—MA06 和启动降级拒绝；MA07/MA08 的真实浏览器/进程证据见 `var/evidence/m5-entry/run-1790860437951/m5/accounts-browser.json`、`accounts-restart.json` 及上级 `entry-verification.json`。不同进程重启后重新登录、成员角色保留；角色撤销、账号停用、退出、空闲/绝对超时均拒绝后续访问；伪造开发头不能改变真实身份。安全 Cookie/CSRF 不代替 HTTPS 部署验收。
- 页面：登录、个人账号创建、项目角色分配、撤销访问、停用/恢复账号已接实际接口；1440×1000 和 390×844 验证均无横向溢出或运行时错误。初轮浏览器选择器与隐式 select 标签问题已修复，随后完整账号流程及重启通过。截图位于上述 `m5/`；检测器仅保留既有 Inter 字体 warning。
- 数据保护：`source-integrity.json` 核对 7/7 宁波原件 SHA-256。现有 8 个项目/8 份文件的数据库快照为 `var/backups/pre-m5-identity-20261001-f1452194.sqlite3`，SQLite integrity_check=ok，原迁移版本 14，清点见 `runtime-before.json`；这只是升级前数据库快照，**不计 M5-03 完整恢复通过**。
- M5-02 首批基础：PostgreSQL 迁移版本 001/002 连续性、旧迁移外层事务归一化、迁移记录/关闭连接、运行域表/RLS/身份审计静态契约，以及 Repository 原子命令事件写路径共 **16/16** 通过；测试文件为 `mvp/tests/test_postgres_migrations.py`、`mvp/tests/test_postgres_boundary.py`。当前机器没有可调用的 PostgreSQL 服务/客户端，本项没有把 SQL 文件执行或假连接测试当作真实数据库验收。
- M5-02 代码接入后的全量回归：`.venv\Scripts\python.exe -m unittest discover -s mvp\tests -p 'test_*.py' -q` **131/131**，0 跳过、0 失败；`npm --prefix web run build` 成功，保留既有 PDF.js 大包 warning。此前 123/123 是 M5-01 交付时的历史基线。
- 日常入口状态：现有 8080 服务 PID 21124 属于本仓库；自动审批以“blocked by policy”拒绝停止/替换该进程，本轮没有再次尝试终止。旧进程和运行库保留，新前端已做兼容并以只读浏览器验证 8 个项目可见、0 页面运行错误，证据 `legacy-entry.json`。**不能声称当前 8080 已启用新账号后台**。首次启用需在原启动终端停止服务，再运行 `start-secure` 设置个人密码；已有账号库启动时自动选 accounts，拒绝退回 local。
- 运行边界：SQLite、参考 HTTP server、回环地址；账号管理员有组织内全部项目管理权，普通用户按项目角色受限；正式发布/采购/付款接口关闭。PostgreSQL 全域适配、真实数据库 RLS、完整恢复、团队部署/监控、专业评估、SSO/MFA/账号恢复流程及持续团队试用未完成。未发现可直接调用的 psql/pg_ctl/Docker 命令，不把此观察写成永久环境结论，也不据此要求用户先安装 Docker。
- 完整复核报告：`docs/14-M5准入复核与首批实施报告.md`。已纠正状态表与交接中的旧 M4 下一步，以及 persistence README 中“只需注入 PostgreSQL 驱动”的不实简化；动态任务状态只维护本文件。

## 2026-09-30—2026-10-01 本轮实测证据

- Windows 本地 `.venv` 使用 Python 3.12.14、Node 24.18.0、npm 11.16.0；固定 `jsonschema 4.25.1` 和 `shapely 2.1.2`。`& .\scripts\rkd.ps1 test` 执行前端生产构建和 90 项测试：90 通过、0 跳过、0 失败；Vite 仍提示 PDF.js 主包超过 500 kB，但构建成功。
- 真实 HTTP + SQLite 集成测试覆盖跨线程创建/编辑、旧版本 409、事务中途失败回滚、进程重启恢复；静态服务测试覆盖 HTML/JS 返回及路径越界 404。
- 浏览器实测：新建 `M1 浏览器验收项目`，更名为 `M1 浏览器验收项目-已保存`，刷新和两次服务重启后仍显示 v1；运行库 `var/app.sqlite3` 内项目关系表版本 1、迁移记录 001/002 均存在。该项目为明确的测试数据，非宁波真实项目。
- M1-04 浏览器实测：首屏默认宁波项目、7 份带来源和 v1 标记的原件；PDF.js 平面图线稿及现场照片成功显示。测试项目通过文件选择器上传 PDF，服务重启后仍存在且显示“未解析”。浏览器原生下载 `C:\Users\Administrator\Downloads\04 平面PL.dwg`，其 SHA-256 与 `fixtures/.../source/04 平面PL.dwg` 同为 `77DDAC8E80401BF3C7913BFF8AC959DC5D4A0CC573EC5CDCBC2CAB5D95A47616`。后台测试覆盖同名文件 v1/v2、上传中断/哈希不符/跨项目拒绝及种子二次导入不覆盖。宁波决策保留 60 万元含税、5% 试用税率、20%/60% 成本加成和源表不含税冲突，不进行正式税务认定。
- 已知限制：PDF.js 当前构建提示主 JS 包超过 500 kB；本地运行不受阻，后续可拆分按需加载。浏览器控制台提示可选 SansSerif 系统字体缺失，图面线稿已显示，原件下载保留完整 PDF。
- M1-05 浏览器实测：重载 `http://127.0.0.1:8080` 后默认宁波项目显示“检查与问题 5”和“成果与任务 1”；问题页显示报告定位、严重度、“专业批准状态：未批准”和处置控件，任务页显示 `cad_report_import`、`succeeded`、`attempt 1`、5 条来源问题及“重启可恢复”。此前通过接口保存的 `in_review` 及理由在重启后仍返回并显示；API 实测重试后 attempt 递增且问题仍为 5 条，取消状态不可再次取消。首次重启窗口中的 `Failed to fetch` 是浏览器在服务切换期间的瞬态，刷新后已恢复。
- M1-06 源预算与试算实测：Excel COM 以只读方式读取 `20260721宁波协诚集团样品展厅装修预算.xls`，抽取展厅/家具 112 条明细，来源金额合计 ¥616,308.50 与源表 `汇总!D8` 对账差 ¥0.00；工作副本按当前项目决定排除 12 行，保留 8 条家具范围冲突提示。预算页显示源优惠价 ¥600,000（源表标注不含税）与合同含税目标 ¥600,000 分开保存，税率只作为本地试用参数；接口编辑第一行工程量 6→7.5 后生成 v3，浏览器将设计未税成本 ¥1,000→¥1,200 并保存为 v4，页面显示设计含税 ¥2,016、合并含税 ¥670,812.66。随后将源明细对账差额先按金额精度量化再生成告警，重新试算生成 v5，`SOURCE_RECONCILIATION` 尾差告警消失。原始 `.xls` 保持只读，派生抽取写入 `fixtures/ningbo-xiecheng/2026-09/derived/budget-source-extract.json`，运行修订写入 `var/app.sqlite3`。
- M1-07 导出实测：新增预算成果表和 `POST /api/v1/projects/{project}/estimates/{estimate}/export`；当前修订生成 `estimate-vN.html` 与 `estimate-vN.csv`，HTML 可独立打开，CSV 为 UTF-8 BOM，数据库保存成果相对路径、SHA-256、字节数和预算修订号。真实 HTTP 下载返回 200，下载字节与记录哈希一致；同一修订重复导出不生成重复成果，跨项目读取返回未找到。浏览器预算页已接“导出当前修订”并显示两个下载成果。
- M1-08 工程验收：使用项目固定 Python 运行时执行 `python -m unittest discover -s mvp/tests -q`，结果 **97 项通过、0 项跳过、0 失败**。U08 由 `test_m1_tasks.py` 覆盖失败/运行中恢复、重试不重复问题和取消持久化；U09 由 `test_sqlite_http_threading.py`、`test_api_service.py` 覆盖 HTTP 并发线程、事务回滚、旧版本冲突和同键幂等；U10 由跨组织文件/成果/项目测试覆盖。8080 服务已用 `pwsh .\scripts\rkd.ps1 start` 启动，环境自检通过。尝试调用本机 CUA 浏览器接口时初始化返回系统路径错误，故浏览器自动化试用未冒称完成；用户可直接打开 `http://127.0.0.1:8080` 进行最后试用。
- M2-05 成果生命周期实测：10×5−2×2 生成 v1 后修改为 12×5−2×2，v1 的 6 个空间成果状态均变为 `superseded`，v2 的 6 个成果保持 `draft`；预算导出后再创建新预算修订，旧 HTML/CSV 状态变为 `superseded`，文件仍可按原 artifact_id 读取。全量测试 97 项通过。
- M3-01 实测：重启后的 8080 服务 `GET /api/v1/projects/project_ningbo_xiecheng_2026/requirements` 初始返回空草稿；POST `/requirements/drafts` 生成 v1，状态 `draft_unconfirmed`，绑定 12 条决策/原件来源；重复 POST 保持 v1 且输入哈希相同。需求页由前端构建产物提供，规则生成明确标注不代表 AI 设计结果。
- 当前运行入口：`& .\scripts\rkd.ps1 start`，浏览器 `http://127.0.0.1:8080`。本地回环开发身份头只用于试用，不代表生产认证。运行服务正在本机开放 8080 回环端口。

## 2026-10-01 M4-01 首条采购施工链实现证据

- 新增 SQLite 迁移 `013_procurement.sql`，保存订单、订单行、收货、收货行、分派、采购事件；`external_effects_enabled` 固定为 `false`，实际下单与付款没有入口。
- 新增 `mvp/rkd_mvp/procurement_service.py` 和 API：`GET/POST /api/v1/projects/{project_id}/procurement/orders`、订单详情、`/receipts`、`/allocations`。所有数量以 Decimal 文本计算；收货不超过订单，分派不超过已收货未分派；同项目同幂等键同指纹复用，异内容冲突。
- 前端新增“采购施工”页，可创建材料订单草稿、记录收货和分派，并显示订单/已收/已分派/可分派数量及“外部下单已关闭”。
- `.venv\Scripts\python.exe -m unittest discover -s mvp\tests -p 'test_m4_procurement.py' -v`：**3 项通过、0 跳过、0 失败**；覆盖服务层守恒、幂等、项目隔离、SQLite 重启和真实 HTTP 订单→收货→分派。全量测试：**112 项通过、0 跳过、0 失败**。`npm --prefix web run build` 构建成功；仍有既有 PDF.js 大包警告。
- M4-01 验收证据：`mvp/tests/test_m4_procurement.py` 共 3 项通过；`scripts/verify_m4_browser.cjs` 浏览器创建独立测试项目并完成订单→收货→分派，截图 `var/evidence/m4-procurement-browser.png`，页面无横向溢出和运行时错误；运行服务重启后 `/api/health/ready` 为 200，SQLite `schema_migrations` 最大版本为 13，采购列表接口为 200。
- M4-02 已完成工程验收；当前采购施工页只保存本地事实，不执行真实外部下单、付款、签证或施工发布。此段旧“下一步”建议已由 M5 准入复核更正：M4-03 未列入执行计划，不作为新增前置任务；后续按 M5 台账推进。

## 2026-10-01 M4-02 变更闭环验收证据

- 新增 SQLite 迁移 `014_changes.sql`，保存变更请求、基线快照、影响分析、成果文件、验收历史和幂等事件；旧 M2/M3 成果只读保留。
- 新增 `mvp/rkd_mvp/change_service.py` 和 API：变更创建、确定性影响分析、JSON/HTML/manifest 成果下载、验收记录；成本/工程量/工期未提供时保持 `unknown`，不补 0。
- 前端“采购施工”页新增“M4-02 问题与变更”区，可保存变更、生成影响分析并记录验收；页面明确显示待人工确认和旧成果保留。
- `.venv\Scripts\python.exe -m unittest discover -s mvp\tests -q`：**115 项通过、0 跳过、0 失败**；M4 专项覆盖 `test_m4_changes.py` 3 项、`test_m4_procurement.py` 3 项。`npm --prefix web run build` 构建成功。
- 浏览器实测脚本 `scripts/verify_m4_change_browser.cjs`：选取已有 M2 几何基线项目，完成变更→影响分析→验收；影响分析识别 6 个旧成果并生成 3 个新文件，页面无横向溢出和运行时错误。截图：`var/evidence/m4-change-browser.png`。服务重启后迁移版本为 14，变更列表接口返回 200。

## 2026-10-01 M3 完整受限场景验收证据

- 本轮 `pwsh -NoProfile -File scripts/rkd.ps1 test`：生产构建成功，**109 项通过、0 跳过、0 失败**；完整日志 `var/logs/m3-full-tests.log`。新增 M3 用例覆盖包一致性、非法布局/无解、毫米舍入、源需求过期、版本冲突、跨项目隔离、失败回滚、成果字节篡改和 HTTP 恢复；原有宁波需求测试补充验证人工修订及模型成果保留 12 条来源与业务口径。
- 浏览器使用本机配套 Playwright + Edge，不再依赖此前初始化失败的 CUA；脚本 `scripts/verify_m3_browser.cjs`。实际新建 `M3 浏览器验收展厅 1790850507917`（`project_8c42638b9f07`），仅使用测试尺寸，没有修改宁波运行需求/原件。较早一次浏览器脚本因报告文件名写错而中止，已修正并完整重跑通过；另一个明确的测试项目保留，不清理用户运行库。
- DA01/DA02：浏览器保存需求 v2，再生成设计 v1；12×8m，通道 1.5m，总面积 96㎡、通道 18㎡、分区 78㎡。来源传递同时由隔离宁波种子测试核对，默认尺寸始终标为测试参数。
- DA03：接待区宽度 3→2m，面积 19.5→13㎡，生成设计 v2、未分配 6.5㎡；X=11m 越界保存返回错误，当前设计仍 v2，没有半笔修订。
- DA04/DA05：外框宽度 12→16m，保存需求 v3 后设计状态 `source_outdated`；重新生成设计 v3，分区面积 104㎡、通道 24㎡，三个对象 ID 保持一致。浏览器实际下载当前七份成果及历史 v1 ZIP，逐份字节数和 SHA-256 与服务记录一致；历史 v1 标记 `superseded`。证据 `var/evidence/m3/browser-verification.json`。
- DA06：停止已核对属于本项目的服务进程（监听 PID 34024、启动 PID 12024），新服务启动 PID 35572；浏览器刷新后仍为 `design_7dc9766cf8fb` / v3，模型和七份成果元数据与重启前完全一致。证据 `process-restart.json`、`restart-verification.json`。
- 成果检查：`scripts/verify_m3_artifacts.py` 使用配套 QA Python/Pillow；ZIP 六份文件、manifest 的五个内容文件哈希、模型/CSV/SVG 基线一致；CSV 合计 104㎡；现有 ASCII DXF 读取器确认米单位、五条闭合分区/边界/通道多段线，几何最大坐标 16×8m。这是字节/格式工程核验，未宣称 AutoCAD 或专业施工审签通过。证据 `artifact-verification.json`。
- 视觉复验：1440×1000 桌面及 390×844 手机页面 document 宽度与 viewport 相同，无横向溢出或浏览器运行错误；图面三类分区色像素在两种截图中均超过 500，确认非空白。`desktop-confirm.png`、`mobile-confirm.png`、`report.png`、`outputs.png` 保存于 `var/evidence/m3/`。Impeccable 单次检测仅报告既有 Inter 字体警告；沿用原工作台字体。
- 实际下载入口：工作台“需求草稿→成果与历史”；验证文件 `var/evidence/m3/design-package-v3.zip`、`design-v3.html`、`layout-v3.dxf`、`layout-v3.svg`、`zones-v3.csv`、`model-v3.json`、`manifest-v3.json`。运行地址仍为 `http://127.0.0.1:8080`，只监听回环。已知 Vite PDF.js 主包大小警告保留，构建不受阻。

## 2026-09-29 架构审查与验证基线（历史）

- 默认 `run_api_server.py` 的 HTTP + SQLite 组合：创建项目可复现跨线程连接异常。
- 上传目前只登记元数据；业务命令主要走通用事件 handler；模拟执行器没有生成实际 BIM/图纸/BOQ 文件；成果下载未接通。
- 命令/事件/审计缺少统一事务；失败任务恢复、幂等请求指纹、项目范围键和正式授权均存在缺口。对应任务见执行计划第 13 节。
- 按旧交接命令设置临时 PYTHONPATH 后：75 项测试中 **70 通过、5 报错**；临时目录内 jsonschema/Shapely 包不完整。不附加临时目录的审查记录为 69 通过、6 跳过。跳过不能记为通过。
- 以前记录的 75/75 和 Schema 校验是历史结果，本轮文档修改没有重新执行代码测试，也没有修复以上缺陷。
- CAD/DXF 共同候选比较通过不代表专业对象批准；当前专业对象和可计量对象仍为 0。

## 历史架构与研发资产（不计为产品验收）

| 序号 | 交付物 | 状态 | 文件 |
| --- | --- | --- | --- |
| 0 | 开工前架构预检与扩展性约束 | 已完成基线，进入八项封板设计 | `docs/00-开工前架构预检与扩展性约束.md` |
| 1 | 自主设计公司系统 V1 产品需求规格 | 已完成 V1.1 架构修订版，待产品负责人确认 | `docs/01-自主设计公司系统V1产品需求规格.md` |
| 2 | 完整业务生产链和项目状态机 | P0 修订完成：G2/DesignIntent、财务事实状态机、命令/事件注册表已接入；待业务责任人确认 | `docs/02-完整业务生产链和项目状态机.md`、`contracts/v1/command-registry.json`、`contracts/v1/event-registry.json` |
| 3 | Agent 与专业执行器设计 | P0 契约已收紧：条件结果、规格哈希、输出/验收强类型、CommandEnvelope；待专用 Agent Schema、专业确认和金标准验证 | `docs/03-Agent与专业执行器设计.md`、`contracts/v1/` |
| 4 | 自动空间规划、BIM、效果图、施工图和报价统一模型方案 | 已完成 V1.0 架构草案，待专业责任人确认、真实文件回放和对象映射金标准 | `docs/04-空间BIM成果与报价统一模型方案.md` |
| 5 | 网站、后端、工作流、权限、审计、部署和备份架构 | 已完成 V1.1 架构审查修订，P0/P1 护栏和事件/审计契约已补齐；待技术负责人确认、容量/安全验证和部署演练 | `docs/05-平台后端工作流权限审计部署与备份架构.md`、`contracts/v1/event-envelope.schema.json`、`contracts/v1/audit-event.schema.json` |
| 6 | 第一条端到端纵向 MVP 参考基线 | 有 API、流程、SQLite 快照、PostgreSQL 接口边界和模拟成果链；2026-09-29 审查发现实际入口/事务/上传/任务等缺口，按 M1 补实。CAD 模块及历史测试仍可复用，当前验证结果见上方 | `docs/06-第一条端到端纵向MVP方案.md`、`contracts/v1/openapi.v1.json`、`mvp/` |
| 7 | 宁波协诚试点资料与 CAD 分析 | 640 个共同候选通过图层/类别/类型/二维边界比较，含 70 个块边界；133 个几何组和 70 个闭合区仍是候选。专业拓扑算法和对象确认未完成；本期先用于预览与问题证据，不阻塞 M1 | `docs/07-宁波协诚施工期试点方案.md`、`fixtures/ningbo-xiecheng/2026-09/derived/cad-cross-engine-review-report.md` |
| 8 | 开发团队、阶段、工期、成本、风险、测试和上线计划 | 已完成 V1.0：团队/RACI、8-12 周首链路与 9-15 月正式版阶段、预算带、14 项风险、测试门槛、灰度、回滚和灾备已定义 | `docs/08-开发团队阶段工期成本风险测试与上线计划.md` |
| 9 | AI 自主完成率、图纸错误率、成果一致性和人工干预评估体系 | 已完成 V1.0：合格分母、五级自动化、干预分类、E0-E3 缺陷、一致性/证据/效率指标、阶段门槛和防作弊规则已定义；已建立机器观察合同、历史项目只读导入器和金标准清单合同，待 3 个真实历史项目进入后分层回放 | `docs/09-AI自主完成率图纸错误率成果一致性与人工干预评估体系.md`、`docs/12-历史项目金标准导入与分层规范.md`、`contracts/v1/gold-standard-manifest.schema.json` |
| 10 | 第一周、第一月、三个月和六个月执行清单 | 已完成 V1.0：按用户、实施团队、系统三方拆分行动、完成标准、材料时间表和每周八问 | `docs/10-第一周第一月三个月六个月执行清单.md` |

## 已核对资料

- 当前推进指令：用户在本对话确认先交付可操作系统，并要求先固化计划，避免后续 AI 偏离。
- 较早接管指令曾引用 `pasted-text.txt`，仅属历史背景。
- 旧交接说明：`C:/Users/Administrator/Documents/Codex/2026-09-06/new-chat/outputs/室内设计公司_AI项目_Codex交接说明.md`。
- 工作区在接管时为空 Git 仓库，无历史提交和已有系统代码。
- 宁波协诚样本已接入：1 个 DWG、1 个同源 DXF、1 页 A3 PDF 平面图、1 份旧版 `.xls` 预算、3 张现场照片。接入报告和文件指纹见 `fixtures/ningbo-xiecheng/2026-09/`。

## 用户口径与后续验证边界

- 宁波协诚 DWG 已进入当前工作区，完成首轮结构解析、57 层语义映射、PDF 尺寸交叉核对、块上下文分层、主平面定位、候选提取、嵌套块变换、4 个复杂层定位、几何归组和闭合区候选；尚待第二引擎或原 CAD 软件复核、专业对象确认、客户需求确认、材料样板确认和变更单。
- 用户给出的本地试用口径：含税总价 600,000 元，税率 5%；公式拆税为未税 571,428.57 元、税额 28,571.43 元；施工/设计的 20%/60% 均按成本加成。机电和消防排除。正式财务/合同核验与本地试算分开，不重复询问或阻塞试用。
- 源预算写“不含税”，历史样本清单税率仍为 pending；M1-04 应把最新决策带来源导入运行项目并保留冲突，不能悄悄改原件。
- 3 个完整历史项目尚未提供，当前不索取；只影响未来跨项目质量验证，不阻塞 M1/M2。现有资料与测试模型足够开发。

## 2026-10-01 M2 首个切片实测证据

- 新增 `mvp/persistence/sqlite/007_spatial.sql`、`mvp/rkd_mvp/spatial_service.py` 和空间 API。空间对象默认使用稳定 ID `space-test-floor`，每次尺寸或扣除区修改创建不可变几何修订；扣除区越界、重叠和非正面积均拒绝。
- 前端新增“空间与工程量”页，可编辑外框宽度/长度、添加/删除扣除区、保存修订并查看面积、公式、工程量和历史修订。参数几何明确标记为 M2 受控测试区域，不冒充宁波 CAD 自动识别。
- 后端单测 `mvp/tests/test_m2_spatial.py` 覆盖 10×5−2×2、12×5−2×2、越界扣除和旧修订冲突；全量 `scripts/rkd.ps1 test`：92 项通过、0 跳过、0 失败。隔离 HTTP 实测端口 8091 返回首版 `46.00`、修改后 `56.00`、历史修订 2、工程量 `56.00`。
- M2-03 实测：同一几何修订生成 `geometry-v1.svg`、`geometry-v1.dxf`、`quantity-v1.csv`；逐文件核对落盘字节、SHA-256 和数据库元数据；HTTP 下载 SVG 返回 200、510 字节、`image/svg+xml`。成果页按钮通过带项目身份的请求返回真实文件。
- M2-04 实测：隔离项目首版 `10×5−2×2` 为 `46.00 m²`、含税报价 `¥5,796.00`；改为 `12×5−2×2` 后为 `56.00 m²`、含税报价 `¥7,056.00`。每个修订生成 6 个成果：SVG、DXF、CSV、报价 HTML、manifest JSON、ZIP；成果包 HTTP 下载返回 200/3,822 字节。停止并重启服务后项目仍返回 v2、56.00 m²、¥7,056.00 和 6 个成果。
- 成本快照明确标为“M2 测试成本快照（人工输入）”，报价 HTML 标为“测试/设计草稿 · 非正式报价 · 不用于施工发布”；缺失单位成本时报价保持 unknown。默认 8080 被另一工作区占用时可使用 `RKD_MVP_PORT=8091`。
- Impeccable detector 仅报告现有 Inter 字体为 warning，未发现新增机械性 UI 问题；已在 8091 窄屏浏览器查看空间页，页面可横向浏览表格和标签。

## 当前下一步（2026-11-08）

按执行计划第12.7—12.9节和docs/21第12—13节，不再重复已完成的 01—05 工程切片、01c / DELIVERY-01、真实 PG 与浏览器证据、真实 AI 设计链，以及本批参考真实平面图后的返工。用户已对上一版两个候选给出明确否决并要求学习真实布局，本批已按此重做；最先需要用户参与的是两件具体事：① 打开 `var/review/2026-11-10/real-design-review.html` 看**返工后**的 `hub-branch` / `brand-loop` 两张新概念平面，按 AD08 四项给出认可/待调整/不认可及具体对象，这是 AD08 唯一合法来源；② 决定继续调用的费用/次数上限，以及是否允许模型参考哪些类别的项目资料（默认全部不外发）。不需要再问服务地址、税率、审核人姓名或重做服务器授权。若这版仍不认可，内部应继续补几何能力（多边形分区、墙体围合、柱网/门窗/楼梯与真实尺度校验），而不是继续加管理配套；其余可自主继续的是同边界相反需求对照补 AD02、真实模型链上浏览器与重启补 AD07、图面/对象版本一致性专项补 AD05/AD06、把受限对象的技术深度扩到可专业复核的图纸与材料做法、准备 BUSINESS-01；随后才评估 PLATFORM-01。复用现有工作台、双库迁移、文件校验和备份恢复；不以工程测试数、模型自评或文档页数代替设计与专业验收，AD01—AD08 通过数仍按固定验收逐项确认，本批不自行改判。

## 历史下一步（2026-10-29记录，保留上下文，不再执行）

AUD-01—04、M5-03a 和 LINK-01 当前地坪切片均已通过工程复验。M5-02a 项目/文件已通过真实 HTTP、字节、并发、回滚和重启。下一动作 M5-02b：继续需求修订，再按依赖接入设计/生产/采购等服务；禁止 SQL 字符串转换、隐式 SQLite 回退或两套权威运行库。PostgreSQL 001—004 及迁入对账有效，全域 API 切库尚未完成。M5-03—06 的正式责任和上线门槛保留。日常库仍 SQLite，本批未替换日常服务进程，不据历史 PID 推断当前服务状态；个人账号首次启用使用 `scripts/rkd.ps1 start-secure`。不把宁波 CAD 候选升级为专业对象，不执行真实外部下单或付款。

当前用户无需提供新资料。实际专业对象确认、更多样本、生产账号及正式环境按执行计划后续阶段处理。

## 历史架构设计状态（不作为 M1 开工审批）

| 封板项 | 状态 | 对应交付物 |
| --- | --- | --- |
| 业务域、对象归属和模块边界 | 已建立基线，待在数据模型中验证 | `00-开工前架构预检与扩展性约束.md` |
| 项目配置关系图、统一编码和外部引用 | 已建立概念基线，待逻辑数据模型 | `00-开工前架构预检与扩展性约束.md` |
| 子流程状态机、命令、事件、超时和补偿 | P0 已建立机器注册表，待责任人和真实数据确认 | `02-完整业务生产链和项目状态机.md`、`contracts/v1/command-registry.json`、`contracts/v1/event-registry.json` |
| 版本、基线、分支、发布和变更传播 | 已完成状态规则，待逻辑数据模型验证 | `00`、`02` |
| Agent 权限和执行器协议 | 通用契约 P0 已收紧，CommandEnvelope、ValidationProfile、数据生命周期和执行器供应链护栏已建立；待专用输出 schema、命令网关和金标准 | `00`、`03`、`contracts/v1` |
| WBS、进度、成本、现金和采购模型 | 已建立对象边界，待逻辑数据模型 | 后续数据模型附录 |
| 空间、构件、材料、视图、工程量、价格统一模型 | V1.0 架构草案已建立，待真实文件和专业金标准验证 | `04-空间BIM成果与报价统一模型方案.md` |
| 平台、后端、工作流、权限、审计、部署和备份 | V1.1 审查修订已建立：事务边界、RLS、DLQ/重放、审计防篡改、备份不可变和外部 unknown 状态；待技术验证和演练 | `05-平台后端工作流权限审计部署与备份架构.md` |
| 外部适配器、对账和兼容规范 | 已建立原则，已在第 6 项定义模拟适配器、故障注入和 unknown 对账验收 | `00`、`05`、`06-第一条端到端纵向MVP方案.md` |
| 金标准、测试、发布、回滚和恢复 | 已建立基线，待第 8/9 项细化 | `00`、`08`、`09` |

## 2026-10-30 NAS 权限恢复与实际构建推进

- 用户终端sudo命令返回无报错；已用新SSH核实Justin加入docker组、Docker28.5.2可调用。已执行已校验候选的host_deploy，未动既有容器。NAS已有Tailscale Serve443/8443及对应Funnel给其他服务使用，拟使用独立9443且只在tailnet提供访问。原配置保存NAS `/home/Justin/rkd-ai/tailscale-before.json`，尚未启用新监听。
- 首次构建失败：NAS既有docker.fnnas.com源401、Docker Hub直连超时。未改全局daemon/代理，候选改用可访问的docker.m.daocloud.io，Python和PG的上游manifest SHA保持不变；Python依赖使用清华PyPI镜像、版本保持锁定。两文件下载源配置变更已核对原摘要并记入NAS候选manifest的download_source_patch，当前仓库同步。
- 当前实际镜像拉取会话30252/1645，重试部署会话42541；NAS日志python-pull.log、postgres-pull.log、deploy-retry.log。HTTPS Origin已设为https://fnos-nas.tailcca6f8.ts.net:9443，仍需容器实际启动、TLS和全部字节/恢复实测。Docker权限已解决，不再向用户重复索取。首位个人账号仍待用户可信终端交互设置，不代设密码。
