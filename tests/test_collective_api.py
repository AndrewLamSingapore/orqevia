import json
import pytest
from fastapi.testclient import TestClient
from app.collective_api import WorkspaceRequest,execute_workspace
from app.capability_broker import CoreRequest,execute_core_request,ServiceRequest,execute_request
from app.collective_workspace import CollectiveWorkspace
from app.action_records import ActionLedger
from app.agent_registry import registered_agent_ids

JOB='11111111-1111-4111-8111-111111111111'
class Queue:
    def __init__(self,actor):self.actor=actor
    def get(self,key):return {'agent':self.actor,'id':key,'prompt':'PRIVATE','data_classification':'LOCAL_ONLY'}

@pytest.mark.parametrize('actor',sorted(registered_agent_ids()))
def test_authenticated_principal_can_write_read_and_publish_own_note(actor,tmp_path):
    store=CollectiveWorkspace(tmp_path/'store.db');ledger=ActionLedger(tmp_path/'audit.jsonl')
    try:
        def call(operation,**parameters):
            return execute_workspace(WorkspaceRequest(actor=actor,job_id=None if actor=='prime' else JOB,operation=operation,parameters=parameters),
                                     job_queue=Queue(actor),store=store,ledger=ledger)
        assert call('sketch.write',owner=actor,entry='checkpoint',note={'objective':'Engineering work','next_actions':['Review retained evidence']},checkpoint=True)['result']==1
        assert call('sketch.read',owner=actor,entry='checkpoint')['result']['checkpoint']==1
        call('board.subscribe',board='EVIDENCE')
        message=call('board.post',board='EVIDENCE',key='note-1',note={'summary':'Bounded source receipt; not certification'})['result']
        assert call('board.pending')['result'][0]['id']==message
        call('board.ack',message=message)
        with pytest.raises(PermissionError):call('sketch.read',owner='a02' if actor!='a02' else 'a01',entry='checkpoint')
    finally:ledger.close()

def test_core_internet_path_has_no_agent_job_dependency(tmp_path):
    ledger=ActionLedger(tmp_path/'audit.jsonl')
    try:
        result=execute_core_request(CoreRequest(request_id='core-public-probe',service='internet.public.read',parameters={'url':'https://example.com'}),
             reader=lambda url:{'status':200},ledger=ledger)
        assert result['actor']=='prime' and result['independent_of_specialist_jobs']
        assert result['audit_persisted']
    finally:ledger.close()

def test_local_only_task_cannot_disclose_public_request(tmp_path):
    ledger=ActionLedger(tmp_path/'audit.jsonl');calls=[]
    try:
        with pytest.raises(PermissionError):execute_request(ServiceRequest(agent='a01',job_id=JOB,service='internet.public.read',parameters={'url':'https://example.com'}),
           job_queue=Queue('a01'),reader=lambda url:calls.append(url),ledger=ledger)
        assert not calls
        assert json.loads((tmp_path/'audit.jsonl').read_text().splitlines()[-1])['success'] is False
    finally:ledger.close()

def test_unauthenticated_and_oversized_service_body_rejected_before_operation(monkeypatch):
    monkeypatch.setenv('PRIME_SPINE_TOKEN','owner-fixture-key-never-production')
    from app.direct_entry import app
    with TestClient(app,raise_server_exceptions=False) as client:
        assert client.post('/api/capabilities/request',content='not-json').status_code==401
        assert client.post('/api/capabilities/request',content='x'*300001,
                           headers={'Authorization':'Bearer owner-fixture-key-never-production'}).status_code==413
        assert client.post('/api/capabilities/request',content='{"agent":"a01","agent":"a02"}',
                           headers={'Authorization':'Bearer owner-fixture-key-never-production'}).status_code==422
        assert client.post('/api/capabilities/request',content='{"parameters":{"value":NaN}}',
                           headers={'Authorization':'Bearer owner-fixture-key-never-production'}).status_code==422
