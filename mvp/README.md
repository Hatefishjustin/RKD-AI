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

旧参考内核仍保留内存/SQLite快照与模拟适配器，相关模拟命令不作为业务完成证明。当前可操作服务使用SQLite或显式PostgreSQL仓储；NAS另用FastAPI/Uvicorn账号入口。真实RLS、完整恢复、部署及专业生产边界分别验证，不能把旧内核或当前规则模型等同正式BIM/施工发布。

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

### AI-DESIGN-01 需求理解任务（候选任务书）

“需求”页顶部新增 AI 需求理解区。默认 `start` 不配置任何真实模型通道：提交后会保存可见的失败作业及配置错误，不生成规则任务书，也不产生设计、量价、采购或发布副作用。要在本机用明确标记的**非真实 AI**合成通道检查完整持久任务链，可运行：

```powershell
pwsh -NoProfile -File .\scripts\rkd.ps1 start-ai-synthetic
```

该命令只设置 `RKD_AI_PROVIDER=synthetic` 与 `RKD_AI_EXTERNAL_CONTEXT=false`，不会联网、不读取其他软件密钥、不发送项目原件。工作台会显示“本地合成测试通道（非真实 AI）”；提交合成自然语言后立即返回持久作业编号，后台记录排队/理解/校验/保存阶段、模型运行配置、用量摘要和失败原因。成功后可查看带来源状态的任务书、假设、冲突、最少补问与成本缺项，并人工编辑保存为新修订。该结果仍是候选，不代表 AD01—AD08 通过，也不代表真实模型调用了外部服务。

真实 OpenAI 兼容通道由服务端环境变量显式配置：`RKD_AI_PROVIDER=openai-compatible`、`RKD_AI_BASE_URL`、`RKD_AI_MODEL`、`RKD_AI_API_KEY`；可选 `RKD_AI_PROVIDER_NAME`、`RKD_AI_TIMEOUT_SECONDS`、`RKD_AI_MAX_INPUT_CHARS`、`RKD_AI_MAX_OUTPUT_TOKENS`。默认 `RKD_AI_EXTERNAL_CONTEXT=false`，真实模型调用只发送当前自然语言输入与必要提示，不外发项目决策、原件元数据或原件文本；只有显式设为 `true` 才发送已获准的项目上下文。原件文本可在本地按 01c 解析，但解析结果仅本地可查，不会因设为 `true` 自动外发。密钥不进入任务记录、日志、前端或 Git；费用未知时保留 `unknown`，超时可能计费时保留 `pending_reconciliation`。未提供配置或调用失败时不会退回合成或规则结果冒充真实 AI。接口与任务书契约见 `contracts/v1/openapi.v1.json`、`contracts/v1/ai-design-brief.schema.json`。

### M5-01 本机账号与项目权限

在项目根目录运行：

```powershell
pwsh -NoProfile -File .\scripts\rkd.ps1 start-secure
```

首次在终端设置个人管理员账号、显示姓名和 8–128 字符密码，密码输入不回显，也不写入命令行或日志。已有账号时直接启动；浏览器地址仍为 `http://127.0.0.1:8080`。如果已有服务占用端口，先在其启动终端按 Ctrl+C 停止再启动。启用账号后，普通 `start` 也会自动使用账号模式；设置 `RKD_AUTH_MODE=local` 试图降级将失败。

登录后侧栏“账号与成员管理”可创建普通账号、分配当前项目的负责人/编辑/只读角色、撤销访问、停用或恢复账号。管理员可管理本组织全部项目；普通用户只能看到已分配项目。下载原件和各类成果均检查当前会话与项目授权。负责人只具备本地验收记录权限，没有正式报价/合同/施工图发布权限。

首次启用请自行设置真实密码。自动验收使用隔离数据库中的随机测试密码，不会在用户运行库预建默认管理员。现有本地使用方式继续保留，未初始化账号的数据库仍使用固定本地身份；它不接受客户端伪造组织或操作者。

