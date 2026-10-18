# 纵向 MVP 参考代码骨架

> 本地工作台已接项目、原件、任务、预算和 M2 参数几何成果链；M3 提供矩形展厅需求编辑、规则布局、几何编辑/检查及 SVG/DXF/CSV/JSON/HTML/ZIP 成果。动态验收结果见 [项目状态](../PROJECT_STATUS.md)。规则草稿不代表 AI、BIM 或正式施工图。

这是第 6 项方案的可执行参考骨架，用 Python 标准库验证核心架构护栏：

- 组织/项目上下文和跨租户拒绝；
- 命令幂等、业务事件、审计事件和 Outbox；
- 执行器 Inbox 去重；
- SQLite 重启后恢复项目、命令、事件、任务、产物和外部动作；
- 可恢复的 MVP 工作流状态机，支持状态迁移、重启恢复、非法迁移拒绝和跨租户拒绝；
- Outbox 消费失败后按次数重试，超过上限进入死信队列；Inbox 重复消息只处理一次；
- OpenAPI API 边界，包含项目、文件、命令、工作流、成果和健康检查入口；
- Python 标准库本地 HTTP API 服务，可验证命令幂等和租户隔离；
- 本地 HTTP 服务默认使用 SQLite 文件，重启后项目和命令仍然保留；
- 身份验证通过 `IdentityProvider` 接口隔离；M5-01 提供本机个人账号、服务端会话及项目角色，正式 OIDC/团队部署仍待后续验收；
- G2 后的生产批次、图纸与 BOQ 两条分支；
- EX-14 简化交叉校验；
- 外部发布 `unknown` 状态和人工解决入口。

当前实现同时提供内存存储、SQLite 本地持久化和 PostgreSQL 接入边界，并使用确定性模拟适配器隔离外部副作用。它故意不绑定具体 Web 框架、工作流产品或 BIM 软件，也不是生产实现，不能替代 `docs/05` 的真实 PostgreSQL RLS、备份、压测和恢复演练。

新增的 CAD 接入预检器会校验 DWG 扩展名、文件签名、版本和 SHA-256，并输出 `contracts/v1/cad-source-inspection.schema.json` 对应的状态。可通过可替换的 `CadGeometryParser` 接口接入专业解析器；当前提供 GNU LibreDWG 本地适配器，可提取单位、图层、图元、文字、尺寸和解析诊断的紧凑摘要。解析器输出必须通过 JSON 完整性检查；出现兼容警告时结果保留为 `geometry-parsed`，同时标记 `requires_secondary_validation=true`，不得直接升级为可施工数据。

## 运行

在仓库根目录的 PowerShell 执行以下单入口命令。`prepare` 固定安装 Python/Node 依赖并构建前端；`start` 自动构建后启动同源工作台，运行数据仅写入 `var/`。浏览器打开 `http://127.0.0.1:8080`。

首次启动只读核对 `fixtures/ningbo-xiecheng/2026-09/样本清单.json`，将 7 份宁波原件复制到 `var/projects/`，保存来源、SHA-256 和试用决策。再次启动不覆盖项目名称或已有文件。上传完成仅表示原件保存并进行签名格式检查，不表示已扫描病毒、完成 CAD 解析或专业批准。

```powershell
pwsh -NoProfile -File .\scripts\rkd.ps1 prepare
pwsh -NoProfile -File .\scripts\rkd.ps1 test
pwsh -NoProfile -File .\scripts\rkd.ps1 start
```

使用 PowerShell 7 (`pwsh`)；Windows PowerShell 5 对无 BOM 的中文脚本编码可能无法正确解析。本机已有配套 `pwsh`，无需安装新的系统软件。

### M5-01 本机账号与项目权限

在项目根目录运行：

```powershell
pwsh -NoProfile -File .\scripts\rkd.ps1 start-secure
```

首次在终端设置个人管理员账号、显示姓名和 15–128 字符密码，密码输入不回显，也不写入命令行或日志。已有账号时直接启动；浏览器地址仍为 `http://127.0.0.1:8080`。如果已有服务占用端口，先在其启动终端按 Ctrl+C 停止再启动。启用账号后，普通 `start` 也会自动使用账号模式；设置 `RKD_AUTH_MODE=local` 试图降级将失败。

