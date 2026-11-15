# 关键正负例与复跑结果

## A. 入口小修：同层异材重叠（先复现、再修复，同一脚本各跑一次）

| 编号 | 用例 | 整改前 | 整改后 |
| --- | --- | --- | --- |
| R4F-01 | 同层两块完全相同的 2×2m 面，wood/stone + overlap_declaration 自由文字 | 8㎡/known + 2 笔试算（重复工程量） | conflict/None + 0 笔试算 + 冲突明细 |
| R4F-02 | 同材同层重叠 + 声明 | 并集 4㎡/4000 元 | 并集 4㎡/4000 元（回归护栏） |
| R4F-03 | 同层异材几何互斥 | 8㎡ known | 8㎡ known（合法） |
| R4F-04 | 不同构造层重叠 | 合计被当单层净面积 | 分层计量 + `multi_layer_sum` + 非单层标注 |
| R4F-05 | 结构化互斥裁切（x=1000 实际裁成两块） | 字段被忽略仍 8㎡ | 4㎡ known（wood 2 + stone 2） |
| R4F-06 | 裁切仍重叠/不覆盖 | 忽略字段 / 入口抛错 | conflict 待核，不产 known |
| R4F-07 | **真实 HTTP** 提交冲突 scope，render=false | 任务成功且 8㎡/8000 元进入成果 | 任务成功但 `Q-FLOOR-FINISH=conflict/None`，cost 0 试算，CSV/HTML 标待核 |
| R4F-08 | **真实 HTTP** 同材声明后并集 | 4㎡/4000 元 | 4㎡/4000 元（回归护栏） |

整改前 `all_as_expected=True`、整改后 `all_as_expected=True`；证据 `entry-fix/before.json`、`entry-fix/after.json`。

契约要点：自由文字 `overlap_declaration` **不是**消歧规则；只有 `material_allocation`
给出几何互斥且等价覆盖的裁切面并被程序实际替换原面后，才允许同层异材同时计量；
真实不同构造层分别计量，但合计标为多构造层合计，不叫单层地坪净面积。

## B. 原 15 项回归（W2 二次收口，未放宽断言）

`15/15` observed_pass，failed=0；证据 `entry-fix/regression-15.json`。

## C. R4 本批检查

- `R4-A-SUBMIT` 布局 A 由同一生成器产出完整成果 → **observed_pass**
- `R4-A-ZIP` 布局 A 完整 ZIP/下载 SHA 与 PNG 一致 → **observed_pass**
- `R4-B-SUBMIT` 布局 B 由同一生成器产出完整成果 → **observed_pass**
- `R4-B-ZIP` 布局 B 完整 ZIP/下载 SHA 与 PNG 一致 → **observed_pass**
- `R4-01` 两种不同布局由同一生成器出平面/场景/人眼图，模型哈希与净量不同 → **observed_pass**
- `R4-02-A` 布局 A 平面含墙/洞口/家具/材料/机位/尺寸链且文字可读 → **observed_pass**
- `R4-02-B` 布局 B 平面含墙/洞口/家具/材料/机位/尺寸链且文字可读 → **observed_pass**
- `R4-03-A` 布局 A 围合/开口/家具在平面与三维读同一 ID 与尺寸 → **observed_pass**
- `R4-03-B` 布局 B 围合/开口/家具在平面与三维读同一 ID 与尺寸 → **observed_pass**
- `R4-04-A` 布局 A 真实 CC0 材质/家具/窗光/人眼机位出图 → **observed_pass**
- `R4-04-B` 布局 B 真实 CC0 材质/家具/窗光/人眼机位出图 → **observed_pass**
- `R4-05` 四项受控变更：开口尺寸同步平面/场景且改几何不改量；换材质可追踪；只改相机不改量；只改单价不改几何 → **observed_pass**
- `R4-06` 入口小修：同层异材冲突不产 known 总量/试算；原 15 项回归保留 → **observed_pass**
- `R4-07` 按 job_id 查询只返回该任务的 revision/artifacts，不串另一布局 → **observed_pass**
- `R4-08` 同一 R4 服务代码：取消晚到不复活可显式重试；失败任务不借用他人成果 → **observed_pass**

## D. 浏览器与全量回归

- 真实 Edge 浏览器：`passed=True`，page_errors=0，390px scrollWidth=390，下载 SHA 与 manifest/ZIP 一致；证据 `browser/`。
- 全量单测 262/262 OK（`runtime/full-unittest.log`）；`tsc --noEmit` 与 `npm run build` EXIT=0。
- 修正的真实缺陷：既有 Blender 样板 `box()` 顶/底面是对角自交四边形，R4 渲染器改为正确 8 顶点 6 面棱柱；长对象 ID 撑破 390px 窄屏 grid 轨道，已在 `web/src/styles.css` 用 `minmax(0,1fr)` 与 `overflow-wrap` 修复。
