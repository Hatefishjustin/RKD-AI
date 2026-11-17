# W3 场地与来源整改架构复核

日期：2026-11-17；审查提交 `2253899`。**结论：本批离线样例有进展，但场地快照贯通、来源可信和几何保真未通过；不接受 v2 为已接入的权威生产契约，不放行真实模型试验。** 用户阶段1底图确认有效，未知项继续保留；阶段2方案、AD 和 W4 未获通过。

## 必须修复的发现

1. **[P1] 动线在同一模型内被破坏。** `mvp/rkd_mvp/realmodel_spatial_adapter.py:858` 从中心线重构 legacy `circulation.segments` 时一律按横向矩形计算。交付 `outputs/model.json` 的 `path-west` 在 `spatial.circulation` 中是纵向 4.1m 动线，但 legacy 同 ID 的 `shape.width` 为 `0`、长度仅 `1.2m`；横向路径 Y 也从中心线而非原矩形边界起算。v2 schema 通过不代表两套几何一致，后续校验/显示/导入可能错误。保留原始矩形或做可逆的方向感知变换；逐字段核对源、legacy、spatial、图面，覆盖横/竖/近方、连接和面积，禁止零宽退化。
2. **[P1] 账本不构成可信签发边界。** `controlled_run_ledger.py:64` 的公开 `issue()` 接受任意 `kind=real_model_run, simulated=False` 和调用者自报的输入、输出及父链；`verify_source` 接受调用者传入任意账本对象。独立直接创建账本并对离线夹具签发伪真实运行、伪父修订，`verify_source` 返回 `generation_real_model=True`、`parent_verified=True`。签名只能证明该实例签过调用者给的内容，不能证明调用真实模型或父版本存在；进程内密钥重启即失，历史记录也无法独立验证。未经受控服务的真实运行和持久仓储查验，一律不得升级为真实来源。先建立并说明真正的信任边界：签发仅由受控服务在核验实际请求/响应、项目、父版本和候选后执行，消费者只能注入受控只读验证能力；拒绝随意创建账本、自签伪真实记录、伪造父 ID、跨项目和篡改。需要支持重启后的核验策略，或明确重启后状态为 unknown；本轮不必为此扩展账号、NAS 等平台。
3. **[P1] 快照哈希没有贯通，模型请求缺关键场地信息。** 交付 `checks.json.site_snapshot_sha256` 为 `4001a426…`，`outputs/model.json.site_snapshot.sha256` 为 `db6c0b9a…`；后者实际上是底图文件清单摘要（`realmodel_spatial_adapter.py:747,1045`），并未绑定完整入口假设和未知项。成果 manifest 也没有该快照字段。`ai_design_option_provider.py:_design_messages`（约 760 行）只发送边界和障碍，没发送 `site.entrance.point` / 快照哈希，仍附带固定 12×8 米的 `LEGAL_PATH_EXAMPLE`。本地桩预先知道坐标，不能证明真实模型收到了入口。定义规范化完整快照和哈希计算规则，在实际模型请求、运行记录、候选、适配输出、成果 manifest 核对同一哈希；底图文件摘要另命名。捕获并检查本地桩实际请求正文：包含入口位置、假设、保留区、尺寸及来源；与该场地冲突的 12×8 示例不得误导模型。更改入口/障碍/假设后哈希必须变化；旧请求、重绑或内容不符必须拒绝或明确失效。
4. **[P1] 校验可被绕过且结果未成为实际服务门槛。** `adapt_persisted_candidate(... skip_site_integrity=True)` 可直接跳过场地/几何检查；`adapt_candidate` 也不执行持久候选检查。当前新账本、快照和适配只在验证脚本接线，既有 `ai_design_option_service.py:30,62` 仍只加载旧 v1 schema。不得声称正式用户路径已具备这套门槛。实验与正式路径须隔离，正式候选只能经过同一受控入口、场地及模型版本检查；任何跳过入口只可用于明确标 `not_validated` 的隔离测试，不能登记、采用或作为有效候选。验证实际服务入口或明确交付阻塞证据；保留当前用户可操作范围的真实回归。
5. **[P2] 不完整 ZIP 自身校验失败。** 独立运行 `--no-render` 输出含一个嵌套 `package.zip`（外包里又含旧包），现有 `check_zip_against_manifest` 返回 `ok=false`，问题为未登记文件 `package.zip`。C-12 只检查字符串 `incomplete` 和缺 render，忽略已算出的 `zcheck`。`scripts/verify_w3_control_trust.py:479` 应由同一最终文件集合和唯一 manifest 一次性生成 ZIP，禁止把 ZIP 放进自身；不完整包同样须逐项通过字节一致性，且由实际登记/下载边界拒绝当作完整包。完整、无渲染、渲染失败、取消各留证；HTTP 未测继续标 not_run。
6. **[P2] 兼容性与表述。** 顶层 v2 版本区分是合理的设计方向，但新增 schema 本身不能证明已成为权威契约或旧消费者按版本专门拒绝。C-08 仅验证 v1 样本旧 schema 无错误并检查版本不等，没有调用真实消费者处理 v2；正式服务目前仍固定 v1。对真实消费者测试旧版继续可用、v2 明确报不支持版本，以及升级后的 v2 读写、采用、历史回归；迁移方案经复核前继续标实验。明确矩形声明宽度仍非实测净宽，近方主轴不作为已验证连通。

