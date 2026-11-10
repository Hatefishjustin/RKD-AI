"""DELIVERY-01a/01b: same-source technical draft outputs.

All outputs are derived from ONE adopted development package. They are
explicitly labelled as technical drafts: no construction issue, no product
selection, no professional sign-off, and no invented dimensions or prices.
"""
from __future__ import annotations

import csv
from html import escape
import hashlib
import io
import json
from typing import Any
import zipfile

HANDOVER_VERSION = "rkd-ai-technical-handover.v1"
OUTPUT_VERSION = "ai-technical-delivery-outputs.v1"

SUPPORTED_SCOPE = [
    {"scope_id": "floor-net-area", "statement": "功能分区净地坪面积（确定性计算）", "status": "supported",
     "basis": "同源对象矩形尺寸与计量规则"},
    {"scope_id": "plan-geometry", "statement": "边界、入口、障碍、功能分区、展陈与隔断的二维几何关系", "status": "supported",
     "basis": "已采用且通过硬检查的候选模型"},
    {"scope_id": "material-intent", "statement": "材料分区与设计意向标注", "status": "supported_intent_only",
     "basis": "同源材料 ID，未绑定产品"},
]
UNSUPPORTED_SCOPE = [
    ("spec-product", "材料规格、样板、供应商、单价与适用价格", "没有已批准产品或报价来源"),
    ("construction-detail", "构造层次、基层、收口、厚度、防火与防潮性能", "未建模且未做专业设计"),
    ("mep-fire", "机电、消防、天花、灯具与现场接口", "本切片未建模；项目排除范围不等于接口不存在"),
    ("survey", "现场实测边界、柱网、层高与洞口", "边界仍为测试参数，未现场核验"),
    ("quantity-full", "全项目工程量、损耗、排版、包装与采购换算", "只对功能分区净地坪计价，未知不补 0"),
    ("formal", "正式施工图、正式报价、税务结论、专业审签与施工发布", "需相应责任人与授权，不由程序代签"),
]
REVIEW_TASKS = [
    {"task_id": "review-boundary", "role": "现场/建筑专业", "statement": "核对边界、柱网、入口、障碍与层高是否为现场实测", "status": "pending"},
    {"task_id": "review-material", "role": "材料/室内专业", "statement": "确定材料规格、样板、做法与适用部位，替换设计意向", "status": "pending"},
    {"task_id": "review-detail", "role": "施工图专业", "statement": "补充节点构造、收口、厚度的设计并复核可施工性", "status": "pending"},
    {"task_id": "review-quantity", "role": "造价/商务", "statement": "核对净量至清单量、采购量的换算及价源", "status": "pending"},
    {"task_id": "review-release", "role": "有权责任人", "statement": "决定本技术包是否可进入正式发布流程", "status": "pending"},
]


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")


