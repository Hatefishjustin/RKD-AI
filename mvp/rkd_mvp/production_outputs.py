"""One immutable production package from the saved design and derived BOQ."""
import csv
import hashlib
from html import escape
import io
import json
import zipfile


def generate_production_outputs(snapshot, drawing_files):
    revision = snapshot["revision_no"]
    baseline, quote = snapshot["baseline"], snapshot["quote"]
    output = {}

    def add(kind, filename, mime, data):
        output[kind] = (filename, mime, data)

    def json_bytes(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")

    stream = io.StringIO(newline="")
    fields = ["quantity_item_id", "object_id", "description", "quantity", "unit", "formula", "source_kind"]
    writer = csv.DictWriter(stream, fieldnames=["production_revision_id", "design_revision_id", *fields])
    writer.writeheader()
    for item in snapshot["quantities"]:
        writer.writerow({"production_revision_id": snapshot["production_revision_id"], "design_revision_id": baseline["design_revision_id"], **{key: item[key] for key in fields}})
    add("quantity_csv", f"boq-v{revision}.csv", "text/csv; charset=utf-8", stream.getvalue().encode("utf-8-sig"))
    add("production_json", f"production-v{revision}.json", "application/json", json_bytes(snapshot))
    add("procurement_json", f"procurement-v{revision}.json", "application/json", json_bytes({"baseline": baseline, **snapshot["procurement"]}))
    def value(item):
        return "未知" if item is None else escape(str(item))
    rows = "".join(f"<tr><td>{escape(item['description'])}</td><td>{item['quantity']} m²</td><td>{escape(item['object_id'])}</td></tr>" for item in snapshot["quantities"])
    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>地坪量价草稿 v{revision}</title>
<style>body{{font:16px/1.6 system-ui;max-width:960px;margin:40px auto;padding:24px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #ddd}}</style>
<h1>地坪量价草稿 v{revision}</h1><p>设计 v{baseline['design_revision_no']} / 需求 v{baseline['requirement_revision_no']} · 未批准，非正式报价</p>
<p>计量范围：{escape(snapshot['scope_label'])}。未分配区域不计入；材料损耗未知，采购草稿使用净几何数量。</p>
<table><tr><th>对象</th><th>净工程量</th><th>来源 ID</th></tr>{rows}</table>
<p>合计 {quote['quantity']} m²；未税成本 ¥{value(quote['cost_net'])}；未税报价 ¥{value(quote['sale_net'])}；试用税额 ¥{value(quote['tax'])}；含税草稿 ¥{value(quote['sale_gross'])}</p>
<p>成本来源：{escape(snapshot['settings']['source_label'])}；成本加成 {escape(snapshot['settings']['cost_markup'])}；试用税率 {escape(snapshot['settings']['trial_tax_rate'])}。</p>
<p>来源边界：{escape(baseline['boundary_source'])}。现场、消防、结构及材料做法待专业复核。</p>
<p>生产修订 {escape(snapshot['production_revision_id'])}；输入哈希 {snapshot['input_hash']}</p></html>'''
    add("quotation_html", f"quotation-v{revision}.html", "text/html; charset=utf-8", html.encode("utf-8"))
    for kind, (filename, mime, data) in drawing_files.items():
        add(kind, filename, mime, data)
    manifest = {"schema_version": "design-floor-production.v1", "production_revision_id": snapshot["production_revision_id"],
                "baseline": baseline, "input_hash": snapshot["input_hash"], "quantity_item_ids": [item["quantity_item_id"] for item in snapshot["quantities"]],
                "files": [{"filename": name, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)} for name, _, data in output.values()]}
    add("manifest_json", f"manifest-v{revision}.json", "application/json", json_bytes(manifest))
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, _, data in output.values():
            archive.writestr(name, data)
    add("package_zip", f"production-v{revision}.zip", "application/zip", package.getvalue())
    return output
