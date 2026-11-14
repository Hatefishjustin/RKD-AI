"""Full contract enforcement for studio spatial-plan candidates (ARC-01).

Order is fixed and no stage is skipped:

    structure (JSON Schema, model proposal)
      -> semantic references (catalog / standards / object ids / area rows)
      -> geometry & area reconciliation (geometry.check_geometry, shapely)
      -> lock / identity (program-owned metadata only)

A proposal that fails ANY stage is NOT a valid candidate. Its raw bytes and the
full diagnostic are still saved, marked invalid, and never shown as a usable
option. Nothing is invented to make a broken proposal pass: required fields are
not removed, additionalProperties is not relaxed, and no unknown field is
back-filled. Identity / approval / adoption fields are owned by the program.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import geometry, tools as toolbox

ROOT = Path(__file__).resolve().parents[3]
PROPOSAL_SCHEMA_PATH = ROOT / "contracts" / "v1" / "spatial-plan-proposal.schema.json"
DRAFT_SCHEMA_PATH = ROOT / "contracts" / "v1" / "spatial-plan-draft.schema.json"
STANDARDS_PATH = ROOT / "knowledge" / "design-standards" / "standards.v1.json"
CONTRACT_VERSION = "rkd-spatial-plan.v1"

# Identity metadata: the model may echo it, but the program ALWAYS strips it
# from the proposal and re-injects its own version-chain values. The model
# therefore never decides identity.
IGNORED_IDENTITY = {
    "contract_version", "project_id", "option_id", "revision",
    "parent_revision", "author",
}
# Approval / adoption pointers are hard-forbidden: no agent may decide them.
FORBIDDEN_DECISIONS = {
    "status", "approved", "approval", "adopt_pointer", "adopted",
    "decision", "published", "gate_decision",
}
PROGRAM_OWNED = IGNORED_IDENTITY | FORBIDDEN_DECISIONS


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pointer(parts: list[Any]) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _object_id(instance: Any, parts: list[Any]) -> str:
    """Best-effort stable object reference for a failing path."""
    cur = instance
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list) and isinstance(p, int) and 0 <= p < len(cur):
            cur = cur[p]
        else:
            cur = None
        if isinstance(cur, dict) and cur.get("id"):
            return str(cur["id"])
        if isinstance(cur, dict) and cur.get("name"):
            return str(cur["name"])
    for p in reversed(parts):
        if isinstance(p, int):
            return f"index:{p}"
    return "?"


def _expected(err: Any) -> str:
    v = err.validator
    if v == "required":
        return f"必填字段 {err.validator_value}（对象类型）"
    if v == "type":
        return f"类型 {err.validator_value}"
    if v == "enum":
        return f"枚举值之一 {err.validator_value}"
    if v == "additionalProperties":
        return "不允许的额外字段：只能使用契约已声明字段"
    if v == "minItems":
        return f"数组至少 {err.validator_value} 项"
    if v == "minLength":
        return f"字符串至少 {err.validator_value} 字符"
    if v == "minimum":
        return f"数值 >= {err.validator_value}"
    if v == "exclusiveMinimum":
        return f"数值 > {err.validator_value}"
    if v == "const":
        return f"固定值 {err.validator_value}"
    return f"满足 {v}={err.validator_value}"


def _schema_errors(schema: dict, instance: Any) -> list[dict]:
    out = []
    for e in Draft202012Validator(schema).iter_errors(instance):
        parts = list(e.absolute_path)
        out.append({
            "stage": "structure",
            "rule_id": "CONTRACT-STRUCT",
            "path": _pointer(parts),
            "expected": _expected(e),
            "actual_type": type(e.instance).__name__,
            "object_id": _object_id(instance, parts),
            "message": e.message[:220],
            "hint": ("按契约补齐该字段；身份/批准/采用字段由程序注入，模型不得写入"
                     if e.validator == "additionalProperties" else
                     "按期望类型与取值修改该字段，不要删除必填项或改用自由文本"),
        })
    return out


def _semantic_errors(proposal: dict) -> tuple[list[dict], dict]:
    """Reference integrity that a JSON Schema cannot express."""
    errors: list[dict] = []
    facts: dict[str, Any] = {}
    catalog = {c["catalog_id"]: c for c in toolbox.CATALOG}
    try:
        standards = {r["id"] for r in _load(STANDARDS_PATH)["rules"]}
    except Exception:
        standards = set()
    facts["catalog_entries"] = len(catalog)
    facts["standard_ids"] = sorted(standards)

    ids: dict[str, list[str]] = {}
    for group in ("zones", "circulation", "platforms", "furniture"):
        for i, o in enumerate(proposal.get(group) or []):
            if not isinstance(o, dict):
                continue
            oid = str(o.get("id") or "")
            key = f"{group}:{oid}"
            ids.setdefault(key, []).append(f"/{group}/{i}")
    ceiling = proposal.get("ceiling") if isinstance(proposal.get("ceiling"), dict) else {}
    for group in ("coves", "fixtures"):
        for i, o in enumerate(ceiling.get(group) or []):
            if isinstance(o, dict):
                ids.setdefault(f"ceiling.{group}:{o.get('id')}", []).append(f"/ceiling/{group}/{i}")
    duplicates = {k: v for k, v in ids.items() if len(v) > 1}
    facts["object_id_duplicates"] = duplicates
    for key, paths in duplicates.items():
        errors.append({
            "stage": "semantics", "rule_id": "REF-DUP", "path": paths[0],
            "expected": "对象 id 在同一方案内唯一", "actual_type": "duplicate",
            "object_id": key, "message": f"对象 id 重复：{key} 出现于 {', '.join(paths)}",
            "hint": "给每个对象一个稳定且不重复的 id；修订时沿用未删除对象的 id",
        })

    for i, f in enumerate(proposal.get("furniture") or []):
        if not isinstance(f, dict):
            continue
        cid = str(f.get("catalog_id") or "")
        if cid not in catalog:
            errors.append({
                "stage": "semantics", "rule_id": "REF-CATALOG",
                "path": f"/furniture/{i}/catalog_id", "expected": "目录内真实 catalog_id",
                "actual_type": "unknown_reference", "object_id": str(f.get("id") or f"furniture[{i}]"),
                "message": f"家具引用了不存在的目录条目「{cid}」",
                "hint": "先用 search_catalog 拿真实目录 id；未知家具不得用 600×600 默认框代替",
            })
    for i, s in enumerate(proposal.get("standards_cited") or []):
        if isinstance(s, str) and s not in standards:
            errors.append({
                "stage": "semantics", "rule_id": "REF-STANDARD",
                "path": f"/standards_cited/{i}", "expected": f"已登记规范编号 {sorted(standards)}",
                "actual_type": "unknown_reference", "object_id": s,
                "message": f"引用了不存在的规范编号「{s}」",
                "hint": "只引用规范库里实际存在的编号；启发式阈值不得包装成专业规范",
            })
    zone_names = {str(z.get("name")) for z in (proposal.get("zones") or []) if isinstance(z, dict)}
    functional_rows = [r for r in (proposal.get("area_table") or [])
                       if isinstance(r, dict) and not toolbox_is_other(r.get("name"))]
    unmatched = [str(r.get("name")) for r in functional_rows if r.get("name") not in zone_names]
    facts["area_table_unmatched_functional_rows"] = unmatched
    for i, name in enumerate(unmatched):
        errors.append({
            "stage": "semantics", "rule_id": "REF-AREA-ROW", "path": "/area_table",
            "expected": "功能区行 name 对应某个 zone.name；其余用『通道及其他/未分配』单列",
            "actual_type": "unknown_reference", "object_id": name,
            "message": f"面积表功能区行「{name}」找不到同名分区",
            "hint": "把该行改成已有分区名，或归入程序复算的通道/未分配行",
        })
    return errors, facts


def toolbox_is_other(name: Any) -> bool:
    return geometry._is_other_row(str(name or ""))


def validate_proposal(raw: Any, *, project: dict, option_id: str, revision: int,
                      parent_revision: int | None, author: str = "D2",
                      lock_object_ids: list[str] | None = None,
                      locks: dict | None = None,
                      previous_plan: dict | None = None) -> dict:
    """Validate a model proposal and return a full diagnostic report.

    Returns {ok, stage, errors, warnings, facts, checks, plan, proposal_sha256,
             repair_feedback, status}. `plan` is the assembled full draft
    (program-owned metadata injected) ONLY when ok is True.
    """
    proposal_schema = _load(PROPOSAL_SCHEMA_PATH)
    draft_schema = _load(DRAFT_SCHEMA_PATH)
    errors: list[dict] = []
    warnings: list[dict] = []
    checks: dict[str, Any] = {}
    facts: dict[str, Any] = {}
    stage = "structure"

    if not isinstance(raw, dict):
        return _report(False, "structure", [{
            "stage": "structure", "rule_id": "CONTRACT-STRUCT", "path": "/",
            "expected": "一个 JSON 对象", "actual_type": type(raw).__name__,
            "object_id": "?", "message": "模型输出不是 JSON 对象",
            "hint": "只输出一个符合 spatial-plan-proposal.v1 的 JSON 对象"}],
            warnings, facts, checks, None, raw)

    # ---- stage 0: identity boundary ----------------------------------------
    # Identity echoes are stripped and replaced by program values (the model's
    # values are never trusted). Decision pointers are hard-rejected.
    ignored = sorted(IGNORED_IDENTITY & set(raw))
    facts["model_identity_fields_ignored"] = ignored
    facts["identity_injected_by_program"] = list(IGNORED_IDENTITY)
    proposal = {k: v for k, v in raw.items() if k not in IGNORED_IDENTITY}
    forbidden = sorted(FORBIDDEN_DECISIONS & set(raw))
    facts["model_decision_fields_rejected"] = forbidden
    for f in forbidden:
        errors.append({
            "stage": "structure", "rule_id": "IDENTITY-BOUNDARY", "path": f"/{f}",
            "expected": "批准/采用/发布/状态指针由用户与程序决定，模型提案中不得出现",
            "actual_type": type(raw[f]).__name__, "object_id": f,
            "message": f"模型擅自写入决定字段「{f}」",
            "hint": "删除该字段；批准与采用只能由用户在闸口给出，模型不得自评通过",
        })
    checks["identity_boundary"] = "passed" if not forbidden else "failed"
    if errors:
        stage = "structure"
        return _report(False, stage, errors, warnings, facts, checks, None, raw)

    # ---- stage 1: structure -------------------------------------------------
    errors.extend(_schema_errors(proposal_schema, proposal))
    checks["structure_schema"] = "passed" if not errors else "failed"
    checks["structure_error_count"] = len(errors)
    if errors:
        stage = "structure"
        return _report(False, stage, errors, warnings, facts, checks, None, raw)

    # ---- stage 2: semantic references --------------------------------------
    sem, sem_facts = _semantic_errors(proposal)
    facts.update(sem_facts)
    errors.extend(sem)
    checks["semantic_references"] = "passed" if not sem else "failed"
    checks["semantic_error_count"] = len(sem)
    if errors:
        stage = "semantics"
        return _report(False, stage, errors, warnings, facts, checks, None, raw)

    # ---- stage 3: geometry & area -------------------------------------------
    site = project["site"]
    catalog = {c["catalog_id"]: c for c in toolbox.CATALOG}
    geo = geometry.check_geometry(proposal, site, catalog=catalog)
    checks["geometry"] = geo["checks"]
    facts["geometry_metrics"] = geo["metrics"]
    for i in geo["issues"]:
        if i["severity"] == "blocker":
            errors.append({
                "stage": "geometry", "rule_id": i["rule_id"],
                "path": i.get("path") or "/", "expected": "几何/面积满足唯一程序口径",
                "actual_type": "geometry_violation", "object_id": ", ".join(i["objects"]) or "?",
                "message": i["message"], "hint": i["hint"],
            })
        else:
            warnings.append({
                "stage": "geometry", "rule_id": i["rule_id"],
                "path": i.get("path") or "/", "expected": "建议修正",
                "actual_type": "geometry_advisory", "object_id": ", ".join(i["objects"]) or "?",
                "message": i["message"], "hint": i["hint"],
            })
    checks["geometry_blocker_count"] = sum(1 for e in errors if e["stage"] == "geometry")
    if errors:
        stage = "geometry"
        return _report(False, stage, errors, warnings, facts, checks, None, raw)

    # ---- stage 4: locks & revision integrity --------------------------------
    # W0-F04: a field lock compares THAT FIELD only. Passing `lock_object_ids`
    # still means "whole object", but it is expressed through the same field-aware
    # comparator so validation can never silently escalate a field lock.
    lock_ids = set(lock_object_ids or [])
    effective_locks = locks
    if effective_locks is None and lock_ids:
        effective_locks = {"locks": [{"object_id": str(oid), "fields": ["*"],
                                      "source": "caller",
                                      "reason": "锁定对象"} for oid in lock_ids]}
    if previous_plan is not None and (effective_locks or {}).get("locks"):
        from .revision_task import lock_conflicts as _lock_conflicts
        hits = _lock_conflicts(previous_plan, proposal, effective_locks)
        facts["locked_objects_changed"] = sorted({h["object_id"] for h in hits})
        facts["lock_conflict_details"] = [
            {"object_id": h["object_id"], "fields": h.get("fields"),
             "changed_fields": h.get("changed_fields"),
             "diagnostic": h.get("diagnostic"), "message": h.get("message")}
            for h in hits]
        for h in hits:
            errors.append({
                "stage": "locks", "rule_id": "LOCK-REVISION", "path": "/",
                "expected": "锁定对象/字段在修订中保持不变或明确提出冲突",
                "actual_type": "lock_violation", "object_id": h["object_id"],
                "message": h.get("message") or f"锁定对象「{h['object_id']}」在修订中被改动或删除",
                "hint": "恢复该对象的被锁字段；如确实无法保留，把冲突作为待决项交用户，"
                        "不要静默解除锁定",
            })
    checks["locks"] = "passed" if not any(e["stage"] == "locks" for e in errors) else "failed"
    facts["locked_object_ids"] = sorted(lock_ids or
                                        {lk["object_id"] for lk in
                                         (effective_locks or {}).get("locks") or []})
    if errors:
        stage = "locks"
        return _report(False, stage, errors, warnings, facts, checks, None, raw)

    # ---- assemble the full draft (program-owned identity) -------------------
    plan = copy.deepcopy(proposal)
    plan.update({
        "contract_version": CONTRACT_VERSION,
        "project_id": project["id"],
        "option_id": option_id,
        "revision": revision,
        "parent_revision": parent_revision,
        "author": author,
    })
    draft_errors = _schema_errors(draft_schema, plan)
    checks["draft_schema_after_assembly"] = "passed" if not draft_errors else "failed"
    if draft_errors:
        stage = "structure"
        errors.extend(draft_errors)
        return _report(False, stage, errors, warnings, facts, checks, None, raw)

    stage = "passed"
    return _report(True, stage, errors, warnings, facts, checks, plan, raw)


def _report(ok: bool, stage: str, errors: list[dict], warnings: list[dict],
            facts: dict, checks: dict, plan: dict | None, raw: Any) -> dict:
    digest = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True,
                                       default=str).encode("utf-8")).hexdigest()
    lines = []
    for i, e in enumerate(errors[:12], 1):
        lines.append(
            f"{i}. [{e['stage']}/{e['rule_id']}] 路径 {e['path']}；对象 {e['object_id']}；"
            f"期望 {e['expected']}；实际 {e['actual_type']}。{e['message']}。建议：{e['hint']}")
    if len(errors) > 12:
        lines.append(f"（另有 {len(errors) - 12} 条，详见 errors 数组）")
    feedback = ("契约校验未通过，共 %d 条问题（首个失败阶段：%s）。\n%s"
                % (len(errors), stage, "\n".join(lines))) if errors else "契约四级校验全部通过"
    return {
        "ok": ok, "stage": stage, "errors": errors, "warnings": warnings,
        "facts": facts, "checks": checks, "plan": plan,
        "proposal_sha256": digest,
        "repair_feedback": feedback,
        "status": "valid_candidate" if ok else "invalid_raw",
    }


def substantive_difference(a: dict, b: dict) -> dict:
    """Q06: reject rename/colour/reorder/trivial-shift as a second topology.

    Compares structural signatures that ignore names, colours and object order.
    """
    def sig(plan: dict) -> dict:
        zones = []
        for z in (plan.get("zones") or []):
            if not isinstance(z, dict):
                continue
            poly = z.get("polygon")
            if not isinstance(poly, list) or len(poly) < 3:
                continue
            xs = [float(p[0]) for p in poly if isinstance(p, (list, tuple)) and len(p) == 2]
            ys = [float(p[1]) for p in poly if isinstance(p, (list, tuple)) and len(p) == 2]
            if not xs or not ys:
                continue
            zones.append((z.get("role"), round(min(xs) / 1000), round(min(ys) / 1000),
                          round((max(xs) - min(xs)) / 1000), round((max(ys) - min(ys)) / 1000),
                          len(poly)))
        routes = []
        for c in (plan.get("circulation") or []):
            if isinstance(c, dict) and isinstance(c.get("path"), list):
                routes.append(tuple((round(float(p[0]) / 1000), round(float(p[1]) / 1000))
                                    for p in c["path"] if isinstance(p, (list, tuple)) and len(p) == 2))
        furniture = sorted((str(f.get("catalog_id")), round(float(f.get("x", 0)) / 1000),
                            round(float(f.get("y", 0)) / 1000))
                           for f in (plan.get("furniture") or []) if isinstance(f, dict))
        return {"zones": sorted(zones, key=lambda t: (t[0], t[1], t[2])),
                "routes": sorted(routes), "furniture": furniture}

    sa, sb = sig(a), sig(b)
    zone_diff = sa["zones"] != sb["zones"]
    route_diff = sa["routes"] != sb["routes"]
    furn_diff = sa["furniture"] != sb["furniture"]
    # topology requires geometry/relationship change; a single renamed or
    # reordered object does not count.
    substantive = zone_diff or route_diff or (furn_diff and zone_diff)
    return {
        "substantive": bool(substantive),
        "zone_topology_changed": bool(zone_diff),
        "circulation_changed": bool(route_diff),
        "furniture_changed": bool(furn_diff),
        "signature_a": sa, "signature_b": sb,
        "reason": ("结构签名实质不同" if substantive else
                   "结构签名相同：仅换名/配色/顺序或无意义位移不算新拓扑"),
    }


def structural_summary(plan: dict) -> str:
    """A compact, complete structural hand-off for downstream agents.

    Uses object ids + full object facts (never a character truncation).
    """
    def rows(group: str, fields: tuple[str, ...]) -> str:
        out = []
        for o in (plan.get(group) or []):
            if isinstance(o, dict):
                out.append("{" + ", ".join(f"{k}={json.dumps(o.get(k), ensure_ascii=False)}"
                                           for k in fields) + "}")
        return "\n  ".join(out) or "（无）"
    ceiling = plan.get("ceiling") if isinstance(plan.get("ceiling"), dict) else {}
    return (
        "【基线完整对象事实 · 非截断】\n"
        f"策略: {json.dumps(plan.get('strategy'), ensure_ascii=False)}\n"
        f"分区({len(plan.get('zones') or [])}):\n  {rows('zones', ('id', 'name', 'role', 'polygon', 'area_sqm'))}\n"
        f"动线({len(plan.get('circulation') or [])}):\n  {rows('circulation', ('id', 'width_mm', 'path'))}\n"
        f"展台({len(plan.get('platforms') or [])}):\n  {rows('platforms', ('id', 'name', 'kind', 'polygon', 'corner_radius_mm'))}\n"
        f"家具({len(plan.get('furniture') or [])}):\n  {rows('furniture', ('id', 'catalog_id', 'x', 'y', 'rot'))}\n"
        f"天花: 灯槽 {len(ceiling.get('coves') or [])} / 灯位 {len(ceiling.get('fixtures') or [])}\n"
        f"面积表: {json.dumps(plan.get('area_table'), ensure_ascii=False)}\n"
        f"未决项: {json.dumps(plan.get('open_questions'), ensure_ascii=False)}\n"
        f"引用规范: {json.dumps(plan.get('standards_cited'), ensure_ascii=False)}"
    )
