"""W0/R1 + W0/R2: task resolution, explicit old baselines, structured locks,
deterministic objective rechecks.

Design rules (docs/26 sections 2, 4):
  * generate, revise and retry are DIFFERENT tasks. A revise loads the FULL
    plan of the artifact named by the feedback, never "the latest file".
  * An unusable baseline is an explicit conflict, never a silent substitution
    with a freshly generated A/B pair.
  * Locks are structured object/field records, not Chinese keyword hits on
    object names. Conflicts offer an alternative and never unlock themselves.
  * A measurable objective is rechecked by its rule (clear width, capacity,
    position, lock). Aesthetic objectives stay unknown + pending for the user.
    "Referenced in the diff" is NEVER recorded as "resolved".

No external calls, no design judgement. `unknown` is never filled with 0.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from . import geometry
from .tools import CATALOG

TASK_GENERATE = "generate"
TASK_REVISE = "revise"
TASK_CONFLICT = "conflict"

_DRAFT_IDENTITY = ("contract_version", "project_id", "option_id", "revision", "author")
_MIN_CLEAR_WIDTH_MM = getattr(geometry, "MIN_CLEAR_WIDTH_MM", 1200)

# rule_id -> (field, unit, object group(s) the rule can actually measure)
_RULE_SCOPES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "CIR-001": ("width_mm", "mm", ("circulation",)),
    "CIR-003": ("width_mm", "mm", ("circulation",)),
    "STD-001": ("rot", "degree", ("furniture",)),
    "STD-005": ("kelvin", "K", ("ceiling.fixtures", "ceiling.coves")),
    "AREA-002": ("area_sqm", "sqm", ("zones",)),
    "STD-004": ("sightline", "unknown", ("zones",)),  # not computable yet
}

_TEXT_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"净宽[^0-9\-]{0,14}(-?\d+(?:\.\d+)?)\s*mm", re.I), "CIR-001"),
    (re.compile(r"旋[到转至为设]*\s*(-?\d+(?:\.\d+)?)\s*(?:°|度)", re.I), "STD-001"),
    (re.compile(r"色温[^0-9\-]{0,14}(-?\d+(?:\.\d+)?)\s*K", re.I), "STD-005"),
    (re.compile(r"面积[^0-9\-]{0,14}(-?\d+(?:\.\d+)?)\s*(?:㎡|平米|平方米)", re.I), "AREA-002"),
]


def _sha(obj: Any) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ R1 tasks --
def resolve_task(st, project_id: str, expected_feedback_revision: int | None) -> dict:
    """Decide generate / revise / conflict from VERSIONED feedback only.

    Never guesses a baseline from the newest file. Returns a resolution with
    the complete baseline plan when the task is a revise.
    """
    rows = st.feedback(project_id)
    explicit = [f for f in rows if f.get("baseline_artifact_id")]
    pending = [f for f in explicit if not f.get("consumed_by_run")]
    consumed = [f for f in explicit if f.get("consumed_by_run")]

    if st.feedback_changed_since(project_id, expected_feedback_revision):
        return _conflict("concurrent_new_feedback",
                         f"运行开始时的有效需求版本 v{expected_feedback_revision} 已落后于当前 "
                         f"v{st.feedback_revision(project_id)}；晚到结果不得成为当前版本",
                         ["先取消/作废这一轮，再按最新留言开新任务",
                          "不要重放旧输入，也不要把旧结果写成新版"])
    if not pending:
        if consumed:
            last = consumed[-1]
            return _conflict(
                "feedback_already_consumed",
                f"反馈 {last['id']}（v{last['revision_no']}）已由 run "
                f"{last['consumed_by_run']} 消费；不得用新 run 重放同一反馈绕过最多 2 轮自动返工",
                ["请给一条新的老板留言并明确选择要续改的旧方案",
                 "或由老板在闸口决定第 3 轮怎么做",
                 "程序不会把这条旧反馈再当成一次新的续改任务"])
        return {"kind": TASK_GENERATE, "task_kind": TASK_GENERATE, "feedback": None,
                "baseline": None, "plan": None,
                "reason": "没有绑定旧基线的待续改反馈；本轮按 generate 处理"
                          "（文字留言仍进入有效需求与修订输入，不偷换为 revise）",
                "feedback_rows": rows}

    fb = pending[-1]
    art = st.artifact_by_id(fb["baseline_artifact_id"])
    if art is None:
        return _conflict("baseline_not_found",
                         f"反馈指定的旧基线产物 {fb['baseline_artifact_id']} 不存在",
                         ["在页面重新选择一份存在的有效候选", "不要回退到最新文件"])
    if art.get("project_id") and art["project_id"] != project_id:
        return _conflict("cross_project_baseline",
                         f"旧基线 {art['id']} 属于项目 {art['project_id']}，不是 {project_id}",
                         ["只在本项目内选择旧基线", "跨项目引用一律拒绝"])
    if art.get("kind") != "spatial-plan":
        return _conflict("baseline_not_spatial_plan",
                         f"旧基线 {art['id']} 是 {art.get('kind')}，不是空间方案",
                         ["选择候选 A/B 的空间方案产物"])
    if art.get("contract_status") != "valid_candidate" or art.get("status") in (
            "superseded", "invalid_raw"):
        return _conflict("baseline_invalid",
                         f"旧基线 {art['id']} 状态 {art.get('status')}/"
                         f"{art.get('contract_status')}，不是有效候选",
                         ["另选一份有效的候选", "历史失败稿只读保留，不作为续改基线"])
    if fb.get("baseline_revision_uid") and \
            fb["baseline_revision_uid"] != art.get("revision_uid"):
        return _conflict("baseline_uid_mismatch",
                         f"反馈携带的 revision_uid {fb['baseline_revision_uid']} 与旧基线 "
                         f"{art['id']} 的 {art.get('revision_uid')} 不一致",
                         ["重新选择该候选的当前版本", "不要猜版本或按时间取最近文件"])
    plan = art.get("payload")
    if not isinstance(plan, dict) or any(k not in plan for k in _DRAFT_IDENTITY):
        return _conflict("baseline_not_full_draft",
                         f"旧基线 {art['id']} 不是完整的 spatial-plan-draft.v1 交接文档",
                         ["选择通过四级校验的有效候选", "旧 legacy 草案不作为续改基线"])
    if plan.get("project_id") != project_id:
        return _conflict("cross_project_baseline",
                         f"旧基线文档内 project_id={plan.get('project_id')} 与本项目不一致",
                         ["只在本项目内选择旧基线"])
    return {"kind": TASK_REVISE, "task_kind": TASK_REVISE, "feedback": fb,
            "baseline": art, "plan": copy.deepcopy(plan), "feedback_rows": rows,
            "reason": f"按反馈 {fb['id']} 指定的旧基线 {art['id']} "
                      f"(revision_uid={art.get('revision_uid')}) 续改，不重新生成 A/B",
            "baseline_selection": fb.get("baseline_selection") or "explicit_pointer"}


def _conflict(code: str, detail: str, alternatives: list[str]) -> dict:
    return {"kind": TASK_CONFLICT, "task_kind": TASK_CONFLICT, "conflict_code": code,
            "conflict_detail": detail, "alternatives": alternatives,
            "feedback": None, "baseline": None, "plan": None,
            "reason": "旧基线不适用：明确冲突，不偷换、不自动重新生成 A/B"}


# ------------------------------------------------------------------- R1 locks --
def structured_locks(plan: dict, site: dict | None = None,
                     user_locks: list[dict] | None = None) -> dict:
    """Structured object/field locks. No Chinese keyword matching on names."""
    locks: list[dict] = []
    for z in (plan.get("zones") or []):
        if isinstance(z, dict) and z.get("role") == "arrival":
            locks.append({"object_id": str(z.get("id")), "fields": ["*"],
                          "source": "program:role_arrival",
                          "reason": "入口/到达区是需求中明确保留的空间条件"})
    for lk in (user_locks or []):
        if isinstance(lk, dict) and str(lk.get("object_id") or "").strip():
            locks.append({"object_id": str(lk["object_id"]),
                          "fields": list(lk.get("fields") or ["*"]),
                          "source": "user_explicit",
                          "reason": str(lk.get("reason") or "老板明确指定的保留对象/字段")})
    # de-duplicate by (object_id, fields)
    seen, uniq = set(), []
    for lk in locks:
        key = (lk["object_id"], tuple(lk["fields"]))
        if key not in seen:
            seen.add(key)
            uniq.append(lk)
    return {
        "locks": uniq,
        "lock_object_ids": sorted({lk["object_id"] for lk in uniq}),
        "keyword_matching_used": False,
        "site_keepout_delegated_to": ["LOCK-001 保留区几何 keep-out",
                                       "CIR-004 入口可达", "CIR-003 实测瓶颈"],
        "site_keepout_source": "site.stair / site.bath / site.entrance（结构化场地条件）",
        "note": "门/窗/柱网未在契约中建模，相关锁定覆盖为 unsupported，不视为通过",
    }


def _object_signature(plan: dict, object_id: str) -> str | None:
    groups = ("zones", "furniture", "circulation", "platforms")
    ceiling = plan.get("ceiling") if isinstance(plan.get("ceiling"), dict) else {}
    for group in groups + ("ceiling.coves", "ceiling.fixtures"):
        container = (ceiling.get(group.split(".", 1)[1]) if group.startswith("ceiling.")
                     else plan.get(group)) or []
        for o in container:
            if isinstance(o, dict) and str(o.get("id")) == object_id:
                return _sha(o)
    return None


def lock_conflicts(base: dict, candidate: dict, locks: dict) -> list[dict]:
    out = []
    for lk in locks.get("locks") or []:
        oid = lk["object_id"]
        b, a = _object_signature(base, oid), _object_signature(candidate, oid)
        changed = b != a
        if not changed:
            continue
        fields = lk["fields"]
        out.append({"object_id": oid, "fields": fields,
                    "source": lk["source"], "reason": lk["reason"],
                    "base_sha256_prefix": (b or "")[:12],
                    "candidate_sha256_prefix": (a or "")[:12],
                    "alternative": ("恢复该对象被锁定的字段；若确实无法同时满足，"
                                    "把冲突作为待决项交用户决定，程序不自行解除锁定")})
    return out


# -------------------------------------------------------------- R2 objectives --
def derive_text_objectives(text: str, *, source: str = "text_heuristic",
                           prefix: str = "O", object_ids: list[str] | None = None,
                           issue_id: str | None = None,
                           feedback_id: str | None = None) -> list[dict]:
    """Restricted, auditable parsing of MEASURABLE targets from natural text.

    Object identity is NEVER inferred from a Chinese object name: scope comes
    from the rule_id, and an explicit object id is used only when supplied.
    """
    out: list[dict] = []
    for pattern, rule_id in _TEXT_RULES:
        m = pattern.search(text or "")
        if not m:
            continue
        field, unit, scope = _RULE_SCOPES[rule_id]
        try:
            target = float(m.group(1))
        except (TypeError, ValueError):
            continue
        out.append({"objective_id": f"{prefix}{len(out) + 1}", "kind": "measurable",
                    "rule_id": rule_id, "field": field, "target": target, "unit": unit,
                    "objects_scope": list(scope), "object_ids": list(object_ids or []),
                    "source": source, "issue_id": issue_id,
                    "feedback_id": feedback_id,
                    "parsed_from": m.group(0)[:80],
                    "computable": rule_id != "STD-004"})
    return out


def derive_objectives(feedback_rows: list[dict], issues: list[dict] | None = None) -> list[dict]:
    """Collect objectives from structured feedback, text, and review issues."""
    out: list[dict] = []
    for fb in (feedback_rows or []):
        structured = fb.get("objectives") or []
        for i, obj in enumerate(structured):
            if isinstance(obj, dict) and obj.get("kind"):
                item = copy.deepcopy(obj)
                item.setdefault("objective_id", f"FB{fb.get('revision_no', '?')}-{i + 1}")
                item.setdefault("source", "structured")
                item.setdefault("feedback_id", fb.get("id"))
                item.setdefault("computable", item.get("kind") == "measurable")
                out.append(item)
        text = str(fb.get("text") or "")
        heuristics = derive_text_objectives(
            text, prefix=f"FB{fb.get('revision_no', '?')}-", object_ids=None,
            feedback_id=str(fb.get("id") or ""))
        # a structured objective with the same rule wins over the heuristic
        structured_rules = {o.get("rule_id") for o in structured}
        out.extend(o for o in heuristics if o["rule_id"] not in structured_rules)
        if not heuristics and not structured:
            out.append({"objective_id": f"FB{fb.get('revision_no', '?')}-A",
                        "kind": "aesthetic", "rule_id": "USER-JUDGEMENT",
                        "field": "user_judgement", "target": None, "unit": "n/a",
                        "objects_scope": [], "object_ids": [],
                        "source": "text_unparsed", "feedback_id": fb.get("id"),
                        "computable": False,
                        "note": "没有可计算目标（例如「更开放」「更有设计感」）；"
                                "只提供图面对比与模型意见，最终等用户确认"})
        elif re.search(r"保留|不动|保持", text):
            out.append({"objective_id": f"FB{fb.get('revision_no', '?')}-L",
                        "kind": "lock", "rule_id": "LOCK-REVISION",
                        "field": "locked_objects", "target": None, "unit": "n/a",
                        "objects_scope": [], "object_ids": [],
                        "source": "text_heuristic", "feedback_id": fb.get("id"),
                        "computable": True,
                        "note": "保留要求由结构化锁复核，不靠关键词命中对象名"})
    for i in (issues or []):
        if not isinstance(i, dict):
            continue
        text = f"{i.get('suggest') or ''} {i.get('evidence') or ''}"
        objs = [str(x) for x in (i.get("objects") or [])]
        found = derive_text_objectives(text, prefix=f"{i.get('issue_id', 'I')}-",
                                       source="review_issue", object_ids=objs,
                                       issue_id=str(i.get("issue_id") or ""))
        if found:
            out.extend(found)
        elif i.get("action") != "reject":
            out.append({"objective_id": f"{i.get('issue_id', 'I')}-A",
                        "kind": "aesthetic", "rule_id": "USER-JUDGEMENT",
                        "field": "user_judgement", "target": None, "unit": "n/a",
                        "objects_scope": objs, "object_ids": objs,
                        "source": "review_issue_unparsed",
                        "issue_id": str(i.get("issue_id") or ""),
                        "computable": False,
                        "note": "这条意见没有可计算目标；不可计算或尚未实现的复核写 unknown"})
    return out


def _plan_objects(plan: dict, scope: list[str], object_ids: list[str]) -> list[tuple[str, dict]]:
    ceiling = plan.get("ceiling") if isinstance(plan.get("ceiling"), dict) else {}
    out: list[tuple[str, dict]] = []
    # An EMPTY scope means "no object identity is claimed" (aesthetic target).
    # Never fall back to "all objects" — that would attach a vague opinion to
    # every changed object and fake a linkage. Explicit object_ids may still be
    # resolved across all groups.
    if scope:
        groups = tuple(scope)
    elif object_ids:
        groups = ("zones", "furniture", "circulation", "platforms",
                  "ceiling.coves", "ceiling.fixtures")
    else:
        groups = ()
    for group in groups:
        container = (ceiling.get(group.split(".", 1)[1]) if group.startswith("ceiling.")
                     else plan.get(group)) or []
        for o in container:
            if isinstance(o, dict) and str(o.get("id") or "") and \
                    (not object_ids or str(o["id"]) in object_ids):
                out.append((str(o["id"]), o))
    return out


def _measure(plan: dict, objective: dict, site: dict, catalog: dict) -> dict:
    """Re-measure an objective with the corresponding deterministic rule."""
    rule = objective.get("rule_id")
    field = objective.get("field")
    target = objective.get("target")
    scope = objective.get("objects_scope") or []
    ids = objective.get("object_ids") or []
    objs = _plan_objects(plan, scope, ids)
    catalog = catalog or {c["catalog_id"]: c for c in CATALOG}

    if rule in ("CIR-001", "CIR-003") and field == "width_mm":
        if not (isinstance(site, dict) and site.get("width_mm") and site.get("height_mm")):
            return {"rule_id": rule, "target": target, "measured": None,
                    "passing_object_ids": [], "rechecked": None,
                    "unknown_reason": "缺少场地边界，无法用几何复算实测净宽/瓶颈"}
        geo = geometry.check_geometry(plan, site, catalog=catalog)
        measured = {}
        for oid, o in objs:
            measured[oid] = {
                "declared_width_mm": o.get("width_mm"),
                "measured_clear_width_mm": geo["metrics"].get(
                    f"measured_clear_width_mm::{oid}"),
                "circulation_issues": [x["rule_id"] for x in geo["issues"]
                                       if oid in x["objects"]
                                       and x["rule_id"] in ("CIR-001", "CIR-003")],
            }
        passing = [oid for oid, m in measured.items()
                   if isinstance(m["declared_width_mm"], (int, float))
                   and float(m["declared_width_mm"]) >= float(target or 0)
                   and m["measured_clear_width_mm"] is not None
                   and float(m["measured_clear_width_mm"]) >= _MIN_CLEAR_WIDTH_MM
                   and not m["circulation_issues"]]
        return {"rule_id": rule, "target": target, "measured": measured,
                "passing_object_ids": passing,
                "engine": geo["metrics"].get("geometry_engine"),
                "rechecked": "pass" if passing else "fail"}
    if field in ("rot", "kelvin", "area_sqm") and rule in _RULE_SCOPES:
        values = {oid: o.get(field) for oid, o in objs}
        passing = [oid for oid, v in values.items()
                   if isinstance(v, (int, float)) and float(v) == float(target)]
        return {"rule_id": rule, "target": target, "measured": values,
                "passing_object_ids": passing,
                "rechecked": "pass" if passing else "fail"}
    return {"rule_id": rule, "target": target, "measured": None,
            "passing_object_ids": [], "rechecked": None,
            "unknown_reason": f"规则 {rule}/{field} 尚未实现确定性复核"}


def recheck_objectives(objectives: list[dict], base: dict, candidate: dict, *,
                       site: dict | None = None, catalog: dict | None = None,
                       locks: dict | None = None,
                       changed_objects: list[str] | None = None) -> list[dict]:
    """Four states per objective: input_included / object_changed /
    objective_rechecked / user_confirmed. Never resolves by diff reference."""
    site = site or {}
    catalog = catalog or {c["catalog_id"]: c for c in CATALOG}
    changed_ids = {str(k).split(":", 1)[-1] for k in (changed_objects or [])}
    results: list[dict] = []
    for obj in (objectives or []):
        oid_scope = obj.get("object_ids") or []
        scope_objs = [o[0] for o in _plan_objects(candidate,
                                                   obj.get("objects_scope") or [], oid_scope)]
        object_changed = bool(changed_ids & (set(scope_objs) | set(oid_scope)))
        item: dict[str, Any] = {
            "objective_id": obj.get("objective_id"), "kind": obj.get("kind"),
            "rule_id": obj.get("rule_id"), "field": obj.get("field"),
            "target": obj.get("target"), "unit": obj.get("unit"),
            "source": obj.get("source"), "issue_id": obj.get("issue_id"),
            "feedback_id": obj.get("feedback_id"),
            "input_included": True,
            "object_changed": object_changed,
            "linked_objects": [x for x in scope_objs if x in changed_ids],
            "objective_rechecked": "unknown",
            "user_confirmed": "pending",
            "resolved": None,
            "note": "",
        }
        if obj.get("kind") == "lock":
            conflicts = lock_conflicts(base, candidate, locks or {"locks": []})
            item["evidence"] = {"locked_objects": (locks or {}).get("lock_object_ids", []),
                                "conflicts": conflicts}
            item["objective_rechecked"] = "fail" if conflicts else "pass"
            item["user_confirmed"] = "not_applicable"
            item["object_changed"] = bool(conflicts)
            item["resolved"] = not conflicts
            item["note"] = ("锁定对象由结构化对象/字段锁复算；冲突只报告并给替代，"
                            "不自行解除锁定" if conflicts else "锁定对象未变")
        elif obj.get("kind") == "aesthetic" or not obj.get("computable", True):
            item["evidence"] = {"target": obj.get("target"), "measured": None,
                                "unknown_reason": obj.get("note") or
                                "审美/未实现目标需要用户或对应规则，不由程序判定"}
            item["objective_rechecked"] = "unknown"
            item["user_confirmed"] = "pending"
            item["resolved"] = None
            item["note"] = ("不可计算或尚未实现的复核写 unknown；只提供图面对比与模型意见，"
                            "最终等用户确认；不把『引用到变化』记为已解决")
        else:
            before = _measure(base, obj, site, catalog)
            after = _measure(candidate, obj, site, catalog)
            item["evidence"] = {"before": before, "after": after}
            state = after.get("rechecked")
            if state is None:
                item["objective_rechecked"] = "unknown"
                item["user_confirmed"] = "pending"
                item["resolved"] = None
                item["note"] = f"规则未实现：{after.get('unknown_reason')}；写 unknown，不记已解决"
            else:
                item["objective_rechecked"] = state
                item["user_confirmed"] = "not_applicable"
                item["resolved"] = state == "pass" and object_changed
                item["note"] = ("目标值由对应规则复算；" +
                                ("达到目标且对象确有变化" if item["resolved"]
                                 else "未达到目标或目标对象未发生有效变化，不构成已解决"))
        results.append(item)
    return results
