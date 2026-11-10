"""Stage 1 deliverable: a checkable real-site base map for Ningbo Xiecheng.

Reads the already-parsed CAD evidence (no new CAD parsing, no perfect
topology cleanup) and the original A3 PDF plan. Produces:

* the forward-oriented original PDF plan as PNG;
* a 1:1 metric site base map as SVG with colour-coded confidence;
* a transparent geometry overlay SVG aligned to the PDF plan;
* a machine-readable element/status inventory;
* a double-clickable "打开我看.html" entry page.

"解析确认" (green) = geometry present in the CAD evidence with high mapping
confidence. "待现场复核" (orange, dashed) = inferred, low-confidence, or not
extracted at all. Nothing here is a construction drawing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
DERIVED = SOURCE / "derived"
PDF = SOURCE / "source" / "平面图.pdf"
OUT = ROOT / "var" / "deliverables" / "ningbo-xiecheng" / "2026-11-10"
STAMP = "2026-11-10"

# Pixel rect of the exhibition hall outer boundary in the 2859x2021
# forward-oriented PDF render, established from the PDF's drawing paths.
PDF_SIZE = (2859, 2021)
PLAN_RECT = (452.0, 367.0, 2214.0, 1610.0)

CONFIRMED = "#1c6b48"
REVIEW = "#c0701c"
NEUTRAL = "#8b98a4"
DOOR = "#2a5f8f"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((DERIVED / name).read_text(encoding="utf-8"))


def render_forward_pdf() -> Path:
    doc = fitz.open(PDF)
    matrix = fitz.Matrix(2.4, 2.4).prerotate(270)
    pix = doc[0].get_pixmap(matrix=matrix, alpha=False)
    target = OUT / "00_原始平面图_正向.png"
    pix.save(target)
    doc.close()
    return target


def site_frame(plan: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    bounds = plan["target_region"]["bounds"]
    minx, miny = bounds["minimum"]
    maxx, maxy = bounds["maximum"]
    return float(minx), float(miny), float(maxx), float(maxy), float(maxx - minx), float(maxy - miny)


def point(pt: list[float], frame: tuple[float, ...]) -> tuple[float, float]:
    minx, miny, _, maxy, _, _ = frame
    return (float(pt[0]) - minx, maxy - float(pt[1]))


def polyline(candidate: dict[str, Any], frame: tuple[float, ...], *, color: str,
             width: float, dashed: bool = False, opacity: float = 1.0) -> str:
    points = candidate.get("geometry_points") or []
    if len(points) < 2:
        return ""
    coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(p, frame) for p in points))
    dash = f' stroke-dasharray="{width * 4:.0f} {width * 3:.0f}"' if dashed else ""
    return (f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{width}"'
            f'{dash} stroke-opacity="{opacity}" stroke-linecap="round" stroke-linejoin="round"/>')


def polygon(ring: list[list[float]], frame: tuple[float, ...], *, color: str,
            opacity: float, dashed: bool = False) -> str:
    if len(ring) < 3:
        return ""
    coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(p, frame) for p in ring))
    dash = ' stroke-dasharray="60 40"' if dashed else ""
    return (f'<polygon points="{coords}" fill="{color}" fill-opacity="{opacity}" '
            f'stroke="{color}" stroke-width="18"{dash}/>')


def collect(plan: dict[str, Any], regions: dict[str, Any], frame: tuple[float, ...]) -> dict[str, Any]:
    current = [item for item in plan["candidates"]
               if item.get("scope_disposition") == "included-design-evidence"]
    # HATCH boundaries are fill patterns, not wall centrelines; joining their
    # sampled points draws a false long diagonal across the whole plan.
    walls = [item for item in current if item.get("category") == "architecture.wall"
             and item.get("source_entity_type") != "HATCH"]
    doors = [item for item in current if item.get("category") == "architecture.opening.door"]
    circles = [item for item in current if item.get("source_entity_type") == "CIRCLE"]
    low = [item for item in current if float(item.get("mapping_confidence") or 0) < 0.9]
    wall_polygons = [item for item in regions.get("region_candidates", [])
                     if item.get("category") == "architecture.wall" and item.get("exterior_ring")]
    confirmed_wall_ids = {item.get("candidate_id") for item in current
                          if float(item.get("mapping_confidence") or 0) >= 0.9}
    return {"current": current, "walls": walls, "doors": doors, "circles": circles,
            "low": low, "wall_polygons": wall_polygons, "confirmed_wall_ids": confirmed_wall_ids}


def geometry_svg(data: dict[str, Any], frame: tuple[float, ...], *, frame_only: bool) -> str:
    _, _, _, _, width, height = frame
    parts: list[str] = []
    # Outer boundary: anchor layers matched in plan-localization-profile.
    parts.append(f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="none" '
                 f'stroke="{CONFIRMED}" stroke-width="55"/>')
    # Wall solids with real thickness from polygon candidates.
    for item in data["wall_polygons"]:
        parts.append(polygon(item["exterior_ring"], frame, color=CONFIRMED, opacity=0.30))
    # Wall linework.
    for item in data["walls"]:
        color = CONFIRMED if item.get("candidate_id") in data["confirmed_wall_ids"] else REVIEW
        parts.append(polyline(item, frame, color=color, width=30, dashed=color == REVIEW))
    # Doors.
    for item in data["doors"]:
        parts.append(polyline(item, frame, color=DOOR, width=42))
    # Possible columns (circles) - DXF has no independent column category.
    for index, item in enumerate(data["circles"]):
        pts = item.get("geometry_points") or []
        if not pts:
            continue
        cx, cy = point(pts[0], frame)
        b = item.get("bounds") or {}
        radius = max(120.0, min(400.0, float((b.get("maximum", [0, 0])[0] - b.get("minimum", [0, 0])[0]) / 2) or 180.0))
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius:.0f}" fill="{REVIEW}" '
                     f'fill-opacity="0.22" stroke="{REVIEW}" stroke-width="22" stroke-dasharray="60 40"/>')
        if index == 0:
            parts.append(f'<text x="{cx + radius + 80:.0f}" y="{cy:.0f}" font-size="165" fill="{REVIEW}">疑似柱/圆形对象?</text>')
    # Entrance candidate: a door on the left perimeter, inferred from the PDF lobby.
    entrance = None
    for item in data["doors"]:
        pts = item.get("geometry_points") or []
        if pts and min(point(p, frame)[0] for p in pts) < 500:
            entrance = item
            break
    if entrance:
        pts = entrance.get("geometry_points") or []
        ex, ey = point(pts[0], frame)
        parts.append(f'<g><path d="M {max(120, ex - 320):.0f} {ey:.0f} L {ex + 700:.0f} {ey:.0f}" '
                     f'stroke="{REVIEW}" stroke-width="55" marker-end="url(#arrow)"/>'
                     f'<text x="{max(160, ex - 340):.0f}" y="{ey - 150:.0f}" font-size="190" fill="{REVIEW}">主入口（推断·待复核）</text></g>')
    # Obstructions visible on the PDF but not classified in CAD evidence.
    # Drawn as approximate review boxes, explicitly labelled as visual estimates.
    parts.append(f'<rect x="0" y="{height - 8400:.0f}" width="2300" height="8200" fill="none" '
                 f'stroke="{REVIEW}" stroke-width="26" stroke-dasharray="90 65"/>')
    parts.append(f'<text x="120" y="{height - 8600:.0f}" font-size="170" fill="{REVIEW}">楼梯/结构（目测·待复核）</text>')
    parts.append(f'<rect x="{width - 4200:.0f}" y="{height - 9200:.0f}" width="4100" height="5200" fill="none" '
                 f'stroke="{REVIEW}" stroke-width="26" stroke-dasharray="90 65"/>')
    parts.append(f'<text x="{width - 4100:.0f}" y="{height - 9400:.0f}" font-size="170" fill="{REVIEW}">卫生湿区（目测·待复核）</text>')
    # Windows: no independent CAD category; flag rather than invent positions.
    parts.append(f'<text x="{width - 7600:.0f}" y="330" font-size="185" fill="{REVIEW}">外墙开窗：未提取，待现场复核</text>')
    if frame_only:
        return "\n".join(parts)
    return "\n".join(parts)


def build_base_map_svg(data: dict[str, Any], frame: tuple[float, ...]) -> str:
    _, _, _, _, width, height = frame
    margin, legend_w, title_h = 900.0, 5200.0, 1500.0
    total_w, total_h = width + margin * 2 + legend_w, height + margin * 2 + title_h
    body = geometry_svg(data, frame, frame_only=True)
    legend = [
        (CONFIRMED, "解析确认", "CAD 候选置信度 ≥0.9 / 定位图层匹配"),
        (DOOR, "门（解析）", "DXF 门图层候选，墙洞口配对待复核"),
        (REVIEW, "待现场复核", "推断、低置信度或未提取"),
    ]
    legend_svg = [f'<text x="{width + margin + 200:.0f}" y="{margin + 200:.0f}" font-size="230" '
                  f'font-weight="600" fill="#2b3a49">图例 LEGEND</text>']
    for index, (color, label, note) in enumerate(legend):
        y = margin + 500 + index * 620
        legend_svg.append(f'<rect x="{width + margin + 200:.0f}" y="{y:.0f}" width="320" height="220" '
                          f'fill="{color}" fill-opacity="0.35" stroke="{color}" stroke-width="22"/>')
        legend_svg.append(f'<text x="{width + margin + 620:.0f}" y="{y + 180:.0f}" font-size="185" fill="#2b3a49">{escape(label)}</text>')
        legend_svg.append(f'<text x="{width + margin + 620:.0f}" y="{y + 430:.0f}" font-size="140" fill="#6b7a8a">{escape(note)}</text>')
    note_y = margin + 500 + len(legend) * 620 + 300
    notes = ["阶段 1 底图 · 仅供核对", "非施工定位依据", "尺寸单位 mm（标注为 m）",
             "外轮廓 26.17 × 17.92 m", "来源：宁波 DXF/DWG + A3 平面图", "未清完 133 项拓扑复核"]
    for index, note in enumerate(notes):
        legend_svg.append(f'<text x="{width + margin + 200:.0f}" y="{note_y + index * 300:.0f}" '
                          f'font-size="155" fill="#8a6836">{escape(note)}</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.0f} {total_h:.0f}" role="img" aria-label="宁波协诚真实场地底图">
<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">
<path d="M0,0 L10,5 L0,10 z" fill="{REVIEW}"/></marker></defs>
<rect width="{total_w:.0f}" height="{total_h:.0f}" fill="#ffffff"/>
<rect x="60" y="60" width="{total_w - 120:.0f}" height="{total_h - 120:.0f}" fill="none" stroke="#c9d2da" stroke-width="12"/>
<g transform="translate({margin:.0f},{margin:.0f})">
<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="#fbfcfd" stroke="#e3e8ec" stroke-width="12"/>
{body}
<line x1="0" y1="-320" x2="{width:.0f}" y2="-320" stroke="#7c8894" stroke-width="14"/>
<text x="{width / 2:.0f}" y="-420" text-anchor="middle" font-size="220" fill="#4c5a68">26.17 m</text>
<line x1="-320" y1="0" x2="-320" y2="{height:.0f}" stroke="#7c8894" stroke-width="14"/>
<text transform="translate(-460,{height / 2:.0f}) rotate(-90)" text-anchor="middle" font-size="220" fill="#4c5a68">17.92 m</text>
</g>
{''.join(legend_svg)}
<line x1="{margin:.0f}" y1="{height + margin + 420:.0f}" x2="{total_w - margin:.0f}" y2="{height + margin + 420:.0f}" stroke="#c9d2da" stroke-width="12"/>
<text x="{margin:.0f}" y="{height + margin + 800:.0f}" font-size="250" font-weight="600" fill="#2b3a49">宁波协诚集团样品展厅 · 真实场地底图 / SITE BASE MAP</text>
<text x="{margin:.0f}" y="{height + margin + 1120:.0f}" font-size="175" fill="#5c6b79">阶段 1 · 2026-11-10 · 依据 DXF/DWG 解析产物与原始 A3 平面图 · 绿色为解析确认，橙色虚线为待现场复核</text>
</svg>'''


def build_overlay_svg(data: dict[str, Any], frame: tuple[float, ...]) -> str:
    _, _, _, _, width, height = frame
    body = geometry_svg(data, frame, frame_only=True)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
            f'preserveAspectRatio="none" role="img" aria-label="解析几何叠加层">'
            f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{REVIEW}"/></marker></defs>'
            f'{body}</svg>')


def build_inventory(data: dict[str, Any], frame: tuple[float, ...]) -> dict[str, Any]:
    _, _, _, _, width, height = frame
    return {
        "contract_version": "rkd-site-basemap.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": "宁波协诚集团样品展厅",
        "stage": "阶段1 · 真实场地底图（等用户确认）",
        "coordinate_space": "dwg-model-space, millimetres, origin at lower-left of target_region",
        "boundary": {"width_m": round(width / 1000, 2), "length_m": round(height / 1000, 2),
                     "source": "cad-plan-candidates.json target_region.bounds + plan-localization-profile anchor layers",
                     "status": "解析确认", "note": "与 A3 平面图 26170 / 17920 尺寸链一致"},
        "elements": [
            {"element": "展厅外轮廓", "count": 1, "status": "解析确认",
             "source": "target_region.bounds（PL-天花尺寸等定位图层 matched）"},
            {"element": "外墙（带厚度多边形）", "count": len(data["wall_polygons"]), "status": "解析确认",
             "source": "cad-region-candidates.json architecture.wall polygon candidates"},
            {"element": "墙线", "count": len(data["walls"]), "status": "部分解析确认 / 部分待复核",
             "source": "cad-plan-candidates.json architecture.wall；置信度 <0.9 标橙"},
            {"element": "门", "count": len(data["doors"]), "status": "解析确认（洞口配对待复核）",
             "source": "cad-plan-candidates.json architecture.opening.door；拓扑复核 12 项需墙开口配对"},
            {"element": "窗", "count": 0, "status": "待现场复核",
             "source": "57 个图层语义映射中无独立窗类别；未编造位置"},
            {"element": "柱（疑似圆形对象）", "count": len(data["circles"]), "status": "待现场复核",
             "source": "CIRCLE 候选；DXF 无 architecture.column 独立分类"},
            {"element": "主入口", "count": 1, "status": "待现场复核（推断）",
             "source": "A3 平面图门厅 LOBBY 位置 + 左侧外墙门候选"},
            {"element": "障碍：楼梯/结构、卫生湿区", "count": 2, "status": "待现场复核（目测范围）",
             "source": "A3 平面图斜线填充区域；DXF 未独立分类"},
        ],
        "limits": [
            "只处理设计需要的外轮廓/主要墙体/柱/门窗/入口/障碍；133 项拓扑复核未清理，保持待复核标记",
            "PDF 为 A3 排版图、DXF 为模型空间；叠加层按外轮廓像素矩形近似配准，可在入口页微调，不作为测量依据",
            "图纸注明「具体尺寸以现场实际情况为准」；未经现场实测，所有尺寸待复核",
            "固定家具、天花、地面等 400+ 候选未纳入底图，避免干扰场地核对",
        ],
        "counts": {"current_scope_candidates": len(data["current"]),
                   "low_confidence_candidates": len(data["low"]),
                   "unresolved_topology_items": 133},
    }


def build_entry_page(inventory: dict[str, Any], image_test: dict[str, Any]) -> str:
    left = PLAN_RECT[0] / PDF_SIZE[0] * 100
    top = PLAN_RECT[1] / PDF_SIZE[1] * 100
    width = (PLAN_RECT[2] - PLAN_RECT[0]) / PDF_SIZE[0] * 100
    height = (PLAN_RECT[3] - PLAN_RECT[1]) / PDF_SIZE[1] * 100
    rows = "".join(
        f"<tr><td>{escape(item['element'])}</td><td>{item['count']}</td>"
        f"<td class='{'ok' if item['status'].startswith('解析确认') else 'review'}'>{escape(item['status'])}</td>"
        f"<td>{escape(item['source'])}</td></tr>" for item in inventory["elements"])
    limits = "".join(f"<li>{escape(item)}</li>" for item in inventory["limits"])
    files = [
        ("00_原始平面图_正向.png", "宁波项目原始 A3 平面布置图（已转正，可直接核对房间与尺寸链）"),
        ("01_真实场地底图.svg", "真实场地底图：外轮廓、外墙、柱、门、窗、入口、障碍，颜色区分状态"),
        ("01b_几何叠加层.svg", "透明几何层，用于叠在原始平面图上"),
        ("阶段1_底图核对.pdf", "阶段 1 汇总 PDF：原始图 + 底图 + 状态清单，可直接发看"),
        ("底图数据.json", "每个元素的来源、数量与状态，可追溯"),
        ("图像通道测试.json", "模型通道是否支持图像生成的测试结论"),
    ]
    file_links = "".join(
        f'<li><a href="{escape(name)}" target="_blank">{escape(name)}</a>'
        f'<span>{escape(note)}</span></li>' for name, note in files)
    style_a = "A 现代轻奢：暖木饰面 + 哑光金属、2700–3000K 重点照明、低饱和米金氛围，中央中岛做视觉焦点。"
    style_b = "B 工业简约：清水混凝土灰 + 深色金属、4000K 线性光、冷灰与炭黑，长向叙事动线配侧向洽谈口袋。"
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>宁波协诚 · 阶段1 真实场地底图</title>
<style>
@page{{size:A3 landscape;margin:12mm}}
*{{box-sizing:border-box}}
body{{font:14px/1.65 "Microsoft YaHei","PingFang SC",sans-serif;color:#22303f;margin:0;background:#f4f6f8}}
.wrap{{max-width:1280px;margin:0 auto;padding:24px}}
h1{{font-size:23px;margin:0 0 4px}} h2{{font-size:17px;margin:26px 0 10px;padding-bottom:6px;border-bottom:1px solid #d9e0e6}}
h3{{font-size:14px;margin:16px 0 6px}} p{{margin:7px 0}} small{{color:#6b7a8a}}
.hero{{background:#fff;border-left:3px solid #1c6b48;padding:14px 18px;margin:14px 0 20px}}
.badge{{display:inline-block;padding:2px 9px;border:1px solid #c9d2da;border-radius:2px;font-size:12px;margin-right:6px}}
.ok{{color:#1c6b48;font-weight:600}} .review{{color:#c0701c;font-weight:600}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff}}
th,td{{padding:7px 9px;border-bottom:1px solid #e2e8ec;text-align:left;vertical-align:top}}
th{{background:#eef2f4;color:#3a4a5c}}
.files{{list-style:none;padding:0}} .files li{{background:#fff;border:1px solid #dfe6eb;padding:9px 12px;margin:6px 0}}
.files a{{font-weight:600;color:#1a5c86;margin-right:10px}} .files span{{color:#5c6b79;font-size:12.5px}}
.plan{{position:relative;width:100%;background:#fff;border:1px solid #dfe6eb;overflow:hidden;line-height:0}}
.plan>img.base{{display:block;width:100%;height:auto}}
.overlay{{position:absolute;opacity:.75;pointer-events:none}}
.controls{{background:#fff;border:1px solid #dfe6eb;padding:10px 14px;margin:8px 0 14px;line-height:1.5}}
.controls label{{display:inline-block;margin-right:18px;font-size:12.5px}}
.controls input[type=range]{{vertical-align:middle;width:110px}}
.note{{background:#fffaf0;border:1px solid #e8d5b0;padding:10px 14px;font-size:13px}}
ul{{margin:6px 0 12px;padding-left:20px}} li{{margin-bottom:5px}}
footer{{margin:26px 0 10px;color:#6b7a8a;font-size:12px;border-top:1px solid #d9e0e6;padding-top:10px}}
@media print{{body{{background:#fff}} .controls{{display:none}} .wrap{{max-width:none}}}}
</style></head><body><div class="wrap">
<h1>宁波协诚集团样品展厅 · 阶段 1 真实场地底图</h1>
<p><small>2026-11-10 · 只做底图，等你确认后再进阶段 2 · 本页双击即可打开，不需要命令行</small></p>
<div class="hero"><strong>本阶段只回答一个问题：场地底图对不对。</strong><br>
绿色 = 解析确认（CAD 证据置信度高 / 定位图层匹配）；橙色虚线 = 待现场复核（推断、低置信度或根本没提取到）。<br>
底图来自宁波项目 <code>04 平面PL.dwg/dxf</code> 的既有解析产物与原始 A3 平面图，<strong>不再使用 12×8m 测试矩形</strong>。外轮廓 <strong>26.17 × 17.92 m</strong>，与图纸尺寸链 26170 / 17920 一致。
</div>

<h2>① 我能打开的文件</h2>
<ul class="files">{file_links}</ul>

<h2>② 叠加核对：解析几何压在原始平面图上</h2>
<div class="controls">
<label>叠加透明度 <input id="op" type="range" min="0" max="100" value="72"></label>
<label>水平微调 <input id="dx" type="range" min="-80" max="80" value="0"></label>
<label>垂直微调 <input id="dy" type="range" min="-80" max="80" value="0"></label>
<label>缩放 <input id="sc" type="range" min="90" max="110" value="100"></label>
<label><input id="show" type="checkbox" checked> 显示解析层</label>
</div>
<div class="plan" id="plan">
<img class="base" src="00_原始平面图_正向.png" alt="宁波原始平面布置图">
<img class="overlay" id="ov" src="01b_几何叠加层.svg" alt="解析几何叠加层"
 style="left:{left:.3f}%;top:{top:.3f}%;width:{width:.3f}%;height:{height:.3f}%">
</div>
<p><small>叠加层按原始图外轮廓像素矩形做近似配准，可用上面滑块微调。<strong>只用于核对轮廓与元素位置，不作为测量依据</strong>；PDF 是 A3 排版图、DXF 是模型空间，未做像素级测绘配准。</small></p>

<h2>③ 单独看解析底图（1:1 米制，含图例与尺寸）</h2>
<div class="plan"><img class="base" src="01_真实场地底图.svg" alt="真实场地底图"></div>

<h2>④ 元素状态清单</h2>
<table><thead><tr><th>元素</th><th>数量</th><th>状态</th><th>来源 / 说明</th></tr></thead><tbody>{rows}</tbody></table>

<h2>⑤ 卡点与未做的事（如实）</h2>
<div class="note"><ul>{limits}</ul></div>

<h2>⑥ 阶段 2 待你确认的一句话风格定位</h2>
<p>{escape(style_a)}</p><p>{escape(style_b)}</p>
<p><small>这两句只是阶段 2 的风格起点，尚未生成任何平面或效果图；阶段 2 只看方案 A 的平面布置图 + 1 张效果图。</small></p>

<h2>⑦ 图像生成通道测试（无项目资料）</h2>
<p>{escape(image_test.get('summary', '未测试'))}</p>
<p><small>{escape(image_test.get('detail', ''))}</small></p>

<h2>⑧ 需要你决定的事（最多 2 条）</h2>
<ol>
<li><strong>底图是否正确</strong>：外轮廓、外墙、门、入口方向、楼梯/湿区位置有没有明显错？确认后我才进阶段 2。</li>
<li><strong>上面 A / B 两句话风格定位是否可用</strong>，或你想换风格关键词。</li>
</ol>

<footer>阶段 1 交付到此为止。设计是否成立只由你的评价决定，本页不自评通过；管理配套（PG / NAS / 账号 / 岗位审查 / 备份恢复）本阶段全部冻结。证据目录：var/deliverables/ningbo-xiecheng/2026-11-10/</footer>
</div>
<script>
const ov=document.getElementById('ov');
function sync(){{ov.style.opacity=document.getElementById('op').value/100;
ov.style.display=document.getElementById('show').checked?'block':'none';
const dx=+document.getElementById('dx').value,dy=+document.getElementById('dy').value,sc=+document.getElementById('sc').value/100;
ov.style.transform='translate('+dx+'px,'+dy+'px) scale('+sc+')';}}
['op','dx','dy','sc','show'].forEach(id=>document.getElementById(id).addEventListener('input',sync));sync();
</script></body></html>'''


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    plan = load_json("cad-plan-candidates.json")
    regions = load_json("cad-region-candidates.json")
    frame = site_frame(plan)
    data = collect(plan, regions, frame)
    render_forward_pdf()
    (OUT / "01_真实场地底图.svg").write_text(build_base_map_svg(data, frame), encoding="utf-8")
    (OUT / "01b_几何叠加层.svg").write_text(build_overlay_svg(data, frame), encoding="utf-8")
    inventory = build_inventory(data, frame)
    (OUT / "底图数据.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    image_test_path = OUT / "图像通道测试.json"
    image_test = json.loads(image_test_path.read_text(encoding="utf-8")) if image_test_path.exists() else {
        "summary": "尚未测试", "detail": ""}
    (OUT / "打开我看.html").write_text(build_entry_page(inventory, image_test), encoding="utf-8")
    print(json.dumps({
        "out": str(OUT), "boundary_m": [round(frame[4] / 1000, 2), round(frame[5] / 1000, 2)],
        "walls": len(data["walls"]), "wall_polygons": len(data["wall_polygons"]),
        "doors": len(data["doors"]), "circles": len(data["circles"]),
        "entry_page": str(OUT / "打开我看.html")}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
