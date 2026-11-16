# 前后同例负例与正例（W3 control/trust）

复现 harness：`scripts/repro_w3_control_trust_negatives.py`（同一份夹具与判定，分别加载冻结 `4d2ac76` 与本批适配器）。证据：`var/evidence/roadmap/W3-control-trust-remediation/{before,after}/repro/repro.json`。综合验证 `scripts/verify_w3_control_trust.py` 与 `checks.json`。0 外部调用。

## 同例负例（before → after，均为实际执行）

| 编号 | 输入 | before | after |
| --- | --- | --- | --- |
| P1 入口错位 | 旧持久样本：入口 [0,10.3]、动线左端 [0,2.24] | 距离 8.06m，仍产出 | 新快照贯通后距离 0m；C-05 入口连通断言 |
| P1 保留区交叠 | 同一个旧样本 | path-south ∩ 楼梯 = 3.072㎡，仍产出 | 交叠 0；`CIRCULATION_BLOCKED_BY_KEEPOUT` 会在冲突时拒绝 |
| P1 伪来源/伪父链 | 自报 `kind=real_model_run,simulated=false` + 自算 SHA + 任意父 ID | 接受，标 real_model、父 `resolved` | 拒绝 `RUN_LEDGER_ABSENT`；账本伪造签名/跨项目/错误父 ID 另测全拒绝（C-09） |
| P1 设计事实损失 | 手工构造含关系、材料绑定、focal、未知 kind、非矩形的持久候选 | 关系 0、材料全 null、focal 丢、未知 kind 静默 | 关系 1、材料绑定保留、focal 保留、未知 kind/非矩形显式 unsupported（C-10） |
| P2 契约冲突 | 同一候选文档 | 顶层 v1 + 旧 schema 26 错误、无版本升级 | 顶层 v2；旧 v1 仍通过、v2 被旧消费者按版本拒绝（C-08） |
| P2 净宽图例 | 最终 plan.svg | "主动线（净宽 mm）"；近方零长线 | "主动线（模型声明宽度，非实测净宽）"；近方标未验证（C-14） |
| P2 无渲染包 | `--no-render` 输出 | 有 manifest+ZIP、无 render、未声明不完整 | 清单 `package_completeness=incomplete`，不登记完整成果（C-12） |

## 综合正例

| 编号 | 断言 | 结果 |
| --- | --- | --- |
| C-01 | 顶层 v2 是唯一权威可识别版本 | pass |
| C-02 | 同一场地快照：底图事实/概念假设/现场未知分离、哈希贯通 | pass |
| C-03 | 真实 provider 在快照上经几何校审产出 2 候选（0 外部调用） | pass |
| C-04 | 真实仓储写入读回 | pass |
| C-05 | 持久候选入口连通、动线不压保留区、边界/保留区逐项一致 | pass |
| C-06 | 来源由受控账本签发验签（simulated=true） | pass |
| C-07 0/1 | 两候选适配产物通过顶层 v2 契约 | pass |
| C-08 | 旧消费者回归 + 版本识别 | pass |
| C-09 | 伪造签名/跨项目/错误父 ID 拒绝 | pass |
| C-10 | 完整字段映射与损失清单 | pass |
| C-11 | 本地 Blender 人眼图（工程样张） | pass |
| C-12 | 最终包含 render，ZIP/清单逐项一致 | pass |
| C-13 | HTTP 下载 | **not_run**（未启动服务/浏览器） |
| C-14 | 图面净宽口径与近方显示 | pass |

`--no-render` 独立预跑：13 pass / 0 fail / 2 not_run（C-11、C-13），渲染与下载不计通过。

## 复跑

```
cd "D:/Github/RKD AI"
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/repro_w3_control_trust_negatives.py \
  --adapter "var/evidence/roadmap/W3-control-trust-remediation/before/code/realmodel_spatial_adapter.py" \
  --label before --out "var/evidence/roadmap/W3-control-trust-remediation/before/repro"
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/repro_w3_control_trust_negatives.py \
  --adapter "mvp/rkd_mvp/realmodel_spatial_adapter.py" --label after \
  --sample "deliverables-for-review/roadmap/W3-control-trust-remediation/outputs/model.json" \
  --plan "deliverables-for-review/roadmap/W3-control-trust-remediation/outputs/plan.svg" \
  --no-render-dir "var/evidence/roadmap/W3-control-trust-remediation/no-render-packet/outputs" \
  --out "var/evidence/roadmap/W3-control-trust-remediation/after/repro"
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/verify_w3_control_trust.py \
  --evidence "var/evidence/roadmap/W3-control-trust-remediation/after" \
  --out "deliverables-for-review/roadmap/W3-control-trust-remediation"
```
务必传新目录；脚本默认会重建指定 runtime 的 SQLite 并覆盖该目录输出，不覆盖旧批次。
