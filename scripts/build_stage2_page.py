"""Stage 2 review page (v3): six cameras, one plan, one PDF."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "var" / "deliverables" / "ningbo-xiecheng" / "2026-11-10"
ROOT = Path(__file__).resolve().parents[1]

USE_LABEL = {
    "floor": "地面", "wall": "墙面 / 天花", "oak": "中岛台体、展墙翼、家具",
    "walnut": "弧形品牌墙、接待台背板", "bronze": "灯具、五金、展品底座",
    "stone": "中岛顶层台面", "fabric": "沙发、单椅、窗帘", "glass": "洽谈室隔断",
    "plant": "光廊与场景角落",
}
LIGHT_LABEL = {
    "morning": "上午自然光", "bright": "正午偏亮", "afternoon": "下午斜阳",
    "evening": "傍晚暖光", "aerial": "日景鸟瞰",
}


def main() -> int:
    design = json.loads((OUT / "方案A_设计数据.json").read_text(encoding="utf-8"))
    manifest_path = ROOT / "assets" / "CC0-素材清单.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else \
        {"textures": {}, "models": {}}

    area_rows = "".join(
        f"<tr><td>{r['no']}</td><td>{r['name']}{'（环形）' if r.get('ring') else ''}</td>"
        f"<td class='num'>{r['area']:.1f}</td></tr>"
        for r in design["area_table"])
    area_sum = sum(r["area"] for r in design["area_table"])
    narrative = "".join(f"<li>{n}</li>" for n in design["narrative"])
    materials = "".join(
        f"<tr><td><span class='sw' style='background:{m['color']}'></span>{m['name']}</td>"
        f"<td>{USE_LABEL.get(k, '—')}</td></tr>"
        for k, m in design["materials"].items())
    nonorth = "".join(f"<li>{n}</li>" for n in design["non_orthogonal"])

    cams = design["cameras"]
    shots = "".join(
        f"""<figure><img src="03_效果图_{c['id']}_{c['name']}.png" alt="{c['id']} {c['name']}">