登录后侧栏“账号与成员管理”可创建普通账号、分配当前项目的负责人/编辑/只读角色、撤销访问、停用或恢复账号。管理员可管理本组织全部项目；普通用户只能看到已分配项目。下载原件和各类成果均检查当前会话与项目授权。负责人只具备本地验收记录权限，没有正式报价/合同/施工图发布权限。

首次启用请自行设置真实密码。自动验收使用隔离数据库中的随机测试密码，不会在用户运行库预建默认管理员。现有本地使用方式继续保留，未初始化账号的数据库仍使用固定本地身份；它不接受客户端伪造组织或操作者。

本批仍为回环地址、SQLite 和参考 HTTP server，**未获准局域网/公网团队生产使用**。PostgreSQL、完整备份恢复、HTTPS/生产服务器、监控、专业审签、SSO/MFA 及账号恢复流程仍按 M5 后续任务处理。管理员不授予正式发布权限，真实下单和付款关闭。

复核命令：`node scripts/verify_m5_entry.cjs`。测试自动启动/停止自己的隔离服务，运行库、下载及截图写入 `var/evidence/m5-entry/run-*/`，不连接 `var/app.sqlite3`；测试密码仅在子进程环境中传递，不进入证据文件。仅复核账号切片可加 `--accounts-only`。

### M3 本地展厅设计

打开项目的“需求草稿”页，填写外框、预留通道、功能分区最小面积和设计备注，保存后生成布局。默认 12×8m 为明确标记的测试参数；宁波 CAD 原件不会自动升级为已核验场地边界。已记录业务决定和来源原件保留在需求快照中。

“分区布局”可选择对象并编辑坐标/宽长；“检查并保存布局”执行边界、重叠、通道、最小面积、通道连接和对象 ID 检查。保存新版本同时更新图面、面积清单和报告，失败不保存。“成果与历史”可下载七份真实成果，旧版也可读取。需求修订后旧设计显示待重新生成；消防、现场、结构/机电仍为未知/待专业复核，所有成果未批准。

接口契约在 `contracts/v1/openapi.v1.json` 和 `showroom-design.schema.json`。浏览器复验可运行 `node scripts/verify_m3_browser.cjs`，使用本机配套 Playwright/Edge；新建明确的测试项目，证据保存在 `var/evidence/m3/`。`--restart` 在服务进程重启后核对上次模型、修订和成果哈希。运行数据和下载文件不进入 Git。

其他研究工具仍可在仓库根目录单独运行：

```text
python -m unittest discover -s mvp/tests -v
python mvp/run_demo.py
python mvp/run_api_server.py
python mvp/run_cad_preflight.py --input "path/to/plan.dwg" --source-asset-id drawing-cad-01
python mvp/run_cad_preflight.py --input "path/to/plan.dwg" --source-asset-id drawing-cad-01 --libredwg-home "path/to/libredwg"
python mvp/run_cad_semantic_mapping.py --inspection "path/to/cad-source-inspection.json" --rules "mvp/config/cad-layer-semantic-rules.v1.json" --output "path/to/cad-layer-semantic-mapping.json"
python mvp/run_cad_plan_candidates.py --input "path/to/plan.dwg" --inspection "path/to/cad-source-inspection.json" --semantic-mapping "path/to/cad-layer-semantic-mapping.json" --profile "path/to/plan-localization-profile.json" --libredwg-home "path/to/libredwg" --output "path/to/cad-plan-candidates.json"
python mvp/run_cad_review_layers.py --input "path/to/plan.dwg" --inspection "path/to/cad-source-inspection.json" --semantic-mapping "path/to/cad-layer-semantic-mapping.json" --plan-candidates "path/to/cad-plan-candidates.json" --libredwg-home "path/to/libredwg" --output "path/to/cad-review-layer-analysis.json"
python mvp/run_cad_object_groups.py --plan-candidates "path/to/cad-plan-candidates.json" --endpoint-tolerance-mm 2 --output "path/to/cad-object-groups.json"
python mvp/run_cad_topology_review.py --plan-candidates "path/to/cad-plan-candidates.json" --object-groups "path/to/cad-object-groups.json" --output "path/to/cad-topology-review.json"
python mvp/run_cad_region_candidates.py --plan-candidates "path/to/cad-plan-candidates.json" --snap-tolerance-mm 2 --minimum-area-m2 0.01 --output "path/to/cad-region-candidates.json"
python mvp/run_cad_secondary_validation.py --dxf "path/to/plan.dxf" --source-asset-id drawing-cad-01-dxf --dwg-inspection "path/to/cad-source-inspection.json" --output "path/to/cad-secondary-validation.json"
python mvp/run_gold_standard_intake.py --source-directory "path/to/read-only-project" --config "path/to/intake-config.json" --output "path/to/gold-standard-manifest.json"
python mvp/run_cad_secondary_geometry_review.py --dxf "path/to/plan.dxf" --plan-candidates "path/to/cad-plan-candidates.json" --dwg-plan-candidates "path/to/cad-plan-candidates.json" --semantic-rules "mvp/config/cad-layer-semantic-rules.v1.json" --output "path/to/cad-secondary-geometry-review.json"
python mvp/run_cad_cross_engine_review.py --dxf-review "path/to/cad-secondary-geometry-review.json" --dwg-plan-candidates "path/to/cad-plan-candidates.json" --output "path/to/cad-cross-engine-review.json"
```