本批业务 API 仍为回环地址、SQLite 和参考 HTTP server，**未获准局域网/公网团队生产使用**。PostgreSQL 完整备份恢复、HTTPS/生产服务器、监控、专业审签、SSO/MFA 及账号恢复流程仍按 M5 后续任务处理。管理员不授予正式发布权限，真实下单和付款关闭。

复核命令：`node scripts/verify_m5_entry.cjs`。测试自动启动/停止自己的隔离服务，运行库、下载及截图写入 `var/evidence/m5-entry/run-*/`，不连接 `var/app.sqlite3`；测试密码仅在子进程环境中传递，不进入证据文件。仅复核账号切片可加 `--accounts-only`。

### M5-02 真实 PostgreSQL 验证

项目根目录执行：

```powershell
pwsh -NoProfile -File .\scripts\rkd.ps1 postgres-prepare
pwsh -NoProfile -File .\scripts\rkd.ps1 postgres-test
```

首条命令准备项目内固定版本工具及可选驱动；第二条创建自己的回环测试实例，实际迁移、执行 16 项数据库检查、导入只读运行快照、核对记录/文件并重启数据库，结束停止实例。2026-10-28 的演练核对 37 张目标表、733 行及 74 个文件通过；现有 `var/app.sqlite3` 和原件保留。详见 [验证报告](../docs/15-M5-02真实数据库验证与迁移演练.md) 和 [持久化说明](persistence/README.md)。本入口没有切换业务 API，M5-02 全域接入及 M5-03 完整恢复仍待完成。

### PostgreSQL 生产链 API 试点

`postgres-test` 现在还会实际执行生产链业务专项（当前 45 项）和独立 API 进程的真实上传、签名下载、版本冲突及重启；证据位于各轮 `business-tests.log`、`api-verification.json`。应用角色必须非 owner、非超级用户且没有绕过 RLS 的权限，单独授予 `EXECUTE ON FUNCTION rkd.list_project_summaries(), rkd.list_account_project_roles(text)`；底层项目/文件 RLS 保持项目级隔离。

可用 `scripts/rkd.ps1 postgres-api` 启动回环 API 与构建工作台试点：通过进程环境显式设置 `RKD_POSTGRES_DSN`（回环数据库、已迁移及授权的应用角色）、`RKD_POSTGRES_RUNTIME`（独立原件/成果目录）和可选 `RKD_POSTGRES_PORT`（默认 8092）。未启用账号时用固定本机身份；`postgres-accounts` 在可信本机终端交互创建管理员，之后自动账号模式且禁止降级，旧本机进程即时拒绝访问。没有 DSN/数据库错误也不会回退 SQLite。该入口已接项目、文件/决策、需求、规则设计、地坪量价/成果、采购、变更再生产、任务/问题、预算及独立参数几何；账号/会话/角色已接（8项真实PG身份专项）；旧模拟命令等未开放域明确返回 501；默认 `start` 仍为已有完整本地工作台。不要用此切片替代日常服务。

### 完整本地备份与恢复

`pwsh -NoProfile -File scripts/rkd.ps1 backup` 将当前 SQLite 一致快照、库内引用的原件/成果、应用源码、锁定依赖、种子资料和构建前端保存为 `var/backups/complete-*.zip`。缺失或哈希不一致的文件会使备份失败，不输出已完成包。包包含业务数据和账号密码哈希，按原始项目资料管理；不包含系统 Python、.venv、node_modules 或环境秘密。

恢复到新目录：`pwsh -NoProfile -File scripts/rkd.ps1 restore -Archive "完整包路径.zip" -Destination "新恢复目录"`。已有目录拒绝覆盖；每个文件和数据库行摘要通过后才发布恢复目录。`runtime/app.sqlite3` 为恢复数据库，`application/` 为当时应用基线，`restore-report.json` 记录时点、耗时与校验数。旧会话失效，使用原账号密码重新登录；未完成上传需重新上传。

使用恢复的应用时，将 `RKD_MVP_DB_PATH` 指向新目录的 `runtime/app.sqlite3`，用已准备的 Python 执行 `application/mvp/run_api_server.py`；迁移到其他机器时按包内锁定依赖重建环境。该入口只支持当前 SQLite 本地恢复，不能替代 PostgreSQL 或生产环境灾备验收。可复验 `scripts/verify_local_backup.py`。

