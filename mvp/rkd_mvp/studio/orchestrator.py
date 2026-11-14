"""A1 scenario: one real loop through the studio for the mapped project.

P plans -> D1 writes the brief -> D2 and D3 talk -> D2 drafts two options ->
R reviews -> D2 answers point by point and revises -> P opens a gate for the boss.

Everything lands in the shared store; nothing is auto-approved.

ARC-01/03/04 remediation:
  * candidate acceptance is a FOUR-STAGE contract check (structure -> semantic
    references -> geometry/area -> locks), not a minimum-field check;
  * no character truncation of any structured hand-off; baseline ids, full
    object facts and issue_ids are passed explicitly;
  * revisions prefer whitelisted object patches applied by the program, and
    verify retention / deletion reasons / locks / per-issue linkage;
  * boss messages enter versioned effective requirements and the revision input;
  * run_id / candidate group / unique revision uid / parent uid / input hash /
    check report are all persisted; a late result from a stale input is
    invalidated instead of becoming the current version;
  * gates are bound to a concrete artifact baseline. MAX_AUTO_REWORK stays 2.

A failed model answer is a failure, not an empty artifact that quietly proceeds.
"""
from __future__ import annotations

import json
import threading
import traceback
from typing import Any, Callable

from . import revision as revision_mod
from . import sketch, tools as toolbox, validation, vision
from .tools import check_plan
from .llm import BudgetExceeded, Client, ModelError, Usage, extract_json
from .roles import ROLES, Role
from .store import Store, input_hash, new_id

Event = Callable[[dict], None]

# The boss's rule: a designer may be sent back automatically at most twice;
# a third round must be decided by the boss, never by the agents.
MAX_AUTO_REWORK = 2

# The channel sometimes wraps every answer in a single-key JSON object.
_WRAPPER_KEYS = ("response", "reply", "answer", "text", "content", "message",
                 "result", "data", "plan", "brief", "review")


class IncompleteArtifact(RuntimeError):
    """A deliverable is missing or unusable. The run must not be marked succeeded."""


class SupersededRun(RuntimeError):
    """A newer boss input (or explicit cancel) arrived; this run's result is stale."""


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


def _default_project() -> dict:
    from pathlib import Path
    root = Path(__file__).resolve().parents[3] / "fixtures" / "studio" / "projects" / "ningbo-xiecheng.json"
    d = json.loads(root.read_text(encoding="utf-8"))
    return {"id": d["project_id"], "name": d["name"], "site": d["site"],
            "requirement": d["requirement"]}


def plan_is_valid(plan: dict, project: dict | None = None) -> tuple[bool, str]:
    """Compatibility entry point: now a FULL contract check, never a min-field gate.

    Structure -> semantic references -> geometry/area -> locks must all pass.
    Historically this returned True for payloads with 66 Schema errors; it no
    longer does. Passing Schema alone is never treated as geometry validity.
    """
    project = project or _default_project()
    report = validation.validate_proposal(
        plan, project=project, option_id=str(plan.get("option_id") or "A"),
        revision=int(plan.get("revision") or 1), parent_revision=None)
    if report["ok"]:
        return True, ""
    first = report["errors"][0] if report["errors"] else {"message": "未知"}
    return False, (f"{report['stage']} 阶段 {len(report['errors'])} 条契约问题："
                   f"{first['path']} {first['message']}")


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


def _qc(plan: dict, site: dict) -> dict:
    """Deterministic figures only. This never says a design is good."""
    try:
        ck = check_plan(plan, site)
    except Exception as exc:  # a malformed draft becomes a blocker, not a crash
        return {"blocker": 1, "major": 0, "area_gap_sqm": 0.0,
                "issues": [{"severity": "blocker", "rule_id": "GEO-000",
                            "message": f"几何校验无法处理这份数据：{type(exc).__name__}: {exc}"}],
                "metrics": {"zone_area_sum_sqm": 0.0, "area_table_sum_sqm": 0.0},
                "tool_error": True}
    m = ck["metrics"]
    # ARC-02: single reconciliation basis = design scope, not zone-vs-table.
    gap = m.get("area_reconciliation_gap_sqm")
    if gap is None:
        gap = abs(m.get("zone_area_sum_sqm", 0) - m.get("area_table_sum_sqm", 0))
    return {
        "blocker": sum(1 for i in ck["issues"] if i["severity"] == "blocker"),
        "major": sum(1 for i in ck["issues"] if i["severity"] == "major"),
        "area_gap_sqm": round(float(gap), 1),
        "issues": ck["issues"],
        "metrics": m,
    }


def _worse(base: dict, now: dict) -> tuple[bool, str]:
    """Did the revision get measurably worse than the reference version?"""
    if now["blocker"] > base["blocker"]:
        return True, f"blocker 从 {base['blocker']} 增到 {now['blocker']}"
    if now["blocker"] == base["blocker"] and now["major"] > base["major"]:
        return True, f"major 从 {base['major']} 增到 {now['major']}"
    if now["area_gap_sqm"] > base["area_gap_sqm"] + 0.5:
        return True, f"面积对账差从 {base['area_gap_sqm']}㎡ 增到 {now['area_gap_sqm']}㎡"
    return False, ""


def _qc_text(q: dict) -> str:
    return f"blocker {q['blocker']} / major {q['major']} / 面积差 {q['area_gap_sqm']}㎡"


