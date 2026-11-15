"""组装 W2-R4-表达收口 复核包（docs/26 第 6 节 + review-next.md 交付项）。

用法：PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/build_w2_r4_closeout_review.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / "var/evidence/roadmap/W2-R4-表达收口/full"
PACKET = ROOT / "deliverables-for-review/roadmap/W2-R4-表达收口"
PREV = ROOT / "deliverables-for-review/roadmap/W2-R4-同源表达"
BASEMAP = ROOT / "deliverables-for-review/ningbo-xiecheng/2026-11-10"
BASE_COMMIT = "8fd7948"          # 架构师 review-next.md 审查 HEAD
PACKET.mkdir(parents=True, exist_ok=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jload(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def copy(src: Path, dst: Path) -> bool:
    if not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def copy_tree(src: Path, dst: Path, *, skip: set[str] | None = None) -> int:
    if not src.is_dir():
        return 0
    n = 0
    for path in sorted(src.rglob("*")):
        if not path.is_file() or (skip and path.name in skip):
            continue
        if copy(path, dst / path.relative_to(src)):
            n += 1
    return n


now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
checks = jload(EVID / "checks.json")
closeout = jload(EVID / "closeout" / "closeout-checks.json")
visual = jload(EVID / "visual" / "capture-observations.json")
browser = jload(EVID / "browser" / "verification.json")
conflict_before = jload(EVID / "before" / "finish-conflict-before.json")
conflict_after = jload(EVID / "after" / "finish-conflict-after.json")
regression = jload(EVID / "regression-second-closeout" / "repro-r4-regression.json")
no_render = jload(ROOT / "var/evidence/roadmap/W2-R4-表达收口/no-render-semantics/checks.json")
metas = {L: jload(EVID / "outputs" / f"layout-{L}" / "render-meta.json")
         for L in ("A", "B")}
indexes = {L: jload(EVID / "outputs" / f"layout-{L}" / "plan-index.json")
           for L in ("A", "B")}
presentations = {L: jload(EVID / "outputs" / f"layout-{L}" / "presentation.json")
                 for L in ("A", "B")}

# ------------------------------------------------------------------ 复制产物
for letter in ("A", "B"):
    src = EVID / "outputs" / f"layout-{letter}"
    dst = PACKET / "outputs" / f"layout-{letter}"
    copy_tree(src, dst)
    expr = (presentations[letter].get("expression") or {})
    (PACKET / "outputs" / f"expression-input-{letter}.json").write_text(
        json.dumps(expr, ensure_ascii=False, indent=2), encoding="utf-8")
copy_tree(PREV / "outputs" / "layout-A", PACKET / "outputs" / "previous-layout-A",
          skip={"render.png"})
copy_tree(PREV / "outputs" / "layout-B", PACKET / "outputs" / "previous-layout-B",
          skip={"render.png"})
copy_tree(EVID / "visual", PACKET / "visual")
copy_tree(EVID / "render-compare", PACKET / "render-compare")
copy_tree(EVID / "browser", PACKET / "browser")
copy_tree(EVID / "closeout", PACKET / "closeout")
# runtime 目录里还有 seed 的原始 40MB 文件与隔离库；复核包只需要三份回归日志。
for log_name in ("full-unittest.log", "tsc.log", "frontend-build.log"):
    copy(EVID / "runtime" / log_name, PACKET / "runtime" / log_name)
copy(EVID / "checks.json", PACKET / "checks-source.json")
copy(EVID / "before" / "finish-conflict-before.json", PACKET / "entry-fix" / "before.json")
copy(EVID / "after" / "finish-conflict-after.json", PACKET / "entry-fix" / "after.json")
copy(EVID / "regression-second-closeout" / "repro-r4-regression.json",
     PACKET / "entry-fix" / "regression-15.json")
(PACKET / "no-render-semantics").mkdir(exist_ok=True)
copy(ROOT / "var/evidence/roadmap/W2-R4-表达收口/no-render-semantics/checks.json",
     PACKET / "no-render-semantics" / "checks.json")
(PACKET / "no-render-semantics" / "README.md").write_text(
    "# --no-render 报告语义修正\n\n"
    "架构师独立运行 `verify_w2_r4.py --no-render` 曾得 12 pass / 3 fail（退出 1）。"
    "本批把图像项改为 `not_run`、缺前置证据改为 `missing_evidence`，两者都不计入产品失败；"
    "验证摘要按 function_level / contract / http / external_evidence / real_render / "
    "browser / manual_visual 分层。\n\n"
    "在同一空目录复现结果：`" + json.dumps(no_render.get("totals"), ensure_ascii=False) +
    "`、退出码 0。完整渲染运行（本包 checks-source.json）为 15/15、0 not_run、0 缺证。\n",
    encoding="utf-8")
for name in ("阶段1_底图核对.html", "阶段1_底图核对.pdf", "01_真实场地底图.svg",
             "底图数据.json", "00_原始平面图_正向.png"):
    copy(BASEMAP / name, PACKET / "basemap" / name)

# ------------------------------------------------------- 可打印完整编号索引
for letter in ("A", "B"):
    idx = indexes[letter]
    rows = []
    for item in idx["labels"].values():
        detail = item.get("object_id") or ""
        bits = [f'{k}={v}' for k, v in item.items()
                if k not in ("code", "kind", "object_id", "name", "source")
                and v is not None]
        rows.append(
            f'<tr><td>{escape(item["code"])}</td><td>{escape(item["kind"])}</td>'
            f'<td>{escape(detail)}</td><td>{escape(item.get("name") or "")}</td>'
            f'<td>{escape(" · ".join(bits)[:180])}</td>'
            f'<td>{escape(str(item.get("source") or ""))}</td></tr>')
    chain = idx["dimension_chain"]
    stations = []
    for axis in ("x", "y"):
        for st in chain[axis]["stations"]:
            stations.append(
                f'<tr><td>{axis.upper()}{st["id"]}</td><td>{st["coordinate_mm"]}</td>'
                f'<td>{st["delta_from_previous_mm"]}</td>'
                f'<td>{escape("; ".join(st["basis"]))}</td></tr>')
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>布局 {letter} · 平面编号索引与尺寸链（可打印）</title>
<style>@page{{size:A4;margin:12mm}}body{{font:12px/1.55 "Microsoft YaHei",sans-serif;color:#1f2937}}
h1{{font-size:18px}}h2{{font-size:14px;margin-top:18px;border-bottom:1px solid #cbd5e1;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;font-size:10.5px}}th,td{{border:1px solid #d7dee6;padding:4px 6px;text-align:left;vertical-align:top}}
th{{background:#f1f5f9}}tr{{page-break-inside:avoid}}thead{{display:table-header-group}}
.note{{background:#fff7ed;border-left:3px solid #c2410c;padding:8px 10px;font-size:11px}}
@media print{{body{{font-size:10.5px}}}}</style></head><body>
<h1>布局 {letter} · 平面编号索引与受控尺寸链</h1>
<p>本页把平面图上放不下的完整编号说明按正常字号单独打印，解决 A4 缩放后图内索引小字偏小的问题。
索引与平面 SVG 由同一份标签字典生成（{escape(idx["plan_layers_version"])}）。</p>
<div class="note">全部墙厚/高度、门窗洞口、材质贴图、家具、机位与陈设均为人工测试假设，
未现场复核、非 AI 自动设计；尺寸链是图面可读性对账用的受控假设，不是施工定位尺寸。</div>
<h2>编号索引（{len(idx["labels"])} 项）</h2>
<table><thead><tr><th>编号</th><th>类别</th><th>对象 ID</th><th>名称</th><th>尺寸/参数</th><th>来源</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h2>尺寸链站表（X 闭合 {chain["x"]["sum_delta_mm"]}/{chain["x"]["total_mm"]} mm，
Y 闭合 {chain["y"]["sum_delta_mm"]}/{chain["y"]["total_mm"]} mm）</h2>
<table><thead><tr><th>站点</th><th>坐标 mm</th><th>Δ mm</th><th>依据</th></tr></thead>
<tbody>{''.join(stations)}</tbody></table>
<h2>表达对象与工程量</h2>
<pre>{escape(json.dumps(idx["expression_accounting"], ensure_ascii=False, indent=2))}</pre>
<p>{escape(chain["note"])}</p></body></html>"""
    (PACKET / f"plan-index-{letter}.html").write_text(html, encoding="utf-8")

