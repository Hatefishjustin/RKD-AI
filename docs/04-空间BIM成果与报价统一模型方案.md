# 自动空间规划、BIM、效果图、施工图和报价统一模型方案

文档状态：V1.0 统一模型架构草案  
编制日期：2026-09-18  
依赖文档：`00-开工前架构预检与扩展性约束.md`、`01-自主设计公司系统V1产品需求规格.md`、`02-完整业务生产链和项目状态机.md`、`03-Agent与专业执行器设计.md`  
适用范围：企业空间首条纵向生产链；宁波协诚资料接入和施工期试点；V1 数据模型、执行器生产包和成果交叉校验

## 1. 目的和结论

本方案规定空间、构件、材料、专业文件、视图、工程量、价格和发布成果如何共享
同一条数字线程。核心结论如下：

1. 系统采用“业务语义层 + 专业原生层 + 交换校验层 + 渲染场景层 + 发布成果层”，不把 IFC、DWG、RVT、场景文件或某个供应商 API 当成全系统事实源。
2. 业务语义层维护稳定内部 ID、对象关系、规格、状态、基线和 TraceLink；专业文件负责其擅长的几何、参数和制图表达。
3. 每个下游结果绑定同一个 `BaselineSet`、输入修订、规则版本和生产包；结果不能仅凭“最新文件”继续生产。
4. 量由经过验证的模型和确定性计量规则产生，价格由版本化价格快照和公式产生，合同、发票、付款和实际成本由财务事实模块独立维护。
5. 转换允许有损，但损失必须被记录、量化并在质量门中处理；不能用“文件成功导出”代替“业务语义保持”。

## 2. 非目标

V1 不试图创建一个覆盖所有专业的万能 BIM 平台，也不在第一阶段完成结构、机电、消防、景观、全屋住宅、复杂曲面和完整竣工运维模型。新专业通过能力包和适配器增加，不修改既有核心对象含义。

## 3. 统一模型分层

| 层 | 事实/职责 | 典型对象或文件 | 可否直接决定业务效力 |
| --- | --- | --- | --- |
| 业务语义层 | 稳定对象身份、关系、规格、状态、基线和约束 | `SpatialUnit`、`Element`、`Assembly`、`MaterialSpec`、`DesignIntent` | 是 |
| 专业原生层 | 专业软件可编辑几何、参数、族/块、视图和制图源 | RVT/DWG/3DM/原生场景文件 | 只对声明的专业表示负责 |
| 交换校验层 | 跨软件交换、对象映射、几何和属性校验 | IFC、glTF、JSON manifest、检查报告 | 否，可作为验证证据 |
| 渲染场景层 | 材质实例、灯光、相机、UV、后期和渲染参数 | 场景文件、资产映射、渲染配置 | 否，可产生候选/发布成果 |
| 图纸表达层 | 视图、图签、标注、详图、索引和修订 | DWG/PDF/图纸数据集 | 发布后形成成果记录 |
| 商务派生层 | 工程量、价格、报价、合同引用和经营指标 | BOQ、Quote、ContractLine、报表 | 由归属业务模块确认 |
| 发布成果层 | 某个批准版本向指定接收人传递的不可变包 | Transmittal、交付包、归档包 | 是发布事实，不反向改源对象 |

### 3.1 写入边界

- 语义层只能由归属模块通过公开命令写入；Agent 和执行器不能直接写业务数据库。
- 专业执行器只能读取作业输入并写入作业暂存区，结果通过 `ExecutorResultV1` 回传。
- 交换模型和渲染场景是可重建表示，不能覆盖语义对象的状态、规格或基线。
- 图纸上的手工标注只能产生“表达修订”或“问题/变更建议”；若影响尺寸、构件或工程量，必须回到语义层或专业源模型。
- BOQ、报价和财务对象只能引用模型和规则，不能反向修改几何。

## 4. 规范化对象图

V1 的最小可追踪链如下，箭头表示版本化引用而不是数据库级联覆盖：

```text
Requirement / Constraint
        -> DesignIntent
        -> SpatialProgram / SpatialUnit
        -> Element / Assembly
        -> MaterialSpec / Product
        -> ModelObject / ModelRevision
        -> ViewSpec / DrawingView / RenderView
        -> QuantityItem
        -> CostItem / QuoteLine
        -> ContractLine / PurchaseLine
        -> Receipt / Allocation / CostEntry
```

