"""Position-routed internal draft review. No formal signature or external send."""
import json
from .api_service import ApiError
from .models import new_id, now_iso
from .review_readiness import assess
from .review_checklist import prompts, validate


def eligible(accounts, db, identity, project, position, excluded):
    positions={r['position_key']:r for r in db.query('review_positions',(identity.organization_id,))}
    if position not in positions or not positions[position]['active']:
        return []
    result=[]
    for member in db.query('review_position_members',(identity.organization_id,position)):
        uid=member['user_id']
        user=db.query('scoped_user',(identity.organization_id,uid)).fetchone()
        access=db.query('member',(identity.organization_id,project,uid)).fetchone()
        if user and user['active'] and uid not in excluded and (user['is_admin'] or access):
            result.append(uid)
    return result


def tasks(accounts, service, identity, project, body=None, task_id=None):
    accounts.authorize(identity,f'/api/v1/projects/{project}/review-tasks','GET')
    with accounts.repository.transaction(project_id=project) as db:
        existing=list(db.query('review_tasks',(identity.organization_id,project)))
    if body is None and not existing:
        return {'items':[], 'formal_release_allowed':False}
    report=assess(service,identity.organization_id,project)
    production=service.get_production(identity.organization_id,project)['item']
    author=production.get('actor_id') if production else None
    with accounts.repository.transaction(project_id=project,write=body is not None) as db:
        org=identity.organization_id
        if body is not None and task_id is None:
            member=db.query('member',(org,project,identity.actor_id)).fetchone()
            if not identity.is_admin and (not member or member['role']!='manager'):
                raise ApiError(403,'MANAGER_REQUIRED','仅项目负责人可送审')
            if not report['engineering_checks_passed'] or body.get('evidence_sha256')!=report['evidence_sha256']:
                raise ApiError(409,'REVIEW_NOT_READY','生产草稿缺项或检查已变化，请重新检查')
            current=list(db.query('review_tasks',(org,project)))
            for key in accounts.REVIEW_POSITIONS:
                if any(r['position_key']==key and r['evidence_sha256']==report['evidence_sha256'] for r in current):
                    continue
                tid=new_id('review-task')
                payload={**report,'production_author_id':author}
                db.query('insert_review_task',(org,project,tid,key,report['evidence_sha256'],production['production_revision_id'],json.dumps(payload,ensure_ascii=True),identity.actor_id,now_iso(),'pending',1,None,None,None))
                accounts._audit(db,identity.actor_id,org,'review_task.created',tid,{'position_key':key,'evidence_sha256':report['evidence_sha256']},project)
        rows=[dict(r) for r in db.query('review_tasks',(org,project))]
        if task_id:
            row=next((r for r in rows if r['task_id']==task_id),None)
            if row is None:raise ApiError(404,'NOT_FOUND','审查事项不存在')
            payload=json.loads(row['payload_json'])
            receivers=eligible(accounts,db,identity,project,row['position_key'],{row['creator_id'],payload.get('production_author_id')})
            if identity.actor_id not in receivers:raise ApiError(403,'REVIEWER_REQUIRED','需有效岗位及项目权限，不能审核自己提交或制作的成果')
            if row['evidence_sha256']!=report['evidence_sha256']:raise ApiError(409,'REVIEW_BASELINE_CHANGED','成果已变化，请重新送审')
            if row['status']!='pending' or body.get('expected_version')!=row['version']:raise ApiError(409,'STALE_REVIEW','事项已处理或版本变化')
            note=body.get('note'); status=body.get('status')
            if status not in {'reviewed','changes_requested'} or not isinstance(note,str) or not 1<=len(note.strip())<=2000:
                raise ApiError(400,'INVALID_REVIEW','请选择草稿审查结论并填写1–2000字说明')
            checklist=validate(row['position_key'],body.get('checklist'),payload['artifacts'],status)
            db.query('insert_review_checklist',(task_id,org,project,json.dumps(checklist,ensure_ascii=True)))
            db.query('finish_review_task',(status,identity.actor_id,note.strip(),now_iso(),org,project,task_id,row['version']))
            accounts._audit(db,identity.actor_id,org,'review_task.reviewed',task_id,{'status':status,'note':note.strip(),'evidence_sha256':row['evidence_sha256']},project)
            rows=[dict(r) for r in db.query('review_tasks',(org,project))]
        checklists={r['task_id']:json.loads(r['checklist_json']) for r in db.query('review_checklists',(org,project))}
        result=[]
        for row in rows:
            payload=json.loads(row.pop('payload_json'))
            receivers=eligible(accounts,db,identity,project,row['position_key'],{row['creator_id'],payload.get('production_author_id')})
            stale=row['evidence_sha256']!=report['evidence_sha256']
            row.update(checklist_prompts=prompts(row['position_key']),checklist=checklists.get(row['task_id']),snapshot=payload,source_outdated=stale,eligible_count=len(receivers),
                       routing_status='assigned' if receivers else 'awaiting_assignment',
                       can_review=identity.actor_id in receivers and not stale and row['status']=='pending',
                       formal_release_allowed=False)
            for key in ('created_at','updated_at'):
                if hasattr(row[key],'isoformat'):row[key]=row[key].isoformat()
            position_names={p['position_key']:p['name'] for p in db.query('review_positions',(org,))}
            row['position_name']=position_names.get(row['position_key'],accounts.REVIEW_POSITIONS.get(row['position_key'],row['position_key']))
            result.append(row)
        if body is not None and assess(service,org,project)['evidence_sha256']!=report['evidence_sha256']:
            raise ApiError(409,'REVIEW_BASELINE_CHANGED','保存期间生产成果变化，请重新检查')
        current=[item for item in result if not item['source_outdated']]
        unknown=sum(1 for item in current for check in (item.get('checklist') or {}).get('items',[]) if check['status']=='unknown')
        summary={'current_tasks':len(current),'pending':sum(item['status']=='pending' for item in current),
                 'changes_requested':sum(item['status']=='changes_requested' for item in current),
                 'unverified_items':unknown,'historical_tasks':len(result)-len(current),
                 'formal_release_allowed':False}
        return {'items':result,'summary':summary,'formal_release_allowed':False}