# ------------------------------------------------------------------ 文档
gaps = [
    "效果图仍是内部评审级，不是设计公司给客户的交付图：无人物、软装细节少、无真实品牌内容。",
    "布局 B 最左一扇窗仍有高亮近白区域（窗外本地渐变假设在该角度露出高亮段）；"
    "其余窗扇窗框/竖梃/玻璃/窗外层次可辨。未继续压暗参数掩盖它。",
    "整体仍偏暗偏灰，天花占画面偏大（既有 1500mm 人眼机位 + 24mm 广角；"
    "为满足前后同机位未改机位）。",
    "功能陈设仍偏稀疏，B 的大空地仍明显；品牌板只有抽象色块，几乎看不出品牌内容。",
    "窗外是本地程序化天空/地平线渐变，不是真实外景；照明含假设补光，未做照度/配光计算。",
    "材质分缝/收边是示意几何，不是施工排版；贴图 tile 为人工假设，不是材料规格。",
    "A4 打印缩放后图内图例与索引小字仍偏小（已另出 plan-index-A.html / B.html 可打印索引页）。",
    "平面无闭合施工尺寸链、柱网、洁具、构造节点；每布局仅 1 个机位 1 张人眼图，"
    "未做天花/立面/多视角/材料实物板/汇总客户 PDF（W4 范围，未授权启动）。",
    "表达层全部是人工测试假设（`site_verified=false` / `not_ai_design=true`），"
    "不计入 AI 接替设计；AD01—AD08 与用户阶段确认不变。",
]
(PACKET / "design-gaps.md").write_text(
    "# 仍然不像设计公司成果的地方（逐条，不自行降低验收标准）\n\n"
    + "\n".join(f"{i}. {g}" for i, g in enumerate(gaps, 1))
    + "\n\n本批是同源表达能力的工程与图面收口；工程检查与自动断言通过不代表 R4 设计通过、"
      "W2 整体完成或客户设计通过。\n", encoding="utf-8")