def _locked_ids(plan: dict, feedback_text: str = "") -> list[str]:
    """Objects locked by default (arrival/entrance, main route, display focus).

    Stair / bathroom / windows are additionally protected by geometry keep-out
    checks; here we protect design objects the boss told us to keep.
    """
    ids: set[str] = set()
    for z in (plan.get("zones") or []):
        if isinstance(z, dict) and z.get("role") == "arrival":
            ids.add(str(z.get("id")))
    # The route itself is NOT locked wholesale: review issues legitimately ask
    # for width/path changes. The entrance condition is protected by the CIR-004
    # geometry check instead (route must still reach the entrance band).
    for f in (plan.get("furniture") or []):
        if isinstance(f, dict) and any(k in str(f.get("id", "")).lower()
                                       for k in ("focal", "hero", "display", "entry")):
            ids.add(str(f.get("id")))
    # "保留 X" in a boss message locks the named object id when it exists
    if "保留" in feedback_text:
        known = {str(o.get("id")) for g in ("zones", "furniture", "circulation", "platforms")
                 for o in (plan.get(g) or []) if isinstance(o, dict)}
        for token in feedback_text.replace("，", " ").replace("、", " ").split():
            t = token.strip("。；;,. ")
            if t in known:
                ids.add(t)
    return sorted(ids)


