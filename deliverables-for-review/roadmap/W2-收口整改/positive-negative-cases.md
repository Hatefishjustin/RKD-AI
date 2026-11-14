# 正负例清单（W2 收口整改）

复跑入口（同一脚本对两个源码版本各跑一次）：

```powershell
# 整改后
.\.venv\Scripts\python.exe scripts\w2_closeout_repro.py --label after --out var\evidence\roadmap\W2-收口整改

# 整改前（隔离 worktree，不改动工作区）
$env:RKD_VERIFY_ROOT='D:\Github\RKD AI\var\evidence\roadmap\W2-收口整改\before-code'
$env:RKD_PLACEHOLDER_RENDERER='1'
.\.venv\Scripts\python.exe scripts\w2_closeout_repro.py --label before --out var\evidence\roadmap\W2-收口整改
```

> `RKD_PLACEHOLDER_RENDERER=1` 只在隔离工作树里放一个占位文件，满足整改前代码的
> 「渲染器文件是否存在」检查；实际渲染由可控渲染桩完成，不冒充 Blender 出图。

## R1 完整包

### 正例 1：有渲染 → PNG 必须在清单与 ZIP 内一致
- 预期：清单列出的文件集合与 ZIP 条目双向一致；PNG 在 ZIP 内的字节与单独下载完全相同。
- 整改前：清单有 `render.png`，ZIP 条目为 `cost.html / manifest.json / plan.svg /
  quantity.csv / quantity.json / scene.json`，**没有 render.png**（`add_rendered` 只写清单）。
- 整改后：ZIP 条目含 `render.png`，逐项 sha/大小一致，PNG 与单下载 `True`。

### 正例 2：render=false → 清单与 ZIP 都不得有 PNG
- 整改前/后均通过（旧实现本来就不加渲染记录）。这条保留为回归护栏。

### 负例 1：渲染没有产出文件
- 预期：任务失败，不登记任何成果，不交出"成功完整包"。
- 实测（整改后）：`failed` / `SPATIAL_OUTPUT_FAILED`，0 成果。

### 负例 2：清单字节被改动
- 预期：拒绝据该清单校验并交出文件。
- 整改前：直接解析清单并返回文件（清单被当成可信哈希来源）。
- 整改后：`500 MANIFEST_HASH_MISMATCH`。

## R2 生命周期

### 负例 3：生成中取消，渲染晚到
- 预期：任务终态 `cancelled`；晚到渲染丢弃；无成果登记；再次取消幂等。
- 整改前：`/cancel` 不存在（404），渲染返回后任务变 `succeeded`。
- 整改后：`cancelled`，0 成果，第二次取消 200。

### 负例 4：生成中换当前采用版本
- 预期：旧成果标历史预览，不得冒充当前成果；两条成果都可按 job 查到。
- 整改前：`status.revisions` 为空，只暴露"最新一条"，旧成果不可见。
- 整改后：A=`historical_preview`、B=`current_adopted`，`revision` 指向 B。

### 负例 5：失败后显式重试 + 重复请求
- 预期：失败不登记半份成果；同幂等键返回原任务；重试新任务 `retry_of` 指原任务。
- 整改前：`/retry` 不存在（404）。
- 整改后：202 → 重试任务 `succeeded`，`config.retry_of` 正确。

### 负例 6：A 慢 B 快（反序完成）+ 服务重启遗留 running
- 预期：两条成果按 job 关联到各自修订；只有本批遗留任务被标 `WORKER_RESTARTED`；
  已完成修订仍可列。
- 整改前：无 `recover()`，遗留任务永远卡在 running。
- 整改后：遗留任务 `failed/WORKER_RESTARTED`，两条成果均在列表中。

### 负例 7：共用表插入深化量价修订
- 预期：本页当前成果不被替换，该修订不出现在本页列表。
- 整改前：`latest_succeeded_revision()` 不看输出契约，本页成果消失。
- 整改后：本页成果不变，外来修订不进列表。

## R3 计量与扣除

### 正例 3：L 形手算
- 预期：毛 24 ㎡、扣 2 ㎡、净 22 ㎡、包围盒 30/28 ㎡。
- 整改前：数值对，但量名为「地坪完成面净面积」且 `independent_recompute_m2`
  复用同一个 Shapely 扣除值（伪独立）。
- 整改后：量名为「功能分区几何净面积（非完成面工程量）」，
  `independent_method=vertical_strip_union_v1`，差值 `independent_delta_m2` 单列。

### 负例 8：两个扣除区相交
- 预期：并集 3.25 ㎡（不是 1+2+2）。
- 整改前后均通过——如实记录：Shapely 交集本身没算错。

### 负例 9：扣除区完全在分区外
- 预期：0 ㎡，不产生负面积。整改前后均通过（同上说明）。

### 负例 10：扣除区跨分区边界
- 预期：只扣落在分区内的 0.5×2 = 1.0 ㎡（块宽 1 米，有 0.5 米在缺口外）。
- 整改前后均通过（同上说明）。

### 负例 11：给了单价但没有材料面依据
- 预期：不出金额（避免用假设单价掩盖未知范围）。
- 整改前：直接把单价套在"地坪完成面净面积"上算出金额。
- 整改后：`known_items=[]`，缺项写明"面积依据 unknown，即使给了单价也不试算"。

### 负例 12：材料面切片没有来源声明
- 预期：拒绝（400 `INVALID_FINISH_SCOPE`）；函数层 `normalize_finish_scope` 抛错。
- 整改后：材料面必须带 `declared_by`、每条材料面必须带 `material_ref.material_id`。

### 正例 4：材料面 + 假设单价同页对账
- 预期：`Q-FLOOR-FINISH` 面积按材料分组；有价源的材料出行金额，无价源的材料保持
  unknown；页面同时显示面积依据来源与单价假设，不再出现"本页没有金额"却列金额的矛盾。
- 整改后：A 布局实测 `Q-FLOOR-FINISH=84.6 ㎡`（40.8 + 33.6，手算一致），
  `M-A` 金额 `40.8×800=32 640`，`M-B` 保持 unknown。

## 判据强度说明

- 所有 R2 用例用**事件屏障**控制时序（渲染桩进入后阻塞、外部释放），没有用 `sleep` 猜时序。
- 每个用例独立断言，任一失败只影响自己，不中断其余检查。
- 删除过的弱断言：旧 `W2-02` 只检查"ZIP 条目非空"，本批改为清单↔ZIP 双向逐项比对。
