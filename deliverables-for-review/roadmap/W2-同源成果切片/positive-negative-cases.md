# W2 同源成果切片 · 正负例与复现

证据：`checks.json`（7/7，真实 HTTP、隔离双库、本机 Blender）、`browser/verification.json`（passed=true）。
源是明确标记的本地夹具（`arc_first_batch_stub`），不是真实 AI 设计，不计入 AD。

## 正例

| 编号 | 输入/动作 | 预期 | 实际 |
| --- | --- | --- | --- |
| W2-01 | 对一个冻结的精确模型修订生成成果 | 平面/净量/成本/清单/包全部产出，任务 succeeded | job succeeded；6 个登记文件 + render.png（清单登记） |
| W2-02 | 逐文件下载 plan/render/csv/html/manifest/zip | 全部 200、字节非空、SHA 与登记一致 | 全部 200；manifest 与 artifact 登记的 sha256 均匹配 |
| W2-03 | 检查平面内容 | 含分区、面积表、图例、总尺寸、机位、未建模缺项、非施工图声明 | 全部命中（含 ZA1/F1 标注） |
| W2-04 | 非矩形净量独立复算 | 与精确多边形一致；bbox 结果不同且不用于计量 | 233.03 ㎡；独立复算 233.03；bbox 234.31（+1.28） |
| W2-05 | 没有价源时的成本 | 金额 unknown、不是报价 | known_items=[]、total=null、formal_quote=false |
| W2-06 | 两种布局走同一生成器 | 模型哈希不同、净量不同、各有平面与人眼图 | A 233.03 ㎡ / B 229.08 ㎡；两份 PNG 均产出 |
| W2-07 | 四种受控变更 | 见下 | 全部成立 |
| 浏览器 | 页面选修订→生成→看平面/人眼图/净量→下载 | 任务完成、图可见、缺项可见、SHA 一致、390px | `passed=true`；7 行净量；plan 10,022 B、render 1,033,426 B、zip 10,249 B；sha 一致；`page_errors=[]` |

## 四种受控变更（生成器级，同一冻结模型副本）

| 变更 | 结果 |
| --- | --- |
| 改几何（ZA2 收进 800mm） | 平面 SVG 改变、场景 JSON 改变、地坪净量从 233.03 变为更小值 |
| 改材料（给分区加 `finish_material`） | 平面配色/场景材质改变；净量不变 |
| 只改相机（位置 +3000mm） | 平面机位标注与场景相机改变；净量完全不变 |
| 只改单价（1000 → 1200 元/㎡ 假设输入） | 成本已知项金额增大；平面、场景、净量不变；总额仍 unknown、formal_quote=false |

> 单价是**调用方假设输入**，明确标 `caller_provided_assumption_not_a_quote`，不是价源、不是报价。

## 负例 / 边界（W1 收口已覆盖，本批回归）

| 情况 | 结果 |
| --- | --- |
| 旧矩形深化/量价链遇到 spatial 模型 | 422 `SPATIAL_MODEL_REQUIRES_PRECISE_PATH`（不据 bbox 算量） |
| 旧 rect 反馈链遇到 spatial 模型 | 422 同上（不静默降级） |
| 缺父 + `allow_orphan` | `parent=null`、`diff_baseline=unknown_missing_parent`、`diff=[]` |
| 非空间模型请求 W2 成果 | 422 `SPATIAL_PAYLOAD_REQUIRED` |
| 渲染器缺失 | 503 `RENDERER_UNAVAILABLE`（本机存在 Blender，未触发） |
| 渲染/生成失败 | job=failed + 诊断，不登记当前成果（无半份成果） |

## 复现

```bash
export PYTHONPATH="mvp;scripts;."
./.venv/Scripts/python.exe scripts/verify_w2_spatial_outputs.py \
  --out var/evidence/roadmap/W2-同源成果切片/after \
  --runtime var/evidence/roadmap/W2-同源成果切片/runtime
./.venv/Scripts/python.exe scripts/verify_w2_browser.py \
  --out var/evidence/roadmap/W2-同源成果切片/after/browser \
  --runtime var/evidence/roadmap/W2-同源成果切片/browser-runtime
```

渲染依赖本机 `tools/blender/blender-4.2.9-windows-x64/blender.exe`（Cycles CPU）；无网络、无外部图像通道。
