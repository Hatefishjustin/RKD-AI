# 首批复核包 · 证据时间与契约映射勘误记录（W0 / R3）

性质：**独立勘误记录**，不是对上一批交付包的修订版，也不替代唯一动态状态表 `PROJECT_STATUS.md`。
依据：`docs/26-持续制作路线与周期复核计划.md` 第 2 节 R3、第 6 节。
适用：架构师复核 W0 时核对证据来源与 W1 统一模型适配前的字段口径。

**本文件不修改、不覆盖、不回写任何历史证据。** 原有
`deliverables-for-review/arc-first-batch/` 与 `var/evidence/architecture-handoff/first-batch/`
下所有文件保持原始字节；下方记录其 SHA-256 供复核时比对。

## 1. 时间轴：编制 / 执行 / 复跑补生成 / 提交分开标明

复核包 `review-packet.md` 头部写「日期：2026-11-12」，而 `checks.json` / `q-checks.json`
内含 `2026-11-14` 的生成时间。这是**两类不同事件**，不是证据造假，也不应混用日期：
11-12 是复核包的编制日与当日执行，11-14 是架构师复核当日重新生成 Q 清单/检查汇总并提交补丁。

| 事件类别 | 实际时间（带时区） | 对应代码基线 | 证据文件 / 来源 |
| --- | --- | --- | --- |
| 审查基线提交 | 2026-11-11T22:48:29+08:00 | `d6501a9` | `git log -1 d6501a9` |
| 复核包**编制**日期 | 2026-11-12（日内时间未记录，不推断） | 审查基线 `d6501a9` | `arc-first-batch/review-packet.md` 头部「日期」 |
| 整改前复现**执行** | 2026-11-12T23:02:01+08:00 | `d6501a9` | `before-reproduction.json` → `generated_at` |
| 浏览器验收**执行** | 2026-11-12T15:47:39.778763+00:00（= 23:47:39+08:00） | 整改工作区 | `browser-verification.json` → `checked_at`（UTC，注意换算是北京时间同日） |
| 整改后复现**执行** | 2026-11-12T23:48:30+08:00 | 整改工作区 | `after-reproduction.json` → `generated_at` |
| Q 清单 / 检查汇总**复跑补生成** | 2026-11-14T11:21:18、11:21:20+08:00 | 已完成的整改代码（尚未提交） | `q-checks.json`、`checks.json` → `generated_at` |
| 主体实现**提交** | 2026-11-14T11:26:18+08:00 | `eb6513c` | `git log -1 eb6513c` |
| 复核包标注**提交** | 2026-11-14T11:26:47+08:00 | `957cf77` | `git log -1 957cf77` |
| W0 整改前复现**执行** | 2026-11-14T11:53:38+08:00 | `957cf77` | `var/evidence/roadmap/W0-收口/before/reproduction.json` |

口径说明（**不得混用**）：

1. `checks.json` 的 `baseline` 字段是**审查基线** `d6501a9`，不是该文件生成时的 HEAD，
   也不是本批实现提交号。三者分别写：`d6501a9`（审查基线）/ `eb6513c`（实现提交）/
   `957cf77`（复核包标注提交）。
2. 11-12 的执行证据保留 11-12 的时间；11-14 的补生成与提交保留 11-14 的时间。
   不把 11-14 的事件倒填进 11-12 的编制日期，也不因日期差异推断 11-12 的证据无效。
3. `browser-verification.json` 的 `checked_at` 使用 UTC，换算成北京时间是同日 23:47，
   与 `after-reproduction.json` 的 23:48 相邻，不构成时间倒序矛盾。
4. 本 W0 复核包中所有 `generated_at` / `checked_at` / `committed_at` 一律带时区，
   并同时记录**执行时间**与**源码基线**，避免再次出现"一份文件只有一个笼统日期"。

### 历史证据字节（只读，未改动）

| 文件 | 字节数 | SHA-256（文件原始字节） |
| --- | --- | --- |
| `arc-first-batch/review-packet.md` | 17814 | `8ac87bd723818054f71c1b00adbab43a7777370e7ce8da87458e9791c046ca21` |
| `arc-first-batch/ARC-05-adaptation-note.md` | 6193 | `cc451e8bd6c0e078da5732db6d963cf318d1229433e5b439a2aec3d62e95d451` |

> `w0_repro.py` 记录的 `historical_packet_sha256` 是按 `read_text()` 后的 UTF-8 文本计算，
> 与上表按原始字节计算的口径不同；两者不互相替代，复核时按原始字节 SHA 为准。

## 2. 契约映射修正：按实际三份 schema，不按字段名拼接

`ARC-05-adaptation-note.md` 第 2 节第 1 行原文：

```
| `contract_version` / `project_id` | `rkd-spatial-plan.v1` / 与主系统项目 ID 显式映射（`source_project_id`） | `ai-design-option` 的 `schema_version` / `project_id` | 映射必须显式记录，不从名称推断；跨项目引用拒绝 |
```

这行把**三份契约的字段混在一起**，W0 实测（`w0_repro.py` R3-b）确认：

| 实测项 | 结果 |
| --- | --- |
| `spatial-plan-proposal.schema.json` 是否含 `contract_version` | **false** |
| `spatial-plan-proposal.schema.json` 是否含 `project_id` | **false** |
| `spatial-plan-draft.schema.json` 的 `contract_version` 常量 | `rkd-spatial-plan.v1` |
| `spatial-plan-draft.schema.json` 是否含 `project_id` | true |
| `ai-design-option.schema.json` 的 `schema_version` 常量 | `rkd-ai-design-option.v1` |
| `ai-design-option.schema.json` 是否含 `project_id` | **false** |
| `ai-design-option.schema.json` 的 `additionalProperties` | false |

