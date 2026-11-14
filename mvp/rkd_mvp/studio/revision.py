"""Whitelisted object patches & revision integrity (ARC-03).

The model proposes WHAT to change; the program applies the patch against an
explicit baseline, re-computes the full new version, and verifies object
retention / deletion reasons / locks. A model cannot write arbitrary JSON paths
(in particular identity, approval, adoption or price-source fields).

If a caller still supplies a full plan instead of a patch, the full plan goes
through exactly the same integrity checks; deletion without a reason, changing
a locked object, or dropping unrelated objects is rejected.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

PATCH_GROUPS = {
    "zones": {"name", "role", "polygon", "area_sqm"},
    "furniture": {"catalog_id", "x", "y", "rot", "w_mm", "d_mm"},
    "circulation": {"width_mm", "path"},
    "platforms": {"name", "kind", "corner_radius_mm", "polygon", "height_mm"},
    "ceiling.coves": {"polygon", "band_mm", "kelvin"},
    "ceiling.fixtures": {"type", "x", "y", "kelvin", "aim"},
    "area_table": {"name", "area_sqm"},
    "strategy": {"name", "narrative", "tradeoffs", "non_orthogonal"},
    "open_questions": set(),
    "standards_cited": set(),
}
ALLOWED_OPS = {"update", "add", "remove"}
FORBIDDEN_PATHS = {"project_id", "option_id", "revision", "author",
                   "contract_version", "status", "approved", "adopt_pointer",
                   "decision", "published"}


def _err(code: str, message: str, hint: str, path: str = "") -> dict:
    return {"stage": "revision", "rule_id": code, "path": path,
            "expected": "白名单 patch 或完整方案且满足修订完整性",
            "actual_type": "revision_violation", "object_id": "?",
            "message": message, "hint": hint}


def _container(plan: dict, group: str):
    if group.startswith("ceiling."):
        ceiling = plan.setdefault("ceiling", {})
        return ceiling.setdefault(group.split(".", 1)[1], [])
    return plan.setdefault(group, [])


def apply_patch(base: dict, patch: list[dict]) -> tuple[dict | None, list[dict], dict]:
    """Apply whitelisted object edits to a deep copy of the baseline.

    Returns (new_plan, errors, audit). Never mutates base. On any error the
    plan is None: a partially applied patch is not a valid revision.
    """
    errors: list[dict] = []
    audit: dict[str, Any] = {"operations": [], "rejected_operations": []}
    plan = copy.deepcopy(base)

    if not isinstance(patch, list) or not patch:
        return None, [_err("PATCH-000", "patch 为空或不是数组",
                           "输出 patch 数组，或给出完整方案走完整性校验")], audit

    for i, op in enumerate(patch):
        path = f"/patch/{i}"
        if not isinstance(op, dict):
            errors.append(_err("PATCH-001", f"patch[{i}] 不是对象", "每项写成 {op,group,id,fields,reason}", path))
            continue
        action = str(op.get("op") or "")
        group = str(op.get("group") or "")
        if action not in ALLOWED_OPS:
            errors.append(_err("PATCH-002", f"不支持的操作 {action}",
                               f"只用 {sorted(ALLOWED_OPS)}", path))
            continue
        if group not in PATCH_GROUPS:
            errors.append(_err("PATCH-003", f"不支持的对象组 {group}",
                               f"只用 {sorted(PATCH_GROUPS)}", path))
            continue
        if action == "remove" and not str(op.get("reason") or "").strip():
            errors.append(_err("PATCH-004", "删除对象没有写理由",
                               "remove 必须带 reason，说明为什么删除及替代关系", path))
            continue
        container = _container(plan, group)
        if not isinstance(container, (list, dict)):
            errors.append(_err("PATCH-005", f"{group} 不是可编辑容器",
                               "检查基线数据形状", path))
            continue

        if group == "strategy":
            fields = op.get("fields") or {}
            bad = sorted(set(fields) - PATCH_GROUPS[group])
            if bad:
                errors.append(_err("PATCH-006", f"strategy 字段不在白名单：{bad}",
                                   "只改允许的字段", path))
                continue
            plan["strategy"].update(fields)
            audit["operations"].append({"op": action, "group": group, "fields": sorted(fields)})
            continue

        if isinstance(container, list):
            # area_table rows have no `id`; their stable key is `name`.
            id_field = "name" if group == "area_table" else "id"
            oid = str(op.get("id") or op.get("name") or "")
            if not oid:
                errors.append(_err("PATCH-007", "缺少对象 id/name",
                                   "patch 必须指向具体对象；不能整组替换", path))
                continue
            idx = next((k for k, o in enumerate(container)
                        if isinstance(o, dict) and str(o.get(id_field)) == oid), None)
            if action == "add":
                if idx is not None:
                    errors.append(_err("PATCH-008", f"对象 {oid} 已存在",
                                       "新增对象用新的稳定 id/name", path))
                    continue
                obj = {id_field: oid}
                obj.update(op.get("fields") or {})
                container.append(obj)
            elif action == "update":
                if idx is None:
                    errors.append(_err("PATCH-009", f"找不到对象 {oid}",
                                       "update 只能改基线中存在的对象；不要凭空造对象", path))
                    continue
                fields = op.get("fields") or {}
                bad = sorted(set(fields) - PATCH_GROUPS[group])
                if bad:
                    errors.append(_err("PATCH-006", f"{group} 字段不在白名单：{bad}",
                                       "只改允许的字段", path))
                    continue
                container[idx].update(fields)
            else:  # remove
                if idx is None:
                    errors.append(_err("PATCH-009", f"找不到要删除的对象 {oid}",
                                       "remove 只能删基线中存在的对象", path))
                    continue
                container.pop(idx)
            audit["operations"].append({"op": action, "group": group, "id": oid,
                                        "reason": op.get("reason") or ""})
        else:
            errors.append(_err("PATCH-005", f"{group} 容器类型不支持",
                               "检查基线数据形状", path))
        # identity / approval fields are never writable
        for k in FORBIDDEN_PATHS:
            if isinstance(op.get("fields"), dict) and k in op["fields"]:
                errors.append(_err("IDENTITY-BOUNDARY", f"patch 试图写入程序所有字段 {k}",
                                   "身份/批准/采用字段由程序生成，模型不得写入", path))

    # strip program-owned identity from the derived plan: the caller will
    # re-inject it through validation.validate_proposal with the new revision.
    for k in FORBIDDEN_PATHS:
        plan.pop(k, None)
    audit["errors"] = len(errors)
    return (None, errors, audit) if errors else (plan, [], audit)


def _object_map(plan: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for group in ("zones", "furniture", "circulation", "platforms"):
        for o in (plan.get(group) or []):
            if isinstance(o, dict) and o.get("id"):
                out[f"{group}:{o['id']}"] = json.dumps(o, ensure_ascii=False, sort_keys=True)
    ceiling = plan.get("ceiling") if isinstance(plan.get("ceiling"), dict) else {}
    for group in ("coves", "fixtures"):
        for o in (ceiling.get(group) or []):
            if isinstance(o, dict) and o.get("id"):
                out[f"ceiling.{group}:{o['id']}"] = json.dumps(o, ensure_ascii=False, sort_keys=True)
    return out


def verify_revision_integrity(base: dict, candidate: dict, *,
                              responses: list[dict] | None = None,
                              issues: list[dict] | None = None,
                              lock_object_ids: list[str] | None = None,
                              boss_feedback: list[dict] | None = None) -> dict:
    """Full-output path: prove retention, deletion reasons, locks, issue linkage.

    Returns {ok, errors, changed_objects, removed_objects, added_objects,
             issue_resolutions, boss_feedback_resolutions, object_retention_ratio}
    """
    errors: list[dict] = []
    before, after = _object_map(base), _object_map(candidate)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    short_changed = [k.split(":", 1)[1] for k in changed]

    responses = [r for r in (responses or []) if isinstance(r, dict)]
    issues = [i for i in (issues or []) if isinstance(i, dict)]
    response_by_id = {str(r.get("issue_id")): r for r in responses}
    reason_text = " ".join(str(r.get("reason") or "") + " " + str(r.get("change") or "")
                           for r in responses)

    # 1. deletion must have an explicit reason (no silent dropping of objects)
    for key in removed:
        oid = key.split(":", 1)[1]
        if oid not in reason_text and not any(oid in str(i.get("objects")) for i in issues):
            errors.append(_err("REV-DELETE", f"对象 {key} 被删除但没有理由",
                               "在 responses 里写明删除原因与替代关系，或保留该对象", key))
    # 2. locked objects unchanged
    locks = set(lock_object_ids or [])
    for oid in locks:
        keys = [k for k in set(before) | set(after) if k.split(":", 1)[1] == oid]
        if any(before.get(k) != after.get(k) for k in keys):
            errors.append(_err("LOCK-REVISION", f"锁定对象 {oid} 被改动或删除",
                               "恢复该对象；无法满足时把冲突作为待决项交用户", "/"))
    # 3/4. Per-issue checks only apply when a structured review exists. An
    # automatic rework round has no fresh issue list, so it is checked for
    # retention / locks / deletion reasons but not blamed for missing linkage.
    issue_resolutions = []
    if issues:
        touched_ids = set(short_changed) | {k.split(":", 1)[1] for k in added + removed}
        issue_ids = {str(x) for i in issues for x in (i.get("objects") or [])}
        for key in before:
            oid = key.split(":", 1)[1]
            if oid in touched_ids and oid not in issue_ids and oid not in reason_text:
                errors.append(_err("REV-UNRELATED", f"与评审意见无关的对象 {key} 被无理由改动",
                                   "只改被指出的问题；无关对象保持原状", key))
    for i in issues:
        iid = str(i.get("issue_id") or "")
        r = response_by_id.get(iid)
        if not r:
            issue_resolutions.append({"issue_id": iid, "action": "missing",
                                      "verified": False, "reason": "没有逐条回应"})
            errors.append(_err("REV-ISSUE", f"评审意见 {iid} 没有逐条回应",
                               "每条意见都要 accept/reject 并写理由", f"/issues/{iid}"))
            continue
        action = str(r.get("action") or "")
        objs = [str(x) for x in (i.get("objects") or [])]
        if action == "reject":
            ok = bool(str(r.get("reason") or "").strip())
            if not ok:
                errors.append(_err("REV-REJECT", f"意见 {iid} 拒绝但未写理由",
                                   "reject 必须给出理由", f"/responses/{iid}"))
            issue_resolutions.append({"issue_id": iid, "action": "reject",
                                      "verified": ok, "reason": r.get("reason") or ""})
        elif action == "accept":
            linked = sorted(set(objs) & set(short_changed + [k.split(":", 1)[1] for k in added + removed]))
            verified = bool(linked) or bool(str(r.get("change") or "").strip()
                                            and any(k in str(r.get("change")) for k in objs))
            # A change to an arbitrary object does NOT prove this issue was fixed:
            # the object named by the issue itself must appear in the diff.
            if not linked:
                errors.append(_err("REV-ISSUE", f"意见 {iid} 被接受，但其对象 {objs} 没有出现在对象 diff 中",
                                   "按意见改对应对象；不能改任意一个别的对象就宣称全部落实",
                                   f"/responses/{iid}"))
            issue_resolutions.append({"issue_id": iid, "action": "accept",
                                      "verified": bool(linked), "linked_objects": linked,
                                      "recheck": "对象 diff 复核" if linked else "未通过",
                                      "change": r.get("change") or ""})
        else:
            issue_resolutions.append({"issue_id": iid, "action": action or "unknown",
                                      "verified": False, "reason": "action 只能是 accept/reject"})
            errors.append(_err("REV-ISSUE", f"意见 {iid} 的 action 非法",
                               "写成 accept 或 reject", f"/responses/{iid}"))
    # 5. boss feedback must be visibly referenced by the revision input
    boss_resolutions = []
    for fb in (boss_feedback or []):
        text = str(fb.get("text") or "")
        boss_resolutions.append({
            "feedback_id": fb.get("feedback_id"), "revision_no": fb.get("revision_no"),
            "text": text, "in_revision_input": True,
            "linked_changes": short_changed,
            "note": "老板留言已进入修订输入；是否真正满足由用户对具体图面判定",
        })
    retention = (len(set(before) & set(after)) / len(before)) if before else 1.0
    return {
        "ok": not errors, "errors": errors,
        "changed_objects": changed, "removed_objects": removed, "added_objects": added,
        "object_retention_ratio": round(retention, 3),
        "issue_resolutions": issue_resolutions,
        "boss_feedback_resolutions": boss_resolutions,
        "accepted_issues_verified": sum(1 for r in issue_resolutions
                                        if r["action"] == "accept" and r["verified"]),
        "accepted_issues_total": sum(1 for r in issue_resolutions if r["action"] == "accept"),
    }


def revision_input_hash(base: dict, issues: list[dict], feedback: list[dict],
                        baseline_id: str, baseline_uid: str) -> str:
    raw = json.dumps({"baseline_id": baseline_id, "baseline_uid": baseline_uid,
                      "base": base, "issues": issues, "feedback": feedback},
                     ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
