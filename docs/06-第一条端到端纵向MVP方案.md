# 第一条端到端纵向 MVP 方案

> 2026-09-29 交付拆分：当前按 [产品交付执行计划与设计](13-产品交付执行计划与设计.md) 先完成 M1 的真实界面、文件、计算、导出和恢复，再完成 M2/M3 专业成果链。本文的大范围纵向链不再是首次让用户看到系统的门槛；现有参考实现有已复现运行缺陷，模拟成果成功不计作产品完成，最新结果见根目录状态文件。

文档状态：V1.1 执行基线（参考实现审查修订）
编制日期：2026-09-18
适用范围：从一个企业空间项目的资料接入，到 G2 批准、生产批次、至少两个专业成果分支、EX-14 交叉检查和变更回放。
依赖文档：`00-开工前架构预检与扩展性约束.md`、`01-自主设计公司系统V1产品需求规格.md`、`02-完整业务生产链和项目状态机.md`、`03-Agent与专业执行器设计.md`、`04-空间BIM成果与报价统一模型方案.md`、`05-平台后端工作流权限审计部署与备份架构.md`
依赖契约：`contracts/v1/*.schema.json`

## 1. 目标和完成定义

本 MVP 的目标不是证明所有专业都能自动完成，而是证明系统具备一条真实可运行的生产骨架：

1. 用户可以在组织和项目边界内登录、上传资料、查看处理状态和领取人工任务。
2. 原始文件经过隔离、扫描、版本化后，能够形成可引用的需求、DesignIntent、SpatialPlan 和生产基线。
3. 同一个 `ProductionBatch` 能按统一模型清单启动至少两个成果分支，并保留同一基线、输入版本、执行器版本和质量门。
4. 分支结果能够通过 `ValidationProfileV1` 和 EX-14 交叉检查，失败时进入可解释的修正或人工接管路径。
5. 任意命令、事件、Agent 运行、执行器作业、人工审批和产物都能沿 `correlation_id`、`causation_id`、`TraceLink` 和审计记录回放。
6. 同一消息、命令、回调或故障重试不会产生重复业务事实或重复外部副作用。
7. 修改一个固定构件后，旧成果不会被静默覆盖，系统能标记过期分支并只重跑受影响的分支。

MVP 完成的判断以验收矩阵为准，不以页面数量或模型调用次数为准。没有跨租户负例、重复消息、超时、恢复和人工接管测试，不得宣称完成。

## 2. 产品切片

### 2.1 固定场景

- 一个组织下的一个室内设计项目。
- 一个楼层或一个主要空间区域。
- 一组经过脱敏的现场资料：CAD/PDF/图片/材料表中至少两类；没有资料时使用版本化合成夹具。
- 空间对象覆盖房间、墙、门、窗、地面、顶面、固定家具、灯具和设备的最小集合。
- 一个批准的 `DesignIntent`、一个 `SpatialPlan`、一个 BIM 原生表示和一个交换表示。
- 生产批次至少运行两个分支。默认选择“施工图 + 工程量/报价”；若 BIM 或制图执行器尚未具备，允许以“效果图 + 工程量/报价”作为临时分支，但契约和质量门不能省略。

### 2.2 不纳入本 MVP

- 真实付款、正式采购下单、不可撤销的客户发布和真实供应商写入。
- 完整机电/结构协调、复杂自由曲面、全量施工节点自动生成。
- 自动批准材料替代、自动签署合同、自动改变财务事实。
- 未经证据确认的竣工现状作为真实数据。
- 一开始就支持多组织复杂计费、开放式插件市场和所有历史项目迁移。

非目标不等于删除接口。接口保留版本、能力、状态和人工接管位，后续可以替换模拟适配器而不改变业务对象和审计边界。

## 3. 角色和授权

| 角色 | MVP 能力 | 明确不能做的事 |
| --- | --- | --- |
| 组织管理员 | 建立项目、管理成员、查看审计和运行健康 | 不能绕过 G2/G3/G5 专业或财务门 |
| 项目负责人 | 上传资料、组织需求、发起生产批次、领取异常 | 不能修改已批准基线或直接写数据库 |
| 设计负责人 | 编辑 DesignBrief/DesignIntent、选择概念、提交设计审批 | 不能以 Agent 结果代替本人审批 |
| 专业负责人 | 审核空间、模型、图纸、工程量和质量门 | 不能修改来源事实而不产生新修订 |
| 商务负责人 | 审核数量、价格快照、报价风险和客户版草稿 | 不能直接提交真实采购或付款 |
| 审计/运维 | 查看不可篡改审计、重放队列、恢复演练结果 | 不能无记录地改业务事实 |
| Agent/Executor 身份 | 读取被授权输入、返回结构化结果、申请命令 | 无生产库写权限、无通用管理员权限 |