def _color(material_id: Any) -> str:
    return {"mat-warm": "#e7d5bd", "mat-cool": "#dce4ed", "mat-neutral": "#e4e8eb"}.get(str(material_id), "#e4e8eb")


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def technical_plan_svg(package: dict[str, Any], delivery: dict[str, Any]) -> bytes:
    boundary = package["boundary"]
    width, length = _number(boundary.get("width")), _number(boundary.get("length"))
    scale = min(760 / max(width, 1), 520 / max(length, 1))
    ox, oy = 110.0, 90.0

    def px(x: float) -> float:
        return ox + x * scale

    def py(y: float) -> float:
        return oy + y * scale

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 700" role="img" aria-label="同源技术平面草稿">',
        '<rect width="1000" height="700" fill="#ffffff"/>',
        '<text x="28" y="34" font-size="17" fill="#243447">技术平面草稿 · 同源对象与尺寸标注</text>',
        '<text x="28" y="55" font-size="11" fill="#8a6836">非施工图 · 尺寸/材料/做法未经专业复核 · 禁止用于施工发布</text>',
    ]
    for x in range(0, int(width) + 1):
        parts.append(f'<line x1="{px(x):.2f}" y1="{py(0):.2f}" x2="{px(x):.2f}" y2="{py(length):.2f}" stroke="#eef1f4" stroke-width="0.6"/>')
    for y in range(0, int(length) + 1):
        parts.append(f'<line x1="{px(0):.2f}" y1="{py(y):.2f}" x2="{px(width):.2f}" y2="{py(y):.2f}" stroke="#eef1f4" stroke-width="0.6"/>')
    parts.append(f'<rect x="{px(0):.2f}" y="{py(0):.2f}" width="{width * scale:.2f}" height="{length * scale:.2f}" fill="none" stroke="#354557" stroke-width="2"/>')
    for obj in package["objects"]:
        shape = obj.get("shape", {})
        x, y = _number(shape.get("x")), _number(shape.get("y"))
        w, h = _number(shape.get("width")), _number(shape.get("length"))
        if w <= 0 or h <= 0:
            continue
        kind = obj["kind"]
        if kind == "material_surface":
            continue  # drawn as hatch inside its parent zone below
        stroke = {"partition_intent": "#b0762e", "site_interface": "#9b3f3f",
                  "entrance_zone": "#2f6f52"}.get(kind, "#6b7987")
        fill = _color(obj.get("material_id")) if kind in {"floor_surface", "display_object"} else "none"
        parts.append(f'<rect x="{px(x):.2f}" y="{py(y):.2f}" width="{w * scale:.2f}" height="{h * scale:.2f}" '
                     f'fill="{fill}" stroke="{stroke}" stroke-width="{1.6 if kind != "floor_surface" else 0.9}"/>')
        label = f'{obj["object_id"]}'
        parts.append(f'<text x="{px(x) + 3:.2f}" y="{py(y) + 11:.2f}" font-size="8" fill="#263342">{escape(label)}</text>')
        if kind == "floor_surface":
            parts.append(f'<text x="{px(x + w / 2):.2f}" y="{py(y + h / 2):.2f}" text-anchor="middle" font-size="10" fill="#3c4a58">{escape(obj["name"][:12])}</text>')
            parts.append(f'<text x="{px(x + w / 2):.2f}" y="{py(y + h / 2) + 13:.2f}" text-anchor="middle" font-size="8" fill="#6b7a8a">{escape(str(shape.get("width")))} × {escape(str(shape.get("length")))} m</text>')
    # Dimension lines for the outer boundary.
    parts.append(f'<line x1="{px(0):.2f}" y1="{py(length) + 22:.2f}" x2="{px(width):.2f}" y2="{py(length) + 22:.2f}" stroke="#354557" stroke-width="0.8"/>')
    parts.append(f'<text x="{px(width / 2):.2f}" y="{py(length) + 38:.2f}" text-anchor="middle" font-size="11" fill="#354557">边界宽 {escape(str(boundary.get("width")))} m（{escape(str(boundary.get("boundary_source")))}）</text>')
    parts.append(f'<line x1="{px(0) - 22:.2f}" y1="{py(0):.2f}" x2="{px(0) - 22:.2f}" y2="{py(length):.2f}" stroke="#354557" stroke-width="0.8"/>')
    parts.append(f'<text x="{px(0) - 30:.2f}" y="{py(length / 2):.2f}" transform="rotate(-90 {px(0) - 30:.2f} {py(length / 2):.2f})" text-anchor="middle" font-size="11" fill="#354557">边界长 {escape(str(boundary.get("length")))} m</text>')
    materials = package.get("materials", [])
    parts.append('<text x="28" y="640" font-size="11" fill="#354557">材料意向图例（未选产品）：</text>')
    for index, material in enumerate(materials[:4]):
        cx = 210 + index * 150
        parts.append(f'<rect x="{cx}" y="629" width="12" height="12" fill="{_color(material.get("material_id"))}" stroke="#6b7987" stroke-width="0.6"/>')
        parts.append(f'<text x="{cx + 17}" y="639" font-size="10" fill="#3c4a58">{escape(str(material.get("material_id")))}</text>')
    parts.append(f'<text x="28" y="672" font-size="10" fill="#6b7a8a">同源包 {escape(package["production_revision_id"])} · 交付 {escape(delivery["delivery_id"])} · 采用版本 v{int(delivery["adoption_version"])} · 对象 {len(package["objects"])} 项</text>')
    parts.append('</svg>')
    return "\n".join(parts).encode("utf-8")


def detail_node_svg(package: dict[str, Any], delivery: dict[str, Any]) -> bytes:
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 420" role="img" aria-label="地坪与隔断交接节点示意">',
        '<rect width="820" height="420" fill="#ffffff"/>',
        '<text x="26" y="32" font-size="16" fill="#243447">节点示意 · 地坪 / 隔断交接</text>',
        '<text x="26" y="52" font-size="11" fill="#8a6836">构造示意，不是施工详图；所有层次、尺寸与性能参数未知，不得据此施工</text>',
        '<rect x="90" y="250" width="440" height="26" fill="#d9dfe5" stroke="#48566a" stroke-width="1"/>',
        '<rect x="90" y="230" width="440" height="20" fill="#e7d5bd" stroke="#48566a" stroke-width="1"/>',
        '<rect x="300" y="96" width="24" height="134" fill="#c9d2db" stroke="#48566a" stroke-width="1"/>',
        '<line x1="90" y1="276" x2="530" y2="276" stroke="#48566a" stroke-width="0.6" stroke-dasharray="4 3"/>',
        '<text x="110" y="244" font-size="10" fill="#3c4a58">饰面层（规格 unknown）</text>',
        '<text x="110" y="267" font-size="10" fill="#3c4a58">基层 / 找平（做法 unknown）</text>',
        '<text x="332" y="160" font-size="10" fill="#3c4a58">隔断（高度 / 厚度 / 构造 unknown）</text>',
    ]
    for index, (_, statement, reason) in enumerate(UNSUPPORTED_SCOPE[:5]):
        y = 98 + index * 24
        parts.append(f'<text x="580" y="{y}" font-size="9.5" fill="#8a4b2a">待定：{escape(statement[:16])}</text>')
        parts.append(f'<text x="580" y="{y + 12}" font-size="8.5" fill="#6b7a8a">{escape(reason[:22])}</text>')
    parts.append(f'<text x="26" y="392" font-size="10" fill="#6b7a8a">同源包 {escape(package["production_revision_id"])} · 交付 {escape(delivery["delivery_id"])} · 专业复核状态：pending</text>')
    parts.append('</svg>')
    return "\n".join(parts).encode("utf-8")


