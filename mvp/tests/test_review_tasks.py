from copy import deepcopy
import unittest
from mvp.tests import test_asgi_transport as transport
from rkd_mvp.design_rules import DEFAULT_PROGRAM


class ReviewTaskTests(unittest.TestCase):
    setUp = transport.ASGITransportTests.setUp
    tearDown = transport.ASGITransportTests.tearDown
    login = transport.ASGITransportTests.login
    # Reuse only fixture/helpers, not the transport test cases.
    def seed(self):
        self.login()
        actor=self.client.get('/api/v1/auth/session').json()['user']['user_id']
        s=self.service
        s.create_requirement_draft('org-local','alpha',actor,{})
        s.update_requirement('org-local','alpha',actor,{'expected_revision':1,'design_program':deepcopy(DEFAULT_PROGRAM),'change_reason':'test'})
        s.create_design('org-local','alpha',actor,{'expected_revision':0,'requirement_revision_no':2,'change_reason':'test'})
        self.price('100',actor)
        self.path='/api/v1/projects/alpha/review-tasks'
        self.actor=actor
        return actor

    def price(self,cost,actor):
        current=self.service.get_production('org-local','alpha')
        self.service.save_production_settings('org-local','alpha',actor,{'expected_version':current['settings']['version'],'expected_design_revision':1,'settings':{**current['settings'],'unit_cost_net':cost,'source_label':'test'}})

    def submit(self):
        evidence=self.client.get('/api/v1/projects/alpha/review-readiness').json()['evidence_sha256']
        return self.client.post(self.path,json={'evidence_sha256':evidence})

    def staff(self,name='staff'):
        user=self.client.post('/api/v1/auth/users',json={'username':name,'display_name':name,'password':self.password}).json()['user_id']
        self.client.post('/api/v1/projects/alpha/members',json={'user_id':user,'role':'viewer'})
        return user

    def position(self,user,version=0):
        response=self.client.patch('/api/v1/auth/review-positions/design_reviewer',json={'name':'Design','active':True,'user_ids':[user],'expected_version':version})
        self.assertEqual(response.status_code,200,response.text)

    def test_assignment_self_review_dedup_and_record(self):
        actor=self.seed(); user=self.staff()
        response=self.submit(); self.assertEqual(response.status_code,200,response.text)
        rows=response.json()['items']; self.assertEqual(len(rows),2)
        self.assertTrue(all(r['routing_status']=='awaiting_assignment' for r in rows))
        self.assertEqual([r['task_id'] for r in rows],[r['task_id'] for r in self.submit().json()['items']])
        task=next(r for r in rows if r['position_key']=='design_reviewer')
        self.position(actor)
        body={'expected_version':1,'status':'reviewed','note':'draft only','checklist':[{'code':code,'status':'unknown','note':'not verified','artifact_ids':[]} for code in ('site_boundary','drawing_scope','professional_scope')]}
        self.assertEqual(self.client.post(self.path+'/'+task['task_id'],json=body).status_code,403)
        self.position(user,1)
        self.client.cookies.clear(); self.login('staff')
        current=self.client.get(self.path).json()['items']
        self.assertTrue(next(r for r in current if r['task_id']==task['task_id'])['can_review'])
        self.assertEqual(self.submit().status_code,403)
        response=self.client.post(self.path+'/'+task['task_id'],json=body)
        self.assertEqual(response.status_code,200,response.text)
        row=next(r for r in response.json()['items'] if r['task_id']==task['task_id'])
        self.assertEqual(row['reviewer_id'],user); self.assertEqual(row['version'],2)
        self.assertFalse(row['formal_release_allowed'])
        self.assertEqual(self.client.post(self.path+'/'+task['task_id'],json=body).status_code,409)
        self.assertEqual(self.client.patch('/api/v1/projects/alpha',json={'name':'no','expected_version':1}).status_code,403)

    def test_reroute_revoke_stale_and_bad_note(self):
        actor=self.seed(); first=self.staff('first'); second=self.staff('second')
        self.position(first)
        task=next(r for r in self.submit().json()['items'] if r['position_key']=='design_reviewer')
        self.position(second,1)
        body={'expected_version':1,'status':'reviewed','note':'draft only','checklist':[{'code':code,'status':'unknown','note':'not verified','artifact_ids':[]} for code in ('site_boundary','drawing_scope','professional_scope')]}
        self.client.cookies.clear(); self.login('first')
        self.assertEqual(self.client.post(self.path+'/'+task['task_id'],json=body).status_code,403)
        self.client.cookies.clear(); self.login('second')
        self.assertEqual(self.client.post(self.path+'/'+task['task_id'],json={**body,'note':' '}).status_code,400)
        self.assertEqual(self.client.get('/api/v1/projects/beta/review-tasks').status_code,404)
        self.price('101',actor)
        row=next(r for r in self.client.get(self.path).json()['items'] if r['task_id']==task['task_id'])
        self.assertTrue(row['source_outdated']); self.assertFalse(row['can_review'])
        self.assertEqual(self.client.post(self.path+'/'+task['task_id'],json=body).status_code,409)
        self.client.cookies.clear(); self.login()
        self.assertEqual(len(self.submit().json()['items']),4)
        self.price(None,actor)
        self.assertEqual(self.submit().status_code,409)
        self.client.post('/api/v1/projects/alpha/members',json={'user_id':second,'role':'none'})
        self.client.cookies.clear(); self.login('second')
        self.assertEqual(self.client.get(self.path).status_code,404)

    def test_evidence_archive_frozen_files_history_and_access(self):
        import io, json, zipfile, hashlib
        actor=self.seed(); user=self.staff()
        task=self.submit().json()['items'][0]
        url=self.path+'/'+task['task_id']+'/evidence'
        self.client.cookies.clear();self.login('staff')
        response=self.client.get(url)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.headers['content-type'],'application/zip')
        self.assertEqual(response.headers['cache-control'],'no-store')
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            record=json.loads(archive.read('review-record.json'))
            self.assertEqual(len(record['files']),8)
            for item in record['files']:
                self.assertEqual(hashlib.sha256(archive.read(item['member'])).hexdigest(),item['sha256'])
            self.assertEqual(record['task']['evidence_sha256'],task['evidence_sha256'])
            self.assertFalse(record['formal_release_allowed'])
        self.price('102',actor)
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            record=json.loads(archive.read('review-record.json'))
            self.assertTrue(record['task']['source_outdated'])
            self.assertEqual(record['task']['production_revision_id'],task['production_revision_id'])
        artifact=task['snapshot']['artifacts'][0]
        _,path=self.service.get_production_artifact('org-local','alpha',artifact['artifact_id'])
        data=path.read_bytes();path.write_bytes(b'X'*len(data))
        self.assertNotEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get('/api/v1/projects/beta/review-tasks/'+task['task_id']+'/evidence').status_code,404)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(url).status_code,401)

    def test_checklist_validation_atomicity_and_persistence(self):
        import io,json,zipfile
        self.seed();uid=self.staff();self.position(uid)
        task=next(r for r in self.submit().json()['items'] if r['position_key']=='design_reviewer')
        self.client.cookies.clear();self.login('staff')
        url=self.path+'/'+task['task_id']
        body={'expected_version':1,'status':'reviewed','note':'draft review'}
        self.assertEqual(self.client.post(url,json=body).status_code,400)
        checks=[{'code':p['code'],'status':'unknown','note':'awaiting site evidence','artifact_ids':[]} for p in task['checklist_prompts']]
        self.assertEqual(self.client.post(url,json={**body,'checklist':[{**checks[0],'code':[]},*checks[1:]]}).status_code,400)
        checks[0]['status']='checked'
        self.assertEqual(self.client.post(url,json={**body,'checklist':checks}).status_code,400)
        checks[0]['artifact_ids']=['foreign-artifact']
        self.assertEqual(self.client.post(url,json={**body,'checklist':checks}).status_code,400)
        checks[0]['artifact_ids']=[task['snapshot']['artifacts'][0]['artifact_id']]
        checks[1]['status']='needs_changes'
        self.assertEqual(self.client.post(url,json={**body,'checklist':checks}).status_code,400)
        response=self.client.post(url,json={**body,'status':'changes_requested','checklist':checks})
        self.assertEqual(response.status_code,200,response.text)
        row=next(r for r in self.client.get(self.path).json()['items'] if r['task_id']==task['task_id'])
        self.assertEqual(row['version'],2)
        self.assertEqual(row['checklist']['items'],checks)
        self.assertFalse(row['checklist']['professional_approval'])
        with zipfile.ZipFile(io.BytesIO(self.client.get(url+'/evidence').content)) as archive:
            record=json.loads(archive.read('review-record.json'))
            self.assertEqual(record['task']['checklist']['items'],checks)

    def test_baseline_race_rolls_back_tasks_and_checklist(self):
        from unittest.mock import patch
        from rkd_mvp.review_readiness import assess
        self.seed()
        report=assess(self.service,'org-local','alpha')
        with patch('rkd_mvp.review_tasks.assess',side_effect=[report,{**report,'evidence_sha256':'changed'}]):
            response=self.client.post(self.path,json={'evidence_sha256':report['evidence_sha256']})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.client.get(self.path).json()['items'],[])
        uid=self.staff();self.position(uid)
        task=next(r for r in self.submit().json()['items'] if r['position_key']=='design_reviewer')
        self.client.cookies.clear();self.login('staff')
        checks=[{'code':p['code'],'status':'unknown','note':'awaiting evidence','artifact_ids':[]} for p in task['checklist_prompts']]
        with patch('rkd_mvp.review_tasks.assess',side_effect=[report,{**report,'evidence_sha256':'changed'}]):
            response=self.client.post(self.path+'/'+task['task_id'],json={'expected_version':1,'status':'reviewed','note':'test','checklist':checks})
        self.assertEqual(response.status_code,409)
        rows=self.client.get(self.path).json()
        row=next(r for r in rows['items'] if r['task_id']==task['task_id'])
        self.assertEqual(row['version'],1);self.assertIsNone(row['checklist'])
        self.assertEqual(rows['summary']['pending'],2)
