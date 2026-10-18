from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from decimal import Decimal
from html import escape
from xml.etree import ElementTree as ET


def generate_design_outputs(baseline: dict, model: dict, validation: dict, requirement: dict) -> dict:
    revision = baseline["revision_no"]
    width, length = Decimal(model["width"]), Decimal(model["length"])
    scale = Decimal("50")
    margin = Decimal("45")
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    svg = ET.Element(f"{{{ns}}}svg", {"viewBox": f"0 0 {width * scale + margin * 2} {length * scale + margin * 2 + 40}", "role": "img", "aria-label": "展厅分区设计草稿"})
    def element(tag, attrs=None, value=None):
        node = ET.SubElement(svg, f"{{{ns}}}{tag}", attrs or {})
        node.text = value
    element("title", value=f"展厅分区草稿 v{revision}")
    element("metadata", value=json.dumps(baseline, ensure_ascii=False))
    element("rect", {"x": str(margin), "y": str(margin), "width": str(width * scale), "height": str(length * scale), "fill": "#ffffff", "stroke": "#263342", "stroke-width": "2"})
    colors = ["#def0e8", "#e8edf8", "#f7ead6", "#f3e3e9"]
    for i, zone in enumerate(model["zones"]):
        x, y, w, d = (Decimal(zone[k]) * scale for k in ("x", "y", "width", "length"))
        element("rect", {"x": str(margin + x), "y": str(margin + y), "width": str(w), "height": str(d), "fill": colors[i % len(colors)], "stroke": "#647487"})
        # Text uses a fixed drawing scale and bounded length so narrow zones remain legible.
        font_size = max(Decimal("4"), min(Decimal("14"), w / Decimal(max(1, len(zone["name"])))))
        element("text", {"x": str(margin + x + w / 2), "y": str(margin + y + d / 2), "text-anchor": "middle", "font-size": str(font_size), "fill": "#263342"}, zone["name"])
        element("text", {"x": str(margin + x + w / 2), "y": str(margin + y + d / 2 + 19), "text-anchor": "middle", "font-size": str(min(Decimal("12"), w / 9))}, zone["area_m2"] + " m2")
    element("text", {"x": str(margin + width * scale / 2), "y": str(margin + Decimal(model["aisle_width"]) * scale / 2), "text-anchor": "middle", "font-size": "13"}, f"预留通道 {model['aisle_width']} m")
    element("text", {"x": str(margin), "y": "25", "font-size": "14"}, f"{width} x {length} m | v{revision}")
    element("text", {"x": str(margin), "y": str(length * scale + margin + 30), "font-size": "12", "fill": "#a45043"}, "TEST / DESIGN DRAFT - NOT FOR CONSTRUCTION")
    svg_bytes = ET.tostring(svg, encoding="utf-8", xml_declaration=True)
    dxf = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1015", "9", "$INSUNITS", "70", "6", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    def rectangle(x, y, w, d, layer):
        dxf.extend(["0", "LWPOLYLINE", "100", "AcDbEntity", "8", layer, "100", "AcDbPolyline", "90", "4", "70", "1"])
        for px, py in [(x, y), (x + w, y), (x + w, y + d), (x, y + d)]:
            dxf.extend(["10", str(px), "20", str(py)])
    rectangle(Decimal(0), Decimal(0), width, length, "M3-DRAFT-BOUNDARY")
    rectangle(Decimal(0), Decimal(0), width, Decimal(model["aisle_width"]), "M3-DRAFT-AISLE")
    for z in model["zones"]:
        rectangle(*(Decimal(z[k]) for k in ("x", "y", "width", "length")), "M3-ZONE-" + z["zone_id"])
    dxf.extend(["0", "TEXT", "100", "AcDbEntity", "8", "M3-DRAFT-NOTES", "100", "AcDbText", "10", "0", "20", "-1", "30", "0", "40", "0.25", "1", f"DESIGN DRAFT - NOT FOR CONSTRUCTION | v{revision}", "100", "AcDbText", "0", "ENDSEC", "0", "EOF", ""])
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["design_revision_id", "requirement_id", "requirement_revision_no", "zone_id", "name", "area", "unit", "x_m", "y_m", "width_m", "length_m", "source", "status"])
    for z in model["zones"]:
        # Prevent editable names from turning into formulas when the CSV opens in Excel.
        name = "'" + z["name"] if z["name"].startswith(("=", "+", "-", "@")) else z["name"]
        writer.writerow([baseline["design_revision_id"], baseline["requirement_id"], baseline["requirement_revision_no"], z["zone_id"], name, z["area_m2"], "m²", z["x"], z["y"], z["width"], z["length"], "程序计算的矩形功能分区", "设计草稿"])
    checks = "".join(f"<li>{escape(c['code'])}: {escape(c['message'])} ({escape(c['status'])})</li>" for c in validation["hard_checks"] + validation["professional_checks"])
    rows = "".join(f"<tr><td>{escape(z['name'])}</td><td>{z['width']} × {z['length']} m</td><td>{z['area_m2']} m²</td></tr>" for z in model["zones"])
    notes = escape(requirement["content"].get("design_notes", ""))
    report = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>展厅分区草稿 v{revision}</title><style>body{{font:14px 'Microsoft YaHei',sans-serif;margin:32px auto;padding:0 20px;max-width:1000px;color:#263342}}svg{{width:100%;max-height:550px}}td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}table{{width:100%;border-collapse:collapse}}code{{overflow-wrap:anywhere}}</style></head><body><h1>展厅分区设计草稿 v{revision}</h1><p>规则生成 / 人工编辑 · 未批准 · 不用于施工发布。分区线不是墙体。</p><p>需求基线：{escape(baseline['requirement_id'])} / v{baseline['requirement_revision_no']}<br>设计基线：{escape(baseline['design_revision_id'])}<br>输入哈希：<code>{baseline['input_hash']}</code></p>{svg_bytes.decode('utf-8').split('?>', 1)[-1]}<table><tr><th>分区</th><th>尺寸</th><th>面积</th></tr>{rows}</table><h2>规则检查与专业限制</h2><ul>{checks}</ul><h2>需求备注</h2><p>{notes}</p></body></html>'''.encode("utf-8")
    def json_bytes(value):
        return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    outputs = {
        "layout_svg": (f"layout-v{revision}.svg", "image/svg+xml", svg_bytes),
        "layout_dxf": (f"layout-v{revision}.dxf", "application/dxf", "\n".join(dxf).encode("ascii")),
        "zone_csv": (f"zones-v{revision}.csv", "text/csv; charset=utf-8", stream.getvalue().encode("utf-8-sig")),
        "model_json": (f"model-v{revision}.json", "application/json", json_bytes({"baseline": baseline, "model": model, "requirement": requirement, "validation": validation})),
        "report_html": (f"design-v{revision}.html", "text/html; charset=utf-8", report),
    }
    manifest = {"schema_version": "design-production-package.v1", **baseline, "purpose": "design_draft_not_for_construction", "rule_version": validation["rule_version"], "files": [{"kind": kind, "filename": name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)} for kind, (name, _, data) in outputs.items()]}
    outputs["manifest_json"] = (f"manifest-v{revision}.json", "application/json", json_bytes(manifest))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, _, data in outputs.values():
            archive.writestr(filename, data)
    outputs["package_zip"] = (f"design-package-v{revision}.zip", "application/zip", buf.getvalue())
    return outputs
