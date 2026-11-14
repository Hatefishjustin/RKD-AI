"""W0/R1 + W0/R2 + W0-F01—F04: task resolution, structured locks, deterministic
objective rechecks.

Design rules (docs/26 sections 2, 4; architect review 2026-11-14):
  * generate, revise and retry are DIFFERENT tasks. A revise loads the FULL
    plan of the artifact named by the feedback, never "the latest file".
  * The CURRENT task comes from the newest versioned feedback row, i.e. the
    boss's latest expressed intent. Consumed history can block replaying THE
    SAME task; it can never block a later generate intent. Older unconsumed
    revise messages are never silently revived and never silently dropped:
    same-baseline messages are merged EXPLICITLY (and consumed together),
    different baselines are an explicit conflict that needs a decision.
  * An unusable baseline is an explicit conflict, never a silent substitution
    with a freshly generated A/B pair.
  * Locks are structured object/FIELD records, not Chinese keyword hits on
    object names. A field lock compares that field only; `*` locks the object.
    Unsupported fields, deleted objects and unknown objects are diagnosed.
  * A measurable objective carries an explicit target object set, comparator
    (min / exact / max) and quantifier (default ALL). Partial fulfilment is
    NOT success; an empty or missing target set is never success.
  * A "keep X unchanged" requirement must be bound to concrete objects. When it
    cannot be bound (or is ambiguous) it is `unknown` + pending, and it is never
    verified against some other lock.
  * Aesthetic objectives stay unknown + pending for the user.

No external calls, no design judgement. `unknown` is never filled with 0.
"""
from __future__ import annotations

import copy
import hashlib
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
_TOL = 1e-6

# rule_id -> (field, unit, object group(s) the rule can actually measure)
_RULE_SCOPES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "CIR-001": ("width_mm", "mm", ("circulation",)),
    "CIR-003": ("width_mm", "mm", ("circulation",)),
    "STD-001": ("rot", "degree", ("furniture",)),
    "STD-005": ("kelvin", "K", ("ceiling.fixtures", "ceiling.coves")),
    "AREA-002": ("area_sqm", "sqm", ("zones",)),
    "STD-004": ("sightline", "unknown", ("zones",)),  # not computable yet
}

# A target value needs a comparison operator, never "roughly >= is fine".
_DEFAULT_COMPARATOR = {
    "CIR-001": "min", "CIR-003": "min", "AREA-002": "min",
    "STD-001": "exact", "STD-005": "exact",
}

# Fields a lock may name. Anything else is an explicit diagnostic, not a pass.
_LOCK_FIELDS: dict[str, set[str]] = {
    "zones": {"name", "role", "polygon", "area_sqm"},
    "furniture": {"catalog_id", "x", "y", "rot", "w_mm", "d_mm"},
    "circulation": {"width_mm", "path"},
    "platforms": {"name", "kind", "corner_radius_mm", "polygon", "height_mm"},
    "ceiling.coves": {"polygon", "band_mm", "kelvin"},
    "ceiling.fixtures": {"type", "x", "y", "kelvin", "aim"},
}

_TEXT_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"净宽[^0-9\-]{0,14}(-?\d+(?:\.\d+)?)\s*mm", re.I), "CIR-001"),
    (re.compile(r"旋[到转至为设]*\s*(-?\d+(?:\.\d+)?)\s*(?:°|度)", re.I), "STD-001"),
    (re.compile(r"色温[^0-9\-]{0,14}(-?\d+(?:\.\d+)?)\s*K", re.I), "STD-005"),
    (re.compile(r"面积[^0-9\-]{0,14}(-?\d+(?:\.\d+)?)\s*(?:㎡|平米|平方米)", re.I), "AREA-002"),
]

_PRESERVE_RE = re.compile(r"保留|不动|保持|原样|不改|维持")
_CLAUSE_SPLIT = re.compile(r"[，,。；;、\n]")


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


