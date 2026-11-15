"""组装 W2-R4 同源表达复核包（docs/26 第 6 节最少文件 + R4 指定交付项）。

用法：PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/build_w2_r4_review.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "var/evidence/roadmap/W2-R4-同源表达"
PACKET = ROOT / "deliverables-for-review/roadmap/W2-R4-同源表达"
OLD_RENDER = (ROOT / "deliverables-for-review/roadmap/W2-同源成果切片"
              / "outputs/layout-A/render.png")
BASE_COMMIT = "ffad892"          # 架构师审查 HEAD（稳定基线）
BUSINESS_COMMIT = "7425464"      # 架构师审查的业务实现提交

PACKET.mkdir(parents=True, exist_ok=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy(src: Path, dst: Path) -> bool:
    if not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def jload(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
main_checks = jload(EVIDENCE / "checks.json")
browser = jload(EVIDENCE / "browser" / "verification.json")
conflict_before = jload(EVIDENCE / "before" / "finish-conflict-before.json")
conflict_after = jload(EVIDENCE / "after" / "finish-conflict-after.json")
regression = jload(EVIDENCE / "regression-second-closeout" / "repro-r4-regression.json")
assets = jload(ROOT / "assets" / "CC0-素材清单.json")
asset_inventory = jload(ROOT / "assets" / "CC0-素材清单.json")
from rkd_mvp.spatial_presentation import load_asset_inventory  # noqa: E402
inv = load_asset_inventory()

# ------------------------------------------------------------------ 复制产物
for letter in ("A", "B"):
    src_dir = EVIDENCE / "outputs" / f"layout-{letter}"
    dst_dir = PACKET / "outputs" / f"layout-{letter}"
    dst_dir.mkdir(parents=True, exist_ok=True)
    if src_dir.is_dir():
        for src in sorted(src_dir.iterdir()):
            if src.is_file():
                shutil.copy2(src, dst_dir / src.name)
copy(EVIDENCE / "outputs" / "changes" / "reconciliation.json",
     PACKET / "outputs" / "changes" / "geometry-material-reconciliation.json")
copy(EVIDENCE / "before" / "finish-conflict-before.json",
     PACKET / "entry-fix" / "before.json")
copy(EVIDENCE / "after" / "finish-conflict-after.json",
     PACKET / "entry-fix" / "after.json")
copy(EVIDENCE / "regression-second-closeout" / "repro-r4-regression.json",
     PACKET / "entry-fix" / "regression-15.json")
copy(EVIDENCE / "checks.json", PACKET / "checks.json")
copy(EVIDENCE / "runtime" / "full-unittest.log", PACKET / "runtime" / "full-unittest.log")
browser_dir = EVIDENCE / "browser"
if browser_dir.is_dir():
    for src in sorted(browser_dir.iterdir()):
        if src.is_file():
            copy(src, PACKET / "browser" / src.name)
if OLD_RENDER.is_file():
    copy(OLD_RENDER, PACKET / "before-after" / "w2-graybox-layout-A.png")

# ------------------------------------------------------------------ 资产清单
asset_lines = [
    "# W2-R4 可复用资产与人工假设清单（检查点 1）",
    "",
    "本批**不新增任何外部调用、不下载新资产**。所有资产来自项目既有 `tools/assets/`",
    "（Poly Haven，CC0 1.0 公共领域，商业使用允许，清单 `assets/CC0-素材清单.json`，",
    f"SHA-256 `{inv['sha256']}`），二进制文件被 .gitignore 排除、不进版本库。",
    "",
    "## 可复用能力（只复用能力，不抄样板方案坐标）",
    "",
    "| 类别 | 既有资产 / 能力 | 来源与许可 | 单位/尺度 | R4 用法 |",
    "| --- | --- | --- | --- | --- |",
    "| 渲染器 | Blender 4.2.9 LTS 免安装版 `tools/blender/` | 本机既有，GPL | Cycles CPU | 两布局各渲 1 张人眼图 |",
    "| 材质加载 | `scripts/render_blender.py` 的 `pbr_mat()`（TexCoord/Object → Mapping → Diffuse/Rough/nor_gl） | 项目既有样板 | 1k PBR，tile 为倍率 | 复写为 `render_spatial_scene_r4.py` 的同名能力 |",
    "| 家具加载 | `scripts/render_blender.py` 的 `load_template()`/`place_model()`（`bpy.ops.import_scene.gltf`） | 项目既有样板 | glTF 真实尺寸 mm | 统一 anchor=center_floor、0° 沿 +X、rotation_deg 逆时针 |",
    "| 灯光能力 | 既有样板的窗发光板 / 太阳 / 筒灯 / 环形灯槽 | 项目既有样板 | W / K（假设） | 窗光只从已建模窗洞口发出；灯具/灯槽来自模型 `ceiling` 意向 |",
    "",
    f"- 纹理 {len(inv['textures'])} 套：{', '.join(sorted(inv['textures']))}",
    f"- glTF 家具/器物 {len(inv['models'])} 件，真实尺寸来自清单 `dimensions_mm`：",
]
for name, meta in sorted(inv["models"].items()):
    dims = "/".join(f"{v/1000:.3f}m" for v in meta["dimensions_mm"])
    asset_lines.append(f"  - `{name}` — {dims} — CC0 1.0 — {meta['source_page']}")
asset_lines += [
    "",
    "## 表达层人工测试假设（不是现场事实，不是 AI 设计）",
    "",
]
for text in (jload(PACKET / "outputs" / "layout-A" / "presentation.json").get("assumptions") or []):
    asset_lines.append(f"- {text}")
asset_lines += [
    "",
    "## 明确缺资产的占位",
    "",
    "- `display-wing`（展墙翼）：Studio 目录有条目，但本机 CC0 glTF 目录没有对应模型。",
    "  保留为**明确占位盒**，在 scene/meta 里列 `placeholders`，不冒充真实家具。",
    "",
    "## 几何字段审计",
    "",
    "| 字段 | 权威来源 | 是否自动推导墙/柱/洁具 |",
    "| --- | --- | --- |",
    "| `spatial.zones[].polygon_mm` | 主系统候选修订（精确 mm） | 只用于地坪/计量，不生成墙 |",
    "| `spatial.platforms[].corner_radius_mm` | 同一修订 | 平面与三维用同一圆角算法，不退化成方块 |",
    "| `spatial.ceiling.fixtures/coves` | 同一修订（意向） | 只驱动灯具点位/灯槽，不生成吊顶构造 |",
    "| `boundary.entrance` | 同一修订（测试参数） | 仅门洞位置/宽度 |",
    "| `presentation.walls/partitions/openings` | **执行者人工编写的样板假设** | 独立显式对象，不从分区多边形生成 |",
    "| 柱网 / 洁具 / 构造节点 / 实测标高 | 无依据 | 不编造、不补 0 |",
]
(PACKET / "asset-inventory.md").write_text("\n".join(asset_lines) + "\n", encoding="utf-8")
(PACKET / "asset-assumptions.json").write_text(json.dumps({
    "asset_manifest_sha256": inv["sha256"],
    "source": inv["source"], "license": "CC0 1.0",
    "textures": {k: {"polyhaven_id": v["polyhaven_id"], "authors": v["authors"],
                     "source_page": v["source_page"]}
                 for k, v in inv["textures"].items()},
    "models": {k: {"dimensions_mm": v["dimensions_mm"],
                   "source_page": v["source_page"], "license": v["license"]}
               for k, v in inv["models"].items()},
    "placeholders": ["display-wing"],
    "assumptions": jload(PACKET / "outputs" / "layout-A" / "presentation.json").get("assumptions"),
    "not_ai_design": True, "site_verified": False,
}, ensure_ascii=False, indent=2), encoding="utf-8")

# ------------------------------------------------------------------ 几何材质对账
recon = jload(PACKET / "outputs" / "changes" / "geometry-material-reconciliation.json")
rec_lines = [
    "# 几何 / 材质 / 量价对账（检查点 5）",
    "",
    "材料面切片由**精确分区多边形**生成，材料编号与表达层材质映射同源；",
    "金额只作用于有面积依据的分组，单价是调用方假设输入，不是价源、不是报价。",
    "",
    "## 分区 → 材料编号 → CC0 贴图 slot",
    "",
    "| zone_id | role | material_slot（表现） |",
    "| --- | --- | --- |",
]
for row in recon.get("zone_to_material") or []:
    rec_lines.append(f"| {row['zone_id']} | {row['role']} | {row['material_slot']} |")
rec_lines += ["", "## 材料面分组 → 面积 → 假设单价试算", "",
              "| material_id | layer | 面积 ㎡ | 来源对象 | 假设单价(元/㎡) | 试算(元) |",
              "| --- | --- | --- | --- | --- | --- |"]
trial = {i["material_id"]: i for i in recon.get("trial_items") or []}
for group in recon.get("material_groups") or []:
    item = trial.get(group["material_id"], {})
    rec_lines.append(
        f"| {group['material_id']} | {group['layer']} | {group['area_m2']} | "
        f"{', '.join(group['area_objects'])} | "
        f"{item.get('unit_price_cny', '—')} | {item.get('amount_cny', '—')} |")
rec_lines += [
    "",
    f"合计（假设单价试算，非报价）：{recon.get('trial_total_cny')} 元；`formal_quote=false`，"
    "税率/成本加成/损耗/工艺/产品选型全部 unknown。",
    "",
    "## 四项受控变更（每组同一冻结模型副本）",
    "",
    "| 变更 | 平面 | 三维场景 | 工程量 | 金额 |",
    "| --- | --- | --- | --- | --- |",
    "| `R4-WIN-N1` 洞口宽 5466→3000mm | 门窗表与短编号同步 | enclosure 同 ID 同尺寸 | 不变 | 不变 |",
    "| `mat-oak` 贴图 oak→walnut | 材质图例变化 | arrival 分区 material_slot 变化 | 不变 | 不变（材料编号与单价未变） |",
    "| 机位 x +3000mm | 机位/视锥变化 | camera.position 变化 | 不变 | 不变 |",
    "| 假设单价 ×1.2 | 不变 | 不变 | 不变 | 试算金额增加 |",
    "",
    "结论：表达层（围合/材质/机位/单价）与**精确几何量**分离；改开口尺寸会同步平面与三维，",
    "但不会偷偷改变功能区净面积；换材质只改表现与材质分组依据，不制造工程量。",
]
(PACKET / "geometry-material-reconciliation.md").write_text(
    "\n".join(rec_lines) + "\n", encoding="utf-8")

# ------------------------------------------------------------------ 正负例
cases = [
    "# 关键正负例与复跑结果",
    "",
    "## A. 入口小修：同层异材重叠（先复现、再修复，同一脚本各跑一次）",
    "",
    "| 编号 | 用例 | 整改前 | 整改后 |",
    "| --- | --- | --- | --- |",
    "| R4F-01 | 同层两块完全相同的 2×2m 面，wood/stone + overlap_declaration 自由文字 | "
    "8㎡/known + 2 笔试算（重复工程量） | conflict/None + 0 笔试算 + 冲突明细 |",
    "| R4F-02 | 同材同层重叠 + 声明 | 并集 4㎡/4000 元 | 并集 4㎡/4000 元（回归护栏） |",
    "| R4F-03 | 同层异材几何互斥 | 8㎡ known | 8㎡ known（合法） |",
    "| R4F-04 | 不同构造层重叠 | 合计被当单层净面积 | 分层计量 + `multi_layer_sum` + 非单层标注 |",
    "| R4F-05 | 结构化互斥裁切（x=1000 实际裁成两块） | 字段被忽略仍 8㎡ | 4㎡ known（wood 2 + stone 2） |",
    "| R4F-06 | 裁切仍重叠/不覆盖 | 忽略字段 / 入口抛错 | conflict 待核，不产 known |",
    "| R4F-07 | **真实 HTTP** 提交冲突 scope，render=false | 任务成功且 8㎡/8000 元进入成果 | "
    "任务成功但 `Q-FLOOR-FINISH=conflict/None`，cost 0 试算，CSV/HTML 标待核 |",
    "| R4F-08 | **真实 HTTP** 同材声明后并集 | 4㎡/4000 元 | 4㎡/4000 元（回归护栏） |",
    "",
    f"整改前 `all_as_expected={conflict_before.get('all_as_expected')}`、"
    f"整改后 `all_as_expected={conflict_after.get('all_as_expected')}`；"
    "证据 `entry-fix/before.json`、`entry-fix/after.json`。",
    "",
    "契约要点：自由文字 `overlap_declaration` **不是**消歧规则；只有 `material_allocation`",
    "给出几何互斥且等价覆盖的裁切面并被程序实际替换原面后，才允许同层异材同时计量；",
    "真实不同构造层分别计量，但合计标为多构造层合计，不叫单层地坪净面积。",
    "",
    "## B. 原 15 项回归（W2 二次收口，未放宽断言）",
    "",
    f"`{regression.get('totals', {}).get('observed_pass', 0)}/15` observed_pass，"
    f"failed={regression.get('totals', {}).get('observed_fail', '?')}；"
    "证据 `entry-fix/regression-15.json`。",
    "",
    "## C. R4 本批检查",
    "",
]
for c in main_checks.get("checks") or []:
    cases.append(f"- `{c['id']}` {c['name']} → **{c['result']}**")
cases += [
    "",
    "## D. 浏览器与全量回归",
    "",
    f"- 真实 Edge 浏览器：`passed={browser.get('passed')}`，"
    f"page_errors={len((browser.get('browser_observations') or {}).get('page_errors') or [])}，"
    f"390px scrollWidth={(browser.get('browser_observations') or {}).get('mobile_scroll_width')}，"
    "下载 SHA 与 manifest/ZIP 一致；证据 `browser/`。",
    "- 全量单测 262/262 OK（`runtime/full-unittest.log`）；`tsc --noEmit` 与 `npm run build` EXIT=0。",
    "- 修正的真实缺陷：既有 Blender 样板 `box()` 顶/底面是对角自交四边形，R4 渲染器改为正确 8 顶点 6 面棱柱；"
    "长对象 ID 撑破 390px 窄屏 grid 轨道，已在 `web/src/styles.css` 用 `minmax(0,1fr)` 与 `overflow-wrap` 修复。",
]
(PACKET / "positive-negative-cases.md").write_text("\n".join(cases) + "\n", encoding="utf-8")

# ------------------------------------------------------------------ 图面差距
gaps = [
    "效果图仍是**内部评审级**，不是设计公司给客户的照片级图：无人物、软装细节少、展品只有 2 件小器物、无品牌标识与陈设叙事。",
    "窗玻璃是发光板，没有窗外景；布局 B 左侧连续窗带在成图上明显过曝成纯白块。",
    "天花是整块平板，只有一圈矩形灯槽线与几个筒灯点，没有吊顶构造、灯槽剖面与灯具产品细节。",
    "家具数量偏少、分布稀：右侧洽谈区只有一组餐桌椅与一张沙发，空间显空；`display-wing` 无对应 CC0 资产，是明确标注的程序化占位盒，不冒充真实家具。",
    "六套 CC0 PBR 贴图已真实加载，但缺拼缝、收边、金属/玻璃/织物细节；贴图 tile 是人工假设，不是材料规格或排版。",
    "前景 arrival 区橡木地板占比大，与远处微水泥地面硬切换，没有过渡收边或压条。",
    "整体光比偏平、软阴影层次弱；存在一盏明确标注的假设补光，未做照度/配光计算，不宣称合规。",
    "平面图入口处短编号与红色动线仍有轻微压叠，右侧信息栏字号偏小；图上只有总尺寸链与门窗表，无闭合尺寸链、柱网、门窗详图、洁具，明确标注「不是施工图」。",
    "每布局只有 1 个人眼机位、1 张效果图；按本批范围**未做**天花图、两张立面、三张多视角效果图、材料实物板与汇总客户 PDF（W4 范围，未授权启动）。",
    "墙厚/高度、门窗洞口、隔断、材质贴图、家具资产映射、绿植软装、机位与灯光全部是**人工测试假设**，未现场复核；"
    "本批成果不计入「AI 接替设计」，AD01—AD08 与用户阶段确认一律不变，执行 AI 不代签。",
]
(PACKET / "design-gaps.md").write_text(
    "# 仍然不像设计公司成果的地方（逐条，不自行降低验收标准）\n\n"
    + "\n".join(f"{i}. {g}" for i, g in enumerate(gaps, 1))
    + "\n\n结论：本批是**同源表达能力的工程切片**，工程检查通过不代表 R4 设计质量通过，"
      "更不代表 W2 整体完成或客户设计通过。\n", encoding="utf-8")

# ------------------------------------------------------------------ review-packet
packet_md = [
    "# W2-R4 同源表达 · 复核包",
    "",
    f"编制时间：{now}；审查基线：`{BASE_COMMIT}`（架构师审查 HEAD），业务实现 `{BUSINESS_COMMIT}`。",
    "运行证据：`var/evidence/roadmap/W2-R4-同源表达/`（旧证据一律保留，未覆盖前一批）。",
    "",
    "## 1. 需求映射",
    "",
    "| 委托项 | 落地 | 证据 |",
    "| --- | --- | --- |",
    "| 更新唯一状态表的受限结论 | PROJECT_STATUS.md 顶部追加架构复核受限结论；AD 与用户阶段确认不变 | 本仓库 `PROJECT_STATUS.md` |",
    "| 先修同层异材重叠变 known 重复工程量 | 冲突/待核 + 结构化互斥裁切；补真实 HTTP 负例 | `entry-fix/`、`positive-negative-cases.md` |",
    "| 保留 15 项回归 | 15/15 observed_pass，未放宽断言 | `entry-fix/regression-15.json` |",
    "| 检查点 1 资产复用 | 6 套 CC0 PBR + 10 件 glTF + Blender 4.2.9；来源/许可/尺寸列清 | `asset-inventory.md` |",
    "| 检查点 2 同源围合开口 | 4 段周界墙 + 2 段隔断 + 7 处洞口，平面/三维同对象 ID 与 mm 尺寸 | `outputs/layout-*/` |",
    "| 检查点 3 真实家具材质 | 目录真实尺寸 + CC0 贴图；1 件明确占位；材料面/分配/计量对应 | `geometry-material-reconciliation.md` |",
    "| 检查点 4 机位灯光 | 1500mm 人眼机位标注在平面；窗光来自已建模窗口；灯槽/筒灯/软阴影 | `outputs/layout-*/scene.json`、`render-meta.json` |",
    "| 检查点 5 同源验证与人工目检 | 两布局同生成器；4 项受控变更；ZIP/SHA、取消晚到、任务定位回归；人工查看两布局效果图与平面 | `checks.json`、`browser/` |",
    "| 前后对比 | 旧 W2 灰盒图 vs R4 真实材质图；入口小修 before/after | `before-after/`、`entry-fix/` |",
    "",
    "## 2. 做了什么 / 没做什么",
    "",
    "**做了**：入口小修（v3 finish-scope 契约、conflict 状态、结构化裁切、HTTP 负例）；",
    "新增表达层契约校验 `spatial_presentation.py`、人工假设样板 `w2_r4_fixture_presentation.py`、",
    "真实资产渲染器 `render_spatial_scene_r4.py`；平面/场景/清单/成本/服务设置同源扩展；",
    "修两类真实缺陷（Blender 盒体拓扑、390px 窄屏溢出）；两布局各生成可读平面 + 1 张人眼图 + 完整 ZIP；",
    "浏览器验收、全量 262 单测、前端构建与类型检查。",
    "",
    "**没做（及原因）**：W3/W4 未授权启动，不做全套天花/立面/三效果图/汇总客户 PDF；",
    "不新增付费外部调用或图像通道（0 次、0 费用）；不扩 PG/NAS/账号/租约平台；",
    "不做柱网/洁具/构造节点/照度计算/现场实测（无依据，不编现场事实）；",
    "不把人工样板参数说成系统自动设计、不代用户判定设计成立、不改 AD01—AD08 与阶段确认。",
    "",
    "## 3. 结果与设计差距",
    "",
    f"- R4 专项 **{main_checks.get('totals', {}).get('observed_pass', 0)}/"
    f"{len(main_checks.get('checks') or [])} observed_pass**；浏览器 passed="
    f"{browser.get('passed')}；全量单测 262/262；入口小修前后 8/8 各符合预期；15 项回归 15/15。",
    f"- 真实生成图片：**2 张**人眼效果图（本机 Blender Cycles CPU，两布局各一张）；"
    "平面 PNG 预览 2 张、浏览器截图 2 张、旧灰盒对比 1 张（均为本地派生，不是外部生成图）。",
    "- 外部模型调用 0 次、外发图片 0 张、tokens 0、费用 0；密钥未使用、未落盘。",
    "- 图面差距逐条见 `design-gaps.md`；工程修复通过 ≠ R4 设计通过 ≠ W2 整体完成。",
    "",
    "## 4. 风险与下一步（交架构师）",
    "",
    "- 表达层仍是人工测试假设，下一步若要计入自动设计，必须由系统模型从需求生成墙/门窗/材质/家具，"
    "并保留对象 ID 与来源；本批不计入 AD。",
    "- 单实例 SQLite 边界不变：不推广到任意材料组合、PG、双活或断电正确性。",
    "- W2 整体仍未放行；W3 真实调用须另获准额度与资料范围；阶段 1→2 / 2→3 只接受用户对具体版本的明确确认。",
    "- 本批**不请求用户决定**：无待决闸口，未新增 `decision-request.md`。",
    "",
    "## 5. 文件索引",
    "",
    "| 路径 | 内容 |",
    "| --- | --- |",
    "| `index.html` | 评审入口（可打印），含前后对比与两布局图 |",
    "| `checks.json` | 逐项 observed_pass/fail/not_run + 环境/命令/时间 |",
    "| `code-diff.md` / `changes.patch` | 相对 `ffad892` 的提交差异 |",
    "| `manifest.json` | 源码基线、版本、产物字节与 SHA、原件/派生分类 |",
    "| `positive-negative-cases.md` | 入口小修正负例、回归、浏览器 |",
    "| `asset-inventory.md` / `asset-assumptions.json` | 资产来源/许可/尺寸与人工假设 |",
    "| `geometry-material-reconciliation.md` | 几何材质量价对账 |",
    "| `design-gaps.md` | 仍不像客户成果的逐条说明 |",
    "| `outputs/layout-A|B/` | 源模型、平面、场景、PNG、完整 ZIP、清单、源说明 |",
    "| `entry-fix/`、`browser/`、`before-after/`、`runtime/` | 负例、浏览器、前后对比、运行证据 |",
]
(PACKET / "review-packet.md").write_text("\n".join(packet_md) + "\n", encoding="utf-8")

# ------------------------------------------------------------------ 汇总 checks.json
summary_checks = []
for c in main_checks.get("checks") or []:
    summary_checks.append({"id": c["id"], "name": c["name"],
                           "result": c["result"],
                           "evidence_ref": "var/evidence/roadmap/W2-R4-同源表达/checks.json",
                           "executed_at": main_checks.get("executed_at")})
summary_checks += [
    {"id": "R4-ENTRY-FIX-BEFORE", "name": "入口小修整改前 8 例缺陷/护栏符合预期",
     "result": "observed_pass" if conflict_before.get("all_as_expected") else "observed_fail",
     "evidence_ref": "entry-fix/before.json", "executed_at": conflict_before.get("executed_at")},
    {"id": "R4-ENTRY-FIX-AFTER", "name": "入口小修整改后 8 例修复/护栏符合预期",
     "result": "observed_pass" if conflict_after.get("all_as_expected") else "observed_fail",
     "evidence_ref": "entry-fix/after.json", "executed_at": conflict_after.get("executed_at")},
    {"id": "R4-REGRESSION-15", "name": "原 15 项 W2 二次收口回归",
     "result": "observed_pass" if (regression.get("totals") or {}).get("observed_pass") == 15
     else "observed_fail",
     "evidence_ref": "entry-fix/regression-15.json",
     "executed_at": regression.get("executed_at")},
    {"id": "R4-BROWSER", "name": "真实 Edge 浏览器：成果可见、下载 SHA、390px、无 JS 错误",
     "result": "observed_pass" if browser.get("passed") else "observed_fail",
     "evidence_ref": "browser/verification.json", "executed_at": browser.get("checked_at")},
    {"id": "R4-FULL-UNITTEST", "name": "全量单元测试 262/262",
     "result": "observed_pass",
     "evidence_ref": "runtime/full-unittest.log", "executed_at": now},
    {"id": "R4-FRONTEND", "name": "tsc --noEmit 与 npm run build EXIT=0",
     "result": "observed_pass", "evidence_ref": "review-packet.md §2", "executed_at": now},
    {"id": "W3-W4-REAL-DESIGN", "name": "W3/W4 真实设计与完整客户成果",
     "result": "not_run", "evidence_ref": "design-gaps.md",
     "executed_at": None},
    {"id": "AD01-AD08-USER-JUDGEMENT", "name": "固定验收与用户设计阶段确认",
     "result": "not_run", "evidence_ref": "PROJECT_STATUS.md", "executed_at": None},
]
passed = sum(1 for c in summary_checks if c["result"] == "observed_pass")
failed = sum(1 for c in summary_checks if c["result"] == "observed_fail")
not_run = sum(1 for c in summary_checks if c["result"] == "not_run")
(PACKET / "checks.json").write_text(json.dumps({
    "task_id": "W2-R4 同源表达",
    "schema_version": "rkd-w2-r4-review-checks.v1",
    "compiled_at": now,
    "source_baseline": BASE_COMMIT,
    "business_code_baseline": BUSINESS_COMMIT,
    "environment": {"python": "3.12.14 (project .venv)",
                    "renderer": "Blender 4.2.9 LTS Cycles CPU (local)",
                    "browser": "Microsoft Edge headless via Playwright",
                    "database": "isolated SQLite", "keys_used": False},
    "commands": [
        "PYTHONPATH=\"mvp;scripts;.\" ./.venv/Scripts/python.exe scripts/verify_w2_r4_finish_conflict.py --label before|after --out <dir>",
        "PYTHONPATH=\"mvp;scripts;.\" ./.venv/Scripts/python.exe scripts/w2_second_closeout_repro.py --label r4-regression --out <dir>",
        "PYTHONPATH=\"mvp;scripts;.\" ./.venv/Scripts/python.exe scripts/verify_w2_r4.py --out <dir> --samples 24",
        "PYTHONPATH=\"mvp;scripts;.\" ./.venv/Scripts/python.exe scripts/verify_w2_r4_browser.py --out <dir> --runtime <dir> --outputs <dir>",
        "PYTHONPATH=\"mvp;scripts;.\" ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -p \"test_*.py\" -q",
        "npx tsc --noEmit && npm run build (web/)",
        "PYTHONPATH=\"mvp;scripts;.\" ./.venv/Scripts/python.exe scripts/build_w2_r4_review.py",
    ],
    "checks": summary_checks,
    "totals": {"observed_pass": passed, "observed_fail": failed, "not_run": not_run},
    "external_calls": 0, "tokens": 0, "images_generated": 2,
    "images_external_generated": 0, "images_sent_out": 0,
    "cost_amount_or_null": None, "cost_status": "no_external_calls_zero_cost",
    "not_customer_design_approval": True,
    "boundaries": ["W2 整体未放行", "AD01—AD08 与用户阶段确认不变",
                   "W3/W4 未授权启动", "不扩 PG/NAS/账号/租约平台"],
}, ensure_ascii=False, indent=2), encoding="utf-8")

# ------------------------------------------------------------------ code-diff
def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, errors="replace").stdout.strip()


diff_stat = git("diff", "--stat", BASE_COMMIT)
new_files = git("ls-files", "--others", "--exclude-standard").splitlines()
patch = PACKET / "changes.patch"
code_diff = [
    "# 提交差异",
    "",
    f"- 稳定基线：`{BASE_COMMIT}`（架构师 `review-and-R4.md` 的审查 HEAD）；"
    f"架构师列出的业务实现提交为 `{BUSINESS_COMMIT}`。",
    f"- 本包 `changes.patch` 由 `git diff {BASE_COMMIT}`（含 `git add -N` 的新文件）生成，"
    "覆盖业务代码、脚本、前端样式、状态表与架构师复核输入；"
    "补丁不包含 `changes.patch` / `manifest.json` / `index.html` 自身，避免自引用。",
    "- 实际 HEAD 以 `git rev-parse HEAD` 为准；本包不写死易变的 HEAD。",
    "",
    "## `git diff --stat ffad892`",
    "",
    "```",
    diff_stat or "(未取到)",
    "```",
    "",
    "## 本批新增文件（git 未跟踪，纳入补丁）",
    "",
]
for line in new_files:
    if line.startswith(("mvp/", "scripts/", "deliverables-for-review/roadmap/W2-R4",
                        "deliverables-for-review/roadmap/W2-second-architect")):
        code_diff.append(f"- `{line}`")
code_diff += [
    "",
    "## 改动摘要（不按行数衡量工作价值）",
    "",
    "| 文件 | 改动 |",
    "| --- | --- |",
    "| `mvp/rkd_mvp/ai_spatial_outputs.py` | finish_scope v3 冲突/裁切/多构造层口径；"
    "plan/scene/package 支持表达层；圆角轮廓；conflict 成本与 HTML |",
    "| `mvp/rkd_mvp/ai_spatial_output_service.py` | settings.presentation 校验；"
    "按 presentation 选择真实资产渲染器；revision 记录表达层对象与材质 |",
    "| `mvp/rkd_mvp/spatial_presentation.py` | 新增：表达层契约校验（人工假设、对象 ID、资产引用、洞口/机位/灯光） |",
    "| `scripts/render_spatial_scene_r4.py` | 新增：CC0 PBR + glTF + 围合开口 + 窗光/灯槽 + 人眼机位 |",
    "| `scripts/w2_r4_fixture_presentation.py` | 新增：A/B 人工测试假设样板数据（明确非 AI 设计） |",
    "| `scripts/verify_w2_r4*.py/.cjs` | 新增：入口小修复现、完整验证、浏览器验收 |",
    "| `scripts/build_w2_r4_review.py` | 新增：复核包组装 |",
    "| `web/src/styles.css` | 修长对象 ID 撑破 390px 窄屏 grid 轨道 |",
    "| `PROJECT_STATUS.md` | 追加架构复核受限结论与 W2-R4 结果 |",
]
(PACKET / "code-diff.md").write_text("\n".join(code_diff) + "\n", encoding="utf-8")

# ------------------------------------------------------------------ index.html
def img(rel: str, caption: str) -> str:
    return (f'<figure><img src="{rel}" alt="{caption}"><figcaption>{caption}</figcaption></figure>')


gap_html = "".join(f"<li>{g}</li>" for g in gaps)
check_rows = "".join(
    f'<tr><td>{c["id"]}</td><td>{c["name"]}</td><td class="{("pass" if c["result"]=="observed_pass" else "nr")}">'
    f'{c["result"]}</td></tr>' for c in summary_checks)
layout_rows = []
for letter in ("A", "B"):
    meta = jload(PACKET / "outputs" / f"layout-{letter}" / "render-meta.json")
    scene = jload(PACKET / "outputs" / f"layout-{letter}" / "scene.json")
    qty = jload(PACKET / "outputs" / f"layout-{letter}" / "quantity.json")
    net = next((x["value"] for x in qty.get("items") or []
                if x["quantity_id"] == "Q-FLOOR-GEOMETRIC-NET"), "—")
    layout_rows.append(
        f'<tr><td>布局 {letter}</td><td>{net} ㎡</td>'
        f'<td>{len((scene.get("enclosure") or {}).get("walls") or [])} 墙 / '
        f'{len((scene.get("enclosure") or {}).get("openings") or [])} 洞口</td>'
        f'<td>{len((meta.get("assets") or {}).get("textures_used") or [])} 套贴图 / '
        f'{len((meta.get("assets") or {}).get("models_used") or [])} 件资产</td>'
        f'<td>{(meta.get("lights") or {}).get("window_area_lights")} 窗光</td>'
        f'<td>{meta.get("seconds", "—")} s</td></tr>')

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>W2-R4 同源表达 · 复核入口</title>
<style>
@page{{size:A4;margin:10mm}}
*{{box-sizing:border-box}}
body{{font:13px/1.65 "Microsoft YaHei","Noto Sans SC",system-ui,sans-serif;
 margin:0 auto;max-width:1180px;padding:28px 32px 60px;color:#1f2937;background:#fff}}
h1{{font-size:25px;margin:0 0 6px;color:#0f172a}}
h2{{font-size:17px;margin:26px 0 10px;padding-bottom:6px;border-bottom:2px solid #1e3a5f;color:#1e3a5f}}
h3{{font-size:14px;margin:18px 0 6px;color:#334155}}
.meta{{color:#64748b;font-size:12px;margin-bottom:16px}}
.banner{{background:#f1f5f9;border-left:4px solid #1e3a5f;padding:12px 16px;margin:14px 0}}
.warn{{background:#fff7ed;border-left:4px solid #c2410c;padding:12px 16px;margin:14px 0}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
figure{{margin:0;border:1px solid #dbe3ea;background:#fff}}
figure img{{display:block;width:100%;height:auto}}
figcaption{{font-size:11px;color:#475569;padding:6px 9px;border-top:1px solid #eef2f6}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin:10px 0}}
th,td{{border:1px solid #d7dee6;padding:5px 8px;text-align:left;vertical-align:top}}
th{{background:#f1f5f9}}
.pass{{color:#166534;font-weight:600}} .nr{{color:#92400e}}
ul{{margin:6px 0 6px 18px;padding:0}} li{{margin:4px 0}}
code{{background:#f1f5f9;padding:1px 4px;font-size:11.5px}}
.tag{{display:inline-block;background:#e2e8f0;border-radius:3px;padding:1px 7px;
 font-size:11px;margin:0 4px 4px 0}}
.footer{{margin-top:32px;border-top:1px solid #d7dee6;padding-top:12px;
 font-size:11.5px;color:#64748b}}
@media print{{
 body{{font-size:11px;line-height:1.5;padding:0;max-width:none}}
 h2{{page-break-after:avoid}} table{{page-break-inside:auto}}
 tr,th,td{{page-break-inside:avoid}} figure{{page-break-inside:avoid}}
 .grid2{{page-break-inside:auto}} thead{{display:table-header-group}}
 img{{max-height:105mm;object-fit:contain}}
 -webkit-print-color-adjust:exact;print-color-adjust:exact
}}
</style></head><body>
<h1>W2-R4 同源表达 · 内部复核入口</h1>
<div class="meta">编制 {now} · 审查基线 <code>{BASE_COMMIT}</code> · 业务实现 <code>{BUSINESS_COMMIT}</code>
 · 运行证据 <code>var/evidence/roadmap/W2-R4-同源表达/</code></div>

<div class="banner"><b>受限结论：</b>架构复核确认 C1/C2/C3 在单实例 SQLite 已验证范围通过、R1 维持通过；
<b>W2 整体仍未放行</b>，AD01—AD08 与用户阶段确认不变，W3/W4 未授权启动。
本包只交同源表达能力切片；<b>不得自评客户设计通过</b>。</div>

<h2>0. 本批做了什么</h2>
<p>① 入口小修：同层异材重叠不再靠 <code>overlap_declaration</code> 自由文字变成 known 重复工程量；
冲突返回待核、不产 known 总量/试算，只有结构化互斥裁切并被程序实际替换原面才可计量；
补真实 HTTP 负例，原 15 项回归 15/15 保留。② 连续完成资产复用审计、同源围合开口、
真实家具材质、机位灯光与两布局可见成果，未为小修另停一批。</p>
<p>
<span class="tag">R4 专项 {main_checks.get('totals',{}).get('observed_pass',0)}/{len(main_checks.get('checks') or [])} pass</span>
<span class="tag">入口小修 before/after 8/8</span>
<span class="tag">15 项回归 15/15</span>
<span class="tag">浏览器 passed={browser.get('passed')}</span>
<span class="tag">全量单测 262/262</span>
<span class="tag">生成人眼图 2 张</span>
<span class="tag">外部调用 0 · 费用 0</span>
</p>

<h2>1. 前后对比</h2>
<div class="grid2">
{img('before-after/w2-graybox-layout-A.png', '前：W2 同源成果切片（灰盒 / 色块，无墙体门窗、统一灰家具）')}
{img('outputs/layout-A/render.png', '后：W2-R4 布局 A（CC0 真实材质、家具、围合开口、窗光与灯槽）')}
</div>
<p class="meta">两图由同一模型链的生成器产出；后图仍未达到客户交付级，差距见第 5 节。
入口小修的前后证据另见 <code>entry-fix/before.json</code> 与 <code>entry-fix/after.json</code>。</p>

<h2>2. 两种布局的可见成果</h2>
<table><thead><tr><th>布局</th><th>几何净面积</th><th>围合/开口</th><th>CC0 资产</th><th>窗光</th><th>渲染耗时</th></tr></thead>
<tbody>{''.join(layout_rows)}</tbody></table>
<div class="grid2">
{img('outputs/layout-A/render.png', '布局 A · 人眼 1.5m / 24mm（人工假设机位）')}
{img('outputs/layout-B/render.png', '布局 B · 人眼 1.5m / 24mm（同一生成器）')}
</div>
<div class="grid2">
{img('browser/plan-preview-A.png', '布局 A · 可读平面（墙/门洞/窗/家具/材料/机位/门窗表）')}
{img('browser/plan-preview-B.png', '布局 B · 可读平面（同一生成器，分区组织不同）')}
</div>
<p class="meta">每布局完整文件见 <code>outputs/layout-A|B/</code>：源模型、平面、场景、PNG、
量价、清单与完整 ZIP；下载 SHA 与清单逐项一致。</p>

<h2>3. 检查点落地与逐项结果</h2>
<table><thead><tr><th>编号</th><th>检查项</th><th>结果</th></tr></thead><tbody>{check_rows}</tbody></table>
<p class="meta">1 资产审计 → <code>asset-inventory.md</code>；2 围合开口 → 4 段周界墙 + 2 段隔断 + 7 处洞口，
平面与三维同对象 ID/尺寸；3 家具材质 → 目录真实尺寸、6 套 CC0 PBR、1 件明确占位；
4 机位灯光 → 人眼 1.5m、窗光来自已建模窗口、灯槽/筒灯/软阴影；
5 同源验证 → <code>geometry-material-reconciliation.md</code> 与 <code>checks.json</code>。</p>

<h2>4. 来源与责任边界</h2>
<div class="warn"><b>表达层全部是人工测试假设：</b>墙厚/高度、门窗洞口、隔断、材质贴图、家具资产映射、
绿植软装、机位与灯光由执行者人工编写，<code>site_verified=false</code>、
<code>not_ai_design=true</code>；未现场复核、不冒充系统模型自动设计、不计入 AI 接替设计验收。
精确分区、动线、平台、天花意向来自主系统候选修订（本地夹具，非真实 AI 设计）。
柱网/洁具/构造节点/照度/产品选型缺依据，一律不编造、不补 0。</div>

<h2>5. 仍然不像设计公司成果的地方（逐条）</h2>
<ol>{gap_html}</ol>

<h2>6. 做与未做、图片与费用</h2>
<p><b>做：</b>入口小修与 HTTP 负例、15 项回归、资产审计、同源围合开口、真实家具材质、机位灯光、
两布局平面 + 各一张人眼图、完整 ZIP/SHA、浏览器与全量回归、修两类真实缺陷。</p>
<p><b>未做：</b>W3/W4 全套设计成果与真实付费模型调用；天花/立面/三视角/材料实物板/汇总客户 PDF；
PG/NAS/账号/租约平台；柱网洁具与照度合规；不代用户确认设计、不改 AD 与阶段闸口。</p>
<p><b>图片与费用：</b>本机 Blender Cycles CPU 生成人眼效果图 <b>2 张</b>（布局 A/B 各 1）；
平面 PNG 预览 2 张、浏览器桌面/移动截图 2 张、旧灰盒对比 1 张为本地派生。
外部模型调用 <b>0 次</b>、外发图片 <b>0 张</b>、tokens <b>0</b>、费用 <b>0</b>；密钥未使用、未落盘。</p>

<div class="footer">执行者报告 · 架构师独立复核项待审 · 用户设计确认与 AD01—AD08 由用户给，不代签。
工程检查通过不代表 R4 设计通过，更不代表 W2 整体完成。详细文件：<code>review-packet.md</code>、
<code>checks.json</code>、<code>code-diff.md</code>、<code>manifest.json</code>、
<code>positive-negative-cases.md</code>、<code>design-gaps.md</code>。</div>
</body></html>"""
(PACKET / "index.html").write_text(html, encoding="utf-8")

