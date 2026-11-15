# C3 按 ID 查询串成果与历史截断

## 缺陷（架构复核指认）

1. `status()` 先取「全局最新 50 条任务/修订」，再在里面找显式 ID；找不到就回退到
   "最新成功成果"。于是：
   - 显式查一个**失败**任务 B，返回的 `revision`/`artifacts` 来自上一个**成功**任务 A
     （架构实测记录：请求 B、返回 A 的成果行与 6 个文件）；
   - 任务/其他类型超过 50 条后，真实存在的旧任务按 ID 查直接 404；
   - 其他类型任务挤占全局 50 条后，本页自己的历史也被挤掉。
2. `job_id` 与 `production_revision_id` 同时给时没有冲突拒绝。

## 修法

- 显式 `job_id` → 直接 `job(job_id)` 主键查询，校验 `config.kind=spatial_outputs`；
  修订用 `revisions_by_job(job_id)`（按 job 直查），只返回这个任务自己的修订与成果文件；
  查不到就是 404，**不回退**。
- 显式 `production_revision_id` → 直接 `revision(id)` 主键查询，再反查它所属的 job；
  两个参数同时给 → 400 `AMBIGUOUS_QUERY`。
- 列表：类型过滤**下沉到 SQL**（Postgres `config->>'kind'`，SQLite `config_json LIKE`），
  先过滤后分页；修订按 `measurement_version LIKE 'rkd-spatial-outputs%'` 下沉过滤；
  过滤后取最近 N 条，并把 `checked` 总数如实返回（不声称"最新 50 条就是全部历史"）。
- 页面默认（无参数）保留"续看上一份成功成果"，但 `revision_source='last_successful'`
  明确标注，面板新增 `spatial-previous-output` 提示：这不是本次任务的产物。

## 整改前 → 整改后（`repro-before.json` → `repro-after.json`）

| 用例 | 整改前 | 整改后 |
| --- | --- | --- |
| W2C2-C3-01 显式查失败任务 B | 200，revision=任务 A 的（`ai-spatial-job_8739…`），artifacts=6 个 | 200，`revision=null`、`artifacts=[]`，只返回任务 B 自己 |
| W2C2-C3-02 按修订 ID 反查 | 返回的 job 是"最新任务"（另一个 ID） | 返回的 job 就是对应任务 |
| W2C2-C3-03 两参数同时给 | 200（默默按其中一个处理） | 400 `AMBIGUOUS_QUERY` |
| W2C2-C3-04 55 条历史后查最旧任务 | 404 `JOB_NOT_FOUND`（被最新 50 条截断） | 200，返回它自己的修订与成果文件 |

> 整改前的 404/串改数值是逐条实测记录，不是推断；`repro-before.json` 里保留了
> 具体任务 ID（`requested_job_id` / `returned_revision_job_id`）。

## 与 C2 的关系

两者共用 `status()` 读路径，本批一并修：显式语义与回退语义分离后，
"页面默认续看" 仍然可用，但不再冒充任务产物。