每条关系同时保存 `TraceLink`，其中至少记录来源修订、目标修订、关系类型、方向、来源、有效期和状态。一个对象可以关联多个表示，一个工程量或报价项也可以来自多个模型对象；不得用一对一假设简化真实工程。

## 5. 公共对象约束

所有可追踪对象至少具备：

```text
object_id: immutable UUID
object_type: registry key
revision_id: immutable UUID
aggregate_version: monotonic integer
project_id / organization_id
state / state_reason
source_refs[]: evidence and upstream revisions
classification_refs[]
unit_context / coordinate_context
created_at / created_by / updated_at / updated_by
rule_set_version / capability_pack_version
```

### 5.1 身份和分类

1. `object_id` 代表业务身份；`revision_id` 代表不可变内容快照；软件内部 ID、IFC GUID、CAD Handle、SKU 和文件路径只能进入 `ExternalReference`。
2. 对象替代不改变 `object_id`，除非业务事实确实是新对象；软件重建对象时使用外部映射和人工确认。
3. 分类必须使用能力包注册的稳定编码，保存分类体系和版本；不允许把中文名称作为唯一匹配键。
4. 实例与类型分开：`ElementType`/`Product` 描述可复用定义，`Element`/`ModelObject` 描述项目实例。
5. 关系删除采用 `superseded` 或 `invalidated`，不物理删除已经进入基线、发布、采购或财务的历史关系。

## 6. 核心语义对象

### 6.1 SpatialUnit 与空间程序

`SpatialUnit` 是可用于空间规划、面积核算、模型定位、图纸索引和施工位置的语义空间。其 `kind` 至少包括 `site`、`building`、`floor`、`zone`、`room`、`circulation`、`service-area` 和 `temporary-area`。

必备字段：

```text
unit_id / parent_unit_id / kind
name / code / occupancy_or_function
boundary_reference / geometry_status
design_area_basis / measurement_area_basis / chargeable_area_basis
adjacency_refs[] / access_constraints[] / environmental_targets[]
spatial_program_revision / design_intent_revision
```

面积口径必须独立保存。例如设计面积和计价面积不能覆盖成一个数；每个面积值必须带单位、计算规则、来源、日期和用途。

### 6.2 Element、Assembly 和系统关系

`Element` 表示项目中可定位、可验证或可计量的构件实例；`Assembly` 表示由多个构件、做法和工序组成的施工或产品组合。

核心字段：

```text
element_id / element_kind / host_space_id
assembly_id / system_id / type_id
semantic_geometry_ref / model_object_refs[]
material_spec_refs[] / required_properties{}
construction_method_ref / quantity_rule_ref
status / validation_state / approved_baseline_ref
```

典型 `element_kind` 包括墙体、隔断、门、窗、地面、天花、固定家具、活动家具、灯具、设备、饰面、标识和临时设施。新增类型通过分类注册表和能力包加入，不在代码中散落类型判断。

### 6.3 DesignIntent、MaterialSpec 和 Product

- `DesignIntent` 描述方向、氛围、色彩、材料倾向、品牌体验、维护要求、预算等级和禁用项；它在 G2 前批准并进入 `BaselineSet`，但不是材料采购事实。
- `MaterialSpec` 描述项目要求的性能、外观、做法、尺寸、安装、验收、替代策略和证据；它可以引用多个候选产品。
- `Product` 描述供应商、制造商、SKU、价格/交期快照、认证和采购可用性；产品变更不能静默改变 `MaterialSpec`。

```text
DesignIntent -> MaterialSpec -> ProductCandidate -> ApprovedProduct -> PurchaseLine
```

材质颜色、纹理和效果图资产必须分别记录“概念参考”“设计规格”“批准产品”“渲染资产”四种来源状态，避免参考图被误当作可采购产品。

### 6.4 ViewSpec、DrawingView 和 RenderView

`ViewSpec` 是视图意图和约束的语义对象；`DrawingView` 和 `RenderView` 是其专业表示。