### 设计到地坪量价与采购草稿

“需求草稿”→“分区布局”保存设计后，会按同一设计对象自动生成地坪工程量、量价报告、采购需求和包含 SVG/DXF 的完整生产包。默认只计功能分区；“地坪范围、价格与采购信息”可选择包含通道。未分配区域不计量，材料损耗保持未知，采购量为净几何量。

成本空白保留未知；填写成本、加成率、试用税率或来源后会生成新量价版本。材料规格、供应商及到货地点齐全时，自动生成采购施工页的本地订单草稿，不对外下单。设计修改会自动更新量价与草稿，旧包可下载；过期基线不能登记新收货。已有收货/分派事实时只生成待核对的最新采购需求，避免重复整单采购。

生产版本选择器可查看历史及下载包。所有数量保留设计/需求修订、对象 ID 和来源；草稿不等于专业批准。可重复验证：`.venv\Scripts\python.exe scripts/verify_production_chain.py`，只使用 `var/evidence/` 的独立数据库和服务。

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

SQLite 持久化适配器可通过 `MVPApp(SQLiteStore("vertical-mvp.sqlite3"))` 使用。它用于本地验证重启恢复，不等同于生产租户隔离；PostgreSQL 使用连续版本迁移及非 owner 应用角色，当前计划内业务域已通过真实PG服务、HTTP、浏览器和恢复验证；日常库切换及NAS部署单独验收。

默认本机服务使用固定本地身份，开发身份头不能改变它；账号模式使用服务端会话和项目角色。`DevHeaderIdentityProvider` 只供显式配置的开发测试，不能用于生产。默认数据库文件是 `var/app.sqlite3`，可用 `RKD_MVP_DB_PATH` 指定位置。M5 后续接入带 RLS 的 PostgreSQL 业务服务及可靠任务消费，并按阶段验证生产服务器、HTTPS、监控和恢复。

### 完整 PostgreSQL 备份与恢复

可信维护终端显式设置 `RKD_POSTGRES_MAINTENANCE_DSN` 和匹配的 `RKD_POSTGRES_RUNTIME` 后，执行 `scripts/rkd.ps1 postgres-backup`。备份使用同一导出快照的 pg_dump 和逐表摘要，包含全部引用原件/成果及当前应用基线；不打包数据库连接密码。应用非owner角色因RLS不可见全表时拒绝生成不完整备份，不回退或隐式使用应用DSN。

恢复使用指向新建空应用数据库的维护DSN：`scripts/rkd.ps1 postgres-restore -Archive 完整包.zip -Destination 新目录`。已有目录/非空库拒绝覆盖，包内字节先于数据库写入校验；恢复后核对所有行/文件，再撤销旧会话及中断上传，保留原密码/角色/业务幂等。可用 `RKD_POSTGRES_APP_ROLE` 指定已有、非owner、非超级用户且无bypassrls权限的应用角色，恢复器授予最小业务表及目录函数权限。源码CLI `scripts/postgres_backup.py` 的 `--binary-directory` 可显式指定对应平台同版本 pg_dump/pg_restore 工具目录。

### AI-DESIGN-02/03 设计候选与反馈草稿

`start-ai-synthetic` 同时启用 `RKD_AI_PROVIDER=synthetic` 和 `RKD_AI_DESIGN_PROVIDER=synthetic`。在“需求”页生成结构化任务书后，打开“AI 候选”页提交候选集：系统立即返回持久作业编号，后台记录策略/几何/校验/图面阶段，保存至少两个具有不同空间组织的可计算候选和真实 SVG 文件。新几何使用 `rkd-ai-design-option.v1`，支持左侧/右侧入口、障碍、环形或支状通路、功能区、展台与隔断意向；不再要求所有分区接触旧底边通道。