def material_schedule_csv(package: dict[str, Any]) -> bytes:
    stream = io.StringIO(newline="")
    fields = ["object_id", "source_object_id", "object_kind", "name", "material_id", "application",
              "specification_status", "product_status", "method_status", "quantity_scope",
              "measurement_rule", "source_refs", "missing_reason", "release_status"]
    writer = csv.DictWriter(stream, fieldnames=["production_revision_id", *fields], lineterminator="\n")
    writer.writeheader()
    for obj in package["objects"]:
        quantity_scope = "floor_net_area" if obj["kind"] == "floor_surface" else "not_priced"
        writer.writerow({
            "production_revision_id": package["production_revision_id"],
            "object_id": obj["object_id"], "source_object_id": obj["source_object_id"],
            "object_kind": obj["kind"], "name": obj["name"], "material_id": obj.get("material_id") or "unknown",
            "application": "地坪" if obj["kind"] in {"floor_surface", "material_surface"} else "设计意向对象",
            "specification_status": "unknown", "product_status": "unknown", "method_status": "unknown",
            "quantity_scope": quantity_scope,
            "measurement_rule": MEASUREMENT_LABEL if quantity_scope == "floor_net_area" else "未建立计量规则",
            "source_refs": "|".join(obj.get("source_refs", [])),
            "missing_reason": "材料规格、样板、做法与产品均未确定；未知不填 0",
            "release_status": "not_approved",
        })
    return stream.getvalue().encode("utf-8-sig")


MEASUREMENT_LABEL = "floor-net-area.v1"


def build_handover(package: dict[str, Any], delivery: dict[str, Any],
                   extractions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": HANDOVER_VERSION,
        "delivery_id": delivery["delivery_id"],
        "production_revision_id": package["production_revision_id"],
        "option_revision_id": package["option_revision_id"],
        "adoption_version": int(delivery["adoption_version"]),
        "input_hash": delivery["input_hash"],
        "baseline": package["baseline"],
        "delivery_depth": "technical_draft_not_construction_documents",
        "supported_scope": SUPPORTED_SCOPE,
        "unsupported_scope": [
            {"item_id": item, "statement": statement, "reason": reason,
             "value": None, "known_status": "unknown", "source_refs": []}
            for item, statement, reason in UNSUPPORTED_SCOPE
        ],
        "source_extractions": [
            {"extraction_id": item["extraction_id"], "file_id": item["file_id"],
             "filename": item["filename"], "status": item["status"],
             "segment_count": int(item["segment_count"]), "file_sha256": item["file_sha256"]}
            for item in extractions
        ],
        "object_ids": [obj["object_id"] for obj in package["objects"]],
        "quantity_item_ids": [item["quantity_item_id"] for item in package["quantity_items"]],
        "review_tasks": [dict(task) for task in REVIEW_TASKS],
        "status": {"professional_review": "pending", "formal_quote": False,
                   "construction_issue": False, "publication_status": "not_approved",
                   "external_effects_enabled": False, "purchase_order": "not_started"},
    }


def technical_handover_html(handover: dict[str, Any], delivery: dict[str, Any]) -> bytes:
    supported = "".join(
        f"<tr><td>{escape(item['statement'])}</td><td>{escape(item['status'])}</td><td>{escape(item['basis'])}</td></tr>"
        for item in handover["supported_scope"]
    )
    unsupported = "".join(
        f"<tr><td>{escape(item['statement'])}</td><td>unknown</td><td>{escape(item['reason'])}</td></tr>"
        for item in handover["unsupported_scope"]
    )
    reviews = "".join(
        f"<tr><td>{escape(task['role'])}</td><td>{escape(task['statement'])}</td><td>{escape(task['status'])}</td></tr>"
        for task in handover["review_tasks"]
    )
    sources = "".join(
        f"<li>{escape(item['filename'])} · {escape(item['status'])} · 片段 {item['segment_count']} · <code>{escape(item['file_sha256'][:16])}…</code></li>"
        for item in handover["source_extractions"]
    ) or "<li>本次未登记可解析资料片段；原件内容未进入模型上下文</li>"
    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>技术交接说明 {escape(delivery['delivery_id'])}</title>
