# 本批代码差异（基线 4d2ac76）

`changes.patch` 区分 NEW（新文件）与 MODIFIED vs 4d2ac76。复核重点是差异，不是行数。

| 文件 | 类型 | 用途 | 行数 |
| --- | --- | --- | --- |
| `mvp/rkd_mvp/controlled_run_ledger.py` | 新增 | 受控运行账本：进程内密钥签发 HMAC、按 run_id 验签、项目/候选/父链绑定 | 142 |
| `mvp/rkd_mvp/realmodel_spatial_adapter.py` | 修改 | v3：场地快照逐项核对、来源账本验证、持久候选完整映射与损失、主轴/类型保真、顶层 v2 输出 | 1162 |
| `mvp/rkd_mvp/ai_design_option_provider.py` | 修改 | 站点声明入口点贯通生成与几何校审，不再硬编码侧边默认点 | — |
| `mvp/rkd_mvp/ai_spatial_outputs.py` | 修改 | 图例/标注不再称模型声明宽度为净宽；近方主轴画轮廓并标未验证 | — |
| `scripts/repro_w3_control_trust_negatives.py` | 新增 | 六项负例同例 before/after harness | 232 |
| `scripts/verify_w3_control_trust.py` | 新增 | 场地快照贯通、受控账本、完整映射、顶层 v2、图面、ZIP、回归综合验证 | 541 |
| `contracts/v2/ai-design-option.schema.json` | 新增 | 唯一权威顶层 v2 契约（spatial.oneOf 两分支） | 1494 |

**未改**：`contracts/v1/*`（旧 schema 保持只读与向后兼容）、AD、数据库迁移、NAS/PG/账号、旧复核包与证据。Windows CRLF 警告为换行规范化，不代表字节改动。
