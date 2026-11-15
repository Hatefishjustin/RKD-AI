# 改动范围（基线 82d2a66）

`git diff 82d2a66 -- mvp web scripts`：5 个文件，+1100 / −99；零迁移、零新表、无新服务。
完整补丁见同目录 `changes.patch`（78 885 字节）。

## mvp/rkd_mvp/ai_spatial_outputs.py（C1）

- `GENERATOR_VERSION v3`、`QUANTITY_VERSION v3`、`COST_VERSION v3`、`FINISH_SCOPE_VERSION v2`
  （计量方法与契约变了，版本必须跟着变；`MANIFEST_VERSION` 未变）。
- 新增 `_segments` / `_segment_cross_x` / `_event_abscissae`：条带断点 = 全部顶点 x +
  全部边-边交点 x；`scanline_area` / `scanline_area_minus` 在这些断点上分条带，
  条带内截面长度线性 → 中点值即精确积分（`vertical_strip_union_v1` → `vertical_strip_exact_v2`）。
- `_finish_quantity`：主值改为 Shapely 精确并/差（按 layer+material 分组 union），
  条带只做交叉校验；两条路径差 > `INDEPENDENT_TOL_M2`(1e-3 ㎡) → `known_status="disputed"`，
  `value=null`，不给 material_groups 之外的金额依据；`deduction_basis="none"` 时不扣保留区。
- `normalize_finish_scope`：单位契约（坐标 mm、面积 m2、其余拒绝）、有限坐标与 ±1e6 mm 上限、
  有效简单多边形、`object_id` 唯一、`deduction_basis` 白名单、同层重叠需
  `overlap_declaration`，返回值新增 `layer` / `same_layer_overlaps` / `overlap_declaration`。
- `build_cost`：disputed 分支（不试算金额，unknown 里写明两条路径不一致）；
  known_items 带层信息与 `Q-FLOOR-FINISH/<material>@<layer>` 引用。
- `cost_html`：disputed 专属口径（不再出现"没有金额"与金额并存的矛盾）。

## mvp/rkd_mvp/ai_spatial_output_service.py（C2/C3）

- `new_instance_id()` + `instance_id` 参数；`_create_job` 把 `run_instance` 写进 `config`。
- `recover()`：只回收 `run_instance ≠ 当前实例` 的本批 queued/running 任务；
  不再读 `_active`；返回值带 `instance_id`。`status()` 仍会在读前触发恢复，但现在对
  本实例任务是 no-op（这是 C2 的关键）。
- `status()`：`job_id` / `production_revision_id` 主键直查 + 类型校验，显式查询不回退；
  两参数同给 → 400 `AMBIGUOUS_QUERY`；默认概览返回 `last_successful` 与
  `revision_source`（`job` / `last_successful` / `none` / `requested_job` / `requested_revision`），
  `query.explicit` 标注是否显式；列表分页前按类型过滤（见仓储）。
- `_is_spatial_revision` / `_label_binding` 提取为公共小函数。

## mvp/rkd_mvp/ai_development_repository.py（C3 支撑）

- `jobs(limit=None, *, kind=None)`：kind 过滤下沉 SQL（Postgres `config->>'kind'=?`、
  SQLite `config_json LIKE '%"kind":"…"'`），过滤后再 LIMIT；`limit=None` 表示取全。
- `revisions(limit=None, *, measurement_prefix=None)`：`measurement_version LIKE '前缀%'` 下沉。
- 新增 `revisions_by_job(job_id)`：按 job 主键直查修订（显式查询用）。

## web/src/AiSpatialOutputsPanel.tsx

- `Status` 类型补 `revision_source` / `last_successful` / `query`；
  `revision_source === "last_successful"` 时显示
  `data-testid="spatial-previous-output"` 提示：当前显示的是上一份成功成果，
  不是本次任务的产物。其余 UI 不变（页面本就不用显式查询）。

## scripts/w2_second_closeout_repro.py（新增，15 条）

- 函数级：C1-01…06（解析期望值、单位契约、无效多边形、同层重叠）。
- HTTP 级（复用 `w2_closeout_repro.Stack` 隔离装配）：C1-07/08（真实入口两个三角材料面）、
  C2-01…03（`_launch` 接缝 + 屏障）、C3-01…04（显式语义 + >50 历史）。
- 解析工具 `triangle_rect_area(ax, ay, lx, ly, rect)` 只在斜边与保留区上下边、
  以及保留区下边以下三处断点分段——第一版漏了第三个断点，已在 `c1-handcheck.md` §5 如实记录。