必备字段：用途、观察位置/方向、裁剪范围、目标对象集、比例或分辨率、隐藏/显示规则、来源模型修订、视图模板版本、接收用途和质量门。

同一空间可以有多个图纸视图和渲染视角。视图不拥有构件几何；视图只引用模型对象并保存表达参数。

### 6.5 QuantityItem、CostItem 和 QuoteLine

- `QuantityItem` 保存对象集合、计量规则、单位、公式、精度、损耗、取整、人工补充标志和计算结果。
- `CostItem` 保存成本分类、来源、价格快照、税、币种、期间、承诺/实际状态和证据。
- `QuoteLine` 保存面向客户的范围、单位、数量、单价、税、折扣、排除项和报价版本。

工程量和金额的最小追踪链必须是：

```text
ModelObject revision
  -> QuantityRule version
  -> QuantityItem revision
  -> PriceSnapshot / Formula version
  -> CostItem / QuoteLine revision
  -> approved Quote / ContractLine
```

任何无法回到模型对象、人工补充证据或确定性规则的数量必须标记 `manual` 或 `unresolved`，不得默认零值或伪造精确度。

## 7. 权威方向矩阵

| 信息类别 | 权威对象/层 | 允许派生到 | 禁止反向覆盖 |
| --- | --- | --- | --- |
| 客户目标、硬约束、验收指标 | Requirement/Constraint/DesignBrief | SpatialProgram、DesignIntent、检查规则 | 模型和报价 |
| 品牌、氛围、色彩、材料方向 | DesignIntent | MaterialSpec 草案、渲染场景 | 已批准产品、合同 |
| 空间边界、功能、邻接、面积口径 | SpatialUnit/SpatialProgram | BIM 空间、图纸索引、QTO 范围 | 渲染图片、图纸手工线 |
| 构件语义身份、类型、系统、做法 | Element/Assembly | BIM 原生对象、图纸、QTO | DWG/PDF 线条、渲染对象 |
| 精确几何、参数、族/块和专业属性 | BIM/CAD 原生修订 | IFC、渲染场景、图纸、QTO | 预览图、PDF 标注 |
| 跨软件交换和验证属性 | IFC/交换模型/验证报告 | 目标软件输入、质量报告 | 业务批准状态 |
| 材质、灯光、相机和后期 | RenderScene/RenderView | 渲染图片、预览 | BIM 几何和产品规格 |
| 图纸视图、标注、图签和索引 | DrawingSet + drawing rules | DWG/PDF、发布包 | 模型几何和空间面积 |
| 工程量 | QuantityItem + validated model | BOQ、报价、成本预测 | 模型几何和合同事实 |
| 单价、税、利润、付款 | PriceSnapshot/Formula/Finance facts | Quote、Contract、经营看板 | 模型和工程量 |
| 发布状态和接收记录 | Artifact/Transmittal | 外部门户、归档 | 源对象版本 |

当两个来源冲突时，按矩阵停在 `conflicted` 或 `needs-human`，不能按时间戳选择“最新”作为权威。

## 8. 坐标、单位、精度和详细程度

### 8.1 坐标上下文

每个模型修订和交换包保存：坐标系、原点、项目基点、旋转、单位、楼层基准、精度、转换矩阵、来源软件、目标软件和转换日志。不得通过文件名或人工约定猜坐标。

坐标转换必须产生可审计的 `CoordinateTransform` 记录；转换后抽样检查已知控制点、楼层标高、轴网、门窗和边界。控制点误差超出项目能力包阈值时，模型进入 `correction-required`。

### 8.2 单位和精度

业务存储使用明确单位和高精度数值；展示、图纸和报价分别使用格式化规则。面积、长度、角度、数量、金额和百分比不能共用一个无单位数值字段。舍入只在规定的计算边界发生，并记录舍入规则版本。

### 8.3 LOD 与 LOI

V1 使用可扩展的级别，不把软件版本名称当作等级：

| 级别 | 语义要求 | 允许用途 | 不能声称 |
| --- | --- | --- | --- |
| L0 | 概念区域和方向 | 需求讨论、概念参考 | 可施工、可计量 |
| L1 | 空间边界、功能和面积 | 空间规划、候选比较 | 构造和精确工程量 |
| L2 | 主要构件、类型、材料意图和协调几何 | 模型协调、初步 QTO、效果图 | 完整施工节点 |
| L3 | 可施工构件、做法、参数、图纸引用和检查属性 | 施工图、正式 QTO、报价 | 竣工实测事实 |
| L4 | 已施工/实测、收货、变更和验收证据 | 竣工与保修 | 未经证据确认的现状 |

