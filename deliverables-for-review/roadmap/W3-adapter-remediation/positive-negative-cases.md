# 前后同例负例与正例（R01—R06）

复现脚本 `scripts/repro_w3_adapter_negatives.py`；同一 harness、同一夹具，分别加载冻结基线 `dcc11f7` 代码与本批 v2 代码执行。证据：`var/evidence/roadmap/W3-adapter-remediation/{before,after}/repro/repro.json`；综合验证 `checks.json`。0 外部调用。

## 同例负例（before → after）

| 编号 | 同一输入 | before（dcc11f7 实测） | after（v2 实测） |
| --- | --- | --- | --- |
| R01a | `site.keepouts=[]` 仍声称 v2 | 接受，输出 0 保留区 | 拒绝 `KEEPOUT_SET_MISMATCH` |
| R01b | 入口点改 `[0,1]` 且未声明假设 | 接受，写成底图入口 | 拒绝 `ENTRANCE_ASSUMPTION_UNDECLARED` |
| R02a | `design_origin=real_model`、`run_refs=['invented']` | 接受，real_model 与 generation=false 矛盾 | 拒绝 `RUN_RECORD_MISSING` |
| R02b | `provenance.sha256` 全 0 | 接受并写入来源 | 拒绝 `CANDIDATE_SHA_MISMATCH` |
| R02c | `parent_revision_id='invented-parent-uid'` | 接受并标 `source_parent` | 拒绝 `PARENT_UNVERIFIED` |
| R04a | 1.4×7.6m 纵向 `path-west` | 输出横向 `[[2200,11200],[3600,11200]]` | 输出纵向，is_vertical=true |
| R04b | `circulation_kind='branch'` | 输出 `loop` | 输出 `branch` |
| R06 | 材料名与墙类型变化后的 diff | 0 字段 | 6 条字段级/对象级差异 |

## 综合正例（comprehensive verifier）

| 编号 | 断言 | 结果 |
| --- | --- | --- |
| V-01 | v2 契约/输出 schema 合法 | observed_pass |
| V-02 | 从哈希验证 JSON+SVG 提取保留区/边界/入口/未核项并逐项一致 | observed_pass |
| V-03 | 独立手算：分区∩卫生间保留区 = 4.0㎡（非零） | observed_pass |
| V-04 | 真实 provider + 本地协议桩产出 2 候选（模拟，0 网络） | observed_pass |
| V-05 | 真实仓储写入读回 objects[].shape / circulation.segments | observed_pass |
| V-060/61 | 两候选经持久候选路径适配、schema 0 错误、来源=fixture、real_model=false | observed_pass |
| V-07 | 横/纵/近方动线保真；近方 unknown；净宽 model_declared_unverified | observed_pass |
| V-08 | branch/loop 保真 | observed_pass |
| V-09 | 伪来源/错 SHA/伪父链拒绝 | observed_pass |
| V-10 | fixture/human/unknown 来源标签保留且 real_model=false | observed_pass |
| V-11 | diff 覆盖材料/来源/场地/语义 | observed_pass |
| V-12 | 对象丢失与父链变化报告为差异/损失 | observed_pass |
| V-13 | 本地 Blender 人眼图（工程样张） | observed_pass |
| V-14 | render 进入最终 ZIP/清单并重开校验 | observed_pass |
| V-15 | 下载 ZIP 图像字节与独立渲染一致 | observed_pass |
| V-16 | 输出集 SHA 登记；必需文件口径明确 | observed_pass |
| V-17 | 旧 schema 26 项错误逐条登记（不称兼容） | observed_pass |

`--no-render` 预跑：V-13/V-14/V-15 = **not_run**，不计通过；15 pass / 0 fail / 3 not_run。

## 复跑

```
cd "D:/Github/RKD AI"
# before：使用冻结代码（已存于 var/.../before/code）
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/repro_w3_adapter_negatives.py \
  --adapter "var/evidence/roadmap/W3-adapter-remediation/before/code/realmodel_spatial_adapter.py" \
  --label before --out "var/evidence/roadmap/W3-adapter-remediation/before/repro"
# after
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/repro_w3_adapter_negatives.py \
  --adapter "mvp/rkd_mvp/realmodel_spatial_adapter.py" \
  --label after --out "var/evidence/roadmap/W3-adapter-remediation/after/repro"
# 完整验证（含渲染）
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/verify_w3_adapter_remediation.py \
  --evidence "var/evidence/roadmap/W3-adapter-remediation/after" \
  --out "deliverables-for-review/roadmap/W3-adapter-remediation"
```
