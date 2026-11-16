# 前后同例负例与正例（W3 前置适配）

执行证据：`var/evidence/roadmap/W3-真实模型spatial适配/after/verification.json`；`checks.json` 的 RM-* 项。全部离线确定性夹具，0 外部调用。

## 负例（同一输入，朴素做法 vs 适配契约）

| 编号 | 同一测试例 | 朴素/缺陷做法（before） | 本批契约行为（after） | 结果 |
| --- | --- | --- | --- | --- |
| RM-N01 | site.boundary_source 改成 `manual_boundary_not_site_verified` | 直接接受 W2 测试边界并落图 | `SITE_BOUNDARY_MISMATCH` 拒绝，要求确认的 `rkd-site-basemap.v2` | pass |
| RM-N02 | 模型原生边界 12×8m（旧测试框架） | 把 12×8m 矩形原样放进 26.17×17.92m 底图 | `MODEL_FRAME_MISMATCH` 拒绝，不缩放不平移 | pass |
| RM-N03 | `design_origin.kind=real_model` 但 `run_refs=[]` | 离线夹具冒称真实 AI 设计 | `DESIGN_ORIGIN_UNVERIFIED` 拒绝 | pass |
| RM-N04 | 分区矩形 x=25m、宽 7m（越出 26.17m） | 截断越界部分继续出图 | `OBJECT_OUTSIDE_BOUNDARY` 拒绝 | pass |
| RM-N05 | `zone_role=unknown_role_not_in_vocab` | 默认归类为 `primary_display` | 角色 `unknown` + 字段清单标 unknown，不擅自归类 | pass |
| RM-16 | 同一对象 `zone:display` 宽度变化后重适配 | 新旧版本混用、无对账 | `diff_spatial` 记录同一稳定 ID 的 `polygon_mm` 前后值 | pass |

## 正例（必须同时成立）

| 编号 | 断言 | 观察 | 结果 |
| --- | --- | --- | --- |
| RM-01 | 适配契约实例符合自身 JSON Schema | 契约由代码常量生成，避免文档与实现漂移 | pass |
| RM-02 | 确认的 v2 底图 5 文件字节/SHA 与绑定卡一致 | 逐文件实测一致，边界 26170×17920mm | pass |
| RM-10A/B | 两个候选适配产物符合 additive 输出 Schema | 均无 schema error | pass |
| RM-11 | 两候选空间组织实质不同 | 分区多边形签名不同（非仅改名/配色） | pass |
| RM-12 | 字段清单含 unknown 行且值不为 0 | unknown 行 `target_value=null` | pass |
| RM-13 | 来源/人工表达分离 | `origin_kind=real_model_shape_fixture`、`design_origin=fixture`、`expression_source` 不含 W2 人工表达 | pass |
| RM-14 | 四角化不冒称非矩形；curved_intent 无弧墙 | 所有分区 `non_rectangular_capability=false`；所有 partition_intent `arc_geometry_generated=false` | pass |
| RM-15 | 底图保留区进入净量且 `site_verified=false` | 楼梯/卫生间两项保留区来自确认底图 | pass |
| RM-17 | 同一冻结模型生成 plan/scene/quantity/cost 并打包 | ZIP 与清单逐文件字节一致 | pass |
| RM-18 | 无价源成本保持 unknown | 成本类量 `value=null` | pass |
| RM-19 | 只改材质意向不改几何量 | 净量相等、场景变化 | pass |
| RM-20 | 只改机位不改几何量 | 净量相等 | pass |
| RM-21 | 本地 Blender 人眼图（工程样张） | 1,024,095 字节 PNG，退出码 0 | pass |

## 复跑命令

```
cd "D:/Github/RKD AI"
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/verify_realmodel_spatial.py \
  --evidence var/evidence/roadmap/W3-真实模型spatial适配/after \
  --out "deliverables-for-review/roadmap/W3-真实模型spatial适配"
```

复跑会覆盖本批同一输出目录；请勿用它覆盖旧批次。需要只做快速检查时加 `--no-render`（此时 RM-21 自动计 pass 但**没有**真实渲染，不应当作出图证据）。
