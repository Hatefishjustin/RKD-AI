# W2 同源成果切片 · 架构师复核包

编制时间：2026-11-14 22:45（北京时间）；证据执行时间见 `manifest.json`。
上游依据：`deliverables-for-review/roadmap/W1-lineage-architect/review-and-W2.md`
（W1 本机 SQLite 受限范围放行 + W2 范围、顺序、退出标准）；`docs/26` 第 3/4/6 节。
比较基线：`bfd0753`（W2 入口边界提交）；本批业务提交见 `commit-reference.md`。
性质：**同源表达能力切片**，不是新增 AI 设计验收。不改 AD、不启动 W3/W4、不正式发布/切库。

## 1. 需求映射（按架构师执行顺序）

| 顺序 | 本批处理 | 落点 |
| --- | --- | --- |
| 1 冻结输入清单 | 每个成果登记项目、候选、修订 ID、模型 hash、源产物/SHA/父链、对象/材料/视图版本、生成器版本、几何权威 | `ai_spatial_outputs.freeze_input`；`outputs/layout-*/manifest.json` 的 `baseline` |
| 2 精确模型出平面 | 精确多边形、名称/面积、家具目录尺寸、动线、保留区、总尺寸与分区尺寸、图例、面积表、机位、未建模缺项、"非施工图"声明 | `build_plan_svg`；`outputs/layout-*/plan.svg` |
| 3 同一模型出 Blender 人眼图 | 场景 JSON 只含模型坐标/尺寸 + 明确标注的渲染假设；Cycles CPU 出图，机位 1.5m/24mm | `build_scene`、`scripts/render_spatial_scene.py`；`outputs/layout-*/render.png` |
| 4 同源净量与成本 | 只用精确多边形：地坪毛面积、保留区扣除、净面积；bbox 结果并列但**不用于计量**；金额无价源一律 unknown | `measure`、`build_cost`；`quantity.csv/json`、`cost.html` |
| 5 页面与下载 | "同源成果"页签：选修订→生成→看平面/人眼图/净量/缺项→下载六个文件；任务轮询；失败保留诊断 | `AiSpatialOutputsPanel.tsx`、`/ai/spatial-outputs` 接口 |

## 2. 实际做了什么

- **服务**：`AISpatialOutputService` 复用既有 `ai_development_jobs/revisions/artifacts` 三张表（**零迁移、零新表**），
  任务分阶段（geometry→measurement→pricing→outputs），渲染在数据库写事务之外，失败置 `failed` 并保留诊断，
  不登记半份成果；同一幂等键对应不同输入给 409。
- **图面**：平面从 `spatial.zones[].polygon_mm` 直接绘制（非矩形入口区原样），
  含总宽/总长尺寸线、分区尺寸文字、面积表、图例、动线净宽、保留区斜线、灯具点位、
  相机符号与视线、`未建模/缺项` 清单和"概念平面，不是施工图"声明。
- **人眼图**：`build_scene` 把同一模型转成米制场景（分区多边形、家具目录尺寸、展台高度、灯位），
  相机由入口与最大分区**按固定规则推导**并在场景/平面/清单里标为假设；
  `render_spatial_scene.py` 用本机 Blender 4.2.9 Cycles CPU 渲染，无外部资产、无外部图像通道。
- **净量**：地坪毛面积/保留区扣除/净面积均用 shapely 精确多边形；同时算一个**独立鞋带公式**复核，
  再算一个 bbox 结果并列展示（A 布局 bbox 比精确值大 1.28 ㎡），明确"bbox 只作对照"。
- **成本**：没有价源时 `known_items=[]`、总额 `null`、`formal_quote=false`；
  只有显式传入假设单价（`settings.floor_unit_price_cny`）才出现一条金额，并标
  `caller_provided_assumption_not_a_quote`，总额仍是 unknown。
- **W2 入口边界（前置小修，已单独提交 `bfd0753`）**：旧矩形反馈/补丁链与旧深化/量价链对 spatial 模型一律 422；
  缺父差量标 `unknown_missing_parent` 且 `diff=[]`；`allow_orphan` 严格布尔。`verify_w1_lineage.py` 16/16。

## 3. 验证（真实执行）

