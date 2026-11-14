# TEXT-01 独立复核

日期：2026-11-14。HEAD db9121e，业务实现48afd01，比较基线5571e4e；检查开始工作区干净。

## 结论

限定整改，W0暂不放行，W1—W4暂不开始。原三项复现已修复，本轮独立执行14个函数案例全部fixed_signature、12项真实HTTP验收全部通过。不得据此声称任意普通文字都能正确理解；新增边界证明同一共用解析路径仍可能反转或遗漏要求。

不推翻已有五项整改，不重做总体架构。最后收口目标是保守正确：支持范围内准确解析，范围外保留unknown/pending，不能把不完整理解标resolved。无需实现完整中文语义系统。

## 独立证据与范围

- `scripts/text_feedback_cases.py --phase after --out var/evidence/roadmap/TEXT-architect-review/cases.json`：14 fixed_signature。
- `scripts/verify_text_http.py --out var/evidence/roadmap/TEXT-architect-review/http --runtime var/evidence/roadmap/TEXT-architect-review/runtime`：12 pass、0 fail，隔离库、本地模型桩。
- 静态阅读revision_task共用解析、绑定、比较符和子句处理。另直接调用实际parse_text_requirements、现有valid_proposal夹具，新增三个函数级边界案例，见本目录boundary-cases.json；不冒称浏览器实测。
- 未独立重跑浏览器、全量262项或构建；执行者报告与架构师独立证据分开。历史证据未覆盖。

## 剩余整改（同属TEXT-01）

### P1：否定要求被反转为正向目标

输入：`不要把 F3 旋转到 -30 度`。
实际：生成computable=true、exact -30、object_ids=[F3]，没有pending。
原因：模式在句中匹配“旋转到…”后，没有核查否定作用范围。
要求：明确支持的否定可转为正确约束；否则整项unknown/pending，禁止形成与原句相反的可执行目标。不要简单把所有含“不”的句子拒绝，因为“不超过/不小于”是已有支持比较符。

### P1：存在与不存在的对象并列时，缺失对象被吞掉

输入：`把 F1 和 F9 旋转到 -30 度`。
实际：只保留F1，binding_status=resolved、pending=[]。单独F9测试虽通过，并列时_measurable_binding先返回已找到ids，未处理unknown_ids。
要求：保留全部点名引用；缺失对象明确fail或未解析阻断，不能部分解析即宣布整项绑定成功。补存在+缺失、仅缺失、存在+歧义等组合。

### P2：同一子句的剩余诉求仍然被吞掉

输入：`把 F3 旋转到 -30 度并让整体更有设计感`。
实际：只有数值目标，pending=[]。parse_text_requirements匹配数值后把整个子句consumed=True，遗漏未匹配尾部；用户不输入逗号就触发。
要求：跟踪已解释文本片段与残余片段；残余实际诉求保留原句与unknown/pending。不能依赖用户每次恰好输入标点，也不能只针对“设计感”加一条补丁。无需把残余自动翻译成可计算目标。

## 一次性收口验收

保留14/12回归，新增上述三类普通text入口的HTTP正负例，不手填objectives/locks。至少覆盖否定与“不超过”的区别、并列对象部分不存在、无逗号复合句；检查结果不反转、不漏对象、不吞剩余诉求。浏览器验证其中一个正常文字输入。失败/未解析与用户待确认必须在证据中可见。

本次集中修复“语义覆盖与保守拒绝”，不要继续堆同义词补丁。未知表达允许unknown；不要求所有表达都变成成功修订。这是现有TEXT-01边界，不新增产品任务或验收分母。

## 直接交给执行AI

```text
请继续TEXT-01限定整改，先读：
D:\Github\RKD AI\deliverables-for-review\roadmap\TEXT-architect-review\architect-review.md
以及同目录boundary-cases.json。
14个函数案例与12项HTTP验收已获架构师独立通过，保留这些成果。W0仍未放行：修复否定反转、存在与缺失对象并列时漏项、同一子句未解析尾部被吞掉这三个共用解析边界。实现“已解析片段/未解析片段+完整对象引用”的保守判定，不继续只堆特定句子的正则补丁；不能准确理解时unknown/pending，不能变成相反目标。
补普通text HTTP正负例和至少一条浏览器路径，不手填结构化目标冒充解析成功；回归原14/12案例与受影响测试。保存新目录 D:\Github\RKD AI\deliverables-for-review\roadmap\W0-文字反馈保守判定\，更新PROJECT_STATUS.md后交架构师复核。不改AD，不开始W1—W4，不扩管理功能，不新增付费调用，不覆盖旧证据。
```

## 交付与边界

本轮仅审查、隔离复验、保存文档和JSON，没有修改业务代码；未生成设计成果，因为本轮处理工程正确性。
仍不像设计公司成果的地方：没有新增客户级平面、人眼效果图、完整图纸PDF；统一模型到渲染/量价尚未贯通，真实设计仍待用户确认。工程通过不冲抵这些差距。
外部模型调用0、外发图片0、生成设计图片0、新增外部费用0。
