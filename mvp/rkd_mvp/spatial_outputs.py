from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from xml.etree import ElementTree as ET


FORMULA_VERSION = "spatial-floor-cost-markup-tax.v1"


def quote_result(area: Decimal, pricing: dict) -> dict:
    def money(value: Decimal) -> str:
        return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
    cost = pricing["unit_cost_net"]
    net_cost = None if cost is None else area * Decimal(cost)
    net = None if net_cost is None else Decimal(money(net_cost * (1 + Decimal(pricing["cost_markup"]))))
    tax = None if net is None else Decimal(money(net * Decimal(pricing["trial_tax_rate"])))
    return {"quantity": format(area, "f"), "unit": "m²", "currency": "CNY",
            "cost_net": None if net_cost is None else money(net_cost),
            "sale_net": None if net is None else money(net),
            "tax": None if tax is None else money(tax),
            "sale_gross": None if net is None else money(net + tax),
            "status": "unknown_cost" if net_cost is None else "draft"}


def generate_outputs(baseline: dict, width: Decimal, length: Decimal,
                     deductions: list[dict], quote: dict) -> dict[str, tuple[str, str, bytes]]:
    revision = baseline["revision_no"]
    area = baseline["quantity"]
    scope = "TEST / DESIGN DRAFT - NOT FOR CONSTRUCTION"
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    def element(tag, attributes=None, text=None, parent=None):
        item = ET.SubElement(parent, f"{{{ns}}}{tag}", attributes or {}) if parent is not None else ET.Element(f"{{{ns}}}{tag}", attributes or {})
        item.text = text
        return item
    margin = max(width, length) / Decimal("10")
    svg = element("svg", {"viewBox": f"{-margin} {-margin} {width + margin * 2} {length + margin * 3}", "role": "img", "aria-label": f"地坪净面积 {area} 平方米"})
    element("title", text=f"测试地坪 v{revision} - {area} m2", parent=svg)
    element("metadata", text=json.dumps(baseline, ensure_ascii=False), parent=svg)
    element("rect", {"width": str(width), "height": str(length), "fill": "#dfeee8", "stroke": "#183b35", "stroke-width": str(margin / 20)}, parent=svg)
    for item in deductions:
        element("rect", {"x": item["x"], "y": item["y"], "width": item["width"], "height": item["length"], "fill": "#fff", "stroke": "#bd4b39", "stroke-width": str(margin / 20)}, parent=svg)
    element("text", {"x": "0", "y": str(-margin / 3), "font-size": str(margin / 3), "fill": "#183b35"}, f"v{revision} | {width} x {length} m | {area} m2", svg)
    element("text", {"x": "0", "y": str(length + margin), "font-size": str(margin / 4), "fill": "#8d2e22"}, scope, svg)
    svg_bytes = ET.tostring(svg, encoding="utf-8", xml_declaration=True)

    lines = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1015", "9", "$INSUNITS", "70", "6", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    def rectangle(x, y, w, h, layer):
        lines.extend(["0", "LWPOLYLINE", "100", "AcDbEntity", "8", layer, "100", "AcDbPolyline", "90", "4", "70", "1"])
        for px, py in [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]:
            lines.extend(["10", str(px), "20", str(py)])
    rectangle(Decimal(0), Decimal(0), width, length, "M2-TEST-FLOOR")
    for item in deductions:
        rectangle(*(Decimal(item[key]) for key in ("x", "y", "width", "length")), "M2-TEST-DEDUCTION")
    for index, text in enumerate([scope, f"Revision {revision} | area {area} m2", f"Baseline: {baseline['geometry_revision_id']}"]):
        lines.extend(["0", "TEXT", "100", "AcDbEntity", "8", "M2-TEST-NOTES", "100", "AcDbText", "10", "0", "20", str(-margin * (index+1)), "30", "0", "40", str(margin / 4), "1", text, "100", "AcDbText"])
    lines.extend(["0", "ENDSEC", "0", "EOF", ""])

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["geometry_revision_id", "revision_no", "input_hash", "quantity_item_id", "description", "quantity", "unit", "source", "status"])
    writer.writerow([baseline["geometry_revision_id"], revision, baseline["input_hash"], baseline["quantity_item_id"], "参数地坪净面积", area, "m²", "程序计算：外框面积减扣除区面积", "测试/设计草稿"])
    for item in deductions:
        writer.writerow([baseline["geometry_revision_id"], revision, baseline["input_hash"], item["deduction_id"], "扣除区域（不重复计入净面积）", str(Decimal(item["width"]) * Decimal(item["length"])), "m²", "人工参数输入", "测试/设计草稿"])

    pricing = quote["pricing"]
    result = quote["result"]
    fields = [("净工程量", f"{area} m²"), ("未税单位成本", pricing["unit_cost_net"] or "未知"),
              ("成本来源", pricing["source_label"]), ("施工成本加成率", pricing["cost_markup"]),
              ("本地试用税率", pricing["trial_tax_rate"]), ("未税成本", result["cost_net"]),
              ("未税报价", result["sale_net"]), ("税额", result["tax"]), ("含税报价", result["sale_gross"])]
    rows = "".join(f"<tr><th>{escape(label)}</th><td>{escape(str(value) if value is not None else '未知')}</td></tr>" for label, value in fields)
    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>M2 测试地坪报价 v{revision}</title><style>body{{font:14px 'Microsoft YaHei',sans-serif;color:#263342;margin:32px auto;padding:0 20px;max-width:900px}}h1{{font-size:24px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #ddd}}svg{{display:block;width:100%;max-height:420px}}code{{overflow-wrap:anywhere}}@media print{{body{{margin:0}}}}</style>
<h1>测试地坪报价 / v{revision}</h1><p>测试/设计草稿 · 非正式报价 · 不用于施工发布。税率仅作本地试算。</p>
<p>几何基线：<code>{baseline['geometry_revision_id']}</code><br>报价修订：<code>{quote['quote_revision_id']}</code><br>输入哈希：<code>{baseline['input_hash']}</code></p>
{svg_bytes.decode('utf-8').split('?>', 1)[-1]}<table>{rows}</table><p>公式版本：{FORMULA_VERSION}。未税报价按分舍入后计算税额，含税报价等于未税报价加税额。数量保持原始 Decimal 精度；缺失成本保持未知。</p></html>'''.encode("utf-8")
    outputs = {
        "svg": (f"geometry-v{revision}.svg", "image/svg+xml", svg_bytes),
        "dxf": (f"geometry-v{revision}.dxf", "application/dxf", "\n".join(lines).encode("ascii")),
        "quantity_csv": (f"quantity-v{revision}.csv", "text/csv; charset=utf-8", output.getvalue().encode("utf-8-sig")),
        "quote_html": (f"quote-v{revision}.html", "text/html; charset=utf-8", html),
    }
    manifest = {"schema_version": "spatial-production-package.v1", **baseline,
                "purpose": scope, "quote": quote, "files": [
                    {"kind": kind, "filename": filename, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
                    for kind, (filename, _, data) in outputs.items()]}
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    outputs["manifest_json"] = (f"manifest-v{revision}.json", "application/json", manifest_bytes)
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, _, data in outputs.values():
            archive.writestr(filename, data)
    outputs["package_zip"] = (f"production-v{revision}.zip", "application/zip", package.getvalue())
    return outputs
