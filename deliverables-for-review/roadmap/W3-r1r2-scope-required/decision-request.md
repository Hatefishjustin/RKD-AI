# 待复核裁定（scope 必填收尾）

本轮不宣布 W3 通过、不宣布设计通过、不放行真实模型试验、不推进阶段或 W4。

## D1 错误形态

现状：遗漏 `scope` 由 Python 签名强制抛 `TypeError`；显式 `scope=None` 才返回领域码 `OBSERVATION_SCOPE_REQUIRED`。

请裁定：是否接受两种错误形态？若要求「所有遗漏形态统一领域码」，需把签名改回 `scope=None` 默认值并在函数入口校验，这会削弱签名层的强制力，属口径选择。

## D2 兼容性

`issue(scope=…)` 与 `register_and_issue(scope=…)` 现在是破坏性签名变更。仓内调用点与测试桩已全部检查更新；若有仓外集成方，需要同步传 scope。

请裁定：是否需要发布迁移说明或过渡期兼容层（本批未做，也不建议默默兼容，因为那会退回旧行为）。

## D3 历史 harness 的处置

`scripts/w3_trust_findings.py`、`scripts/verify_w3_trust_remediation.py` 是 before-only 工具，依赖已关闭的 `observe_exchange`，在当前代码上先于 `issue()` 失败。本轮保留原样以免破坏历史 before 证据的可复现性。

请裁定：是否要求把它们全部改造成「当前代码也能跑出 fixed」的现代 harness（工作量与本批小范围收尾不匹配，需单独授权）。

## D4 与上一批待决项的关系

`W3-r1r2-source-records/decision-request.md` 的 D1—D6（scope 形态、一次 invocation 多请求、两阶段提交窗口、`controlled_observations()` 去留、上一轮待决项、定性）仍未裁定，本轮未改动相关结论。

## D5 定性

- 全部候选 `fixture`/`simulated=True`，不计 AD01—AD08，不是 AI 自动设计或客户成果。
- `succeeded` 只表示流程跑完；未发生外部模型调用（`external_calls=0`、`cost_cny=0`、`keys_used=false`）。
- 未改 AD01—AD08、阶段确认、未知项与正式责任边界。
