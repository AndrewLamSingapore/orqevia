import hashlib
import json
import time
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import interface_contract, agent_dispatch_api


def test_deterministic_native_contract_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('ORQEVIA_REGISTRY_V1_ENABLED','1')
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN','fixture-owner')
    monkeypatch.setenv('ORQEVIA_INTERFACE_CLIENTS_JSON',json.dumps({'fixture':{
        'token_sha256':hashlib.sha256(b'fixture-client').hexdigest(),
        'expires_at':time.time()+300,
        'capabilities':['objective.submit','task.read','task.cancel','artifact.read']}}))
    app=FastAPI();app.include_router(interface_contract.router)
    headers={'X-Client-ID':'fixture','Authorization':'Bearer fixture-client'}
    body={'objective':'Hash these exact supplied bytes','context':'abc','idempotency_key':'same',
          'deterministic_operation':'sha256'}
    before=agent_dispatch_api.deterministic_ops.metrics.copy()
    with patch('app.compute_queue_api.queue.submit',side_effect=AssertionError('Model queue forbidden')):
        with TestClient(app,base_url='https://testserver') as client:
            result=client.post('/interface/v1/objectives',json=body,headers=headers)
            assert result.status_code==202, result.text
            task=result.json()['task_id']
            status=client.get('/interface/v1/tasks/'+task,headers=headers).json()
            assert status['state']=='COMPLETED' and len(status['steps'])==1
            dispatch=status['steps'][0]['dispatch']
            assert dispatch['model_calls']==0 and dispatch['artifact']['task_id']==task
            artifact=client.get('/interface/v1/artifacts/'+dispatch['artifact']['artifact_id'],headers=headers)
            assert artifact.status_code==200
            assert hashlib.sha256(artifact.content).hexdigest()==artifact.headers['X-Artifact-SHA256']
            assert json.loads(artifact.content)==hashlib.sha256(b'abc').hexdigest()
            assert client.post('/interface/v1/objectives',json=body,headers=headers).json()['task_id']==task
            assert client.post('/interface/v1/tasks/'+task+'/cancel',headers=headers).json()['jobs']==[]
            body['idempotency_key']='second'
            second=client.post('/interface/v1/objectives',json=body,headers=headers)
            assert second.status_code==202 and second.json()['task_id']!=task
    after=agent_dispatch_api.deterministic_ops.metrics
    assert after['operations']-before['operations']==2
    assert after['hits']-before['hits']>=1


def test_invalid_deterministic_input_is_blocked_not_completed(tmp_path,monkeypatch):
    from app.objective_api import submit,get,ObjectiveRequest
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('ORQEVIA_REGISTRY_V1_ENABLED','1')
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN','fixture-owner')
    result=submit(ObjectiveRequest(objective='Validate supplied JSON',context='{"a":1,"a":2}',deterministic_operation='json_validate'),'Bearer fixture-owner')
    status=get(result['id'],'Bearer fixture-owner')
    assert status['state']=='COMPLETED_WITH_FAILURES'
    assert status['steps'][0]['state']=='blocked'
    assert not (tmp_path/'artifacts').exists()


def test_external_surface_has_no_owner_or_legacy_routes():
    from app.interface_server import app
    paths=set(app.openapi()["paths"])
    paths.update(route.path for route in app.routes if hasattr(route,"path"))
    allowed_prefixes=('/interface/v1/','/pwa','/integration/')
    bounded_bridge={
        '/api/orqevia/{path:path}','/orqevia/{path:path}',
        '/api/orqevia/{path}','/orqevia/{path}',
    }
    assert paths and all(path.startswith(allowed_prefixes) or path in bounded_bridge for path in paths)
    assert not any(path.startswith('/control') for path in paths)
    assert not any(path.startswith('/api/') and path not in bounded_bridge for path in paths)


def test_future_build_observations_preserve_unknown_measurements(tmp_path,monkeypatch):
    from app.engineering_loop import build_verify
    monkeypatch.setenv('ORQEVIA_DATA_DIR',str(tmp_path))
    calls=[]
    def builder(objective,feedback):
        calls.append(feedback)
        return 'fixed' if feedback else 'broken'
    def verifier(path):
        passed=path.read_text()=='fixed'
        return {'passed':passed,'verdict':'ACCEPT' if passed else 'REJECT','verifier':'a18',
            'independent':True,'candidate_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'checks':[{'name':'fixture-content','status':'PASS' if passed else 'FAIL',
                'evidence_ref':'fixture:test_next_integration'}]}
    result=build_verify(root=tmp_path/'fixture-trial',objective='fixture only',builder=builder,
        verifier=verifier,model='fixture-model',backend='fixture-backend')
    assert result['state']=='VERIFIED_CANDIDATE' and len(result['attempts'])==2
    obs=result['attempts'][1]['observation']
    assert obs['repair_cycles']==1 and obs['artifact_sha256_verified'] and obs['final_artifact_validation']
    assert obs['input_tokens'] is None and obs['cost_usd'] is None and obs['handoff_accuracy'] is None
    assert calls[0] is None and calls[1]['passed'] is False and calls[1]['verdict']=='REJECT'