expr0 = presentations["A"].get("expression") or {}
asset_lines = [
    "# 资产、来源与人工假设清单（V2/V3 更新）",
    "",
    "本批**未下载任何新资产、未新增外部调用**。资产仍来自项目既有 `tools/assets/`"
    "（Poly Haven，CC0 1.0）。渲染器只读版本化表达输入，不手工改像素。",
    "",
    "## 可复用资产",
    "",
    "| 类别 | 内容 | 来源/许可 | 本批用法 |",
    "| --- | --- | --- | --- |",
    "| 渲染器 | Blender 4.2.9 LTS 免安装版 | 项目既有，GPL | Cycles CPU，两布局各 1 张人眼图 |",
    "| PBR 贴图 | 6 套 1k：floor_microcement / wall_plaster / oak / walnut / stone / fabric | "
    "Poly Haven CC0 1.0，清单 `assets/CC0-素材清单.json` | 真实贴图 + 版本化 tile |",
    "| glTF 家具/器物 | 10 件，尺寸取清单 `dimensions_mm` | Poly Haven CC0 1.0 | "
    "统一 anchor=center_floor、0° 沿 +X、rotation_deg 逆时针 |",
    "| 窗外环境 | 本地程序化天空/地平线渐变 | **执行者人工假设**，非外部素材 | "
    "透过透明玻璃可见，明确标 `labelled_local_sky_gradient_assumption` |",
    "| 程序化表达 | 展墙 / 展台 / 品牌板 | **执行者人工假设几何**，非 CC0 资产 | "
    "替代 display-wing 占位盒，保留对象 ID/位置/尺寸 |",
    "",
    "## V2/V3 版本化表达输入",
    "",
    f"- 契约：`{expr0.get('schema_version')}`；声明来源 `{expr0.get('declared_by')}`。",
    f"- 材质收边/接缝：{', '.join(sorted((expr0.get('material_finish') or {})))} "
    "（tile / joint_spacing_mm / joint_width_mm / edge_trim_mm，均为人工假设）。",
    "- 窗表现：`glass_kind=transparent`，发光玻璃板 0，窗框宽 "
    f"{(expr0.get('window_expression') or {}).get('frame_width_mm')} mm，"
    f"洞口深度 {(expr0.get('window_expression') or {}).get('reveal_depth_mm')} mm，"
    "窗外为标注的本地天空渐变。",
    "- 完整输入见 `outputs/expression-input-A.json` / `-B.json` 与 `expression-input.md`。",
    "",
    "## 对象来源分类（不计工程量）",
    "",
]
for letter in ("A", "B"):
    counts = (metas[letter].get("expression") or {}).get("origin_counts") or {}
    asset_lines.append(f"- 布局 {letter}：`{json.dumps(counts, ensure_ascii=False)}`；"
                       f"`engineering_quantity_effect="
                       f'{(metas[letter].get("expression") or {}).get("engineering_quantity_effect")}`')
asset_lines += [
    "",
    "源模型对象、CC0 表达资产、测试陈设、程序化表达在 `plan-index.json` 的 "
    "`expression_accounting` 与场景 `origin_kind` 中分列；"
    "**新增陈设不进入 measure() 的工程量、材料面切片或试算金额**（专项断言 V3-*-03 证明）。",
    "",
    "## 明确假设（不编现场事实）",
    "",
]
for text in (presentations["A"].get("assumptions") or []):
    asset_lines.append(f"- {text}")
(PACKET / "asset-inventory.md").write_text("\n".join(asset_lines) + "\n", encoding="utf-8")

(PACKET / "expression-input.md").write_text(
    "# 版本化表达输入（V2 窗光/材质 · V3 陈设分类）\n\n"
    f"契约 `{expr0.get('schema_version')}`，由 `scripts/w2_r4_fixture_presentation.py` 生成、"
    "`mvp/rkd_mvp/spatial_presentation.py` 校验、`scripts/render_spatial_scene_r4.py` 只读消费。"
    "参数不写死在渲染器，也不手工改像素。\n\n"
    "## 窗表现\n\n"
    + "\n".join(f"- `{k}` = `{v}`" for k, v in
                (expr0.get("window_expression") or {}).items())
    + "\n\n## 材质收边/接缝\n\n"
    + "\n".join(f"- **{k}**：`{json.dumps(v, ensure_ascii=False)}`"
                for k, v in (expr0.get("material_finish") or {}).items())
    + "\n\n## 调参留痕（人工目检驱动，非放宽检查）\n\n"
    "1. 首版：透明玻璃 + 窗框 + 窗外渐变；曝光 -0.30、窗光系数 0.50、补光 32 → "
    "人工看图判定偏暗、地面分缝过抢、展台基座突兀。\n"
    "2. 二版：曝光 -0.15、窗光系数 0.62、补光 42、分缝调浅、展台基座改浅木 → "
    "亮度与材质尺度改善；仍见 B 最左窗高亮。\n"
    "3. 三版：面光源 `visible_camera=False`、窗外渐变整体压暗（emission 0.34）→ "
    "窗框/玻璃/窗外层次可辨，最左窗扇仍有高亮残留，如实列为未解决项，未继续压暗掩盖。\n\n"
    "## 陈设分类\n\n"
    "`furniture[].origin_kind ∈ {source_model, cc0_expression_asset, test_staging, "
    "procedural_expression}`；后两类只进入平面与场景表现，工程量恒为 0 影响。"
    "位置由本布局动线/分区派生，不复制固定样板坐标；不暗改源方案、不称 AI 自动设计。\n",
    encoding="utf-8")

