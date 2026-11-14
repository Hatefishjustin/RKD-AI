# Q10 检查矩阵（同源成果：对象/材质/相机/哈希、字节一致、变更后旧版保留、生命周期）

Q10 在本批拆成「同源」与「生命周期」两组。每行给出可复跑的判据与本次实测结果；
判据来源：docs/26 第 3 节 W2 退出证据 + 架构复核 R2 的四条限定。

## A. 同源与字节

| # | 判据 | 实测结果 | 证据 |
| --- | --- | --- | --- |
| A1 | 平面/场景/净量/机位来自同一个冻结修订（同一 `model_hash` 与 `source.sha256`） | 通过：两布局各一次，`baseline.model_hash` 不同且平面标题栏、场景 JSON、清单同源字段一致 | `after-w2-script/checks.json` W2-01/W2-06 |
| A2 | 对象 ID 在平面、场景、清单三处一致（不是按位置猜） | 通过：`spatial.zones[].object_id` / `furniture[].object_id` 直接写入三处 | 同上 W2-01/W2-03 |
| A3 | 材质变化影响平面配色与场景材质，但不改净量 | 通过：材料变更用例净量不变、平面/场景字节改变 | 同上 W2-07 |
| A4 | 只改相机不改任何工程量 | 通过：机位改动后 `quantities` 完全相等 | 同上 W2-07 |
| A5 | 只改单价不改几何 | 通过：单价 1000→1200 时金额变化、`quantities` 与 `plan` 与同 scope 基线完全相等 | 同上 W2-07 |
| A6 | 下载逐文件字节与登记一致；ZIP 解压后清单逐项命中 | 通过（本批新增严格判据：清单 ↔ ZIP 双向比对 + PNG 与单独下载一致） | 同上 W2-02；`repro-after.json` W2C-R1-01/03 |
| A7 | 无渲染时清单与 ZIP 都不得出现 PNG | 通过（真实入口 render=false） | `repro-after.json` W2C-R1-04 |
| A8 | 清单字节被改动后不得据其校验交付 | 通过：返回 `MANIFEST_HASH_MISMATCH` | `repro-after.json` W2C-R1-06 |

## B. 生命周期（架构 R2）

| # | 判据 | 实测结果 | 证据 |
| --- | --- | --- | --- |
| B1 | 生成中取消 → 单调终态，晚到渲染不得改回 running/succeeded | 通过：取消后任务 `cancelled`，晚到渲染被丢弃，本任务 0 成果登记 | `repro-after.json` W2C-R2-01 |
| B2 | 取消后再次取消幂等；已完成任务不可取消 | 通过：第二次取消返回 200（已取消）；已完成返回 409 `CANNOT_CANCEL`，历史字节保留 | 同上 + 服务实现 |
| B3 | 生成中换当前版本 → 完成结果不得冒充当前成果 | 通过：旧成果 `historical_preview`，新采用版本 `current_adopted` | `repro-after.json` W2C-R2-02 |
| B4 | 按 job/修订查询，保留历史入口 | 通过：`?job_id=` / `?production_revision_id=` 均可定位；`revisions[]` 全量列出 | 同上 + W2C-R2-05 |
| B5 | A/B 反序完成仍能按 job 关联到正确修订 | 通过：A 慢 B 快，两条成果各自 `option_revision_id` 正确 | `repro-after.json` W2C-R2-05 |
| B6 | 失败不登记半份成果 | 通过：渲染失败任务 `failed`，0 修订、0 成果 | `repro-after.json` W2C-R2-03 |
| B7 | 显式重试关联原任务；同幂等键不重跑 | 通过：`config.retry_of` 指原任务；同键返回原任务 `reused=true` | 同上 |
| B8 | 重启后只恢复本批中断任务，历史字节可读 | 通过：遗留 `running` 任务被标 `WORKER_RESTARTED`，已成功修订仍可列可下 | `repro-after.json` W2C-R2-05 |
| B9 | 共用表内旧深化量价成果不污染本页 | 通过：插入 `ai-development-outputs.v1` 修订后，本页当前成果不变且该修订不进本页列表 | `repro-after.json` W2C-R2-04 |

## C. 未纳入本批的 Q10 子项（not_run，如实标注）

| # | 子项 | 状态 | 原因 |
| --- | --- | --- | --- |
| C1 | 多进程/多实例并发取消与恢复 | not_run | 仅单进程多线程 + 数据库条件更新；未起第二进程 |
| C2 | PostgreSQL 下的条件更新与恢复 | not_run | 本批只在 SQLite 隔离库实测，未起 PG 实例 |
| C3 | 断电/进程被杀后的文件残留清理 | not_run | 只测服务重启后的任务状态恢复，未做断电注入 |
| C4 | 渲染进程主动终止 | 未采用 | 本批明确采用「允许渲染结束后丢弃登记」，不杀进程 |

## D. 旧版保留

- 上一批复核包 `deliverables-for-review/roadmap/W2-同源成果切片/` 未被本批写入（`git status` 无相关改动）。
- 本批全部运行证据写入独立目录 `var/evidence/roadmap/W2-收口整改/`，不回写历史。
- 旧修订字节不动：新成果写入独立 `projects/ai-spatial-outputs/<job_id>/` 目录。