## 独立复核证据

- `scripts/verify_w3_control_trust.py --no-render` 在新目录 `D:\Github\RKD AI\var\evidence\roadmap\W3-trust-architect\` 执行：13 pass / 0 fail / 2 not_run；两项为 Blender 和 HTTP。未独立重跑 262 单测、Blender、浏览器或真实模型。
- 针对账本直接调用 `ControlledRunLedger.issue(real_model_run, simulated=False, ...)` 加 `verify_source`，伪真实来源及任意父链均被标验证通过；没有外部调用或伪造真实文件。
- 打开本批样本，发现纵向 `path-west` legacy 宽度为 0，原 spatial 为 4.1m 纵线；并对比审计与模型快照哈希，发现两者不同。
- 独立检查本轮 no-render 包：ZIP 多出内嵌 `package.zip`，清单校验 `ok=false`。成功渲染样本另含 `render.png`，本轮未重渲染。

## 给执行 AI 的提示词

```text
阅读 D:\Github\RKD AI\deliverables-for-review\roadmap\W3-trust-architect\review-and-next.md 及 PROJECT_STATUS.md，以 2253899 为基线，先在新的隔离证据目录复现六项发现，再修复同例复跑。必须包括：纵向 legacy 矩形零宽、公开 issue 自签伪真实运行及任意父链、完整快照哈希不一致、实际模型请求缺入口与旧12×8示例、绕过场地校验、无渲染 ZIP 内嵌自身且清单校验失败。不能只断言中间字段或脚本伪造的输出。

将底图文件摘要与完整场地快照摘要分开命名并贯穿真实请求、持久候选、适配、成果；用实际协议桩捕获请求验证，同一哈希与数据逐项对账。运行来源需要实际受控服务与仓储产生的证据；没有可信证据时保持 unknown。覆盖源与所有投影的几何和身份一致；完整/不完整 ZIP 均通过清单校验且不能冒充完整。验证真实消费者是否支持 v2 和旧版本，仍未接通的路径列明确阻塞。保持原设计来源、阶段确认和未知项口径，不扩大 NAS/账号/W4，不调用外部模型，先交架构复核。
```

## 设计差距与费用

现有成果仍为本地协议桩灰盒样张，分区矩形，缺真实材质、产品细节、软装、人物、窗光和客户级完整成果。本轮仅做架构审查及文档记录，未修改业务代码，外部调用 0、外发 0、新增图片 0、费用 0。