所有 API、后台任务、对象令牌、搜索索引和恢复连接都必须携带组织/项目上下文；项目外的同 ID 资源统一返回不可区分的拒绝结果。

## 4. 端到端流程

### 4.1 主流程

```text
登录/组织/项目
  -> 文件上传初始化
  -> 隔离区扫描与文件指纹
  -> 原始资料版本化
  -> 需求草稿与 DesignBrief
  -> DesignIntent 草稿
  -> 人工概念选择和 G2 批准
  -> SpatialProgram / SpatialPlan
  -> ProductionBatch
  -> BIM Manifest
  -> 分支 A：施工图或效果图
  -> 分支 B：工程量与报价
  -> EX-14 统一交叉检查
  -> 人工查看与成果发布模拟
  -> 审计、指标和可回放记录
```

### 4.2 资料接入

1. API 创建上传会话，返回一次性对象存储令牌；令牌只允许写入指定组织、项目和隔离前缀。
2. 上传完成后计算 `sha256`、媒体类型、大小、来源、上传者和资料分级，写入 `FileObject` 草稿。
3. 扫描、格式识别、敏感信息检测和压缩包递归检查通过后，资料从 `quarantine` 转为 `raw`；失败或超时停留隔离区。
4. 任何下游任务只能引用已扫描的文件版本。扫描结果和文件指纹是审计证据，不允许覆盖。

### 4.3 需求与 G2

使用已注册命令 `CreateRequirementDraft`、`CreateDesignBriefDraft`、`SubmitBriefForReview`、`ComposeDesignIntent`、`SelectConceptOption` 和 `ApproveDesignIntent`。Agent 只能返回建议和证据引用，命令网关验证权限、来源修订、状态和幂等键后写入事实。

G2 通过条件：需求冲突有处置结论，DesignIntent 的目标、限制、风格、预算等级、禁用项和验收指标已版本化，现场资料可用性达到 `ValidationProfileV1` 的最低阈值，且审批人不是自动化身份。

### 4.4 空间和生产批次

使用 `CreateSpatialProgramDraft`、`QueueSpatialSolveJob`、`RecordOptionMetrics` 和人工 `SelectOption`。MVP 可以使用确定性空间规划夹具或人工输入的已验证布局，但必须输出空间对象 ID、版本、约束、指标和决策证据。

使用 `QueueBIMBuildJob` 创建 BIM 修订和 `UnifiedModelManifestV1`。Manifest 至少绑定：语义模型修订、BIM 原生文件、交换表示、坐标和单位上下文、对象映射、转换损失、覆盖率、执行器和规则版本。

### 4.5 两条专业分支

每条分支都是独立的 `ExecutorJob`，共享同一个 `ProductionBatch` 和输入基线：

- 图纸分支：`QueueDrawingJob` -> `drawing-set.generated` -> 图纸验证 -> `MarkDrawingReleaseCandidate`。
- 效果图分支：`QueueSceneBuildJob` -> `QueueRenderJob` -> 场景/相机/图片和差异报告。
- 工程量/报价分支：`QueueQuantityTakeoff` -> `QueuePriceCalculation` -> `CreateQuoteDraft`。

默认验收组合为“图纸 + 工程量/报价”。每个分支可独立重试，但只能使用兼容的同一模型基线；一个分支重跑不能把另一个分支静默替换为最新版本。

### 4.6 EX-14 和发布模拟

`QueueValidationJob` 使用一个明确版本的 `ValidationProfileV1`，检查至少包括：空间面积和对象数量、模型与图纸引用、模型与工程量映射、报价数量/单价/税/舍入、DesignIntent 关键约束和成果基线一致性。

