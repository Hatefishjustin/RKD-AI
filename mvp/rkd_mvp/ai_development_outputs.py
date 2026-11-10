"""Same-source AI development, quantity, cost and artifact generation.

This module reads one adopted rkd-ai-design-option.v1 revision and derives
material surfaces, display/furniture and partition intents, a model-driven
glTF/isometric preview, deterministic quantities, and a local cost draft. It
never writes the legacy design, production, procurement, or release tables.
"""
from __future__ import annotations

import base64
import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
import hashlib
import io
import json
import struct
from typing import Any
import zipfile

from .ai_design_geometry import render_svg
from .spatial_outputs import FORMULA_VERSION, quote_result

PACKAGE_VERSION = "rkd-ai-development-package.v1"
OUTPUT_VERSION = "ai-development-outputs.v1"
MEASUREMENT_VERSION = "ai-development-measurement.v1"
GENERATOR_VERSION = "ai-development-generator.v1"

VISUAL_HEIGHTS = {
    "functional_zone": "0.05",
    "display_object": "0.80",
    "partition": "2.20",
    "entrance_marker": "0.05",
    "obstacle": "2.80",
}
MATERIAL_COLORS = {
    "mat-warm": [0.72, 0.53, 0.33, 1.0],
    "mat-cool": [0.55, 0.61, 0.68, 1.0],
    "mat-neutral": [0.70, 0.72, 0.75, 1.0],
}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def normalize_settings(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("量价参数格式无效")
    unit_raw = raw.get("unit_cost_net")
    if unit_raw is None or str(unit_raw).strip() == "":
        unit_cost = None
    else:
        try:
            value = Decimal(str(unit_raw))
        except (ValueError, InvalidOperation, TypeError):
            raise ValueError("未税单位成本不是有效数字") from None
        if not value.is_finite() or value < 0 or value > Decimal("1000000000") or value != value.quantize(Decimal("0.000001")):
            raise ValueError("未税单位成本超出有效范围")
        unit_cost = format(value.normalize(), "f")
    markup_raw = raw.get("cost_markup", "0.20")
    tax_raw = raw.get("trial_tax_rate", "0.05")
    try:
        markup, tax = Decimal(str(markup_raw)), Decimal(str(tax_raw))
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError("加成率或试用税率不是有效数字") from None
    if not markup.is_finite() or not tax.is_finite() or markup < 0 or markup > 10 or tax < 0 or tax >= 1:
        raise ValueError("加成率或试用税率超出有效范围")
    label = str(raw.get("source_label") or "").strip()
    if len(label) > 500:
        raise ValueError("成本来源说明最多 500 字")
    if not label:
        label = "unknown"
    if unit_cost is not None and label == "unknown":
        label = "人工输入（未专业核验）"
    return {"unit_cost_net": unit_cost, "cost_markup": format(markup.normalize(), "f"),
            "trial_tax_rate": format(tax.normalize(), "f"), "source_label": label,
            "tax_status": "local_trial_only", "formal_tax_review": "unknown"}


def _shape_area(shape: dict[str, Any]) -> Decimal:
    value = Decimal(str(shape["width"])) * Decimal(str(shape["length"]))
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _shape_length(shape: dict[str, Any]) -> Decimal:
    value = max(Decimal(str(shape["width"])), Decimal(str(shape["length"])))
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _deepened_objects(model: dict[str, Any]) -> list[dict[str, Any]]:
    kind_map = {
        "functional_zone": "floor_surface",
        "display_object": "furniture_intent",
        "partition": "partition_intent",
        "entrance_marker": "entrance_zone",
        "obstacle": "site_interface",
    }
    result = []
    for obj in model.get("objects", []):
        shape = obj.get("shape", {})
        kind = obj.get("kind")
        semantic_kind = kind_map.get(kind, "unsupported_object")
        result.append({
            "object_id": f"dev:{obj['object_id']}",
            "source_object_id": obj["object_id"],
            "kind": semantic_kind,
            "name": obj.get("name", obj["object_id"]),
            "shape": dict(shape),
            "material_id": obj.get("material_id"),
            "status": "intent_only" if kind in {"functional_zone", "display_object", "partition", "entrance_marker"} else "site_evidence_unknown",
            "product_status": "unknown",
            "specification_status": "unknown",
            "visual_height_m": VISUAL_HEIGHTS.get(kind, "0.05"),
            "height_status": "visual_only_not_site_verified",
            "source_refs": list(obj.get("source_refs", [])),
            "parent_object_id": obj.get("parent_object_id"),
            "locked": bool(obj.get("locked")),
        })
    # Material surfaces are explicit derived objects, not new geometric facts.
    for obj in model.get("objects", []):
        if obj.get("kind") != "functional_zone":
            continue
        shape = obj["shape"]
        result.append({
            "object_id": f"surface:{obj['object_id']}",
            "source_object_id": obj["object_id"],
            "kind": "material_surface",
            "name": f"{obj.get('name', obj['object_id'])}地坪材料分区",
            "shape": dict(shape),
            "material_id": obj.get("material_id"),
            "status": "intent_only",
            "product_status": "unknown",
            "specification_status": "unknown",
            "visual_height_m": "0.01",
            "height_status": "visual_only_not_site_verified",
            "source_refs": list(obj.get("source_refs", [])),
            "parent_object_id": obj["object_id"],
            "locked": bool(obj.get("locked")),
        })
    return result


def _quantity_items(objects: list[dict[str, Any]], production_revision_id: str,
                    option_revision_id: str) -> tuple[list[dict[str, Any]], Decimal]:
    items: list[dict[str, Any]] = []
    floor_total = Decimal("0")
    for obj in objects:
        source = obj["source_object_id"]
        shape = obj["shape"]
        if obj["kind"] == "floor_surface":
            quantity = _shape_area(shape)
            floor_total += quantity
            items.append({
                "quantity_item_id": f"q-{production_revision_id}-floor-{source}",
                "object_id": obj["object_id"], "source_object_id": source,
                "description": f"{obj['name']}净地坪面积", "quantity": _decimal_text(quantity), "unit": "m²",
                "formula": f"{shape['width']} × {shape['length']}（逐项四位小数）",
                "source_kind": "program_calculation", "quantity_status": "calculated",
                "cost_scope": "floor_net_area", "rule_version": MEASUREMENT_VERSION,
                "option_revision_id": option_revision_id,
            })
        elif obj["kind"] == "furniture_intent":
            items.append({
                "quantity_item_id": f"q-{production_revision_id}-display-{source}",
                "object_id": obj["object_id"], "source_object_id": source,
                "description": f"{obj['name']}对象计数", "quantity": "1", "unit": "项",
                "formula": "按模型中稳定对象 ID 计数", "source_kind": "program_calculation",
                "quantity_status": "counted", "cost_scope": "not_priced",
                "rule_version": MEASUREMENT_VERSION, "option_revision_id": option_revision_id,
            })
        elif obj["kind"] == "partition_intent":
            items.append({
                "quantity_item_id": f"q-{production_revision_id}-partition-{source}",
                "object_id": obj["object_id"], "source_object_id": source,
                "description": f"{obj['name']}二维长度（仅几何检查）",
                "quantity": _decimal_text(_shape_length(shape)), "unit": "m",
                "formula": "二维形状较长边；高度、厚度、做法未知",
                "source_kind": "program_calculation", "quantity_status": "visual_only",
                "cost_scope": "not_priced", "rule_version": MEASUREMENT_VERSION,
                "option_revision_id": option_revision_id,
            })
    return items, floor_total


def _unknown_items(model: dict[str, Any]) -> list[dict[str, Any]]:
    statements = [
        ("circulation-area", "通路地坪面积与铺装做法", "通路已在模型中表达，但本切片只对功能分区净地坪计价"),
        ("material-product", "材料规格、样板、供应商和单价", "材料仍为设计意向，未选产品，不能编造价格"),
        ("wastage", "损耗、排版、包装、起订量和库存", "采购换算规则与实际供应条件未知"),
        ("partition-spec", "隔断高度、厚度、构造和防火性能", "当前只表达二维位置和视觉高度"),
        ("display-product", "展陈/家具产品型号、做法和安装", "当前对象为展陈意向，不是已批准产品"),
        ("ceiling-lighting", "天花、灯具、机电接口", "本切片未建模，宁波项目排除机电/消防施工范围不等于接口不存在"),
        ("formal-tax", "正式税务、合同条件和发布批准", "5% 为本地试用参数，正式适用性和责任未核验"),
    ]
    return [{"item_id": item_id, "statement": statement, "reason": reason,
             "value": None, "unit": "unknown", "known_status": "unknown",
             "source_refs": [], "model_schema_version": model.get("schema_version")}
            for item_id, statement, reason in statements]


def _gltf(objects: list[dict[str, Any]], materials: list[dict[str, Any]]) -> tuple[bytes, list[dict[str, Any]]]:
    positions = [
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
    ]
    indices = [
        0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6,
        0, 4, 5, 0, 5, 1, 1, 5, 6, 1, 6, 2,
        2, 6, 7, 2, 7, 3, 3, 7, 4, 3, 4, 0,
    ]
    position_bytes = b"".join(struct.pack("<fff", *point) for point in positions)
    index_bytes = b"".join(struct.pack("<H", index) for index in indices)
    buffer_bytes = position_bytes + index_bytes
    material_index = {}
    gltf_materials = []
    for material in materials:
        material_id = str(material.get("material_id"))
        if material_id not in material_index:
            material_index[material_id] = len(gltf_materials)
            gltf_materials.append({
                "name": material_id,
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": MATERIAL_COLORS.get(material_id, MATERIAL_COLORS["mat-neutral"]),
                    "metallicFactor": 0.0, "roughnessFactor": 0.85,
                },
            })
    if "mat-neutral" not in material_index:
        material_index["mat-neutral"] = len(gltf_materials)
        gltf_materials.append({"name": "mat-neutral", "doubleSided": True,
                               "pbrMetallicRoughness": {"baseColorFactor": MATERIAL_COLORS["mat-neutral"],
                                                        "metallicFactor": 0.0, "roughnessFactor": 0.85}})
    meshes, nodes, node_map = [], [], []
    for obj in objects:
        shape = obj.get("shape", {})
        try:
            x, y = float(shape["x"]), float(shape["y"])
            width, length = float(shape["width"]), float(shape["length"])
            height = float(obj.get("visual_height_m", "0.05"))
        except (KeyError, TypeError, ValueError):
            continue
        material_id = str(obj.get("material_id") or "mat-neutral")
        if material_id not in material_index:
            material_id = "mat-neutral"
        mesh_index = len(meshes)
        meshes.append({"name": obj["object_id"],
                       "primitives": [{"attributes": {"POSITION": 0}, "indices": 1,
                                       "material": material_index[material_id]}]})
        node_index = len(nodes)
        nodes.append({"name": obj["name"], "mesh": mesh_index,
                      "translation": [x, y, 0.0], "scale": [width, length, height],
                      "extras": {"object_id": obj["object_id"],
                                 "source_object_id": obj["source_object_id"],
                                 "kind": obj["kind"], "material_id": material_id,
                                 "height_status": obj["height_status"]}})
        node_map.append({"node": node_index, "object_id": obj["object_id"],
                         "source_object_id": obj["source_object_id"], "kind": obj["kind"]})
    data_uri = "data:application/octet-stream;base64," + base64.b64encode(buffer_bytes).decode("ascii")
    gltf = {
        "asset": {"version": "2.0", "generator": GENERATOR_VERSION,
                  "extras": {"purpose": "model_driven_display_only", "professional_bim": False}},
        "scene": 0, "scenes": [{"name": "AI development draft", "nodes": list(range(len(nodes)))}],
        "nodes": nodes, "meshes": meshes, "materials": gltf_materials,
        "buffers": [{"byteLength": len(buffer_bytes), "uri": data_uri}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(position_bytes), "byteLength": len(index_bytes), "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3",
             "min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 1.0]},
            {"bufferView": 1, "componentType": 5123, "count": len(indices), "type": "SCALAR",
             "min": [0], "max": [7]},
        ],
        "extras": {"node_object_map": node_map, "height_status": "visual_only_not_site_verified"},
    }
    return _json_bytes(gltf), node_map