每个候选显示图面、入口/动线结构、材料意向、已知成本与缺项、硬检查和取舍；可输入“更开放但保留入口”“材质别太冷”等反馈生成新修订，稳定对象 ID、锁定条件和对象 diff 均保留。冲突反馈、障碍阻断、窄通路、点接触或同质候选会被明确拒绝，不写入当前设计、量价、采购、批准或发布状态。采用按钮只把选定有效候选登记为“当前草稿”，`production_task_status` 保持 `not_started`；正式批准与同源量价属于后续 04/05。

本批的候选策略由明确标记的合成设计适配器产生，不是语言模型判断；OpenAI 兼容需求理解通道也只验证协议适配，没有真实付费设计模型调用。AD01—AD08 仍按实际反馈和同源成果逐项验收，不因工程链通过而自动计分。接口契约见 `contracts/v1/openapi.v1.json`，模型契约见 `contracts/v1/ai-design-option.schema.json`。

恢复应用位于目标 `application/`，原件与成果位于 `runtime/`；环境和数据库凭证独立配置，不能从包内假设。`scripts/verify_postgres.py` 在隔离实例执行完整恢复、逐文件HTTP下载及实际API/数据库重启，不改日常运行库。

### FN NAS 候选部署

独立生产传输为 `mvp/run_team_api.py`（FastAPI/Uvicorn、真实账号、显式PG、回环监听）；共享 `ApiRoutes` 和现有领域服务，不运行参考HTTP server，也不信任代理身份头。公开Origin必须HTTPS，只有回环地址可用HTTP加密隧道试验。锁定依赖在 `mvp/requirements-server.txt`，本机prepare同时安装。

`python scripts/prepare_nas_release.py` 从当前日常库生成完整一致备份、隔离恢复及校验发布包；NAS准备、独立容器、首位个人账号及HTTPS验收见 [部署操作](../scripts/deploy/README.md)。`python scripts/verify_team_transport.py` 验证真实NAS初始化程序、PG、Uvicorn、浏览器和重启；仅使用 `var/evidence/` 隔离实例。实际状态仍以根台账为准，候选包不代表团队上线或权威库切换。


账号模式现支持审核岗位和草稿待办：管理员在“账号与成员管理”配置两个岗位及项目权限，负责人在生产区域检查并提交草稿，符合职责分离条件的成员在顶部待办记录意见。无有效接收人保持待配置；源版本/文件变化后旧事项失效。记录不授予正式报价、施工图或外部发布权限。SQLite019/PG009为新增任务表；日常权威库切换仍需单独验收。

### AI-DESIGN-04/05 同源深化与量价草稿

在“AI 候选”页采用有效候选后，打开“深化量价”页。可留空未税单位成本，也可填写明确的测试价源；施工成本加成默认 0.20、本地试用税率默认 0.05，金额均由 Decimal 程序计算，正式税务适用性仍为 unknown。提交后返回独立作业编号，后台依次完成同源对象整理、确定性计量、成本试算和成果落盘，并把采用指针的生产任务状态从 `not_started` 推进到 `queued/succeeded/failed`；旧 `create_design → production sync` 保持关闭，不创建采购订单或发布。

深化包从同一采用候选派生材料表面、展陈/家具、隔断和入口对象，生成模型驱动 glTF（节点 extras 保留语义对象 ID）、等轴测 SVG、平面 SVG、对象工程量 CSV、量价 HTML、development JSON、manifest 和 ZIP。只有功能分区净地坪面积进入本地试算；展示对象仅计数、隔断仅记录二维长度，通路、材料产品、损耗、包装、起订量、天花灯具、正式税务和专业审签保持 unknown，不把 0 当未知，也不把地坪小计冒充全项目总价。

所有成果按文件字节数和 SHA-256 登记，下载时再次校验；采用基线发生反馈修订或重新采用后，旧成果标记 `source_outdated` 但保留可读。候选/采用/批准/发布仍分开。契约见 `contracts/v1/ai-development-package.schema.json` 与 `contracts/v1/openapi.v1.json`。本批仍是确定性工程链，不是真实 AI 设计质量或正式报价验收；AD01—AD08 仍按真实模型调用、用户反馈和专业成果逐项判定。