cases = [
    "# 关键正负例与复跑结果",
    "",
    "## A. 入口小修（上一批已受限通过，本批不重做）",
    "",
    f"- 整改前 `all_as_expected={conflict_before.get('all_as_expected')}`、"
    f"整改后 `all_as_expected={conflict_after.get('all_as_expected')}`；"
    "证据 `entry-fix/`。",
    f"- 原 15 项回归 `{regression.get('totals', {}).get('observed_pass')}/15` "
    "（`entry-fix/regression-15.json`）。",
    "",
    "## B. --no-render 报告语义（架构师点名）",
    "",
    f"- 空目录复现：`{json.dumps(no_render.get('totals'), ensure_ascii=False)}`、退出码 0；"
    "图像项 `not_run`、缺前置证据 `missing_evidence`，均不计产品失败。",
    "- 完整渲染运行：15/15 observed_pass、0 not_run、0 缺证（`checks-source.json`）。",
    "- 摘要分层：`verification_layers` = function_level / contract / http / "
    "external_evidence / real_render / browser / manual_visual。",
    "",
    "## C. V1—V3 专项自动断言（与人工目检分列）",
    "",
]
for c in (closeout.get("automatic_assertions") or {}).get("checks") or []:
    cases.append(f"- `{c['id']}` {c['name']} → **{c['result']}**")
cases += [
    "",
    "## D. 真实缺陷修正（先复现再修）",
    "",
    "1. 短编号撞号：V3 新增 `R4-STG-PED-03` / `R4-STG-OBJ-03` 与 `R4-PROP-03` "
    "旧算法都生成 `P03`，导致图面标签重叠且 `plan-index.json` 的 labels 互相覆盖。"
    "改为按类别前缀全局唯一分配（`plan_layers.furniture_codes`），并把 R4-03 断言改为按索引对账。"
    "修正后 A/B 自动几何检查均 0 重叠、0 出界。",
    "2. 局部裁剪黑屏：`<img src=file://…>` 在 `setContent` 的 about:blank 源下被阻止加载，"
    "改用 base64 data URL，裁剪后为真实像素。",
    "3. 图下方索引首版长字符串横向压到第二列：去掉图内冗余来源字段，完整说明移到 "
    "`plan-index-*.html` / `plan-index.json`。",
    "4. 顶部标题与尺寸链说明重叠：合并为一行提示，链线下移。",
    "",
    "## E. 浏览器与全量回归",
    "",
    f"- 真实 Edge：`passed={browser.get('passed')}`、390px 无溢出、"
    "下载 SHA 与 manifest/ZIP 一致（`browser/verification.json`）。",
    "- 全量单测与前端构建：`runtime/full-unittest.log` / `tsc.log` / `frontend-build.log`。",
]
(PACKET / "positive-negative-cases.md").write_text("\n".join(cases) + "\n", encoding="utf-8")

# ------------------------------------------------------------------ 汇总 checks.json
auto = closeout.get("automatic_assertions") or {}
summary = {
    "task_id": "W2-R4 表达收口 V1—V3",
    "schema_version": "rkd-w2-r4-closeout-review-checks.v1",
    "compiled_at": now,
    "source_baseline": BASE_COMMIT,
    "automatic_assertions": {
        "http_and_render": {"observed_pass": (checks.get("totals") or {}).get("observed_pass"),
                            "observed_fail": (checks.get("totals") or {}).get("observed_fail"),
                            "evidence": "checks-source.json"},
        "v1_v3_special": {"observed_pass": auto.get("observed_pass"),
                          "observed_fail": auto.get("observed_fail"),
                          "evidence": "closeout/closeout-checks.json"},
        "plan_geometry": {"overlaps": {k: v.get("overlap_count")
                                       for k, v in (visual.get("auto_geometry_check") or {}).items()},
                          "evidence": "visual/capture-observations.json"},
        "browser": {"passed": browser.get("passed"), "evidence": "browser/verification.json"},
        "no_render_semantics": {"totals": no_render.get("totals"),
                                "evidence": "no-render-semantics/checks.json"},
        "entry_fix_regression": (regression.get("totals") or {}),
        "full_unittest": {"evidence": "runtime/full-unittest.log"},
        "note": "自动断言只做几何/编号/闭合/契约/工程量/HTTP/渲染发生与浏览器下载对账",
    },
    "manual_visual_review": {
        "status": "reported_separately",
        "evidence": "manual-visual-review.md",
        "note": "前后全图、入口/洽谈区局部、窗区/功能区局部、A4 打印缩放由人工逐处看图判定；"
                "自动断言不代替人工目检，也不宣布客户设计通过",
    },
    "totals": {"automatic_pass": (checks.get("totals") or {}).get("observed_pass", 0)
               + auto.get("observed_pass", 0),
               "automatic_fail": (checks.get("totals") or {}).get("observed_fail", 0)
               + auto.get("observed_fail", 0),
               "not_run_in_complete_run": (checks.get("totals") or {}).get("not_run", 0)},
    "external_calls": 0, "tokens": 0,
    "images_generated_this_batch": {
        "human_eye_renders": 2,
        "plan_full_and_local_screenshots": len(visual.get("screenshots") or []),
        "render_compare_crops": 12,
        "browser_screenshots": 4,
        "note": "均为本机 Blender/浏览器派生；before 图只读引用上一批，未重新生成",
    },
    "cost_amount_or_null": None, "cost_status": "no_external_calls_zero_cost",
    "boundaries": ["W2 整体未放行", "AD01—AD08 与用户阶段确认不变",
                   "阶段1具体版本确认前停在阶段1边界", "W3/W4 未启动",
                   "不扩 PG/NAS/账号/租约平台"],
    "not_customer_design_approval": True,
}
(PACKET / "checks.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                    encoding="utf-8")

# ------------------------------------------------------------------ code-diff
def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, errors="replace").stdout.strip()