LOI 另外记录需要的属性完整度。几何通过不代表信息完整；属性缺失、未检查和估算必须分别显示。

## 9. 专业表示和转换契约

每次转换形成不可变 `RepresentationRun`：

```text
run_id / source_revision_ids[] / target_representation
source_software / target_software
source_bundle_digest / target_bundle_digest
coordinate_context / unit_context
mapping_profile_version / conversion_parameters_hash
created_artifact_ids[] / dropped_fields[] / warnings[]
validation_profile / validation_result
```

生产批次使用 `contracts/v1/unified-model-manifest.schema.json` 生成
`UnifiedModelManifestV1`。清单绑定语义模型、专业表示、坐标/单位、对象映射、转换损失和覆盖率，
是 EX-14 交叉检查及后续 API 的稳定输入；它不取代任何专业原生文件。

### 9.1 转换规则

1. 转换前先锁定输入修订和能力版本；转换过程中不读取“当前最新”对象。
2. 映射分为一对一、一对多、多对一、未映射和冲突五类；多对一必须保存合并理由和来源集合。
3. 丢失字段、近似几何、未支持对象和单位转换误差必须进入报告；任何严重丢失阻断下游正式发布。
4. 交换文件可被重建，原生文件和业务语义对象不被交换文件覆盖。
5. 只有目标表示通过对应 `ValidationProfile`，才允许进入下一生产阶段。

## 10. 生产批次和统一输出矩阵

每次从批准模型生产正式成果都创建 `ProductionBatch`，绑定：G2/G3/G4 相关基线、模型修订、DesignIntent、规则和能力包、输入清单、输出清单、质量门、成本预算、负责人和截止时间。

| 分支 | 输入基线 | 主要执行器 | 最小输出 | 进入下一步的条件 |
| --- | --- | --- | --- | --- |
| BIM/模型 | G2 + SpatialPlan + SiteDataset | EX-04/05 | 业务语义模型、原生模型、交换模型、对象映射 | 单位/坐标、对象稳定性、几何和属性检查通过 |
| 效果图 | 已验证模型 + DesignIntent | EX-06/07/14 | 场景、相机、材质映射、图片和差异报告 | 主要几何一致、资产来源完整、渲染质量通过 |
| 施工图 | 已验证模型 + 图纸规则 | EX-08/09/14 | 图纸集、索引、检查报告、G4 包 | 视图/引用/标注/图模检查通过 |
| BOQ | 已验证模型 + 做法 + 计量规则 | EX-10 | 数量行、公式、来源对象、异常 | 来源覆盖、单位和汇总勾稽通过 |
| 报价 | 冻结 BOQ + 价格快照 + 公式 | EX-11/14 | 客户报价、内部成本、风险和 G3 包 | 金额/税/舍入/范围和量价关系通过 |

生产批次允许分支独立重试，但交叉检查只针对同一基线和兼容输入。分支输出为空、版本不匹配或输入缺失时，批次保持 `partially-complete` 或 `correction-required`，不能用空结果通过。

## 11. 各专业生产边界

### 11.1 空间规划

- 输入：G2 基线中的 DesignIntent、SiteDataset、SpatialProgram、ConstraintSet、优化目标。
- 输出：候选 `SpatialOption`、指标、违规、冲突集、选择理由和 `SpatialPlan`。
- 约束求解器负责硬约束和确定性指标；Agent 负责组织输入、解释结果和生成任务，不直接画正式平面。
- 方案候选保留为分支；只有 `approved-for-model` 才能进入 BIM。

### 11.2 BIM/参数化模型

- 语义层先创建或更新 `SpatialUnit`、`Element`、`Assembly` 和 `MaterialSpec` 修订，再由 EX-04 生成专业文件。
- 原生对象与业务对象通过 `ExternalReference` 和映射记录关联；不确定匹配必须人工确认。
- EX-05 负责几何闭合、碰撞、净高、属性、分类、可计量性和规则覆盖检查。
- BIM 变更形成 `ChangeSet`，不会静默修改已批准基线。

