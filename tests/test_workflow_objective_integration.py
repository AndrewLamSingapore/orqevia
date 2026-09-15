from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import interface_contract, objective_api
from app.artifact_factory import ArtifactFactory


class WorkflowObjectiveIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(os.environ['PRIME_DATA_DIR']).parent/('workflow-objective-'+uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        policy={client:{'token_sha256':hashlib.sha256(client.encode()).hexdigest(),'expires_at':time.time()+300,
            'capabilities':['objective.submit','task.read','artifact.read','task.cancel']} for client in ('dell','phone')}
        self.env=patch.dict(os.environ,{'PRIME_DATA_DIR':str(self.root),'PRIME_SPINE_TOKEN':'workflow-owner-fixture',
            'PRIME_INTERFACE_CLIENTS_JSON':json.dumps(policy)})
        self.env.start()
        app=FastAPI();app.include_router(interface_contract.router)
        self.client=TestClient(app,base_url='https://testserver')
        self.body={'objective':'Reconcile tabular totals','context':json.dumps({'rows':[
            {'item':'alpha','amount':'0.10'},{'item':'beta','amount':'0.20'}],'expected_total':'0.30'}),'idempotency_key':'one'}

    def tearDown(self):
        from app.action_records import close_ledgers
        self.client.close();close_ledgers();self.env.stop()

    def headers(self,client='dell'):
        return {'X-Client-ID':client,'Authorization':'Bearer '+client}

    def submit(self,client='dell',body=None):
        return self.client.post('/interface/v1/objectives',headers=self.headers(client),json=body or self.body)

    def test_same_client_contract_runs_roles_and_retrieves_owned_verified_artifact(self):
        with patch.object(objective_api,'dispatch_request',side_effect=AssertionError('No inference allowed')) as inference:
            response=self.submit()
        assert response.status_code==202,response.text
        assert inference.call_count==0
        task=response.json()['task_id']
        status=self.client.get('/interface/v1/tasks/'+task,headers=self.headers()).json()
        assert status['state']=='COMPLETED'
        workflow=status['steps'][0]['dispatch']['workflow']
        assert workflow['workflow_run_id']==task and workflow['validation']=='PASS'
        assert workflow['artifacts'][0]['task_id']==task
        listing=self.client.get('/interface/v1/tasks/'+task+'/artifacts',headers=self.headers()).json()
        artifact=next(row for row in listing['artifacts'] if row['artifact_id']==workflow['artifacts'][0]['artifact_id'])
        downloaded=self.client.get('/interface/v1/artifacts/'+artifact['artifact_id'],headers=self.headers())
        assert hashlib.sha256(downloaded.content).hexdigest()==artifact['sha256']
        assert downloaded.json()['valid_rows_total']=='0.30'
        assert self.client.get('/interface/v1/tasks/'+task+'/events',headers=self.headers()).status_code==200
        assert self.client.post('/interface/v1/tasks/'+task+'/cancel',headers=self.headers()).status_code==200

    def test_replay_and_concurrent_client_task_isolation(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(self.submit,('dell','phone')))
        assert all(result.status_code==202 for result in results)
        tasks=[result.json()['task_id'] for result in results]
        assert tasks[0]!=tasks[1]
        assert self.submit().json()['task_id']==tasks[0]
        for owner,other,task in [('dell','phone',tasks[0]),('phone','dell',tasks[1])]:
            assert self.client.get('/interface/v1/tasks/'+task,headers=self.headers(other)).status_code==404
            artifacts=self.client.get('/interface/v1/tasks/'+task+'/artifacts',headers=self.headers(owner)).json()['artifacts']
            assert all(row['task_id']==task for row in artifacts)
            assert self.client.get('/interface/v1/artifacts/'+artifacts[0]['artifact_id'],headers=self.headers(other)).status_code==404

    def test_unsupported_objective_or_context_keeps_existing_route(self):
        for objective,context in [('Explain the supplied facts','{}'),('Reconcile tabular totals','not-json')]:
            with patch.object(objective_api,'dispatch_request',return_value={'state':'COMPLETED','result':'existing-route'}) as dispatch:
                value=objective_api.submit(objective_api.ObjectiveRequest(objective=objective,context=context),'Bearer workflow-owner-fixture')
            assert dispatch.call_count>=1
            assert 'workflow' not in value['steps'][0]['dispatch']

    def test_failed_tool_is_persisted_without_inference_fallback(self):
        with patch.object(ArtifactFactory,'retrieve',side_effect=FileNotFoundError('fixture')):
            response=self.submit()
        task=response.json()['task_id']
        status=self.client.get('/interface/v1/tasks/'+task,headers=self.headers()).json()
        assert status['state']=='COMPLETED_WITH_FAILURES'
        assert status['steps'][0]['workflow']['validation']=='UNAVAILABLE'
        assert status['steps'][0]['workflow']['metrics']['readback_retries']==1


if __name__=='__main__':unittest.main()