<figcaption><strong>{c['id']} · {c['name']}</strong>　{LIGHT_LABEL.get(c['light'], c['light'])}　{c['lens']} mm
　·　{c['note']}</figcaption></figure>"""
        for c in cams)
    cam_rows = "".join(
        f"<tr><td><strong>{c['id']}</strong></td><td>{c['name']}</td>"
        f"<td class='num'>{c['eye'][0]/1000:.2f}, {c['eye'][1]/1000:.2f}</td>"
        f"<td class='num'>{c['target'][0]/1000:.2f}, {c['target'][1]/1000:.2f}</td>"
        f"<td class='num'>{c['lens']}</td><td>{LIGHT_LABEL.get(c['light'], c['light'])}</td>"
        f"<td>{c['light_note']}</td></tr>"
        for c in cams)

    tex_rows = "".join(
        f"<tr><td>{k}</td><td>{v['polyhaven_id']}</td><td>{v['name']}</td>"
        f"<td><a href='{v['source_page']}'>{v['source_page'].replace('https://', '')}</a></td>"
        f"<td>{', '.join(v.get('authors', {}).values()) or '—'}</td><td>CC0 1.0</td></tr>"
        for k, v in manifest.get("textures", {}).items())
    model_rows = "".join(
        f"<tr><td>{k}</td><td>{v['name']}</td>"
        f"<td><a href='{v['source_page']}'>{v['source_page'].replace('https://', '')}</a></td>"
        f"<td>{', '.join(v.get('authors', {}).values()) or '—'}</td><td>CC0 1.0</td></tr>"
        for k, v in manifest.get("models", {}).items())

    total = design["site"]["width"] * design["site"]["height"] / 1e6

    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>宁波协诚 · 方案A · 六视角</title>
<style>
@page{{size:A3 landscape;margin:10mm}}
*{{box-sizing:border-box}}
body{{font:14px/1.7 "Microsoft YaHei","PingFang SC",sans-serif;color:#22303f;margin:0;background:#f4f6f8}}
.wrap{{max-width:1400px;margin:0 auto;padding:22px}}
h1{{font-size:24px;margin:0 0 4px}}
h2{{font-size:17px;margin:26px 0 10px;padding-bottom:6px;border-bottom:1px solid #d9e0e6}}
h3{{font-size:13.5px;margin:12px 0 6px;color:#3a4a5c}}
p{{margin:7px 0}} small{{color:#6b7a8a}}
.hero{{background:#fff;border-left:3px solid #a8763f;padding:16px 20px;margin:14px 0 18px}}
.hero strong{{font-size:15px}}
.tag{{display:inline-block;padding:2px 9px;border:1px solid #c9d2da;border-radius:2px;font-size:12px;margin:0 6px 4px 0;color:#4a5866}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff}}
th,td{{padding:7px 9px;border-bottom:1px solid #e2e8ec;text-align:left;vertical-align:top}}
th{{background:#eef2f4;color:#3a4a5c}}
td.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.sw{{display:inline-block;width:16px;height:16px;margin-right:8px;vertical-align:-3px;border:1px solid #b9c2ca}}
figure{{margin:0 0 14px;background:#fff;border:1px solid #dfe6eb}}
figure img{{display:block;width:100%;height:auto}}
figcaption{{font-size:12px;color:#5a6875;padding:8px 12px;border-top:1px solid #eef2f4;line-height:1.6}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.note{{background:#fffaf0;border:1px solid #e8d5b0;padding:10px 14px;font-size:13px}}
.bad{{background:#fdf3f3;border:1px solid #e5c4c4;padding:10px 14px;font-size:13px}}
ul{{margin:6px 0 12px;padding-left:20px}} li{{margin-bottom:5px}}
.files{{list-style:none;padding:0}} .files li{{background:#fff;border:1px solid #dfe6eb;padding:9px 12px;margin:6px 0}}
.files a{{font-weight:600;color:#1a5c86;margin-right:10px}} .files span{{color:#5c6b79;font-size:12.5px}}
a{{color:#1a5c86}}
footer{{margin:26px 0 10px;color:#6b7a8a;font-size:12px;border-top:1px solid #d9e0e0;padding-top:10px}}
@media print{{body{{background:#fff}} .wrap{{max-width:none}}
figure{{page-break-inside:avoid}} figure img{{max-height:430pt;width:auto;max-width:100%;margin:0 auto}}
h2,h3{{page-break-after:avoid}} table,.grid2{{page-break-inside:auto}} tr{{page-break-inside:avoid}}}}
</style></head><body><div class="wrap">
<h1>宁波协诚集团样品展厅 · 方案 A · 第 3 版（六视角）</h1>
<p><small>中央环岛 · 环游叙事 · 概念方案（非施工图）· 2026-11-10 · 场地 26.17 × 17.92 m / 层高 3.0 m</small></p>

<div class="hero">
<strong>这一版的核心变化：不再是“一个中岛五个角度”，而是六个机位、五套光线，每个功能区各有一张能看懂的画面。所有画面来自同一份设计数据，材质、家具、灯具全部共用。</strong><br>
<span class="tag">6 个机位</span><span class="tag">5 套光线预设</span><span class="tag">CC0 PBR 贴图 6 套</span>
<span class="tag">CC0 家具模型 10 件</span><span class="tag">相机符号已上图</span>
</div>

<h2>① 六张效果图</h2>
{shots}

<h2>② 机位表（与平面图上的 C0–C5 一一对应）</h2>
<table><thead><tr><th>编号</th><th>画面</th><th>机位 x, y（m）</th><th>朝向 x, y（m）</th><th>焦距</th><th>光线</th><th>光怎么打</th></tr></thead>
<tbody>{cam_rows}</tbody></table>
<p><small>为什么有 6 张而不是 5 张：接待台与中岛分处入口两侧（约 140° 夹角），任何单张直线透视都装不下，所以把“序厅”单独拆成 C0，C1 专注“入口看中岛”。</small></p>

<h2>③ 平面布置图（带相机编号与视域）</h2>
<figure><img src="02_方案A_平面布置图.svg" alt="方案A平面布置图">
<figcaption>1:100 平面布置图 · 橙色相机符号 + 虚线扇形为视域 · 右侧图例含“效果图视点 VIEWS”表 · 面积表合计 {area_sum:.1f} ㎡</figcaption></figure>

<h2>④ 设计说明</h2>
<div class="grid2">
<div>
<h3>空间组织（七步叙事）</h3>
<ul>{narrative}</ul>
</div>
<div>
<h3>非直角元素清单</h3>
<ul>{nonorth}</ul>
<h3>与场地条件的关系</h3>
<ul>
<li><strong>保留</strong>：外墙、北向 3 段窗带、东墙 2 段窗、西南楼梯（2.4 × 8.0 m，本次已建出踏步）、东南卫生间（4.17 × 4.7 m）。</li>
<li><strong>未发现结构柱</strong>，中岛可放场地正中。</li>
<li><strong>拆改</strong>：原 U 形展台墙、六边形展台取消；两间洽谈室沿用原隔墙位置改玻璃隔断。</li>
</ul>
</div>
</div>

<h2>⑤ 面积与材料</h2>
<div class="grid2">
<table><thead><tr><th>编号</th><th>区域</th><th style="text-align:right">面积（㎡）</th></tr></thead>
<tbody>{area_rows}
<tr><td>—</td><td><strong>合计</strong></td><td class="num"><strong>{area_sum:.1f}</strong></td></tr>
<tr><td>—</td><td><small>场地外包 26.17 × 17.92</small></td><td class="num"><small>{total:.1f}</small></td></tr>
</tbody></table>
<div>
<table><thead><tr><th>材料</th><th>用在哪</th></tr></thead><tbody>{materials}</tbody></table>
<p><small>材料色块与渲染里的贴图出自同一份数据 + 同一套 CC0 贴图，改一处三处同步。</small></p>
</div>
</div>

<h2>⑥ CC0 素材来源（Poly Haven，全部 CC0 1.0，可商用）</h2>
<h3>PBR 贴图</h3>
<table><thead><tr><th>用途</th><th>素材 ID</th><th>名称</th><th>来源</th><th>作者</th><th>授权</th></tr></thead><tbody>{tex_rows}</tbody></table>
<h3>家具与器物模型</h3>
<table><thead><tr><th>用途</th><th>名称</th><th>来源</th><th>作者</th><th>授权</th></tr></thead><tbody>{model_rows}</tbody></table>
<p><small>下载脚本 <code>scripts/fetch_cc0_assets.py</code>；文件存在 <code>tools/assets/</code>（不进版本库），来源与 SHA-256 记在 <code>assets/CC0-素材清单.json</code>（进版本库）。</small></p>

<h2>⑦ 展品说明（按项目资料核实的结果）</h2>
<div class="note"><p>{design.get("product_note", "")}</p>
<p><small>依据：施工图 DWG/PDF、装修预算 xls、3 张现场照片里都没有出现协诚的产品清单或样品照片；现场照片是毛坯状态。因此不做“猜产品”，改为按本项目主材做四组可辨认的样品。</small></p></div>

<h2>⑧ 这一版做到哪、没做到哪（如实）</h2>
<div class="note">
<p><strong>做到了：</strong>6 个机位、5 套光线（上午 / 正午 / 下午斜阳 / 傍晚 / 日景鸟瞰）；6 套 CC0 PBR 贴图（木饰面、石材、微水泥、布艺、乳胶漆、胡桃木）与 10 件 CC0 家具模型；地面 3 m 分缝、90 mm 踢脚、墙顶 20 mm 阴影缝；玻璃隔断改成细铜框；接待台改为实体前台；补出保留楼梯；四组样品重做；相机位置与朝向写进 <code>方案A_设计数据.json</code> 并画在平面图上。</p>
</div>
<div class="bad">
<p><strong>仍然不像设计公司成果的地方：</strong></p>
<ul>
<li><strong>石材台面仍偏“奶白”</strong>：贴图是大理石／莱姆石，但 M_STONE 提亮后纹理细节被压平，中岛顶层远看仍像一整块浅色石膏。</li>
<li><strong>家具是“缩放到尺寸”的通用模型</strong>：沙发、餐椅、吧椅都不是这个方案指定的款式；只对齐了宽度，高度略有出入，坐垫、缝线、木饰拼缝的精致度达不到样板展厅要求。</li>
<li><strong>展品是示意样品</strong>：石材样块、木饰面板、金属型材、织物样册都是几何体搭的，不是真实产品模型；协诚到底展什么，资料里查不到。</li>
<li><strong>展墙翼仍像“木盒子”</strong>：翼墙上挂的画框是纯色块、没有内容；与地面的收口只有一条深色踢脚。</li>
<li><strong>窗户过曝</strong>：为压住室内亮度，窗外天空板接近纯白，窗框偏黑；每张图的窗光强度是固定的，没有真正的时间变化。</li>
<li><strong>没有人物、没有软装细节</strong>：书、器皿、挂画内容、窗帘褶皱、地毯绒毛都缺，画面里没有人的尺度参照。</li>
<li><strong>鸟瞰是“揭掉天花”的做法</strong>：能看到布局，但露出墙顶截面，不是正规轴测图或剖轴测。</li>
<li><strong>只有 6 张静态图</strong>：立面图、天花图、材料板、节点都还没有，按“设计成果标准”仍差 4 类成果。</li>
</ul>
<p><small>结论：这一版比第 2 版在“看得懂”上前进了一大步（六个功能区各自成立、光线有区别、材质是真实贴图），但仍<strong>不是客户交付级</strong>。我不把它算通过。</small></p>
</div>

<h2>⑨ 等你确认</h2>
<ol>
<li>六个机位选得对不对？有没有哪个功能区还缺一张（例如洽谈室内景、水吧、卫生间）。</li>
<li>五套光线的差别够不够？现在 C3 是下午斜阳、C4 是傍晚，其余是白天。</li>
<li>展品方向：等协诚的产品资料，还是先按“材料样品”继续深化？</li>
</ol>

<h2>⑩ 文件</h2>
<ul class="files">
<li><a href="02_方案A_平面布置图.svg" target="_blank">02_方案A_平面布置图.svg</a><span>1:100，含相机编号 C0–C5 与视域扇形</span></li>
<li><a href="03_效果图_C0_序厅·接待.png" target="_blank">03_效果图_C0–C5（6 张）</a><span>1400 × 880，Blender 4.2.9 Cycles，110 采样</span></li>
<li><a href="方案A_设计数据.json" target="_blank">方案A_设计数据.json</a><span>分区、墙、家具、展台、洁具、材料、灯、相机（含 eye/target/lens/light）</span></li>
<li><a href="阶段2_方案A.pdf" target="_blank">阶段2_方案A.pdf</a><span>本页导出的 PDF</span></li>
</ul>

<footer>方案 A 第 3 版到此为止，停下等你确认。设计与效果是否成立只由你评价，本页不自评通过。管理配套（PG / NAS / 账号 / 岗位审查 / 备份恢复）本阶段全部冻结。六张图全部本机 Blender 直出，本轮外发图片 0 张、费用 0。</footer>
</div></body></html>"""
    target = OUT / "打开我看.html"
    target.write_text(html, encoding="utf-8")
    print(json.dumps({"page": str(target), "cameras": len(cams), "area_sum": area_sum}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
