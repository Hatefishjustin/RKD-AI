"""Plumbing test for the A1 loop: canned model answers, real store, real flow.

This proves the machinery (tasks, discussion, artifacts, review, revision, gate)
works end to end WITHOUT pretending to be a real model run. Real runs are done
through the studio service with a live channel.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mvp"))

from rkd_mvp.studio import orchestrator  # noqa: E402
from rkd_mvp.studio.llm import Usage  # noqa: E402
from rkd_mvp.studio.store import Store  # noqa: E402

W, H = 26170, 17920

# Plumbing-only stand-in: this test must not depend on a local headless browser
# or Pillow. Real visual reviews run inside the service process with real
# rasters (see docs/evidence/a1-studio-vision-review.png).
FAKE_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 32 + b"\xff\xd9"


def plan(option: str, revision: int = 1) -> dict:
    zones = [
        ("Z1", "序厅", "arrival", [[0, 8600], [5400, 8600], [5400, 13500], [0, 13500]]),
        ("Z2", "中央中岛", "island", [[9000, 6200], [16000, 6200], [16000, 11000], [9000, 11000]]),
        ("Z3", "北光廊", "gallery", [[5400, 13300], [21800, 13300], [21800, 17700], [5400, 17700]]),
        ("Z4", "南场景", "scene", [[5400, 1800], [20400, 1800], [20400, 5200], [5400, 5200]]),
        ("Z5", "东洽谈", "meeting", [[19400, 7600], [26100, 7600], [26100, 13300], [19400, 13300]]),
        ("Z6", "水吧", "service", [[2400, 1800], [5400, 1800], [5400, 6100], [2400, 6100]]),
    ]
    zs = []
    for zid, name, role, poly in zones:
        area = abs(sum(poly[i][0] * poly[(i + 1) % 4][1] - poly[(i + 1) % 4][0] * poly[i][1]
                       for i in range(4))) / 2 / 1e6
        zs.append({"id": zid, "name": name, "role": role, "polygon": poly, "area_sqm": round(area, 1)})
    total = sum(z["area_sqm"] for z in zs)
    data = {
        "contract_version": "rkd-spatial-plan.v1",
        "project_id": "ningbo-xiecheng",
        "option_id": option,
        "revision": revision,
        "parent_revision": 1 if revision > 1 else None,
        "author": "D2",
        "strategy": {
            "name": "环岛漫游" if option == "A" else "一轴到底",
            "narrative": "进门先被弧形木墙引到中央，再绕着中岛走一圈看完，最后在南侧坐下。",
            "tradeoffs": ["主展台居中，四周都能看", "环游占掉约 55 ㎡ 通道面积"],
            "non_orthogonal": ["中岛三级圆角 R1560/1360/1180", "入口弧形品牌墙 R4660"],
        },
        "zones": zs,
        "circulation": [{"id": "C1", "width_mm": 2000,
                         "path": [[1800, 11000], [8000, 11000], [17500, 11000], [17500, 6000], [8000, 5200]]}],
        "platforms": [{"id": "P1", "name": "中央圆角中岛", "kind": "rounded",
                       "corner_radius_mm": 1180, "height_mm": 720,
                       "polygon": [[9000, 6200], [16000, 6200], [16000, 11000], [9000, 11000]]}],
        "ceiling": {"strategy": "环形灯槽洗台面，北光廊轨道射灯洗翼墙",
                    "coves": [{"id": "CV1", "band_mm": 200, "kelvin": 3000,
                               "polygon": [[8400, 5600], [16600, 5600], [16600, 11600], [8400, 11600]]}],
                    "fixtures": [{"id": "L1", "type": "spot", "x": 10250, "y": 7700, "kelvin": 3000},
                                 {"id": "L2", "type": "spot", "x": 14750, "y": 7700, "kelvin": 3000},
                                 {"id": "L3", "type": "downlight", "x": 13000, "y": 14500, "kelvin": 3000}]},
        "furniture": [{"id": "F1", "catalog_id": "sofa-3p", "x": 8400, "y": 4050, "rot": 0},
                      {"id": "F2", "catalog_id": "dining-table", "x": 14400, "y": 3300, "rot": 0},
                      {"id": "F3", "catalog_id": "display-wing", "x": 9500, "y": 16350, "rot": -12}],
        "area_table": [{"name": z["name"], "area_sqm": z["area_sqm"]} for z in zs]
                      + [{"name": "通道及其他", "area_sqm": round(469.0 - total, 1)}],
        "open_questions": ["协诚的产品清单缺失，展品只能做示意"],
        "standards_cited": ["STD-001", "STD-003", "STD-005"],
    }
    # A revision must change real objects, not merely claim to have changed them.
    if revision > 1:
        data["ceiling"]["fixtures"].append(
            {"id": "L4", "type": "spot", "x": 11800, "y": 14500, "kelvin": 3000})
        data["circulation"][0]["width_mm"] = 2100
    if revision == 2:
        # Deliberately worse area reconciliation: exercises the auto rework path.
        data["area_table"] = [{"name": "全部（错误示例）", "area_sqm": 800.0}]
    return data


class FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.usage = Usage()
        self.config = type("C", (), {"model": "fake-model", "run_token_limit": 600_000,
                                     "project_token_limit": 2_000_000, "configured": True})()

    def chat(self, messages, tools=None, temperature=0.6, max_tokens=3000, json_only=False):
        system = messages[0]["content"]
        last = messages[-1]["content"]
        self.usage.add(1200, 400)
        if "这是第" in last and "自动打回" in last:
            text = json.dumps(plan("A", 3), ensure_ascii=False)
        elif "项目经理" in system:
            text = "这一轮先做三件事：定任务书、出两个拓扑不同的空间候选、总监评审后改一版。交付物是两份候选和一份修订；做完等老板选。"
        elif "需求分析" in system:
            text = json.dumps({"goal": "做一个能带客户看样品、也能坐下来谈的展厅",
                               "must_have": ["品牌第一眼", "产品序列", "重点展台"],
                               "site_facts": ["26.17×17.92m，层高 3m", "楼梯与卫生间保留"],
                               "budget": "60 万含税",
                               "inferences": ["推断：需要一条 2m 净宽的环游动线"],
                               "open_questions": ["协诚产品清单缺失"]}, ensure_ascii=False)
        elif "空间规划" in system and "还没开始排平面" in last:
            text = "问你两件事：这个项目你想让人记住什么？天花和重点照明你打算怎么做，我好留空。"
        elif "概念与材质" in system and "刚刚问你" in last:
            text = "记忆点放在中央那一圈光，人绕着走。天花做环形灯槽压住中岛，北墙只用轨道洗墙，别做满吊顶。"
        elif '"responses"' in last:
            revised = plan("A", 2)
            text = json.dumps({
                "responses": [
                    {"issue_id": "I1", "action": "accept", "change": "南侧加 1.2m 过渡带", "reason": ""},
                    {"issue_id": "I2", "action": "accept", "change": "北光廊补到 7 个射灯", "reason": ""},
                    {"issue_id": "I3", "action": "reject", "change": "", "reason": "B 不在本轮深化范围"},
                    {"issue_id": "I4", "action": "accept", "change": "品牌墙改 R4660 弧墙", "reason": ""},
                    {"issue_id": "I5", "action": "accept", "change": "面积表拆出楼梯与卫生间", "reason": ""},
                ],
                "plan": revised,
            }, ensure_ascii=False)
        elif "空间规划" in system and "候选 B" in last:
            text = json.dumps(plan("B"), ensure_ascii=False)
        elif "空间规划" in system and "候选 A" in last:
            text = json.dumps(plan("A"), ensure_ascii=False)
        elif "设计总监" in system:
            text = json.dumps({
                "verdict": "revise",
                "summary": "两个方案都能用，但 A 的环游半径过大，B 的一轴到底让北光廊变成死胡同。",
                "issues": [
                    {"issue_id": "I1", "candidate": "A", "severity": "blocker", "objects": ["C1"],
                     "rule_id": "CIR-001", "evidence": "环游净宽 2000mm 但从南侧绕回缺少收口",
                     "suggest": "在南场景与环游之间加 1200mm 的过渡带"},
                    {"issue_id": "I2", "candidate": "A", "severity": "major", "objects": ["Z3"],
                     "rule_id": "STD-005", "evidence": "北光廊只有 3 个灯位，2/3 长度没有照明",
                     "suggest": "按 3m 间距补轨道射灯"},
                    {"issue_id": "I3", "candidate": "B", "severity": "major", "objects": ["Z5"],
                     "rule_id": "STD-004", "evidence": "东洽谈区没有对应的视线与采光",
                     "suggest": "洽谈区靠东窗布置"},
                    {"issue_id": "I4", "candidate": "A", "severity": "minor", "objects": ["F3"],
                     "rule_id": "STD-001", "evidence": "只有一处斜置，另一处非直角靠中岛支撑",
                     "suggest": "入口品牌墙做成弧墙"},
                    {"issue_id": "I5", "candidate": "A", "severity": "blocker", "objects": ["Z4"],
                     "rule_id": "STD-003", "evidence": "面积表把差额全塞给通道，没有说明",
                     "suggest": "拆出楼梯与卫生间占用面积"},
                ],
                "better": "A",
                "why": "A 的环游更符合带客户看展的节奏，只要把北侧照明补齐。",
            }, ensure_ascii=False)
        elif "逐条回应" in last:
            revised = plan("A", 2)
            text = json.dumps({
                "responses": [
                    {"issue_id": "I1", "action": "accept", "change": "南侧加 1.2m 过渡带", "reason": ""},
                    {"issue_id": "I2", "action": "accept", "change": "北光廊补到 7 个射灯", "reason": ""},
                    {"issue_id": "I3", "action": "reject", "change": "", "reason": "B 不在本轮深化范围"},
                    {"issue_id": "I4", "action": "accept", "change": "品牌墙改 R4660 弧墙", "reason": ""},
                    {"issue_id": "I5", "action": "accept", "change": "面积表拆出楼梯与卫生间", "reason": ""},
                ],
                "plan": revised,
            }, ensure_ascii=False)
        else:
            text = "收到。"
        return {"content": text, "tool_calls": [], "usage": {"in": 1200, "out": 400},
                "model": self.config.model}

    def chat_vision(self, messages, images, temperature=0.4, max_tokens=1000, json_only=False):
        self.usage.add(1500, 300)
        return {"content": json.dumps({
            "summary": "（假模型）两张草案都偏方块感，天花的表达弱于案例参照。",
            "observations": [{"target": "A", "observation": "矩形分区", "gap": "缺圆弧",
                              "suggest": "入口做弧墙"}],
            "limits": "假模型不真的看图，仅验证管线"}, ensure_ascii=False),
            "usage": {"in": 1500, "out": 300}, "model": "fake-model",
            "image_count": len(images)}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="studio-test-"))
    store = Store(tmp / "studio.db")
    studio = orchestrator.Studio(store)
    studio.seed_from_fixtures()
    orchestrator.Client = FakeClient  # type: ignore[assignment]
    orchestrator.vision.svg_to_jpeg = lambda svg, limit=720: FAKE_JPEG  # type: ignore[assignment]
    orchestrator.vision.reference_jpeg = lambda limit=720: FAKE_JPEG  # type: ignore[assignment]
    studio.run_a1("ningbo-xiecheng", background=False)

    state = store.project_state("ningbo-xiecheng")
    msgs = [m for m in state["messages"] if m["kind"] != "tool"]
    kinds = {m["kind"] for m in msgs}
    plans = [a for a in state["artifacts"] if a["kind"] == "spatial-plan"]
    sketches = [a for a in state["artifacts"] if a["kind"] == "plan-sketch"]
    checks = {
        "有任务拆解": "task" in kinds,
        "有讨论": "discussion" in kinds,
        "有两个候选": len({p["option_id"] for p in plans if p["revision"] == 1}) == 2,
        "有修订版": any(p["revision"] >= 2 for p in plans),
        "有缩略图": len(sketches) >= 3,
        "有评审": bool(state["reviews"]) and len(state["reviews"][0]["issues"]) >= 5,
        "有逐条回应": any("逐条回应" in m["body"] for m in msgs),
        "有闸口": any(g["status"] == "waiting" for g in state["gates"]),
        "有自动打回": "rework" in kinds,
        "有看图自评": "visual-review" in kinds,
        "有重做版本": any(p["revision"] >= 3 for p in plans),
        "总监没说通过": all("通过" not in (r["verdict"] or "") for r in state["reviews"]),
    }
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print(json.dumps({"messages": len(msgs), "artifacts": len(state["artifacts"]),
                      "tokens": state["usage"]["tokens_total"]}, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
