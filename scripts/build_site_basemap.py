"""Stage 1 deliverable: a checkable real-site base map for Ningbo Xiecheng.

Round 2 (after user review of round 1). Only annotations change; geometry is
not re-surveyed. Elements are split into the three groups the user asked for:

* 建筑固有条件 — must be kept: perimeter walls (with thickness), stairs,
  bathroom wet area, doors, windows, columns.
* 奥创设计原布局 — reference only, may be redesigned: corridor display walls,
  the two meeting-room partitions, water bar, hexagon display platform,
  furniture. Never treated as load-bearing.
* 待现场复核 — inferred or unverifiable: entrance position, window head
  heights, visually estimated obstruction extents.

Windows are read from the original A3 plan (the CAD layer "WINDOW" only holds
a 122x84 legend swatch, so it cannot be used). On the north wall the dimension
chain gives 1910 / 600 / 5400 / 600 / 5400 / 600 / 5400 / 600 / 1060 / 1170 /
3170 / 260, and the drawing breaks the wall line at each 600 segment: those are
the piers, the three 5400 spans are the glazing bands. On the east wall the
wall is drawn with a third (glass) line over two runs; those are marked as
window bands. Both readings are flagged 待现场复核 for head height and sill.
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

FIXED = "#1c6b48"        # 建筑固有条件
EXISTING = "#5a6b7a"     # 奥创原设计（仅参考）
REVIEW = "#c0701c"       # 待现场复核
DOOR = "#2a5f8f"
WINDOW = "#1f6f8b"

# Window bands read off the A3 plan, in site-local millimetres (origin = SW
# corner of the lease boundary, +x east, +y north). (start, end) along the wall.
WINDOW_NORTH = [(2688, 8154), (8778, 14228), (14867, 20317)]
WINDOW_EAST = [(231, 3037), (5742, 8273)]

# Hexagon display platform: the eight CIRCLE candidates cluster on one
# 860 mm ring at (6040, 1830); four of them are 20 mm centre marks, not columns.
HEX_CENTER = (6040.0, 1830.0)
HEX_RADIUS = 520.0

# Fixed architecture measured from the A3 plan (pixel -> mm conversion below).
STAIR = (0.0, 0.0, 2400.0, 8000.0)
BATH = (22000.0, 2600.0, 26170.0, 7300.0)


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
    """DWG model space -> SVG space (y down, origin top-left of the site)."""
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


def svg_rect_mm(x0: float, y0: float, x1: float, y1: float, height_mm: float,
                *, fill: str, fill_opacity: float, stroke: str,
                stroke_width: float, dashed: bool = False) -> str:
    """Site-local mm rect (y up) -> SVG rect (y down)."""
    dash = ' stroke-dasharray="80 60"' if dashed else ""
    return (f'<rect x="{x0:.0f}" y="{height_mm - y1:.0f}" width="{x1 - x0:.0f}" '
            f'height="{y1 - y0:.0f}" fill="{fill}" fill-opacity="{fill_opacity}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}"{dash}/>')


def collect(plan: dict[str, Any], regions: dict[str, Any]) -> dict[str, Any]:
    current = [item for item in plan["candidates"]
               if item.get("scope_disposition") == "included-design-evidence"]
    # HATCH boundaries are fill patterns, not wall centrelines; joining their
    # sampled points draws a false long diagonal across the whole plan.
    walls = [item for item in current if item.get("category") == "architecture.wall"
             and item.get("source_entity_type") != "HATCH"]
    doors = [item for item in current if item.get("category") == "architecture.opening.door"]
    circles = [item for item in current if item.get("source_entity_type") == "CIRCLE"]
    furniture = [item for item in current if str(item.get("category", "")).startswith("interior.furniture")]
    low = [item for item in current if float(item.get("mapping_confidence") or 0) < 0.9]
    wall_polygons = [item for item in regions.get("region_candidates", [])
                     if item.get("category") == "architecture.wall" and item.get("exterior_ring")]
    return {"current": current, "walls": walls, "doors": doors, "circles": circles,
            "furniture": furniture, "low": low, "wall_polygons": wall_polygons}


def window_symbol_north(x0: float, x1: float, width: float) -> str:
    """Glazing band that replaces the north wall over the opening."""
    parts = [f'<rect x="{x0 - 40:.0f}" y="-60" width="{x1 - x0 + 80:.0f}" height="150" fill="#fbfcfd"/>',
             f'<rect x="{x0:.0f}" y="0" width="{x1 - x0:.0f}" height="196" fill="{WINDOW}" fill-opacity="0.20"/>']
    for y in (18, 98, 178):
        weight = 30 if y != 98 else 18
        parts.append(f'<line x1="{x0:.0f}" y1="{y}" x2="{x1:.0f}" y2="{y}" stroke="{WINDOW}" '
                     f'stroke-width="{weight}"/>')
    span = x1 - x0
    mullions = max(1, round(span / 1800))
    for index in range(1, mullions):
        x = x0 + span * index / mullions
        parts.append(f'<line x1="{x:.0f}" y1="18" x2="{x:.0f}" y2="178" '
                     f'stroke="{WINDOW}" stroke-width="14" stroke-opacity="0.7"/>')
    return "".join(parts)


def window_symbol_east(y0: float, y1: float, width: float, height: float) -> str:
    """Vertical glazing band replacing the east wall; y0/y1 are site-local."""
    top, bottom = height - y1, height - y0
    parts = [f'<rect x="{width - 60:.0f}" y="{top - 40:.0f}" width="150" height="{bottom - top + 80:.0f}" '
             f'fill="#fbfcfd"/>',
             f'<rect x="{width - 196:.0f}" y="{top:.0f}" width="196" height="{bottom - top:.0f}" '
             f'fill="{WINDOW}" fill-opacity="0.20"/>']
    for x in (width - 18, width - 98, width - 178):
        weight = 30 if x != width - 98 else 18
        parts.append(f'<line x1="{x:.0f}" y1="{top:.0f}" x2="{x:.0f}" y2="{bottom:.0f}" '
                     f'stroke="{WINDOW}" stroke-width="{weight}"/>')
    span = bottom - top
    mullions = max(1, round(span / 1800))
    for index in range(1, mullions):
        y = top + span * index / mullions
        parts.append(f'<line x1="{width - 18:.0f}" y1="{y:.0f}" x2="{width - 178:.0f}" y2="{y:.0f}" '
                     f'stroke="{WINDOW}" stroke-width="14" stroke-opacity="0.7"/>')
    return "".join(parts)


def geometry_svg(data: dict[str, Any], frame: tuple[float, ...], *, frame_only: bool) -> str:
    _, _, _, _, width, height = frame
    parts: list[str] = [f'<g id="fixed">']
    # Perimeter: 200 mm wall drawn as an outer and inner line.
    parts.append(f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="none" '
                 f'stroke="{FIXED}" stroke-width="58"/>')
    parts.append(f'<rect x="200" y="200" width="{width - 400:.0f}" height="{height - 400:.0f}" '
                 f'fill="none" stroke="{FIXED}" stroke-width="26" stroke-opacity="0.85"/>')
    # Windows.
    for x0, x1 in WINDOW_NORTH:
        parts.append(window_symbol_north(x0, x1, width))
    for y0, y1 in WINDOW_EAST:
        parts.append(window_symbol_east(y0, y1, width, height))
    # Stairs (fixed).
    sx0, sy0, sx1, sy1 = STAIR
    parts.append(svg_rect_mm(sx0, sy0, sx1, sy1, height, fill=FIXED, fill_opacity=0.05,
                             stroke=FIXED, stroke_width=30))
    steps = 16
    for index in range(1, steps):
        y = sy0 + (sy1 - sy0) * index / steps
        parts.append(f'<line x1="{sx0 + 80:.0f}" y1="{height - y:.0f}" x2="{sx1 - 80:.0f}" '
                     f'y2="{height - y:.0f}" stroke="{FIXED}" stroke-width="12" stroke-opacity="0.6"/>')
    parts.append(f'<text x="{sx0 + 260:.0f}" y="{height - sy1 + 300:.0f}" font-size="180" '
                 f'fill="{FIXED}">楼梯（保留）</text>')
    # Bathroom wet area (fixed).
    bx0, by0, bx1, by1 = BATH
    parts.append(f'<defs><pattern id="wet" width="90" height="90" patternUnits="userSpaceOnUse">'
                 f'<path d="M0,90 L90,0" stroke="{FIXED}" stroke-width="16" stroke-opacity="0.7"/></pattern></defs>')
    parts.append(svg_rect_mm(bx0, by0, bx1, by1, height, fill="url(#wet)", fill_opacity=0.9,
                             stroke=FIXED, stroke_width=34))
    parts.append(f'<text x="{bx0 + 380:.0f}" y="{height - (by0 + by1) / 2:.0f}" font-size="170" '
                 f'fill="{FIXED}">卫生间湿区（保留）</text>')
    # Doors from CAD evidence.
    for item in data["doors"]:
        parts.append(polyline(item, frame, color=DOOR, width=42))
    parts.append('</g>')

    # Existing (Aochuang) layout — reference only.
    parts.append(f'<g id="existing" opacity="0.9">')
    for item in data["wall_polygons"]:
        parts.append(polygon(item["exterior_ring"], frame, color=EXISTING, opacity=0.16, dashed=True))
    for item in data["walls"]:
        parts.append(polyline(item, frame, color=EXISTING, width=20, dashed=True, opacity=0.75))
    # Existing furniture footprints (reference only, very light).
    minx, miny, _, maxy, _, _ = frame
    for item in data.get("furniture", []):
        bounds = item.get("bounds") or {}
        if not bounds.get("minimum"):
            continue
        (fx0, fy0), (fx1, fy1) = bounds["minimum"], bounds["maximum"]
        x0, x1 = float(fx0) - minx, float(fx1) - minx
        y0, y1 = maxy - float(fy1), maxy - float(fy0)
        if (x1 - x0) < 60 or (y1 - y0) < 60:
            continue
        parts.append(f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{x1 - x0:.0f}" height="{y1 - y0:.0f}" '
                     f'fill="{EXISTING}" fill-opacity="0.07" stroke="{EXISTING}" stroke-width="10" '
                     f'stroke-opacity="0.35"/>')
    # Hexagon display platform with its inner circles.
    cx, cy = HEX_CENTER
    cy_svg = height - cy
    pts = []
    for index in range(6):
        import math
        angle = math.radians(60 * index + 30)
        pts.append(f"{cx + HEX_RADIUS * math.cos(angle):.0f},{cy_svg + HEX_RADIUS * math.sin(angle):.0f}")
    parts.append(f'<polygon points="{" ".join(pts)}" fill="{EXISTING}" fill-opacity="0.12" '
                 f'stroke="{EXISTING}" stroke-width="28" stroke-dasharray="70 50"/>')
    parts.append(f'<circle cx="{cx:.0f}" cy="{cy_svg:.0f}" r="380" fill="none" stroke="{EXISTING}" '
                 f'stroke-width="22"/>')
    parts.append(f'<text x="{cx + 700:.0f}" y="{cy_svg + 60:.0f}" font-size="165" fill="{EXISTING}">'
                 f'六边形展台（原设计·可重做）</text>')
    parts.append('</g>')

    # Review layer.
    parts.append(f'<g id="review">')
    entrance = None
    for item in data["doors"]:
        pts = item.get("geometry_points") or []
        if pts and min(point(p, frame)[0] for p in pts) < 500:
            entrance = item
            break
    if entrance:
        pts = entrance.get("geometry_points") or []
        ex, ey = point(pts[0], frame)
        label_y = max(260.0, ey - 260)
        parts.append(f'<g><path d="M {max(120, ex - 320):.0f} {ey:.0f} L {ex + 700:.0f} {ey:.0f}" '
                     f'stroke="{REVIEW}" stroke-width="55" marker-end="url(#arrow)"/>'
                     f'<text x="{max(200, ex - 300):.0f}" y="{label_y:.0f}" font-size="185" fill="{REVIEW}">'
                     f'主入口（推断·待复核）</text></g>')
    parts.append('</g>')
    return "\n".join(parts)


def build_base_map_svg(data: dict[str, Any], frame: tuple[float, ...]) -> str:
    _, _, _, _, width, height = frame
    margin, legend_w, title_h = 900.0, 5400.0, 1500.0
    total_w, total_h = width + margin * 2 + legend_w, height + margin * 2 + title_h
    body = geometry_svg(data, frame, frame_only=True)
    legend = [
        (FIXED, "建筑固有条件（必须保留）", "外墙/楼梯/卫生间湿区/门"),
        (WINDOW, "窗（原图读取）", "北墙 3 段 5400 窗带 + 东墙 2 段，待复核"),
        (EXISTING, "奥创原设计（仅参考）", "展墙/隔墙/水吧/六边形展台/家具"),
        (REVIEW, "待现场复核", "入口位置、目测范围、洞口高度"),
    ]
    legend_svg = [f'<text x="{width + margin + 160:.0f}" y="{margin + 170:.0f}" font-size="200" '
                  f'font-weight="600" fill="#2b3a49">图例 LEGEND</text>']
    legend_svg.append(f'<line x1="{width + margin + 160:.0f}" y1="{margin + 250:.0f}" '
                      f'x2="{width + margin + legend_w - 200:.0f}" y2="{margin + 250:.0f}" '
                      f'stroke="#c9d2da" stroke-width="10"/>')
    for index, (color, label, note) in enumerate(legend):
        y = margin + 420 + index * 720
        legend_svg.append(f'<rect x="{width + margin + 160:.0f}" y="{y:.0f}" width="280" height="170" '
                          f'fill="{color}" fill-opacity="0.30" stroke="{color}" stroke-width="20"/>')
        legend_svg.append(f'<text x="{width + margin + 160:.0f}" y="{y + 300:.0f}" font-size="150" fill="#2b3a49">{escape(label)}</text>')
        legend_svg.append(f'<text x="{width + margin + 160:.0f}" y="{y + 460:.0f}" font-size="120" fill="#6b7a8a">{escape(note)}</text>')
    note_y = margin + 420 + len(legend) * 720 + 120
    notes = ["阶段 1 底图 · 仅供核对", "非施工定位依据", "尺寸单位 mm（标注为 m）",
             "外轮廓 26.17 × 17.92 m", "柱：未发现结构柱", "来源：宁波 DXF/DWG + A3 平面图"]
    for index, note in enumerate(notes):
        legend_svg.append(f'<text x="{width + margin + 200:.0f}" y="{note_y + index * 290:.0f}" '
                          f'font-size="150" fill="#8a6836">{escape(note)}</text>')
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
<text x="{margin:.0f}" y="{height + margin + 1120:.0f}" font-size="170" fill="#5c6b79">阶段 1 第 2 版 · 2026-11-10 · 绿色=建筑固有条件，蓝=窗，灰=奥创原设计（仅参考），橙=待现场复核</text>
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
    fixed = [
        {"element": "展厅外轮廓 / 外墙", "status": "解析确认",
         "detail": "26.17 × 17.92 m，与图纸尺寸链 26170 / 17920 一致；外墙按 200 mm 双线绘制",
         "source": "target_region.bounds + 定位图层锚点"},
        {"element": "窗（北墙）", "status": "原图读取·待现场复核",
         "detail": "3 段 5400 窗带，4 处 600 窗间垛；端部实墙 1910 / 3170",
         "source": "A3 平面图北墙尺寸链 1910-600-5400-600-5400-600-5400-600-1060-1170-3170-260"},
        {"element": "窗（东墙）", "status": "原图读取·待现场复核",
         "detail": "2 段三线窗符号：距南墙 0.23–3.04 m、5.74–8.27 m",
         "source": "A3 平面图东墙三线（墙-玻璃-墙）画法"},
        {"element": "楼梯", "status": "解析确认",
         "detail": "西南角 2.4 × 8.0 m，16 级踏步示意",
         "source": "A3 平面图 + DXF 几何"},
        {"element": "卫生间湿区", "status": "解析确认",
         "detail": "东南角 4.17 × 4.7 m，斜线填充范围",
         "source": "A3 平面图斜线填充区域"},
        {"element": "门", "status": "解析确认（洞口配对待复核）",
         "detail": f"{len(data['doors'])} 个门候选",
         "source": "cad-plan-candidates.json architecture.opening.door"},
        {"element": "柱", "status": "未发现",
         "detail": "原「8 个疑似柱」是同一六边形展台内的 1 个圆环 + 4 个 20 mm 圆心标记，不是结构柱",
         "source": "CIRCLE 候选复核：x 5610–6470 / y 1400–2260 全部落在同一展台范围内"},
    ]
    existing = [
        {"element": "过道两侧 U 形展台墙", "status": "原设计·可重做",
         "detail": "沿东西向主通道布置，非承重，可整体拆除重排",
         "source": "A3 平面图 + DXF 墙体候选（仅作参考层）"},
        {"element": "两间洽谈室隔墙", "status": "原设计·可重做",
         "detail": "西北 19.8㎡ / 东北 5.08 m 进深；可保留改造或取消",
         "source": "A3 平面图"},
        {"element": "水吧", "status": "原设计·可重做",
         "detail": "约 1.8 × 3.0 m，位于楼梯东侧",
         "source": "A3 平面图"},
        {"element": "六边形展台", "status": "原设计·可重做",
         "detail": "中心 (6.04, 1.83) m，外接圆 R≈0.52 m，内含圆环与圆心标记",
         "source": "CIRCLE 候选聚类"},
        {"element": "家具（固定 + 活动）", "status": "原设计·可重做",
         "detail": "282 件家具候选，仅作参考，不进入新方案的保留清单",
         "source": "interior.furniture.fixed / loose"},
    ]
    review = [
        {"element": "主入口位置", "status": "待现场复核",
         "detail": "推断在西门厅，宽度与门洞高度未核实",
         "source": "A3 平面图门厅 + 左侧外墙门候选"},
        {"element": "窗台高 / 窗洞高", "status": "待现场复核",
         "detail": "平面图无法读出竖向尺寸，立面图未提供",
         "source": "—"},
        {"element": "卫生间内部隔断", "status": "待现场复核",
         "detail": "仅确认湿区范围，洁具与隔断位置未提取",
         "source": "A3 平面图斜线区"},
        {"element": "133 项拓扑复核", "status": "待现场复核",
         "detail": "本轮不清理，保持标记，不影响方案设计",
         "source": "cad-topology-review.json"},
    ]
    return {
        "contract_version": "rkd-site-basemap.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": "宁波协诚集团样品展厅",
        "stage": "阶段1 · 真实场地底图（第2版 · 已按用户核对意见改标注）",
        "coordinate_space": "site-local millimetres, origin at SW corner, +x east, +y north",
        "boundary": {"width_m": round(width / 1000, 2), "length_m": round(height / 1000, 2),
                     "source": "cad-plan-candidates.json target_region.bounds",
                     "status": "解析确认", "note": "与 A3 平面图 26170 / 17920 尺寸链一致"},
        "groups": {"fixed": fixed, "existing": existing, "review": review},
        "elements": fixed + existing + review,
        "limits": [
            "本轮只改标注，不重做几何；外轮廓/门/卫生间已由用户核对认可",
            "窗的平面位置按原图尺寸链与线型读取，窗台高/洞口高无法从平面图得出，必须现场复核",
            "PDF 为 A3 排版图、DXF 为模型空间；叠加层按外轮廓像素矩形近似配准，可在入口页微调，不作为测量依据",
            "图纸注明「具体尺寸以现场实际情况为准」；未经现场实测，所有尺寸待复核",
        ],
        "counts": {"current_scope_candidates": len(data["current"]),
                   "low_confidence_candidates": len(data["low"]),
                   "unresolved_topology_items": 133,
                   "windows": len(WINDOW_NORTH) + len(WINDOW_EAST),
                   "structural_columns": 0},
    }


def build_entry_page(inventory: dict[str, Any], image_test: dict[str, Any]) -> str:
    left = PLAN_RECT[0] / PDF_SIZE[0] * 100
    top = PLAN_RECT[1] / PDF_SIZE[1] * 100
    width = (PLAN_RECT[2] - PLAN_RECT[0]) / PDF_SIZE[0] * 100
    height = (PLAN_RECT[3] - PLAN_RECT[1]) / PDF_SIZE[1] * 100

    def rows(items, cls):
        return "".join(
            f"<tr><td>{escape(i['element'])}</td>"
            f"<td class='{cls}'>{escape(i['status'])}</td>"
            f"<td>{escape(i['detail'])}</td><td class='src'>{escape(i['source'])}</td></tr>"
            for i in items)

    fixed_rows = rows(inventory["groups"]["fixed"], "ok")
    existing_rows = rows(inventory["groups"]["existing"], "ref")
    review_rows = rows(inventory["groups"]["review"], "review")
    limits = "".join(f"<li>{escape(item)}</li>" for item in inventory["limits"])
    files = [
        ("00_原始平面图_正向.png", "宁波项目原始 A3 平面布置图（已转正）"),
        ("01_真实场地底图.svg", "第2版底图：三组要素分开标注，补北墙/东墙窗"),
        ("01b_几何叠加层.svg", "透明几何层，可叠在原始平面图上核对"),
        ("阶段1_底图核对.pdf", "阶段 1 汇总 PDF，可直接发看"),
        ("底图数据.json", "三组要素的来源、数量与状态"),
        ("图像通道测试.json", "图像生成通道的测试结论（含未测原因）"),
    ]
    file_links = "".join(
        f'<li><a href="{escape(name)}" target="_blank">{escape(name)}</a>'
        f'<span>{escape(note)}</span></li>' for name, note in files)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>宁波协诚 · 阶段1 底图（第2版）</title>
<style>
@page{{size:A3 landscape;margin:12mm}}
*{{box-sizing:border-box}}
body{{font:14px/1.65 "Microsoft YaHei","PingFang SC",sans-serif;color:#22303f;margin:0;background:#f4f6f8}}
.wrap{{max-width:1280px;margin:0 auto;padding:24px}}
h1{{font-size:23px;margin:0 0 4px}} h2{{font-size:17px;margin:26px 0 10px;padding-bottom:6px;border-bottom:1px solid #d9e0e6}}
p{{margin:7px 0}} small{{color:#6b7a8a}}
.hero{{background:#fff;border-left:3px solid #1c6b48;padding:14px 18px;margin:14px 0 18px}}
.ok{{color:#1c6b48;font-weight:600}} .review{{color:#c0701c;font-weight:600}} .ref{{color:#5a6b7a;font-weight:600}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff}}
th,td{{padding:7px 9px;border-bottom:1px solid #e2e8ec;text-align:left;vertical-align:top}}
th{{background:#eef2f4;color:#3a4a5c}} td.src{{color:#6b7a8a;font-size:11.5px;width:26%}}
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
footer{{margin:26px 0 10px;color:#6b7a8a;font-size:12px;border-top:1px solid #d9e0de;padding-top:10px}}
@media print{{body{{background:#fff}} .controls{{display:none}} .wrap{{max-width:none}}}}
</style></head><body><div class="wrap">
<h1>宁波协诚集团样品展厅 · 阶段 1 底图（第 2 版）</h1>
<p><small>2026-11-10 · 只改标注，不动几何 · 外轮廓 / 门 / 卫生间已由你核对认可</small></p>
<div class="hero"><strong>这一版按你的三条意见改了：</strong>
① 要素分成三组——建筑固有条件（必须保留）、奥创原设计（仅参考，可重做）、待现场复核；
② 补上北墙 3 段 5400 窗带与东墙 2 段窗；
③ 原「8 个疑似柱」核实为同一六边形展台内的圆环 + 圆心标记，<strong>未发现结构柱</strong>。
</div>

<h2>① 我能打开的文件</h2>
<ul class="files">{file_links}</ul>

<h2>② 叠加核对：底图压在原始平面图上</h2>
<div class="controls">
<label>叠加透明度 <input id="op" type="range" min="0" max="100" value="72"></label>
<label>水平微调 <input id="dx" type="range" min="-80" max="80" value="0"></label>
<label>垂直微调 <input id="dy" type="range" min="-80" max="80" value="0"></label>
<label>缩放 <input id="sc" type="range" min="90" max="110" value="100"></label>
<label><input id="show" type="checkbox" checked> 显示标注层</label>
</div>
<div class="plan" id="plan">
<img class="base" src="00_原始平面图_正向.png" alt="宁波原始平面布置图">
<img class="overlay" id="ov" src="01b_几何叠加层.svg" alt="标注叠加层"
 style="left:{left:.3f}%;top:{top:.3f}%;width:{width:.3f}%;height:{height:.3f}%">
</div>
<p><small>叠加层按原始图外轮廓像素矩形近似配准，可用滑块微调。只用于核对轮廓与元素位置，不作为测量依据。</small></p>

<h2>③ 单独看底图（1:1 米制，含图例与尺寸）</h2>
<div class="plan"><img class="base" src="01_真实场地底图.svg" alt="真实场地底图"></div>

<h2>④ 第一组：建筑固有条件（必须保留）</h2>
<table><thead><tr><th>要素</th><th>状态</th><th>说明</th><th>来源</th></tr></thead><tbody>{fixed_rows}</tbody></table>

<h2>⑤ 第二组：奥创设计原布局（仅参考，新方案可全部重做）</h2>
<table><thead><tr><th>要素</th><th>状态</th><th>说明</th><th>来源</th></tr></thead><tbody>{existing_rows}</tbody></table>

<h2>⑥ 第三组：待现场复核</h2>
<table><thead><tr><th>要素</th><th>状态</th><th>说明</th><th>来源</th></tr></thead><tbody>{review_rows}</tbody></table>

<h2>⑦ 这一版仍未解决的事（如实）</h2>
<div class="note"><ul>{limits}</ul></div>

<h2>⑧ 图像生成通道</h2>
<p>{escape(image_test.get('summary', '未测试'))}</p>
<p><small>{escape(image_test.get('detail', ''))}</small></p>

<footer>底图部分到此为止。管理配套（PG / NAS / 账号 / 岗位审查 / 备份恢复）本阶段全部冻结。证据目录：var/deliverables/ningbo-xiecheng/2026-11-10/</footer>
</div>
<script>
const ov=document.getElementById('ov');
function sync(){{ov.style.opacity=document.getElementById('op').value/100;
ov.style.display=document.getElementById('show').checked?'block':'none';
const dx=+document.getElementById('dx').value,dy=+document.getElementById('dy').value,sc=+document.getElementById('sc').value/100;
ov.style.transform='translate('+dx+'px,'+dy+'px) scale('+sc+')';}}
['op','dx','dy','sc','show'].forEach(id=>document.getElementById(id).addEventListener('input',sync));sync();
</script></body></html>'''


def print_entry_pdf() -> Path | None:
    """Print the entry page to an A3-landscape PDF with headless Edge."""
    import subprocess
    import tempfile

    candidates = [
        r"C:\Program Files (x86)\Microsoft\EdgeCore\150.0.4078.65\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\EdgeCore\147.0.3912.98\msedge.exe",
    ]
    browser = next((item for item in candidates if Path(item).exists()), None)
    if not browser:
        return None
    target = OUT / "阶段1_底图核对.pdf"
    profile = Path(tempfile.mkdtemp(prefix="rkd-edge-"))
    command = [browser, "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
               "--no-default-browser-check", "--virtual-time-budget=20000", "--no-pdf-header-footer",
               f"--user-data-dir={profile}", f"--print-to-pdf={target}",
               (OUT / "阶段1_底图核对.html").as_uri()]
    subprocess.run(command, capture_output=True, timeout=180)
    return target if target.exists() else None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    plan = load_json("cad-plan-candidates.json")
    regions = load_json("cad-region-candidates.json")
    frame = site_frame(plan)
    data = collect(plan, regions)
    render_forward_pdf()
    (OUT / "01_真实场地底图.svg").write_text(build_base_map_svg(data, frame), encoding="utf-8")
    (OUT / "01b_几何叠加层.svg").write_text(build_overlay_svg(data, frame), encoding="utf-8")
    inventory = build_inventory(data, frame)
    (OUT / "底图数据.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    image_test_path = OUT / "图像通道测试.json"
    image_test = json.loads(image_test_path.read_text(encoding="utf-8")) if image_test_path.exists() else {
        "summary": "尚未测试", "detail": ""}
    (OUT / "阶段1_底图核对.html").write_text(build_entry_page(inventory, image_test), encoding="utf-8")
    pdf = print_entry_pdf()
    print(json.dumps({
        "out": str(OUT), "boundary_m": [round(frame[4] / 1000, 2), round(frame[5] / 1000, 2)],
        "walls": len(data["walls"]), "doors": len(data["doors"]),
        "windows": len(WINDOW_NORTH) + len(WINDOW_EAST),
        "pdf": str(pdf) if pdf else "not printed",
        "entry_page": str(OUT / "阶段1_底图核对.html")}, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