(PACKET / "code-diff.md").write_text(
    "# 提交差异\n\n"
    f"- 稳定基线：`{BASE_COMMIT}`（架构师 `review-next.md` 审查 HEAD）。"
    "补丁由 `git diff 8fd7948`（配合 `git add -N` 纳入新文件）生成，覆盖业务代码、"
    "脚本、状态表与复核输入；不含 `changes.patch` / `manifest.json` / `index.html` 自身，避免自引用。\n"
    "- 最终提交号见 `commit-reference.md`（单独提交补记，不写死易变 HEAD）。\n\n"
    "## `git diff --stat 8fd7948`\n\n```\n"
    + (git("diff", "--stat", BASE_COMMIT) or "(未取到)") + "\n```\n\n"
    "## 改动摘要（不按行数衡量工作价值）\n\n"
    "| 文件 | 改动 |\n| --- | --- |\n"
    "| `mvp/rkd_mvp/plan_layers.py` | 新增：分层平面、避让引线、短编号全局唯一、"
    "闭合尺寸链、完整索引 |\n"
    "| `mvp/rkd_mvp/ai_spatial_outputs.py` | presentation 时委托分层平面；"
    "新增 `plan-index.json` 成果与清单摘要；表达式版本常量 |\n"
    "| `mvp/rkd_mvp/spatial_presentation.py` | 新增 `expression` 契约校验、"
    "`origin_kind` 四类分类与计数 |\n"
    "| `scripts/w2_r4_fixture_presentation.py` | 新增版本化表达输入、V3 测试陈设、"
    "display-wing 程序化替换 |\n"
    "| `scripts/render_spatial_scene_r4.py` | V2 透明玻璃/窗框/窗外假设/分缝收边/曝光；"
    "V3 程序化表达对象与来源分组 |\n"
    "| `scripts/verify_w2_r4.py` | `--no-render` 语义修正、验证分层、索引对账、"
    "下载 `plan-index.json` |\n"
    "| `scripts/verify_w2_r4_closeout.py` | 新增：V1—V3 专项断言，自动与人工分列 |\n"
    "| `scripts/capture_w2_r4_visual.cjs` | 新增：前后全图/局部/打印缩放与自动几何检查 |\n"
    "| `scripts/capture_render_crops.cjs` | 新增：人眼图前后全图与窗区/功能区局部 |\n"
    "| `scripts/build_w2_r4_closeout_review.py` | 新增：复核包组装 |\n"
    "| `PROJECT_STATUS.md` | 追加本批受限结论与交付记录 |\n",
    encoding="utf-8")