所有阻断错误进入 `CreateTechnicalIssue`、`CreateCommercialIssue` 或人工任务。通过后仅生成“可审阅/可发布模拟”状态；使用 `SimulatedPublishAdapter` 写入测试外部记录和审计，不接真实客户、供应商或付款系统。

### 4.7 变更回放

人工发起 `CreateChangeSetDraft`，改变一个固定家具或灯具的位置/规格，生成新修订和 `TraceLink`。旧生产批次保持历史状态；系统标记受影响的 BIM、图纸、效果图、工程量和报价分支，使用 `QueueImpactAnalysis` 决定重跑集合。未受影响且输入版本兼容的分支可以保留，但必须显示“来自旧基线”。

## 5. 纵向架构切片

### 5.1 运行单元

| 运行单元 | 责任 | 不拥有的权力 |
| --- | --- | --- |
| `web-api` | OIDC 回调、查询、上传会话、命令入口、审批页面数据 | 不直接调用执行器写业务事实 |
| `command-gateway` | 权限、状态、幂等、聚合写入、业务审计摘要和 Outbox | 不执行长耗时专业计算 |
| `workflow-worker` | 持久化等待、重试、人工任务、分支依赖和升级 | 不绕过命令网关改聚合 |
| `agent-runtime` | 需求提取、冲突解释、建议和证据整理 | 不拥有生产 DB 写权限 |
| `executor-dispatcher` | 创建 `ExecutorJob`、签名输入包、接收回调、Inbox 去重 | 不把回调直接当业务事实 |
| `simulated-executors` | 用固定夹具生成 BIM/图纸/渲染/QTO/验证结果 | 不访问其他租户数据 |
| `audit-projector` | 将可靠审计队列写入隔离审计存储、哈希链和检查点 | 不修改业务事实 |
| `object-store` | 隔离区、原始文件、派生文件和下载令牌 | 不提供跨项目裸路径 |
| `relational-db` | 聚合、修订、任务、Outbox/Inbox、权限和索引 | 应用角色不能绕过 RLS |

MVP 可将多个运行单元部署在一个进程或少量服务中，但模块边界、身份边界、事务边界和契约边界必须保持，后续拆分不得改变消息语义。

### 5.2 最小模块所有权

| 模块 | 主要聚合 | 纵向链中的最小职责 |
| --- | --- | --- |
| Identity/Access | Organization、Membership、Role、Policy | 组织、项目上下文和授权决策 |
| Project Kernel | Project、Revision、Baseline、TraceLink、Artifact | 所有生产对象的版本和来源 |
| Intake | FileObject、ScanResult、SourceEvidence | 文件隔离、扫描、指纹和证据 |
| Requirements/Design | Requirement、DesignBrief、DesignIntent、ConceptOption | 需求到 G2 的可审批事实 |
| Spatial/Model | SpatialProgram、SpatialPlan、BIMRevision、ObjectMapping | 统一模型和 Manifest |
| Production | ProductionBatch、ExecutorJob、ExecutorResult | 分支调度、结果收口和重试 |
| Commercial | BOQ、Quote、PriceSnapshot、CommercialIssue | 数量、价格、报价草稿 |
| Quality | ValidationRun、TechnicalIssue、Exception | EX-14 和阻断规则 |
| Workflow/Audit | WorkflowRun、HumanTask、CommandRecord、AuditEvent | 等待、人工接管、审计和回放 |

## 6. 契约和消息路径

### 6.1 Agent 路径

```text
AgentTaskV1
  -> AgentResultV1
  -> 证据/模式/业务校验
  -> CommandEnvelopeV1
  -> command-gateway
  -> business fact + AuditEventV1 + Outbox
```

Agent 结果中的 `proposed_commands` 不是已执行命令。命令网关拒绝缺少来源修订、规格哈希、权限上下文、幂等键或验证结果的命令。

### 6.2 执行器路径

```text
ExecutorJobV1
  -> executor input package
  -> SimulatedExecutor
  -> ExecutorResultV1
  -> Inbox 去重和规格/能力校验
  -> Artifact/Validation/Issue 命令
  -> EventEnvelopeV1 + AuditEventV1
```

结果回调必须同时提供 `job_id`、`attempt`、输入规格哈希、执行器版本、输出产物引用、质量摘要、错误类型和可重试建议。重复回调只能产生一次业务结果。

### 6.3 事件和审计

