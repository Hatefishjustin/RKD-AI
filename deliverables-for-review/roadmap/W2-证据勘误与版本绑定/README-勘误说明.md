# W2 证据漂移勘误与阶段1 版本绑定准备（静态文档批次）

编制：2026-11-16 · 审查 HEAD `86e08b02e00e886cb43f6961bd2dad46398894fd`（工作区此前仅有未跟踪的 `W2-gate-architect/`）。

**性质**：本批次只新增/修改文档，不运行设计模型、不生成图像、不改业务代码、不改契约、不改原件、不改 AD、不推进用户项目阶段 2、不启动 W3/W4。外部模型请求 0、外发 0、新增图 0、费用 0、密钥未使用未落盘。

**依据**：架构师 `deliverables-for-review/roadmap/W2-gate-architect/review-and-handoff.md`「证据问题：旧复核包当前不再自洽」与「字段清单的架构校正」两节；`docs/26` 第 6 节「不为文案一致回写历史证据，补充勘误记录即可」。

## 一、为什么有这一批

架构师指出：`W2-R4-表达收口/manifest.json` 对 `basemap-confirmation-card.md` 登记的字节/SHA 与 HEAD 当前同路径文件已不匹配，逐文件校验必然失败。新增修订留痕是诚实的，但不能让旧 manifest 对当前字节重新成立。故按"新批次保存便携副本 + 勘误、旧包原样不动"处理。

## 二、失配的精确事实（已用 Git 与哈希实测核对）

| 对象 | 字节 | SHA-256 | 说明 |
| --- | --- | --- | --- |
| 旧包 `W2-R4-表达收口/manifest.json` 对确认卡的登记值 | 4761 | `4b7cb1d76d3c6f88d78df5f7d51a03f5989abe92ba5e1595f752cf01aece42f5` | 经 `git show f6b8145:.../basemap-confirmation-card.md` 实测正是该历史快照，即提交 `f6b8145` 时的字节 |
| HEAD `86e08b0` 当前 `W2-R4-表达收口/basemap-confirmation-card.md` | 7778 | `9ef6aa30986ed30af54338bfbbb9ac998eea55b0f8e1bf71a91c636cfb7729c4` | 2026-11-16 只改第五节确认口径后的版本 |
| 本批次便携副本 `W2-证据勘误与版本绑定/basemap-confirmation-card.md` | 7778 | `9ef6aa30986ed30af54338bfbbb9ac998eea55b0f8e1bf71a91c636cfb7729c4` | 与 HEAD 当前卡片逐字节一致，供便携引用 |

结论：失配是**同一路径在两次提交间的字节变更**，不是伪造。旧 manifest 是对 `f6b8145` 历史快照的真实登记；HEAD 卡片是后续文书修订的真实结果。两者不能同时成立。

## 三、本批的处理边界（严格遵守）

1. **旧包与运行证据保持现状、不再覆盖**：`deliverables-for-review/roadmap/W2-R4-表达收口/` 下的 `manifest.json`、`basemap-confirmation-card.md`、`checks.json`、`outputs/`、`browser/`、`render-compare/` 等一律不改字节；`var/evidence/roadmap/` 下同名批次运行证据同样不动。
2. **不把旧包全量校验写成通过**：今后凡引用 `W2-R4-表达收口/manifest.json`，必须同时说明「该包对 `basemap-confirmation-card.md` 一项与当前 HEAD 失配，非全量当前校验通过」。本批 `manifest.json` 只校验**本批次便携副本**，不对旧包作出通过结论。
3. **不改写提交、不回写历史**：不以当前卡片覆盖旧 manifest，也不重写历史。
4. **便携性**：当前确认卡副本与本批勘误放在同一新目录，便于整目录拷贝送审；引用时只认本副本的完整 SHA。

## 四、本批包含的文件

| 文件 | 作用 |
| --- | --- |
| `README-勘误说明.md` | 本文件；漂移事实与处理边界 |
| `basemap-confirmation-card.md` | 当前确认卡便携副本（7778 字节，`9ef6aa30…`） |
| `stage1-recognition-trace.md` | 阶段1 原始认可话语追查结论与一次简短版本绑定请求 |
| `field-coverage-erratum.md` | 字段清单 rect 四角投影/非矩形、真实模型来源的勘误 |
| `manifest.json` | 本批文件字节/SHA 清单，校验便携副本；记录旧包例外 |

## 五、仍待用户/架构师决定（不代签）

- 阶段1 底图版本绑定：见 `stage1-recognition-trace.md`，**未获用户明确结论前停在阶段1 边界**。
- 字段清单两处口径修正：见 `field-coverage-erratum.md`，属文档勘误，不改工程结论。
- 下一批真实设计验证范围与费用/资料授权：仍由架构师在用户绑定底图版本后单独下发；本批不新增授权。
