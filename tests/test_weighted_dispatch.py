"""Actual authenticated dispatch, persistence and action provenance in test stores."""
import json

import pytest

from tests.test_direct_execution import api, isolated  # noqa: F401
from tests.test_weighted_decision import request


@pytest.fixture(autouse=True)
def calculator_storage(monkeypatch,tmp_path):
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path))


def test_a04_dispatch_calculates_persists_artifact_and_records_real_tool_actions(api,tmp_path,monkeypatch):
    from app.artifact_factory import ArtifactFactory
    from app.action_records import action_ledger
    client,compute=api
    def forbidden(*args,**kwargs):raise AssertionError('Calculator must not submit inference')
    monkeypatch.setattr(compute.queue,'submit',forbidden)
    body={'capability':'responsibility.a04','objective':'Compare the supplied weighted options.',
          'context':json.dumps(request()),'deterministic_operation':'weighted_decision'}
    assert client.post('/api/agents/dispatch',json=body).status_code==401
    response=client.post('/api/agents/dispatch',headers={'Authorization':'Bearer isolated-test-owner'},json=body)
    assert response.status_code==202,response.text
    result=response.json()
    assert result['agent_id']=='a04' and result['model_calls']==0
    assert result['calculation_provider']=='deterministic' and result['calculation_action_durable']
    _,raw=ArtifactFactory(tmp_path/'artifacts').retrieve(result['artifact']['artifact_id'])
    artifact=json.loads(raw)
    assert artifact['scores']=={'A':9,'B':9} and artifact['decision']=='TIE'
    ledger=action_ledger();assert ledger.flush()
    rows=[json.loads(line) for line in ledger.path.read_text(encoding='utf-8').splitlines()]
    completed=[r for r in rows if r['phase']=='completed']
    assert {r['action_type'] for r in completed}=={'decision.weighted.calculate','decision.weighted.artifact'}
    assert all(r['agent_id']=='a04' and r['success'] is True for r in completed)
    assert result['calculation_action_id'] in {r['action_id'] for r in completed}


def test_explicit_weighted_objective_routes_to_a04_and_displays_the_persisted_calculation(api,monkeypatch):
    client,compute=api
    def forbidden(*args,**kwargs):raise AssertionError('Calculator must not submit inference')
    monkeypatch.setattr(compute.queue,'submit',forbidden)
    headers={'Authorization':'Bearer isolated-test-owner'}
    response=client.post('/api/agents/objectives',headers=headers,json={
        'objective':'Evaluate these facts.','context':json.dumps(request()),
        'deterministic_operation':'weighted_decision'})
    assert response.status_code==202,response.text
    task=client.get('/api/agents/objectives/'+response.json()['id'],headers=headers).json()
    assert task['state']=='COMPLETED'
    assert task['steps'][0]['capability']=='responsibility.a04'
    assert task['result']['type']=='DETERMINISTIC_CALCULATION'
    assert task['result']['authoritative'] is False
    assert json.loads(task['result']['text'])['decision']=='TIE'
    assert task['execution_metadata']['inference_attempts']['status']=='NOT_APPLICABLE'


def test_wrong_role_and_missing_criterion_fail_the_affected_request_only(api):
    client,_=api
    headers={'Authorization':'Bearer isolated-test-owner'}
    body={'capability':'responsibility.a17','objective':'Compare.',
          'context':json.dumps(request()),'deterministic_operation':'weighted_decision'}
    assert client.post('/api/agents/dispatch',headers=headers,json=body).status_code==422
    body['capability']='responsibility.a04'
    value=request();del value['option_criterion_scores'][1]['speed'];body['context']=json.dumps(value)
    assert client.post('/api/agents/dispatch',headers=headers,json=body).status_code==422
    body['context']=json.dumps(request())
    assert client.post('/api/agents/dispatch',headers=headers,json=body).status_code==202


def test_thin_objective_contract_accepts_the_explicit_calculator_operation():
    from app.interface_node import Objective
    body=Objective(objective='Compare.',context=json.dumps(request()),
        idempotency_key='weighted-fixture',deterministic_operation='weighted_decision')
    assert body.deterministic_operation=='weighted_decision'