所有事件使用 `EventEnvelopeV1`，至少包括组织/项目、聚合版本、相关/因果 ID、幂等键、事件 schema 版本、数据分级和 payload hash。关键状态变化使用 `AuditEventV1`，通过前一事件哈希、当前事件哈希和定期 checkpoint 形成可验证链。

## 7. 模拟适配器

### 7.1 必备适配器

1. `SimulatedScanAdapter`：模拟通过、病毒命中、超时和格式不支持。
2. `SimulatedSpatialExecutor`：用确定性夹具返回空间方案和指标。
3. `SimulatedBimExecutor`：生成最小 BIM 原生/交换文件和 `UnifiedModelManifestV1`。
4. `SimulatedDrawingExecutor`：生成图纸集、图纸索引、视图来源和质量报告。
5. `SimulatedQtoExecutor`：按模型映射生成 `QuantityItem`、BOQ 和数量证据。
6. `SimulatedRenderExecutor`：在选择效果图分支时生成场景、相机、图片占位和一致性报告。
7. `SimulatedValidationExecutor`：执行 ValidationProfile 和 EX-14 规则。
8. `SimulatedPublishAdapter`：将“可发布”写入隔离测试端点，支持确认、拒绝和 unknown。

### 7.2 故障注入

每个适配器都支持测试配置而不是隐式随机：

| 故障 | 预期行为 |
| --- | --- |
| 超时 | 任务进入 retryable，达到上限后人工接管 |
| 重复回调 | Inbox 去重，不新增业务事实 |
| 输入规格过期 | 拒绝结果，不能写入新基线 |
| 质量门失败 | 产物保留为失败证据，创建技术/商务问题 |
| 外部 unknown | 停止自动重发，进入对账或人工解决 |
| 租户上下文错误 | 拒绝并记录安全审计，不泄漏资源存在性 |

适配器输出必须使用固定夹具版本和 deterministic seed，便于历史回放、差异比较和升级兼容测试。

## 8. MVP 工作流状态

主工作流状态：

```text
created
  -> intake
  -> scanning
  -> requirements
  -> design-intent-review
  -> pending-g2
  -> g2-approved
  -> spatial-plan
  -> production-batch
  -> branch-processing
  -> cross-check
  -> ready-for-review
  -> completed
```

任何状态都可以进入 `blocked`、`failed` 或 `superseded`，但必须带原因、责任人、输入版本和恢复动作。`completed` 只表示该基线的 MVP 成果包通过验收，不表示后续版本永远有效。

工作流运行时必须支持持久化等待、节点重启、重试、人工任务、超时、版本升级、因果链和 DLQ。事件重放默认不触发外部副作用；外部动作必须经过 `unknown -> reconciling -> confirmed/rejected/manual-resolution`。

## 9. API 和页面最小面

以下是实现边界，不要求一次完成最终 UI。机器可读契约见 `contracts/v1/openapi.v1.json`：

| 能力 | 最小接口/页面 |
| --- | --- |
| 身份和项目 | OIDC callback、组织切换、项目列表、项目上下文 |
| 文件 | 上传初始化/完成、扫描状态、文件版本和证据列表 |
| 命令 | 统一 command submit、幂等键、命令状态和稳定错误码 |
| 工作流 | 当前状态、人工任务、阻断原因、重试/重放入口 |
| 设计 | Requirements、DesignBrief、DesignIntent、概念选择和 G2 审批 |
| 生产 | ProductionBatch、分支状态、输入基线、产物列表和质量门 |
| 结果 | 图纸/图片/BOQ/报价草稿预览、下载令牌、TraceLink |
| 审计 | 按项目/聚合/操作者查询，显示哈希链检查点和证据 |
| 测试 | 仅测试组织可见的故障注入和模拟发布结果 |

长任务统一返回 `workflow_run_id`、`command_id` 或 `job_id`，禁止同步 HTTP 请求等待专业执行完成。

## 10. 数据和环境基线

### 10.1 环境

- `local`：开发和合约测试，使用本地数据库、对象存储仿真和模拟适配器。
- `staging`：集成、故障注入、权限负例、压测和恢复演练；使用独立密钥和数据。
- `production`：MVP 仅允许经过审批的真实脱敏样本，默认关闭真实外部副作用。

### 10.2 最小存储