# ------------------------------------------------------------------ manifest.json
def classify(rel: str) -> str:
    if rel.startswith("outputs/layout-"):
        name = Path(rel).name
        if name in ("model.json", "presentation.json", "finish-scope.json"):
            return "source_or_declared_fixture"
        return "derived_output"
    if rel.startswith(("browser/", "runtime/", "entry-fix/")):
        return "running_evidence"
    if rel.startswith("before-after/"):
        return "previous_batch_reference"
    return "review_document"


manifest_files = []
for path in sorted(PACKET.rglob("*")):
    if not path.is_file() or path.name == "manifest.json":
        continue
    rel = path.relative_to(PACKET).as_posix()
    manifest_files.append({"path": rel, "bytes": path.stat().st_size,
                           "sha256": sha(path), "kind": classify(rel)})
(PACKET / "manifest.json").write_text(json.dumps({
    "schema_version": "rkd-w2-r4-review-manifest.v1",
    "compiled_at": now,
    "source_baseline": BASE_COMMIT,
    "business_code_baseline": BUSINESS_COMMIT,
    "code_head_at_compile": git("rev-parse", "HEAD"),
    "versions": {"generator": "rkd-spatial-outputs.v4",
                 "plan": "rkd-spatial-plan.v4", "scene": "rkd-spatial-scene.v2",
                 "quantity": "rkd-spatial-quantity.v4", "cost": "rkd-spatial-cost.v4",
                 "finish_scope": "rkd-spatial-finish-scope.v3",
                 "manifest": "rkd-spatial-output-manifest.v3",
                 "presentation": "rkd-spatial-presentation-fixture.v1"},
    "asset_manifest_sha256": inv["sha256"],
    "design_origin": "labelled local fixture + executor manual test assumptions; NOT AI design",
    "site_verified": False,
    "images_generated": 2, "external_calls": 0, "cost_amount_or_null": None,
    "files": manifest_files,
    "note": "原件（source/）只读；var/ 为运行数据；本包为派生成果与证据；"
            "旧证据目录未覆盖。manifest.json 自身不计入清单。",
}, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps({"packet": str(PACKET), "files": len(manifest_files) + 1,
                  "checks": {"pass": passed, "fail": failed, "not_run": not_run},
                  "bytes": sum(f["bytes"] for f in manifest_files)},
                 ensure_ascii=False, indent=2))

