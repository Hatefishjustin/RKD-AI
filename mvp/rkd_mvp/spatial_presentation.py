"""W2-R4 presentation layer: EXPLICIT, labelled fixture assumptions only.

This module deliberately does NOT design anything. The authoritative model is
still ``spatial.zones[].polygon_mm`` from the main-system candidate revision.
Walls, openings, partitions, material choices, furniture asset references,
cameras and lights are supplied by the caller as an explicit presentation
fixture and are validated here. They are:

* ``site_verified = False`` and ``not_ai_design = True`` — never site facts and
  never counted as "the system designed it";
* never derived automatically from functional-zone boundaries (a zone polygon
  is NOT a wall);
* read by the SAME object ids in the readable plan, the Blender scene spec and
  the rendered scene.

Asset ids must exist in ``assets/CC0-素材清单.json`` (Poly Haven, CC0 1.0).
Missing assets are allowed only as explicitly declared placeholders.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .ai_spatial_outputs import PRESENTATION_VERSION

ROOT = Path(__file__).resolve().parents[2]
ASSET_MANIFEST = ROOT / "assets" / "CC0-素材清单.json"
ASSETS_ROOT = ROOT / "tools" / "assets"

DISCLAIMER = (
    "本表达层是人工编写的受控样板假设：墙厚/高度、门窗洞口、隔断、材质贴图、"
    "家具资产映射、绿植软装、机位与灯光均为人工测试假设，未现场复核，"
    "不是系统模型自动设计结果，不计入 AI 接替设计验收；"
    "照明为示意，不宣称照度合规；平面为内部评审图，不是施工图。"
)


class PresentationError(ValueError):
    pass


def load_asset_inventory() -> dict:
    """The one source of truth for available CC0 assets and their real sizes."""
    if not ASSET_MANIFEST.is_file():
        raise PresentationError(f"找不到资产清单：{ASSET_MANIFEST}")
    raw = ASSET_MANIFEST.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    return {"sha256": hashlib.sha256(raw).hexdigest(),
            "source": data.get("source"),
            "license_note": data.get("license_note"),
            "textures": data.get("textures") or {},
            "models": data.get("models") or {}}


def _finite_number(value: Any, name: str, *, low: float | None = None,
                   high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PresentationError(f"{name} 必须是数值")
    number = float(value)
    if not math.isfinite(number):
        raise PresentationError(f"{name} 必须是有限数值")
    if low is not None and number < low:
        raise PresentationError(f"{name} 小于下限 {low}")
    if high is not None and number > high:
        raise PresentationError(f"{name} 大于上限 {high}")
    return number


def _pair(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise PresentationError(f"{name} 必须是 [x, y]")
    return [_finite_number(value[0], f"{name}[0]", low=-1e6, high=1e6),
            _finite_number(value[1], f"{name}[1]", low=-1e6, high=1e6)]


def _inside(point: list[float], boundary_mm: list[float] | None, name: str) -> None:
    if boundary_mm is None:
        return
    w, h = boundary_mm
    if not (-500 <= point[0] <= w + 500 and -500 <= point[1] <= h + 500):
        raise PresentationError(f"{name} 超出场地边界 {w:.0f}×{h:.0f} mm")


def _segment_length(segment: list) -> float:
    (x1, y1), (x2, y2) = segment[0], segment[1]
    return math.hypot(x2 - x1, y2 - y1)


def _point_on_segment(point: list[float], segment: list) -> bool:
    (x1, y1), (x2, y2) = segment[0], segment[1]
    vx, vy = x2 - x1, y2 - y1
    length2 = vx * vx + vy * vy
    if length2 <= 0:
        return False
    t = ((point[0] - x1) * vx + (point[1] - y1) * vy) / length2
    t = max(0.0, min(1.0, t))
    return math.hypot(point[0] - (x1 + t * vx), point[1] - (y1 + t * vy)) <= 1.0


def normalize_presentation(raw: dict | None,
                           boundary_mm: list[float] | None = None) -> dict | None:
    """Validate and normalise an explicitly declared presentation fixture.

    Idempotent: feeding the returned dict back in produces the same result, so
    the service may validate once at submit and once again in the worker without
    losing or double-applying anything.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PresentationError("presentation 必须是对象")
    inventory = load_asset_inventory()
    slots = set(inventory["textures"])
    models = inventory["models"]
    if raw.get("unit", "mm") != "mm":
        raise PresentationError("presentation.unit 只支持 mm（与精确模型一致）")
    if raw.get("site_verified") is not False:
        raise PresentationError("presentation.site_verified 必须为 false：不得冒充现场实测")
    if raw.get("not_ai_design") is not True:
        raise PresentationError("presentation.not_ai_design 必须为 true：不得冒充 AI 设计")
    if not isinstance(raw.get("declared_by"), str) or not raw["declared_by"].strip():
        raise PresentationError("presentation.declared_by 必须标明人工假设来源")
    if inventory["sha256"] != raw.get("asset_manifest_sha256"):
        raise PresentationError("presentation.asset_manifest_sha256 与本机资产清单不一致")

    ids: set[str] = set()

    def claim(value: Any, name: str) -> str:
        oid = str(value or "")
        if not oid:
            raise PresentationError(f"{name} 缺少 object_id")
        if oid in ids:
            raise PresentationError(f"presentation 内 object_id 重复：{oid}")
        ids.add(oid)
        return oid

    def wall(item: dict, index: int, group: str, *, default_kind: str) -> dict:
        oid = claim(item.get("object_id"), f"{group}[{index}].object_id")
        segment = item.get("segment_mm")
        if not isinstance(segment, list) or len(segment) != 2:
            raise PresentationError(f"{group}[{index}].segment_mm 必须是两个端点")
        seg = [_pair(segment[0], f"{group}[{index}].segment_mm[0]"),
               _pair(segment[1], f"{group}[{index}].segment_mm[1]")]
        length = _segment_length(seg)
        if length < 100:
            raise PresentationError(f"{group}[{index}] 墙段长度小于 100mm")
        thickness = _finite_number(item.get("thickness_mm"), f"{group}[{index}].thickness_mm",
                                   low=60, high=500)
        height = _finite_number(item.get("height_mm"), f"{group}[{index}].height_mm",
                                low=1800, high=6000)
        slot = item.get("material_slot")
        if slot not in slots:
            raise PresentationError(f"{group}[{index}].material_slot 不在 CC0 贴图目录：{slot!r}")
        for end in seg:
            _inside(end, boundary_mm, f"{group}[{index}].segment_mm")
        return {"object_id": oid, "kind": str(item.get("kind") or default_kind),
                "segment_mm": seg, "length_mm": round(length, 2),
                "thickness_mm": thickness, "height_mm": height,
                "material_slot": slot,
                "source": str(item.get("source") or "manual_test_assumption"),
                "assumption": True, "site_verified": False}

    walls = [wall(w, i, "walls", default_kind="perimeter")
             for i, w in enumerate(raw.get("walls") or [])]
    partitions = [wall(p, i, "partitions", default_kind="partition")
                  for i, p in enumerate(raw.get("partitions") or [])]
    wall_by_id = {w["object_id"]: w for w in walls + partitions}

    openings = []
    for index, item in enumerate(raw.get("openings") or []):
        oid = claim(item.get("object_id"), f"openings[{index}].object_id")
        kind = item.get("kind")
        if kind not in {"door", "window"}:
            raise PresentationError(f"openings[{index}].kind 必须是 door 或 window")
        host = wall_by_id.get(str(item.get("wall_object_id") or ""))
        if host is None:
            raise PresentationError(f"openings[{index}].wall_object_id 必须引用已建模墙段")
        center = _pair(item.get("center_mm"), f"openings[{index}].center_mm")
        _inside(center, boundary_mm, f"openings[{index}].center_mm")
        if not _point_on_segment(center, host["segment_mm"]):
            raise PresentationError(f"openings[{index}].center_mm 不在所属墙段上")
        width = _finite_number(item.get("width_mm"), f"openings[{index}].width_mm",
                               low=300, high=host["length_mm"] - 100)
        sill = _finite_number(item.get("sill_mm"), f"openings[{index}].sill_mm",
                              low=0, high=host["height_mm"] - 300)
        height = _finite_number(item.get("height_mm"), f"openings[{index}].height_mm",
                                low=300, high=host["height_mm"] - sill)
        openings.append({"object_id": oid, "kind": kind,
                         "wall_object_id": host["object_id"],
                         "center_mm": center, "width_mm": width,
                         "height_mm": height, "sill_mm": sill,
                         "source": str(item.get("source") or "manual_test_assumption"),
                         "assumption": True, "site_verified": False})

    furniture = []
    for index, item in enumerate(raw.get("furniture") or []):
        oid = claim(item.get("object_id"), f"furniture[{index}].object_id")
        position = _pair(item.get("position_mm"), f"furniture[{index}].position_mm")
        _inside(position, boundary_mm, f"furniture[{index}].position_mm")
        rotation = _finite_number(item.get("rotation_deg", 0),
                                  f"furniture[{index}].rotation_deg", low=-360, high=360)
        anchor = item.get("anchor") or "center_floor"
        if anchor != "center_floor":
            raise PresentationError(f"furniture[{index}].anchor 只支持 center_floor")
        z_offset = _finite_number(item.get("z_offset_m", 0),
                                  f"furniture[{index}].z_offset_m", low=0, high=2.0)
        asset_id = item.get("asset_id")
        dims = None
        if asset_id is not None:
            if asset_id not in models:
                raise PresentationError(f"furniture[{index}].asset_id 不在 CC0 模型目录：{asset_id!r}")
            dims = [float(v) for v in models[asset_id]["dimensions_mm"]]
            given = item.get("asset_dimensions_mm")
            if given is not None:
                if not isinstance(given, list) or len(given) != 3:
                    raise PresentationError(f"furniture[{index}].asset_dimensions_mm 必须是三元组")
                if any(abs(float(a) - b) > 1.0 for a, b in zip(given, dims)):
                    raise PresentationError(
                        f"furniture[{index}].asset_dimensions_mm 与资产清单真实尺寸不符")
        furniture.append({
            "object_id": oid,
            "catalog_id": str(item.get("catalog_id") or ""),
            "asset_id": asset_id,
            "asset_dimensions_mm": [round(v, 3) for v in dims] if dims else None,
            "placeholder": asset_id is None,
            "placeholder_note": (None if asset_id is not None else
                                 "目录没有对应 CC0 家具资产，明确留程序化占位，不冒充真实家具"),
            "position_mm": position, "rotation_deg": rotation,
            "z_offset_m": z_offset,
            "z_offset_note": (f"置于已建模台面/展台之上 {z_offset:.2f}m（人工假设），"
                              "避免与平台实体穿插" if z_offset > 0 else None),
            "anchor": anchor,
            "kind": str(item.get("kind") or "model_furniture"),
            "source": str(item.get("source") or "manual_test_assumption"),
            "assumption": True, "site_verified": False,
        })

    materials = []
    for index, item in enumerate(raw.get("materials") or []):
        slot = item.get("slot")
        if slot not in slots:
            raise PresentationError(f"materials[{index}].slot 不在 CC0 贴图目录：{slot!r}")
        hex_color = str(item.get("hex") or "#cccccc")
        if len(hex_color) != 7 or hex_color[0] != "#":
            raise PresentationError(f"materials[{index}].hex 必须是 #rrggbb")
        materials.append({
            "material_id": str(item.get("material_id") or f"mat-{slot}"),
            "slot": slot, "name": str(item.get("name") or slot),
            "hex": hex_color,
            "tile": _finite_number(item.get("tile", 0.5), f"materials[{index}].tile",
                                   low=0.05, high=5.0),
            "tint": [_finite_number(v, f"materials[{index}].tint[{j}]", low=0.1, high=2.0)
                     for j, v in enumerate(item.get("tint") or [1.0, 1.0, 1.0])],
            "rough": _finite_number(item.get("rough", 0.6), f"materials[{index}].rough",
                                    low=0.05, high=1.0),
            "normal_strength": _finite_number(item.get("normal_strength", 0.3),
                                              f"materials[{index}].normal_strength",
                                              low=0.0, high=1.0),
            "zone_roles": [str(v) for v in item.get("zone_roles") or []],
            "source": str(item.get("source") or "manual_test_assumption"),
            "assumption": True, "site_verified": False,
        })

    cameras = []
    for index, item in enumerate(raw.get("cameras") or []):
        oid = claim(item.get("object_id") or item.get("camera_id"),
                    f"cameras[{index}].object_id")
        position = _pair(item.get("position_mm"), f"cameras[{index}].position_mm")
        target = _pair(item.get("target_mm"), f"cameras[{index}].target_mm")
        _inside(position, boundary_mm, f"cameras[{index}].position_mm")
        _inside(target, boundary_mm, f"cameras[{index}].target_mm")
        cameras.append({
            "object_id": oid, "position_mm": position, "target_mm": target,
            "eye_height_mm": _finite_number(item.get("eye_height_mm", 1500),
                                            f"cameras[{index}].eye_height_mm",
                                            low=1200, high=1800),
            "lens_mm": _finite_number(item.get("lens_mm", 24),
                                      f"cameras[{index}].lens_mm", low=14, high=60),
            "source": str(item.get("source") or "manual_test_assumption"),
            "assumption": True, "site_verified": False,
        })
    if not cameras:
        raise PresentationError("presentation.cameras 至少要有一个人眼机位")

    lighting = raw.get("lighting") or {}
    window_ids = list(lighting.get("window_opening_ids") or [])
    declared_windows = {o["object_id"] for o in openings if o["kind"] == "window"}
    if any(oid not in declared_windows for oid in window_ids):
        raise PresentationError("lighting.window_opening_ids 必须指向已建模的窗洞口："
                                "窗光不得来自不存在的窗")
    fixtures = []
    for index, item in enumerate(lighting.get("fixtures") or []):
        position = _pair(item.get("position_mm"), f"lighting.fixtures[{index}].position_mm")
        _inside(position, boundary_mm, f"lighting.fixtures[{index}].position_mm")
        fixtures.append({"object_id": str(item.get("object_id") or f"L{index + 1}"),
                         "position_mm": position,
                         "type": str(item.get("type") or "downlight"),
                         "kelvin": _finite_number(item.get("kelvin", 3000),
                                                  f"lighting.fixtures[{index}].kelvin",
                                                  low=1800, high=8000),
                         "source": str(item.get("source") or "model_ceiling_fixtures"),
                         "assumption": True})
    coves = []
    for index, item in enumerate(lighting.get("coves") or []):
        polygon = item.get("polygon_mm") or []
        if len(polygon) < 3:
            raise PresentationError(f"lighting.coves[{index}].polygon_mm 至少 3 点")
        coves.append({"object_id": str(item.get("object_id") or f"CV{index + 1}"),
                      "polygon_mm": [_pair(p, f"lighting.coves[{index}].polygon_mm[{j}]")
                                     for j, p in enumerate(polygon)],
                      "kelvin": _finite_number(item.get("kelvin", 3000),
                                               f"lighting.coves[{index}].kelvin",
                                               low=1800, high=8000),
                      "source": str(item.get("source") or "model_ceiling_coves"),
                      "assumption": True})
    sun = lighting.get("sun") or {}
    lighting_out = {
        "window_opening_ids": window_ids,
        "fixtures": fixtures, "coves": coves,
        "sun": {"azimuth_deg": _finite_number(sun.get("azimuth_deg", 200), "sun.azimuth_deg",
                                              low=0, high=360),
                "elevation_deg": _finite_number(sun.get("elevation_deg", 38),
                                                "sun.elevation_deg", low=5, high=85),
                "energy": _finite_number(sun.get("energy", 2.0), "sun.energy",
                                         low=0.0, high=10.0),
                "source": "manual_test_assumption"},
        "note": "假设照明：窗光来自已建模窗洞口，灯具/灯槽来自模型天花意向；"
                "未做照度/配光计算，不宣称合规",
    }

    assumptions = [str(v) for v in raw.get("assumptions") or []]
    missing = [str(v) for v in raw.get("missing") or []]
    counts = {"walls": len(walls), "partitions": len(partitions),
              "openings": len(openings), "furniture": len(furniture),
              "furniture_placeholders": sum(1 for f in furniture if f["placeholder"]),
              "materials": len(materials), "cameras": len(cameras),
              "window_lights": len(window_ids), "fixtures": len(fixtures),
              "coves": len(coves)}
    return {
        "schema_version": PRESENTATION_VERSION,
        "normalized": True,
        "unit": "mm",
        "declared_by": raw["declared_by"],
        "declaration": str(raw.get("declaration") or ""),
        "site_verified": False,
        "not_ai_design": True,
        "not_site_fact": True,
        "asset_manifest_sha256": inventory["sha256"],
        "asset_source": inventory["source"],
        "asset_license": "CC0 1.0 (Poly Haven)",
        "assets_root": "tools/assets",
        "walls": walls, "partitions": partitions, "openings": openings,
        "furniture": furniture, "materials": materials, "cameras": cameras,
        "lighting": lighting_out,
        "zone_material_map": {
            m["material_id"]: m["slot"] for m in materials},
        "assumptions": assumptions, "missing": missing,
        "counts": counts, "disclaimer": DISCLAIMER,
    }
