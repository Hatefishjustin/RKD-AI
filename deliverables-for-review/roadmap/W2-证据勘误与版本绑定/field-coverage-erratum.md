# 字段清单勘误：rect 四角投影 / 非矩形设计、真实模型来源核实

编制：2026-11-16 · 依 `W2-gate-architect/review-and-handoff.md`「字段清单的架构校正」。**只做文档勘误，不改业务代码、不改契约、不改字段清单原文字节。**

被勘误对象：`deliverables-for-review/roadmap/W2-expression-architect/field-coverage-and-unknowns.md`（等待期只读清单，保持原样）。该清单本身仍是有用的缺口清单，下列两处表述须按本文件口径理解；本文件不构成设计能力升级或验收结论。

## 一、rect 四角投影 ≠ 获得真实非矩形设计

### 清单原文的两处表述

- 第 19 行架构复核已提示：`rect→polygon` 不要把同一个矩形无损改写成四角多边形当成已获得真实多边形设计。
- 第 89 行替换表「分区几何」：`真实模型输出的精确多边形（或经声明的 rect→polygon 投影并记入 losses）`。

### 勘误口径

1. 真实模型输出 `REAL_DESIGN_OUTPUT_SHAPE` 中 `zones / walls / furniture / focal_point / paths / entrance_buffers` 的几何字段全部是米制 `rect`（`x/y/width/length`），源码 `mvp/rkd_mvp/ai_design_option_provider.py` 的 `_to_model()` 也只是把这些矩形写入 `objects[].shape`；**当前真实模型不产出任何精确多边形、曲线或非直角几何**。
2. 把这种 `rect` 无损改写成"四角多边形"（4 个顶点）只改变存储表示，**不含任何新的形状信息**：它仍是矩形。投影必须记入 `adaptation.losses` / `field_ledger` 并标注 `bbox_derived` 或"矩形四角化，非真实轮廓"，不得表述为"获得真实多边形设计"或"非矩形设计能力成立"。
3. **真正非矩形设计**指模型给出矩以外的顶点（凹/凸多边形、斜边、弧形意图且有对应几何）并能被同源表达消费。本批 W1/W2 中"非矩形"样例（`zones[].polygon_mm` 5 点、`platforms[].corner_radius_mm`）均来自 **Studio 人工夹具提案**，不是真实模型设计输出。字段清单第 25 行注释"分区仍为矩形"针对真实模型输出是准确的，不得据 Studio 夹具 polygons 反推模型具备该能力。
4. `curved_intent` 在无对应弧/斜几何时**仍属意向**：它是 `wall_type` 的一个枚举值（`solid|screen|curved_intent|feature`），输出形状里没有任何曲率/控制点字段。表达器不得据该枚举自行编造弧墙并标为已建模；缺几何时该墙段保持"意向未落地/几何 unknown"，不进工程量。
5. 门窗、墙高、窗台、产品规格缺来源时，按清单第 92—94 行继续保留 `unknown` 或明确标注测试假设；**不能从"底图尺寸相同"推断现场已核**，也不因完成四角投影就置 `site_verified=true`。

## 二、design_origin.kind=real_model 须按运行证据核实

### 勘误口径

1. `design_origin` 是**上游设计来源的声明字段**，不是证明。适配器（`ai_design_studio_adapter.py`、`RealModelDesignOptionProvider._to_model()`）的职责是**保留并校验**该来源，不能凭字段取值声明 `kind=real_model` 就宣称"真实 AI 设计已成立"。
2. 要认定某候选 `design_origin.kind=real_model`，必须能指向**具体调用与产物记录**，至少含：模型请求、输入哈希、输出哈希、提示版本（prompt version）、候选及父链。本仓库已有的真实调用证据在：
   - `var/evidence/real-design/2026-11-09/run-*/verification.json`
   - `var/evidence/real-design/2026-11-10/run-20261109T231902-f19989/verification.json`（实测：`model=gpt-5.6-sol`、`prompt_version=design-studio-concept.zh-CN.v2+rkd-design-reference.v1`、`model_runs.entries[].provider_request_id` 与 token 用量、`passed=true`；`external_context_allowed=false`）。
   这些记录证明"确有一次真实模型设计调用"，但**不与 W2-R4 产物直接相连**——W2-R4 的 `outputs/layout-A|model.json` 实测 `generation.provider_kind=studio_proposal_adapter`、`real_model=false`、`design_origin.kind=fixture`。
3. 当前链路事实（清单第 11—17 行）保持：真实模型输出（米制 `rect`）与现有 `spatial`（mm 精确多边形）**尚未贯通**；W2 表达层吃的是人工夹具提案。凡引用 `design_origin.kind=real_model` 的结论，先核对是否附有上述运行证据，以及该证据是否确实连到当前产物；无证据或跨链引用一律按 `unknown` / `fixture` 处理。
4. 词表映射必须显式、版本化，不得按名字猜资产：
   - 真实模型 `zone_role`（`foyer|primary_display|deep_talk|buffer|service`）→ `spatial.zones[].role`（实测 `arrival|gallery|island|meeting|scene|service`）需显式映射表；真实模型 `furniture_type` → `spatial.catalog_id`（实测 `sofa-3p|dining-table|display-wing`）同样需显式目录映射。
   - 无映射项保留 `unknown` 或拒绝，不能按字符串巧合把 `foyer` 当 `arrival`、把 `island` 当 `display_case`。
5. 费用与资料授权不因本勘误改变：本批 0 外部调用、0 费用。真实模型再调用与项目资料外发仍受既有授权约束，由架构师在用户绑定底图版本后单独界定范围；本勘误不构成新授权，也不得被写成"连字段映射文档都不能准备"的前置条件。

## 三、边界

- 本文件只修正文档表述，不改变 V1—V3 工程收口结论、不改变 AD01—AD08、不推进用户项目阶段 2、不启动 W3/W4。
- 仍不像设计公司成果的地方（见清单末尾与 `design-gaps.md`）保持：每布局 1 机位、偏暗偏灰、无真实多边形/非矩形模型设计、围合/开口/材料/家具为标注的人工假设、人工样板不计系统自动设计。
