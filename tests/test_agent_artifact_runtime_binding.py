"""Mocked dispatch regressions; these do not certify a live agent."""
import json
import pytest
from fastapi import HTTPException

from app import agent_dispatch_api as dispatch
from app import runtime_status
from app.artifact_factory import ArtifactFactory


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv('PRIME_REGISTRY_V1_ENABLED', '1')
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', 'd' * 40)
    monkeypatch.setattr(dispatch, 'authenticate_owner', lambda _: None)
    monkeypatch.setattr(runtime_status, 'production_health',
                        lambda: {'observation': 'OBSERVED', 'http_status': 200,
                                 'status': 'UNKNOWN', 'ok': True})
    return tmp_path


def test_a19_report_binds_source_and_effective_capability(configured):
    result = dispatch.dispatch_request(dispatch.AgentRequest(
        capability='auto', objective=runtime_status.OBJECTIVE), 'owner-test')
    metadata, raw = ArtifactFactory(configured / 'artifacts').retrieve(
        result['artifact']['artifact_id'])
    assert metadata['runtime_revision'] == 'd' * 40
    assert result['agent_id'] == 'a19'
    assert result['capability'] == 'responsibility.a19'
    assert result['runtime_source_revision'] == metadata['runtime_revision']
    assert metadata['creator_agents'] == ['a19']
    assert metadata['task_id'] == result['task_id'] == json.loads(raw)['task_id']
    assert result['model_calls'] == 0


@pytest.mark.parametrize('source', ['', 'UNKNOWN', 'bad' * 14])
def test_missing_or_invalid_source_never_becomes_a_current_revision(configured, monkeypatch, source):
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', source)
    result = dispatch.dispatch_request(dispatch.AgentRequest(
        capability='responsibility.a19', objective=runtime_status.OBJECTIVE), 'owner-test')
    assert result['artifact']['runtime_revision'] == 'UNKNOWN'
    assert result['runtime_source_revision'] == 'UNKNOWN'
    assert result['model_calls'] == 0


def test_source_binding_does_not_bypass_owner_authentication(configured, monkeypatch):
    def reject(_):
        raise HTTPException(401, 'Owner authentication required')
    monkeypatch.setattr(dispatch, 'authenticate_owner', reject)
    with pytest.raises(HTTPException) as failure:
        dispatch.dispatch_request(dispatch.AgentRequest(
            capability='responsibility.a19', objective=runtime_status.OBJECTIVE), None)
    assert failure.value.status_code == 401
    assert not (configured / 'artifacts').exists()
