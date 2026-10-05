"""The live adapter retains authentication, role binding and non-certification."""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.agent_execution_live import observe_live_baseline


def test_live_adapter_rejects_missing_owner_credential(monkeypatch):
    monkeypatch.setenv('PRIME_SPINE_TOKEN', 'fixture-owner')
    with pytest.raises(HTTPException) as denied:
        observe_live_baseline('a19', 'responsibility.a19', authorization='')
    assert denied.value.status_code == 401


def test_live_adapter_dispatches_authenticated_local_only_and_observes(monkeypatch):
    monkeypatch.setenv('PRIME_SPINE_TOKEN', 'fixture-owner')
    from app import agent_dispatch_api, compute_queue_api

    job_id = str(uuid.uuid4())
    observed = {}

    def dispatch(body, authorization, **_):
        assert authorization == 'Bearer fixture-owner'
        assert body.capability == 'responsibility.a19'
        assert body.data_classification == 'LOCAL_ONLY'
        assert body.max_cost_usd == 0
        assert body.priority == 'low'
        observed['objective'] = body.objective
        return {'capability': body.capability, 'job': {'id': job_id, 'agent': 'a19'}}

    def get_job(requested_id):
        assert requested_id == job_id
        now = datetime.now(timezone.utc).isoformat()
        marker = observed['objective'].split(': ')[-1]
        return {'id': job_id, 'agent': 'a19', 'prompt': observed['objective'],
                'status': 'completed', 'result': marker, 'provider': 'ollama-fast',
                'started_at': now, 'completed_at': now, 'attempts': 1, 'error': ''}

    monkeypatch.setattr(agent_dispatch_api, 'dispatch_request', dispatch)
    monkeypatch.setattr(compute_queue_api.queue, 'get', get_job)
    result = observe_live_baseline('a19', 'responsibility.a19',
                                   authorization='Bearer fixture-owner')
    assert result['state'] == 'EXECUTED'
    assert result['challenge_returned'] is True
    assert result['certification'] == 'UNVERIFIED'
    assert result['job_id'] == job_id
    assert 'fixture-owner' not in str(result)
