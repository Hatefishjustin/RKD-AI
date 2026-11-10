"""Build a printable review page from REAL model-generated design artifacts.

Reads the isolated runtime produced by scripts/verify_real_design.py. It does
not call any model again, does not read the API key, and does not modify the
daily database. Every comparison field comes from persisted model revisions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))

from rkd_mvp.ai_design_geometry import render_svg  # noqa: E402
from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.design_reference import public as reference_public  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402

ORG = "org-local"
STAMP = "2026-11-10"


def main() -> int:
    raw_source = (os.environ.get("RKD_REAL_DESIGN_RUN") or "").strip()
    source = Path(raw_source) if raw_source else None
    if not source:
        runs = sorted((ROOT / "var" / "evidence" / "real-design" / STAMP).glob("run-*"),
                      key=lambda item: item.stat().st_mtime)
        candidates = [run for run in runs
                      if (run / "verification.json").exists()
                      and json.loads((run / "verification.json").read_text(encoding="utf-8")).get("passed")]
        if not candidates:
            print("No passed real-design run found; set RKD_REAL_DESIGN_RUN", flush=True)
            return 2
        source = candidates[-1]
    runtime = source / "runtime"
    verification = json.loads((source / "verification.json").read_text(encoding="utf-8"))
    store = SQLiteStore(runtime / "app.sqlite3")
    files = FileService(runtime / "app.sqlite3", runtime)
    service = ApiService(MVPApp(store), files, runtime_root=runtime)
    try:
        brief_state = service.get_ai_requirement_status(ORG, NINGBO_PROJECT_ID)
        brief = brief_state["item"]["brief"]["brief"]
        option_state = service.get_ai_design_options(ORG, NINGBO_PROJECT_ID)
        options = option_state["item"]["options"]
        technical = service.get_ai_technical_delivery(ORG, NINGBO_PROJECT_ID)["item"]
        candidates = []
        for option in options:
            artifact = next(item for item in option["artifacts"] if item["artifact_kind"] == "layout_svg")
            # Re-draw from the persisted, versioned model with the current
            # drawing program. This never changes the model, the stored
            # artifact bytes or their registered hashes; it only avoids
            # showing an older renderer's overlapping labels in this review.
            svg_bytes = render_svg(option["model"])
            candidates.append({
                "strategy_id": option["strategy"]["strategy_id"],
                "statement": option["strategy"]["statement"],
                "tradeoffs": option["strategy"]["tradeoffs"],
                "circulation": option["model"]["circulation"]["kind"],
                "entrance": option["model"]["boundary"]["entrance"]["side"],
                "zones": [obj["name"] for obj in option["model"]["objects"] if obj["kind"] == "functional_zone"],
                "materials": [item["material_id"] for item in option["model"]["materials"]],
                "paths": len(option["model"]["circulation"]["segments"]),
                "validation": option["validation"]["status"],
                "source_kind": option["source_kind"], "revision_no": option["revision_no"],
                "real_model": option["model"]["generation"]["real_model"],
                "model_id": option["model"]["generation"]["model_id"],
                "prompt_version": option["model"]["generation"]["prompt_version"],
                "svg_sha256": hashlib.sha256(svg_bytes).hexdigest(), "svg_bytes": len(svg_bytes),
                "svg": svg_bytes.decode("utf-8"), "stored_svg_sha256": artifact["sha256"],
                "drawing": "current_rasteriser_redraw_from_persisted_model",
                "cost_unknown": [str(item.get("statement", "")) for item in option["model"]["cost"]["unknown_items"]],
            })
        plan_artifact = next(item for item in technical["artifacts"] if item["artifact_kind"] == "technical_plan_svg")
        _, plan_path = service.get_ai_technical_delivery_artifact(ORG, NINGBO_PROJECT_ID, plan_artifact["artifact_id"])
        plan_svg = plan_path.read_text(encoding="utf-8")
        html = render(verification, brief, candidates, plan_svg, technical, source)
        out_dir = ROOT / "var" / "review" / STAMP
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "real-design-review.html"
        target.write_text(html, encoding="utf-8")
        pdf = generate_pdf(target, out_dir / "real-design-review.pdf")
        result = {"html": str(target), "html_bytes": target.stat().st_size,
                  "html_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                  "pdf": str(pdf) if pdf else None, "source_run": str(source),
                  "candidates": [item["strategy_id"] for item in candidates],
                  "real_model": all(item["real_model"] for item in candidates)}
        (out_dir / "real-design-review.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return 0
    finally:
        store.close()


def generate_pdf(html_path: Path, pdf_path: Path) -> Path | None:
    edge = Path(r"C:\Program Files (x86)\Microsoft\EdgeCore\150.0.4078.65\msedge.exe")
    if not edge.exists():
        return None
    env = {key: value for key, value in os.environ.items()
           if key not in {"HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"}}
    user_data = Path(tempfile.gettempdir()) / f"rkd-real-review-{os.getpid()}"
    command = [str(edge), "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
               "--no-default-browser-check", "--virtual-time-budget=15000", "--no-pdf-header-footer",
               "--no-proxy-server", f"--user-data-dir={user_data}",
               f"--print-to-pdf={pdf_path}", html_path.as_uri()]
    try:
        process = subprocess.run(command, capture_output=True, timeout=180, env=env,
                                 text=True, errors="replace")
        return pdf_path if process.returncode == 0 and pdf_path.exists() and pdf_path.stat().st_size > 10000 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def render(verification: dict, brief: dict, candidates: list[dict], plan_svg: str,
           technical: dict, source: Path) -> str:
    if not candidates:
        raise RuntimeError("no real-model candidates available")
    first, second = (candidates + [candidates[0]])[:2]

    def row(label, left, right):
        return f"<tr><th>{escape(label)}</th><td>{escape(str(left))}</td><td>{escape(str(right))}</td></tr>"

    intent = "".join(f"<li>{escape(str(item.get('statement', '')))}</li>" for item in brief.get("design_intent", []))
    requirements = "".join(f"<li>{escape(str(item.get('statement', '')))}</li>" for item in brief.get("requirements", []))
    questions = "".join(f"<li>{escape(str(item.get('statement', '')))}<small>{escape(str(item.get('reason', '')))}</small></li>"
                        for item in brief.get("open_questions", []))
    comparison = "".join([
        row("策略编号", first["strategy_id"], second["strategy_id"]),
        row("动线形态", first["circulation"], second["circulation"]),
        row("入口侧", first["entrance"], second["entrance"]),
        row("动线区段数", first["paths"], second["paths"]),
        row("功能区", "、".join(first["zones"]), "、".join(second["zones"])),
        row("材料意向", "、".join(first["materials"]), "、".join(second["materials"])),
        row("设计取舍", "；".join(first["tradeoffs"][:3]), "；".join(second["tradeoffs"][:3])),
        row("成本缺项", "；".join(first["cost_unknown"][:4]), "；".join(second["cost_unknown"][:4])),
        row("几何硬检查", first["validation"], second["validation"]),
        row("版本 / 来源", f"v{first['revision_no']} · {first['source_kind']}",
            f"v{second['revision_no']} · {second['source_kind']}"),
        row("来源", f"真实模型 {first['model_id']}", f"真实模型 {second['model_id']}"),
        row("提示版本", first["prompt_version"], second["prompt_version"]),
        row("图面 SHA-256（前 16 位）", first["svg_sha256"][:16], second["svg_sha256"][:16]),
    ])
    runs = verification.get("model_runs", {})
    revision = verification.get("steps", {}).get("feedback_revision", {})
    diff_text = "；".join(f"{item['object_id']} {item['field']}" for item in revision.get("diff", [])[:8]) or "无"
    generated = datetime.now(timezone.utc).isoformat()
    reference = reference_public()
    source_titles = "；".join(escape(f"{item['title']}（{item['kind']}）") for item in reference["sources"][:6])
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>真实 AI 设计候选评审</title>
<style>
@page{{size:A4;margin:12mm}}
*{{box-sizing:border-box}}
body{{font:13px/1.62 "Microsoft YaHei","PingFang SC",sans-serif;color:#22303f;max-width:1080px;margin:28px auto;padding:0 22px;background:#fff}}
h1{{font-size:22px;margin:0 0 6px}} h2{{font-size:16px;margin:23px 0 9px;padding-bottom:5px;border-bottom:1px solid #d9e0e6}}
h3{{font-size:13px;margin:13px 0 6px;color:#43536a}} p{{margin:7px 0}} small{{color:#6b7a8a;font-size:11px;display:block}}
code{{font:11px Consolas,monospace;background:#f2f5f7;padding:1px 4px;overflow-wrap:anywhere}}
.banner{{border-left:3px solid #2f6f52;background:#f2f8f4;padding:9px 13px;margin:12px 0 18px}}
table{{border-collapse:collapse;width:100%;font-size:11.5px;margin:8px 0 14px;page-break-inside:auto}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #e2e8ec;vertical-align:top;overflow-wrap:anywhere}}
thead{{display:table-header-group}} tr{{page-break-inside:avoid}} th{{background:#f1f4f6;color:#3a4a5c;font-weight:600}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.card{{border:1px solid #dfe6eb;border-radius:3px;padding:10px;page-break-inside:avoid}}
.card svg,.plan svg{{width:100%;height:auto;max-height:330px;display:block}}
ul{{margin:6px 0 12px;padding-left:18px}} li{{margin-bottom:5px}}
.feedback{{border:1px solid #cfd9e1;padding:10px 13px;background:#fafcfe}}
.decision{{border:1px solid #cfd9e1;padding:10px 13px;margin:8px 0}}
footer{{margin-top:24px;padding-top:10px;border-top:1px solid #d9e0e6;color:#6b7a8a;font-size:10.5px}}
@media print{{body{{font-size:10.6px;margin:0;max-width:none}} h2{{page-break-after:avoid}} .card svg,.plan svg{{max-height:250px}} .grid{{gap:8px}}}}
@media (max-width:760px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>真实 AI 设计候选评审材料</h1>
<p><small>生成时间 {escape(generated)} · 模型 {escape(str(verification.get('model')))} · 通道 {escape(str(verification.get('base_url')))} · 宁波协诚展厅受限场景</small></p>
<div class="banner"><strong>这是一版返工方案。</strong>您对上一版两个真实 AI 候选的评价是「两个都完全不可以」，并要求先去参考网络上真实的平面图、学习真实设计师怎么组织布局。本版据此重做：下面两张图面、设计概念、叙事序列、功能层级、家具与片墙仍<strong>由真实语言模型完成</strong>，程序只做几何硬检查、落模、工程量、图纸与责任边界。真实调用留痕（模型名、提示版本、用量、请求 ID）不变；设计质量仍需您评价，专业可施工性仍需相应责任人复核。</div>

<h2>0. 为什么重做：您的反馈与真实平面图研究</h2>
<p><strong>您的反馈（如实记录，作为 AD08 负例）：</strong>「两个都完全不可以；我需要你去参考网络上真实的平面图先学习真实的设计师怎么设计布局的」。这不是「待调整」，是明确否决并要求返工，不由模型自评或自动测试代签。</p>
<h3>实际看过的真实平面图</h3>
<ul>
<li>金堂奖「往来无白」300㎡ 玻璃制品展厅<strong>一层 / 二层平面布局图</strong>：主入口凹入弧形门斗与橱窗、服务前台配吧椅、两间画了真实桌椅的洽谈室、茶水间 / 储藏 / 办公室、片墙与弧形展具、绿植、楼梯「上 19 步」、标高 +0.160、粗黑墙体与中英文图注。</li>
<li>设计本「重构—宽驰大家居新展厅」560㎡ 平面布置图 / 轴测图说明：入口展示区 / 中心洽谈区 / 产品陈列区三区、圆厅与方厅、景观内庭、隔断形成独立小场景，明确反对「大仓库式平铺陈列」。</li>
<li>600㎡ 生物科技展厅「一轴四区」、MiSUMi 单向叙事序厅→数字→实物→工艺→文化走廊→洽谈、南京博物院二期用中庭打断冗长流线等公开案例。</li>
</ul>
<h3>提炼并写进模型提示的设计方法（{escape(reference['reference_version'])}，{escape(reference['research_date'])}）</h3>
<ol>
<li><strong>先叙事再拓扑，最后才落几何</strong>：一句话主题 → 内容序列 → 串联 / 环形 / 放射 / 中心英雄 / 混合原型 → 平面；不再「先画通道再塞分区」。</li>
<li><strong>功能有层级</strong>：入口门斗与前厅形象 → 主展示（中岛、展墙、视觉焦点）→ 深度转化（洽谈、选样、茶水）→ 收束出口，另有服务台、储藏后勤与缓冲留白；不能只有三个并排矩形。</li>
<li><strong>节奏</strong>：开场在入口五步内、高潮在动线约三分之二处、收束近出口；密—疏—密，核心展区之间留缓冲。</li>
<li><strong>真实元素与图纸表达</strong>：形象片墙、服务前台与吧椅、洽谈桌椅、中岛展台、绿植、储藏茶水；粗实线墙体、门洞与门扇弧线、尺寸标注、中英文图注、图例与标题栏。</li>
<li><strong>尺度与校验边界</strong>：主通道行业常见 ≥2.0m（WW/T 0089-2018 规范底线 2.4m）、次通道 ≥1.2m；组合式布局优于复杂迂回（FOAR 2025 视域图研究）。这些仅作方法参考，<strong>不宣称消防、疏散或无障碍合规</strong>。</li>
</ol>
<p><small>参考来源（{reference['source_count']} 项，含规范、教材、公开平面图、行业指南与同行评议论文）：{source_titles} 等。仅学习布局方法，不复制任何图纸，下载的公开图片只保存在本地证据目录，不随交付物分发。</small></p>

<h2>1. 真实模型理解的需求与设计意图</h2>
<h3>结构化需求</h3><ul>{requirements}</ul>
<h3>设计意图</h3><ul>{intent}</ul>
<h3>模型提出的最少补问</h3><ul>{questions or '<li>无</li>'}</ul>

<h2>2. 两个由真实模型设计的候选（真实 SVG 图面）</h2>
<div class="grid">
<div class="card"><h3>候选 A · {escape(first['strategy_id'])}{' · 已按反馈修订' if first['source_kind'] == 'human_feedback' else ''}</h3>{first['svg']}<small>图面 SHA-256 {escape(first['svg_sha256'])} · {first['svg_bytes']} 字节 · v{first['revision_no']}</small></div>
<div class="card"><h3>候选 B · {escape(second['strategy_id'])}{' · 已按反馈修订' if second['source_kind'] == 'human_feedback' else ''}</h3>{second['svg']}<small>图面 SHA-256 {escape(second['svg_sha256'])} · {second['svg_bytes']} 字节 · v{second['revision_no']}</small></div>
</div>
<p><small>工作台显示每个候选的最新修订：反馈后模型把原方案 <code>branch-salon</code> 重命名为 <code>open-loop</code>，因此这里候选 A 的版本与端到端验证报告中的初始策略名不同；两者均为同一真实模型链的产物，版本与来源见下表。</small></p>
<table><thead><tr><th>对比项</th><th>候选 A</th><th>候选 B</th></tr></thead><tbody>{comparison}</tbody></table>
<h3>设计概念与依据（模型原文摘要）</h3>
<p><strong>A：</strong>{escape(first['statement'][:700])}</p>
<p><strong>B：</strong>{escape(second['statement'][:700])}</p>
<p><small>几何硬检查只验证边界、避障、连通、入口、瓶颈、面积与稳定 ID，不代表消防、疏散、无障碍或规范合规。</small></p>

<h2>3. 一次真实自然语言反馈后的修订</h2>
<p>反馈原文：<strong>{escape(str(verification.get('feedback')))}</strong></p>
<p>模型给出的变更意图：{escape(', '.join(revision.get('parsed_intents', [])) or '见对象 diff')}；实际对象/关系差异：{escape(diff_text)}，共 {len(revision.get('diff', []))} 项。入口与展陈锁定条件由程序强制保护，锁定冲突会单独记录，不会被静默覆盖。</p>

<h2>4. 采用后的同源技术交付草稿</h2>
<div class="plan card"><h3>技术平面（标注对象 ID 与边界尺寸）· 非施工图</h3>{plan_svg}</div>
<p>同源深化包与技术成果共 {len(technical['artifacts'])} 类文件；专业复核状态 <code>pending</code>，正式报价与施工发布均为 false。技术包不是施工图，材料规格、构造做法、机电消防接口与现场实测仍为未知。</p>

<h2>5. 真实调用留痕与边界</h2>
<p>本次端到端调用记录：设计模型运行 <strong>{runs.get('count', 0)}</strong> 条，累计输入 <strong>{runs.get('total_input_tokens', 0)}</strong> tokens、输出 <strong>{runs.get('total_output_tokens', 0)}</strong> tokens；金额保持 <code>unknown</code>，超时请求保留 <code>pending_reconciliation</code>。密钥只在服务端进程环境变量中，未写入任何文件、数据库、日志、前端或 Git；项目原件、解析文本、项目决策与预算默认<strong>不外发</strong>，模型只收到当前自然语言输入、明确标记的测试边界与必要提示。</p>
<p><small>证据：{escape(str(source / 'verification.json'))}；模型运行台账同目录 design-model-runs.jsonl。</small></p>

<h2>6. 请您给出具体反馈（AD08）</h2>
<div class="feedback"><p>请针对<strong>上面看得见的图面</strong>回答，不需要操作代码：</p><ol>
<li><strong>需求响应：</strong>哪一张更接近「开放展示 + 保留独立洽谈 + 左侧入口 + 暖木色」？哪些地方没有响应？</li>
<li><strong>空间组织：</strong>入口、动线、展陈与洽谈区的关系是否可用？希望环游还是分支，隔断多还是少？</li>
<li><strong>材料氛围：</strong>暖木 / 中性的分区意向是否合适？有没有必须避免的材料或色调？</li>
<li><strong>可继续深化：</strong>这个方向是否值得继续做材料做法、节点和量价？若否，请指出应返工的具体对象。</li>
</ol><p><small>认可、待调整、不认可将分别记录，不由模型自评或自动测试代签。</small></p></div>

<h2>7. 仍需您决定的两件事</h2>
<div class="decision"><h3>① 费用与调用上限</h3><p>通道已接通并跑通联调。建议继续按「一次需求理解 + 一次双候选 + 一次反馈修订」的小额批次推进，每次记录真实用量；需要扩大到更多方案、更多轮反馈或多项目时请先给一个额度或次数上限。未配置、超时、限额、畸形输出都会留下可见失败记录，不回退到合成结果，也不无限重试收费。</p></div>
<div class="decision"><h3>② 项目资料外发范围</h3><p>当前 <code>RKD_AI_EXTERNAL_CONTEXT=false</code>：不外发项目决策、原件元数据、本地解析文本、预算与现场照片。若您希望模型参考具体项目资料，请明确指定允许的类别（例如仅允许结构化任务书文本、或仅允许某几份已解析片段）；商业原件与现场照片默认仍不外发。</p></div>
<p><small>税率、合同总价、审核人姓名与服务器授权都不需要重复提供。</small></p>

<footer>本页由 scripts/build_real_design_review.py 从真实模型运行留下的隔离成果生成，未再次调用模型、未读取密钥、未改动日常运行库或 NAS。AD01—AD08 按固定验收逐项判定，工程回归不代替用户设计评价与专业签核。</footer>
</body></html>'''


if __name__ == "__main__":
    raise SystemExit(main())