CAD 工具目录属于部署配置，不写死在业务代码中。DWG 和解析过程保持本地运行；约几十兆的中间 JSON 只存在于临时目录，项目内仅保存结构化摘要和诊断计数。

CAD 图层语义映射使用外置、带版本号的规则文件，不把客户图层命名写死在核心业务代码中。解析器从模型空间和图纸空间沿块插入关系计算可达内容，并把未使用块定义、无可靠所有者图元和可达图元分开。输出分别记录“已分类”“无需系统分类复核”“系统复核”和“项目范围处置”；CAD 存储图元数不得直接当作工程量，后续对象化只消费符合规则的模型可达内容。

主平面候选提取使用项目级定位配置和至少两个独立尺寸锚点，不依赖整张 DWG 的全局坐标范围。插入块按基点、缩放、旋转、镜像和平移递归展开；任何循环、缺失定义、非平面拉伸或超深嵌套都会降级为部分展开并写入结构化原因。候选只是待合并的几何证据，不得直接当作构件数量或报价工程量。

闭合区候选使用 `requirements-geometry.txt` 锁定的 Shapely/GEOS 线网算法。填充和尺寸不参与多边形化，悬线、切割线和无效环单独计数；生成的墙占地、天花或地坪候选仍需第二 CAD 引擎和专业语义验证，`quantity_status` 保持 `not-ready`。

第二通道接入器读取 ASCII DXF 的版本、单位、HEADER 范围、图层、块定义以及 ENTITIES 模型/图纸空间摘要，并可与 DWG 预检摘要生成差异报告。它不展开块、不推断专业对象、不计算工程量，输出的 `promotion_status` 固定为 `not-approved`。完整接入和停止条件见 `docs/11-DXF第二通道接入与核对规范.md`。

历史项目金标准导入器只读扫描原件，生成文件指纹、重复组、候选资料角色、版本关系、隐私状态和三类独立用途授权。接入本身不授予训练权，也不把候选角色变成专业正确答案。规范见 `docs/12-历史项目金标准导入与分层规范.md`。

DXF 几何级第二通道审查器在 DWG 主平面范围内统计直接模型实体，并执行基础 2D BLOCK/INSERT 基点、缩放、旋转和嵌套展开，再按专业类别与 DWG 候选比较；完整数组、非平面挤出、全部填充拓扑和专业语义仍需第二 CAD 引擎。结果固定为未批准且不可计量。完整限制见 `fixtures/ningbo-xiecheng/2026-09/derived/cad-secondary-geometry-review-report.md`。

跨引擎逐对象核对器使用 DXF/DWG 保留的 CAD 实体句柄比较图层、类别、实体类型和边界；块使用展开后边界，圆弧使用独立采样容差。非交集项按类别和实体类型保留为抽查队列，不能因共同项匹配而自动批准专业对象。

SQLite 持久化适配器可通过 `MVPApp(SQLiteStore("vertical-mvp.sqlite3"))` 使用。它用于本地验证重启恢复，不等同于生产租户隔离；生产环境仍需执行 `persistence/postgres/001_vertical_mvp.sql` 并使用非 owner 应用角色。

本地 HTTP 服务使用 `X-Organization-Id` 和 `X-Actor-Id` 作为开发身份头，不能用于生产；生产必须替换为 OIDC/JWT 验证、正式反向代理和限流。默认数据库文件是 `var/app.sqlite3`，可用 `RKD_MVP_DB_PATH` 指定位置。下一阶段将把 `SQLiteStore` 替换为带 RLS 的关系数据库，把本地单进程队列替换为具备并发 claim、租约、延迟重试和监控的正式消息系统。
