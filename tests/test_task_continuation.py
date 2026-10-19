import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from tests.test_workflow_objective_integration import WorkflowObjectiveIntegrationTests
from app import objective_api
from app.operational_workflows import execute_workflow

class ContinuationTests(WorkflowObjectiveIntegrationTests):
    def start(self):return self.submit().json()['task_id']
    def follow(self,task,client='dell',**changes):
        body={'objective':self.body['objective'],'context':self.body['context'],'expected_revision':0,'idempotency_key':'follow'}
        body.update(changes)
        return self.client.post('/interface/v1/tasks/'+task+'/continue',headers=self.headers(client),json=body)
    def test_revision_artifacts_preserve_original_and_replay(self):
        task=self.start()
        db=objective_api.connect();before=db.execute('SELECT steps_json FROM objectives WHERE id=?',(task,)).fetchone()[0];db.close()
        url='/interface/v1/tasks/'+task
        original=self.client.get(url+'/artifacts',headers=self.headers()).json()
        old_id=original['latest_result_artifact_id']
        old=self.client.get('/interface/v1/artifacts/'+old_id,headers=self.headers()).content
        result=self.follow(task);assert result.status_code==202,result.text
        assert result.json()['revision']==1 and result.json()['task_id']==task
        assert self.follow(task).json()['idempotent_replay'] is True
        status=self.client.get(url,headers=self.headers()).json()
        assert status['revision']==1 and [s['revision'] for s in status['steps']]==[0,1]
        listing=self.client.get(url+'/artifacts',headers=self.headers()).json()
        assert listing['latest_result_artifact_id']!=old_id
        assert self.client.get('/interface/v1/artifacts/'+old_id,headers=self.headers()).content==old
        latest=self.client.get('/interface/v1/artifacts/'+listing['latest_result_artifact_id'],headers=self.headers()).json()
        assert latest['revision']==1 and latest['id']==task
        db=objective_api.connect();assert db.execute('SELECT steps_json FROM objectives WHERE id=?',(task,)).fetchone()[0]==before;db.close()
    def test_auth_conflicts_and_schema(self):
        task=self.start()
        assert self.follow(task,'phone').status_code==404
        assert self.client.post('/interface/v1/tasks/'+task+'/continue',json={}).status_code in (401,403)
        assert self.follow(task,expected_revision=1).status_code==409
        assert self.follow(task,minimum_tier='FLAGSHIP').status_code==422
        assert self.follow(task).status_code==202
        assert self.follow(task,context='different').status_code==409
        assert self.follow(task,idempotency_key='new').status_code==409
    def test_shared_owner_continuation(self):
        import os
        policies=json.loads(os.environ['ORQEVIA_INTERFACE_CLIENTS_JSON'])
        for policy in policies.values():policy['owner_account_id']='owner-fixture'
        with patch.dict(os.environ,{'ORQEVIA_INTERFACE_CLIENTS_JSON':json.dumps(policies)}):
            task=self.start()
            assert self.follow(task,'phone').status_code==202
            assert self.client.get('/interface/v1/tasks/'+task,headers=self.headers()).json()['revision']==1
    def test_concurrent_reservation_and_interrupted_replay(self):
        task=self.start();entered=threading.Event();release=threading.Event()
        def blocked(*args,**kwargs):
            entered.set();assert release.wait(8);return execute_workflow(*args,**kwargs)
        with patch('app.operational_workflows.execute_workflow',side_effect=blocked):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first=pool.submit(self.follow,task)
                assert entered.wait(5)
                assert self.follow(task,idempotency_key='other').status_code==409
                assert self.follow(task).status_code==409
                release.set();assert first.result().status_code==202
        db=objective_api.connect();db.execute("UPDATE objective_turns SET state='dispatching' WHERE task=?",(task,));db.commit();db.close()
        assert self.follow(task).status_code==409

    def test_cancel_current_jobs_only(self):
        from app import interface_node as node
        task=self.start()
        fake={'revision':1,'steps':[{'revision':0,'job':{'status':'running'},'dispatch':{'job':{'id':'old'}}},
            {'revision':1,'job':{'status':'completed'},'dispatch':{'job':{'id':'done'}}},
            {'revision':1,'job':{'status':'running'},'dispatch':{'job':{'id':'current'}}}]}
        with patch.object(objective_api,'get',return_value=fake),patch.object(node.compute_queue_api.queue,'cancel') as cancel:
            response=self.client.post('/interface/v1/tasks/'+task+'/cancel',headers=self.headers())
        assert response.status_code==200
        cancel.assert_called_once_with('current')
    def test_general_followup_context_bound_and_same_parent(self):
        task=self.start()
        with patch.object(objective_api,'dispatch_request',return_value={'state':'COMPLETED','result':'followup'}) as dispatch:
            result=self.follow(task,objective='Explain the prior result',context='x'*76000)
        assert result.status_code==202,result.text
        for call in dispatch.call_args_list:
            assert call.kwargs['parent_task_id']==task
            body=call.args[0]
            assert len(body.context)<=80000
            assert 'UNTRUSTED_PRIOR_TASK_EVIDENCE' in body.context
            assert body.objective=='Explain the prior result'