### AI-DESIGN-01c 原件内容解析与 DELIVERY-01 技术交付草稿

“需求”页旁的“资料与技术交付”页提供两项本地能力：

1. **原件内容解析**：对项目内已保存的原件逐个点击“解析原件”。纯文本/Markdown/CSV/JSON/XML/DXF 按行生成可定位片段（`line:N-M`）；PDF 只读取能可靠解码的文本层，按内容流/文本块定位，页码映射未核验会明确提示；扫描件、CID 字体、CAD 二进制、电子表格和图片一律标记 `no_extractable_text_layer` 或 `unsupported_format`，**不编造内容**。每条记录绑定原件 SHA-256 与抽取器版本，原件变化后旧记录标记非当前。抽取结果仅本地可查：需求理解作业的输入清单会注明哪些文件已有本地文本片段，但未获明确批准前不把项目资料或原件文本发给外部模型。
2. **同源技术交付草稿**：只有当前已采用且未过期的深化包可以生成。成果含带对象 ID/尺寸标注的技术平面 SVG、材料做法 CSV、地坪/隔断节点示意 SVG、技术交接说明 HTML、交接数据 JSON、成果清单和 ZIP，共 7 类；全部绑定同一对象集、采用版本和输入哈希。材料规格、产品、做法、构造、机电/消防接口、现场实测、损耗与正式税务保持 unknown；专业复核待办按角色列出且状态恒为 `pending`。技术包**不是施工图**，不触发旧 `create_design → production sync`、采购订单、正式报价或施工发布。

成果按字节数和 SHA-256 登记，下载时再次校验；采用基线变化后旧包标记 `source_outdated` 但保留可读。新增表使用 SQLite 024 / PostgreSQL 014 迁移（含 RLS 与导入映射），不改已执行的旧迁移或旧成果。契约见 `contracts/v1/ai-source-extraction.schema.json`、`contracts/v1/ai-technical-handover.schema.json` 与 `contracts/v1/openapi.v1.json`；AI 需求任务书契约的来源状态与来源类型做了兼容扩展。

可复跑验证与评审材料生成：

```powershell
pwsh -NoProfile -Command "& '.\.venv\Scripts\python.exe' '.\scripts\verify_professional_delivery.py'"
pwsh -NoProfile -Command "& '.\.venv\Scripts\python.exe' '.\scripts\build_design_review.py'"
```

前者跑专项/全量测试、严格环境检查、前端构建并输出 `var/evidence/professional-delivery/2026-11-08/verification.json`；后者在隔离临时库跑完整链，把两个真实候选图面、技术平面与评审问题清单写成单文件可打印 HTML（`var/review/2026-11-08/design-review-2026-11-08.html`），不改动日常运行库或 NAS。两者都不联网、不调用付费模型。

后续已补真实环境证据（2026-11-09）：`scripts/verify_postgres_delivery.py` 在隔离 PG17 实例上验证 014 三表的 jsonb 往返、RLS、租户隔离与成果字节；`scripts/verify_delivery_browser.py`（配合 `verify_delivery_browser.cjs`）用真实浏览器点击本页完成解析原件、生成技术包、下载 ZIP 与桌面/移动截图。命令：

```powershell
pwsh -NoProfile -Command "& '.\.venv\Scripts\python.exe' '.\scripts\verify_postgres_delivery.py'"
pwsh -NoProfile -Command "& '.\.venv\Scripts\python.exe' '.\scripts\verify_delivery_browser.py'"
```

### 真实 AI 设计通道（2026-11-09 起）

需求理解、两个概念候选与自然语言反馈修订已改由真实 OpenAI 兼容模型完成；合成适配器只用于工程回归，不再冒充设计能力。程序仍负责几何硬检查、落模、工程量、图纸与责任边界；校审不通过时把错误与修复建议退回模型限次重画，仍不通过则明确失败、不写入候选。

启动（密钥只在当前终端会话，不要写进任何文件）：

```powershell
$env:RKD_AI_API_KEY = '你的密钥'
pwsh -NoProfile -File .\scripts\rkd.ps1 start-ai-real
```

