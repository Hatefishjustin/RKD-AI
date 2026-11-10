"""A1 scenario: one real loop through the studio for the Ningbo project.

P plans → D1 writes the brief → D2 and D3 talk → D2 drafts two options →
R reviews → D2 answers point by point and revises → P opens a gate for the boss.
Everything lands in the shared store; nothing is auto-approved.

A failed model answer is a failure, not an empty artifact that quietly proceeds.
"""
from __future__ import annotations

import json
import threading
import traceback
from typing import Any, Callable

from . import sketch, tools as toolbox
from .tools import check_plan
from .llm import BudgetExceeded, Client, ModelError, Usage, extract_json
from .roles import ROLES, Role
from .store import Store

Event = Callable[[dict], None]

# The channel sometimes wraps every answer in a single-key JSON object.
_WRAPPER_KEYS = ("response", "reply", "answer", "text", "content", "message",
                 "result", "data", "plan", "brief", "review")


class IncompleteArtifact(RuntimeError):
    """A deliverable is missing or unusable. The run must not be marked succeeded."""


def _unwrap(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        key = next(iter(value))
        if key in _WRAPPER_KEYS and isinstance(value[key], (str, dict, list)):
            return _unwrap(value[key])
    return value


def _display_text(text: str) -> str:
    """Natural-language turns must read like a colleague, not like JSON."""
    t = text.strip()
    if t.startswith("{"):
        try:
            d = json.loads(t)
            if isinstance(d, dict):
                for k in _WRAPPER_KEYS:
                    if k in d and isinstance(d[k], str) and len(d) <= 2:
                        return d[k].strip() or t
        except Exception:
            pass
    return t


def _safe_json(text: str) -> dict:
    try:
        data = _unwrap(extract_json(text))
        if isinstance(data, dict):
            return data
        return {"raw": text, "parse_error": True}
    except Exception:
        return {"raw": text, "parse_error": True}


def plan_is_valid(plan: dict) -> tuple[bool, str]:
    """Minimum usable deliverable: real zones, a strategy and an area table."""
    zones = plan.get("zones") or []
    if not isinstance(zones, list) or len(zones) < 3:
        return False, "分区少于 3 个（或根本不是列表）"
    for z in zones:
        if not isinstance(z, dict):
            return False, "分区条目不是对象"
        poly = z.get("polygon") or []
        if not isinstance(poly, list) or len(poly) < 3:
            return False, f"分区 {z.get('id', '?')} 没有可用的多边形轮廓"
    if not str((plan.get("strategy") or {}).get("name") or "").strip():
        return False, "没有方案名称/主张"
    if not (plan.get("area_table") or []):
        return False, "缺面积表"
    return True, ""


def _changed_objects(before: dict, after: dict) -> list[str]:
    """Which object ids actually changed between two plan revisions."""
    keys = ("zones", "furniture", "platforms", "circulation")
    changed: list[str] = []

    def sig(plan: dict, key: str) -> dict[str, str]:
        return {str(o.get("id", "?")): json.dumps(o, ensure_ascii=False, sort_keys=True)
                for o in (plan.get(key) or []) if isinstance(o, dict)}

    for key in keys:
        a, b = sig(before, key), sig(after, key)
        for oid in set(a) | set(b):
            if a.get(oid) != b.get(oid):
                changed.append(f"{key}:{oid}")
    for sub in ("coves", "fixtures"):
        a = sig((before.get("ceiling") or {}), sub)
        b = sig((after.get("ceiling") or {}), sub)
        for oid in set(a) | set(b):
            if a.get(oid) != b.get(oid):
                changed.append(f"ceiling.{sub}:{oid}")
    return sorted(changed)


class Studio:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()
        self._running: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ seeding
    def seed_from_fixtures(self) -> list[str]:
        from pathlib import Path
        root = Path(__file__).resolve().parents[3] / "fixtures" / "studio" / "projects"
        ids = []
        for f in sorted(root.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            self.store.upsert_project(data["project_id"], data["name"], data["site"],
                                      data["requirement"], (data.get("golden_reference") or {}).get("path"))
            ids.append(data["project_id"])
        return ids

    # -------------------------------------------------------------------- agent
    def _speak(self, role: Role, client: Client, project_id: str, task_id: str | None,
               instruction: str, context: str = "", tools: list[dict] | None = None,
               handlers: dict[str, Callable[..., dict]] | None = None,
               json_only: bool = False, kind: str = "say", label: str = "",
               evidence: list[dict] | None = None, max_steps: int = 5) -> str:
        messages = [{"role": "system", "content": role.system}]
        if context:
            messages.append({"role": "user", "content": context})
        messages.append({"role": "user", "content": instruction})
        ev: list[dict] = [
            {"type": "input", "role": role.id, "task_id": task_id, "label": label,
             "context_chars": len(context), "instruction": instruction[:260],
             "tools_allowed": [t["function"]["name"] for t in (tools or [])]},
            {"type": "model", "name": client.config.model},
        ]
        ev.extend(evidence or [])
        start = (client.usage.tokens_in, client.usage.tokens_out)
        text = ""

        for step in range(max_steps):
            force_final = step == max_steps - 1
            step_messages = list(messages)
            if force_final:
                tail = ("只输出要求的那一个 JSON 对象，不要包裹、不要解释。"
                        if json_only else "直接用中文说结论，不要输出 JSON 外壳。")
                step_messages.append({"role": "user",
                                      "content": "现在禁止再调用任何工具，请立即给出最终答案：" + tail})
            before = (client.usage.tokens_in, client.usage.tokens_out)
            resp = client.chat(step_messages, tools=None if force_final else tools,
                               temperature=role.temperature, max_tokens=role.max_tokens,
                               json_only=json_only)
            used = (client.usage.tokens_in - before[0], client.usage.tokens_out - before[1])

            if force_final or not resp["tool_calls"]:
                text = resp["content"]
                final_tokens = used
                break

            messages.append({"role": "assistant", "content": resp["content"] or "",
                             "tool_calls": resp["tool_calls"]})
            first = True
            for call in resp["tool_calls"]:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                fn = (handlers or {}).get(name)
                try:
                    result = fn(**args) if fn else {"error": f"未知工具 {name}"}
                except Exception as exc:  # tool failure is data, not a crash
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                compact = json.dumps(result, ensure_ascii=False)
                ev.append({"type": "tool", "name": name, "args": args,
                           "result": compact[:1200]})
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": compact[:6000]})
                self.store.add_message(project_id, role.id, "tool",
                                       f"调用工具 `{name}`", task_id=task_id,
                                       evidence=[{"type": "tool", "name": name, "args": args,
                                                  "result": compact[:600]}],
                                       tokens_in=used[0] if first else 0,
                                       tokens_out=used[1] if first else 0,
                                       model=client.config.model)
                first = False
        else:
            text, final_tokens = "", (0, 0)

        if not text:
            text = "（未给出结论：模型在工具调用阶段用尽轮次）"
            if json_only:
                text = "{}"
        if not json_only:
            text = _display_text(text)

        ev[1].update({"calls": client.usage.calls,
                      "tokens_in": client.usage.tokens_in - start[0],
                      "tokens_out": client.usage.tokens_out - start[1]})
        self.store.add_message(project_id, role.id, kind, text, task_id=task_id,
                               evidence=ev, tokens_in=final_tokens[0],
                               tokens_out=final_tokens[1], model=client.config.model)
        return text

    # ---------------------------------------------------------------- A1 script
    def run_a1(self, project_id: str, background: bool = True) -> dict:
        with self._lock:
            if project_id in self._running:
                return {"status": "already_running", "project_id": project_id}
            self._running.add(project_id)
        project = self.store.get_project(project_id)
        if not project:
            with self._lock:
                self._running.discard(project_id)
            raise KeyError(project_id)

        def work() -> None:
            prior = sum((r["tokens_in"] or 0) + (r["tokens_out"] or 0)
                        for r in self.store.runs(project_id) if r["status"] != "running")
            client = Client(project_tokens=prior)
            run_id = self.store.start_run(project_id, client.config.model)
            status, error = "succeeded", None
            try:
                self._scenario(project, client)
            except BudgetExceeded as exc:
                status, error = "budget_stopped", str(exc)
                self.store.add_message(project_id, "P", "gate", f"预算闸口：{exc}",
                                       evidence=[{"type": "budget"}])
                self.store.open_gate(project_id, "预算已到上限", str(exc))
            except IncompleteArtifact as exc:
                status, error = "incomplete", str(exc)
                detail = (f"本轮没有交出可用成果：{exc}。按老板的规矩不算通过，"
                          "不进入下一步，也不把空方案摆到成果栏。请决定重跑还是换做法。")
                self.store.add_message(project_id, "P", "gate", detail,
                                       evidence=[{"type": "incomplete", "reason": str(exc)}])
                self.store.open_gate(project_id, "本轮未完成：请决定重跑还是换做法", detail)
            except ModelError as exc:
                status, error = "model_failed", str(exc)
                detail = f"模型通道问题，回路中断：{exc}"
                self.store.add_message(project_id, "P", "gate", detail,
                                       evidence=[{"type": "channel"}])
                self.store.open_gate(project_id, "通道中断：请决定是否重跑", detail)
            except Exception as exc:  # noqa: BLE001 - never lose the trace
                status, error = "failed", f"{type(exc).__name__}: {exc}"
                self.store.add_message(project_id, "P", "gate",
                                       f"回路异常中断：{error}",
                                       evidence=[{"type": "trace", "detail": traceback.format_exc()[-1500:]}])
                self.store.open_gate(project_id, "回路异常中断：请决定是否重跑", error)
            finally:
                self.store.finish_run(run_id, status, client.usage.tokens_in,
                                      client.usage.tokens_out, error)
                with self._lock:
                    self._running.discard(project_id)

        if background:
            threading.Thread(target=work, daemon=True, name=f"studio-{project_id}").start()
            return {"status": "started", "project_id": project_id}
        work()
        return {"status": "finished", "project_id": project_id}

    # ------------------------------------------------------------------ helpers
    def _ctx(self, project: dict) -> str:
        site = project["site"]
        req = project["requirement"]
        return (
            f"【项目】{project['name']}\n"
            f"【场地】{site['width_mm'] / 1000:.2f} × {site['height_mm'] / 1000:.2f} m，层高 "
            f"{site['ceiling_mm'] / 1000:.2f} m；北窗 {len(site.get('windows_north') or [])} 段、"
            f"东窗 {len(site.get('windows_east') or [])} 段；入口在西墙 y={site['entrance'][1]}–{site['entrance'][1] + site['entrance'][2]} mm；"
            f"保留：楼梯 {site['stair'][2] / 1000:.2f}×{site['stair'][3] / 1000:.2f} m、卫生间 "
            f"{(site['bath'][2] - site['bath'][0]) / 1000:.2f}×{(site['bath'][3] - site['bath'][1]) / 1000:.2f} m；"
            f"结构柱 {site.get('columns', 0)} 根。\n"
            f"【老板原话】{req['text']}\n"
            f"【必须项】{'、'.join(req['must_have'])}\n"
            f"【约束】预算 {req['constraints']['budget_cny']:,} 元（{req['constraints']['budget_note']}），"
            f"风格 {req['constraints']['style']}。\n"
            f"【已知缺口】{'；'.join(req.get('unknowns') or [])}"
        )

    def _tools_for(self, project: dict, role_id: str):
        spec, handlers = toolbox.build_tools(project)
        allow = {
            "D1": {"get_site", "get_requirement"},
            "D2": {"get_site", "get_requirement", "list_standards", "search_catalog", "validate_plan"},
            "D3": {"get_site", "get_requirement", "list_standards", "search_catalog"},
            "D4": {"get_site", "search_catalog", "validate_plan"},
            "R": {"get_site", "get_requirement", "list_standards"},
        }.get(role_id, set())
        picked = [t for t in spec if t["function"]["name"] in allow]
        return picked, {k: v for k, v in handlers.items() if k in allow}

    _TOOL_BUDGET = ("工具预算：最多 3 次调用（list_standards 一次；search_catalog 一次，"
                    "不传 query 会返回全部目录；validate_plan 一次）。"
                    "拿够信息后必须立刻输出最终完整 JSON，禁止再调工具。")

    # ---------------------------------------------------------------- scenario
    def _scenario(self, project: dict, client: Client) -> None:
        pid = project["id"]
        ctx = self._ctx(project)

        # 0. P plans the work
        task_p = self.store.create_task(pid, "P", "拆解本项目：这一轮做什么")
        self._speak(
            ROLES["P"], client, pid, task_p,
            "老板刚把这个项目交给我们，还没给任何方案。请用 3–5 句话说明：这一轮先做什么、交给谁、"
            "交付物是什么、什么算做完。不要复述场地数据，不要现在做设计判断。",
            context=ctx, kind="task", label="任务拆解", max_steps=2)
        self.store.update_task(task_p, "done")

        # 1. D1 brief
        task_d1 = self.store.create_task(pid, "D1", "产出设计任务书")
        brief_raw = self._speak(
            ROLES["D1"], client, pid, task_d1,
            "请产出任务书，只输出 JSON：{\"goal\":\"一句话目标\",\"must_have\":[\"...\"],"
            "\"site_facts\":[\"...\"],\"budget\":\"...\",\"inferences\":[\"你自己加的判断，标明推断\"],"
            "\"open_questions\":[\"必须问老板的\"]}。must_have 要能一条条对回老板原话。",
            context=ctx, tools=self._tools_for(project, "D1")[0],
            handlers=self._tools_for(project, "D1")[1], json_only=True, kind="artifact",
            label="任务书", max_steps=4)
        brief = _safe_json(brief_raw)
        if not brief.get("goal"):
            raise IncompleteArtifact("D1 没有交出带 goal 的任务书")
        self.store.save_artifact(pid, "brief", brief, "D1", task_id=task_d1)
        self.store.update_task(task_d1, "done")

        # 2. D2 <-> D3 discussion before drawing
        task_talk = self.store.create_task(pid, "D2", "与概念设计对齐（动手前讨论）")
        q = self._speak(
            ROLES["D2"], client, pid, task_talk,
            "还没开始排平面。你先问概念设计（D3）两个具体问题：这个项目你打算怎么让人记住它？"
            "天花和重点照明你想怎么做（这会影响我怎么留空和留高）？用 2–3 句话说，像同事说话。",
            context=ctx + f"\n【任务书】{json.dumps(brief, ensure_ascii=False)[:1200]}",
            kind="discussion", label="向概念设计提问", max_steps=2)
        a = self._speak(
            ROLES["D3"], client, pid, task_talk,
            "空间规划（D2）刚问你：" + q + "\n请直接回答他，2–4 句话，说清你的叙事方向和天花/灯光的打算。"
            "不要现在出完整概念，也不要替他排平面。",
            context=ctx, kind="discussion", label="回答空间规划", max_steps=2)
        self.store.update_task(task_talk, "done")

        # 3. D2 two options
        task_d2 = self.store.create_task(pid, "D2", "出两个拓扑不同的空间候选")
        options: dict[str, dict] = {}
        for opt in ("A", "B"):
            raw = self._speak(
                ROLES["D2"], client, pid, task_d2,
                f"请产出候选 {opt}。要求：\n"
                f"- 与另一个候选在拓扑上不同（入口关系、重点展台位置、动线形状至少两项不同）；\n"
                f"- 严格按契约只输出 JSON（rkd-spatial-plan.v1）：contract_version/project_id/option_id/revision/"
                f"strategy{{name,narrative,tradeoffs,non_orthogonal}}/zones[]/circulation[]/"
                f"platforms[]/ceiling{{strategy,coves[],fixtures[]}}/furniture[]/area_table[]/open_questions[]/standards_cited[]；\n"
                f"- zones[].polygon 用 mm 的 [[x,y],...]，area_sqm 与轮廓一致；天花要有灯槽与灯具点位；\n"
                f"- 至少 5 个分区、3 件家具、2 处非直角造型；\n"
                f"- {self._TOOL_BUDGET}\n"
                f"- 交付前用 validate_plan 自检一次，把 blocker 改掉。",
                context=ctx + f"\n【任务书】{json.dumps(brief, ensure_ascii=False)[:1200]}\n"
                              f"【与概念的讨论】{a[:600]}",
                tools=self._tools_for(project, "D2")[0], handlers=self._tools_for(project, "D2")[1],
                json_only=True, kind="artifact", label=f"候选 {opt}", max_steps=5)
            plan = _safe_json(raw)
            ok, why = plan_is_valid(plan)
            if not ok:
                self.store.add_message(pid, "D2", "note",
                                       f"候选 {opt} 没交出可用数据：{why}。模型原文：{raw[:400]}",
                                       task_id=task_d2,
                                       evidence=[{"type": "invalid_output", "reason": why,
                                                  "raw_head": raw[:400]}])
                raise IncompleteArtifact(f"候选 {opt} 无效：{why}")
            plan.setdefault("contract_version", "rkd-spatial-plan.v1")
            plan["project_id"] = pid
            plan["option_id"] = opt
            plan["revision"] = 1
            plan["author"] = "D2"
            aid = self.store.save_artifact(pid, "spatial-plan", plan, "D2", option_id=opt, revision=1,
                                           task_id=task_d2)
            self.store.save_artifact(pid, "plan-sketch",
                                     {"svg": sketch.render(plan, project["site"], f"候选 {opt} · {plan.get('strategy', {}).get('name', '')}")},
                                     "D2", option_id=opt, revision=1, task_id=task_d2)
            options[opt] = {"id": aid, "plan": plan}
            self.store.add_message(pid, "D2", "note",
                                   f"候选 {opt}「{plan['strategy']['name']}」已出图：{len(plan['zones'])} 个分区、"
                                   f"{len(plan.get('furniture') or [])} 件家具。",
                                   task_id=task_d2, evidence=[{"type": "artifact", "id": aid, "revision": 1}])
        self.store.update_task(task_d2, "done")

        # 4. R reviews
        task_r = self.store.create_task(pid, "R", "评审两个候选")
        review_raw = self._speak(
            ROLES["R"], client, pid, task_r,
            "请评审这两个候选。先调 list_standards 取全部规范，再逐条对照。\n"
            "只输出 JSON：{\"verdict\":\"advance|revise\",\"summary\":\"一段话：这两个方案各自的问题与优点\","
            "\"issues\":[{\"issue_id\":\"I1\",\"candidate\":\"A|B\",\"severity\":\"blocker|major|minor\","
            "\"objects\":[\"分区或家具 id\"],\"rule_id\":\"STD-00x\",\"evidence\":\"数据事实\","
            "\"suggest\":\"具体改法\"}],\"better\":\"A|B\",\"why\":\"为什么\"}。\n"
            "要求：至少 5 条 issue，必须挂到具体对象；不许写\"通过\"；如果方案平庸，要直说平庸在哪。",
            context=ctx + "\n【候选 A】" + json.dumps(options["A"]["plan"], ensure_ascii=False)[:4000]
            + "\n【候选 B】" + json.dumps(options["B"]["plan"], ensure_ascii=False)[:4000],
            tools=self._tools_for(project, "R")[0], handlers=self._tools_for(project, "R")[1],
            json_only=True, kind="review", label="评审意见", max_steps=4)
        review = _safe_json(review_raw)
        issues = review.get("issues") or []
        if len(issues) < 3 or not review.get("summary"):
            raise IncompleteArtifact("总监没有交出可核对的结构化评审（意见少于 3 条或缺总结）")
        self.store.save_review(pid, options["A"]["id"], "R", str(review.get("verdict") or "revise"),
                               str(review.get("summary") or ""), issues)
        self.store.update_task(task_r, "done")

        # 5. D2 responds point by point and revises the chosen one
        target = review.get("better") if review.get("better") in ("A", "B") else "A"
        task_rev = self.store.create_task(pid, "D2", f"逐条回应评审并修订候选 {target}", round_no=2)
        rev_raw = self._speak(
            ROLES["D2"], client, pid, task_rev,
            f"总监的评审意见如下：{json.dumps(issues, ensure_ascii=False)[:3000]}\n"
            f"请对候选 {target} 做两件事：① 逐条回应（接受就写改了什么，不接受就写清理由）；"
            f"② 给出修订后的完整 JSON（契约同上，revision=2，parent_revision=1）。\n"
            "只输出 JSON：{\"responses\":[{\"issue_id\":\"I1\",\"action\":\"accept|reject\","
            "\"change\":\"改了什么\",\"reason\":\"不接受的理由（若接受则简述）\"}],\"plan\":{...}}。\n"
            f"- 被接受的 issue 必须真的改到 plan 里（分区、家具、灯位、面积表按意见调整）；\n"
            f"- {self._TOOL_BUDGET}\n"
            "- 只改被指出的问题，不要顺手重做整个方案。",
            context=ctx + "\n【原候选】" + json.dumps(options[target]["plan"], ensure_ascii=False)[:4000],
            tools=self._tools_for(project, "D2")[0], handlers=self._tools_for(project, "D2")[1],
            json_only=True, kind="revise", label="逐条回应 + 修订", max_steps=5)
        rev = _safe_json(rev_raw)
        new_plan = rev.get("plan") or {}
        responses = rev.get("responses") or []
        ok2, why2 = plan_is_valid(new_plan)
        if not responses or not ok2:
            raise IncompleteArtifact(
                f"修订无效：逐条回应 {len(responses)} 条；{why2 or 'plan 可用'}。"
                "评审意见没有被落实，不算完成往返。")
        new_plan.update({"contract_version": "rkd-spatial-plan.v1", "project_id": pid,
                         "option_id": target, "revision": 2, "parent_revision": 1, "author": "D2"})
        aid2 = self.store.save_artifact(pid, "spatial-plan", new_plan, "D2", option_id=target,
                                        revision=2, parent_revision=1, task_id=task_rev)
        self.store.save_artifact(pid, "plan-sketch",
                                 {"svg": sketch.render(new_plan, project["site"],
                                                       f"候选 {target} 修订版 · {new_plan.get('strategy', {}).get('name', '')}")},
                                 "D2", option_id=target, revision=2, parent_revision=1, task_id=task_rev)
        accepted = sum(1 for r in responses if r.get("action") == "accept")
        changed = _changed_objects(options[target]["plan"], new_plan)
        if accepted and not changed:
            raise IncompleteArtifact(f"逐条回应接受了 {accepted} 条，但 v1→v2 没有任何对象发生变化")
        self.store.add_message(
            pid, "D2", "note",
            f"已逐条回应 {len(responses)} 条意见，接受 {accepted} 条；候选 {target} v2 实际改动 "
            f"{len(changed)} 个对象：{'、'.join(changed[:8]) or '无'}。",
            task_id=task_rev,
            evidence=[{"type": "artifact", "id": aid2, "revision": 2},
                      {"type": "responses", "items": responses[:10]},
                      {"type": "diff", "changed": changed}])
        self.store.update_task(task_rev, "done")

        # 6. P opens the gate — with the deterministic QC figures, not a claim of success
        def _count(ck: dict, severity: str) -> int:
            return sum(1 for i in ck["issues"] if i["severity"] == severity)

        qc_before = check_plan(options[target]["plan"], project["site"])
        qc_after = check_plan(new_plan, project["site"])
        b0, m0 = _count(qc_before, "blocker"), _count(qc_before, "major")
        b1, m1 = _count(qc_after, "blocker"), _count(qc_after, "major")
        qc_line = (f"程序硬校验：v1 blocker {b0} / major {m0}；v2 blocker {b1} / major {m1}。"
                   + ("修订版仍有 blocker，不能当作可用方案。" if b1 else "修订版没有 blocker，但仍不等于设计合格。")
                   + "程序只量几何与面积，不替老板判断好不好看。")
        gate_title = ("本轮成果仍有硬伤：请决定是否继续打回" if b1
                      else "选一个方向继续（A1 回路到此）")
        gate_detail = (
            f"总监建议：{review.get('verdict')}，倾向选择 {target}（{review.get('why') or ''}）。\n"
            f"本轮实数：2 个候选、{len(issues)} 条评审意见、{len(responses)} 条逐条回应、"
            f"v2 改动 {len(changed)} 个对象。\n{qc_line}\n"
            "注意：总监只能建议；流程走完不等于方案通过，是否成立由你决定。")
        gid = self.store.open_gate(pid, gate_title, gate_detail)
        self.store.add_message(pid, "P", "gate", gate_detail,
                               evidence=[{"type": "gate", "id": gid},
                                         {"type": "artifact", "id": aid2, "revision": 2},
                                         {"type": "qc", "v1": {"blocker": b0, "major": m0},
                                          "v2": {"blocker": b1, "major": m1}}])
        self.store.add_message(pid, "P", "note",
                               f"本轮流程走完。成果栏里有候选 A/B、{target} 的修订版 v2 和三张草案缩略图。"
                               + qc_line,
                               evidence=[{"type": "usage", "tokens": client.usage.total},
                                         {"type": "qc", "v2_issues": qc_after["issues"][:6]}])