### 2.1 三份契约的真实边界

| 契约 | 责任主体 | 版本键 | 身份字段 | 备注 |
| --- | --- | --- | --- | --- |
| `spatial-plan-proposal.v1` | **模型提案**（Studio） | 无版本键（靠 `$id` 与文件版本） | **无**：不含 `contract_version` / `project_id` / `option_id` / `revision` / `parent_revision` / `author`，也不含批准/采用字段 | `additionalProperties:false`；required = strategy, zones, circulation, furniture, area_table, open_questions |
| `spatial-plan-draft.v1` | **程序装配后的完整交接文档**（Studio） | `contract_version` = const `rkd-spatial-plan.v1` | 有 `project_id`、`option_id`、`revision`（int）、可选 `parent_revision`（int 或 null）、`author` | 身份由 `validation.validate_proposal()` 在四级校验通过后注入，模型不得决定 |
| `ai-design-option.v1` | **主系统候选模型** | `schema_version` = const `rkd-ai-design-option.v1` | 有 `set_id`、`option_id`、`revision_no`（int）、`parent_revision_id`（string 或 null）；**没有 `project_id`，也没有 `contract_version`** | `additionalProperties:false`；项目归属由仓储键/表列承载，不是文档字段 |

### 2.2 原文的四处表述混用（勘误，不改原文件）

1. 把 `contract_version` / `project_id` 写成「Studio 提案字段」——它们只存在于 **draft** 文档，proposal 契约根本没有。
2. 把 `rkd-spatial-plan.v1` 当成 proposal 的版本值——该常量属于 draft 契约的 `contract_version`。
3. 把 `project_id` 写成 `ai-design-option` 的落点字段——该契约 `additionalProperties:false` 且无此字段，直接写入会因 schema 校验失败。
4. 把 `schema_version` 与 `contract_version`、`revision` 与 `revision_no`、
   `parent_revision` 与 `parent_revision_id` 当成可直接对应的同义字段——实际类型与语义不同
   （`parent_revision` 是 int 版本号，`parent_revision_id` 是字符串 ID）。

### 2.3 修正后的映射草案（供 W1 实施前核对，W0 不实现适配）

| Studio 提案字段 | 程序装配后的 draft 字段 | 主系统落点 | 适配损失 / 处理 |
| --- | --- | --- | --- |
| （无身份字段） | `contract_version`=`rkd-spatial-plan.v1` | `schema_version`=`rkd-ai-design-option.v1` | 两套版本键并存，映射必须显式且带版本，不得互相覆盖 |
| （无身份字段） | `project_id`（Studio 内部 id） | **无同名字段**；用 `set_id` + 仓储项目键 + `source_project_id` 显式映射 | 跨项目引用拒绝；不得把 `project_id` 塞进 `ai-design-option` 文档 |
| （无身份字段） | `option_id`（`^[A-Z]$`） | `option_id`（任意非空字符串） | 候选组归属用 `set_id` 表达，不能只靠 A/B 字母 |
| （无身份字段） | `revision`（int） / `parent_revision`（int\|null） | `revision_no`（int） / `parent_revision_id`（string\|null） | int 版本号与字符串版本 ID 的转换必须留痕，不能静默丢弃 |
| `strategy.{name,narrative,tradeoffs}` | 同名 | `strategy.{strategy_id,statement,tradeoffs,source_refs}` | `source_refs` 需真实来源 ID，不能补造 |
| `zones[].{id,role,polygon,area_sqm}` | 同名 | `objects[]`（shape 目前**只支持 `rect`**） | 多边形→矩形会丢几何精度，必须标 `unsupported` 或扩展 shape，不得离散后宣称精确 |
| `circulation[].{id,width_mm,path}` | 同名 | `circulation.{path_id,kind,min_width,segments,connections}` | mm 与米/单位换算、折线段映射需显式；净宽须由几何复算 |
| `ceiling.{coves,fixtures}` | 同名 | 主系统当前无天花/灯具对象 | 标 `unknown` / 待扩展，不得静默丢弃或据草案缩略图未画推断数据缺失 |
| `furniture[].{catalog_id,x,y,rot}` | 同名 | `objects[]` + 目录引用 | 尺寸取目录实际 w_mm/d_mm，旋转占地用 shapely 复算 |
| `area_table` | 同名 | `cost` / 面积摘要 | 由程序按「可布置范围 = 外框 − 保留区」复算，不采信模型合计 |
| `open_questions` / `standards_cited` | 同名 | 缺口与依据引用 | unknown 不填 0；引用编号必须存在于规范库 |

W1 实施前必须以本表与三份 schema 的实际内容为准；若发现进一步冲突，追加勘误，
不回写 Studio 提案契约，也不放宽 `additionalProperties` 或必填项。

## 3. 本勘误明确未做的事

- 未修改 `arc-first-batch/` 下任何历史证据或适配说明的字节；
- 未把 11-14 的事件倒填为 11-12，也未把 11-12 的证据重跑覆盖；
- 未实现 Studio → 主系统写入适配器、未生成效果图或任何设计成果（W1 范围）；
- 未改变 AD01—AD08 结论，未代替用户确认任何设计阶段。