关系库保存聚合、版本、状态、权限、Outbox/Inbox、工作流、审计摘要和索引；对象存储保存原始/派生文件及不可变证据；隔离审计存储保存完整 `AuditEventV1`、哈希检查点和备份目录。搜索和向量索引不是权威事实，恢复时可重建。

### 10.3 事务边界

命令执行必须在一个业务数据库事务中完成 `CommandRecord + 聚合状态 + 业务事实 + 业务审计摘要 + 幂等索引 + Outbox`。执行器回调先写 Inbox 和结果摘要，再由命令网关生成正式业务事实。任何绕过命令网关的直接表写入都视为严重缺陷。

## 11. 验收与测试矩阵

| 编号 | 场景 | 通过标准 |
| --- | --- | --- |
| E2E-01 | 合成夹具完整跑通 | 从文件到至少两个分支、EX-14、审计和成果包全部可查 |
| E2E-02 | 真实脱敏样本回放 | 与夹具相同的契约和状态，不依赖人工改库 |
| SEC-01 | 跨组织读取/下载/回调 | API、后台任务、对象令牌、搜索和恢复连接全部拒绝 |
| SEC-02 | Agent/Executor 直接写库 | 数据库权限或代码扫描证明无法写入生产聚合 |
| IDEM-01 | 重复命令 | 相同幂等键返回原结果，不新增事实 |
| IDEM-02 | 重复事件/重复执行器回调 | Inbox 去重，版本只推进一次 |
| VER-01 | 旧 Revision 命令 | 明确返回 superseded/version-conflict，不覆盖新基线 |
| FILE-01 | 病毒命中/扫描超时 | 文件停留隔离区，下游不可引用 |
| JOB-01 | 分支超时和重试 | 只重试受影响分支，达到上限创建人工任务 |
| JOB-02 | 质量门失败 | 产物和报告保留，批次不能标记完成 |
| EXT-01 | 发布模拟 unknown | 不盲目重发，进入对账或人工解决 |
| AUD-01 | 审计篡改检测 | 哈希链/checkpoint 检测到修改并告警 |
| REC-01 | 数据库和对象恢复 | 恢复后 Outbox/Inbox 去重，工作流可继续，外部动作不重复 |
| LOAD-01 | 基础压测 | 满足平台文档定义的 P95、队列积压和降级目标 |
| MIG-01 | 契约/工作流升级 | 历史运行可回放或有明确迁移，不丢失因果链 |

### 11.1 首条夹具的断言

首条夹具至少断言：文件 hash 稳定、G2 只由人批准、Manifest 与生产分支的输入版本相同、图纸和 BOQ 均可追踪到对象 ID、EX-14 能发现一个故意制造的不一致、修复后只重跑受影响分支、审计链完整、重复回调不产生第二份正式成果。

## 12. 指标和退出条件

MVP 退出必须同时满足：

- 合约 schema、命令注册表和事件注册表校验通过；
- 至少一套合成夹具和一套真实脱敏样本完成端到端回放；
- 0 个跨租户泄漏，0 个 Agent/Executor 直接业务写入；
- 关键命令、事件和执行器回调的重复测试通过；
- 至少一次超时、质量失败、unknown 和恢复演练通过；
- 每个正式产物都能定位到项目、基线、模型修订、执行器版本、输入规格哈希和验证结果；
- 生产批次完成率、失败原因、人工接管率、分支重跑率、EX-14 阻断率和端到端延迟可查询；
- 技术负责人确认真实 BIM/制图执行器的替换接口和下一阶段容量预算。

真实宁波样本已进入工作区并完成 DWG/PDF/XLS/照片接入、CAD 预处理和范围归组；这些结果允许标记“真实样本首轮回放通过”，但第二 CAD 引擎、专业对象验证、真实数据库、正式消息系统和生产部署未完成，仍不能标记“生产就绪”。

## 13. 实施顺序

### 阶段 A：共同底座

建立项目骨架、配置和迁移、组织/项目/RLS、对象存储隔离、命令网关、审计摘要、Outbox/Inbox、统一错误码和本地可运行环境。

### 阶段 B：资料到 G2

实现上传/扫描/文件版本、需求和 DesignBrief、DesignIntent、人工概念选择、G2 审批和 TraceLink。先用夹具验证状态机，再接真实文件解析。

### 阶段 C：生产批次和两个分支

