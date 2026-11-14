# W1 版本谱系与来源映射（W1-R1 / W1-R2 收口）

依据：`W1-architect-review/architect-review.md` §W1-R1、§W1-R2 与"W2 衔接约束"。
本文件补充 `W1-统一模型适配/contract-mapping.md`，只说明**这次改动的身份/父链/来源口径**。

## 1. 候选身份：从"字母 + 导入顺序"改为"源根谱系"

| 项 | 旧（W1 首版，已修） | 新 |
| --- | --- | --- |
| `option_id` | `studio:{main}:{studio}:{A\|B}` | `studio:{main}:{studio}:root:{root_revision_uid}` |
| 根谱系解析 | 无 | `StudioProposalSource.lineage()` 沿 `parent_revision_uid` 回溯到无父的源修订 |
| A/B 字母 | 当成候选身份 | 只作为显示名（`strategy.statement`、`spatial.source.option_id`） |
| 独立两组 A | 被当成同一候选的 v1→v2 | 两个不同根 → 两个候选，各自 v1、parent=null |
| 分叉（同父两子） | 第二个分叉接在第一个后面 | 两个分叉的 `parent_revision_id` 都指向父版本的主系统修订，彼此不是父子 |
| 乱序（先导入子） | 旧稿被接到新稿后面 | 父未导入 → 409 `SOURCE_PARENT_NOT_IMPORTED`；补齐父后再导入，链正确 |
| 源父 UID 在 Studio 不存在 | 被当作根 | 409 `SOURCE_PARENT_MISSING`，不猜谱系 |
| 建环 | 不检测 | 409 `SOURCE_LINEAGE_CYCLE` |

**主系统 `revision_no` 与源父链的关系**：`revision_no` 是主系统内该候选的单调修订号（受
`UNIQUE(option_id, revision_no)` 约束）；`parent_revision_id` 来自**源 UID 映射**。
分叉时两条修订可能共享同一个父，`revision_no` 仍连续递增（2、3），这是 DAG 上的两个分支，
不是"父子串联"。

## 2. 父 UID → 主系统修订 ID 的显式映射

不新增表：映射由已导入修订的 `model.spatial.source.revision_uid` 建立，写在**同一个事务里**
重读。逻辑（`AIDesignOptionService._lineage_state`）：

```text
for revision in revisions_for_option(option_id):
    source_uid = revision.model.spatial.source.revision_uid
    by_source[source_uid] = revision
parent = by_source[source_parent_uid] if source_parent_uid else None
parent_missing = bool(source_parent_uid) and parent is None
next_revision_no = max(revision_no) + 1
```

- 同一来源重复导入：`set_by_key(studio-import:...)` 命中 → `reused=true`，不造版本。
- 缺父默认拒绝；只有显式 `allow_orphan=true` 才导入，且：
  `parent_revision_id = null`、`spatial.source.parent_link_status = "source_parent_not_imported"`、
  `root_revision_uid` 仍是源根。**不伪造父关系，也不事后回填**。
- `diff` 对比的是**源父修订**的 `spatial`（不是"上一条导入的记录"），所以分叉的 diff 相对共同父版本。

## 3. 写事务内重检（W1-R2）

旧流程：读事务算 `latest` / `revision_no` / 幂等 → 生成 SVG → 写事务直接 insert。
并发时两个请求可能都基于相同旧版本，产生重复版本号或原始唯一约束异常。

新流程：写事务（SQLite `BEGIN IMMEDIATE` / PG 行锁事务）内**依次重检**：

1. `set_by_key(idempotency_key)`：若另一个并发请求已提交同源版本 → 直接复用，清理**本次尝试自己的** SVG 目录；
2. `_lineage_state(...)`：重算 `parent` 与 `next_revision_no`；若与准备阶段不同（父刚被导入 / 版本号被占），
   在锁内**重新适配并重绘**该修订，再写入；
3. 缺父仍拒绝；
4. 三行（set / revision / artifact）在同一事务提交，失败整体回滚。

文件只在事务提交成功后才保留；失败或复用只删除本次 `set_id` 自己的目录，不碰别人已提交的字节。
**没有新增锁服务、消息队列、后台任务或迁移**。

## 4. 设计来源与适配来源分开

| 字段 | 含义 | 取值 |
| --- | --- | --- |
| `spatial.source.origin_kind` | **传输/适配路径** | 固定 `studio_import` |
| `spatial.source.design_origin.kind` | **上游设计来源** | `real_model` / `human` / `fixture` / `unknown` |
| `spatial.source.design_origin.declared_by` | 依据 | `studio_artifact.diagnostics.source` 或 `not_declared` |
| `spatial.source.design_origin.declaration` | 原始声明文本 | 原样保留或 `null` |
| `spatial.source.design_origin.run_refs` | 运行引用 | 源 `run_id` / `candidate_group_id` |
| DB `source_kind` | 旧粗粒度枚举 | 仍为 `human_edit`（已披露兼容取舍，未新增迁移） |

口径：只有源产物**明确声明**时才写 `fixture`/`real_model`/`human`；未声明一律 `unknown`。
**适配器不是 AI，但这不能把上游真实模型产出改标成人工**——所以适配路径与设计来源分成两个字段，
展示和统计优先读 `design_origin`。

## 5. 精确 spatial 仍是权威，bbox 只是 legacy 显示

- `spatial.zones[].polygon_mm` 原样保存源多边形；导入详情/对账读它。
- legacy `objects[].shape` 是包围盒，带 `geometry_mode="bbox_derived"` 与
  `exact_polygon_ref`；`spatial.adaptation.losses` 明列 `bounding_box_only`。
- 本次收口**没有**放宽这条声明，也没有任何代码据 bbox 计算面积/工程量。
- W2 若从该模型出平面/三维/数量，必须读 `spatial`；仍标 losses 的 bbox 不得作为计量依据
  （W2 衔接约束，本轮不启动 W2）。

## 6. 本批未做

- 未重做适配器字段映射；未启动 W2 制图/渲染/量价；未新增外发、付费调用或基础设施。
- 未新增表/列/迁移；未改 AD01—AD08；未代替用户确认任何设计阶段。
