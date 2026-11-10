"""Download actual frozen draft artifacts with their unsigned review record."""
import hashlib
import io
import json
import zipfile
from .api_service import ApiError
from .review_tasks import tasks


def package(accounts, service, identity, project, task_id):
    result = tasks(accounts, service, identity, project)
    task = next((item for item in result['items'] if item['task_id'] == task_id), None)
    if task is None:
        raise ApiError(404, 'NOT_FOUND', '审查事项不存在')
    output = io.BytesIO()
    total = 0
    entries = []
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for index, artifact in enumerate(task['snapshot']['artifacts']):
            try:
                metadata, path = service.get_production_artifact(identity.organization_id, project, artifact['artifact_id'])
            except (ApiError, OSError) as error:
                raise ApiError(409, 'REVIEW_ARTIFACT_CHANGED', '送审成果缺失或变化，不能生成审核包') from error
            if metadata['size_bytes'] > 32 * 1024 * 1024 - total:
                raise ApiError(413, 'EVIDENCE_TOO_LARGE', '审核包超过32MiB，请分别下载成果')
            try:
                data = path.read_bytes()
            except OSError as error:
                raise ApiError(409, 'REVIEW_ARTIFACT_CHANGED', '送审成果不可读取') from error
            digest = hashlib.sha256(data).hexdigest()
            if len(data) != metadata['size_bytes'] or digest != artifact['sha256']:
                raise ApiError(409, 'REVIEW_ARTIFACT_CHANGED', '送审成果缺失或变化，不能生成审核包')
            total += len(data)
            # Names are generated, never accepted as archive paths from inputs.
            suffix = path.suffix if path.suffix in {'.json', '.html', '.csv', '.svg', '.dxf', '.zip'} else '.bin'
            name = f'artifacts/{index + 1:02d}{suffix}'
            archive.writestr(name, data)
            entries.append({'member': name, 'filename': artifact['filename'], 'artifact_id': artifact['artifact_id'], 'sha256': digest, 'size_bytes': len(data)})
        archive.writestr('review-record.json', json.dumps({'schema_version': 'rkd-draft-review-evidence.v1', 'task': task, 'files': entries, 'formal_release_allowed': False, 'classification': '未签署草稿审核包；不构成正式报价或施工发布'}, ensure_ascii=False, indent=2).encode('utf-8'))
    return output.getvalue()