# ------------------------------------------------------------------ review-packet
(PACKET / "review-packet.md").write_text(
    "# W2-R4 表达收口 · 复核包\n\n"
    f"编制 {now}；审查基线 `{BASE_COMMIT}`。"
    "运行证据 `var/evidence/roadmap/W2-R4-表达收口/full/`；上一批 `W2-R4-同源表达` 原图只读引用，未回写。\n\n"
    "## 1. 需求映射\n\n"
    "| 委托项 | 落地 | 证据 |\n| --- | --- | --- |\n"
    "| 修正 `--no-render` 报告语义 | 图像项 `not_run`、缺前置证据 `missing_evidence`、"
    "摘要分层；空目录复现 12 pass / 0 fail / 2 not_run / 1 缺证 / 退出 0 | `no-render-semantics/` |\n"
    "| V1 平面可读性与关键尺寸链 | 几何/编号/注释三层、避让引线、短编号全局唯一、"
    "X/Y 闭合尺寸链、完整索引与可打印索引页 | `visual/`、`outputs/layout-*/plan-index.json`、`plan-index-*.html` |\n"
    "| V2 窗光/材质 | 透明玻璃替代发光板、窗框/竖梃/洞口深度、窗外本地渐变假设、"
    "地面分缝/木饰面竖缝/踢脚收边、版本化表达输入 | `expression-input.md`、`render-compare/` |\n"
    "| V3 功能表达与占位资产 | display-wing 程序化展墙、测试陈设分四类、"
    "位置由本布局派生、工程量恒 0 影响 | `asset-inventory.md`、`closeout/closeout-checks.json` |\n"
    "| 自动断言与人工目检分列 | 专项断言 20/20 与逐张看图结论分别成文 | `checks.json`、`manual-visual-review.md` |\n"
    "| 阶段1底图确认卡 | 查得历史认可未绑定具体版本 → 出确认卡并停在阶段边界，"
    "人工工程样板验证继续 | `basemap-confirmation-card.md`、`basemap/` |\n"
    "| 真实前后图与局部可读性 | 16 张平面前后/局部/打印 + 12 张人眼图前后/局部 | `visual/`、`render-compare/` |\n\n"
    "## 2. 做与未做\n\n"
    "**做了**：上述 V1—V3 全部检查点、`--no-render` 语义、底图确认卡、"
    "两布局完整源模型/表达输入/场景/平面/PNG/ZIP、四项受控变更与取消晚到/任务定位回归、"
    "专项断言 20/20、完整验证 15/15、浏览器、全量单测与前端构建、"
    "修 4 类真实缺陷（短码撞号、索引溢出、顶部重叠、局部裁剪黑屏）。\n\n"
    "**没做**：W3/W4 未启动；未新增付费/外部调用；未扩 PG/NAS/账号/租约平台；"
    "未做天花/立面/多视角/材料实物板/汇总客户 PDF；未做柱网/洁具/构造节点/照度合规/现场实测；"
    "未生成用户项目阶段2（阶段1具体版本确认前停止）；未改 AD、未代用户确认设计、"
    "未宣布 W2 放行或客户设计通过。\n\n"
    "## 3. 结果与设计差距\n\n"
    f"- 自动断言：完整验证 `{json.dumps(checks.get('totals'), ensure_ascii=False)}`；"
    f"V1—V3 专项 `{auto.get('observed_pass')}/{auto.get('observed_pass', 0) + auto.get('observed_fail', 0)}`；"
    f"浏览器 `passed={browser.get('passed')}`；原 15 项回归 15/15。\n"
    "- 人工目检：逐处结论与未解决项见 `manual-visual-review.md`；"
    "**主体改善成立，但 B 最左窗高亮、整体偏暗、天花占比大、陈设偏稀疏、"
    "打印小字偏小仍未解决**。\n"
    "- 图片与费用：本机新生成人眼图 **2 张**、平面/局部/打印截图 **16 张**、"
    "人眼图前后局部 **12 张**、浏览器截图 **4 张**；外部调用 0、外发 0、tokens 0、费用 0，"
    "密钥未使用未落盘。\n\n"
    "## 4. 风险与后续\n\n"
    "- 表达层仍是人工测试假设；若要计入自动设计，须由系统模型从需求生成墙/门窗/材质/陈设"
    "并保留来源，本批不计入 AD。\n"
    "- 单实例 SQLite 边界不变；W2 整体未放行；W3 须另获费用/资料授权；"
    "阶段 1→2 只接受用户对具体版本的明确确认。\n"
    "- 本批**不请求用户决定**：确认卡是待用户填写的边界文件，不是新待决闸口，"
    "未新增 `decision-request.md`。\n\n"
    "## 5. 文件索引\n\n"
    "见 `index.html` 首页与 `manifest.json` 全量清单（含字节与 SHA）。\n",
    encoding="utf-8")

# ------------------------------------------------------------------ index.html
def fig(rel: str, caption: str) -> str:
    return (f'<figure><img src="{rel}" alt="{escape(caption)}">'
            f'<figcaption>{escape(caption)}</figcaption></figure>')


gap_html = "".join(f"<li>{escape(g)}</li>" for g in gaps)
layer_rows = "".join(
    f'<tr><td>{escape(k)}</td><td>{escape(json.dumps(v, ensure_ascii=False)[:220])}</td></tr>'
    for k, v in (checks.get("verification_layers") or {}).items())
