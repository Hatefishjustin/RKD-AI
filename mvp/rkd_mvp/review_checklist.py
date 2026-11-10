"""Versioned prompts for human draft review, never automatic professional approval."""
from .api_service import ApiError

CHECKLISTS = {
    'design_reviewer': [('site_boundary', '现场边界、柱网及出入口证据'), ('drawing_scope', '图面范围、尺寸及材料做法'), ('professional_scope', '专业适用性与需另行核验事项')],
    'commercial_reviewer': [('quantity_scope', '工程量范围与图面对应'), ('price_source', '成本来源、加成及价格依据'), ('tax_contract', '税务及合同口径待核验事项')],
}


def prompts(position):
    return [{'code': code, 'label': label} for code, label in CHECKLISTS[position]]


def validate(position, supplied, artifacts, conclusion):
    if not isinstance(supplied, list) or len(supplied) != len(CHECKLISTS[position]):
        raise ApiError(400, 'REVIEW_CHECKLIST_REQUIRED', '请逐项填写审查结果及依据，未核验保持未知')
    expected = {code for code, _ in CHECKLISTS[position]}
    found = set()
    valid_ids = {item['artifact_id'] for item in artifacts}
    normalized = []
    for item in supplied:
        if not isinstance(item, dict) or not isinstance(item.get('code'), str) or item.get('code') not in expected or item['code'] in found:
            raise ApiError(400, 'INVALID_REVIEW_CHECKLIST', '审查项目缺失、重复或不属于本岗位')
        found.add(item['code'])
        status, note, refs = item.get('status'), item.get('note'), item.get('artifact_ids')
        if not isinstance(status, str) or status not in {'checked', 'needs_changes', 'unknown'} or not isinstance(note, str) or not 1 <= len(note.strip()) <= 1000:
            raise ApiError(400, 'INVALID_REVIEW_CHECKLIST', '每项需选择状态并填写1–1000字依据')
        if not isinstance(refs, list) or len(refs) > len(valid_ids) or any(not isinstance(ref, str) or ref not in valid_ids for ref in refs) or len(set(refs)) != len(refs):
            raise ApiError(400, 'INVALID_REVIEW_EVIDENCE', '只能引用本次送审版本的成果')
        if status == 'checked' and not refs:
            raise ApiError(400, 'REVIEW_EVIDENCE_REQUIRED', '标为已核对的项目必须引用本版成果')
        if status == 'needs_changes' and conclusion != 'changes_requested':
            raise ApiError(400, 'REVIEW_CONCLUSION_CONFLICT', '有需修改项目时，整体结论必须为需要修改')
        normalized.append({'code': item['code'], 'status': status, 'note': note.strip(), 'artifact_ids': refs})
    return {'schema_version': 'rkd-draft-checklist.v1', 'items': normalized, 'professional_approval': False}
