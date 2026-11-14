# 代码差异（W2 收口整改）

- 基线提交（审查基线）：`b1f1747`
- 业务实现基线：`40049fd`；本批在 `b1f1747` 工作树上做限定整改
- 补丁：`changes.patch`（含新文件 `scripts/w2_closeout_repro.py`）
- 未提交前可用 `git diff` + 该补丁文件核对；提交后以提交号 + `git diff b1f1747..<本批提交>` 复核

## 改动文件

| 文件 | 改动 | 为什么必须改 |
| --- | --- | --- |
| `mvp/rkd_mvp/ai_spatial_outputs.py` | 版本号上调；新增竖条带独立面积；`measure()` 拆分几何量/完成面量；新增材料面切片规范化；成本改为「面积依据 + 假设单价」双条件；`cost_html` 动态口径；`finalize_package` + `check_zip_against_manifest` 取代 `add_rendered`/`finalize_files`；平面面积表同步 | R1 完整包、R3 语义与独立复算 |
| `mvp/rkd_mvp/ai_spatial_output_service.py` | 设置解析加单价/材料面；提交时冻结绑定事实；渲染后与登记前双重检查任务状态；写盘→单事务登记→条件终态；取消/重试/恢复/按 job 查询；下载前校验清单 SHA | R1 原子登记、R2 生命周期 |
| `mvp/rkd_mvp/ai_development_repository.py` | 新增 `touch_job`（条件阶段更新）、`close_job`（条件终态）、`latest_succeeded_revision(output_version)` 过滤 | R2 单调终态与共用表不串页 |
| `mvp/rkd_mvp/ai_development_service.py` | 深化页改为 `latest_succeeded_revision(OUTPUT_VERSION)` | 共用表串页的另一半（不让本页成果挤掉深化页） |
| `mvp/rkd_mvp/api_service.py` / `api_server.py` | 新增 `cancel` / `retry` 接口；`GET spatial-outputs` 支持 `job_id` / `production_revision_id` 查询 | R2 入口 |
| `web/src/AiSpatialOutputsPanel.tsx` | 绑定状态标签、成果历史、取消/重试按钮、成本与数量口径、交付包自检提示 | R2/R3 在页面上可见 |
| `scripts/verify_w2_spatial_outputs.py` | `W2-02` 加强为 ZIP 解压逐项核对；净量按新 id；单价用例补材料面依据 | 验收判据必须跟上语义变化 |
| `scripts/w2_closeout_repro.py`（新增） | 15 条正负例，同一脚本对整改前后各跑一次 | 先复现再修复的可比证据 |

## 明确没有改的东西

- 无新增数据库迁移、无新表、无新列：`ai_development_jobs/revisions/artifacts` 三表沿用。
  取消任务的 `phase` 保持原值（表上 `phase` 有 CHECK 约束，不改迁移就不新增 `cancelled` 值）。
- 未改 W1 适配器、未改契约 schema、未改 `spatial` 精确几何、未改 Studio 校验规则。
- 未改 AD01—AD08 判定、未改阶段确认、未动采购/报价/发布边界。
- 未回写历史证据与旧复核包（`git status` 无 `deliverables-for-review/roadmap/W2-同源成果切片/` 改动）。

## 关键实现点（便于逐行核对）

1. `finalize_package(files, manifest)`：文件集是唯一来源，清单条目由该集合重新计算，
   ZIP 由同一集合写出；随后 `check_zip_against_manifest` 重新打开 ZIP 逐项比对，
   不一致直接 `ValueError`，服务层因此不会登记。
2. `scanline_area_minus(zones, holes)`：条带中点采样 + 区间并/差；只吃原始顶点，
   不复用 `unioned.intersection(keep_union).area`。
3. `measure()` 同时给出：
   - `Q-FLOOR-GEOMETRIC-NET`（几何量，`engineering_status=geometric_only_not_a_finish_quantity`）
   - `Q-FLOOR-FINISH`（只有显式材料面切片才 known，否则 unknown）
4. `build_cost()`：`known_items` 需要「`Q-FLOOR-FINISH` known」且「该材料有假设单价」
   两个条件同时成立；否则只写 unknown 原因。
5. `touch_job` / `close_job`：`UPDATE ... WHERE status=?`，取消后阶段更新返回 0 行，
   晚到的 `succeeded` 写不进去。
6. `status()`：不再比较「最新任务」与「全局最新成功成果」，而是按 `measurement_version`
   前缀筛出本批修订，逐个按**当前采用版本**判定绑定状态，并支持显式 `job_id` /
   `production_revision_id` 查询。
