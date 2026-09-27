"""Regression: completed canonical lookup is not verified claim evidence."""
import json

import pytest

from app import objective_api, system_architecture


@pytest.fixture
def isolated_objectives(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(objective_api, 'authenticate_owner', lambda _: None)
    monkeypatch.setattr(objective_api, 'dispatch_request',
                        lambda *a, **k: pytest.fail('Canonical lookup must not invoke a model'))
    return tmp_path


@pytest.mark.parametrize('question,status,provenance', [
    ('Is Phase 2 Golden and accepted?', 'UNVERIFIED', 'CANONICAL_GOVERNANCE_SSOT'),
    ('Explain the ABEX, Dell, and PRIME architecture relationship',
     'UNAVAILABLE', 'CANONICAL_GOVERNANCE_SSOT'),
])
def test_missing_packaged_governance_never_acquires_claim_authority(
        isolated_objectives, monkeypatch, question, status, provenance):
    # Reproduces the production image's absent governance directory, not the
    # checkout's historical manifests. The task still completes its lookup.
    monkeypatch.setattr(system_architecture, 'ROOT', isolated_objectives / 'missing')
    submitted = objective_api.submit(objective_api.ObjectiveRequest(objective=question))
    task = objective_api.get(submitted['id'])
    nested = task['steps'][0]['dispatch']['system_fact']
    assert nested['status'] == status
    assert task['state'] == 'COMPLETED'
    assert task['execution_metadata']['authoritative'] is True
    assert task['result']['text'] == nested['text']
    assert task['result']['type'] == 'SYSTEM_FACT'  # Keep existing consumer shape.
    assert task['result']['authoritative'] is False
    assert task['result']['verification_status'] == status
    assert task['result']['provenance'] == provenance
    assert task['result']['may_update_truth_plane'] is False
    assert objective_api.get(submitted['id'])['result'] == task['result']


def test_registered_fact_remains_verified_without_truth_mutation_permission(isolated_objectives):
    submitted = objective_api.submit(objective_api.ObjectiveRequest(objective='How many agents do you have?'))
    task = objective_api.get(submitted['id'])
    assert task['state'] == 'COMPLETED'
    assert task['result']['authoritative'] is True
    assert task['result']['verification_status'] == 'VERIFIED'
    assert task['result']['provenance'] == 'CANONICAL_REGISTRY_AND_RUNTIME'
    assert 'REGISTERED AGENTS: 21' in task['result']['text']
    assert task['result']['may_update_truth_plane'] is False


def stored_task(facts, *, turn_facts=None):
    def steps(values):
        return [{'capability': 'system.architecture', 'dispatch': {
            'state': 'COMPLETED', 'model_backend': 'none', 'result': text,
            **({'system_fact': fact} if fact is not None else {}),
        }} for text, fact in values]
    with objective_api.connect() as db:
        db.execute('INSERT INTO objectives VALUES(?,?,?,?)',
                   ('stored-facts', 'test-digest', 'submitted', json.dumps(steps(facts))))
        if turn_facts is not None:
            db.execute('INSERT INTO objective_turns VALUES(?,?,?,?,?,?)',
                       ('stored-facts', 1, 'turn-key', 'test-digest', 'submitted', json.dumps(steps(turn_facts))))
    return objective_api.get('stored-facts')


@pytest.mark.parametrize('status', ['UNVERIFIED', 'UNAVAILABLE', 'PARTIAL', 'STALE', 'CONTRADICTED'])
def test_nonverified_lookup_state_survives_result_projection(isolated_objectives, status):
    fact = {'status': status, 'provenance': 'CANONICAL_GOVERNANCE_SSOT', 'text': 'Bounded assessment'}
    result = stored_task([(fact['text'], fact)])['result']
    assert result['verification_status'] == status
    assert result['authoritative'] is False
    assert result['provenance'] == fact['provenance']
    assert result['may_update_truth_plane'] is False


@pytest.mark.parametrize('fact', [None, {}, 'VERIFIED',
    {'status': 'VERIFIED', 'text': 'Available text'},
    {'status': 'VERIFIED', 'provenance': 'CANONICAL_REGISTRY', 'text': 'Different text'},
])
def test_missing_or_unbound_fact_metadata_does_not_promote_text(isolated_objectives, fact):
    result = stored_task([('Available text', fact)])['result']
    assert result['text'] == 'Available text'
    assert result['authoritative'] is False
    assert result['verification_status'] == 'UNVERIFIED'
    assert result['may_update_truth_plane'] is False


def test_verified_sibling_and_historical_turn_cannot_hide_missing_evidence(isolated_objectives):
    verified = {'status': 'VERIFIED', 'provenance': 'CANONICAL_REGISTRY', 'text': 'Registered facts'}
    missing = {'status': 'UNAVAILABLE', 'provenance': 'CANONICAL_GOVERNANCE_SSOT', 'text': 'Evidence missing'}
    result = stored_task([(verified['text'], verified)], turn_facts=[(missing['text'], missing)])['result']
    assert result['text'] == missing['text']
    assert result['verification_status'] == 'UNAVAILABLE'
    assert result['authoritative'] is False
    assert result['provenance'] == missing['provenance']


def test_mixed_current_facts_expose_partial_status_and_each_source(isolated_objectives):
    verified = {'status': 'VERIFIED', 'provenance': 'CANONICAL_REGISTRY', 'text': 'Registered facts'}
    missing = {'status': 'UNAVAILABLE', 'provenance': 'CANONICAL_GOVERNANCE_SSOT', 'text': 'Evidence missing'}
    result = stored_task([(verified['text'], verified), (missing['text'], missing)])['result']
    assert result['verification_status'] == 'PARTIAL'
    assert result['authoritative'] is False
    assert result['source_assessments'] == [
        {'verification_status': 'VERIFIED', 'provenance': verified['provenance']},
        {'verification_status': 'UNAVAILABLE', 'provenance': missing['provenance']},
    ]
    assert result['may_update_truth_plane'] is False