def _isometric_svg(boundary: dict[str, Any], objects: list[dict[str, Any]]) -> bytes:
    width = float(boundary["width"])
    length = float(boundary["length"])

    def project(x: float, y: float, z: float = 0.0) -> tuple[float, float]:
        return 260 + (x - y) * 24, 40 + (x + y) * 12 - z * 18

    def polygon(points: list[tuple[float, float]], fill: str, stroke: str = "#4d5d6c") -> str:
        coords = " ".join(f"{px:.2f},{py:.2f}" for px, py in points)
        return f'<polygon points="{coords}" fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>'

    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 620 360" role="img" aria-label="模型驱动等轴测预览">',
             '<rect width="620" height="360" fill="#ffffff"/>',
             '<text x="20" y="24" font-size="13" fill="#526173">模型驱动三维表达 · 显示高度仅为视觉假设</text>']
    floor = [project(0, 0), project(width, 0), project(width, length), project(0, length)]
    parts.append(polygon(floor, "#f3f6f8", "#354557"))
    for obj in objects:
        shape = obj.get("shape", {})
        try:
            x, y = float(shape["x"]), float(shape["y"])
            w, l = float(shape["width"]), float(shape["length"])
            h = float(obj.get("visual_height_m", "0.05"))
        except (KeyError, TypeError, ValueError):
            continue
        color = {"mat-warm": "#e7d5bd", "mat-cool": "#dce4ed", "mat-neutral": "#e4e8eb"}.get(str(obj.get("material_id")), "#e4e8eb")
        top = [project(x, y, h), project(x + w, y, h), project(x + w, y + l, h), project(x, y + l, h)]
        side_a = [project(x, y), project(x + w, y), project(x + w, y, h), project(x, y, h)]
        side_b = [project(x + w, y), project(x + w, y + l), project(x + w, y + l, h), project(x + w, y, h)]
        parts.append(polygon(side_a, "#c8d0d8", "#6b7987"))
        parts.append(polygon(side_b, "#b9c3cd", "#6b7987"))
        parts.append(polygon(top, color))
        cx, cy = project(x + w / 2, y + l / 2, h + 0.05)
        parts.append(f'<text x="{cx:.2f}" y="{cy:.2f}" text-anchor="middle" font-size="8" fill="#263342">{escape(obj["name"][:10])}</text>')
    parts.append('<text x="20" y="342" font-size="10" fill="#8a6836">非正式施工图；glTF 节点与语义对象 ID 映射见模型文件</text>')
    parts.append('</svg>')
    return "\n".join(parts).encode("utf-8")


