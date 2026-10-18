# DXF 第二通道接入与核对规范

版本：V1.0  
日期：2026-09-19

## 1. 目的

本规范用于把同一份原始 DWG 从原 CAD 软件另存的 `AutoCAD 2013 DXF` 作为独立证据通道，与 GNU LibreDWG 的首轮结果核对。DXF 不覆盖 DWG 原件，也不自动替换既有派生产物。

第二通道的目标是发现解析器差异，不是用“两个文件看起来差不多”替代专业确认。图层、图元数或范围一致，仍不等于墙、门、家具、房间和工程量已经验证。

## 2. 导出要求

- 从与当前 SHA-256 为 `77DDAC8E80401BF3C7913BFF8AC959DC5D4A0CC573EC5CDCBC2CAB5D95A47616` 的 `04 平面PL.dwg` 相同原件导出。
- 格式选择 `AutoCAD 2013 DXF`，保留模型空间、图纸空间、图层、块、外部参照提示和原坐标。
- 不炸开图块，不移动坐标，不删除图层，不清理未知对象，不另做人工简化。
- DXF 作为新来源资产登记，必须记录导出人、导出软件、软件版本、导出时间和来源 DWG 指纹。

## 3. 接入顺序

1. 将 DXF 放入试点 `source/`，不得覆盖 DWG。
2. 计算文件大小和 SHA-256，更新样本清单。
3. 使用独立 ASCII DXF 读取器读取版本、单位、HEADER 范围、图层、块定义和 ENTITIES 模型/图纸空间摘要。
4. 与现有 `cad-source-inspection.json` 比较稳定摘要，所有差异保留，不自动选择一方为真。
5. 摘要差异解释后，才进入主平面范围、块实例变换、墙/门/家具候选和闭合区的几何级核对。
6. 由 CAD/施工图责任人抽样确认后，才允许把对应对象从 `candidate` 提升为 `verified`；工程量仍需独立计量规则。

## 4. 可执行命令

在仓库根目录运行：

```powershell
$py = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py mvp/run_cad_secondary_validation.py `
  --dxf 'fixtures/ningbo-xiecheng/2026-09/source/04 平面PL.dxf' `
  --source-asset-id 'drawing-cad-01-dxf-2013' `
  --dwg-inspection 'fixtures/ningbo-xiecheng/2026-09/derived/cad-source-inspection.json' `
  --output 'fixtures/ningbo-xiecheng/2026-09/derived/cad-secondary-validation.json'
```

输出必须符合 `contracts/v1/cad-secondary-validation.schema.json`。对比报告的 `promotion_status` 固定为 `not-approved`。

## 5. 第一阶段比较项

- 绘图单位；
- 图层数量和图层名称集合；
- ENTITIES 图元总数和图元类型数；
- 文字类和尺寸类图元数；
- DXF HEADER 与 DWG HEADER 的全图范围；
- 模型空间和图纸空间图元摘要；
- 块定义名称及块内图元数量。

DXF 导出可能改变代理对象、尺寸子类型、动态块表示和实体编码，所以“数量差异”是复核任务，不自动视为 DWG 错误或 DXF 错误。

## 6. 几何级核对门槛

摘要核对完成后，几何级核对至少覆盖：

- 主平面定位范围 `26,169.582 mm × 17,920.175 mm` 与图示 `26,170 mm × 17,920 mm`；
- 当前 831 个主平面直接候选的来源层、范围内/外判定和坐标；
- 105 个插入块的基点、平移、缩放、旋转、镜像和嵌套展开；
- 570 个当前范围候选、261 个机电排除候选；
- 133 个不可计量几何组；
- 70 个闭合区候选及 162 段悬线、7 段切割线。

这些数字是当前 DWG 通道的比较基线，不是要求 DXF 必须机械地产生相同内部记录数。任何差异都必须定位到具体图层、实体或块变换后再判定。

## 7. 停止条件

出现以下任一情况时停止对象升级：

- DXF 不是从登记的 DWG 原件导出，或来源指纹无法说明；
- DXF 为二进制、损坏或缺少 ENTITIES；
- 单位不是毫米且无法证明换算；
- 主平面范围、关键图层或关键块实例存在无法解释的差异；
- 导出过程炸开图块、移动坐标、删层或清理对象；
- 专业责任人尚未完成抽样确认。

停止时保留 `drawing-unverified`、`domain_object_status=not-created` 和 `quantity_status=not-ready`，不得自动填 0 或发布施工成果。
