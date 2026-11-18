# 待复核裁定事项（本轮不自行决定）

本轮不宣布 W3 通过、不宣布设计通过、不放行真实模型试验、不推进阶段或 W4。以下需架构师裁定：

## D1 观测句柄的形态

现状：`ControlledRunService.begin_invocation(project_id)` 产出 `ObservationScope`；provider 只拿 `scope.opener()`；签发必须带 scope，跨 scope 一律 `OBSERVATION_NOT_FROM_INVOCATION`。

请裁定：
1. 是否接受「scope 由 runtime 暴露、服务在 `_run_set` 里创建」这一位置？若要求 provider 自己申请或返回 scope 句柄，需要改 provider 契约。
2. `issue(scope=None)` 目前保持可选（兼容旧调用），生产路径一律传 scope。是否要求改为**必填**、彻底关闭无 scope 的签发路径？

## D2 一次 invocation 多条成功交换的情况

现状：`scope.latest()` 取该次调用最后一条交换；provider 当前是「一次响应产出两个候选」，重试只会产生更早的观测，因此 `latest()` 是成功的那个。

请裁定：若将来一个 invocation 内为多个候选各发一次请求，是否要求改成「按候选下标配对 + 数量不符即 fail closed」？本批未引入该形态，也未预先实现。

## D3 账本与业务仓储的两阶段提交窗口

现状：`commit_revision` 在业务事务提交**之后**写账本文件。若进程在两者之间崩溃，业务修订存在但父链不可用（方向是 fail closed，不会伪造父链），该候选需重跑才能当父修订。

请裁定：
1. 是否接受这一残余窗口，或要求把「已提交候选」做成可重建索引（重启时对账业务仓储重建父链登记）？
2. 若要求对账重建，需要明确「账本记录 vs 仓储行」的权威顺序与冲突处理，属新增机制，需单独授权。

## D4 `controlled_observations()` 是否保留

现状：作为审计只读视图保留，但已无任何签发路径使用（签发必须带 scope）。移除会减少一条「按项目取观测」的误用面，但会使审计导出少一个入口。

请裁定：保留为审计，还是移除。

## D5 与上一轮待决项的关系

上一轮 `W3-astra-r1-composition/decision-request.md` 的 D1（组合根注入形态）、D2（PG 数据面）、D3（反馈能力）、D4（`"controlled-stub"` 回落）、D5（真实模型授权）**仍未裁定**，本轮未改动相关代码，仍待复核。

## D6 本批定性

- 全部候选来源 `fixture`、`simulated=True`，**不计 AD01—AD08**，不是 AI 自动设计、不是客户成果、不是阶段 2 候选。
- `succeeded` 只表示流程跑完；未产生任何真实模型调用（`external_calls=0`、`cost_cny=0`、`keys_used=false`）。
- 未改 AD01—AD08、阶段确认、未知项与正式责任边界。