### 11.3 效果图

- 场景文件只保存几何同步、材质实例、灯光、相机、色彩管理和后期记录。
- 材质参考和实际产品分开；渲染资产必须有来源、许可、版本和绑定对象。
- 主要固定构件、开口、空间边界和视角裁切与模型做几何一致性比较。
- 仅改变灯光、相机或后期时不重跑 QTO；改变绑定模型或固定材质规格时按影响图重跑。

### 11.4 施工图

- 图纸以模型和图纸规则生成视图、标注、图签、索引和详图；人工表达修订必须有来源和适用范围。
- 关键尺寸、标高、门窗编号、材料编号和工程量引用必须能回到语义对象或规则。
- 图纸发布前检查模型版本、字体、外部引用、视图非空、索引和接收用途；图纸不能绕过 G4。

### 11.5 工程量和报价

- EX-10 只读取已验证模型和版本化 `QuantityRule`，输出每行来源对象集合和公式。
- 人工补充量必须有 `ManualQuantityEvidence`、责任人、原因、适用范围和过期时间。
- EX-11 只读取冻结 BOQ、价格快照、公式、税和付款规则；模型变化不得直接修改已发布报价，必须创建变更影响。
- 报价、合同、采购承诺、发票、付款和实际成本保持独立事实，经营看板通过 TraceLink 汇总。

## 12. 变更影响和重生产矩阵

| 变更类型 | 必须失效/重算 | 可以保留 | 必须人工确认 |
| --- | --- | --- | --- |
| 空间边界、面积、邻接 | BIM、图纸、效果图、QTO、报价 | 与空间无关的采购/财务事实 | 对已发布/已施工影响 |
| 固定构件几何或位置 | BIM、图纸、效果图、QTO、报价 | 仅引用不受影响对象的成果 | 图纸发布、施工和合同范围 |
| 构造做法或 MaterialSpec | BIM 属性、图纸、QTO、报价、相关效果图 | 不绑定该规格的视图 | 替代产品和合同/采购影响 |
| 仅渲染灯光/相机 | 相关渲染分支 | BIM、图纸、QTO、报价 | 正式视觉发布人 |
| 图纸模板/标注规则 | 受影响图纸和 G4 包 | 模型、QTO、报价 | 已发布图纸是否撤回 |
| 计量规则/单位 | QTO、报价、受影响成本视图 | 模型几何 | 已冻结/已发布金额 |
| 价格快照/税/利润公式 | 报价、经营预测 | 模型、图纸、已核验实际成本 | 已接受报价和合同变更 |
| 合同/付款条件 | 合同、发票、现金预测和对账策略 | 模型、图纸、已确认工程量 | 业务责任人/法务/财务 |

影响引擎必须同时查看 `TraceLink`、已发布成果、采购/施工事实和不可逆动作。无法判断不能默认为不受影响。

## 13. 统一质量指标

所有指标引用 [ValidationProfileV1](../contracts/v1/validation-profile.schema.json)，并显示分母、范围、版本、阈值、容差和阻断级别。

| 指标 | 定义 | 最低要求 |
| --- | --- | --- |
| 语义映射覆盖率 | 有效业务对象中有稳定专业表示的比例 | 按专业能力包设置阈值，严重对象不得遗漏 |
| 几何一致性 | 绑定对象边界、数量和控制点在容差内的比例 | 低于阈值阻断正式成果 |
| 属性完整度 | 必填 LOI 属性已填且来源有效的比例 | 未检查不计为通过 |
| 图模引用覆盖率 | 关键图纸尺寸/编号/引用可回到模型或规则的比例 | 关键项必须 100% 或有批准例外 |
| QTO 来源覆盖率 | 数量行可回到模型对象或人工证据的比例 | 未解析/未计量单独列出 |
| 量价勾稽率 | 报价行数量与冻结 BOQ 的一致程度 | 差异必须形成异常或变更 |
| 版本兼容率 | 生产包内输入均来自同一基线或批准兼容版本的比例 | 低于 100% 不得发布 |

## 14. 扩展和兼容策略