可覆盖 `RKD_AI_BASE_URL`（默认 `https://api.codelink.chat/v1`）、`RKD_AI_MODEL`（默认 `gpt-5.6-sol`）、`RKD_AI_DESIGN_MAX_ATTEMPTS`、`RKD_AI_TIMEOUT_SECONDS`、`RKD_AI_DESIGN_MAX_OUTPUT_TOKENS`、`RKD_AI_RUN_LOG_DIR`。**`RKD_AI_EXTERNAL_CONTEXT` 固定默认 false**：只向模型发送自然语言输入、明确标记的测试边界与必要提示，项目原件、本地解析文本、项目决策、预算与现场照片均不外发。密钥不进入数据库、日志、前端、Git 或任何落盘配置；`var/ai-model-runs/design-model-runs.jsonl` 与证据目录里的台账只记录模型、提示版本、用量、请求 ID、内容与错误分类，不记密钥。

可复跑验证与评审材料：

```powershell
$env:RKD_AI_API_KEY = '你的密钥'
pwsh -NoProfile -Command "& '.\.venv\Scripts\python.exe' '.\scripts\verify_real_design.py'"
pwsh -NoProfile -Command "& '.\.venv\Scripts\python.exe' '.\scripts\build_real_design_review.py'"
```

前者在隔离库真实跑「需求理解→两个候选→反馈修订→采用→同源深化/技术交付」并输出 `var/evidence/real-design/<日期>/run-*/verification.json`；后者从该运行留下的成果生成 `var/review/<日期>/real-design-review.html`（+ PDF），**不再调用模型、不读取密钥**。负例见 `mvp/tests/test_real_design_provider.py`：未配置、401、超时、畸形输出、同质候选均明确失败且不回退合成，全部用本地协议桩，不联网不计费。

边界：真实模型调用已发生并留痕，但 AD01—AD08 仍按固定验收逐项判定，本批不自行改判通过数；AD08 只能由用户对具体图面给出，不得由模型自评或自动测试代签。费用金额保持 unknown、超时保留 pending_reconciliation。PG/浏览器证据只支撑工程回归；技术交付深度仍只到「可审查草稿」，不是施工图，专业复核 pending。

### 参考真实平面图后的设计方法（2026-11-10）

用户对第一批真实候选明确否决「两个都完全不可以」，要求先学习真实设计师怎么布局。`mvp/rkd_mvp/design_reference.py` 保存 12 项带来源的研究要点（WW/T 0089-2018、《展示设计》教材、《博物馆设计：故事、语调及其他》、金堂奖 300㎡ 与设计本 560㎡ 公开平面图、600㎡「一轴四区」、MiSUMi 单向叙事、南京博物院二期、行业指南、FOAR 2025 视域图论文），经 `prompt_brief()` 注入真实模型提示；真实模型按「先叙事 → 选拓扑原型 → 排前厅/主展/深度洽谈/后勤层级与节奏 → 落几何」输出，候选对象带 `zone_role`、`sequence_role`、片墙、家具类型与视觉焦点。`ai_design_geometry.render_svg` 改为概念平面图纸表达：粗实线墙体、入口门斗与门扇弧线、动线虚线箭头、真实家具轮廓、尺寸线、图例、指北针与标题栏。

返工评审页：`var/review/2026-11-10/real-design-review.html`（+ PDF），第 0 节记录用户否决、实际看过的真实平面图与提炼的 5 条方法；图面由 `scripts/build_real_design_review.py` 从持久模型用当前制图程序现场重绘，不改模型或已登记成果。公开平面图仅保存在 `var/evidence/design-research/2026-11-10/` 供本地学习，不随交付物分发、不复制图纸。

边界：这些数值与原型仅作布局方法参考，不替代当地规范与审图意见，不宣称消防/疏散/无障碍合规；分区仍为矩形、边界为测试参数、未表达柱网/门窗/楼梯，概念平面不是施工图。设计质量仍以用户对具体图面的评价为准，未获认可前不宣称通过。
