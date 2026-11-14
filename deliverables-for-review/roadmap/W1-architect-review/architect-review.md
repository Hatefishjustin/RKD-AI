# W1 架构复核：限定修复版本身份后再进入 W2

日期2026-11-14；HEAD 080f63e，业务提交46e9c1b，基线cb84581。开始时工作区干净。

## 结论

W1是有效进展：已有主系统正式导入、精确多边形载荷、对账与页面入口。独立运行verify_w1_unified_model.py，22项HTTP验收全部通过。但**暂不放行W1进入W2**：版本身份与父链仍按导入顺序推断，不能证明源候选谱系被正确保留。限定修复本节问题，不重做整个适配器。

独立证据：D:\Github\RKD AI\var\evidence\roadmap\W1-architect-review\after\checks.json；本目录checks.json为副本。使用独立runtime、双库及本地夹具，无外部调用。静态检查适配器、导入事务和adopt；未独立重跑浏览器、262全量或构建，执行者报告不可算本轮独立验证。

## W1-R1 / P1：候选身份与父版本不能由字母和导入先后决定

定位：mvp/rkd_mvp/ai_design_option_service.py，import_studio_proposal的option_id构造与latest_revision查询（约418—434行）。

当前option_id为studio:主项目:Studio项目:字母，未包括源候选谱系身份；parent_revision_id直接取该字母最新导入。source.parent_revision_uid虽然保存在spatial中，却未用于建立主系统父链。

直接后果（静态可确定）：独立生成的两组A会成为同一候选连续版本；先导入较新的源稿、再导入旧稿，会将旧稿接到新稿后面；从同一旧稿分叉的两次修改也被串成先后关系。源candidate_group_id随续改run可能变化，因此不能只机械加当前组ID，必须解析根候选/明确源谱系。

现有验收并未覆盖正确父链：scripts/verify_w1_unified_model.py:134的save_valid对所有源稿都写parent_revision_uid=None；W1-06导入v2时仍期待主系统父指向上一导入。这证明测试验证的是“导入顺序”，不是源父子关系。

整改：建立源项目+源revision_uid到主系统revision ID的显式映射；候选身份依据稳定根谱系，A/B仅显示名称。源父未导入时明确拒绝/要求导入父，或采用有清晰来源的缺父状态，不能伪造父关系。不同根的对象ID须在候选范围隔离；同根修订对象稳定。相同源重试幂等，分叉/乱序不改历史。

验收：两组独立A；同父两个分叉；旧稿晚导入；父未导入；A/B及跨项目；同谱系正常v1→v2。至少HTTP层验证源UID→目标ID和父链，不仅检查数字版本递增。修正夹具真实父UID，不靠修改预期绕过失败。

## W1-R2 / P2：写事务内需要重检导入基线与幂等

当前先在读事务算latest/revision_no/幂等，再生成SVG，最后开启写事务直接insert。两个并发请求可能基于相同旧版本完成计算；现有“旧版本并发采用”测试只验证adopt CAS，不覆盖import竞态。

整改：在提交事务中重新检查同源幂等及谱系预期版本。冲突明确返回可解释结果或复用已提交同源版本，不暴露原始唯一约束异常。测试使用屏障让两个导入读到相同前态；覆盖同源并发与同谱系不同子版本，失败无半条记录或遗留文件。文件清理只能删除失败尝试自身产物。此项是现有导入正确性，不扩基础设施。

## W2衔接约束（本轮不授权开始）

精确spatial与legacy bbox共存可作为过渡，但W2必须从spatial生成平面、三维与数量，不能把标注losses当作允许用bbox计量的许可。需要检查旧feedback/adopt/深化入口：不支持spatial的消费者应明确拒绝或选择精确适配路径，不能把它带入旧矩形链后输出貌似有效成果。

DB source_kind=human_edit属于已披露兼容取舍；spatial.source.origin_kind=studio_import只说明传输路径，不说明设计是模型还是人工。W1修复时核对并携带源设计来源（真实模型/人工/夹具/unknown）与运行引用，不能因为适配器不是AI就把上游真实AI产出改称人工。后续展示和统计优先使用明确来源，无法确定保持unknown。

材料、相机、照度、实测高度未建模保持unknown是合理的本批限制；不要求为W1伪造这些值。PG未验收不等于允许正式切库，保持当前本机范围。

## 给执行AI的提示词

```text
继续W1限定收口，先读：
D:\Github\RKD AI\deliverables-for-review\roadmap\W1-architect-review\architect-review.md
22项现有HTTP验收已由架构师独立通过，不重做适配器。修复W1-R1源候选谱系/父UID映射及W1-R2写事务内并发幂等重检。补真实父UID夹具与独立A、分叉、乱序、缺父、同源并发、同谱系并发HTTP证据；不按导入顺序伪造父链。
同时核对设计来源与适配来源分开保留，保留精确spatial权威及bbox损失声明。不要启动W2制图渲染、不扩基础设施、不新增外发或费用、不改AD。
在现有范围连续完成修复、回归和必要页面验证，更新PROJECT_STATUS.md，交 D:\Github\RKD AI\deliverables-for-review\roadmap\W1-版本谱系收口\。提交后由架构师复核，不能自行宣布W2放行。
```

## 本轮工作与差距

仅审查、独立隔离验证并新增交接文档，没有修改业务代码。未生成设计图，因为本轮核验模型工程边界。仍缺客户级图纸、人眼效果图、材料灯光表达和同源量价；目前概念SVG不能算设计公司完整成果，用户设计认可和AD不变。

本轮外部模型调用0、外发图片0、新生成设计图片0、新增外部费用0。
