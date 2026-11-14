# ARC 首批正负例清单

来源：`var/evidence/architecture-handoff/first-batch/after/q-checks.json`；每个 case 的 detail 为机器可读实数。

| 名称 | 类型 | 关键结论 |
| --- | --- | --- |
| Q01 契约负例 7 项 | negative | {"missing_role": {"rejected": true, "stage": "structure", "error_count": 1, "rules": ["CONTRACT-STRUCT"], "has_actionable_feedback": true},  |
| Q01 契约正例 | positive | ok=true |
| Q02 100㎡/3㎡ 负例 | negative | ok=false; explicit_97sqm_unallocated=true |
| Q02 完整布局对账正例 | positive | {"site_area_sqm": 468.966, "reserved_area_sqm": 38.799, "design_scope_sqm": 430.167, "area_table_sum_sqm": 430.167, "reconciliation_gap_sqm" |
| Q03 分离三角形正例 | positive | GEO_004_reported=false |
| Q03 四类几何负例 | negative | {"real_intersection": {"ok": false, "rules": ["GEO-004", "AREA-001", "AREA-003", "STD-005"]}, "self_crossing": {"ok": false, "rules": ["GEO- |
| Q04 broken_route | negative | ok=false |
| Q04 obstacle_crossing | negative | ok=false |
| Q04 reserved_bathroom_changed | negative | ok=false |
| Q04 furniture_rotated_footprint_in_keepout | negative | ok=false |
| Q04 unknown_catalog_rejected | negative | ok=false |
| Q04 measured_bottleneck | negative | ok=false |
| Q05 长方案末尾对象可达 | positive | {"chars": 4706, "tail_reachable": true, "truncations": []} |
| Q06 同质候选负例 | negative | {"rename_only": {"substantive": false, "reason": "结构签名相同：仅换名/配色/顺序或无意义位移不算新拓扑"}, "reorder_only": {"substantive": false}, "trivial_shift_only |
| Q06 真实不同拓扑正例 | positive | substantive=true |
| Q07 反馈→修订正例 | positive | object_retention_ratio=1.0; feedback_in_ctx=true |
| Q08 无对象diff/无理由删除/锁定改动/身份patch负例 | negative | {"accept_without_diff": {"ok": false, "rules": ["REV-UNRELATED", "REV-ISSUE", "REV-ISSUE", "REV-ISSUE", "REV-ISSUE"]}, "delete_without_reaso |
| Q09 闸口重放负例 | negative | applied=false |
| Q09 晚到结果失效负例 | negative | feedback_changed=true |
| Q11 重启与种子幂等正例 | positive | seed_did_not_rewrite_facts=true |
| Q12 流程跑完不等于设计通过 | positive | {"run_statuses": ["succeeded"], "run_status_meaning": "succeeded 只表示流程跑完，不等于设计通过", "artifact_statuses": ["draft", "valid_candidate"], "contr |

## Q 结果

- Q01: observed_pass — 契约有效才进入有效候选；缺role/错类型/无效引用/批准字段被定位；历史保留
- Q02: observed_pass — 面积唯一口径：100㎡/3㎡ 显式指出 97㎡ 未分配；完整布局对账；补通道不再自相矛盾
- Q03: observed_pass — 实际几何：分离三角形不报相交；真实交集/自交/越界/零面积正确拒绝
- Q04: observed_pass — 通行与锁定：断路/障碍/瓶颈/入口不可达/保留卫生间/目录引用均有定位
- Q05: observed_pass — 完整交接：超旧截断长度的末尾对象可被评审/修订读取；基线ID与issue_id明确
- Q06: observed_pass — 多方案实质不同：换名/换色/顺序/无意义位移不算新拓扑
- Q07: observed_pass — 页面反馈进入版本化有效需求，形成绑定原基线的新修订和真实对象 diff
- Q08: observed_pass — 意见逐项对应、拒绝有理由、删除/锁定/身份负例被拒、返工上限仍为2
- Q09: observed_pass — 项目/版本/闸口隔离：切项目不显示宁波、晚到结果失效、决定重放不覆盖
- Q10: not_run — 同源成果真实可用（后续适配批）
- Q11: observed_pass — 重启保留反馈/任务/闸口/检查报告；种子不重写项目事实、不重复事实
- Q12: observed_pass — 工程完成不自动设计通过；来源明确；未确认不生成下一阶段交付；AD 不改判

合计：{"observed_pass": 11, "observed_fail": 0, "not_run": 1}