| 命令 | 结果 | 证据 |
| --- | --- | --- |
| `scripts/verify_w2_spatial_outputs.py` | **7/7 `observed_pass`**（真实 HTTP、隔离双库、两份布局各渲染一次） | `checks.json` |
| `scripts/verify_w2_browser.py` | `passed=true`、`page_errors=[]`、390px 无溢出 | `browser/verification.json`、2 张截图 |
| 受影响 5 模块单测 | **55 OK** | `runtime/focused-unittest.log` |
| 全量单测 | **262 OK**（458.0 s） | `runtime/full-unittest.log` |
| `npx tsc --noEmit` / `npm run build` | EXIT=0 / EXIT=0 | `runtime/frontend-build.log` |

关键实测：

| 项 | 布局 A | 布局 B |
| --- | --- | --- |
| 模型哈希（前 12） | `8ef5fb44d7eb` | `ec04053bd220` |
| 精确地坪净量 | **233.03 ㎡**（独立复算 233.03） | **229.08 ㎡** |
| bbox 对照值 | 234.31 ㎡（**+1.28**，不用于计量） | — |
| 人眼图 | 960×600、24 采样、46.0 s、1.03 MB | 43.6 s |
| 平面 | 10,022 B，含面积表/图例/尺寸/机位 | 同结构 |
| 保存并登记的文件 | plan.svg / quantity.csv / quantity.json / cost.html / manifest.json / package.zip + render.png | 同 |

**四种受控变更**（同一冻结模型副本，避免 hash-only 证明）：

| 变更 | 具体数值/对象变化 |
| --- | --- |
| 改几何（ZA2 西边收进 800mm） | 净量 233.03 → **229.19 ㎡**；平面与场景 JSON 均改变 |
| 改材料（分区 `finish_material`） | 平面配色与场景材质改变；净量**不变** |
| 只改相机（+3000mm） | 平面机位与场景相机改变；净量**不变** |
| 只改单价（假设 1000→1200 元/㎡） | 成本已知项 233,030 → 279,636 元；平面/场景/净量**不变**；总额仍 unknown、`formal_quote=false` |

## 4. 与 W2 退出标准对照

| 退出标准 | 状态 |
| --- | --- |
| 两种不同布局同一生成器出平面与人眼图；源对象 ID/模型哈希/材料/相机可查；相机在平面可定位 | **是**（W2-06；`baseline`、`view_mapping.camera`，平面 C1 标记） |
| 四种受控变更说明具体数值/对象变化 | **是**（W2-07，见上表） |
| 非矩形、含扣除区案例独立复算净量；bbox 结果故意不同且不误用 | **部分**：非矩形与独立复算、bbox 差异已完成；两份标准夹具的保留区**未与分区重叠**，扣除额为 0，含扣除区的独立复算只在几何变更用例里体现（ZA2 收缩），**没有单独构造"保留区落在分区内"的源案例** |
| 同源跨图/数量一致性（Q10）、旧包字节不变、下载逐文件 SHA 一致、生成中变更/取消无半份成果 | **部分**：本次生成内平面/场景/净量/相机同源，下载 SHA 与登记一致；**Q10 的"跨版本/旧包字节不变/生成中变更或取消"未测**（本批未做取消语义） |
| 真实浏览器整链并展示缺项；人工查看平面与渲染 | **是**（浏览器 passed；图已附，但质量见 §6） |

## 5. 没有做，以及为什么

- **没有做 Q10 完整闭环**：架构师要求"旧包字节不变、生成中变更/取消、失败重试不出现半份当前成果"。
  本批只做到了同一次生成内的同源与失败不登记；**取消/中途换版本未实现**，`Q10` 仍不能标通过。
- **没有单独构造"保留区落在分区内"的源案例**：标准夹具的楼梯/卫生间在分区之外，扣除额为 0；
  只有几何变更用例改变了面积。这是本批的验收缺口，需补一个专门的含洞/扣除区源。
- **没有做多视角、天花图、立面、材料板、PDF 汇总**：W2 只要求一张平面 + 一张人眼图；W4 才做全套。
- **没有做真实 AI 设计**：两份布局是明确标记的本地夹具；`design_origin=fixture`，不计入 AD。
- **没有新增基础设施**：零迁移/新表；没有队列、账号、NAS、切库；渲染在现有本机执行。
- **没有做外部调用或外发**：0 外部模型、0 外部图像、0 密钥、0 费用。

