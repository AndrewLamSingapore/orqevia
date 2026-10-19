import hashlib
import json
import os
from pathlib import Path

from tests.test_agent_dispatch_api import AgentDispatchTests
from app.artifact_factory import ArtifactFactory


class InterfaceTests(AgentDispatchTests):
    def setUp(self):
        super().setUp()
        os.environ['ORQEVIA_INTERFACE_CLIENTS_JSON']=json.dumps({client:{'token_sha256':hashlib.sha256(token.encode()).hexdigest(),
            'capabilities':['objective.submit','task.read','task.cancel','artifact.read']} for client,token in [('dell','test-dell'),('iphone','test-phone')]})

    def tearDown(self):
        os.environ.pop('ORQEVIA_INTERFACE_CLIENTS_JSON',None)
        super().tearDown()

    def test_client_identity_is_not_owner_authority_and_reconnect_is_idempotent(self):
        dell={'X-Client-ID':'dell','Authorization':'Bearer test-dell'}
        phone={'X-Client-ID':'iphone','Authorization':'Bearer test-phone'}
        assert self.client.post('/api/harness/pilot/dispatch',headers=dell,json={'actor_id':'a14','prompt':'bypass'}).status_code==401
        body={'objective':'Plan evidence review','idempotency_key':'one'}
        result=self.client.post('/api/interface/v1/objectives',headers=dell,json=body)
        assert result.status_code==202,result.text
        task=result.json()['task_id']
        repeat=self.client.post('/api/interface/v1/objectives',headers=dell,json=body).json()
        assert repeat['task_id']==task and repeat['idempotent_replay']
        changed=self.client.post('/api/interface/v1/objectives',headers=dell,json={**body,'objective':'changed'})
        assert changed.status_code==409
        assert self.client.get('/api/interface/v1/tasks/'+task,headers=dell).status_code==200
        assert self.client.get('/api/interface/v1/tasks/'+task,headers=phone).status_code==404
        artifact=ArtifactFactory(Path(os.environ['ORQEVIA_DATA_DIR'])/'artifacts').create(kind='json',content='{"verified":true}',
            task_id=task,creator='a18',provenance='Independent fixture validation')
        delivered=self.client.get('/api/interface/v1/artifacts/'+artifact['artifact_id'],headers=dell)
        assert delivered.status_code==200
        assert hashlib.sha256(delivered.content).hexdigest()==artifact['sha256']
        assert self.client.get('/api/interface/v1/artifacts/'+artifact['artifact_id'],headers=phone).status_code==404
        owner_download=self.client.get('/api/artifacts/'+artifact['artifact_id'],headers=self.headers)
        assert owner_download.content==delivered.content
        assert self.client.get('/api/artifacts/'+artifact['artifact_id'],headers=dell).status_code==401
        assert self.client.post('/api/interface/v1/tasks/'+task+'/cancel',headers=dell).status_code==200
