"""Evidence-based pre-review checks. This grants no professional authority."""
import hashlib
import json
from datetime import datetime, timezone

from .api_service import ApiError


def assess(service, organization, project):
    service.get_project(organization, project)
    production = service.get_production(organization, project)['item']
    checks = []
    def check(code, label, passed):
        checks.append({'code': code, 'label': label, 'status': 'passed' if passed else 'blocked'})
    check('production_present', '已有生产草稿', production is not None)
    artifacts = []
    baseline = None
    if production:
        baseline = {'production_revision_id': production['production_revision_id'],
                    'production_revision_no': production['revision_no'], 'sources': production['baseline']}
        check('current_sources', '成果引用当前需求与设计版本', production['status'] == 'draft')
        check('cost_known', '成本与含税试算已有明确值',
              production['quote'].get('cost_net') is not None and production['quote'].get('sale_gross') is not None)
        for artifact in production['artifacts']:
            try:
                metadata, path = service.get_production_artifact(organization, project, artifact['artifact_id'])
                data = path.read_bytes()
                valid = len(data) == metadata['size_bytes'] and hashlib.sha256(data).hexdigest() == metadata['sha256']
            except (ApiError, OSError):
                valid = False
            artifacts.append({'artifact_id': artifact['artifact_id'], 'filename': artifact['filename'],
                              'sha256': artifact.get('sha256'), 'verified': valid})
        check('artifact_integrity', '全部成果文件可读取且大小与哈希一致', bool(artifacts) and all(a['verified'] for a in artifacts))
        current = service.get_production(organization, project)['item']
        if not current or current['production_revision_id'] != production['production_revision_id'] or current['status'] != production['status']:
            raise ApiError(409, 'REVIEW_BASELINE_CHANGED', '检查期间生产基线变化，请重新检查')
    # These facts have no implemented verification authority yet. Unknown must
    # remain explicit even when deterministic software checks pass.
    pending = [
        {'code': 'site_boundary', 'label': '现场边界、柱网与出入口复核', 'status': 'unknown'},
        {'code': 'professional_compliance', 'label': '专业规范、消防与无障碍适用性审查', 'status': 'unknown'},
        {'code': 'commercial_tax', 'label': '正式价格、税务和合同口径核验', 'status': 'unknown'},
        {'code': 'responsible_review', 'label': '有权责任人审查、职责分离与签署', 'status': 'not_configured'},
    ]
    payload = {'schema_version': 'rkd-pre-review.v1', 'project_id': project, 'baseline': baseline,
               'checks': checks, 'artifacts': artifacts, 'pending_professional_reviews': pending,
               'engineering_checks_passed': all(c['status'] == 'passed' for c in checks),
               'formal_release_allowed': False, 'classification': '规则生产草稿，非正式报价或施工图',
               'scope': '当前地坪生产草稿送审前检查；不代表专业批准或跨项目准确率评估'}
    payload['evidence_sha256'] = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    payload['checked_at'] = datetime.now(timezone.utc).isoformat()
    return payload