class Studio:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or Store()
        self._running: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ seeding
    def seed_from_fixtures(self) -> list[str]:
        """Insert-only seed. Restarting NEVER rewrites existing project facts."""
        from pathlib import Path
        root = Path(__file__).resolve().parents[3] / "fixtures" / "studio" / "projects"
        ids = []
        for f in sorted(root.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            self.store.ensure_project(
                data["project_id"], data["name"], data["site"], data["requirement"],
                (data.get("golden_reference") or {}).get("path"),
                source_project_id=data.get("source_project_id") or data["project_id"],
                mapping_note=(data.get("id_mapping_note") or
                              "本机 Studio 实验项目；与主系统项目 ID 显式一一映射，"
                              "尚未接入团队/NAS 服务，不冒称生产支持"))
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
             "context_chars": len(context), "instruction": instruction,
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
                # ARC-03: no character truncation of structured tool output.
                compact = json.dumps(result, ensure_ascii=False)
                ev.append({"type": "tool", "name": name, "args": args, "result": compact})
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": compact})
                self.store.add_message(project_id, role.id, "tool",
                                       f"调用工具 `{name}`", task_id=task_id,
                                       evidence=[{"type": "tool", "name": name, "args": args,
                                                  "result_chars": len(compact)}],
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

    def _gate(self, project_id: str, title: str, detail: str,
              baseline_artifact_id: str | None = None,
              baseline_revision_uid: str | None = None) -> str:
        """Never open a second undecided gate; append to the one still waiting."""
        waiting = [g for g in self.store.gates(project_id) if g["status"] == "waiting"]
        if waiting:
            gid = waiting[-1]["id"]
            self.store.amend_gate(gid, detail, title=title)
            return gid
        return self.store.open_gate(project_id, title, detail,
                                    baseline_artifact_id=baseline_artifact_id,
                                    baseline_revision_uid=baseline_revision_uid)

    # ---------------------------------------------------------------- A1 script
    def run_a1(self, project_id: str, background: bool = True,
               expected_feedback_revision: int | None = None) -> dict:
        with self._lock:
            if project_id in self._running:
                return {"status": "already_running", "project_id": project_id}
            self._running.add(project_id)
        project = self.store.get_project(project_id)
        if not project:
            with self._lock:
                self._running.discard(project_id)
            raise KeyError(project_id)

        st = self.store
        expected = (expected_feedback_revision if expected_feedback_revision is not None
                    else st.feedback_revision(project_id))
        eff = st.effective_requirement(project_id)
        ih = input_hash(project_id, expected, eff)
        group_id = new_id("candgroup")

        def work() -> None:
            prior = sum((r["tokens_in"] or 0) + (r["tokens_out"] or 0)
                        for r in st.runs(project_id) if r["status"] != "running")
            client = Client(project_tokens=prior)
            run_id = st.start_run(project_id, client.config.model,
                                  input_hash_value=ih,
                                  expected_feedback_revision=expected,
                                  candidate_group_id=group_id)
            status, error = "succeeded", None
            stats = {"images_sent": 0, "images_generated": 0, "calls": 0}
            try:
                self._scenario(project, client, run_id, group_id, expected, ih, stats)
            except BudgetExceeded as exc:
                status, error = "budget_stopped", str(exc)
                st.add_message(project_id, "P", "gate", f"预算闸口：{exc}",
                               evidence=[{"type": "budget"}])
                self._gate(project_id, "预算已到上限", str(exc))
            except SupersededRun as exc:
                # ARC-04: a late result from a stale input never becomes current.
                status, error = "superseded", str(exc)
                affected = st.invalidate_artifacts(run_id)
                st.add_message(project_id, "P", "note",
                               f"本轮输入已被新留言/取消取代，结果不进入当前版本：{exc}"
                               f"；已标记 {affected} 份本轮产物为 superseded（历史字节保留）。",
                               evidence=[{"type": "superseded", "run_id": run_id,
                                          "expected_feedback_revision": expected,
                                          "current_feedback_revision": st.feedback_revision(project_id)}])
            except IncompleteArtifact as exc:
                status, error = "incomplete", str(exc)
                detail = (f"本轮没有交出可用成果：{exc}。按老板的规矩不算通过，"
                          "不进入下一步，也不把空方案摆到成果栏。请决定重跑还是换做法。")
                st.add_message(project_id, "P", "gate", detail,
                               evidence=[{"type": "incomplete", "reason": str(exc)}])
                self._gate(project_id, "本轮未完成：请决定重跑还是换做法", detail)
            except ModelError as exc:
                status, error = "model_failed", str(exc)
                detail = f"模型通道问题，回路中断：{exc}"
                st.add_message(project_id, "P", "gate", detail,
                               evidence=[{"type": "channel"}])
                self._gate(project_id, "通道中断：请决定是否重跑", detail)
            except Exception as exc:  # noqa: BLE001 - never lose the trace
                status, error = "failed", f"{type(exc).__name__}: {exc}"
                st.add_message(project_id, "P", "gate",
                               f"回路异常中断：{error}",
                               evidence=[{"type": "trace", "detail": traceback.format_exc()[-1500:]}])
                self._gate(project_id, "回路异常中断：请决定是否重跑", error)
            finally:
                # Re-check at the end: input may have changed mid-run.
                stale = st.feedback_changed_since(project_id, expected) or st.is_cancelled(run_id)
                if stale and status == "succeeded":
                    status = "superseded"
                    error = "运行结束后发现更新的老板输入或取消请求；本轮结果不成为当前版本"
                    affected = st.invalidate_artifacts(run_id)
                    st.add_message(project_id, "P", "note", error + f"（{affected} 份产物标记失效）",
                                   evidence=[{"type": "superseded", "run_id": run_id}])
                st.finish_run(run_id, status, client.usage.tokens_in,
                              client.usage.tokens_out, error,
                              calls=client.usage.calls,
                              images_sent=stats["images_sent"],
                              images_generated=stats["images_generated"],
                              cost_amount=None,
                              cost_status="unknown_no_price_table")
                with self._lock:
                    self._running.discard(project_id)

        if background:
            threading.Thread(target=work, daemon=True, name=f"studio-{project_id}").start()
            return {"status": "started", "project_id": project_id,
                    "expected_feedback_revision": expected, "input_hash": ih}
        work()
        return {"status": "finished", "project_id": project_id,
                "expected_feedback_revision": expected, "input_hash": ih}

    # ------------------------------------------------------------------ helpers
    def _assert_current(self, project_id: str, run_id: str, expected: int) -> None:
        if self.store.feedback_changed_since(project_id, expected) \
                or self.store.is_cancelled(run_id):
            raise SupersededRun("已有新的老板输入或本轮被取消")

    def _ctx(self, project: dict) -> str:
        pid = project["id"]
        site = project["site"]
        req = self.store.effective_requirement(pid)
        addenda = req.get("effective_addenda") or []
        feedback_lines = "\n".join(
            f"  - [v{a['revision_no']}/{a['kind']}/{a['feedback_id']}] {a['text']}"
            for a in addenda) or "  （无）"
        return (
            f"【项目】{project['name']}（studio id={pid}，主系统映射="
            f"{project.get('source_project_id') or pid}；本机实验服务，不代表团队/NAS 已支持）\n"
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
            f"【老板后续留言 · 版本化有效需求（修订必须读取）】\n{feedback_lines}\n"
            f"【有效输入哈希】{req.get('effective_input_hash')}\n"
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
    def _scenario(self, project: dict, client: Client, run_id: str, group_id: str,
                  expected: int, ih: str, stats: dict) -> None:
        pid = project["id"]
        st = self.store
        ctx = self._ctx(project)
        site = project["site"]
        feedback_items = st.feedback(pid)
        boss_feedback = [{"feedback_id": f["id"], "revision_no": f["revision_no"],
                          "kind": f["kind"], "text": f["text"]} for f in feedback_items]

        # 0. P plans the work
        self._assert_current(pid, run_id, expected)
        task_p = st.create_task(pid, "P", "拆解本项目：这一轮做什么", run_id=run_id)
        self._speak(
            ROLES["P"], client, pid, task_p,
            "老板刚把这个项目交给我们，还没给任何方案。请用 3–5 句话说明：这一轮先做什么、交给谁、"
            "交付物是什么、什么算做完。不要复述场地数据，不要现在做设计判断。",
            context=ctx, kind="task", label="任务拆解", max_steps=2)
        st.update_task(task_p, "done")

        # 1. D1 brief
        task_d1 = st.create_task(pid, "D1", "产出设计任务书", run_id=run_id)
        brief_raw = self._speak(
            ROLES["D1"], client, pid, task_d1,
            "请产出任务书，只输出 JSON：{\"goal\":\"一句话目标\",\"must_have\":[\"...\"],"
            "\"site_facts\":[\"...\"],\"budget\":\"...\",\"inferences\":[\"你自己加的判断，标明推断\"],"
            "\"open_questions\":[\"必须问老板的\"]}。must_have 要能一条条对回老板原话与后续留言。",
            context=ctx, tools=self._tools_for(project, "D1")[0],
            handlers=self._tools_for(project, "D1")[1], json_only=True, kind="artifact",
            label="任务书", max_steps=4)
        brief = _safe_json(brief_raw)
        if not brief.get("goal"):
            raise IncompleteArtifact("D1 没有交出带 goal 的任务书")
        st.save_artifact(pid, "brief", brief, "D1", task_id=task_d1, run_id=run_id,
                         candidate_group_id=group_id, input_hash_value=ih)
        st.update_task(task_d1, "done")

        # 2. D2 <-> D3 discussion before drawing
        task_talk = st.create_task(pid, "D2", "与概念设计对齐（动手前讨论）", run_id=run_id)
        q = self._speak(
            ROLES["D2"], client, pid, task_talk,
            "还没开始排平面。你先问概念设计（D3）两个具体问题：这个项目你打算怎么让人记住它？"
            "天花和重点照明你想怎么做（这会影响我怎么留空和留高）？用 2–3 句话说，像同事说话。",
            context=ctx + f"\n【任务书完整事实】{json.dumps(brief, ensure_ascii=False)}",
            kind="discussion", label="向概念设计提问", max_steps=2)
        a = self._speak(
            ROLES["D3"], client, pid, task_talk,
            "空间规划（D2）刚问你：" + q + "\n请直接回答他，2–4 句话，说清你的叙事方向和天花/灯光的打算。"
            "不要现在出完整概念，也不要替他排平面。",
            context=ctx, kind="discussion", label="回答空间规划", max_steps=2)
        st.update_task(task_talk, "done")

        # 3. D2 two options — full contract validation, no truncation
        task_d2 = st.create_task(pid, "D2", "出两个拓扑不同的空间候选", run_id=run_id)
        options: dict[str, dict] = {}
        for opt in ("A", "B"):
            self._assert_current(pid, run_id, expected)
            a_summary = ""
            if opt == "B" and options.get("A"):
                # Q06: B gets A's structural summary (complete object facts).
                a_summary = ("\n【候选 A 结构摘要（必须实质不同）】\n"
                             + validation.structural_summary(options["A"]["plan"]))
            raw = self._speak(
                ROLES["D2"], client, pid, task_d2,
                f"请产出候选 {opt}。要求：\n"
                f"- 与另一个候选在拓扑上不同（入口关系、重点展台位置、动线形状至少两项不同）；\n"
                f"- 严格按模型提案契约只输出 JSON（spatial-plan-proposal.v1）："
                f"strategy/zones/circulation/platforms/ceiling/furniture/area_table/"
                f"open_questions/standards_cited；不要写 project_id/revision/author/批准或采用指针；\n"
                f"- zones[].polygon 用 mm 的 [[x,y],...]，area_sqm 与轮廓一致；天花要有灯槽与灯具点位；\n"
                f"- 至少 5 个分区、3 件家具、2 处真实非直角几何（斜边/圆角展台），"
                f"每条声明绑定具体对象 id；\n"
                f"- 面积表合计必须对齐【可布置范围】= 外框面积减去保留楼梯/卫生间，"
                f"功能区之外的面积单列『通道及其他/未分配』并写真实数值，不得隐藏；\n"
                f"- 家具只能用目录里的真实 catalog_id；动线必须连接入口并接入分区；\n"
                f"- {self._TOOL_BUDGET}\n"
                f"- 交付前用 validate_plan 自检一次，把 blocker 改掉。",
                context=(ctx + f"\n【任务书完整事实】{json.dumps(brief, ensure_ascii=False)}\n"
                               f"【与概念的讨论】{a}" + a_summary),
                tools=self._tools_for(project, "D2")[0], handlers=self._tools_for(project, "D2")[1],
                json_only=True, kind="artifact", label=f"候选 {opt}", max_steps=5)
            plan = _safe_json(raw)
            report = validation.validate_proposal(
                plan, project=project, option_id=opt, revision=1, parent_revision=None)
            check_id = st.save_check_report(pid, report, run_id=run_id)
            if not report["ok"]:
                # Raw bytes + full diagnostic retained, but NEVER a valid candidate.
                st.save_artifact(
                    pid, "spatial-plan-raw", {"raw_text": raw, "parsed": plan}, "D2",
                    option_id=opt, revision=1, task_id=task_d2, status="invalid_raw",
                    run_id=run_id, candidate_group_id=group_id, input_hash_value=ih,
                    check_report_id=check_id, contract_status="invalid_raw", diagnostics=report)
                st.add_message(
                    pid, "D2", "note",
                    f"候选 {opt} 契约校验未通过（{report['stage']} 阶段，"
                    f"{len(report['errors'])} 条），原始输出与诊断已保留，不进成果栏有效候选。\n"
                    + report["repair_feedback"],
                    task_id=task_d2,
                    evidence=[{"type": "contract_diagnostic", "stage": report["stage"],
                               "errors": report["errors"], "check_report_id": check_id}])
                raise IncompleteArtifact(f"候选 {opt} 契约无效：{report['repair_feedback'][:300]}")
            if opt == "B" and options.get("A"):
                diff = validation.substantive_difference(options["A"]["plan"], report["plan"])
                if not diff["substantive"]:
                    st.save_artifact(
                        pid, "spatial-plan-raw", {"raw_text": raw, "parsed": plan,
                                                  "difference": diff}, "D2",
                        option_id=opt, revision=1, task_id=task_d2, status="invalid_raw",
                        run_id=run_id, candidate_group_id=group_id, input_hash_value=ih,
                        check_report_id=check_id, contract_status="invalid_raw",
                        diagnostics={"reason": "homogeneous_candidates", "difference": diff})
                    raise IncompleteArtifact("候选 B 与 A 结构签名相同：仅换名/配色/顺序/无意义位移不算新拓扑")
            plan = report["plan"]  # program-injected identity
            uid = new_id("revuid")
            aid = st.save_artifact(
                pid, "spatial-plan", plan, "D2", option_id=opt, revision=1,
                task_id=task_d2, status="valid_candidate", run_id=run_id,
                candidate_group_id=group_id, revision_uid=uid,
                input_hash_value=ih, check_report_id=check_id,
                contract_status="valid_candidate",
                diagnostics={"contract_report": report,
                             "difference_vs_A": diff if opt == "B" else None})
            st.save_artifact(
                pid, "plan-sketch",
                {"svg": sketch.render(plan, site,
                                      f"候选 {opt} · {plan.get('strategy', {}).get('name', '')}")},
                "D2", option_id=opt, revision=1, task_id=task_d2,
                status="valid_candidate", run_id=run_id,
                candidate_group_id=group_id, input_hash_value=ih)
            options[opt] = {"id": aid, "plan": plan, "revision_uid": uid,
                            "check_report_id": check_id}
            st.add_message(
                pid, "D2", "note",
                f"候选 {opt}「{plan['strategy']['name']}」已通过四级契约校验并出图："
                f"{len(plan['zones'])} 个分区、{len(plan.get('furniture') or [])} 件家具；"
                f"基线 id={aid} / revision_uid={uid}。",
                task_id=task_d2,
                evidence=[{"type": "artifact", "id": aid, "revision": 1,
                           "revision_uid": uid, "check_report_id": check_id,
                           "contract_status": "valid_candidate"}])
        st.update_task(task_d2, "done")

        # 4. R reviews — full object facts + explicit baseline ids + issue ids
        task_r = st.create_task(pid, "R", "评审两个候选", run_id=run_id)
        review_context = (
            ctx
            + "\n【候选 A 基线】id=" + options["A"]["id"]
            + " / revision_uid=" + options["A"]["revision_uid"] + "\n"
            + validation.structural_summary(options["A"]["plan"])
            + "\n【候选 B 基线】id=" + options["B"]["id"]
            + " / revision_uid=" + options["B"]["revision_uid"] + "\n"
            + validation.structural_summary(options["B"]["plan"]))
        review_raw = self._speak(
            ROLES["R"], client, pid, task_r,
            "请评审这两个候选。先调 list_standards 取全部规范，再逐条对照。\n"
            "只输出 JSON：{\"verdict\":\"advance|revise\",\"summary\":\"一段话：这两个方案各自的问题与优点\","
            "\"issues\":[{\"issue_id\":\"I1\",\"candidate\":\"A|B\",\"severity\":\"blocker|major|minor\","
            "\"objects\":[\"分区或家具 id\"],\"rule_id\":\"STD-00x\",\"evidence\":\"数据事实\","
            "\"suggest\":\"具体改法\"}],\"better\":\"A|B\",\"why\":\"为什么\"}。\n"
            "要求：至少 5 条 issue，必须挂到具体对象 id；不许写\"通过\"；如果方案平庸，要直说平庸在哪。",
            context=review_context,
            tools=self._tools_for(project, "R")[0], handlers=self._tools_for(project, "R")[1],
            json_only=True, kind="review", label="评审意见", max_steps=4)
        review = _safe_json(review_raw)
        issues = review.get("issues") or []
        if len(issues) < 3 or not review.get("summary"):
            raise IncompleteArtifact("总监没有交出可核对的结构化评审（意见少于 3 条或缺总结）")
        st.save_review(pid, options["A"]["id"], "R", str(review.get("verdict") or "revise"),
                       str(review.get("summary") or ""), issues)
        st.update_task(task_r, "done")

        # 4b. The director looks at our own images: impression only, never a verdict
        visual_summary, visual_images = "", 0
        try:
            images: list[tuple[bytes, str]] = []
            image_notes: list[dict] = []
            for opt in ("A", "B"):
                plan = options[opt]["plan"]
                svg = sketch.render(plan, site,
                                    f"候选 {opt} · {plan.get('strategy', {}).get('name', '')}")
                data = vision.svg_to_jpeg(svg)
                images.append((data, "image/jpeg"))
                image_notes.append({"type": "image", "label": f"候选 {opt} 平面草案",
                                    "source": "本轮候选设计数据 → sketch.render → 本地转位图",
                                    "bytes": len(data),
                                    "visible": "分区轮廓/名称/面积、展台、动线、家具方框",
                                    "not_visible": "天花、灯具、门窗、洁具、尺寸链、材质、灯光"})
            try:
                ref = vision.reference_jpeg()
                images.append((ref, "image/jpeg"))
                image_notes.append({"type": "image", "label": "案例参照",
                                    "source": vision.REFERENCE_NOTE, "bytes": len(ref)})
            except Exception as exc:
                image_notes.append({"type": "image_error", "label": "案例参照",
                                    "detail": str(exc)[:200]})
            visual_images = len(images)
            stats["images_sent"] = len(images)
            stats["images_generated"] = 2  # A/B sketches generated locally
            prompt = (
                "下面是本项目自己生成的图：前两张是本轮候选 A / B 的平面草案（由候选设计数据程序绘制），"
                "第三张是案例参照（宁波方案A第3版效果图，人工编写的手工样板，只作观感对比，不是系统成果）。\n"
                "【图面可见范围声明】草案缩略图只画分区轮廓/名称/面积、展台、动线与家具方框；"
                "制图器没有画天花与灯具，也没有画门窗、洁具、尺寸链、材质。因此『图上看不到天花』"
                "不能推断模型数据里没有天花；请先检查 ceiling 数据，再评价表达，不要据图面缺失写数据结论。\n"
                "请以设计总监身份做看图自评：分别说每个候选看得到什么、有没有明显的方块堆叠感；"
                "再和案例参照对比，指出最接近与差得最远的一处。\n"
                "每条挂到具体对象或图面位置；只写看得见的观感，不要猜数据，不要写「通过」或「建议通过」，"
                "不要给合格判定，也不要用检查清单打分。\n"
                "只输出 JSON：{\"summary\":\"一段话总观感\",\"observations\":[{\"target\":\"A|B|案例对比\","
                "\"observation\":\"看到什么\",\"gap\":\"与案例的差距\",\"suggest\":\"若认同可怎么改\"}],"
                "\"limits\":\"你看不出来的地方\"}。")
            resp = client.chat_vision(
                [{"role": "system", "content": ROLES["R"].system},
                 {"role": "user", "content": prompt}],
                images, temperature=0.45, max_tokens=1400, json_only=True)
            vr = _safe_json(resp["content"])
            if vr.get("parse_error"):
                visual_summary = resp["content"][:600]
            else:
                visual_summary = str(vr.get("summary") or "")[:600]
            st.add_message(
                pid, "R", "visual-review", resp["content"], task_id=task_r,
                evidence=[{"type": "vision", "model": resp["model"],
                           "image_count": resp["image_count"], "images": image_notes,
                           "usage": resp["usage"],
                           "visible_scope": "草案缩略图未画天花/门窗/洁具/尺寸链；不可据此推断数据缺失",
                           "note": "观感意见，不作判据；不得据此宣布通过"}] + image_notes,
                tokens_in=resp["usage"]["in"] or 0,
                tokens_out=resp["usage"]["out"] or 0,
                model=resp["model"])
        except Exception as exc:
            st.add_message(
                pid, "R", "note",
                f"看图自评没能完成：{type(exc).__name__}: {str(exc)[:200]}。"
                "这一项不计入评审结论，也不假装看过图。",
                evidence=[{"type": "vision_failed", "detail": str(exc)[:300]}])

        # 5. Revision: boss feedback + per-issue linkage + whitelisted patches
        target = review.get("better") if review.get("better") in ("A", "B") else "A"
        task_rev = st.create_task(pid, "D2", f"逐条回应评审并修订候选 {target}",
                                  round_no=2, run_id=run_id)
        base_plan = options[target]["plan"]
        base_uid = options[target]["revision_uid"]
        base_aid = options[target]["id"]
        best_qc, best_rev = _qc(base_plan, site), 1
        prev_qc = best_qc
        current_plan, current_rev, current_aid = base_plan, 1, base_aid
        current_uid = base_uid
        new_plan, aid2 = base_plan, current_aid
        now_qc = _qc(base_plan, site)
        rework_count = 0
        rework_log: list[dict] = []
        responses: list[dict] = []
        accepted = 0
        changed: list[str] = []
        accepted_any = False
        stop_reason = ""
        feedback_text = "；".join(f["text"] for f in boss_feedback)
        lock_ids = _locked_ids(base_plan, feedback_text)
        revision_hash = revision_mod.revision_input_hash(
            base_plan, issues, boss_feedback, base_aid, base_uid)

        for attempt in range(1, 2 + MAX_AUTO_REWORK):
            self._assert_current(pid, run_id, expected)
            if attempt == 1:
                task_id = task_rev
                instruction = (
                    f"总监的评审意见（必须逐条回应）：{json.dumps(issues, ensure_ascii=False)}\n"
                    f"【老板留言 · 版本化有效需求，必须进修订输入】"
                    f"{json.dumps(boss_feedback, ensure_ascii=False)}\n"
                    f"【修订基线】artifact id={base_aid} / revision_uid={base_uid} / "
                    f"输入哈希={revision_hash}\n"
                    f"【基线完整对象事实（未截断）】\n{validation.structural_summary(base_plan)}\n"
                    f"请对候选 {target} 做两件事：① 逐条回应（接受就写改了什么，不接受写清理由）；"
                    f"② 优先输出白名单 patch 数组，由程序应用并复算生成完整新版本：\n"
                    "只输出 JSON：{\"responses\":[{\"issue_id\":\"I1\",\"action\":\"accept|reject\","
                    "\"change\":\"改了什么\",\"reason\":\"理由\"}],"
                    "\"patch\":[{\"op\":\"update|add|remove\",\"group\":\"zones|furniture|circulation|"
                    "platforms|ceiling.fixtures|area_table\",\"id\":\"对象id\",\"fields\":{...},"
                    "\"reason\":\"remove 必填\"}]}。\n"
                    "- 白名单只允许对象设计字段，不得写 project_id/revision/批准/采用/价格来源；\n"
                    "- 被接受的 issue 必须真的改到它点名的对象上；无关对象保持原状；删除必须写理由；\n"
                    "- 锁定对象（入口/主动线/保留条件）不得改动："
                    f"{json.dumps(lock_ids, ensure_ascii=False)}；\n"
                    "- 面积表改后仍须对齐可布置范围，几何与动线仍须通过 validate_plan；\n"
                    f"- {self._TOOL_BUDGET}\n"
                    f"【总监看图观感（只作参考，不作判据）】{visual_summary or '本轮未取得观感意见'}\n"
                    "- 只改被指出的问题与老板留言，不要顺手重做整个方案。")
                label = "逐条回应 + 修订"
                context = ctx
            else:
                task_id = st.create_task(
                    pid, "D2", f"自动打回第 {rework_count} 轮重做",
                    round_no=1 + rework_count, run_id=run_id)
                instruction = (
                    f"这是第 {rework_count} 次自动打回。前一稿的问题：{stop_reason}\n"
                    f"【上一稿完整对象事实（未截断）】\n"
                    f"{validation.structural_summary(current_plan)}\n"
                    "请输出白名单 patch 数组或完整方案 JSON。\n"
                    "硬性要求：① 结构/语义/几何/锁定四级契约全过；"
                    "② 面积表合计对齐可布置范围，未分配部分显式列出；"
                    "③ 分区互不重叠、动线连接入口并接入分区；④ 保留天花灯槽与灯具点位；"
                    "⑤ 锁定对象不变；⑥ 不要新增 blocker。\n"
                    f"- {self._TOOL_BUDGET}\n"
                    "- 交付前用 validate_plan 自检一次。")
                label = f"自动打回第 {rework_count} 轮重做"
                context = ctx
            raw = self._speak(
                ROLES["D2"], client, pid, task_id, instruction, context=context,
                tools=self._tools_for(project, "D2")[0],
                handlers=self._tools_for(project, "D2")[1],
                json_only=True, kind="revise", label=label, max_steps=5)
            data = _safe_json(raw)
            if attempt == 1:
                responses = data.get("responses") or []
                accepted = sum(1 for r in responses
                               if isinstance(r, dict) and r.get("action") == "accept")

            patch_result = None
            patch = data.get("patch")
            if isinstance(patch, list) and patch:
                candidate, patch_errors, patch_audit = revision_mod.apply_patch(current_plan, patch)
            else:
                # full-output fallback: same integrity checks still apply
                candidate = data.get("plan") if isinstance(data.get("plan"), dict) else data
                patch_errors, patch_audit = [], {"mode": "full_output"}

            problem = ""
            integrity = None
            report = None
            if patch_errors:
                problem = "白名单 patch 不合法：" + "；".join(
                    e["message"] for e in patch_errors[:3])
            elif not isinstance(candidate, dict):
                problem = "修订稿不是 JSON 对象"
            else:
                integrity = revision_mod.verify_revision_integrity(
                    current_plan, candidate, responses=responses if attempt == 1 else None,
                    issues=issues if attempt == 1 else None,
                    lock_object_ids=lock_ids,
                    boss_feedback=boss_feedback if attempt == 1 else None)
                report = validation.validate_proposal(
                    candidate, project=project, option_id=target,
                    revision=attempt + 1, parent_revision=current_rev,
                    lock_object_ids=lock_ids, previous_plan=current_plan)
                if attempt == 1 and not responses:
                    problem = "没有逐条回应评审意见"
                elif not report["ok"]:
                    problem = f"修订稿契约无效（{report['stage']}）：{report['repair_feedback'][:400]}"
                elif not integrity["ok"]:
                    problem = "修订完整性未通过：" + "；".join(
                        e["message"] for e in integrity["errors"][:3])
                elif boss_feedback and attempt == 1 and not integrity["boss_feedback_resolutions"]:
                    problem = "老板留言未进入修订输入"

            if not problem:
                changed_preview = _changed_objects(current_plan, report["plan"])
                if attempt == 1 and accepted and not changed_preview:
                    problem = f"逐条回应接受了 {accepted} 条，但 v1→v2 没有任何对象发生变化"
                else:
                    next_rev = attempt + 1
                    uid = new_id("revuid")
                    check_id = st.save_check_report(pid, {
                        "kind": "revision", "contract_report": report,
                        "integrity": integrity, "patch_audit": patch_audit,
                        "revision_input_hash": revision_hash,
                        "baseline_artifact_id": base_aid,
                        "baseline_revision_uid": base_uid,
                    }, run_id=run_id)
                    aid = st.save_artifact(
                        pid, "spatial-plan", report["plan"], "D2", option_id=target,
                        revision=next_rev, parent_revision=current_rev, task_id=task_id,
                        status="valid_candidate", run_id=run_id,
                        candidate_group_id=group_id, revision_uid=uid,
                        parent_revision_uid=current_uid if attempt > 1 else base_uid,
                        input_hash_value=revision_hash, check_report_id=check_id,
                        contract_status="valid_candidate",
                        diagnostics={"contract_report": report, "integrity": integrity,
                                     "patch_audit": patch_audit})
                    st.save_artifact(
                        pid, "plan-sketch",
                        {"svg": sketch.render(
                            report["plan"], site,
                            f"候选 {target} v{next_rev} · "
                            f"{report['plan'].get('strategy', {}).get('name', '')}")},
                        "D2", option_id=target, revision=next_rev,
                        parent_revision=current_rev, task_id=task_id,
                        status="valid_candidate", run_id=run_id,
                        candidate_group_id=group_id, input_hash_value=revision_hash)
                    current_uid = uid
                    changed = _changed_objects(base_plan, report["plan"])
                    st.add_message(
                        pid, "D2", "note",
                        (f"已逐条回应 {len(responses)} 条意见，接受 {accepted} 条"
                         f"（逐项复核 {integrity['accepted_issues_verified']}/"
                         f"{integrity['accepted_issues_total']} 条有对象 diff 支撑）；"
                         if attempt == 1 else f"第 {rework_count} 次自动重做完成；")
                        + f"老板留言 {len(boss_feedback)} 条已进入修订输入；"
                        + f"v{next_rev} {_qc_text(_qc(report['plan'], site))}，"
                        + f"相对上一版改动 {len(changed_preview)} 个对象："
                        + f"{'、'.join(changed_preview[:6]) or '无'}。",
                        task_id=task_id,
                        evidence=[{"type": "artifact", "id": aid, "revision": next_rev,
                                   "revision_uid": uid},
                                  {"type": "responses", "items": responses},
                                  {"type": "diff", "changed": changed_preview},
                                  {"type": "issue_resolutions",
                                   "items": integrity["issue_resolutions"]},
                                  {"type": "boss_feedback_resolutions",
                                   "items": integrity["boss_feedback_resolutions"]},
                                  {"type": "patch_audit", "detail": patch_audit}])
                    if task_id != task_rev:
                        st.update_task(task_id, "done")
                        rework_log.append({"rev": next_rev,
                                           "qc": _qc_text(_qc(report["plan"], site)),
                                           "reason": "重做后被接受"})
                    qc_cand = _qc(report["plan"], site)
                    prev_qc, now_qc = qc_cand, qc_cand
                    current_plan, current_rev, current_aid = report["plan"], next_rev, aid
                    new_plan, aid2 = report["plan"], aid
                    accepted_any = True
                    if not _worse(best_qc, qc_cand)[0]:
                        best_qc, best_rev = qc_cand, next_rev
                    break

            if problem:
                stop_reason = problem
                st.save_artifact(
                    pid, "spatial-plan-raw", {"raw_text": raw, "parsed": candidate},
                    "D2", option_id=target, revision=current_rev + 1, task_id=task_id,
                    status="invalid_raw", run_id=run_id, candidate_group_id=group_id,
                    input_hash_value=revision_hash,
                    contract_status="invalid_raw",
                    diagnostics={"reason": problem,
                                 "contract_report": report,
                                 "integrity": integrity,
                                 "patch_errors": patch_errors})
                if rework_count >= MAX_AUTO_REWORK:
                    break
                rework_count += 1
                detail = (
                    f"数字/契约校验判定这一稿不能用：{problem}。"
                    f"当前基准 v{best_rev} {_qc_text(best_qc)}。\n"
                    f"按公司规矩自动打回第 {rework_count} 轮（最多 {MAX_AUTO_REWORK} 轮，"
                    "之后第 3 轮必须由老板决定）。只修这些问题，不要重做整个方案。")
                st.add_message(
                    pid, "P", "rework", detail, task_id=task_rev,
                    evidence=[{"type": "qc", "reference_revision": best_rev,
                               "current_revision": current_rev,
                               "reference": _qc_text(best_qc),
                               "reason": problem},
                              {"type": "rule", "id": "AUTO-REWORK-01",
                               "rule": "修订变差或无效自动打回，最多 2 轮，第 3 轮交老板"}])
        # ARC-04: no valid revision -> task is NOT simply "done".
        st.update_task(task_rev, "no_valid_revision" if not accepted_any else "done",
                       {"accepted_revision": accepted_any, "rework_count": rework_count,
                        "stop_reason": stop_reason or None})
        still_worse, why_still = _worse(best_qc, now_qc)

        # 6. P opens the gate — bound to a concrete baseline, still the boss decides
        b0, m0 = best_qc["blocker"], best_qc["major"]
        b1, m1 = now_qc["blocker"], now_qc["major"]
        if not accepted_any:
            qc_line = (f"程序硬校验：基准 v{best_rev} {_qc_text(best_qc)}；"
                       f"自动打回 {rework_count} 轮后仍没有一稿被接受"
                       f"（最后拦下的原因：{stop_reason or '无'}）。"
                       "本轮不产出修订版，不能当作可用方案。程序只量几何与面积，不替老板判断好不好看。")
        else:
            qc_line = (f"程序硬校验：基准 v{best_rev} {_qc_text(best_qc)}；"
                       f"当前 v{current_rev} {_qc_text(now_qc)}。"
                       + (f"当前版本仍比基准差（{why_still}），不能当作可用方案。" if still_worse
                          else "当前版本没有比基准更差，但仍不等于设计合格。")
                       + "程序只量几何与面积，不替老板判断好不好看。")
        rework_text = "；".join(f"v{r['rev']} {r['qc']}" for r in rework_log)
        gate_title = (
            f"自动打回已用尽 {MAX_AUTO_REWORK} 轮仍无有效修订：请决定第 3 轮怎么做"
            if not accepted_any
            else f"自动打回已用尽 {MAX_AUTO_REWORK} 轮，方案仍变差：请决定第 3 轮怎么做"
            if rework_count >= MAX_AUTO_REWORK and still_worse
            else "本轮成果仍有硬伤：请决定是否继续打回" if b1
            else "选一个方向继续（A1 回路到此）")
        gate_detail = (
            f"总监建议：{review.get('verdict')}，倾向选择 {target}（{review.get('why') or ''}）。\n"
            f"本轮实数：2 个有效候选、{len(issues)} 条评审意见、{len(responses)} 条逐条回应、"
            f"老板留言 {len(boss_feedback)} 条、自动打回 {rework_count} 次"
            + (f"（{rework_text}）" if rework_text else "")
            + f"；被接受的修订版：{'v' + str(current_rev) if accepted_any else '无'}，"
            f"相对 v1 改动 {len(changed)} 个对象。\n"
            + (f"最后拦截原因：{stop_reason}\n" if stop_reason else "")
            + f"总监看图自评：发出 {visual_images} 张自家生成的图（含案例参照），"
            f"观感：{(visual_summary[:220] or '未完成，见时间线')}。观感不作判据。\n"
            f"本轮输入哈希 {ih}；有效需求版本 v{expected}；候选组 {group_id}。\n"
            f"{qc_line}\n"
            "注意：『允许继续试验』与『认可设计方向』都不等于设计通过；总监只能建议；"
            "流程走完不等于方案通过，是否成立由你决定。")
        gid = self._gate(pid, gate_title, gate_detail,
                         baseline_artifact_id=aid2,
                         baseline_revision_uid=current_uid)
        st.add_message(pid, "P", "gate", gate_detail,
                       evidence=[{"type": "gate", "id": gid,
                                  "baseline_artifact_id": aid2,
                                  "baseline_revision_uid": current_uid},
                                 {"type": "artifact", "id": aid2, "revision": current_rev},
                                 {"type": "qc", "v1": {"blocker": b0, "major": m0},
                                  "final": {"blocker": b1, "major": m1}},
                                 {"type": "rework", "count": rework_count,
                                  "log": rework_log},
                                 {"type": "stage_status",
                                  "flow_finished": True,
                                  "valid_artifact_exists": True,
                                  "waiting_user": True,
                                  "design_approved_by_user": False}])
        st.add_message(pid, "P", "note",
                       f"本轮流程走完。成果栏里有候选 A/B"
                       + (f" 与候选 {target} 的 v{current_rev}" if accepted_any
                          else "；本轮没有可用修订版")
                       + f"（自动打回 {rework_count} 次）；总监看图观感已留在时间线，"
                       "属观感不作判据。" + qc_line,
                       evidence=[{"type": "usage", "tokens": client.usage.total},
                                 {"type": "qc", "final_issues": now_qc["issues"][:6]},
                                 {"type": "vision", "image_count": visual_images}])
