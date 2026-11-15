# W2-R4 同源表达 · 复核包

编制时间：2026-11-15T21:10:11+08:00；审查基线：`ffad892`（架构师审查 HEAD），业务实现 `7425464`。
运行证据：`var/evidence/roadmap/W2-R4-同源表达/`（旧证据一律保留，未覆盖前一批）。

## 1. 需求映射

| 委托项 | 落地 | 证据 |
| --- | --- | --- |
| 更新唯一状态表的受限结论 | PROJECT_STATUS.md 顶部追加架构复核受限结论；AD 与用户阶段确认不变 | 本仓库 `PROJECT_STATUS.md` |
| 先修同层异材重叠变 known 重复工程量 | 冲突/待核 + 结构化互斥裁切；补真实 HTTP 负例 | `entry-fix/`、`positive-negative-cases.md` |
| 保留 15 项回归 | 15/15 observed_pass，未放宽断言 | `entry-fix/regression-15.json` |
| 检查点 1 资产复用 | 6 套 CC0 PBR + 10 件 glTF + Blender 4.2.9；来源/许可/尺寸列清 | `asset-inventory.md` |
| 检查点 2 同源围合开口 | 4 段周界墙 + 2 段隔断 + 7 处洞口，平面/三维同对象 ID 与 mm 尺寸 | `outputs/layout-*/` |
| 检查点 3 真实家具材质 | 目录真实尺寸 + CC0 贴图；1 件明确占位；材料面/分配/计量对应 | `geometry-material-reconciliation.md` |
| 检查点 4 机位灯光 | 1500mm 人眼机位标注在平面；窗光来自已建模窗口；灯槽/筒灯/软阴影 | `outputs/layout-*/scene.json`、`render-meta.json` |
| 检查点 5 同源验证与人工目检 | 两布局同生成器；4 项受控变更；ZIP/SHA、取消晚到、任务定位回归；人工查看两布局效果图与平面 | `checks.json`、`browser/` |
| 前后对比 | 旧 W2 灰盒图 vs R4 真实材质图；入口小修 before/after | `before-after/`、`entry-fix/` |

## 2. 做了什么 / 没做什么

**做了**：入口小修（v3 finish-scope 契约、conflict 状态、结构化裁切、HTTP 负例）；
新增表达层契约校验 `spatial_presentation.py`、人工假设样板 `w2_r4_fixture_presentation.py`、
真实资产渲染器 `render_spatial_scene_r4.py`；平面/场景/清单/成本/服务设置同源扩展；
修两类真实缺陷（Blender 盒体拓扑、390px 窄屏溢出）；两布局各生成可读平面 + 1 张人眼图 + 完整 ZIP；
浏览器验收、全量 262 单测、前端构建与类型检查。

**没做（及原因）**：W3/W4 未授权启动，不做全套天花/立面/三效果图/汇总客户 PDF；
不新增付费外部调用或图像通道（0 次、0 费用）；不扩 PG/NAS/账号/租约平台；
不做柱网/洁具/构造节点/照度计算/现场实测（无依据，不编现场事实）；
不把人工样板参数说成系统自动设计、不代用户判定设计成立、不改 AD01—AD08 与阶段确认。

## 3. 结果与设计差距

- R4 专项 **15/15 observed_pass**；浏览器 passed=True；全量单测 262/262；入口小修前后 8/8 各符合预期；15 项回归 15/15。
- 真实生成图片：**2 张**人眼效果图（本机 Blender Cycles CPU，两布局各一张）；平面 PNG 预览 2 张、浏览器截图 2 张、旧灰盒对比 1 张（均为本地派生，不是外部生成图）。
- 外部模型调用 0 次、外发图片 0 张、tokens 0、费用 0；密钥未使用、未落盘。
- 图面差距逐条见 `design-gaps.md`；工程修复通过 ≠ R4 设计通过 ≠ W2 整体完成。

## 4. 风险与下一步（交架构师）

- 表达层仍是人工测试假设，下一步若要计入自动设计，必须由系统模型从需求生成墙/门窗/材质/家具，并保留对象 ID 与来源；本批不计入 AD。
- 单实例 SQLite 边界不变：不推广到任意材料组合、PG、双活或断电正确性。
- W2 整体仍未放行；W3 真实调用须另获准额度与资料范围；阶段 1→2 / 2→3 只接受用户对具体版本的明确确认。
- 本批**不请求用户决定**：无待决闸口，未新增 `decision-request.md`。

## 5. 文件索引

| 路径 | 内容 |
| --- | --- |
| `index.html` | 评审入口（可打印），含前后对比与两布局图 |
| `checks.json` | 逐项 observed_pass/fail/not_run + 环境/命令/时间 |
| `code-diff.md` / `changes.patch` | 相对 `ffad892` 的提交差异 |
| `manifest.json` | 源码基线、版本、产物字节与 SHA、原件/派生分类 |
| `positive-negative-cases.md` | 入口小修正负例、回归、浏览器 |
| `asset-inventory.md` / `asset-assumptions.json` | 资产来源/许可/尺寸与人工假设 |
| `geometry-material-reconciliation.md` | 几何材质量价对账 |
| `design-gaps.md` | 仍不像客户成果的逐条说明 |
| `outputs/layout-A|B/` | 源模型、平面、场景、PNG、完整 ZIP、清单、源说明 |
| `entry-fix/`、`browser/`、`before-after/`、`runtime/` | 负例、浏览器、前后对比、运行证据 |
