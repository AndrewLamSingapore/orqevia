"""Real existing HTTP objective/dispatch/artifact interfaces; simulated service only."""
import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent_registry import load_agent_registry
from app.action_records import close_ledgers

AGENTS=load_agent_registry()['agents']
HEADERS={'Authorization':'Bearer public-test-owner-not-a-live-credential'}


@pytest.fixture
def client(tmp_path,monkeypatch):
    close_ledgers()
    monkeypatch.setenv('PRIME_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('PRIME_SPINE_TOKEN','public-test-owner-not-a-live-credential')
    monkeypatch.setenv('PRIME_REGISTRY_V1_ENABLED','1')
    monkeypatch.setenv('PRIME_FINANCIAL_SIMULATION_ENABLED','1')
    monkeypatch.setenv('PRIME_SOURCE_REVISION','simulation-test-not-live')
    from app.direct_entry import app
    # No lifespan: no worker/model starts. All routes are the actual application routes.
    yield TestClient(app),tmp_path
    close_ledgers()


@pytest.mark.parametrize('record',AGENTS,ids=[a['immutable_id'] for a in AGENTS])
def test_actual_objective_paid_service_artifact(client,record):
    api,root=client
    capability=record['responsibilities'][0]['id']
    services=api.get('/api/financial-simulation/services',params={'capability':capability},headers=HEADERS)
    assert services.status_code==200 and services.json()['services']
    quoted=api.post('/api/financial-simulation/quote',json={'capability':capability,'service':'simulation.lookup'},headers=HEADERS)
    assert quoted.status_code==200
    req=dict(quote=quoted.json(),idempotency_key=uuid.uuid4().hex,objective='Purchase a simulated lookup for my owner objective')
    body=dict(capability=capability,objective=req['objective'],context=json.dumps(req),
              deterministic_operation='financial_simulation',classification='R0',data_classification='LOCAL_ONLY',max_cost_usd=0)
    response=api.post('/api/agents/objectives',json=body,headers=HEADERS)
    assert response.status_code==202,response.text
    result=response.json();dispatch=result['steps'][0]['dispatch']
    assert dispatch['agent_id']==record['immutable_id'] and dispatch['model_calls']==0
    assert dispatch['execution_model']=='DETERMINISTIC'
    artifact_id=dispatch['artifact']['artifact_id']
    raw=json.loads((root/'artifacts'/artifact_id/'artifact.json').read_text())
    assert raw['receipt']['state']=='SETTLED' and raw['receipt']['amount']==100
    assert raw['result']['service']=='simulation.lookup' and raw['live_spending']=='DISABLED'
    read=api.get('/api/agents/objectives/'+result['id'],headers=HEADERS)
    assert read.status_code==200 and read.json()['state']=='COMPLETED'
    audit=api.get('/api/financial-simulation/report',headers=HEADERS).json()
    assert audit['balances']['settled']==100 and len(audit['wallets'])==21
    assert audit['registry_sha256'] and all(v=='UNAVAILABLE_UNIMPLEMENTED' for v in audit['external_providers'].values())
    assert api.post('/api/observability/flush',headers=HEADERS).json()['flushed']
    rows=[json.loads(row) for row in (root/'action-records.jsonl').read_text().splitlines()]
    assert any(r['agent_id']==record['immutable_id'] and r['action_type']=='financial.simulation.artifact' and r['phase']=='completed' for r in rows)


def test_routes_are_owner_authenticated_and_default_disabled(client,monkeypatch):
    api,_=client
    for path in ['/api/financial-simulation/report','/api/financial-simulation/services?capability=responsibility.a01']:
        assert api.get(path).status_code==401
    assert api.post('/api/financial-simulation/owner-control',json={'operation':'freeze','value':True}).status_code==401
    monkeypatch.setenv('PRIME_FINANCIAL_SIMULATION_ENABLED','0')
    assert api.get('/api/financial-simulation/report',headers=HEADERS).status_code==503


def test_route_impersonation_extra_policy_and_real_provider_are_denied(client):
    api,_=client
    q=api.post('/api/financial-simulation/quote',json={'capability':'responsibility.a01','service':'simulation.lookup'},headers=HEADERS).json()
    req=dict(quote=q,idempotency_key=uuid.uuid4().hex,objective='synthetic')
    body=dict(capability='responsibility.a02',objective='synthetic',context=json.dumps(req),deterministic_operation='financial_simulation')
    response=api.post('/api/agents/dispatch',headers=HEADERS,json=body)
    assert response.status_code==202
    assert api.get('/api/financial-simulation/report',headers=HEADERS).json()['balances']['settled']==0
    assert api.post('/api/financial-simulation/quote',json={'capability':'responsibility.a01','service':'cloudflare-wallets','agent':'a02'},headers=HEADERS).status_code==422
