"""Design option A — concept package (plan + 3D render) from one data model.

方案 A：中央圆角中岛 + 环游叙事
现代轻奢：暖木饰面 + 哑光铜 + 微水泥地面，2700–3000K 重点照明，低饱和米金氛围。

v2 修改（2026-11-10 第九批）：
  · 中岛 7.0 × 4.8 m 不变，改为三级圆角台（R1560 / R1360 / R1180），与吊顶环形灯槽同形呼应
  · 新增弧形品牌墙（R2600 圆弧，正对入口）、2 道斜置展墙翼（±12°），全案 4 处非直角元素
  · 卫生间画洁具（坐便 ×3 / 台盆 ×2 / 淋浴 ×1 / 洗手台 ×1）
  · 每个图元入图例或清单，无说明线条删除；分区名称与面积加大并加白色描边
  · 面积表新增「通道及其他」，各行合计 = 469.0 ㎡

Everything (plan drawing, 3D geometry, zone areas, material schedule) is derived
from the tables below, so the plan and the render cannot drift apart. The drawing
is a concept plan, not a construction drawing.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var" / "deliverables" / "ningbo-xiecheng" / "2026-11-10"

W, H, CEILING = 26170.0, 17920.0, 3000.0
TOTAL_AREA = 469.0

INK = "#25313d"
WALL = "#2f3b46"
THIN = "#7b8895"
WARM = "#a8763f"
ACCENT = "#b07b4a"
GLASS = "#6f9bb0"
GREY = "#5c6a72"

MATERIALS = {
    "floor": {"name": "微水泥地面（暖灰）", "color": "#cfc6b8"},
    "wall": {"name": "米白艺术涂料", "color": "#ece6dc"},
    "oak": {"name": "暖白橡木饰面", "color": "#b98a5e"},
    "walnut": {"name": "深胡桃木饰面", "color": "#6b4a33"},
    "bronze": {"name": "哑光铜 / 米金金属", "color": "#a67c52"},
    "stone": {"name": "米白石材台面", "color": "#ded5c6"},
    "fabric": {"name": "低饱和米金布艺", "color": "#c9b79c"},
    "glass": {"name": "长虹玻璃", "color": "#b9cfd6"},
    "plant": {"name": "绿植", "color": "#5d7a56"},
}

# ---------------------------------------------------------------- zones
# box = (x0, y0, x1, y1) in mm; "ring" means the box is the outer boundary of a
# circulation band whose inner boundary is the island base.
ZONES = [
    {"id": "arrival", "no": "01", "name": "序厅 · 品牌第一眼", "short": "序厅",
     "en": "ARRIVAL", "box": (0, 8600, 5400, 13500), "tint": "#e8e0d2"},
    {"id": "loop", "no": "02", "name": "环游动线 · 2.0 m 净宽", "short": "环游动线",
     "en": "LOOP", "box": (6000, 5200, 19000, 12000), "tint": "#f2ede2", "ring": True},
    {"id": "island", "no": "03", "name": "中央中岛 · 核心展台", "short": "中央中岛",
     "en": "CENTRAL ISLAND", "box": (9000, 6200, 16000, 11000), "tint": "#e6d9c4"},
    {"id": "gallery", "no": "04", "name": "北光廊 · 产品序列", "short": "北光廊",
     "en": "DAYLIGHT GALLERY", "box": (5400, 13300, 21800, 17720), "tint": "#e3e8e6"},
    {"id": "scene", "no": "05", "name": "南场景 · 生活样板", "short": "南场景",
     "en": "LIVING SCENE", "box": (5400, 1800, 20400, 5200), "tint": "#e9e3d6"},
    {"id": "lounge", "no": "06", "name": "东洽谈 · 落座", "short": "东洽谈",
     "en": "EAST LOUNGE", "box": (19400, 7600, 26170, 13300), "tint": "#e5e0d3"},
    {"id": "bar", "no": "07", "name": "西水吧 · 服务", "short": "西水吧",
     "en": "WATER BAR", "box": (2400, 1800, 5400, 6100), "tint": "#e4ded2"},
    {"id": "meeting_nw", "no": "08", "name": "洽谈室 A", "short": "洽谈室 A",
     "en": "MEETING A", "box": (0, 13500, 5400, 17720), "tint": "#e8e4da"},
    {"id": "meeting_ne", "no": "09", "name": "洽谈室 B", "short": "洽谈室 B",
     "en": "MEETING B", "box": (21800, 13300, 26170, 17720), "tint": "#e8e4da"},
    {"id": "service", "no": "10", "name": "卫生间 / 后勤", "short": "卫生间",
     "en": "SERVICE", "box": (22000, 2600, 26170, 7300), "tint": "#dfe3e5"},
]

# One-line descriptor under each zone name on the plan
ZONE_SUB = {
    "arrival": "品牌第一眼 · 接待", "loop": "净宽 2.0 m · 四向进入",
    "island": "7.0 × 4.8 m · 圆角三级", "gallery": "北窗采光 · 展墙翼序列",
    "scene": "客厅 / 餐厅 1:1", "lounge": "落座洽谈 · 靠出口",
    "bar": "茶水 · 资料", "meeting_nw": "8–10 人 · 封闭",
    "meeting_ne": "6–8 人 · 封闭", "service": "洁具 6 件 · 保留",
}

# ---------------------------------------------------------------- island & curves# Footprint stays 7000 x 4800; only the corners are rounded, tier by tier.
ISLAND = {
    "base": {"x0": 9000, "y0": 6200, "x1": 16000, "y1": 11000, "r": 1560, "h": 180, "mat": "oak"},
    "mid": {"x0": 9360, "y0": 6560, "x1": 15640, "y1": 10640, "r": 1360, "h": 420, "mat": "oak"},
    "top": {"x0": 9720, "y0": 6920, "x1": 15280, "y1": 10280, "r": 1180, "h": 720, "mat": "stone"},
}
# Ceiling cove ring: same rounded language as the island, 600 mm outside the base.
COVE = {"x0": 8400, "y0": 5600, "x1": 16600, "y1": 11600, "r": 2400, "band": 200, "z": 2850}

# Curved brand wall: shallow arc hung on the arrival hall's north side, bulging
# 900 mm into the room. Chords at y = 13300 from x 800 to 4600, sagitta 900.
# It must NOT cross the sight line from the entrance to the island.
BRAND_ARC = {"cx": 2700.0, "cy": 17460.0, "r": 4660.0, "a0": 243.3, "a1": 296.7,
             "t": 180.0, "h": 2800.0, "mat": "walnut"}

# ---------------------------------------------------------------- walls
# (x0, y0) → (x1, y1) centreline, thickness t, height h, material
WALLS = [
    {"id": "GL-A1", "name": "洽谈室 A 玻璃隔断", "x0": 100, "y0": 13850, "x1": 4900, "y1": 13850,
     "t": 120, "h": 2800, "mat": "glass"},
    {"id": "GL-A2", "name": "洽谈室 A 玻璃隔断", "x0": 4900, "y0": 13850, "x1": 4900, "y1": 17720,
     "t": 120, "h": 2800, "mat": "glass"},
    {"id": "GL-B1", "name": "洽谈室 B 玻璃隔断", "x0": 21800, "y0": 13300, "x1": 26070, "y1": 13300,
     "t": 120, "h": 2800, "mat": "glass"},
    {"id": "GL-B2", "name": "洽谈室 B 玻璃隔断", "x0": 21800, "y0": 13300, "x1": 21800, "y1": 17720,
     "t": 120, "h": 2800, "mat": "glass"},
    {"id": "PT-01", "name": "水吧服务隔墙", "x0": 2400, "y0": 5950, "x1": 5400, "y1": 5950,
     "t": 120, "h": 2800, "mat": "wall"},
    {"id": "WD-01", "name": "材料样板墙", "x0": 20800, "y0": 2600, "x1": 20800, "y1": 5600,
     "t": 120, "h": 2600, "mat": "walnut"},
]
# BRAND_ARC is the third non-orthogonal element; the two rotated bays are the fourth.

FURNITURE = [
    # arrival
    {"kind": "desk", "name": "接待台", "x": 560, "y": 9800, "w": 700, "d": 1700, "h": 1050, "mat": "oak"},
    {"kind": "chair", "name": "接待椅", "x": 1250, "y": 9800, "w": 520, "d": 520, "h": 780, "mat": "fabric", "rot": 90},
    {"kind": "plant", "name": "绿植", "x": 380, "y": 12700, "w": 600, "d": 600, "h": 1400},
    # north gallery — bays 02 and 04 are set off-axis (±12°) to break the grid
    {"kind": "bay", "name": "展墙翼", "x": 6300, "y": 16350, "w": 450, "d": 2300, "h": 2400, "mat": "oak"},
    {"kind": "bay", "name": "展墙翼", "x": 9500, "y": 16350, "w": 450, "d": 2300, "h": 2400, "mat": "oak", "rot": -12},
    {"kind": "bay", "name": "展墙翼", "x": 12700, "y": 16350, "w": 450, "d": 2300, "h": 2400, "mat": "oak"},
    {"kind": "bay", "name": "展墙翼", "x": 15900, "y": 16350, "w": 450, "d": 2300, "h": 2400, "mat": "oak", "rot": 12},
    {"kind": "bay", "name": "展墙翼", "x": 19500, "y": 16350, "w": 450, "d": 2300, "h": 2400, "mat": "oak"},
    {"kind": "bench", "name": "长凳", "x": 18000, "y": 14500, "w": 2400, "d": 420, "h": 420, "mat": "oak"},
    # south scene: living
    {"kind": "rug", "name": "地毯", "x": 8400, "y": 3000, "w": 3800, "d": 2800, "h": 12, "mat": "fabric"},
    {"kind": "sofa", "name": "三人沙发", "x": 8400, "y": 4050, "w": 2400, "d": 950, "h": 780, "mat": "fabric"},
    {"kind": "coffee", "name": "茶几", "x": 8400, "y": 2800, "w": 1200, "d": 620, "h": 380, "mat": "stone"},
    {"kind": "armchair", "name": "单椅", "x": 6200, "y": 2600, "w": 780, "d": 820, "h": 760, "mat": "fabric", "rot": 25},
    {"kind": "armchair", "name": "单椅", "x": 10600, "y": 2600, "w": 780, "d": 820, "h": 760, "mat": "fabric", "rot": -25},
    {"kind": "plant", "name": "绿植", "x": 6000, "y": 4750, "w": 700, "d": 700, "h": 1500},
    # south scene: dining
    {"kind": "table", "name": "餐桌", "x": 14400, "y": 3300, "w": 1900, "d": 950, "h": 750, "mat": "walnut"},
    {"kind": "chair", "name": "餐椅", "x": 13800, "y": 4150, "w": 470, "d": 500, "h": 820, "mat": "oak", "rot": 180},
    {"kind": "chair", "name": "餐椅", "x": 14400, "y": 4150, "w": 470, "d": 500, "h": 820, "mat": "oak", "rot": 180},
    {"kind": "chair", "name": "餐椅", "x": 15000, "y": 4150, "w": 470, "d": 500, "h": 820, "mat": "oak", "rot": 180},
    {"kind": "chair", "name": "餐椅", "x": 13800, "y": 2450, "w": 470, "d": 500, "h": 820, "mat": "oak"},
    {"kind": "chair", "name": "餐椅", "x": 14400, "y": 2450, "w": 470, "d": 500, "h": 820, "mat": "oak"},
    {"kind": "chair", "name": "餐椅", "x": 15000, "y": 2450, "w": 470, "d": 500, "h": 820, "mat": "oak"},
    {"kind": "plant", "name": "绿植", "x": 19600, "y": 2400, "w": 700, "d": 700, "h": 1500},
    # east lounge
    {"kind": "rug", "name": "地毯", "x": 22000, "y": 10600, "w": 3400, "d": 2600, "h": 12, "mat": "fabric"},
    {"kind": "sofa", "name": "沙发", "x": 22000, "y": 12100, "w": 2200, "d": 900, "h": 780, "mat": "fabric"},
    {"kind": "coffee", "name": "茶几", "x": 22000, "y": 10500, "w": 1100, "d": 600, "h": 380, "mat": "stone"},
    {"kind": "armchair", "name": "单椅", "x": 20200, "y": 9800, "w": 760, "d": 800, "h": 760, "mat": "fabric", "rot": -60},
    {"kind": "armchair", "name": "单椅", "x": 23800, "y": 9800, "w": 760, "d": 800, "h": 760, "mat": "fabric", "rot": 60},
    # water bar
    {"kind": "counter", "name": "水吧台", "x": 3600, "y": 4200, "w": 620, "d": 1800, "h": 950, "mat": "stone"},
    {"kind": "cabinet", "name": "备餐柜", "x": 2720, "y": 4200, "w": 350, "d": 1800, "h": 2100, "mat": "walnut"},
    {"kind": "stool", "name": "吧椅", "x": 4150, "y": 3600, "w": 400, "d": 400, "h": 700, "mat": "bronze"},
    {"kind": "stool", "name": "吧椅", "x": 4150, "y": 4800, "w": 400, "d": 400, "h": 700, "mat": "bronze"},
    # meeting A
    {"kind": "table", "name": "会议桌 A", "x": 2500, "y": 15700, "w": 1900, "d": 900, "h": 750, "mat": "walnut"},
    {"kind": "chair", "name": "座椅", "x": 2050, "y": 16550, "w": 460, "d": 480, "h": 800, "mat": "fabric", "rot": 180},
    {"kind": "chair", "name": "座椅", "x": 2500, "y": 16550, "w": 460, "d": 480, "h": 800, "mat": "fabric", "rot": 180},
    {"kind": "chair", "name": "座椅", "x": 2950, "y": 16550, "w": 460, "d": 480, "h": 800, "mat": "fabric", "rot": 180},
    {"kind": "chair", "name": "座椅", "x": 2050, "y": 14850, "w": 460, "d": 480, "h": 800, "mat": "fabric"},
    {"kind": "chair", "name": "座椅", "x": 2500, "y": 14850, "w": 460, "d": 480, "h": 800, "mat": "fabric"},
    {"kind": "chair", "name": "座椅", "x": 2950, "y": 14850, "w": 460, "d": 480, "h": 800, "mat": "fabric"},
    # meeting B
    {"kind": "round", "name": "圆桌 B", "x": 23900, "y": 15600, "w": 1200, "d": 1200, "h": 750, "mat": "walnut"},
    {"kind": "chair", "name": "座椅", "x": 23900, "y": 16500, "w": 450, "d": 470, "h": 800, "mat": "fabric", "rot": 180},
    {"kind": "chair", "name": "座椅", "x": 23150, "y": 15600, "w": 450, "d": 470, "h": 800, "mat": "fabric", "rot": 90},
    {"kind": "chair", "name": "座椅", "x": 24650, "y": 15600, "w": 450, "d": 470, "h": 800, "mat": "fabric", "rot": -90},
    {"kind": "chair", "name": "座椅", "x": 23900, "y": 14700, "w": 450, "d": 470, "h": 800, "mat": "fabric"},
    {"kind": "plant", "name": "绿植", "x": 25300, "y": 14300, "w": 600, "d": 600, "h": 1400},
]

# Four round pedestals on the island top, centred on the island axis
PEDESTALS = [
    {"x": 10250, "y": 7700, "r": 350, "h": 300, "product": "陶罐 P1"},
    {"x": 14750, "y": 7700, "r": 350, "h": 300, "product": "石材样块 P2"},
    {"x": 10250, "y": 9500, "r": 350, "h": 300, "product": "金属器皿 P3"},
    {"x": 14750, "y": 9500, "r": 350, "h": 300, "product": "织物样册 P4"},
]

# Bathroom sanitary ware (kept zone, new drawings)
FIXTURES = [
    {"kind": "wc", "name": "坐便器", "x": 25560, "y": 3300, "rot": 180, "w": 420, "d": 720},
    {"kind": "wc", "name": "坐便器", "x": 25560, "y": 4300, "rot": 180, "w": 420, "d": 720},
    {"kind": "wc", "name": "坐便器", "x": 25560, "y": 5300, "rot": 180, "w": 420, "d": 720},
    {"kind": "vanity", "name": "洗手台", "x": 23800, "y": 6780, "rot": 0, "w": 2600, "d": 640},
    {"kind": "basin", "name": "台盆", "x": 23200, "y": 6780, "rot": 0, "w": 520, "d": 420},
    {"kind": "basin", "name": "台盆", "x": 24400, "y": 6780, "rot": 0, "w": 520, "d": 420},
    {"kind": "shower", "name": "淋浴间", "x": 22950, "y": 3560, "rot": 0, "w": 1500, "d": 1500},
]

LIGHTS = {
    "cove": COVE,
    "track": [(6800, 14200), (12400, 14200), (18800, 14200)],
    "spots": [(10250, 7700), (14750, 7700), (10250, 9500), (14750, 9500),
              (6300, 16350), (12700, 16350), (19500, 16350)],
    "pendants": [(13800, 3300), (15000, 3300)],
}

SCHEDULE_GROUP = {
    "接待台": "接待台（橡木）", "接待椅": "接待椅（布艺）", "沙发": "沙发 / 单椅（布艺）",
    "三人沙发": "沙发 / 单椅（布艺）", "单椅": "沙发 / 单椅（布艺）",
    "餐桌": "餐桌 / 会议桌（胡桃木）", "会议桌 A": "餐桌 / 会议桌（胡桃木）",
    "圆桌 B": "圆桌（胡桃木）", "餐椅": "餐椅 / 座椅（橡木 · 布艺）", "座椅": "餐椅 / 座椅（橡木 · 布艺）",
    "茶几": "茶几（石材）", "水吧台": "水吧台（石材）", "备餐柜": "备餐柜（胡桃木）",
    "展墙翼": "展墙翼 01–05（橡木）", "长凳": "长凳（橡木）", "吧椅": "吧椅（哑光铜）",
    "地毯": "地毯（布艺，虚线示意）", "绿植": "绿植",
}


# ---------------------------------------------------------------- geometry
def zone_area(box: tuple[float, float, float, float]) -> float:
    return (box[2] - box[0]) * (box[3] - box[1]) / 1_000_000


def zone_area_of(zone: dict[str, Any]) -> float:
    a = zone_area(zone["box"])
    if zone.get("ring"):
        b = ISLAND["base"]
        a -= (b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) / 1_000_000
    return a


def area_rows() -> list[dict[str, Any]]:
    rows = []
    for z in ZONES:
        rows.append({"no": z["no"], "name": z["short"], "area": round(zone_area_of(z), 1),
                     "ring": bool(z.get("ring"))})
    used = round(sum(r["area"] for r in rows), 1)
    rows.append({"no": "—", "name": "通道及其他", "area": round(TOTAL_AREA - used, 1), "ring": False})
    return rows


def schedule() -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for item in FURNITURE:
        key = SCHEDULE_GROUP.get(item["name"], item["name"])
        counts[key] = counts.get(key, 0) + 1
    order = ["接待台（橡木）", "接待椅（布艺）", "沙发 / 单椅（布艺）", "餐桌 / 会议桌（胡桃木）", "圆桌（胡桃木）",
             "餐椅 / 座椅（橡木 · 布艺）", "茶几（石材）", "水吧台（石材）", "备餐柜（胡桃木）",
             "展墙翼 01–05（橡木）", "长凳（橡木）", "吧椅（哑光铜）", "地毯（布艺，虚线示意）", "绿植"]
    return [(k, counts[k]) for k in order if k in counts]


def scene_json() -> dict[str, Any]:
    return {
        "contract_version": "rkd-concept-design.v2",
        "scheme": "A",
        "name": "中央圆角中岛 · 环游叙事",
        "style": "现代轻奢：暖木饰面 + 哑光铜 + 微水泥，2700–3000K 重点照明，低饱和米金",
        "site": {"width": W, "height": H, "ceiling": CEILING,
                 "boundary_source": "阶段1 底图（宁波 DXF + A3 平面图）"},
        "fixed": {
            "stair": (0, 0, 2400, 8000),
            "bath": (22000, 2600, 26170, 7300),
            "entrance": (0, 10300, 1800),
            "windows_north": [(2688, 8154), (8778, 14228), (14867, 20317)],
            "windows_east": [(231, 3037), (5742, 8273)],
            "columns": 0,
        },
        "zones": [dict(z) for z in ZONES],
        "area_table": area_rows(),
        "total_area": TOTAL_AREA,
        "walls": [dict(w) for w in WALLS],
        "island": ISLAND,
        "island_note": "外轮廓 7.0 × 4.8 m 不变，R1560 / R1360 / R1180 三级圆角",
        "cove": COVE,
        "brand_arc": BRAND_ARC,
        "furniture": FURNITURE,
        "pedestals": PEDESTALS,
        "fixtures": FIXTURES,
        "lights": {k: v for k, v in LIGHTS.items() if k != "cove"},
        "materials": MATERIALS,
        "non_orthogonal": [
            "中央中岛：三级圆角台 R1560 / R1360 / R1180",
            "吊顶环形灯槽：R2400 圆角环，与中岛同形呼应",
            "弧形品牌墙：R2600 圆弧，凹面正对入口",
            "展墙翼 02 / 04：±12° 斜置",
        ],
        "narrative": [
            "01 序厅：入口先撞见 R2600 的弧形品牌墙，胡桃木曲线把人的视线往中岛方向带，接待台在左。",
            "02 环游：中岛四周 2.0 m 环形动线，四个方向都能进，不走回头路。",
            "03 中岛：外轮廓 7.0 × 4.8 m 不变，改成 R1560 / R1360 / R1180 三级圆角台，与头顶环形灯槽同形。",
            "04 北光廊：北墙 3 段 5.4 m 窗带，5 道 2.3 m 展墙翼，其中 2 道 ±12° 斜置，让光从缝里洗进来。",
            "05 南场景：客厅 + 餐厅两个 1:1 生活场景，材料与家具可触摸。",
            "06 东洽谈：靠东墙落座区，紧邻卫生间与出口。",
            "07 西水吧：楼梯旁服务点，接待、茶水、资料发放合一。",
        ],
    }


# ---------------------------------------------------------------- svg helpers
def Y(y: float) -> float:
    return H - y


def esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def ptext(x: float, y: float, size: float, body: str, *, fill: str = INK, anchor: str = "start",
          weight: str = "400", rotate: float | None = None, spacing: float | None = None,
          halo: bool = False) -> str:
    """Plan-space text (y measured from the south wall, flipped for screen)."""
    return stext(x, Y(y), size, body, fill=fill, anchor=anchor, weight=weight,
                 rotate=rotate, cx=x, cy=Y(y), spacing=spacing, halo=halo)


def stext(x: float, sy: float, size: float, body: str, *, fill: str = INK, anchor: str = "start",
          weight: str = "400", rotate: float | None = None, cx: float | None = None,
          cy: float | None = None, spacing: float | None = None, halo: bool = False) -> str:
    """Screen-space text (sy already flipped)."""
    transform = ""
    if rotate is not None:
        transform = f' transform="rotate({rotate} {cx if cx is not None else x:.0f} {cy if cy is not None else sy:.0f})"'
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    paint = (f' stroke="#ffffff" stroke-width="{size * 0.30:.0f}" stroke-linejoin="round" '
             f'paint-order="stroke" stroke-opacity="0.92"') if halo else ""
    return (f'<text x="{x:.0f}" y="{sy:.0f}" font-size="{size}" fill="{fill}"{paint} '
            f'text-anchor="{anchor}" font-weight="{weight}"{transform}{ls}>{esc(body)}</text>')


def rrect(x0: float, y0: float, x1: float, y1: float, r: float) -> str:
    """Rounded rectangle path in plan coords (y flipped inside)."""
    t, b = Y(y1), Y(y0)
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    return (f"M {x0 + r:.1f} {t:.1f} L {x1 - r:.1f} {t:.1f} "
            f"A {r:.1f} {r:.1f} 0 0 1 {x1:.1f} {t + r:.1f} "
            f"L {x1:.1f} {b - r:.1f} A {r:.1f} {r:.1f} 0 0 1 {x1 - r:.1f} {b:.1f} "
            f"L {x0 + r:.1f} {b:.1f} A {r:.1f} {r:.1f} 0 0 1 {x0:.1f} {b - r:.1f} "
            f"L {x0:.1f} {t + r:.1f} A {r:.1f} {r:.1f} 0 0 1 {x0 + r:.1f} {t:.1f} Z")


def srect(x0: float, sy0: float, x1: float, sy1: float, **kw: Any) -> str:
    """Screen-space rectangle."""
    fill = kw.get("fill", "none")
    stroke = kw.get("stroke", INK)
    sw = kw.get("sw", 20)
    extra = kw.get("extra", "")
    return (f'<rect x="{x0:.0f}" y="{sy0:.0f}" width="{x1 - x0:.0f}" height="{sy1 - sy0:.0f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" {extra}/>')


def arc_point(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def arc_band(cx: float, cy: float, r: float, a0: float, a1: float, t: float, steps: int = 64) -> str:
    outer = [arc_point(cx, cy, r + t / 2, a0 + (a1 - a0) * i / steps) for i in range(steps + 1)]
    inner = [arc_point(cx, cy, r - t / 2, a1 - (a1 - a0) * i / steps) for i in range(steps + 1)]
    pts = outer + inner
    d = "M " + " L ".join(f"{x:.1f} {Y(y):.1f}" for x, y in pts) + " Z"
    return d


def arrow_path(points: list[tuple[float, float]], *, dash: str = "90 70") -> str:
    d = "M " + " L ".join(f"{x:.0f} {Y(y):.0f}" for x, y in points)
    return (f'<path d="{d}" fill="none" stroke="{ACCENT}" stroke-width="34" '
            f'stroke-dasharray="{dash}" marker-end="url(#flow)" stroke-linecap="round" '
            f'stroke-opacity="0.85"/>')


# ---------------------------------------------------------------- symbols
def furniture_svg(item: dict[str, Any]) -> str:
    kind = item["kind"]
    cx, cy = item["x"], item["y"]
    w, d = item["w"], item["d"]
    rot = item.get("rot", 0)
    color = MATERIALS.get(item.get("mat", "oak"), MATERIALS["oak"])["color"]
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - d / 2, cy + d / 2
    body: list[str] = []
    if kind == "rug":
        body.append(f'<rect x="{x0:.0f}" y="{Y(y1):.0f}" width="{w:.0f}" height="{d:.0f}" fill="{color}" '
                    f'fill-opacity="0.28" stroke="{color}" stroke-width="12" stroke-dasharray="70 60"/>')
    elif kind == "plant":
        body.append(f'<circle cx="{cx:.0f}" cy="{Y(cy):.0f}" r="{w / 2:.0f}" fill="{color}" '
                    f'fill-opacity="0.45" stroke="{color}" stroke-width="16"/>')
        body.append(f'<circle cx="{cx:.0f}" cy="{Y(cy):.0f}" r="{w / 4:.0f}" fill="none" '
                    f'stroke="{color}" stroke-width="12"/>')
    elif kind in {"sofa", "armchair"}:
        body.append(f'<rect x="{x0:.0f}" y="{Y(y1):.0f}" width="{w:.0f}" height="{d:.0f}" rx="60" '
                    f'fill="{color}" fill-opacity="0.30" stroke="{INK}" stroke-width="18"/>')
        body.append(f'<rect x="{x0:.0f}" y="{Y(y1):.0f}" width="{w:.0f}" height="180" '
                    f'fill="{color}" fill-opacity="0.55" stroke="{INK}" stroke-width="14"/>')
    elif kind == "bay":
        body.append(f'<rect x="{x0:.0f}" y="{Y(y1):.0f}" width="{w:.0f}" height="{d:.0f}" '
                    f'fill="{color}" fill-opacity="0.45" stroke="{INK}" stroke-width="18"/>')
        body.append(f'<line x1="{x0:.0f}" y1="{Y(y0 + 140):.0f}" x2="{x1:.0f}" y2="{Y(y0 + 140):.0f}" '
                    f'stroke="{INK}" stroke-width="10" stroke-dasharray="50 40"/>')
    elif kind == "chair":
        body.append(f'<rect x="{x0:.0f}" y="{Y(y1):.0f}" width="{w:.0f}" height="{d:.0f}" rx="70" '
                    f'fill="{color}" fill-opacity="0.35" stroke="{INK}" stroke-width="14"/>')
        body.append(f'<rect x="{x0:.0f}" y="{Y(y1):.0f}" width="{w:.0f}" height="95" rx="40" '
                    f'fill="{INK}" fill-opacity="0.40" stroke="none" stroke-width="0"/>')
    elif kind in {"table", "coffee", "desk", "counter", "cabinet"}:
        body.append(f'<rect x="{x0:.0f}" y="{Y(y1):.0f}" width="{w:.0f}" height="{d:.0f}" '
                    f'fill="{color}" fill-opacity="0.42" stroke="{INK}" stroke-width="20"/>')
        body.append(f'<rect x="{x0 + 60:.0f}" y="{Y(y1 - 60):.0f}" width="{w - 120:.0f}" height="{d - 120:.0f}" '
                    f'fill="none" stroke="{INK}" stroke-width="8" stroke-opacity="0.45"/>')
    elif kind == "round":
        body.append(f'<circle cx="{cx:.0f}" cy="{Y(cy):.0f}" r="{w / 2:.0f}" fill="{color}" '
                    f'fill-opacity="0.42" stroke="{INK}" stroke-width="20"/>')
        body.append(f'<circle cx="{cx:.0f}" cy="{Y(cy):.0f}" r="{w / 2 - 80:.0f}" fill="none" '
                    f'stroke="{INK}" stroke-width="8" stroke-opacity="0.45"/>')
    elif kind == "stool":
        body.append(f'<circle cx="{cx:.0f}" cy="{Y(cy):.0f}" r="{w / 2:.0f}" fill="{color}" '
                    f'fill-opacity="0.5" stroke="{INK}" stroke-width="14"/>')
    elif kind == "bench":
        body.append(f'<rect x="{x0:.0f}" y="{Y(y1):.0f}" width="{w:.0f}" height="{d:.0f}" rx="40" '
                    f'fill="{color}" fill-opacity="0.40" stroke="{INK}" stroke-width="16"/>')
    else:
        body.append(f'<rect x="{x0:.0f}" y="{Y(y1):.0f}" width="{w:.0f}" height="{d:.0f}" '
                    f'fill="{color}" fill-opacity="0.35" stroke="{INK}" stroke-width="16"/>')
    group = "".join(body)
    if rot:
        group = f'<g transform="rotate({rot} {cx:.0f} {Y(cy):.0f})">{group}</g>'
    return group


def fixture_svg(item: dict[str, Any]) -> str:
    kind = item["kind"]
    cx, cy = item["x"], item["y"]
    w, d = item["w"], item["d"]
    rot = item.get("rot", 0)
    body: list[str] = []
    if kind == "wc":
        # tank against the wall + bowl ellipse, facing -x when rot = 180
        body.append(f'<rect x="{cx + d / 2 - 200:.0f}" y="{cy - w / 2:.0f}" width="200" height="{w:.0f}" '
                    f'fill="#ffffff" stroke="{INK}" stroke-width="16"/>')
        body.append(f'<ellipse cx="{cx - 40:.0f}" cy="{Y(cy):.0f}" rx="{d / 2 - 150:.0f}" ry="{w / 2 - 15:.0f}" '
                    f'fill="#ffffff" stroke="{INK}" stroke-width="18"/>')
        body.append(f'<ellipse cx="{cx - 40:.0f}" cy="{Y(cy):.0f}" rx="{d / 2 - 235:.0f}" ry="{w / 2 - 95:.0f}" '
                    f'fill="none" stroke="{INK}" stroke-width="8" stroke-opacity="0.45"/>')
    elif kind == "basin":
        body.append(f'<ellipse cx="{cx:.0f}" cy="{Y(cy):.0f}" rx="{w / 2:.0f}" ry="{d / 2:.0f}" '
                    f'fill="#ffffff" stroke="{INK}" stroke-width="16"/>')
        body.append(f'<circle cx="{cx:.0f}" cy="{Y(cy):.0f}" r="30" fill="none" stroke="{INK}" stroke-width="8"/>')
    elif kind == "vanity":
        body.append(f'<rect x="{cx - w / 2:.0f}" y="{Y(cy + d / 2):.0f}" width="{w:.0f}" height="{d:.0f}" '
                    f'fill="{MATERIALS["stone"]["color"]}" fill-opacity="0.5" stroke="{INK}" stroke-width="18"/>')
    elif kind == "shower":
        x0, y0 = cx - w / 2, cy - d / 2
        body.append(f'<rect x="{x0:.0f}" y="{Y(y0 + d):.0f}" width="{w:.0f}" height="{d:.0f}" '
                    f'fill="#ffffff" fill-opacity="0.6" stroke="{INK}" stroke-width="16"/>')
        body.append(f'<line x1="{x0 + 120:.0f}" y1="{Y(y0 + d - 120):.0f}" x2="{x0 + w - 120:.0f}" '
                    f'y2="{Y(y0 + 120):.0f}" stroke="{INK}" stroke-width="8" stroke-opacity="0.35"/>')
        body.append(f'<circle cx="{x0 + w / 2:.0f}" cy="{Y(y0 + d / 2):.0f}" r="55" fill="none" '
                    f'stroke="{INK}" stroke-width="10"/>')
        # glass screen on the inner face
        body.append(f'<line x1="{x0 + w:.0f}" y1="{Y(y0 + d):.0f}" x2="{x0 + w:.0f}" y2="{Y(y0):.0f}" '
                    f'stroke="{GLASS}" stroke-width="22"/>')
    group = "".join(body)
    if rot:
        group = f'<g transform="rotate({rot} {cx:.0f} {Y(cy):.0f})">{group}</g>'
    return group


# ---------------------------------------------------------------- legend pieces
def sym(kind: str, x: float, sy: float, w: float = 300, h: float = 220) -> str:
    """Mini symbol for the legend, drawn in screen space."""
    out: list[str] = []
    if kind == "wall":
        out.append(srect(x, sy, x + w, sy + h, fill=WALL, stroke=WALL, sw=6))
        out.append(f'<line x1="{x + 10}" y1="{sy + h * 0.22:.0f}" x2="{x + w - 10}" y2="{sy + h * 0.22:.0f}" '
                   f'stroke="#ffffff" stroke-width="8" stroke-opacity="0.85"/>')
        out.append(f'<line x1="{x + 10}" y1="{sy + h * 0.78:.0f}" x2="{x + w - 10}" y2="{sy + h * 0.78:.0f}" '
                   f'stroke="#ffffff" stroke-width="8" stroke-opacity="0.85"/>')
    elif kind == "glass":
        out.append(srect(x, sy, x + w, sy + h, fill=GLASS, stroke="none", sw=0, extra='fill-opacity="0.18"'))
        out.append(f'<line x1="{x}" y1="{sy + 20}" x2="{x + w}" y2="{sy + 20}" stroke="{GLASS}" stroke-width="14"/>')
        out.append(f'<line x1="{x}" y1="{sy + h - 20}" x2="{x + w}" y2="{sy + h - 20}" stroke="{GLASS}" stroke-width="14"/>')
    elif kind == "window":
        out.append(srect(x, sy, x + w, sy + h, fill=GLASS, stroke="none", sw=0, extra='fill-opacity="0.14"'))
        for frac in (0.18, 0.5, 0.82):
            out.append(f'<line x1="{x}" y1="{sy + h * frac:.0f}" x2="{x + w}" y2="{sy + h * frac:.0f}" '
                       f'stroke={chr(34)}{GLASS}{chr(34)} stroke-width="12"/>')
        for frac in (0.34, 0.67):
            out.append(f'<line x1="{x + w * frac:.0f}" y1="{sy}" x2="{x + w * frac:.0f}" y2="{sy + h}" '
                       f'stroke="{GLASS}" stroke-width="10"/>')
    elif kind == "door":
        out.append(f'<path d="M {x} {sy + h} L {x} {sy} A {h} {h} 0 0 1 {x + h} {sy + h}" fill="none" '
                   f'stroke="{ACCENT}" stroke-width="12" stroke-dasharray="40 30"/>')
        out.append(f'<line x1="{x}" y1="{sy + h}" x2="{x + w * 0.9:.0f}" y2="{sy + h}" stroke="{WALL}" stroke-width="12"/>')
    elif kind == "stair":
        out.append(srect(x, sy, x + w, sy + h, fill="#dfe3e5", stroke=WALL, sw=10))
        for i in range(1, 6):
            out.append(f'<line x1="{x}" y1="{sy + h * i / 6:.0f}" x2="{x + w}" y2="{sy + h * i / 6:.0f}" '
                       f'stroke="#8b98a4" stroke-width="8"/>')
    elif kind == "paint":
        out.append(srect(x, sy, x + w, sy + h, fill=WALL, stroke=WALL, sw=6))
    elif kind == "wood":
        out.append(srect(x, sy, x + w, sy + h, fill=MATERIALS["walnut"]["color"], stroke=INK, sw=8))
        for i in range(1, 3):
            out.append(f'<line x1="{x}" y1="{sy + h * i / 3:.0f}" x2="{x + w}" y2="{sy + h * i / 3:.0f}" '
                       f'stroke="#ffffff" stroke-width="6" stroke-opacity="0.28"/>')
    elif kind == "arc":
        out.append(f'<path d="M {x + 10} {sy + h} A {w * 0.8:.0f} {h} 0 0 1 {x + w - 10} {sy + h}" fill="none" '
                   f'stroke="{MATERIALS["walnut"]["color"]}" stroke-width="26"/>')
    elif kind == "island":
        out.append(f'<rect x="{x}" y="{sy + 20}" width="{w}" height="{h - 40}" rx="50" fill="{MATERIALS["oak"]["color"]}" '
                   f'fill-opacity="0.22" stroke="{INK}" stroke-width="10"/>')
        out.append(f'<rect x="{x + 40}" y="{sy + 45}" width="{w - 80}" height="{h - 90}" rx="40" fill="{MATERIALS["oak"]["color"]}" '
                   f'fill-opacity="0.36" stroke="{INK}" stroke-width="8"/>')
        out.append(f'<rect x="{x + 80}" y="{sy + 70}" width="{w - 160}" height="{h - 140}" rx="30" '
                   f'fill="{MATERIALS["stone"]["color"]}" fill-opacity="0.6" stroke="{INK}" stroke-width="8"/>')
    elif kind == "pedestal":
        out.append(f'<circle cx="{x + w / 2:.0f}" cy="{sy + h / 2:.0f}" r="{h / 2 - 6:.0f}" fill="#ffffff" '
                   f'fill-opacity="0.8" stroke="{ACCENT}" stroke-width="14"/>')
        out.append(f'<circle cx="{x + w / 2:.0f}" cy="{sy + h / 2:.0f}" r="{h / 5:.0f}" fill="{MATERIALS["bronze"]["color"]}" '
                   f'stroke="none" stroke-width="0"/>')
    elif kind == "furn":
        out.append(srect(x, sy + 20, x + w, sy + h - 20, fill=MATERIALS["oak"]["color"], stroke=INK, sw=12,
                         extra='fill-opacity="0.35"'))
    elif kind == "rug":
        out.append(f'<rect x="{x}" y="{sy + 40}" width="{w}" height="{h - 80}" fill="{MATERIALS["fabric"]["color"]}" '
                   f'fill-opacity="0.28" stroke="{MATERIALS["fabric"]["color"]}" stroke-width="10" stroke-dasharray="30 24"/>')
    elif kind == "plant":
        out.append(f'<circle cx="{x + w / 2:.0f}" cy="{sy + h / 2:.0f}" r="{h / 2 - 6:.0f}" '
                   f'fill="{MATERIALS["plant"]["color"]}" fill-opacity="0.45" stroke="{MATERIALS["plant"]["color"]}" stroke-width="12"/>')
        out.append(f'<circle cx="{x + w / 2:.0f}" cy="{sy + h / 2:.0f}" r="{h / 5:.0f}" fill="none" '
                   f'stroke="{MATERIALS["plant"]["color"]}" stroke-width="10"/>')
    elif kind == "fixture":
        out.append(f'<rect x="{x + w * 0.62:.0f}" y="{sy + 55}" width="60" height="{h - 110}" '
                   f'fill="#ffffff" stroke="{INK}" stroke-width="10"/>')
        out.append(f'<ellipse cx="{x + w * 0.33:.0f}" cy="{sy + h / 2:.0f}" rx="{w * 0.22:.0f}" ry="{h * 0.28:.0f}" '
                   f'fill="#ffffff" stroke="{INK}" stroke-width="12"/>')
    elif kind == "basin":
        out.append(f'<ellipse cx="{x + w / 2:.0f}" cy="{sy + h / 2:.0f}" rx="{w * 0.30:.0f}" ry="{h * 0.34:.0f}" '
                   f'fill="#ffffff" stroke="{INK}" stroke-width="12"/>')
        out.append(f'<circle cx="{x + w / 2:.0f}" cy="{sy + h / 2:.0f}" r="9" fill="none" stroke="{INK}" stroke-width="8"/>')
    elif kind == "cove":
        out.append(f'<rect x="{x}" y="{sy + 30}" width="{w}" height="{h - 60}" rx="50" fill="none" '
                   f'stroke="{ACCENT}" stroke-width="12" stroke-dasharray="36 28"/>')
    elif kind == "flow":
        out.append(f'<path d="M {x} {sy + h / 2:.0f} L {x + w - 40:.0f} {sy + h / 2:.0f}" fill="none" '
                   f'stroke="{ACCENT}" stroke-width="16" stroke-dasharray="44 30" marker-end="url(#flow)"/>')
    elif kind == "tint":
        out.append(srect(x, sy, x + w, sy + h, fill="#e8e0d2", stroke="none", sw=0, extra='fill-opacity="0.9"'))
    elif kind == "dim":
        out.append(f'<line x1="{x}" y1="{sy + h / 2:.0f}" x2="{x + w}" y2="{sy + h / 2:.0f}" stroke="{THIN}" stroke-width="8"/>')
        out.append(f'<line x1="{x}" y1="{sy + 40}" x2="{x}" y2="{sy + h - 40}" stroke="{THIN}" stroke-width="8"/>')
        out.append(f'<line x1="{x + w}" y1="{sy + 40}" x2="{x + w}" y2="{sy + h - 40}" stroke="{THIN}" stroke-width="8"/>')
    return "".join(out)


# ---------------------------------------------------------------- plan
def build_plan_svg() -> str:
    margin, legend_w, bottom_h = 1100.0, 7000.0, 3800.0
    total_w = W + margin * 2 + legend_w
    total_h = H + margin * 2 + bottom_h
    parts: list[str] = []

    # ---- zone tints (draw before everything structural)
    for zone in ZONES:
        x0, y0, x1, y1 = zone["box"]
        if zone.get("ring"):
            inner = ISLAND["base"]
            d = (rrect(x0, y0, x1, y1, 400) + " " + rrect(inner["x0"], inner["y0"], inner["x1"], inner["y1"], inner["r"]))
            parts.append(f'<path d="{d}" fill="{zone["tint"]}" fill-opacity="0.55" fill-rule="evenodd" stroke="none"/>')
        elif zone["id"] == "island":
            b = ISLAND["base"]
            parts.append(f'<path d="{rrect(b["x0"], b["y0"], b["x1"], b["y1"], b["r"])}" fill="{zone["tint"]}" '
                         f'fill-opacity="0.75" stroke="none"/>')
        else:
            parts.append(f'<rect x="{x0:.0f}" y="{Y(y1):.0f}" width="{x1 - x0:.0f}" height="{y1 - y0:.0f}" '
                         f'fill="{zone["tint"]}" fill-opacity="0.55" stroke="none"/>')

    # ---- ceiling cove (overhead, dashed) — rounded like the island
    cove = COVE
    parts.append(f'<path d="{rrect(cove["x0"], cove["y0"], cove["x1"], cove["y1"], cove["r"])}" fill="none" '
                 f'stroke="{ACCENT}" stroke-width="12" stroke-dasharray="70 55" stroke-opacity="0.75"/>')
    inner_cove = rrect(cove["x0"] + cove["band"], cove["y0"] + cove["band"],
                       cove["x1"] - cove["band"], cove["y1"] - cove["band"], cove["r"] - cove["band"])
    parts.append(f'<path d="{inner_cove}" fill="none" stroke="{ACCENT}" '
                 f'stroke-width="8" stroke-dasharray="40 40" stroke-opacity="0.5"/>')

    # ---- island: three rounded tiers (offset shadow makes each step read as a level)
    tier_fill = {"base": ("#b98a5e", 0.34), "mid": ("#c9a077", 0.62), "top": ("#ded5c6", 0.96)}
    for key in ("base", "mid", "top"):
        t = ISLAND[key]
        color, opacity = tier_fill[key]
        d = rrect(t["x0"], t["y0"], t["x1"], t["y1"], t["r"])
        parts.append(f'<g transform="translate(52 52)"><path d="{d}" fill="#6b6257" fill-opacity="0.16" '
                     f'stroke="none"/></g>')
        parts.append(f'<path d="{d}" fill="{color}" fill-opacity="{opacity}" '
                     f'stroke="{INK}" stroke-width="{34 if key == "top" else 16}"/>')
    # step nosing: one thin line just inside each tier edge
    for key in ("base", "mid"):
        t = ISLAND[key]
        parts.append(f'<path d="{rrect(t["x0"] + 60, t["y0"] + 60, t["x1"] - 60, t["y1"] - 60, max(t["r"] - 60, 60))}" '
                     f'fill="none" stroke="{INK}" stroke-width="7" stroke-opacity="0.28"/>')

    # ---- pedestals + exhibit items
    for idx, pod in enumerate(PEDESTALS, start=1):
        px, py, pr = pod["x"], pod["y"], pod["r"]
        parts.append(f'<circle cx="{px:.0f}" cy="{Y(py):.0f}" r="{pr:.0f}" fill="#ffffff" fill-opacity="0.8" '
                     f'stroke="{ACCENT}" stroke-width="18"/>')
        parts.append(f'<circle cx="{px:.0f}" cy="{Y(py):.0f}" r="{pr - 55:.0f}" fill="none" stroke="{ACCENT}" '
                     f'stroke-width="8" stroke-opacity="0.6"/>')
        parts.append(f'<circle cx="{px:.0f}" cy="{Y(py):.0f}" r="{pr * 0.42:.0f}" fill="{MATERIALS["bronze"]["color"]}" '
                     f'fill-opacity="0.45" stroke="{INK}" stroke-width="8"/>')
        parts.append(ptext(px, py - 150, 165, f"P{idx}", fill="#7a4f2a", anchor="middle", weight="700", halo=True))

    # ---- curved brand wall
    arc = BRAND_ARC
    parts.append(f'<path d="{arc_band(arc["cx"], arc["cy"], arc["r"], arc["a0"], arc["a1"], arc["t"])}" '
                 f'fill="{MATERIALS["walnut"]["color"]}" fill-opacity="0.85" stroke="{INK}" stroke-width="10"/>')

    # ---- walls
    for wall in WALLS:
        x0, y0, x1, y1, t = wall["x0"], wall["y0"], wall["x1"], wall["y1"], wall["t"]
        if wall["mat"] == "glass":
            horizontal = abs(y1 - y0) < 1
            if horizontal:
                parts.append(f'<rect x="{x0:.0f}" y="{Y(y0 + t / 2):.0f}" width="{x1 - x0:.0f}" height="{t:.0f}" '
                             f'fill="{GLASS}" fill-opacity="0.18"/>')
                for edge in (y0 - t / 2, y0 + t / 2):
                    parts.append(f'<line x1="{x0:.0f}" y1="{Y(edge):.0f}" x2="{x1:.0f}" y2="{Y(edge):.0f}" '
                                 f'stroke="{GLASS}" stroke-width="26"/>')
            else:
                parts.append(f'<rect x="{x0 - t / 2:.0f}" y="{Y(max(y0, y1)):.0f}" width="{t:.0f}" '
                             f'height="{abs(y1 - y0):.0f}" fill="{GLASS}" fill-opacity="0.18"/>')
                for edge in (x0 - t / 2, x0 + t / 2):
                    parts.append(f'<line x1="{edge:.0f}" y1="{Y(y0):.0f}" x2="{edge:.0f}" y2="{Y(y1):.0f}" '
                                 f'stroke="{GLASS}" stroke-width="26"/>')
        else:
            fill = MATERIALS.get(wall["mat"], MATERIALS["wall"])["color"]
            horizontal = abs(y1 - y0) < 1
            if horizontal:
                parts.append(f'<rect x="{x0:.0f}" y="{Y(y0 + t / 2):.0f}" width="{x1 - x0:.0f}" height="{t:.0f}" '
                             f'fill="{fill}" stroke="{INK}" stroke-width="10"/>')
            else:
                parts.append(f'<rect x="{x0 - t / 2:.0f}" y="{Y(max(y0, y1)):.0f}" width="{t:.0f}" '
                             f'height="{abs(y1 - y0):.0f}" fill="{fill}" stroke="{INK}" stroke-width="10"/>')

    # ---- perimeter wall: 200 mm poché, white core, thin inner face line
    parts.append(f'<rect x="0" y="0" width="{W:.0f}" height="{H:.0f}" fill="none" stroke="{WALL}" stroke-width="200"/>')
    parts.append(f'<rect x="0" y="0" width="{W:.0f}" height="{H:.0f}" fill="none" stroke="#ffffff" stroke-width="150"/>')
    parts.append(f'<rect x="100" y="{Y(H - 100):.0f}" width="{W - 200:.0f}" height="{H - 200:.0f}" fill="none" '
                 f'stroke="{WALL}" stroke-width="22"/>')

    # ---- stair (kept): inset fill keeps the perimeter poché readable
    parts.append(f'<rect x="100" y="{Y(7900):.0f}" width="2200" height="7800" fill="#dfe3e5" fill-opacity="0.75" stroke="none"/>')
    for index in range(1, 16):
        yy = Y(100 + 7800 * index / 16)
        parts.append(f'<line x1="130" y1="{yy:.0f}" x2="2270" y2="{yy:.0f}" stroke="#8b98a4" stroke-width="12"/>')
    parts.append(f'<line x1="2400" y1="{Y(0):.0f}" x2="2400" y2="{Y(8000):.0f}" stroke="{WALL}" stroke-width="200"/>')
    parts.append(f'<line x1="0" y1="{Y(8000):.0f}" x2="2400" y2="{Y(8000):.0f}" stroke="{WALL}" stroke-width="200"/>')
    parts.append(ptext(1200, 4200, 240, "楼梯（保留）", fill=GREY, anchor="middle", rotate=-90, halo=True))

    # ---- bathroom: partition walls + sanitary ware
    parts.append(f'<rect x="22200" y="{Y(7100):.0f}" width="3770" height="4300" fill="#e7ebec" fill-opacity="0.9" stroke="none"/>')
    parts.append(f'<line x1="22100" y1="{Y(7100):.0f}" x2="22100" y2="{Y(2700):.0f}" stroke="{WALL}" stroke-width="200"/>')
    parts.append(f'<line x1="22000" y1="{Y(2700):.0f}" x2="25970" y2="{Y(2700):.0f}" stroke="{WALL}" stroke-width="200"/>')
    parts.append(f'<line x1="22100" y1="{Y(7200):.0f}" x2="25970" y2="{Y(7200):.0f}" stroke="{WALL}" stroke-width="200"/>')
    # WC cubicle partitions between the three toilets
    for yy in (3800, 4800):
        parts.append(f'<line x1="24650" y1="{Y(yy):.0f}" x2="25970" y2="{Y(yy):.0f}" stroke="{WALL}" stroke-width="50"/>')
    parts.append(f'<line x1="24650" y1="{Y(2800):.0f}" x2="24650" y2="{Y(5700):.0f}" stroke="{WALL}" stroke-width="50"/>')
    for item in FIXTURES:
        parts.append(fixture_svg(item))

    # ---- north / east windows (three-line symbol; drawn last so they sit on the wall face)
    for idx, (x0, x1) in enumerate(((2688, 8154), (8778, 14228), (14867, 20317)), start=1):
        sy_top, sy_bot = Y(H), Y(H - 200)
        parts.append(f'<rect x="{x0}" y="{sy_top:.0f}" width="{x1 - x0:.0f}" height="200" fill="{GLASS}" fill-opacity="0.16"/>')
        for frac in (0.12, 0.5, 0.88):
            yy = sy_top + 200 * frac
            parts.append(f'<line x1="{x0}" y1="{yy:.0f}" x2="{x1}" y2="{yy:.0f}" stroke="{GLASS}" stroke-width="14"/>')
        span = x1 - x0
        n = max(2, int(round(span / 1800)))
        for k in range(1, n):
            mx = x0 + span * k / n
            parts.append(f'<line x1="{mx:.0f}" y1="{sy_top:.0f}" x2="{mx:.0f}" y2="{sy_bot:.0f}" '
                         f'stroke="{GLASS}" stroke-width="10"/>')
        parts.append(ptext((x0 + x1) / 2, H + 300, 165, f"W{idx}", fill="#3f6b7c", anchor="middle",
                           weight="600", halo=True))
    for idx, (y0, y1) in enumerate(((231, 3037), (5742, 8273)), start=4):
        parts.append(f'<rect x="{W - 200:.0f}" y="{Y(y1):.0f}" width="200" height="{y1 - y0:.0f}" '
                     f'fill="{GLASS}" fill-opacity="0.16"/>')
        for frac in (0.12, 0.5, 0.88):
            xx = W - 200 + 200 * frac
            parts.append(f'<line x1="{xx:.0f}" y1="{Y(y0):.0f}" x2="{xx:.0f}" y2="{Y(y1):.0f}" stroke="{GLASS}" stroke-width="14"/>')
        parts.append(ptext(W + 330, (y0 + y1) / 2, 165, f"W{idx}", fill="#3f6b7c", anchor="middle",
                           weight="600", rotate=-90, halo=True))

    # ---- entrance
    parts.append(f'<line x1="0" y1="{Y(12100):.0f}" x2="0" y2="{Y(10300):.0f}" stroke="#ffffff" stroke-width="210"/>')
    parts.append(f'<path d="M 0 {Y(12100):.0f} A 1800 1800 0 0 1 1800 {Y(10300):.0f}" fill="none" '
                 f'stroke="{ACCENT}" stroke-width="14" stroke-dasharray="60 40"/>')
    parts.append(ptext(1900, 10520, 200, "D1 主入口", fill=ACCENT, weight="600", spacing="4", halo=True))

    # ---- furniture
    bay_no = 0
    for item in FURNITURE:
        parts.append(furniture_svg(item))
        if item["kind"] == "bay":
            bay_no += 1
            parts.append(ptext(item["x"], item["y"], 230, f"翼 {bay_no:02d}", fill=INK,
                               anchor="middle", weight="700", rotate=item.get("rot", 0) - 90, halo=True))

    # ---- circulation
    parts.append(arrow_path([(300, 11300), (2400, 11100), (4600, 10300), (7600, 9400)]))
    parts.append(arrow_path([(7600, 12400), (12500, 12400), (17200, 12200)]))
    parts.append(arrow_path([(17600, 11400), (17600, 7800), (17000, 5400)]))
    parts.append(arrow_path([(15800, 5000), (12500, 5000), (8800, 5200)]))
    parts.append(arrow_path([(8000, 6200), (8200, 8600)]))
    parts.append(arrow_path([(12000, 12000), (12000, 14200)]))
    parts.append(arrow_path([(18000, 10400), (19800, 10400)]))
    parts.append(arrow_path([(14400, 5900), (14400, 5000)]))

    # ---- zone labels (large, haloed, placed in clear floor)
    zone_labels = {
        "arrival": (2700, 11620, "middle", 440),
        "gallery": (8300, 14420, "middle", 440),
        "scene": (16200, 4880, "start", 440),
        "lounge": (19600, 13060, "start", 420),
        "bar": (3900, 5840, "middle", 400),
        "meeting_nw": (2700, 14520, "middle", 420),
        "meeting_ne": (23950, 14040, "middle", 400),
        "service": (23400, 5900, "middle", 360),
        "island": (12500, 8960, "middle", 420),
        "loop": (12500, 5740, "middle", 380),
    }
    for zone in ZONES:
        x, y, anchor, size = zone_labels[zone["id"]]
        parts.append(ptext(x, y, size, f'{zone["no"]} · {zone["short"]}', fill="#3f4c55",
                           anchor=anchor, weight="700", spacing="8", halo=True))
        sub_y = y - (size * 1.05)
        body = f'{ZONE_SUB[zone["id"]]} · {zone_area_of(zone):.1f} ㎡'
        parts.append(ptext(x, sub_y, 275, body, fill="#6f7a83", anchor=anchor, spacing="6", halo=True))

    # ---- element labels: every drawn element is either named in place or keyed
    parts.append(ptext(2700, 12930, 205, "弧形品牌墙 R4660", fill=MATERIALS["walnut"]["color"],
                       anchor="middle", weight="600", halo=True))
    parts.append(ptext(16820, 11280, 220, "吊顶环形灯槽（与中岛同形）", fill=ACCENT, anchor="start", halo=True))
    parts.append(ptext(21240, 4150, 200, "材料样板墙", fill=MATERIALS["walnut"]["color"],
                       anchor="start", rotate=-90, weight="600", halo=True))
    parts.append(ptext(21120, 7100, 200, "通道 → 卫生间 / 后勤", fill=GREY, anchor="start",
                       rotate=-90, halo=True))
    parts.append(ptext(1200, 4200, 240, "楼梯（保留）", fill=GREY, anchor="middle", rotate=-90, halo=True))
    parts.append(ptext(25250, 6110, 145, "坐便器 ×3", fill=GREY, anchor="middle", halo=True))
    parts.append(ptext(23400, 6330, 135, "台盆 ×2", fill=GREY, anchor="middle", halo=True))
    parts.append(ptext(22580, 4060, 145, "淋浴间", fill=GREY, anchor="start", halo=True))

    # ---- dimension chains
    dim_y = H + 620
    parts.append(f'<line x1="0" y1="{Y(dim_y):.0f}" x2="{W:.0f}" y2="{Y(dim_y):.0f}" stroke="{THIN}" stroke-width="12"/>')
    for x, label in ((0, "0"), (9000, "9.00"), (16000, "16.00"), (22000, "22.00"), (26170, "26.17")):
        parts.append(f'<line x1="{x}" y1="{Y(dim_y - 140):.0f}" x2="{x}" y2="{Y(dim_y + 140):.0f}" stroke="{THIN}" stroke-width="12"/>')
        parts.append(ptext(x, dim_y - 260, 140, label, fill="#6b7a8a", anchor="middle"))
    dim_x = -620
    parts.append(f'<line x1="{dim_x}" y1="{Y(0):.0f}" x2="{dim_x}" y2="{Y(H):.0f}" stroke="{THIN}" stroke-width="12"/>')
    for y, label in ((0, "0"), (8000, "8.00"), (13850, "13.85"), (17920, "17.92")):
        parts.append(f'<line x1="{dim_x - 140}" y1="{Y(y):.0f}" x2="{dim_x + 140}" y2="{Y(y):.0f}" stroke="{THIN}" stroke-width="12"/>')
        parts.append(ptext(dim_x - 190, y - 90, 140, label, fill="#6b7a8a", anchor="end"))

    # ================================================================ legend column
    lx = W + margin + 240
    col_w = legend_w - 520
    sy = -820.0
    legend: list[str] = [
        stext(lx, sy, 320, "方案 A", fill=INK, weight="700"),
        stext(lx, sy + 460, 230, "中央圆角中岛 · 环游叙事", fill=INK),
        stext(lx, sy + 780, 160, "A · ROUNDED ISLAND / LOOP", fill="#8a8f92", spacing="6"),
    ]
    sy += 980
    legend.append(f'<line x1="{lx}" y1="{sy:.0f}" x2="{lx + col_w:.0f}" y2="{sy:.0f}" stroke="#c9d2da" stroke-width="10"/>')

    sy += 260
    legend.append(stext(lx, sy, 195, "材料 MATERIALS", fill=GREY, weight="600", spacing="6"))
    sy += 110
    for key in ("floor", "wall", "oak", "walnut", "bronze", "stone", "fabric", "glass", "plant"):
        mat = MATERIALS[key]
        legend.append(srect(lx, sy, lx + 300, sy + 210, fill=mat["color"], stroke="#9aa4ac", sw=10))
        legend.append(stext(lx + 380, sy + 155, 195, mat["name"], fill="#3c4a56"))
        sy += 300

    sy += 190
    legend.append(stext(lx, sy, 195, "图例 LEGEND", fill=GREY, weight="600", spacing="6"))
    sy += 100
    legend_items = [
        ("wall", "结构外墙（200 mm 双线）"),
        ("window", "窗洞 W1–W5（北 3 / 东 2）"),
        ("door", "门 / 主入口 D1"),
        ("stair", "楼梯（保留）"),
        ("glass", "玻璃隔断（洽谈室 A / B）"),
        ("paint", "涂料隔墙（水吧服务墙）"),
        ("wood", "木饰面墙 / 材料样板墙"),
        ("arc", "弧形品牌墙 R4660"),
        ("island", "三级圆角展台（中岛）"),
        ("pedestal", "圆台展位 P1–P4 + 展品"),
        ("furn", "家具（15–45% 填充）"),
        ("rug", "地毯（虚线示意）"),
        ("plant", "绿植"),
        ("fixture", "洁具：坐便器（水箱 + 便器）"),
        ("basin", "洁具：台盆 / 洗手台"),
        ("cove", "吊顶环形灯槽（虚线）"),
        ("flow", "环游主动线"),
        ("tint", "分区铺色"),
        ("dim", "尺寸线（mm）"),
    ]
    for kind, label in legend_items:
        legend.append(sym(kind, lx, sy, w=300, h=180))
        legend.append(stext(lx + 380, sy + 130, 195, label, fill="#3c4a56"))
        sy += 292

    sy += 190
    legend.append(stext(lx, sy, 195, "家具与展具清单 SCHEDULE", fill=GREY, weight="600", spacing="6"))
    sy += 90
    for label, count in schedule():
        legend.append(stext(lx, sy + 120, 190, label, fill="#3c4a56"))
        legend.append(stext(lx + col_w, sy + 120, 190, f"× {count}", fill=INK, anchor="end", weight="600"))
        legend.append(f'<line x1="{lx}" y1="{sy + 190:.0f}" x2="{lx + col_w:.0f}" y2="{sy + 190:.0f}" '
                      f'stroke="#e2e7ea" stroke-width="8"/>')
        sy += 255
    legend.append(stext(lx, sy + 120, 190, "洁具（卫生间）", fill="#3c4a56"))
    legend.append(stext(lx + col_w, sy + 120, 190, "坐便 ×3 · 台盆 ×2 · 淋浴 ×1", fill=INK,
                        anchor="end", weight="600"))

    sy += 330
    legend.append(stext(lx, sy, 175, f"建筑面积 {TOTAL_AREA:.1f} ㎡ · 层高 {CEILING/1000:.1f} m", fill="#7b8895"))
    legend.append(stext(lx, sy + 280, 175, "色温 2700–3000K · 重点照明 500 lx", fill="#7b8895"))

    # notes
    sy += 620
    legend.append(stext(lx, sy, 195, "设计说明 NOTES", fill=GREY, weight="600", spacing="6"))
    sy += 120
    notes = [
        "1  本图为概念方案，非施工图；尺寸以现场复核为准。",
        "2  中岛外轮廓 7.0 × 4.8 m，三级台阶 300 / 300 / 420 mm。",
        "3  环形灯槽与中岛同形，R2400，槽宽 200 mm，色温 3000K。",
        "4  弧形品牌墙 R4660，胡桃木饰面，弧长 4.3 m，内凹面向主入口。",
        "5  展墙翼 02 / 04 斜置 ±12°，其余垂直北窗。",
        "6  面积按分区轮廓计，通道及其他含楼梯与疏散。",
    ]
    for note in notes:
        legend.append(stext(lx, sy + 200, 170, note, fill="#6b7a8a"))
        sy += 250

    # north arrow + scale bar
    nx, ny = lx + 320, H - 620
    legend.append(f'<circle cx="{nx:.0f}" cy="{ny:.0f}" r="250" fill="none" stroke="#9aa4ac" stroke-width="10"/>')
    legend.append(f'<path d="M {nx:.0f} {ny - 210:.0f} L {nx - 95:.0f} {ny + 110:.0f} L {nx:.0f} {ny + 30:.0f} '
                  f'L {nx + 95:.0f} {ny + 110:.0f} Z" fill="{INK}"/>')
    legend.append(stext(nx, ny + 430, 180, "N", fill=INK, anchor="middle", weight="700"))
    bx, by = lx + 1000, H - 700
    for index in range(5):
        legend.append(srect(bx + index * 400, by - 45, bx + 400 + index * 400, by + 45,
                            fill=INK if index % 2 == 0 else "#ffffff", stroke=INK, sw=8))
    legend.append(stext(bx, by - 180, 165, "0", fill="#7b8895", anchor="middle"))
    legend.append(stext(bx + 2000, by - 180, 165, "5 m", fill="#7b8895", anchor="middle"))

    # ================================================================ bottom strip
    top = H + margin + 180
    parts.append(f'<line x1="{-margin + 120:.0f}" y1="{top - 90:.0f}" x2="{total_w - margin - 120:.0f}" '
                 f'y2="{top - 90:.0f}" stroke="#c9d2da" stroke-width="10"/>')
    # title block
    parts.append(stext(-margin + 240, top + 320, 340, "宁波协诚集团样品展厅 · 方案 A 平面布置图", fill=INK, weight="700"))
    parts.append(stext(-margin + 240, top + 660, 185,
                       "CONCEPT FLOOR PLAN · SCALE 1:100 · 概念方案（非施工图）", fill="#6b7a8a", spacing="6"))
    parts.append(stext(-margin + 240, top + 960, 175,
                       f"建筑面积 {TOTAL_AREA:.1f} ㎡ · 层高 {CEILING/1000:.1f} m · 图纸 A-02 · 2026-11-10", fill="#6b7a8a"))
    parts.append(stext(-margin + 240, top + 1230, 170,
                       "本图与效果图由同一份设计数据（方案A_设计数据.json）生成；尺寸以现场复核为准",
                       fill="#8a8f92"))
    parts.append(stext(-margin + 240, top + 1500, 170,
                       "圆角中岛 R1560 / R1360 / R1180 · 弧形品牌墙 R4660 · 展墙翼 02 / 04 斜置 ±12°",
                       fill="#8a8f92"))

    # area table
    tx = 15200.0
    rows = area_rows()
    col_w2 = 5500.0
    row_h = 380.0
    parts.append(stext(tx, top + 170, 195, "面积表 AREA SCHEDULE（㎡）", fill=GREY, weight="600", spacing="6"))
    left = rows[:6]
    right = rows[6:]
    for col, chunk in ((0, left), (1, right)):
        cx0 = tx + col * (col_w2 + 300)
        sy_h = top + 290
        parts.append(f'<rect x="{cx0:.0f}" y="{sy_h:.0f}" width="{col_w2:.0f}" height="{row_h:.0f}" '
                     f'fill="#eef1f3" stroke="#c9d2da" stroke-width="8"/>')
        parts.append(stext(cx0 + 70, sy_h + 258, 170, "编号", fill=GREY))
        parts.append(stext(cx0 + 760, sy_h + 258, 170, "分区", fill=GREY))
        parts.append(stext(cx0 + col_w2 - 80, sy_h + 258, 170, "面积", fill=GREY, anchor="end"))
        for i, row in enumerate(chunk):
            yy = sy_h + row_h * (i + 1)
            total_row = row["name"] == "通道及其他"
            fill = "#f7f4ec" if total_row else "#ffffff"
            parts.append(f'<rect x="{cx0:.0f}" y="{yy:.0f}" width="{col_w2:.0f}" height="{row_h:.0f}" '
                         f'fill="{fill}" stroke="#dde3e7" stroke-width="8"/>')
            parts.append(stext(cx0 + 70, yy + 258, 175, str(row["no"]), fill="#8a8f92"))
            parts.append(stext(cx0 + 760, yy + 258, 185, row["name"], fill=INK,
                               weight="600" if total_row else "400"))
            parts.append(stext(cx0 + col_w2 - 80, yy + 258, 185, f'{row["area"]:.1f}',
                               fill=INK if total_row else "#3c4a56", anchor="end",
                               weight="600" if total_row else "400"))
    # grand total under the table
    gt_y = top + 290 + row_h * 7 + 130
    parts.append(f'<line x1="{tx:.0f}" y1="{gt_y - 60:.0f}" x2="{tx + col_w2 * 2 + 300:.0f}" y2="{gt_y - 60:.0f}" '
                 f'stroke="#c9d2da" stroke-width="10"/>')
    parts.append(stext(tx, gt_y + 280, 210, "合计", fill=INK, weight="700"))
    parts.append(stext(tx + col_w2 * 2 + 300, gt_y + 280, 210, f"{TOTAL_AREA:.1f} ㎡", fill=INK,
                       anchor="end", weight="700"))
    parts.append(stext(tx, gt_y + 540, 165,
                       "「通道及其他」含楼梯 19.2 ㎡、环廊、疏散通道与结构边带；不含墙体厚度",
                       fill="#8a8f92"))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-margin:.0f} {-margin:.0f} {total_w:.0f} {total_h:.0f}" role="img" aria-label="方案A平面布置图" font-family="'Noto Sans SC','Source Han Sans SC','Microsoft YaHei',sans-serif">
<defs>
<marker id="flow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
<path d="M0,0 L10,5 L0,10 z" fill="{ACCENT}"/></marker>
</defs>
<rect x="{-margin:.0f}" y="{-margin:.0f}" width="{total_w:.0f}" height="{total_h:.0f}" fill="#ffffff"/>
<rect x="{-margin + 60:.0f}" y="{-margin + 60:.0f}" width="{total_w - 120:.0f}" height="{total_h - 120:.0f}"
 fill="none" stroke="#cfd7dd" stroke-width="10"/>
{''.join(parts)}
{''.join(legend)}
</svg>'''


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scene = scene_json()
    (OUT / "方案A_设计数据.json").write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
    svg = build_plan_svg()
    (OUT / "02_方案A_平面布置图.svg").write_text(svg, encoding="utf-8")
    print(json.dumps({
        "plan": str(OUT / "02_方案A_平面布置图.svg"),
        "data": str(OUT / "方案A_设计数据.json"),
        "zones": len(ZONES), "furniture": len(FURNITURE), "fixtures": len(FIXTURES),
        "area_rows": area_rows(),
        "area_sum": round(sum(r["area"] for r in area_rows()), 1),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
