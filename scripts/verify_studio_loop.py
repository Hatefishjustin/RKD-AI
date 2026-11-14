"""Plumbing test for the A1 loop: LOCAL MODEL STUB, real store, real flow.

This proves the ENGINEERING machinery (contract enforcement, geometry,
tasks, discussion, artifacts, review, whitelisted patch revision, gate,
version chain, feedback) works end to end WITHOUT pretending to be a real
model run. Every model answer here comes from arc_first_batch_stub.py and is
explicitly labelled as a local stub. 0 external calls, 0 keys, 0 cost.

The previous version of this test used hand-rolled plans that violated the
contract (469 sqm outer frame used as area table total, missing roles,
furniture without catalog lookup). After ARC-01 those plans are correctly
REJECTED, so the stub was replaced with contract-compliant data. Validation
was NOT relaxed to make this pass.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))
sys.path.insert(0, str(ROOT / "scripts"))

from arc_first_batch_stub import (  # noqa: E402
    SITE, valid_proposal, review_issues, revision_payload, as_json,
)
from rkd_mvp.studio import orchestrator, vision  # noqa: E402
from rkd_mvp.studio.llm import Usage  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402

FAKE_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 32 + b"\xff\xd9"


class FakeClient:
    """Explicitly-labelled LOCAL MODEL STUB. No network, no key, no cost."""

    def __init__(self, *args, **kwargs) -> None:
        self.usage = Usage()
        self.config = type("C", (), {"model": "local-model-stub", "run_token_limit": 600_000,
                                     "project_token_limit": 2_000_000, "configured": True})()

    def chat(self, messages, tools=None, temperature=0.6, max_tokens=3000, json_only=False):
        system = messages[0]["content"]
        last = messages[-1]["content"]
        self.usage.add(1200, 400)
        if "项目经理" in system:
            text = "这一轮先核实设计输入与已知缺口，出两个拓扑不同的空间候选，评审后改一版。交付物是两份候选和一份修订；做完等老板选。"
        elif "需求分析" in system:
            text = as_json({"goal": "做一个能带客户看样品、也能坐下来谈的展厅",
                            "must_have": ["品牌第一眼", "产品序列", "重点展台"],
                            "site_facts": ["26.17×17.92m，层高 3m", "楼梯与卫生间保留"],
                            "budget": "60 万含税",
                            "inferences": ["推断：需要一条 2m 净宽的环游动线"],
                            "open_questions": ["协诚产品清单缺失"]})
        elif "空间规划" in system and "还没开始排平面" in last:
            text = "问你两件事：这个项目你想让人记住什么？天花和重点照明你打算怎么做，我好留空。"
        elif "概念与材质" in system and "刚刚问你" in last:
            text = "记忆点放在中央那一圈光，人绕着走。天花做环形灯槽压住中岛，北墙只用轨道洗墙。"
        elif "设计总监" in system:
            text = as_json({"verdict": "revise",
                            "summary": "A 的环游半径偏大，B 的一轴到底让北端洽谈变成死角；两案都要补照明与收口。",
                            "issues": review_issues(),
                            "better": "A", "why": "A 更符合带客户看展的节奏，只要补齐北侧照明与斜线关系。"})
        # Revision prompts are checked BEFORE option prompts: they also mention
        # "候选 A" as the revision target, so a loose match would return a fresh
        # option instead of the patch and lose the per-issue responses.
        elif "白名单 patch" in last or "逐条回应" in last or "自动打回" in last:
            text = as_json(revision_payload())
        elif "空间规划" in system and "请产出候选 B" in last:
            text = as_json(valid_proposal("B"))
        elif "空间规划" in system and "请产出候选 A" in last:
            text = as_json(valid_proposal("A"))
        else:
            text = "收到。"
        return {"content": text, "tool_calls": [],
                "usage": {"in": 1200, "out": 400, "known": True,
                          "cost_status": "unknown_no_price_table"},
                "model": self.config.model}

    def chat_vision(self, messages, images, temperature=0.4, max_tokens=1000, json_only=False):
        self.usage.add(1500, 300)
        return {"content": as_json({
            "summary": "（本地桩）草案只画了分区与家具，未画天花与灯具；不据图面推断数据缺失。",
            "observations": [{"target": "A", "observation": "矩形分区", "gap": "缺圆弧",
                              "suggest": "入口做弧墙"}],
            "limits": "本地桩不真的看图，仅验证管线"}),
            "usage": {"in": 1500, "out": 300, "known": True,
                      "cost_status": "unknown_no_price_table"},
            "model": "local-model-stub", "image_count": len(images)}


def main() -> int:
    scratch = ROOT / "var" / "evidence" / "architecture-handoff" / "first-batch" / "after" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    store = Store(scratch / f"studio-loop-{os.getpid()}.db")
    studio = orchestrator.Studio(store)
    studio.seed_from_fixtures()
    # boss feedback must enter the revision input (Q07)
    store.add_feedback("ningbo-xiecheng", "boss_message", "调整洽谈区、保留入口")
    orchestrator.Client = FakeClient  # type: ignore[assignment]
    vision.svg_to_jpeg = lambda svg, limit=720: FAKE_JPEG  # type: ignore[assignment]
    vision.reference_jpeg = lambda limit=720: FAKE_JPEG  # type: ignore[assignment]
    studio.run_a1("ningbo-xiecheng", background=False)

    state = store.project_state("ningbo-xiecheng")
    msgs = [m for m in state["messages"] if m["kind"] != "tool"]
    kinds = {m["kind"] for m in msgs}
    plans = [a for a in state["artifacts"] if a["kind"] == "spatial-plan"]
    raw = [a for a in state["artifacts"] if a["kind"] == "spatial-plan-raw"]
    sketches = [a for a in state["artifacts"] if a["kind"] == "plan-sketch"]
    valid = [a for a in plans if a["contract_status"] == "valid_candidate"
             and a["status"] == "valid_candidate"]
    checks = {
        "有任务拆解": "task" in kinds,
        "有讨论": "discussion" in kinds,
        "两个候选均为有效候选": len({p["option_id"] for p in valid if p["revision"] == 1}) == 2,
        "有修订版": any(p["revision"] >= 2 for p in valid),
        "有缩略图": len(sketches) >= 3,
        "有评审": bool(state["reviews"]) and len(state["reviews"][0]["issues"]) >= 5,
        "有逐条回应": any("逐条回应" in m["body"] for m in msgs),
        "有闸口且绑定基线": any(g["status"] == "waiting" and g.get("baseline_artifact_id")
                                for g in state["gates"]),
        "有看图自评": "visual-review" in kinds,
        "总监没说通过": all("通过" not in (r["verdict"] or "") for r in state["reviews"]),
        "老板留言进入版本化反馈": state["feedback_revision"] >= 1
                                and any("调整洽谈区" in f["text"] for f in state["feedback"]),
        "修订读取基线ID与对象diff": any("revision_uid" in json.dumps(m["evidence"], ensure_ascii=False)
                                        for m in msgs),
        "有检查报告关联": all(p["check_report_id"] for p in valid)
                          and len(state["check_reports"]) >= 3,
        "无效原始稿未冒充有效候选": all(a["status"] == "invalid_raw" for a in raw),
        # Real check: no artifact / run / gate anywhere claims approval or a
        # design pass. A `succeeded` run only means the flow finished.
        "阶段状态未自称设计通过": (
            all(a["status"] not in ("approved", "published", "design_passed")
                and a["contract_status"] not in ("approved", "design_passed")
                for a in state["artifacts"])
            and all(r["status"] in ("succeeded", "incomplete", "failed", "budget_stopped",
                                    "model_failed", "superseded", "running")
                    for r in state["runs"])
            and all("设计通过" not in (g.get("decision") or "") for g in state["gates"])
        ),
    }
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print(json.dumps({"messages": len(msgs), "artifacts": len(state["artifacts"]),
                      "valid_candidates": len(valid), "raw_invalid": len(raw),
                      "check_reports": len(state["check_reports"]),
                      "runs": [r["status"] for r in state["runs"]],
                      "tokens": state["usage"]["tokens_total"]}, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