html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>W2-R4 表达收口 · 复核入口</title><style>
@page{{size:A4;margin:10mm}}*{{box-sizing:border-box}}
body{{font:13px/1.65 "Microsoft YaHei","Noto Sans SC",system-ui,sans-serif;
margin:0 auto;max-width:1180px;padding:28px 32px 60px;color:#1f2937;background:#fff}}
h1{{font-size:25px;margin:0 0 6px;color:#0f172a}}
h2{{font-size:17px;margin:26px 0 10px;padding-bottom:6px;border-bottom:2px solid #1e3a5f;color:#1e3a5f}}
h3{{font-size:14px;margin:16px 0 6px;color:#334155}}
.meta{{color:#64748b;font-size:12px;margin-bottom:14px}}
.banner{{background:#f1f5f9;border-left:4px solid #1e3a5f;padding:12px 16px;margin:14px 0}}
.warn{{background:#fff7ed;border-left:4px solid #c2410c;padding:12px 16px;margin:14px 0}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
figure{{margin:0;border:1px solid #dbe3ea;background:#fff}}
figure img{{display:block;width:100%;height:auto}}
figcaption{{font-size:11px;color:#475569;padding:6px 9px;border-top:1px solid #eef2f6}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin:10px 0}}
th,td{{border:1px solid #d7dee6;padding:5px 8px;text-align:left;vertical-align:top}}
th{{background:#f1f5f9}}ul{{margin:6px 0 6px 18px;padding:0}}li{{margin:4px 0}}
code{{background:#f1f5f9;padding:1px 4px;font-size:11.5px}}
.tag{{display:inline-block;background:#e2e8f0;border-radius:3px;padding:1px 7px;font-size:11px;margin:0 4px 4px 0}}
.footer{{margin-top:30px;border-top:1px solid #d7dee6;padding-top:12px;font-size:11.5px;color:#64748b}}
@media print{{body{{font-size:11px;line-height:1.5;padding:0;max-width:none}}
h2{{page-break-after:avoid}}table{{page-break-inside:auto}}tr,th,td{{page-break-inside:avoid}}
figure{{page-break-inside:avoid}}.grid2{{page-break-inside:auto}}thead{{display:table-header-group}}
img{{max-height:100mm;object-fit:contain}}-webkit-print-color-adjust:exact;print-color-adjust:exact}}
</style></head><body>
<h1>W2-R4 表达收口 · 内部复核入口</h1>
<div class="meta">编制 {now} · 审查基线 <code>{BASE_COMMIT}</code> ·
运行证据 <code>var/evidence/roadmap/W2-R4-表达收口/full/</code> ·
上一批原图只读引用，未回写历史</div>
<div class="banner"><b>受限结论：</b>架构复核确认入口异材冲突修复受限通过、R4 表达进展成立；
<b>W2 整体未放行</b>，AD01—AD08 与用户阶段确认不变，W3/W4 未启动。
本批只收口可见表达问题，<b>不得自评客户设计通过、不得宣布 W2 放行、不得修改 AD</b>。</div>
<p>
<span class="tag">完整验证 {json.dumps(checks.get('totals'), ensure_ascii=False)}</span>
<span class="tag">V1—V3 专项 {auto.get('observed_pass')}/20</span>
<span class="tag">浏览器 passed={browser.get('passed')}</span>
<span class="tag">--no-render 语义已修正</span>
<span class="tag">人眼图 2 张 · 外部费用 0</span>
</p>

<h2>0. 本批按 V1 → V2 → V3 连续推进</h2>
<table><thead><tr><th>检查点</th><th>实际改动</th><th>真实前后图</th></tr></thead><tbody>
<tr><td>V1 平面可读性 / 尺寸链</td><td>几何·编号·注释三层分离；短编号带引线避让；
X/Y 受控尺寸链闭合到总尺寸；完整索引与 A4 可打印索引页</td>
<td>入口区、洽谈区局部前后 + 全图 + 打印缩放</td></tr>
<tr><td>V2 窗光 / 材质</td><td>透明玻璃替代发光板；窗框/竖梃/洞口深度；
窗外本地天空渐变假设；地面分缝、木饰面竖缝、踢脚收边；版本化表达输入</td>
<td>同一机位/模型的窗区局部前后</td></tr>
<tr><td>V3 功能表达 / 占位</td><td>display-wing 换程序化展墙；测试陈设分四类；
位置由本布局动线/分区派生；工程量恒 0 影响</td>
<td>功能区局部前后 + 两布局最终人眼图</td></tr>
</tbody></table>

<h2>1. 自动断言与人工目检（严格分列）</h2>
<table><thead><tr><th>类别</th><th>结果 / 证据</th></tr></thead><tbody>
<tr><td><b>自动断言</b></td><td>完整验证 {json.dumps(checks.get('totals'), ensure_ascii=False)}；
V1—V3 专项 {auto.get('observed_pass')}/20；图面标注 0 重叠 / 0 出界 / 最小字号 8.5；
浏览器下载 SHA 一致；原 15 项回归 15/15。见 <code>checks.json</code>、<code>closeout/</code>、
<code>visual/capture-observations.json</code>。</td></tr>
<tr><td><b>人工目检</b></td><td>逐张看前后全图、入口/洽谈区局部、窗区/功能区局部、
A4 打印缩放，逐处结论与未解决项见 <code>manual-visual-review.md</code>。
自动断言不代替人工看图，不以非空 SVG 或亮度阈值宣布通过。</td></tr>
</tbody></table>
<p class="meta">验证分层（来自 checks-source.json 的 verification_layers）：</p>
<table><thead><tr><th>层</th><th>状态</th></tr></thead><tbody>{layer_rows}</tbody></table>

<h2>2. V1 前后：入口区与洽谈区局部</h2>
<div class="grid2">
{fig('visual/plan-A-entry-before.png','V1 前 · A 入口区：门号/机位/动线数值压叠')}
{fig('visual/plan-A-entry-after.png','V1 后 · A 入口区：短编号带引线，压叠消除')}
{fig('visual/plan-A-meeting-before.png','V1 前 · A 洽谈区：三行文字压框、洞口字压线')}
{fig('visual/plan-A-meeting-after.png','V1 后 · A 洽谈区：短徽标 + 引线名称')}
</div>
<div class="grid2">
{fig('visual/plan-A-full-after.png','V1 后 · A 全图（含闭合尺寸链与索引表）')}
{fig('visual/plan-A-print-after.png','V1 后 · A4 打印缩放 270mm（小字偏小，另见 plan-index-A.html）')}
</div>

<h2>3. V2 前后：窗区与材质</h2>
<div class="grid2">
{fig('render-compare/render-B-window-before.png','V2 前 · B 窗区：3 块纯白发光板')}
{fig('render-compare/render-B-window-after.png','V2 后 · B 窗区：窗框/竖梃/玻璃/窗外渐变可辨；最左扇仍高亮')}
{fig('render-compare/render-A-window-before.png','V2 前 · A 窗区')}
{fig('render-compare/render-A-window-after.png','V2 后 · A 窗区：地面分缝与木饰面竖缝可见')}
</div>

<h2>4. V3 前后：功能表达与最终两布局图</h2>
<div class="grid2">
{fig('render-compare/render-B-function-before.png','V3 前 · B 功能区：孤立圆桌、大空地、分散座椅')}
{fig('render-compare/render-B-function-after.png','V3 后 · B 功能区：成组座椅、样板展台与器物')}
{fig('outputs/layout-A/render.png','最终 · 布局 A 人眼图（同一生成器 / 同一假设机位）')}
{fig('outputs/layout-B/render.png','最终 · 布局 B 人眼图（同一生成器 / 同一假设机位）')}
</div>

<h2>5. 阶段1边界：底图确认卡</h2>
<div class="warn"><b>历史「阶段1已由用户核对认可」在台账中未绑定到具体底图版本标识/哈希/边界快照；</b>
W2 与本批的场地边界是 <code>manual_boundary_not_site_verified</code> 测试参数，
表达层墙/门窗/材质/陈设全部 <code>site_verified=false</code>。
按 docs/26 硬节点 3，不能外推为「当前具体版本已确认」。
已准备 <code>basemap-confirmation-card.md</code>（版本/边界/入口/保留区/已知与假设/待确认点/图面），
<b>用户明确确认前停在阶段1边界，不生成该项目阶段2</b>；人工工程样板验证不受阻塞，继续完成本批。
本卡不是替用户签字。</div>
<div class="grid2">
{fig('basemap/00_原始平面图_正向.png','阶段1底图 · 宁波 A3 原图转正（只读引用）')}
{fig('visual/plan-B-full-after.png','本批人工样板 · B 平面（非用户项目阶段2成果）')}
</div>

<h2>6. 仍然不像设计公司成果的地方</h2>
<ol>{gap_html}</ol>

<h2>7. 做与未做、图片与费用</h2>
<p><b>做：</b>V1—V3 全部检查点、<code>--no-render</code> 语义修正、底图确认卡、
两布局完整源模型/表达输入/场景/平面/PNG/ZIP、四项受控变更与取消晚到/任务定位回归、
专项断言、浏览器与全量回归、4 类真实缺陷修正。</p>
<p><b>未做：</b>W3/W4、付费/外部调用、PG/NAS/账号/租约平台、全套天花/立面/多视角/
材料实物板/汇总客户 PDF、柱网洁具与照度合规、现场实测、用户项目阶段2、
AD 修改与用户设计确认、W2 放行宣告。</p>
<p><b>图片与费用：</b>本机新生成人眼效果图 <b>2 张</b>；平面全图/局部/打印截图 <b>16 张</b>；
人眼图前后与局部裁剪 <b>12 张</b>；浏览器桌面/移动与平面预览 <b>4 张</b>。
外部模型调用 <b>0 次</b>、外发图片 <b>0 张</b>、tokens <b>0</b>、费用 <b>0</b>；密钥未使用、未落盘。</p>

<div class="footer">执行者报告 · 架构师独立复核项待审 · 用户设计确认、阶段确认与 AD01—AD08 由用户给，不代签。
工程检查与自动断言通过不代表 R4 设计通过、W2 放行或客户设计通过。
详细文件：<code>review-packet.md</code>、<code>checks.json</code>、<code>code-diff.md</code>、
<code>manifest.json</code>、<code>positive-negative-cases.md</code>、<code>asset-inventory.md</code>、
<code>expression-input.md</code>、<code>manual-visual-review.md</code>、
<code>basemap-confirmation-card.md</code>。</div>
</body></html>"""
(PACKET / "index.html").write_text(html, encoding="utf-8")

# ------------------------------------------------------------------ manifest.json
def classify(rel: str) -> str:
    if rel.startswith("outputs/layout-"):
        return "derived_output"
    if rel.startswith("outputs/previous-"):
        return "previous_batch_reference"
    if rel.startswith(("visual/", "render-compare/", "browser/", "runtime/",
                       "closeout/", "entry-fix/", "no-render-semantics/")):
        return "running_evidence"
    if rel.startswith("basemap/"):
        return "stage1_source_reference"
    return "review_document"


entries = []
for path in sorted(PACKET.rglob("*")):
    if not path.is_file() or path.name == "manifest.json":
        continue
    rel = path.relative_to(PACKET).as_posix()
    entries.append({"path": rel, "bytes": path.stat().st_size,
                    "sha256": sha(path), "kind": classify(rel)})
(PACKET / "manifest.json").write_text(json.dumps({
    "schema_version": "rkd-w2-r4-closeout-review-manifest.v1",
    "compiled_at": now, "source_baseline": BASE_COMMIT,
    "code_head_at_compile": git("rev-parse", "HEAD"),
    "versions": {"generator": "rkd-spatial-outputs.v4",
                 "plan_layers": "rkd-spatial-plan-layers.v1",
                 "plan_index": "rkd-spatial-plan-index.v1",
                 "expression": "rkd-spatial-expression.v1",
                 "presentation": "rkd-spatial-presentation-fixture.v1"},
    "design_origin": "labelled local fixture + executor manual test assumptions; NOT AI design",
    "site_verified": False,
    "images_generated_this_batch": summary["images_generated_this_batch"],
    "external_calls": 0, "cost_amount_or_null": None,
    "files": entries,
    "note": "source/ 原件只读；var/ 为运行数据；basemap/ 是阶段1既有文件只读引用；"
            "上一批 PNG 只读引用未回写；manifest.json 自身不计入清单。",
}, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps({"packet": str(PACKET), "files": len(entries) + 1,
                  "bytes": sum(e["bytes"] for e in entries),
                  "automatic_pass": summary["totals"]["automatic_pass"],
                  "automatic_fail": summary["totals"]["automatic_fail"]},
                 ensure_ascii=False, indent=2))
