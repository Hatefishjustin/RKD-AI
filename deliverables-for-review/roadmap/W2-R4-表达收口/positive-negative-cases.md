# 关键正负例与复跑结果

## A. 入口小修（上一批已受限通过，本批不重做）

- 整改前 `all_as_expected=True`、整改后 `all_as_expected=True`；证据 `entry-fix/`。
- 原 15 项回归 `15/15` （`entry-fix/regression-15.json`）。

## B. --no-render 报告语义（架构师点名）

- 空目录复现：`{"observed_pass": 12, "observed_fail": 0, "not_run": 2, "missing_evidence": 1}`、退出码 0；图像项 `not_run`、缺前置证据 `missing_evidence`，均不计产品失败。
- 完整渲染运行：15/15 observed_pass、0 not_run、0 缺证（`checks-source.json`）。
- 摘要分层：`verification_layers` = function_level / contract / http / external_evidence / real_render / browser / manual_visual。

## C. V1—V3 专项自动断言（与人工目检分列）

- `V1-A-01` 平面几何/编号/注释三层分离，坐标度量可复核 → **observed_pass**
- `V1-A-02` 受控尺寸链 X/Y 从边界经开口/平台站点闭合到总尺寸 → **observed_pass**
- `V1-A-03` 编号索引覆盖墙体/开口/相机/分区/动线/家具，引用可对账 → **observed_pass**
- `V1-A-04` 自动几何检查：图面标注无互相压叠、无出界、字号不低于 8 → **observed_pass**
- `V2-A-01` 玻璃为透明透射，发光玻璃板为 0，窗外为标注的本地假设 → **observed_pass**
- `V2-A-02` 木饰面与地面的纹理比例/分缝/收边来自版本化表达输入 → **observed_pass**
- `V2-A-03` 场景保留模型来源与假设标识，采光仍只来自已建模窗口 → **observed_pass**
- `V3-A-01` 对象分为源模型/CC0 表达资产/测试陈设/程序化表达四类 → **observed_pass**
- `V3-A-02` display-wing 占位件已替换为程序化展墙，黄色占位盒清零 → **observed_pass**
- `V3-A-03` 去掉全部测试陈设后：工程量/成本完全不变，平面与场景确实变化 → **observed_pass**
- `V1-B-01` 平面几何/编号/注释三层分离，坐标度量可复核 → **observed_pass**
- `V1-B-02` 受控尺寸链 X/Y 从边界经开口/平台站点闭合到总尺寸 → **observed_pass**
- `V1-B-03` 编号索引覆盖墙体/开口/相机/分区/动线/家具，引用可对账 → **observed_pass**
- `V1-B-04` 自动几何检查：图面标注无互相压叠、无出界、字号不低于 8 → **observed_pass**
- `V2-B-01` 玻璃为透明透射，发光玻璃板为 0，窗外为标注的本地假设 → **observed_pass**
- `V2-B-02` 木饰面与地面的纹理比例/分缝/收边来自版本化表达输入 → **observed_pass**
- `V2-B-03` 场景保留模型来源与假设标识，采光仍只来自已建模窗口 → **observed_pass**
- `V3-B-01` 对象分为源模型/CC0 表达资产/测试陈设/程序化表达四类 → **observed_pass**
- `V3-B-02` display-wing 占位件已替换为程序化展墙，黄色占位盒清零 → **observed_pass**
- `V3-B-03` 去掉全部测试陈设后：工程量/成本完全不变，平面与场景确实变化 → **observed_pass**

## D. 真实缺陷修正（先复现再修）

1. 短编号撞号：V3 新增 `R4-STG-PED-03` / `R4-STG-OBJ-03` 与 `R4-PROP-03` 旧算法都生成 `P03`，导致图面标签重叠且 `plan-index.json` 的 labels 互相覆盖。改为按类别前缀全局唯一分配（`plan_layers.furniture_codes`），并把 R4-03 断言改为按索引对账。修正后 A/B 自动几何检查均 0 重叠、0 出界。
2. 局部裁剪黑屏：`<img src=file://…>` 在 `setContent` 的 about:blank 源下被阻止加载，改用 base64 data URL，裁剪后为真实像素。
3. 图下方索引首版长字符串横向压到第二列：去掉图内冗余来源字段，完整说明移到 `plan-index-*.html` / `plan-index.json`。
4. 顶部标题与尺寸链说明重叠：合并为一行提示，链线下移。

## E. 浏览器与全量回归

- 真实 Edge：`passed=True`、390px 无溢出、下载 SHA 与 manifest/ZIP 一致（`browser/verification.json`）。
- 全量单测与前端构建：`runtime/full-unittest.log` / `tsc.log` / `frontend-build.log`。