<style>body{{font:14px/1.65 "Microsoft YaHei",sans-serif;color:#263342;max-width:1000px;margin:32px auto;padding:0 20px}}
table{{border-collapse:collapse;width:100%;margin:10px 0 22px}}th,td{{text-align:left;padding:8px;border-bottom:1px solid #dfe5ea;vertical-align:top}}
h1{{font-size:22px}}h2{{font-size:16px;margin-top:26px}}code{{font-size:12px}}small{{color:#6b7a8a}}
.banner{{border-left:3px solid #b0762e;background:#fbf6ec;padding:10px 14px}}</style>
<h1>技术交接说明（草稿）</h1>
<p class="banner"><strong>非施工图 · 未专业复核 · 未批准发布施工或采购</strong>。本包只用于内部技术交接与专业复核准备。</p>
<p>采用候选 <code>{escape(handover['option_revision_id'])}</code> · 采用版本 v{handover['adoption_version']} · 同源深化包 <code>{escape(handover['production_revision_id'])}</code> · 交付 <code>{escape(delivery['delivery_id'])}</code></p>
<p>输入哈希 <code>{escape(handover['input_hash'])}</code> · 交付深度 <code>{escape(handover['delivery_depth'])}</code> · 对象 {len(handover['object_ids'])} 项 · 工程量条目 {len(handover['quantity_item_ids'])} 项</p>
<h2>本包已支持的范围</h2><table><tr><th>范围</th><th>状态</th><th>依据</th></tr>{supported}</table>
<h2>明确未支持 / 保持未知</h2><table><tr><th>缺项</th><th>值</th><th>原因</th></tr>{unsupported}</table>
<h2>资料来源解析状态</h2><ul>{sources}</ul>
<h2>专业复核待办（程序不代签）</h2><table><tr><th>责任角色</th><th>复核内容</th><th>状态</th></tr>{reviews}</table>
<h2>版本与责任边界</h2><p><small>正式报价 false · 施工发布 false · 采购订单 not_started · 外部副作用关闭。图面、材料表、节点示意、清单与说明绑定同一对象集和输入哈希；模型或材料版本变化后本包标记过期，旧文件保留可读。正式税务、合同、消防/机电与现场实测不在本包范围内。</small></p></html>'''
    return html.encode("utf-8")


def generate_technical_outputs(package: dict[str, Any], delivery: dict[str, Any],
                               extractions: list[dict[str, Any]]) -> tuple[dict[str, tuple[str, str, bytes]], dict[str, Any]]:
    handover = build_handover(package, delivery, extractions)
    outputs: dict[str, tuple[str, str, bytes]] = {
        "technical_plan_svg": ("technical-plan.svg", "image/svg+xml", technical_plan_svg(package, delivery)),
        "detail_node_svg": ("detail-node-schematic.svg", "image/svg+xml", detail_node_svg(package, delivery)),
        "material_schedule_csv": ("material-schedule.csv", "text/csv; charset=utf-8", material_schedule_csv(package)),
        "technical_handover_html": ("technical-handover.html", "text/html; charset=utf-8",
                                    technical_handover_html(handover, delivery)),
        "handover_json": (f"handover-{delivery['delivery_id']}.json", "application/json", _json_bytes(handover)),
    }
    files = [{"kind": kind, "filename": name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
             for kind, (name, _, data) in outputs.items()]
    manifest = {"schema_version": "rkd-ai-technical-delivery-manifest.v1",
                "output_version": OUTPUT_VERSION,
                "delivery_id": delivery["delivery_id"],
                "production_revision_id": package["production_revision_id"],
                "option_revision_id": package["option_revision_id"],
                "adoption_version": int(delivery["adoption_version"]),
                "input_hash": delivery["input_hash"],
                "object_ids": handover["object_ids"],
                "quantity_item_ids": handover["quantity_item_ids"],
                "source_extraction_ids": [item["extraction_id"] for item in extractions],
                "professional_review": "pending", "formal_quote": False,
                "construction_issue": False, "publication_status": "not_approved",
                "external_effects_enabled": False, "files": files}
    outputs["delivery_manifest_json"] = (f"manifest-{delivery['delivery_id']}.json", "application/json", _json_bytes(manifest))
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, _, data in outputs.values():
            archive.writestr(name, data)
    outputs["delivery_zip"] = (f"technical-delivery-{delivery['delivery_id']}.zip", "application/zip", stream.getvalue())
    return outputs, manifest
