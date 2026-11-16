# 阶段 2 成果样张（工程路径，非客户成果）

来源：`deliverables-for-review/roadmap/W3-真实模型spatial适配/outputs/`。全部由**同一冻结候选** `outputs/model.json`（离线确定性夹具，`design_origin.kind=fixture`，0 外部调用）经 `rkd-spatial-outputs.v4` 生成；几何权威是 `spatial.zones[].polygon_mm`，不是兼容用矩形。

| 文件 | 作用 | 复核点 |
| --- | --- | --- |
| `model.json` | 冻结候选与 spatial 投影 | `spatial.schema_version=rkd-realmodel-spatial.v1`；`non_rectangular_capability=false`；来源/未知项/字段清单 |
| `plan.svg` | 可读平面 | 分区来自精确多边形；保留区来自确认底图；入口/窗高等未知项保留，不是施工图 |
| `scene.json` | 人眼图场景规格 | 米制；机位、家具高度、材质均为标注假设；对象 ID 与平面一致 |
| `render.png` | 本机 Blender 4.2.9 Cycles CPU 人眼图 | 1,024,095 字节；**内部工程样张**：灰材质、无产品细节/软装/人物，明显不达客户交付级 |
| `quantity.json` / `quantity.csv` | 受支持净量 | 按多边形与保留区复算；无价源项 `value=null`，不填 0 |
| `cost.html` | 成本草稿 | `formal_quote=false`；unknown 成本与已知量同列 |
| `manifest.json` | 同源清单 | 冻结输入、机位、量、成本、缺项版本一致 |
| `package.zip` | 同源成果包 | 与清单逐文件字节/SHA 复核通过 |

## 同源断言（已实测）

- 几何改动（分区宽度）→ 平面与净量变化；逐字段 diff 见 `checks.json` RM-16；
- 只改材质意向 → 场景变化、净量不变（RM-19）；
- 只改入口机位 → 净量不变（RM-20）；
- 无价源 → 成本 unknown（RM-18）；
- ZIP 逐项与清单字节一致（RM-17）。

## 不得这样使用

不得作为宁波协诚项目阶段 2 用户候选、不得发客户、不得当施工图/正式报价/合规结论、不得称 AI 自动设计结果。来源是离线夹具，不是系统模型自动设计；阶段 2 具体候选须由获授权的真实模型运行并经用户评价。