实现 SpatialProgram、BIM Manifest、ProductionBatch、两个模拟执行器、ExecutorResult 收口、分支重试和产物索引。先跑图纸+BOQ，效果图保持可替换分支。

### 阶段 D：EX-14、故障与恢复

实现 ValidationProfile、交叉检查、异常/人工任务、unknown 对账、DLQ 重放、审计检查点、备份恢复和压测。

### 阶段 E：真实适配器替换

使用脱敏 CAD/BIM/材料表回放，对模拟 BIM、制图、QTO 或渲染适配器逐个替换；每次替换都必须保留同一输入/输出契约、金标准和回滚路径。

## 14. 未决决策和风险

1. 首个真实 BIM 主实现、插件、模板和字体兼容范围仍需技术负责人确认。
2. 默认采用“图纸 + 工程量/报价”作为两条分支；若真实制图执行器准备不足，需明确批准切换为“效果图 + 工程量/报价”。
3. 宁波协诚 CAD、报价原件、PDF 和现场照片已进入工作区；材料表、简单施工计划、群聊/审批、变更单以及另外 3 个完整历史企业空间项目尚未进入，完整业务回放仍存在输入缺口。
4. 工作流产品和云厂商暂不锁定；任何候选实现都必须先通过 `docs/05` 的 WorkflowRuntime、恢复和租户隔离验收。
5. 模拟适配器不能证明专业生产质量，只能证明契约、状态、幂等、审计和故障恢复；专业金标准仍需在第 4、8、9 项完成。

## 15. 第一条可执行夹具

建议提交一个固定目录作为第一个验收样本：

```text
fixtures/vertical-mvp/v1/
  source/site-plan.pdf
  source/site-photo-01.jpg
  source/material-list.csv
  expected/requirements.json
  expected/design-intent.json
  expected/spatial-plan.json
  expected/unified-model-manifest.json
  expected/validation-profile.json
  failures/one-cross-check-mismatch.json
```

夹具不应包含真实个人敏感信息。每个输入和期望结果记录 schema 版本、fixture 版本、sha256 和 deterministic seed；以后真实样本只替换 `source/`，不改变流程和验收断言。

## 16. 当前参考实现映射

第一个可运行骨架位于 `mvp/`，合成夹具位于 `fixtures/vertical-mvp/v1/`：

