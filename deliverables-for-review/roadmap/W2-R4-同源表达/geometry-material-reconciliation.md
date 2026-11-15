# 几何 / 材质 / 量价对账（检查点 5）

材料面切片由**精确分区多边形**生成，材料编号与表达层材质映射同源；
金额只作用于有面积依据的分组，单价是调用方假设输入，不是价源、不是报价。

## 分区 → 材料编号 → CC0 贴图 slot

| zone_id | role | material_slot（表现） |
| --- | --- | --- |
| ZA1 | None | oak |
| ZA2 | None | stone |
| ZA3 | None | floor_microcement |
| ZA4 | None | walnut |
| ZA5 | None | fabric |
| ZA6 | None | stone |

## 材料面分组 → 面积 → 假设单价试算

| material_id | layer | 面积 ㎡ | 来源对象 | 假设单价(元/㎡) | 试算(元) |
| --- | --- | --- | --- | --- | --- |
| mat-fabric | floor_finish | 38.19 | FA-ZA5 | 1000.0 | 38190.0 |
| mat-floor-microcement | floor_finish | 72.16 | FA-ZA3 | 1000.0 | 72160.0 |
| mat-oak | floor_finish | 25.18 | FA-ZA1 | 1000.0 | 25180.0 |
| mat-stone | floor_finish | 46.5 | FA-ZA2, FA-ZA6 | 1000.0 | 46500.0 |
| mat-walnut | floor_finish | 51.0 | FA-ZA4 | 1000.0 | 51000.0 |

合计（假设单价试算，非报价）：233030.0 元；`formal_quote=false`，税率/成本加成/损耗/工艺/产品选型全部 unknown。

## 四项受控变更（每组同一冻结模型副本）

| 变更 | 平面 | 三维场景 | 工程量 | 金额 |
| --- | --- | --- | --- | --- |
| `R4-WIN-N1` 洞口宽 5466→3000mm | 门窗表与短编号同步 | enclosure 同 ID 同尺寸 | 不变 | 不变 |
| `mat-oak` 贴图 oak→walnut | 材质图例变化 | arrival 分区 material_slot 变化 | 不变 | 不变（材料编号与单价未变） |
| 机位 x +3000mm | 机位/视锥变化 | camera.position 变化 | 不变 | 不变 |
| 假设单价 ×1.2 | 不变 | 不变 | 不变 | 试算金额增加 |

结论：表达层（围合/材质/机位/单价）与**精确几何量**分离；改开口尺寸会同步平面与三维，
但不会偷偷改变功能区净面积；换材质只改表现与材质分组依据，不制造工程量。
