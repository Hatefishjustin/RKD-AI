# 宁波协诚 DXF 几何级第二通道审查报告

生成时间：2026-09-21  
输入：`source/04 平面PL.dxf`  
DWG 候选基线：`derived/cad-plan-candidates.json`

## 1. 本轮做了什么

使用独立 ASCII DXF 几何读取器，在 DWG 已定位的主平面范围内读取 DXF `ENTITIES` 模型空间几何，并按版本化图层规则统计专业类别。块 `INSERT` 只保留插入点证据，没有展开 `BLOCKS` 变换；尺寸、文字、填充和图纸空间不升级为构件。

## 2. 结果摘要

| 指标 | DXF 第二通道 | DWG 候选基线 |
| --- | ---: | ---: |
| 主平面内直接几何/插入点候选 | 754 | 831 |
| 主平面内当前范围直接候选 | 536 | 570 |
| 块插入点 | 70，均完成基础 2D 块展开 | 105 个已展开块候选 |
| 已创建专业对象 | 0 | 0 |
| 可计量对象 | 0 | 0 |
| 升级状态 | `not-approved` | `not-ready` |

## 3. 类别差异

摘要类别计数如下。差异是进一步抽样的入口，不是自动判定错误：

| 类别 | DXF 直接实体 | DWG 候选 | 差值 |
| --- | ---: | ---: | ---: |
| architecture.detail | 16 | 16 | 0 |
| architecture.opening.door | 18 | 18 | 0 |
| architecture.wall | 82 | 90 | -8 |
| interior.ceiling | 103 | 106 | -3 |
| interior.floor.finish-line | 42 | 58 | -16 |
| interior.furniture.fixed | 205 | 212 | -7 |
| interior.furniture.loose | 70 | 70 | 0 |
| mep.electrical.lighting-fixture | 42 | 42 | 0 |
| mep.electrical.outlet | 15 | 113 | -98 |
| mep.electrical.switch | 47 | 106 | -59 |

DXF 直接实体少于 DWG 候选，主要待核对原因是 DXF 与 DWG 的代理/派生实体表达不同、块候选筛选口径不同，以及 DXF 当前只实现基础 2D 块变换。DXF 本轮对 70 个主平面插入点完成了基础展开，共得到 5,018 个展开点；这仍不是专业 CAD 等价验证。机电类别仍不进入宁波本次报价范围。

## 4. 必须保持的限制

- 这不是第二 CAD 专业引擎的完整等价解析；它只提供独立直接实体证据。
- `INSERT` 已做基础基点、旋转、缩放和嵌套展开，但尚未处理完整数组、非平面挤出和所有填充拓扑，不能用 70 个 DXF 插入点或 5,018 个展开点代替 DWG 的 105 个已展开块候选。
- 754/536 不是墙、门、家具、房间或工程量数量。
- 仍需原 CAD 软件或具备块变换/拓扑能力的第二引擎抽样核对，再执行对象合并、门洞配对和闭合区确认。
