"""Build a printable, self-contained review page from REAL generated artifacts.

This script runs the whole local chain in an isolated temporary database, reads
the actual SVG bytes and structured option/technical data, and writes one HTML
review page plus the source SVGs and a machine-readable data snapshot. It does
not hand-write any design description; every comparison field comes from the
persisted revisions. It never calls a paid model or touches the daily database.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))

from rkd_mvp.ai_design_option_provider import DesignOptionConfig, build_design_option_provider  # noqa: E402
from rkd_mvp.ai_design_option_repository import SQLiteAIDesignOptionRepository  # noqa: E402
from rkd_mvp.ai_design_option_service import AIDesignOptionService  # noqa: E402
from rkd_mvp.ai_development_repository import SQLiteAIDevelopmentRepository  # noqa: E402
from rkd_mvp.ai_development_service import AIDevelopmentService  # noqa: E402
from rkd_mvp.ai_model_provider import AIProviderConfig, build_provider  # noqa: E402
from rkd_mvp.ai_requirement_repository import SQLiteAIRequirementRepository  # noqa: E402
from rkd_mvp.ai_requirement_service import AIRequirementService  # noqa: E402
from rkd_mvp.api_service import ApiService  # noqa: E402
from rkd_mvp.engine import MVPApp  # noqa: E402
from rkd_mvp.file_service import FileService, NINGBO_PROJECT_ID  # noqa: E402
from rkd_mvp.professional_delivery import (AISourceExtractionService, AITechnicalDeliveryService,  # noqa: E402
                                           SQLiteAIProfessionalDeliveryRepository)
from rkd_mvp.requirement_service import RequirementService  # noqa: E402
from rkd_mvp.sqlite_store import SQLiteStore  # noqa: E402

ORG = "org-local"
FIXTURE_ROOT = ROOT / "fixtures" / "ningbo-xiecheng" / "2026-09"
STAMP = "2026-11-08"
OUT_DIR = ROOT / "var" / "review" / STAMP
EVIDENCE_DIR = ROOT / "var" / "evidence" / "professional-delivery" / STAMP
NATURAL_LANGUAGE = "开放交流与展示，入口在左侧，暖木色，保留独立洽谈"


def requirement_config() -> AIProviderConfig:
    return AIProviderConfig(kind="synthetic", name="本地合成测试通道（非真实 AI）", model_id=None,
                            base_url=None, api_key_present=False, adapter_version="rkd-model-provider.v1",
                            prompt_version="requirement-understanding.zh-CN.v1",
                            schema_version="rkd-ai-design-brief.v1", max_input_chars=8000,
                            max_output_tokens=2000, timeout_seconds=20, external_context_allowed=False,
                            real_model=False, configuration_errors=[])


def option_config() -> DesignOptionConfig:
    return DesignOptionConfig(kind="synthetic", name="本地合成设计通道（非真实 AI）",
                              adapter_version="rkd-design-option-provider.v1",
                              prompt_version="design-option-strategy.zh-CN.v1",
                              schema_version="rkd-ai-design-option.v1", max_candidates=2,
                              real_model=False, configuration_errors=[])


def text(value) -> str:
    if value is None:
        return "未知"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rkd-review-") as temporary:
        root = Path(temporary)
        db = root / "app.sqlite3"
        store = SQLiteStore(db)
        files = FileService(db, root)
        requirements = RequirementService(db)
        delivery_repository = SQLiteAIProfessionalDeliveryRepository(db)
        extraction = AISourceExtractionService(delivery_repository, files)
        brief_service = AIRequirementService(
            SQLiteAIRequirementRepository(db), requirements, config=requirement_config(),
            provider_factory=lambda config: build_provider(config), extraction_service=extraction)
        options = AIDesignOptionService(
            SQLiteAIDesignOptionRepository(db),
            lambda org, project: brief_service.status(org, project)["item"],
            lambda org, project: {"width": "12", "length": "8",
                                  "boundary_source": "test_parameters_not_site_verified", "obstacles": []},
            root, config=option_config(), provider=build_design_option_provider(option_config()))
        development = AIDevelopmentService(SQLiteAIDevelopmentRepository(db), options, root)
        technical = AITechnicalDeliveryService(delivery_repository, development, extraction, root)
        service = ApiService(MVPApp(store), files, requirement_service=requirements,
                             ai_requirement_service=brief_service, ai_design_option_service=options,
                             ai_development_service=development,
                             ai_source_extraction_service=extraction,
                             ai_technical_delivery_service=technical, runtime_root=root)
        files.seed_ningbo(service, FIXTURE_ROOT)

        brief_job = service.submit_ai_requirement(ORG, NINGBO_PROJECT_ID, "review",
                                                  {"natural_language": NATURAL_LANGUAGE},
                                                  "review-brief-0001")["item"]
        brief_service.wait_for_job(ORG, NINGBO_PROJECT_ID, brief_job["job_id"])
        brief = service.get_ai_requirement_status(ORG, NINGBO_PROJECT_ID)["item"]["brief"]["brief"]

        option_set = service.submit_ai_design_options(ORG, NINGBO_PROJECT_ID, "review", {},
                                                      "review-options-0001")["item"]
        options.wait_for_set(ORG, NINGBO_PROJECT_ID, option_set["set_id"])
        option_state = service.get_ai_design_options(ORG, NINGBO_PROJECT_ID)
        revisions = option_state["item"]["options"]

        candidates = []
        for index, revision in enumerate(revisions):
            artifact = next(item for item in revision["artifacts"] if item["artifact_kind"] == "layout_svg")
            _, path = service.get_ai_design_option_artifact(ORG, NINGBO_PROJECT_ID, artifact["artifact_id"])
            svg = path.read_text(encoding="utf-8")
            (OUT_DIR / f"candidate-{chr(97 + index)}.svg").write_text(svg, encoding="utf-8")
            candidates.append({
                "option_id": revision["option_id"],
                "option_revision_id": revision["option_revision_id"],
                "strategy": revision.get("strategy", {}),
                "structure_signature": revision.get("structure_signature", {}),
                "materials": revision.get("materials", []),
                "cost": revision.get("cost", {}),
                "validation": revision.get("validation", {}),
                "objects": revision.get("objects", []),
                "boundary": revision.get("boundary", {}),
                "circulation": revision.get("circulation", {}),
                "svg_sha256": artifact["sha256"], "svg_size_bytes": artifact["size_bytes"],
                "svg": svg,
            })

        chosen = next(item for item in revisions if item.get("strategy", {}).get("strategy_id") == "open-loop")
        service.adopt_ai_design_option(ORG, NINGBO_PROJECT_ID, "review",
                                       {"option_id": chosen["option_id"], "expected_revision": 1,
                                        "expected_version": 0})
        development_job = service.submit_ai_development(ORG, NINGBO_PROJECT_ID, "review",
                                                        {"expected_version": 1, "settings": {}},
                                                        "review-development-0001")["item"]
        development.wait_for_job(ORG, NINGBO_PROJECT_ID, development_job["job_id"])
        development_state = service.get_ai_development(ORG, NINGBO_PROJECT_ID)
        service.submit_ai_technical_delivery(ORG, NINGBO_PROJECT_ID, "review", {},
                                             "review-technical-0001")
        technical_state = service.get_ai_technical_delivery(ORG, NINGBO_PROJECT_ID)
        current = technical_state["item"]
        plan_artifact = next(item for item in current["artifacts"]
                             if item["artifact_kind"] == "technical_plan_svg")
        _, plan_path = service.get_ai_technical_delivery_artifact(
            ORG, NINGBO_PROJECT_ID, plan_artifact["artifact_id"])
        plan_svg = plan_path.read_text(encoding="utf-8")
        (OUT_DIR / "technical-plan.svg").write_text(plan_svg, encoding="utf-8")
        handover = current["delivery"]["handover"]

        generated_at = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "schema_version": "rkd-design-review.v1",
            "generated_at": generated_at,
            "input_natural_language": NATURAL_LANGUAGE,
            "source": "isolated local synthetic chain; not a real paid model call",
            "brief": {"requirements": brief.get("requirements", []),
                      "design_intent": brief.get("design_intent", []),
                      "conflicts": brief.get("conflicts", []),
                      "open_questions": brief.get("open_questions", []),
                      "source_status": brief.get("project_context", {}).get("source_status")},
            "candidates": [{key: value for key, value in item.items() if key != "svg"} for item in candidates],
            "development_revision": development_state["item"]["revision"]["production_revision_id"],
            "technical_delivery": {
                "delivery_id": current["delivery"]["delivery_id"],
                "input_hash": current["delivery"]["input_hash"],
                "artifacts": [{key: value for key, value in artifact.items()
                               if key in {"artifact_kind", "filename", "sha256", "size_bytes"}}
                              for artifact in current["artifacts"]],
                "supported_scope": handover["supported_scope"],
                "unsupported_scope": handover["unsupported_scope"],
                "review_tasks": handover["review_tasks"],
            },
            "boundaries": ["合成适配器不是真实 AI", "AD01—AD08 仍为 0/8", "候选与采用草稿不等于正式批准",
                           "技术包不是施工图、正式报价或采购订单", "项目原件内容仅本地解析，未外发"],
        }
        (EVIDENCE_DIR / "review-data.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        html = render(snapshot, candidates, handover, plan_svg, generated_at)
        target = OUT_DIR / "design-review-2026-11-08.html"
        target.write_text(html, encoding="utf-8")
        print(json.dumps({"html": str(target), "bytes": target.stat().st_size,
                          "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                          "candidates": len(candidates),
                          "technical_artifacts": len(current["artifacts"])}, ensure_ascii=False, indent=2))
        brief_service.wait_for_idle()
        options.wait_for_idle()
        development.wait_for_idle()
        store.close()
    return 0


def render(snapshot, candidates, handover, plan_svg, generated_at) -> str:
    def row(label, left, right):
        return f"<tr><th>{escape(label)}</th><td>{escape(text(left))}</td><td>{escape(text(right))}</td></tr>"

    first, second = (candidates + [candidates[0]])[:2]

    def known_cost(item):
        parts = [f"{entry.get('value', '未知')} {entry.get('unit', '')}（{entry.get('item_id', '')}）"
                 for entry in item["cost"].get("known_items", [])]
        return "；".join(parts) if parts else "无"

    def missing_cost(item):
        return "；".join(entry.get("statement", "") for entry in item["cost"].get("unknown_items", [])) or "无"

    def count(item, kind):
        return sum(1 for obj in item["objects"] if obj.get("kind") == kind)

    def material_text(item):
        return "、".join(str(entry.get("name") or entry.get("material_id")) for entry in item["materials"]) or "未知"

    intent_lines = "".join(
        f"<li>{escape(text(item.get('statement')))}<small>来源：{escape(text(item.get('origin_kind')))} · 已知状态：{escape(text(item.get('known_status')))}</small></li>"
        for item in snapshot["brief"]["design_intent"])
    conflict_lines = "".join(
        f"<li>{escape(text(item.get('statement')))}<small>处理：{escape(text(item.get('resolution')))}</small></li>"
        for item in snapshot["brief"]["conflicts"])
    question_lines = "".join(
        f"<li>{escape(text(item.get('statement')))}<small>{escape(text(item.get('reason')))}</small></li>"
        for item in snapshot["brief"]["open_questions"])
    comparison = "".join([
        row("策略编号", first["strategy"].get("strategy_id"), second["strategy"].get("strategy_id")),
        row("设计意图", first["strategy"].get("statement"), second["strategy"].get("statement")),
        row("设计取舍", "；".join(first["strategy"].get("tradeoffs", [])),
            "；".join(second["strategy"].get("tradeoffs", []))),
        row("入口侧", first["structure_signature"].get("entrance_side"),
            second["structure_signature"].get("entrance_side")),
        row("动线形态", first["structure_signature"].get("path_kind"),
            second["structure_signature"].get("path_kind")),
        row("通路区段数", first["structure_signature"].get("segment_count"),
            second["structure_signature"].get("segment_count")),
        row("边界", f"{first['boundary'].get('width')} × {first['boundary'].get('length')} m（未现场核验）",
            f"{second['boundary'].get('width')} × {second['boundary'].get('length')} m（未现场核验）"),
        row("功能区 / 展陈 / 隔断对象数",
            f"{count(first, 'functional_zone')} / {count(first, 'display_object')} / {count(first, 'partition')}",
            f"{count(second, 'functional_zone')} / {count(second, 'display_object')} / {count(second, 'partition')}"),
        row("材料意向", material_text(first), material_text(second)),
        row("成本已知项", known_cost(first), known_cost(second)),
        row("成本缺项", missing_cost(first), missing_cost(second)),
        row("硬检查", first["validation"].get("status"), second["validation"].get("status")),
        row("图面 SHA-256（前 16 位）", first["svg_sha256"][:16], second["svg_sha256"][:16]),
    ])
    supported = "".join(f"<li><strong>{escape(item['statement'])}</strong> · {escape(item['status'])} · {escape(item['basis'])}</li>"
                        for item in handover["supported_scope"])
    unsupported = "".join(f"<li><strong>{escape(item['statement'])}</strong> · {escape(item['reason'])}</li>"
                          for item in handover["unsupported_scope"])
    reviews = "".join(f"<tr><td>{escape(item['role'])}</td><td>{escape(item['statement'])}</td><td>{escape(item['status'])}</td></tr>"
                      for item in handover["review_tasks"])
    artifacts = "".join(
        f"<tr><td>{escape(item['artifact_kind'])}</td><td>{escape(item['filename'])}</td>"
        f"<td>{item['size_bytes']}</td><td><code>{escape(item['sha256'][:16])}…</code></td></tr>"
        for item in snapshot["technical_delivery"]["artifacts"])
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>设计候选与技术交付评审</title>
<style>
@page{{size:A4;margin:12mm}}
*{{box-sizing:border-box}}
body{{font:13px/1.6 "Microsoft YaHei","PingFang SC",sans-serif;color:#22303f;max-width:1080px;margin:28px auto;padding:0 22px;background:#fff}}
h1{{font-size:22px;margin:0 0 6px}} h2{{font-size:16px;margin:24px 0 9px;padding-bottom:5px;border-bottom:1px solid #d9e0e6}}
h3{{font-size:13px;margin:14px 0 6px;color:#43536a}}
p{{margin:7px 0}} small{{color:#6b7a8a;font-size:11px;display:block}}
code{{font:11px Consolas,monospace;background:#f2f5f7;padding:1px 4px;border-radius:2px;overflow-wrap:anywhere}}
.banner{{border-left:3px solid #b0762e;background:#fbf6ec;padding:9px 13px;margin:12px 0 18px}}
.banner strong{{color:#7a5420}}
table{{border-collapse:collapse;width:100%;font-size:11.5px;margin:8px 0 14px;page-break-inside:auto}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #e2e8ec;vertical-align:top;overflow-wrap:anywhere}}
thead{{display:table-header-group}} tr{{page-break-inside:avoid}}
th{{background:#f1f4f6;color:#3a4a5c;font-weight:600}} td{{color:#33465a}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.card{{border:1px solid #dfe6eb;border-radius:3px;padding:10px;page-break-inside:avoid}}
.card svg,.plan svg{{width:100%;height:auto;max-height:330px;display:block}}
.card h3{{margin-top:0}}
ul{{margin:6px 0 12px;padding-left:18px}} li{{margin-bottom:5px}}
.feedback{{border:1px solid #cfd9e1;padding:10px 13px;background:#fafcfe}}
.feedback ol{{padding-left:20px;margin:6px 0}}
.decision{{border:1px solid #cfd9e1;padding:10px 13px;margin:8px 0}}
.decision h3{{margin:0 0 4px}}
footer{{margin-top:26px;padding-top:10px;border-top:1px solid #d9e0e6;color:#6b7a8a;font-size:10.5px}}
@media print{{body{{font-size:10.6px;margin:0;max-width:none}} .noprint{{display:none}} h2{{page-break-after:avoid}} .grid{{gap:8px}} .card svg,.plan svg{{max-height:250px}}}}
</style></head><body>
<h1>设计候选与技术交付评审材料</h1>
<p><small>生成时间 {escape(generated_at)} · 宁波协诚展厅受限场景 · 内部草稿</small></p>
<div class="banner"><strong>先说清楚边界：</strong>下面两张图面来自工作台真实生成的候选文件，但设计策略仍由<strong>明确标记的非 AI 本地合成适配器</strong>产生，不是付费模型输出；AD01—AD08 仍为 0/8。候选、采用草稿、正式批准、施工发布和采购订单是不同状态。本材料用于收集您对具体图面的评价，不代表设计质量或专业可施工性已通过。</div>

<h2>1. 本次输入与任务书</h2>
<p>自然语言需求：<strong>{escape(snapshot['input_natural_language'])}</strong></p>
<p><small>来源状态：{escape(text(snapshot['brief']['source_status']))} · 边界 12 × 8 m 为测试参数，未经现场核验</small></p>
<p><small>本次演示没有对项目原件执行 01c 解析，因此来源内容为「已选但无可用文本」。工作台「资料与技术交付」页可逐个解析原件并查看可定位片段；解析结果仅本地可查，未获明确批准不外发。任务书下列补问文字来自本地合成任务书的真实输出，其「没有读取原件内容」描述的是本次演示输入，不代表系统能力缺失。</small></p>
<h3>结构化设计意图</h3><ul>{intent_lines}</ul>
<h3>已识别冲突</h3><ul>{conflict_lines or '<li>无</li>'}</ul>
<h3>最少补问</h3><ul>{question_lines}</ul>

<h2>2. 两个可计算候选（真实 SVG 图面）</h2>
<div class="grid">
<div class="card"><h3>候选 A · {escape(text(first['strategy'].get('strategy_id')))}</h3>{first['svg']}<small>SHA-256 {escape(first['svg_sha256'])} · {first['svg_size_bytes']} 字节</small></div>
<div class="card"><h3>候选 B · {escape(text(second['strategy'].get('strategy_id')))}</h3>{second['svg']}<small>SHA-256 {escape(second['svg_sha256'])} · {second['svg_size_bytes']} 字节</small></div>
</div>
<table><thead><tr><th>对比项</th><th>候选 A</th><th>候选 B</th></tr></thead><tbody>{comparison}</tbody></table>
<p><small>结构签名与对象来自版本化候选模型；硬检查只验证几何约束，不代表规范合规。已知成本与缺项分开列出，未给出单价的对象不补 0。</small></p>

<h2>3. 采用后的同源技术交付草稿</h2>
<div class="plan card"><h3>技术平面（标注对象 ID 与边界尺寸）· 非施工图</h3>{plan_svg}</div>
<h3>本包已支持</h3><ul>{supported}</ul>
<h3>明确未支持 / 保持未知</h3><ul>{unsupported}</ul>
<h3>成果文件（下载时再次校验字节与 SHA-256）</h3>
<table><thead><tr><th>类型</th><th>文件名</th><th>字节</th><th>SHA-256</th></tr></thead><tbody>{artifacts}</tbody></table>
<h3>专业复核待办（程序不代签）</h3>
<table><thead><tr><th>责任角色</th><th>复核内容</th><th>状态</th></tr></thead><tbody>{reviews}</tbody></table>

<h2>4. 请您给出具体反馈（对应 AD08）</h2>
<div class="feedback"><p>请针对<strong>上面看得见的图面</strong>回答，不需要操作代码：</p><ol>
<li><strong>需求响应：</strong>哪一张更接近「开放交流 + 保留独立洽谈 + 左侧入口 + 暖木色」？哪些地方没有响应？</li>
<li><strong>空间组织：</strong>入口、动线、展陈与洽谈区的关系是否可用？希望环形还是支状，隔断多还是少？</li>
<li><strong>材料氛围：</strong>暖木 / 冷灰 / 中性的分区意向是否合适？有没有必须避免的材料或色调？</li>
<li><strong>可继续深化：</strong>这个方向是否值得继续做材料做法、节点和量价？若否，请指出应返工的具体对象。</li>
</ol><p><small>认可、待调整、不认可将分别记录，不由模型自评或自动测试代签。</small></p></div>

<h2>5. 真实模型联调需要您决定的三件事</h2>
<div class="decision"><h3>① 使用哪个模型服务</h3><p>现有通道已支持 OpenAI 兼容接口，服务端用 <code>RKD_AI_PROVIDER=openai-compatible</code>、<code>RKD_AI_BASE_URL</code>、<code>RKD_AI_MODEL</code>、<code>RKD_AI_API_KEY</code> 配置。密钥只放在服务端环境变量，不进数据库、日志、前端或 Git。也可以用您已批准的自建代理地址与模型标识，不需要改造代码。</p></div>
<div class="decision"><h3>② 费用与调用上限</h3><p>建议先设小额度联调（例如单次需求理解 + 一次两候选生成 + 一次反馈修订），记录真实用量与费用后再决定扩大。未配置、超时、限额、畸形输出都会留下可见失败记录，不会退回规则结果冒充 AI，也不会无限重试收费。</p></div>
<div class="decision"><h3>③ 项目资料外发范围</h3><p>默认 <code>RKD_AI_EXTERNAL_CONTEXT=false</code>：真实模型只接收当前输入的自然语言与必要提示，<strong>不外发项目决策、原件元数据或新解析的原件文本</strong>。本批新增的原件内容解析结果仅本地可查。若要让模型参考项目资料，需要您明确指定允许的资料类别；商业原件与现场照片默认不外发。</p></div>
<p><small>这三项不需要现在就补齐资料或税率；只要确定通道与范围，即可按 AD01—AD07 逐项留证，再结合您的图面反馈判定 AD08。</small></p>

<footer>数据快照：var/evidence/professional-delivery/{STAMP}/review-data.json · 图面原件：var/review/{STAMP}/candidate-a.svg、candidate-b.svg、technical-plan.svg · 技术包：{escape(snapshot['technical_delivery']['delivery_id'])} · 输入哈希 {escape(snapshot['technical_delivery']['input_hash'])}<br>本页由 scripts/build_design_review.py 从隔离运行的真实成果生成；未改动日常运行库、NAS 或旧成果。</footer>
</body></html>'''


if __name__ == "__main__":
    raise SystemExit(main())
