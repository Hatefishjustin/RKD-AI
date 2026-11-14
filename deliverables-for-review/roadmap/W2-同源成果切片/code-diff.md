# W2 同源成果切片 · 代码差异说明

比较基线：`bfd0753`（W2 入口边界）。复核命令 `git diff bfd0753 -- mvp contracts web scripts`。
新增：2 个模块、1 个 Blender 执行器、3 个验收脚本、1 个页面组件；零迁移/零新表。

## 1. `mvp/rkd_mvp/ai_spatial_outputs.py`（新增，约 560 行）

| 部分 | 内容 |
| --- | --- |
| `freeze_input` | 冻结输入清单：项目/候选/修订、模型 hash、源产物与 SHA/父链/来源、对象与材料/视图版本、生成器版本、几何权威 |
| `derive_camera` | 由入口区段与最大功能区推导机位（1.5m/24mm），返回 `assumption=True` 与说明 |
| `measure` | 精确多边形并集、保留区扣除、净面积；独立鞋带公式复核；bbox 结果并列（仅对照）；未知量 `value=None` |
| `build_cost` | 无价源时 `known_items=[]`、总额 null、`formal_quote=false`；显式假设单价才生成一条标注金额 |
| `build_plan_svg` | 分区多边形/名称/面积、家具旋转占地、动线、保留区、总尺寸与分区尺寸、图例、面积表、机位与视线、未建模缺项、"不是施工图" |
| `build_scene` | 米制场景（分区多边形、家具目录尺寸、展台高度、灯位、相机），附 `render_assumptions` |
| `finalize_files` | 生成清单并打包 zip；每个文件登记 sha256/size（render.png 也在清单里） |

## 2. `mvp/rkd_mvp/ai_spatial_output_service.py`（新增，约 330 行）

- `submit`：校验幂等键、修订存在、必须有 `spatial`、`validation=passed`；记录 `config.kind=spatial_outputs`；
  与旧 04/05 任务共用表但用 `kind` 区分；`start_workers=False` 时同步执行（验收用）。
- `_run`：geometry→measurement→pricing→outputs；**渲染在数据库事务之外**；文件先写盘，随后
  单事务登记 revision + artifacts；失败写 `failed` 并保留错误，不登记半份成果；最后清理自己的临时状态。
- `status` / `file`：读取任务、修订、登记文件；`render.png`/`scene.json` 从 `manifest.json` 的
  文件清单解析并按 sha256 校验后返回。
- `run_blender`：调用本机 Blender（Cycles CPU），超时/非零退出明确失败，不退回假图。

## 3. 契约

- `ai-design-option.schema.json`：`spatialZone` 增可选 `finish_material`（材料决策；Studio 提案没有材料规格）。
  其余必填、`additionalProperties`、旧 rect 定义未动。

## 4. API

- `POST /api/v1/projects/{pid}/ai/spatial-outputs`（202，Idempotency-Key）
- `GET  /api/v1/projects/{pid}/ai/spatial-outputs`（任务/修订/文件/边界）
- `GET  /api/v1/projects/{pid}/ai/spatial-outputs/{revisionId}/files/{filename}`（按登记 SHA 校验后返回，带 `X-Content-SHA256`）

## 5. 前端

- 新增 `AiSpatialOutputsPanel.tsx`：选择精确模型修订 → 生成（可关渲染）→ 轮询 → 平面/人眼图（blob URL）→
  净量表 → 缺项 → 六个下载入口；显示模型 hash、源产物、几何权威、父链状态。
- `DesignWorkspace.tsx` 增"同源成果"页签；`styles.css` 增两列图面布局与 820px 单列规则。

## 6. 验收脚本

- `scripts/render_spatial_scene.py`：从场景 JSON 建 Blender 场景（地板/分区/墙/保留区/家具/展台/灯位/相机/灯光），
  Cycles CPU 渲染并写 `.meta.json`；所有坐标来自模型，渲染假设集中在场景 JSON。
- `scripts/verify_w2_spatial_outputs.py`：7 项真实 HTTP + 四种受控变更（生成器级）。
- `scripts/verify_w2_browser.py/.cjs`：真实页面整链、下载 SHA、390px。

## 7. 明确没有改的地方

- 无迁移/新表；`postgres_import.py` 白名单未动；未改旧 04/05 服务语义（只加了 spatial 拒绝）。
- 未改 `spatial` 精确几何、losses 声明、W1 谱系逻辑。
- 未改用户原件、历史复核包、AD 文档、`docs/26`；未启动 W3/W4；未新增外部调用。