- `mvp/rkd_mvp/store.py`：内存版项目、聚合、Outbox、Inbox、产物、审计和外部动作边界；
- `mvp/rkd_mvp/gateway.py`：命令幂等、项目上下文和人工审批门；
- `mvp/rkd_mvp/adapters.py`：确定性 BIM、图纸、BOQ、验证和发布模拟适配器；
- `mvp/rkd_mvp/engine.py`：端到端流程、两个成果分支、重复回调和 `unknown` 处理；
- `mvp/rkd_mvp/sqlite_store.py`：本地 SQLite 持久化适配器，用于验证进程重启后的状态恢复；
- `mvp/rkd_mvp/workflow.py`：可恢复的 MVP 状态机，验证状态迁移、非法迁移、重启恢复和租户边界；
- `mvp/rkd_mvp/queue.py`：Outbox 消费、重试、死信和 Inbox 去重参考实现；
- `contracts/v1/openapi.v1.json`：项目、上传、命令、工作流、产物和健康检查 API 契约；
- `mvp/rkd_mvp/api_service.py`、`mvp/rkd_mvp/api_server.py`：本地 HTTP 服务骨架；生产需替换开发身份头为 OIDC/JWT，并接入正式限流、审计和部署拓扑；
- `mvp/rkd_mvp/identity.py`：可替换的身份提供器边界；本地使用开发请求头，生产必须接入 OIDC/JWT 校验；
- `mvp/rkd_mvp/postgres_store.py`：PostgreSQL DB-API 边界，包含 RLS 上下文事务、Outbox lease/claim 和 Inbox 唯一去重；当前只完成适配器协议和静态测试，未连接真实实例；
- `mvp/persistence/postgres/001_vertical_mvp.sql`：组织/项目、命令、聚合、事件、Outbox/Inbox、工作流、执行器、产物、审计和外部动作的 RLS 迁移基线；
- `mvp/rkd_mvp/ports.py`：命令存储、工作流运行时、执行器调度和外部适配器的替换接口；
- `mvp/tests/test_vertical_slice.py`：端到端、跨租户、Agent 审批、重复命令/回调和外部 unknown 测试。
- `mvp/tests/test_persistence_contract.py`：迁移表、唯一约束、RLS、审计只追加、外部 unknown、工作流重启恢复和死信能力的契约测试；
- `mvp/tests/test_api_contract.py`：API 路径、幂等请求头、租户错误语义和禁止直接写库/执行器入口的契约测试。
- `mvp/tests/test_api_service.py`：本地 HTTP、SQLite 重启、API 幂等和开发身份边界测试。
- `mvp/tests/test_postgres_boundary.py`：PostgreSQL 事务回滚、RLS 上下文和 `SKIP LOCKED` 领取协议测试。
- `mvp/rkd_mvp/dxf_intake.py`、`mvp/run_cad_secondary_validation.py`：独立 ASCII DXF 摘要读取和 DWG 摘要差异报告；只用于第二通道复核准备，不创建专业对象或工程量。
- `contracts/v1/cad-secondary-validation.schema.json`：DXF 第二通道结果合同，强制 `promotion_status=not-approved`。
- `mvp/rkd_mvp/gold_standard_intake.py`、`mvp/run_gold_standard_intake.py`：历史项目只读盘点、哈希、查重、候选资料角色、版本关系以及隐私/用途授权登记。
- `contracts/v1/gold-standard-manifest.schema.json`：金标准清单合同；资料接入不自动授予训练或外部模型上传权限。
- `mvp/rkd_mvp/dxf_geometry_review.py`、`mvp/run_cad_secondary_geometry_review.py`：在 DWG 主平面范围内统计 DXF 直接模型实体，执行基础 2D BLOCK/INSERT 基点、缩放、旋转和嵌套展开，并按专业类别与 DWG 候选做差异审查。
- `contracts/v1/cad-secondary-geometry-review.schema.json`：几何级第二通道审查合同，固定创建对象数和可计量对象数为 0。
- `mvp/rkd_mvp/cad_cross_engine_review.py`、`mvp/run_cad_cross_engine_review.py`：使用保留 CAD 句柄逐对象核对 DXF/DWG 图层、类别、实体类型、直接边界和块展开边界。
- `contracts/v1/cad-cross-engine-review.schema.json`：跨引擎逐对象核对合同，保留非交集抽查队列且禁止自动对象升级。

该实现只证明业务边界和契约行为；SQL 是待实例化的 RLS 迁移基线，不宣称已经完成数据库部署、持久化工作流、不可变备份、真实专业软件质量或容量目标。正式技术栈落定后，应保持这些测试断言不变，并把存储、队列和执行器逐层替换。

## 17. 参考实现审查修订

本轮审查针对刚才的 MVP 参考实现和进度口径，发现并修复以下问题：

| 优先级 | 问题 | 修订 |
| --- | --- | --- |
| P0 | 内存项目表只按 `project_id` 索引，不同组织可能覆盖同名项目 | 所有项目索引改为 `(organization_id, project_id)`，并加入同号隔离测试 |
| P0 | 执行器 Inbox 去重键缺少 `project_id` | 去重键改为组织、项目、作业三元组 |
| P0 | 端到端演示绕过 `QueueBIMBuildJob` 等正式命令 | BIM、图纸、BOQ、验证分支先经过已注册命令，再执行模拟器 |
| P0 | PostgreSQL 组织表没有启用 RLS | 增加组织表策略和迁移契约测试 |
| P1 | Inbox 处理失败后没有可表达的处理中/可重试状态 | 增加 `processing`、`retryable`、`processed` 状态，并保留失败原因 |
| P1 | Outbox 只有消费状态，没有显式可靠性审计 | 增加发布、重试和死信审计事件；迁移增加 `dead_letter` 表 |
| P1 | 进度百分比容易被误读为产品完成度 | 台账区分项目交付项、MVP 参考实现和生产就绪度；真实产品仍未宣称完成 |

本轮修订后的本地测试共 16 项通过。仍然明确限制：本地队列没有分布式 claim/租约，SQLite 没有生产级 RLS，模拟执行器不能证明真实图纸质量；这些必须在 PostgreSQL、正式消息系统和真实专业软件接入时重新验收。