## 6. 仍然不像设计公司成果的地方（逐条）

1. **人眼图是内部试验级**：色块化地面、统一灰家具盒子、没有真实材料纹理/产品/软装/绿植/人物；
   窗光与灯槽层次只做到"能看出空间关系"，达不到客户交付级。已在图注、清单和本包标注。
2. **平面是概念图**：没有墙厚、门窗、柱网、洁具、隔断构件、尺寸链只到总尺寸+分区外框尺寸；
   未建模项只列缺项，不画框线冒充。
3. **家具是目录尺寸的方盒**：没有款式、材质、朝向细节；高度统一 0.75m 是占位假设。
4. **材料只有意向/假设**：没有产品选型、样板、规格；价格没有价源，金额全 unknown。
5. **净量只覆盖地坪**：隔断、天花、门窗、机电全部 unknown；平台包络不算实体量。
6. **相机是推导视点**：不是设计决定的机位，也没有多视角。
7. **没有跨版本 Q10**：同一生成内一致，但旧包失效、变更重生成、取消语义未测。
8. 设计是否成立只能由用户判断；本批不代签。

## 7. 外部调用与费用

| 项 | 数值 |
| --- | --- |
| 外部模型调用 | **0** |
| 外部图像通道 | **0** |
| 外发图片 / 生成图片（外部） | **0 / 0** |
| 真实 tokens | **0** |
| 金额 | **0** |
| 本机渲染 | Blender 4.2.9 Cycles CPU，本地执行，无费用 |
| 密钥 | 未使用、未落盘 |

## 8. 风险与限制

- 渲染依赖本机 Blender 路径；缺失时任务失败并给 503，不会退回假图。
- 场景 JSON 的家具高度/材质/灯光是**渲染假设**，不能作为实测或选型依据。
- 成果写入既有 `ai_development_*` 表，`config.kind=spatial_outputs` 区分旧 04/05 任务；
  旧接口可能把最新任务一并列出，属已知交叉展示，未改旧语义。
- 只在隔离 SQLite 验证；PG/切库/多进程未测。
- Q10 与"含扣除区独立案例"仍是缺口，需下一批补齐后再谈 W2 完成。

## 9. 完整文件路径（`D:\Github\RKD AI\` 下）

复核包：`deliverables-for-review\roadmap\W2-同源成果切片\`
- `index.html`（可直接打开的评审入口）、`review-packet.md`、`positive-negative-cases.md`、
  `code-diff.md`、`changes.patch`、`manifest.json`、`commit-reference.md`
- `checks.json`、`browser\verification.json`、`browser\browser-observations.json`、
  `browser\w2-outputs-desktop.png`、`browser\w2-outputs-mobile.png`
- `outputs\layout-A\{plan.svg,render.png,quantity.csv,quantity.json,cost.html,manifest.json,scene.json,package.zip}`
- `outputs\layout-B\`（同上）
- `runtime\focused-unittest.log`、`runtime\full-unittest.log`、`runtime\frontend-build.log`

运行证据：`var\evidence\roadmap\W2-同源成果切片\`

源码改动：
- `mvp\rkd_mvp\ai_spatial_outputs.py`（新增：平面/场景/净量/成本/清单/打包）
- `mvp\rkd_mvp\ai_spatial_output_service.py`（新增：任务、渲染外置、登记与下载）
- `mvp\rkd_mvp\api_service.py`、`api_server.py`（3 个接口）
- `web\src\AiSpatialOutputsPanel.tsx`（新增）、`DesignWorkspace.tsx`、`styles.css`
- `scripts\render_spatial_scene.py`（新增 Blender 场景执行器）
- `scripts\verify_w2_spatial_outputs.py`、`verify_w2_browser.py/.cjs`（新增验收）
- `contracts\v1\ai-design-option.schema.json`（本批只加分区可选 `finish_material`；`diff_baseline` 等入口字段已在 `bfd0753` 提交）

唯一状态表：`PROJECT_STATUS.md`（已更新；AD 与用户设计确认未改）。