def build_development_package(*, production_revision_id: str, job_id: str,
                              option_revision: dict[str, Any], adoption: dict[str, Any],
                              settings: dict[str, Any], input_hash: str,
                              created_at: str) -> tuple[dict[str, Any], bytes, bytes, bytes, list[dict[str, Any]]]:
    model = option_revision["model"]
    objects = _deepened_objects(model)
    quantity_items, floor_total = _quantity_items(objects, production_revision_id, option_revision["option_revision_id"])
    unknown_items = _unknown_items(model)
    materials = [dict(item) for item in model.get("materials", [])]
    quote = quote_result(floor_total, settings)
    gltf_bytes, node_map = _gltf(objects, materials)
    iso_bytes = _isometric_svg(model["boundary"], objects)
    plan_bytes = render_svg(model)
    package = {
        "schema_version": PACKAGE_VERSION,
        "production_revision_id": production_revision_id,
        "job_id": job_id,
        "option_revision_id": option_revision["option_revision_id"],
        "set_id": option_revision["set_id"],
        "option_id": option_revision["option_id"],
        "adoption_version": int(adoption["expected_revision"]),
        "input_hash": input_hash,
        "created_at": created_at,
        "baseline": {
            "option_schema_version": model.get("schema_version"),
            "strategy_id": option_revision["strategy_id"],
            "option_revision_no": option_revision["revision_no"],
            "model_input_hash": model.get("generation", {}).get("input_hash"),
            "validation_status": option_revision["validation"]["status"],
            "boundary_source": model.get("boundary", {}).get("boundary_source"),
            "formal_approval": False,
        },
        "boundary": model["boundary"],
        "objects": objects,
        "materials": materials,
        "views": {
            "plan_svg": "development-plan.svg",
            "isometric_svg": "development-isometric.svg",
            "model_gltf": "development-model.gltf",
            "node_object_map": node_map,
            "height_status": "visual_only_not_site_verified",
            "professional_bim": False,
        },
        "quantity_items": quantity_items,
        "cost": {
            "currency": "CNY",
            "scope_label": "功能分区净地坪；不含通路、展示/隔断产品、损耗、采购换算和正式税务",
            "pricing": settings,
            "quote": quote,
            "formula_version": FORMULA_VERSION,
            "measurement_version": MEASUREMENT_VERSION,
            "candidate_budget": model.get("cost", {}).get("budget"),
            "known_items": model.get("cost", {}).get("known_items", []),
            "unknown_items": unknown_items,
            "total_project_estimate": {"value": None, "unit": "CNY", "known_status": "unknown",
                                       "unknown_reason": "本切片不是全项目估价", "source_refs": []},
            "formal_quote": False,
        },
        "unknown_items": unknown_items,
        "measurement_rules": [
            {"rule_id": "floor-net-area.v1", "supported_objects": "functional_zone", "unit": "m²",
             "formula": "矩形对象宽度 × 长度，四位小数", "cost_scope": "floor_net_area"},
            {"rule_id": "display-object-count.v1", "supported_objects": "display_object", "unit": "项",
             "formula": "按稳定对象 ID 计数", "cost_scope": "not_priced"},
            {"rule_id": "partition-visual-length.v1", "supported_objects": "partition", "unit": "m",
             "formula": "二维较长边；高度和做法未知", "cost_scope": "not_priced"},
            {"rule_id": "unknown-scope.v1", "supported_objects": "circulation/material/product", "unit": "unknown",
             "formula": "缺项保持 unknown，不填 0", "cost_scope": "not_priced"},
        ],
        "status": {"lifecycle_status": "draft", "formal_quote": False,
                   "external_effects_enabled": False, "procurement_status": "not_started",
                   "publication_status": "not_approved"},
    }
    return package, plan_bytes, iso_bytes, gltf_bytes, node_map


