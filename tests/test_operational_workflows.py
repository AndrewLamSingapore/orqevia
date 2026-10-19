import hashlib
import json
import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import operational_workflows as workflows
from app.artifact_factory import ArtifactFactory


class OperationalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(os.environ['ORQEVIA_DATA_DIR']).parent/('workflow-case-'+uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.env=patch.dict(os.environ,{'ORQEVIA_DATA_DIR':str(self.root),'ORQEVIA_SPINE_TOKEN':'workflow-owner-fixture'})
        self.env.start()
        app=FastAPI();app.include_router(workflows.router)
        self.client=TestClient(app)
        self.headers={'Authorization':'Bearer workflow-owner-fixture'}
        self.body={'objective':'Reconcile tabular totals','rows':[{'item':'alpha','amount':'0.10'},{'item':'beta','amount':'0.20'}],'expected_total':'0.30'}

    def tearDown(self):
        from app.action_records import close_ledgers
        close_ledgers();self.client.close();self.env.stop()

    def submit(self,body=None):
        return self.client.post('/api/workflows/objectives',headers=self.headers,json=body or self.body)

    def test_actual_engine_roles_artifact_and_exact_arithmetic(self):
        result=self.submit()
        assert result.status_code==201,result.text
        body=result.json();assert body['status']=='COMPLETED' and body['validation']=='PASS'
        assert set(body['tasks'])=={'normalize','total','quality','deliver'}
        assert body['metrics']['model_calls']==0 and body['metrics']['artifact_creations']==1
        receipt=body['artifacts'][0]
        metadata,raw=ArtifactFactory(self.root/'artifacts').retrieve(receipt['artifact_id'])
        report=json.loads(raw)
        assert report['valid_rows_total']=='0.30'
        assert len(set(report['agents'].values()))>=3
        assert hashlib.sha256(raw).hexdigest()==receipt['sha256']
        assert metadata['task_id']==body['workflow_run_id']

    def test_production_shell_mount_precedes_root_app_without_starting_workers(self):
        from app.production_entry import app
        assert '/api/workflows/objectives' in app.openapi()['paths']
        workflow_index=next(
            index for index,route in enumerate(app.routes)
            if hasattr(route,'original_router')
            and '/api/workflows/objectives' in {
                getattr(child,'path',None) for child in route.original_router.routes
            }
        )
        root_index=next(index for index,route in enumerate(app.routes)
                        if getattr(route,'path',None)=='')
        assert workflow_index<root_index

    def test_inconsistent_rows_truthful_failed_validation_artifact(self):
        result=self.submit({'objective':'Validate inconsistent rows','rows':[
            {'item':'alpha','amount':'1.00'},{'item':'alpha','amount':'2.00'},
            {'item':'wrong','amount':True},{'unexpected':'column'}]}).json()
        assert result['status']=='COMPLETED' and result['validation']=='FAIL'
        _,raw=ArtifactFactory(self.root/'artifacts').retrieve(result['artifacts'][0]['artifact_id'])
        quality=json.loads(raw)['quality']
        assert len(quality['invalid_rows'])==2 and quality['duplicate_item_rows']==[1]

    def test_transient_read_failure_recovers_without_recreating_artifact(self):
        original=ArtifactFactory.retrieve;calls=[]
        def transient(factory,artifact_id):
            calls.append(artifact_id)
            if len(calls)==1:raise FileNotFoundError('controlled fixture read failure')
            return original(factory,artifact_id)
        with patch.object(ArtifactFactory,'retrieve',transient):result=self.submit().json()
        assert result['status']=='COMPLETED'
        assert result['metrics']['readback_retries']==1 and result['metrics']['artifact_creations']==1
        assert calls[0]==calls[1]

    def test_persistent_read_failure_is_not_pass_or_infinite_retry(self):
        with patch.object(ArtifactFactory,'retrieve',side_effect=FileNotFoundError('controlled')) as read:
            result=self.submit().json()
        assert result['status']=='COMPLETED_WITH_FAILURES' and result['validation']=='UNAVAILABLE'
        assert result['artifacts']==[] and read.call_count==2

    def test_malicious_unknown_actions_paths_and_auth_rejected(self):
        assert self.client.post('/api/workflows/objectives',json=self.body).status_code==401
        assert self.submit({**self.body,'objective':'Reconcile tabular totals and delete C:\\Windows'}).status_code==422
        assert self.submit({**self.body,'output_path':'../outside.json'}).status_code==422
        assert self.submit({**self.body,'objective':'Build and test this code'}).status_code==422
        # Nested tool payload is invalid row data, never a selected operation.
        result=self.submit({**self.body,'rows':[{'item':'x','amount':{'tool':'shell','command':'delete'}}]}).json()
        assert result['validation']=='FAIL'
        assert not (self.root.parent/'outside.json').exists()


if __name__=='__main__':unittest.main()