1. 新项目类型只增加能力包、分类、规则、模板和验证配置；核心对象含义不变。
2. 新 CAD/BIM/渲染软件通过 `ExecutorCapability` 和转换适配器接入，不能在业务 Agent 中写供应商分支。
3. 新对象字段先进入命名空间扩展 JSON；当字段进入公式、权限、工作流或质量门时提升为正式字段。
4. 对象、命令、事件和表示契约采用主版本；破坏性变化创建新主版本和迁移器，保留旧版本读能力。
5. 适配器必须提供输入/输出格式、单位、坐标、对象映射、已知损失、许可证、区域、金标准成绩和回滚版本。
6. 所有转换和派生成果可删除重建；只有业务事实、批准、发布、采购、施工、财务和审计记录不可重建覆盖。

## 15. V1 最小闭环

首个纵向 MVP 不追求覆盖全部构件，建议固定以下边界：

- 一个企业空间项目、一层或一个主要区域；
- 空间边界、墙/隔断、门、窗、地面、天花、固定家具、灯具和主要设备；
- 一个批准 DesignIntent、一个 SpatialPlan、一个 BIM 原生表示和一个交换校验表示；
- 三个渲染视角、一套核心平面/立面图纸、一个可追溯 BOQ 和一版内部/客户报价；
- 变更一项固定构件后，能标记受影响图纸、效果图、工程量和报价；
- 至少验证一个人工补充量、一个材料替代、一个图纸撤回和一个采购对账场景。

暂不纳入 MVP：完整 MEP/结构协调、复杂自由曲面、自动生成所有施工节点、自动批准产品替代、自动付款和未经确认的竣工现状。

## 16. 封板条件和未决决策

### 16.1 封板条件

- [ ] 项目能力包确认空间/构件/材料分类、编码、单位和面积口径。
- [ ] BIM/CAD 责任人确认原生文件、交换文件和语义对象的权威方向。
- [ ] 渲染负责人确认资产、材质、色彩管理、相机和几何容差。
- [ ] 施工图负责人确认图纸目录、图签、标注、字体、外部引用和 G4 清单。
- [ ] 商务/财务确认计量规则、损耗/取整、价格快照、税、利润和付款口径。
- [ ] 技术负责人确认至少一套 `ValidationProfileV1` 和金标准对象映射。
- [ ] 用真实 CAD/BIM/材料/报价样本完成一次输入到成果的回放，记录所有丢失字段和人工接管点。

### 16.2 当前未决决策

1. V1 原生 BIM 主实现选择及其插件/模板/字体兼容范围。
2. 企业空间常用构件、材料和做法的第一版分类编码。
3. 设计面积、计价面积、施工面积和租赁面积的正式口径。
4. QTO 中人工补充项的审批角色、过期规则和与合同的关系。
5. 图纸与模型对象的最低映射覆盖率和允许例外。
6. 渲染几何一致性的控制对象、容差和正式图片后期边界。

## 17. 验收测试矩阵

| 编号 | 场景 | 预期结果 |
| --- | --- | --- |
| UM-01 | 同一墙体在 BIM 中重建外部 ID | 通过映射保留业务对象，不静默新建重复对象 |
| UM-02 | G2 后修改 DesignIntent | 原生产批次不覆盖；生成变更影响和重新批准任务 |
| UM-03 | 交换文件丢失材料性能字段 | 转换报告列出丢失，正式 QTO/发布被阻断 |
| UM-04 | 渲染相机变化 | 只重跑受影响渲染视角，不重跑图纸和 BOQ |
| UM-05 | 固定家具尺寸变化 | 标记图纸、渲染、QTO、报价为 stale 或待影响分析 |
| UM-06 | 人工补充工程量无凭证 | BOQ 可显示缺失，但不能进入冻结报价 |
| UM-07 | 价格快照过期 | 报价进入 correction-required 或 expired，不修改模型 |
| UM-08 | 图纸手工标注与模型冲突 | 生成图模异常，不能以 PDF 标注覆盖模型事实 |
| UM-09 | 同一基线生产多个分支 | 交叉检查按基线和版本配对，不混用最新成果 |
| UM-10 | 新软件适配器接入 | 通过能力、映射、转换损失和金标准后才允许生产 |