def generate_development_outputs(package: dict[str, Any], plan_bytes: bytes,
                                 iso_bytes: bytes, gltf_bytes: bytes) -> dict[str, tuple[str, str, bytes]]:
    production_revision_id = package["production_revision_id"]
    outputs: dict[str, tuple[str, str, bytes]] = {
        "plan_svg": ("development-plan.svg", "image/svg+xml", plan_bytes),
        "isometric_svg": ("development-isometric.svg", "image/svg+xml", iso_bytes),
        "model_gltf": ("development-model.gltf", "model/gltf+json", gltf_bytes),
        "development_json": (f"development-{production_revision_id}.json", "application/json", _json_bytes(package)),
    }
    stream = io.StringIO(newline="")
    fields = ["quantity_item_id", "object_id", "source_object_id", "description", "quantity", "unit",
              "formula", "source_kind", "quantity_status", "cost_scope", "rule_version", "option_revision_id"]
    writer = csv.DictWriter(stream, fieldnames=["production_revision_id", *fields], lineterminator="\n")
    writer.writeheader()
    for item in package["quantity_items"]:
        writer.writerow({"production_revision_id": production_revision_id, **{key: item[key] for key in fields}})
    outputs["quantity_csv"] = (f"quantities-{production_revision_id}.csv", "text/csv; charset=utf-8",
                               stream.getvalue().encode("utf-8-sig"))
    quote = package["cost"]["quote"]
    pricing = package["cost"]["pricing"]

    def show(value: Any) -> str:
        return "未知" if value is None else escape(str(value))

    quantity_rows = "".join(
        f"<tr><td>{escape(item['description'])}</td><td>{escape(item['quantity'])} {escape(item['unit'])}</td><td>{escape(item['object_id'])}</td><td>{escape(item['cost_scope'])}</td></tr>"
        for item in package["quantity_items"]
    )
    unknown_rows = "".join(f"<li><strong>{escape(item['statement'])}</strong>：{escape(item['reason'])}</li>"
                           for item in package["unknown_items"])
    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>AI 同源深化量价草稿 {escape(production_revision_id)}</title>