def _value_sig(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


# ------------------------------------------------------------------ objects --
def _iter_objects(plan: dict):
    """Yield (group, object) for every addressable object in a draft."""
    if not isinstance(plan, dict):
        return
    for group in ("zones", "furniture", "circulation", "platforms"):
        for o in (plan.get(group) or []):
            if isinstance(o, dict) and o.get("id"):
                yield group, o
    ceiling = plan.get("ceiling") if isinstance(plan.get("ceiling"), dict) else {}
    for group in ("coves", "fixtures"):
        for o in (ceiling.get(group) or []):
            if isinstance(o, dict) and o.get("id"):
                yield f"ceiling.{group}", o


def _index(plan: dict) -> dict[str, tuple[str, dict]]:
    return {str(o["id"]): (g, o) for g, o in _iter_objects(plan)}


def _object_signature(plan: dict, object_id: str) -> str | None:
    hit = _index(plan).get(str(object_id))
    return _sha(hit[1]) if hit else None


# ------------------------------------------------------------------ R1 tasks --
def resolve_task(st, project_id: str, expected_feedback_revision: int | None) -> dict:
    """Decide generate / revise / conflict from VERSIONED feedback only.

    The newest feedback row IS the current intent (docs/26 §4). Older rows are
    constraints that stay in the effective requirement; they never take over
    the task on their own (no resurrection) and are never silently discarded
    (merged when they share the baseline, otherwise an explicit conflict).
    """
    rows = st.feedback(project_id)
    if st.feedback_changed_since(project_id, expected_feedback_revision):
        return _conflict("concurrent_new_feedback",
                         f"运行开始时的有效需求版本 v{expected_feedback_revision} 已落后于当前 "
                         f"v{st.feedback_revision(project_id)}；晚到结果不得成为当前版本",
                         ["先取消/作废这一轮，再按最新留言开新任务",
                          "不要重放旧输入，也不要把旧结果写成新版"])
    if not rows:
        return _generate(rows, "还没有留言：本轮按 generate 处理")

    latest = rows[-1]
    pending_all = [f for f in rows if f.get("baseline_artifact_id")
                   and not f.get("consumed_by_run")]
    if not latest.get("baseline_artifact_id"):
        # An explicit generate intent. Consumed history must not block it (F01-b),
        # and older pending revise messages must not hijack it (no resurrection).
        overridden = [f for f in pending_all if f["id"] != latest["id"]]
        return _generate(
            rows,
            f"最新留言（v{latest['revision_no']}）没有指定旧基线：按 generate 处理；"
            "留言内容仍进入有效需求",
            overridden_feedback=overridden)

    if latest.get("consumed_by_run"):
        # Replaying a task that ALREADY ran is what would bypass the rework cap.
        return _conflict(
            "feedback_already_consumed",
            f"最新留言 {latest['id']}（v{latest['revision_no']}）已由 run "
            f"{latest['consumed_by_run']} 消费；不得用新 run 重放同一任务",
            ["给一条新的留言（要续改就重新选中旧方案）",
             "或由老板在闸口决定下一轮怎么做",
             "程序不会把这条已执行的留言再当成一次新任务"],
            pending_feedback=[f for f in pending_all if f["id"] != latest["id"]])

    others = [f for f in pending_all if f["id"] != latest["id"]]
    other_baselines = {f.get("baseline_artifact_id") for f in others}
    if other_baselines - {latest.get("baseline_artifact_id")}:
        # Cross-candidate feedback is NEVER merged silently (F01-c).
        return _conflict(
            "multiple_pending_feedback",
            "有多条待续改留言指向不同旧基线，不能自动合并，也不能丢下更早那条："
            + "；".join(f"{f['id']}(v{f['revision_no']}→{f['baseline_artifact_id']})"
                       for f in pending_all),
            ["先用最早那条开一轮，再处理后面的",
             "或作废不需要的那条（POST /studio/projects/<pid>/feedback/<fid>/withdraw），"
             "作废记录会保留"]
            + [f"待决：{f['id']} v{f['revision_no']}「{str(f.get('text') or '')[:40]}」"
               for f in others],
            pending_feedback=others)

    merged = [f for f in pending_all
              if f.get("baseline_artifact_id") == latest.get("baseline_artifact_id")]
    merged.sort(key=lambda f: f["revision_no"])
    art = st.artifact_by_id(latest["baseline_artifact_id"])
    if art is None:
        return _conflict("baseline_not_found",
                         f"反馈指定的旧基线产物 {latest['baseline_artifact_id']} 不存在",
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
    if latest.get("baseline_revision_uid") and \
            latest["baseline_revision_uid"] != art.get("revision_uid"):
        return _conflict("baseline_uid_mismatch",
                         f"反馈携带的 revision_uid {latest['baseline_revision_uid']} 与旧基线 "
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
    merge_note = ""
    if len(merged) > 1:
        merge_note = ("；同一基线的 " + "、".join(f"v{f['revision_no']}" for f in merged)
                      + " 一并作为本轮约束（显式合并，合并后一次性消费，不会晚点复活）")
    return {"kind": TASK_REVISE, "task_kind": TASK_REVISE, "feedback": latest,
            "merged_feedback": merged,
            "merged_feedback_ids": [f["id"] for f in merged],
            "pending_feedback_ids": [f["id"] for f in merged],
            "baseline": art, "plan": copy.deepcopy(plan), "feedback_rows": rows,
            "reason": f"按最新留言 {latest['id']} 指定的旧基线 {art['id']} "
                      f"(revision_uid={art.get('revision_uid')}) 续改，不重新生成 A/B"
                      + merge_note,
            "baseline_selection": latest.get("baseline_selection") or "explicit_pointer"}


def _generate(rows: list[dict], reason: str,
              overridden_feedback: list[dict] | None = None) -> dict:
    overridden = overridden_feedback or []
    out = {"kind": TASK_GENERATE, "task_kind": TASK_GENERATE, "feedback": None,
           "baseline": None, "plan": None, "feedback_rows": rows,
           "overridden_feedback_ids": [f["id"] for f in overridden],
           "superseded_intent": [{"feedback_id": f["id"], "revision_no": f["revision_no"],
                                  "baseline_artifact_id": f.get("baseline_artifact_id")}
                                 for f in overridden],
           "reason": reason}
    if overridden:
        out["reason"] += ("；更早的续改留言 "
                          + "、".join(f"v{f['revision_no']}" for f in overridden)
                          + " 没有被自动执行，也没被删除：它仍是有效需求，只是不作"
                            "为本轮任务；要续改请重新选中旧方案")
    return out


def _conflict(code: str, detail: str, alternatives: list[str],
              pending_feedback: list[dict] | None = None) -> dict:
    pending = pending_feedback or []
    return {"kind": TASK_CONFLICT, "task_kind": TASK_CONFLICT, "conflict_code": code,
            "conflict_detail": detail, "alternatives": alternatives,
            "pending_feedback": [{"feedback_id": f["id"], "revision_no": f["revision_no"],
                                  "text": f.get("text"),
                                  "baseline_artifact_id": f.get("baseline_artifact_id")}
                                 for f in pending],
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


def lock_conflicts(base: dict, candidate: dict, locks: dict) -> list[dict]:
    """Field-level lock comparison.

    `fields: ["*"]` locks the whole object. Otherwise only the named fields are
    compared, so locking `x` does not reject a `rot` change (W0-F04). Deleted
    objects always conflict; unknown fields / missing objects are diagnosed
    instead of being silently reported as "unchanged".
    """
    out: list[dict] = []
    before, after = _index(base), _index(candidate)
    for lk in (locks or {}).get("locks") or []:
        oid = str(lk.get("object_id"))
        fields = [str(f) for f in (lk.get("fields") or ["*"])]
        item = {"object_id": oid, "fields": fields,
                "source": lk.get("source"), "reason": lk.get("reason"),
                "base_sha256_prefix": None, "candidate_sha256_prefix": None,
                "alternative": ("恢复该对象被锁定的字段；若确实无法同时满足，"
                                "把冲突作为待决项交用户决定，程序不自行解除锁定")}
        b_hit, a_hit = before.get(oid), after.get(oid)
        if b_hit is None and a_hit is None:
            out.append({**item, "diagnostic": "locked_object_not_found",
                        "changed_fields": [],
                        "message": f"锁定对象 {oid} 在基线与候选里都不存在；该锁无法核对"})
            continue
        if b_hit is None:
            out.append({**item, "diagnostic": "locked_object_missing_in_baseline",
                        "changed_fields": [],
                        "message": f"锁定对象 {oid} 不在旧基线里，无法判断是否被改动"})
            continue
        group, b = b_hit
        item["base_sha256_prefix"] = _sha(b)[:12]
        if a_hit is None:
            out.append({**item, "diagnostic": "object_deleted", "changed_fields": ["*"],
                        "message": f"锁定对象 {oid} 被删除"})
            continue
        _, a = a_hit
        item["candidate_sha256_prefix"] = _sha(a)[:12]
        if "*" in fields or not fields:
            if _sha(b) != _sha(a):
                out.append({**item, "diagnostic": "whole_object_changed",
                            "changed_fields": ["*"],
                            "message": f"锁定对象 {oid} 被改动"})
            continue
        supported = _LOCK_FIELDS.get(group, set())
        unknown = [f for f in fields if f not in supported]
        changed = [f for f in fields
                   if f in supported and _value_sig(b.get(f)) != _value_sig(a.get(f))]
        if unknown:
            out.append({**item, "diagnostic": "unsupported_fields",
                        "unsupported_fields": unknown, "changed_fields": changed,
                        "message": (f"锁定字段 {unknown} 不在 {group} 的可核对字段里；"
                                    "无法证明未改动，按冲突处理并需明确诊断")})
            continue
        if changed:
            out.append({**item, "diagnostic": "field_changed",
                        "changed_fields": changed,
                        "message": f"锁定字段 {changed} 被改动（对象 {oid}）"})
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
                    "comparator": _DEFAULT_COMPARATOR.get(rule_id, "exact"),
                    "quantifier": "all",
                    "source": source, "issue_id": issue_id,
                    "feedback_id": feedback_id,
                    "parsed_from": m.group(0)[:80],
                    "computable": rule_id != "STD-004"})
    return out


def preserve_clauses(text: str) -> list[str]:
    """Clauses that carry a keep-as-is requirement (保留/不动/保持/原样…)."""
    return [c.strip() for c in _CLAUSE_SPLIT.split(text or "")
            if c.strip() and _PRESERVE_RE.search(c)]


def resolve_preserve_binding(clause: str, plan: dict) -> dict:
    """Bind one keep-as-is clause to concrete objects, or say why it cannot be.

    Matching is on the object's own id or its declared name inside the clause —
    a traceable binding, not a keyword guess on the whole message. Ambiguity is
    reported with the candidates instead of picking one.
    """
    exact = [oid for oid, _ in _index(plan).items()
             if re.search(rf"(?<![A-Za-z0-9]){re.escape(oid)}(?![A-Za-z0-9])", clause)]
    if len(exact) == 1:
        return {"status": "resolved", "object_ids": exact, "candidates": exact,
                "match": "explicit_object_id", "clause": clause}
    named = []
    for oid, (_group, obj) in _index(plan).items():
        name = str(obj.get("name") or "").strip()
        if len(name) >= 2 and name in clause:
            named.append(oid)
    named = sorted(set(named))
    if len(named) == 1:
        return {"status": "resolved", "object_ids": named, "candidates": named,
                "match": "object_name_in_clause", "clause": clause}
    if len(named) > 1:
        return {"status": "ambiguous", "object_ids": [], "candidates": named,
                "match": "multiple_object_names", "clause": clause}
    return {"status": "unresolved", "object_ids": [], "candidates": [],
            "match": "none", "clause": clause}


def resolve_preserve_bindings(text: str, plan: dict) -> list[dict]:
    return [resolve_preserve_binding(c, plan) for c in preserve_clauses(text)]


def derive_objectives(feedback_rows: list[dict], issues: list[dict] | None = None,
                      plan: dict | None = None) -> list[dict]:
    """Collect objectives from structured feedback, text, locks and review issues.

    `plan` is the baseline the requirements refer to. Without it a keep-as-is
    requirement cannot be bound and is reported as unresolved (never as a pass).
    """
    out: list[dict] = []
    for fb in (feedback_rows or []):
        rev = fb.get("revision_no", "?")
        produced: list[dict] = []
        structured = fb.get("objectives") or []
        for i, obj in enumerate(structured):
            if isinstance(obj, dict) and obj.get("kind"):
                item = copy.deepcopy(obj)
                item.setdefault("objective_id", f"FB{rev}-{i + 1}")
                item.setdefault("source", "structured")
                item.setdefault("feedback_id", fb.get("id"))
                item.setdefault("computable", item.get("kind") == "measurable")
                item.setdefault("quantifier", "all")
                if item.get("kind") == "measurable" and not item.get("comparator"):
                    item["comparator"] = _DEFAULT_COMPARATOR.get(
                        str(item.get("rule_id")), "exact")
                produced.append(item)
        text = str(fb.get("text") or "")
        structured_rules = {o.get("rule_id") for o in structured}
        heuristics = derive_text_objectives(
            text, prefix=f"FB{rev}-", object_ids=None,
            feedback_id=str(fb.get("id") or ""))
        produced.extend(o for o in heuristics if o["rule_id"] not in structured_rules)
        # Explicit structured locks: one objective per lock, so field granularity
        # stays visible and nothing is verified through "some other lock".
        for i, lk in enumerate(fb.get("locks") or []):
            if not isinstance(lk, dict) or not str(lk.get("object_id") or "").strip():
                continue
            produced.append({
                "objective_id": f"FB{rev}-LK{i + 1}", "kind": "lock",
                "rule_id": "LOCK-REVISION", "field": "locked_objects",
                "target": None, "unit": "n/a", "objects_scope": [],
                "object_ids": [str(lk["object_id"])],
                "fields": list(lk.get("fields") or ["*"]),
                "source": "structured_lock", "feedback_id": fb.get("id"),
                "binding_status": "resolved",
                "computable": True,
                "note": str(lk.get("reason") or "老板明确指定的保留对象/字段")})
        # Keep-as-is claims in the text must be TRACKED even next to a numeric
        # target (mixed messages lose nothing), and only pass when bound.
        for i, b in enumerate(resolve_preserve_bindings(text, plan or {})):
            produced.append({
                "objective_id": f"FB{rev}-P{i + 1}", "kind": "preserve",
                "rule_id": "LOCK-PRESERVE", "field": "preserved_objects",
                "target": None, "unit": "n/a",
                "objects_scope": [], "object_ids": list(b["object_ids"]),
                "binding_status": b["status"], "binding_match": b["match"],
                "binding_candidates": b["candidates"], "source_text": b["clause"],
                "source": "text_preserve", "feedback_id": fb.get("id"),
                "computable": b["status"] == "resolved",
                "note": ("保留要求已绑定到具体对象，按对象全文复核"
                         if b["status"] == "resolved" else
                         "保留要求还没绑定到具体对象：未验证，等用户确认或补充对象；"
                         "不用入口锁或别的锁代替")})
        if not produced:
            produced.append({"objective_id": f"FB{rev}-A",
                             "kind": "aesthetic", "rule_id": "USER-JUDGEMENT",
                             "field": "user_judgement", "target": None, "unit": "n/a",
                             "objects_scope": [], "object_ids": [],
                             "source": "text_unparsed", "feedback_id": fb.get("id"),
                             "computable": False,
                             "note": "没有可计算目标（例如「更开放」「更有设计感」）；"
                                     "只提供图面对比与模型意见，最终等用户确认"})
        out.extend(produced)
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
    ceiling = plan.get("ceiling") if isinstance(plan, dict) and \
        isinstance(plan.get("ceiling"), dict) else {}
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


def _cmp_ok(value: Any, target: Any, comparator: str) -> bool:
    """min: value >= target; max: value <= target; exact: value == target."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(target, bool) or not isinstance(target, (int, float)):
        return False
    v, t = float(value), float(target)
    if comparator == "min":
        return v >= t - _TOL
    if comparator == "max":
        return v <= t + _TOL
    return abs(v - t) <= _TOL


def _aggregate(present: int, passing: list[str], missing: list[str],
               quantifier: str) -> str | None:
    """ALL by default. A missing target object is never success; an empty target
    set is `unknown` (None) — it can never become `pass` (W0-F02)."""
    if missing:
        return "fail"
    if present == 0:
        return None
    if quantifier == "any":
        return "pass" if passing else "fail"
    return "pass" if len(passing) == present else "fail"


def _measure(plan: dict, objective: dict, site: dict, catalog: dict) -> dict:
    """Re-measure an objective with the corresponding deterministic rule."""
    rule = objective.get("rule_id")
    field = objective.get("field")
    target = objective.get("target")
    scope = objective.get("objects_scope") or []
    declared = [str(x) for x in (objective.get("object_ids") or [])]
    quantifier = str(objective.get("quantifier") or "all").lower()
    if quantifier not in ("all", "any"):
        quantifier = "all"
    comparator = str(objective.get("comparator")
                     or _DEFAULT_COMPARATOR.get(str(rule), "exact")).lower()
    if comparator not in ("min", "max", "exact"):
        comparator = "exact"
    objs = _plan_objects(plan, scope, declared)
    present = [oid for oid, _ in objs]
    missing = [x for x in declared if x not in present]
    catalog = catalog or {c["catalog_id"]: c for c in CATALOG}
    common = {"rule_id": rule, "field": field, "target": target,
              "comparator": comparator, "quantifier": quantifier,
              "target_objects": present, "missing_object_ids": missing,
              "declared_object_ids": declared,
              "object_source": ("declared_ids" if declared
                                else ("group:" + ",".join(scope) if scope else "none"))}
    if not present and not missing:
        return {**common, "measured": None, "passing_object_ids": [],
                "failing_object_ids": [], "rechecked": None,
                "unknown_reason": "目标没有绑定任何可核对的对象，不能算达标"}

    if rule in ("CIR-001", "CIR-003") and field == "width_mm":
        if not (isinstance(site, dict) and site.get("width_mm") and site.get("height_mm")):
            return {**common, "measured": None, "passing_object_ids": [],
                    "failing_object_ids": [], "rechecked": None,
                    "unknown_reason": "缺少场地边界，无法用几何复算实测净宽/瓶颈"}
        geo = geometry.check_geometry(plan, site, catalog=catalog)
        measured, passing, failing = {}, [], []
        for oid, o in objs:
            declared_mm = o.get("width_mm")
            measured_mm = geo["metrics"].get(f"measured_clear_width_mm::{oid}")
            issues = [x["rule_id"] for x in geo["issues"]
                      if oid in x["objects"]
                      and x["rule_id"] in ("CIR-001", "CIR-003")]
            declared_ok = _cmp_ok(declared_mm, target, comparator)
            measured_ok = _cmp_ok(measured_mm, target, comparator)
            floor_ok = _cmp_ok(measured_mm, _MIN_CLEAR_WIDTH_MM, "min")
            ok = bool(declared_ok and measured_ok and floor_ok and not issues)
            measured[oid] = {
                "declared_width_mm": declared_mm,
                "measured_clear_width_mm": measured_mm,
                "target_mm": target, "comparator": comparator,
                "declared_meets_target": declared_ok,
                "measured_meets_target": measured_ok,
                "absolute_floor_mm": _MIN_CLEAR_WIDTH_MM, "floor_met": floor_ok,
                "circulation_issues": issues, "meets_target": ok}
            (passing if ok else failing).append(oid)
        return {**common, "measured": measured, "passing_object_ids": passing,
                "failing_object_ids": failing,
                "rechecked": _aggregate(len(present), passing, missing, quantifier),
                "engine": geo["metrics"].get("geometry_engine"),
                # Honest scope: the engine only knows keep-outs / entrance, so a
                # measured value is NOT a full clear-width compliance proof.
                "coverage": "limited: declared width + keep-out/entrance geometry; "
                            "不覆盖门洞、家具遮挡与完整净宽合规"}
    if field in ("rot", "kelvin", "area_sqm") and rule in _RULE_SCOPES:
        values, passing, failing = {}, [], []
        for oid, o in objs:
            v = o.get(field)
            values[oid] = v
            (passing if _cmp_ok(v, target, comparator) else failing).append(oid)
        return {**common, "measured": values, "passing_object_ids": passing,
                "failing_object_ids": failing,
                "rechecked": _aggregate(len(present), passing, missing, quantifier),
                "coverage": "declared field value on the object (未渲染复核)"}
    return {**common, "measured": None, "passing_object_ids": [],
            "failing_object_ids": [], "rechecked": None,
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
        oid_scope = [str(x) for x in (obj.get("object_ids") or [])]
        scope_objs = [o[0] for o in _plan_objects(candidate,
                                                   obj.get("objects_scope") or [], oid_scope)]
        targets = sorted(set(scope_objs) | set(oid_scope))
        object_changed = bool(changed_ids & set(targets))
        item: dict[str, Any] = {
            "objective_id": obj.get("objective_id"), "kind": obj.get("kind"),
            "rule_id": obj.get("rule_id"), "field": obj.get("field"),
            "target": obj.get("target"), "unit": obj.get("unit"),
            "source": obj.get("source"), "issue_id": obj.get("issue_id"),
            "feedback_id": obj.get("feedback_id"),
            "target_objects": targets,
            "quantifier": obj.get("quantifier") or "all",
            "input_included": True,
            "object_changed": object_changed,
            "linked_objects": [x for x in targets if x in changed_ids],
            "objective_rechecked": "unknown",
            "user_confirmed": "pending",
            "resolved": None,
            "note": "",
        }
        if obj.get("kind") in ("lock", "preserve"):
            item.update(_recheck_lock_objective(obj, base, candidate))
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
                item["note"] = (f"规则未实现或无可核对对象：{after.get('unknown_reason')}；"
                                "写 unknown，不记已解决")
            else:
                item["objective_rechecked"] = state
                item["user_confirmed"] = "not_applicable"
                item["resolved"] = state == "pass" and object_changed
                if state == "fail" and after.get("missing_object_ids"):
                    item["note"] = ("目标点名的对象在候选里不存在："
                                    f"{after['missing_object_ids']}；对象缺失不算达标")
                elif state == "fail" and len(after.get("passing_object_ids") or []) > 0:
                    item["note"] = (f"只满足部分对象（通过 "
                                    f"{after['passing_object_ids']}，未通过 "
                                    f"{after['failing_object_ids']}）；默认量词=all，"
                                    "部分达标不算解决")
                else:
                    item["note"] = ("目标值由对应规则复算（比较符 "
                                    f"{after.get('comparator')}，量词 {after.get('quantifier')}）；"
                                    + ("达到目标且对象确有变化" if item["resolved"]
                                       else "未达到目标或目标对象未发生有效变化，"
                                            "不构成已解决"))
        results.append(item)
    return results


def _recheck_lock_objective(obj: dict, base: dict, candidate: dict) -> dict:
    """Verify a keep-as-is objective against ITS OWN objects only."""
    bindings = [str(x) for x in (obj.get("object_ids") or [])]
    status = obj.get("binding_status")
    fields = [str(f) for f in (obj.get("fields") or ["*"])]
    if not bindings or status in ("unresolved", "ambiguous"):
        return {"objective_rechecked": "unknown", "user_confirmed": "pending",
                "resolved": None, "object_changed": False,
                "evidence": {"binding_status": status or "unresolved",
                             "candidates": obj.get("binding_candidates") or [],
                             "clause": obj.get("source_text") or "",
                             "verified_objects": []},
                "note": ("这条保留要求还没有绑定到具体对象，未验证；"
                         "不用入口锁或别的锁代替，等用户确认或补充对象")}
    scope_locks = {"locks": [{"object_id": oid, "fields": fields,
                              "source": obj.get("source") or "preserve",
                              "reason": obj.get("note") or "保留要求"}
                             for oid in bindings]}
    conflicts = lock_conflicts(base, candidate, scope_locks)
    return {"objective_rechecked": "fail" if conflicts else "pass",
            "user_confirmed": "not_applicable",
            "resolved": not conflicts,
            "object_changed": bool(conflicts),
            "target_objects": bindings,
            "evidence": {"binding_status": status or "resolved",
                         "verified_objects": bindings, "locked_fields": fields,
                         "binding_match": obj.get("binding_match"),
                         "source_text": obj.get("source_text"),
                         "conflicts": conflicts},
            "note": ("保留对象被改动，冲突只报告并给替代，不自行解除"
                     if conflicts else "保留对象未变（按本条要求自己的对象核对）")}