<style>body{{font:14px/1.6 "Microsoft YaHei",sans-serif;color:#263342;max-width:980px;margin:32px auto;padding:0 20px}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:9px;border-bottom:1px solid #dfe5ea}}h1{{font-size:22px}}small{{color:#6b7a8a}}</style>
<h1>AI 同源深化量价草稿</h1><p><strong>未批准 · 非正式报价 · 不用于施工发布或采购下单</strong></p>
<p>采用候选：<code>{escape(package['option_revision_id'])}</code> · 采用版本 v{package['adoption_version']} · 输入哈希 <code>{escape(package['input_hash'])}</code></p>
<p>计量范围：{escape(package['cost']['scope_label'])}。glTF 节点映射对象 {len(package['views']['node_object_map'])} 项；显示高度仅为视觉假设。</p>
<h2>确定性量价</h2><table>
<tr><th>项目</th><th>值</th></tr>
<tr><td>计价净地坪面积</td><td>{escape(quote['quantity'])} m²</td></tr>
<tr><td>未税单位成本</td><td>{show(pricing['unit_cost_net'])}</td></tr>
<tr><td>成本来源</td><td>{escape(pricing['source_label'])}</td></tr>
<tr><td>施工成本加成率</td><td>{escape(pricing['cost_markup'])}</td></tr>
<tr><td>本地试用税率</td><td>{escape(pricing['trial_tax_rate'])}（{escape(pricing['tax_status'])}）</td></tr>
<tr><td>未税成本</td><td>{show(quote['cost_net'])}</td></tr><tr><td>未税草稿报价</td><td>{show(quote['sale_net'])}</td></tr>
<tr><td>试用税额</td><td>{show(quote['tax'])}</td></tr><tr><td>含税草稿报价</td><td>{show(quote['sale_gross'])}</td></tr></table>
<h2>对象工程量</h2><table><tr><th>对象</th><th>数量</th><th>稳定 ID</th><th>计价范围</th></tr>{quantity_rows}</table>
<h2>明确缺项</h2><ul>{unknown_rows}</ul><p><small>公式版本 {escape(package['cost']['formula_version'])}；计量规则版本 {escape(package['cost']['measurement_version'])}。正式税务、合同、专业审签及发布责任未核验。</small></p></html>'''
    outputs["cost_html"] = (f"cost-{production_revision_id}.html", "text/html; charset=utf-8", html.encode("utf-8"))
    files = [{"kind": kind, "filename": name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
             for kind, (name, _, data) in outputs.items()]
    manifest = {"schema_version": "rkd-ai-development-manifest.v1",
                "output_version": OUTPUT_VERSION,
                "production_revision_id": production_revision_id,
                "option_revision_id": package["option_revision_id"],
                "adoption_version": package["adoption_version"],
                "input_hash": package["input_hash"],
                "quantity_item_ids": [item["quantity_item_id"] for item in package["quantity_items"]],
                "node_object_map": package["views"]["node_object_map"],
                "formal_quote": False, "external_effects_enabled": False,
                "publication_status": "not_approved", "files": files}
    outputs["manifest_json"] = (f"manifest-{production_revision_id}.json", "application/json", _json_bytes(manifest))
    package_stream = io.BytesIO()
    with zipfile.ZipFile(package_stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, _, data in outputs.values():
            archive.writestr(name, data)
    outputs["package_zip"] = (f"development-{production_revision_id}.zip", "application/zip", package_stream.getvalue())
    return outputs
