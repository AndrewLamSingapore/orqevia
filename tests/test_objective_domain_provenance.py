"""Temporary persisted Objective/queue fixtures, not live qualification.

The patch changes source labels only. Completion is not verification and model
text never becomes Objective, registry, artifact or signing authority.
"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException


CREATED = '2026-10-08T00:00:00+00:00'
UPDATED = '2026-10-08T00:00:01+00:00'
STARTED = '2026-10-08T00:00:02+00:00'
COMPLETED = '2026-10-08T00:00:03+00:00'


@pytest.fixture
def domain(tmp_path, monkeypatch):
    # Queue is constructed at import. No import until its temporary path exists.
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ORQEVIA_COMPUTE_QUEUE_DB', str(tmp_path / 'fixture-queue.db'))
    monkeypatch.setenv('ORQEVIA_RUNTIME_REVISION', 'a' * 40)
    monkeypatch.setenv('ORQEVIA_RUNTIME_IMAGE_DIGEST', 'sha256:' + 'b' * 64)
    monkeypatch.setenv('ORQEVIA_INTERFACE_HOST_ID', 'ABEX')
    from app import objective_api
    def authenticate(token):
        if token != 'fixture-owner':
            raise HTTPException(401, 'Owner authentication required')
    monkeypatch.setattr(objective_api, 'authenticate_owner', authenticate)
    monkeypatch.setattr(objective_api.compute_queue_api, 'queue',
        SimpleNamespace(get=lambda _: pytest.fail('Zero-job Objective must not read the queue')))
    return objective_api


def persist(domain, steps, *, recorded=True, state='submitted', turn=None):
    task_id = str(uuid.uuid4())
    db = domain.connect()
    db.execute('INSERT INTO objectives VALUES(?,?,?,?)',
        (task_id, hashlib.sha256(b'public synthetic fixture').hexdigest(), state, json.dumps(steps)))
    if recorded:
        db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)', (task_id, 0, CREATED, UPDATED))
    domain.store_runtime(db, task_id, 0)
    if turn is not None:
        db.execute('INSERT INTO objective_turns VALUES(?,?,?,?,?,?)',
            (task_id, 1, 'fixture-turn', 'c' * 64, turn['state'], json.dumps(turn['steps'])))
        if recorded:
            db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)',
                (task_id, 1, STARTED, COMPLETED))
        domain.store_runtime(db, task_id, 1)
    db.commit(); db.close()
    return task_id


def saved_rows(domain):
    db = domain.connect(read_only=True)
    try:
        return {name: db.execute('SELECT * FROM ' + name + ' ORDER BY 1,2').fetchall()
            for name in ('objectives', 'objective_turns', 'objective_metadata', 'objective_runtime')}
    finally:
        db.close()


@pytest.mark.parametrize('dispatch', [
    {'state': 'COMPLETED', 'model_backend': 'deterministic', 'artifact': {'artifact_id': 'd' * 32}},
    {'state': 'COMPLETED', 'model_backend': 'none', 'result': 'Public synthetic identity report'},
])
def test_zero_job_completion_labels_persisted_objective_not_queue_without_verification(domain, dispatch):
    task_id = persist(domain, [{'capability': 'responsibility.a19', 'dispatch': dispatch}])
    before = saved_rows(domain)
    value = domain.get_read_only(task_id, 'fixture-owner')
    metadata = value['execution_metadata']
    assert value['state'] == 'COMPLETED'
    assert metadata['provenance']['state'] == 'OBJECTIVE_DISPATCH'
    assert metadata['provenance']['timestamps'] == 'OBJECTIVE_METADATA'
    assert metadata['provenance']['timestamp_fields'] == dict(created_at='OBJECTIVE_METADATA',
        started_at='UNAVAILABLE', completed_at='OBJECTIVE_METADATA', updated_at='OBJECTIVE_METADATA')
    assert (metadata['created_at'], metadata['started_at'], metadata['completed_at'], metadata['updated_at']) == (
        CREATED, None, UPDATED, UPDATED)
    assert metadata['jobs'] == [] and metadata['agent_execution'] == []
    assert metadata['inference_attempts']['status'] == 'NOT_APPLICABLE'
    assert metadata['model_content_is_authoritative_metadata'] is False
    assert metadata['provenance']['artifact'] == 'ARTIFACT_STORE'
    assert metadata['provenance']['verification'] == 'VERIFIER'
    if value['result'] is not None:
        assert value['result']['authoritative'] is False
        assert value['result']['verification_status'] == 'UNVERIFIED'
        assert value['result']['may_update_truth_plane'] is False
    assert saved_rows(domain) == before


@pytest.mark.parametrize('step_state', ['blocked', 'failed', 'indeterminate'])
def test_zero_job_failure_source_and_original_terminal_observation_time(domain, step_state):
    task_id = persist(domain, [{'capability': 'responsibility.a19', 'state': step_state}])
    metadata = domain.get_read_only(task_id, 'fixture-owner')['execution_metadata']
    assert metadata['state'] == 'COMPLETED_WITH_FAILURES'
    assert metadata['provenance']['state'] == 'OBJECTIVE_DISPATCH'
    assert metadata['provenance']['timestamps'] == 'OBJECTIVE_METADATA'
    assert metadata['completed_at'] == UPDATED and metadata['started_at'] is None
    assert metadata['lifecycle']['completed_at_source'] == 'TERMINAL_STATE_OBSERVED_AT_OBJECTIVE_UPDATE'
    assert metadata['lifecycle']['started_at_reason'] == (
        'NO_EXECUTION_STARTED_DISPATCH_BLOCKED' if step_state == 'blocked' else 'NO_EXECUTION_START_RECORDED')


def test_unrecorded_zero_job_time_is_unavailable_not_zero_now_or_model_timestamp(domain):
    task_id = persist(domain, [{'capability': 'responsibility.a19',
        'dispatch': {'state': 'COMPLETED', 'model_backend': 'none',
            'result': 'Model-claimed execution time 2020-01-01T00:00:00Z'}}], recorded=False)
    value = domain.get_read_only(task_id, 'fixture-owner')
    metadata = value['execution_metadata']
    assert metadata['provenance']['state'] == 'OBJECTIVE_DISPATCH'
    assert metadata['provenance']['timestamps'] == 'UNAVAILABLE'
    assert all(metadata[field] is None for field in ('created_at', 'started_at', 'completed_at', 'updated_at'))
    assert value['result']['authoritative'] is False and value['result']['verification_status'] == 'UNVERIFIED'


def queue_fixture(domain, monkeypatch, *, status='completed', mixed=False, recorded=True):
    job = dict(id=str(uuid.uuid4()), agent='a19', model='fixture-model', provider='fixture-provider',
        status=status, result='MODEL status: VERIFIED', error=None, created_at=CREATED,
        started_at=None if status == 'queued' else STARTED,
        completed_at=COMPLETED if status == 'completed' else None)
    calls = []
    def get(key):
        calls.append(key)
        assert key == job['id']
        return deepcopy(job)
    monkeypatch.setattr(domain.compute_queue_api, 'queue', SimpleNamespace(get=get))
    steps = [{'capability': 'responsibility.a19', 'dispatch': {'job': {'id': job['id'], 'agent': 'a19'}}}]
    if mixed:
        steps.append({'capability': 'responsibility.a18',
            'dispatch': {'state': 'COMPLETED', 'model_backend': 'deterministic', 'artifact': {'artifact_id': 'd' * 32}}})
    return persist(domain, steps, recorded=recorded), job, calls


@pytest.mark.parametrize('status,expected_state', [('queued', 'WAITING FOR RESOURCE'),
    ('running', 'RUNNING'), ('completed', 'COMPLETED'), ('failed', 'COMPLETED_WITH_FAILURES')])
def test_existing_queue_state_times_and_model_non_authority_are_preserved(domain, monkeypatch, status, expected_state):
    task_id, job, calls = queue_fixture(domain, monkeypatch, status=status)
    value = domain.get_read_only(task_id, 'fixture-owner')
    metadata = value['execution_metadata']
    assert value['state'] == expected_state
    assert metadata['provenance']['state'] == 'QUEUE'
    assert metadata['provenance']['timestamps'] == ('OBJECTIVE_METADATA' if status == 'queued'
        else 'OBJECTIVE_METADATA_AND_QUEUE')
    assert metadata['provenance']['timestamp_fields']['created_at'] == 'OBJECTIVE_METADATA'
    assert metadata['provenance']['timestamp_fields']['started_at'] == (
        'UNAVAILABLE' if status == 'queued' else 'QUEUE')
    assert metadata['created_at'] == CREATED and metadata['started_at'] == job['started_at']
    assert metadata['completed_at'] == (COMPLETED if status == 'completed' else
        STARTED if status == 'failed' else None)
    assert metadata['updated_at'] == (COMPLETED if status == 'completed' else
        UPDATED if status == 'queued' else STARTED)
    assert metadata['jobs'][0]['job_id'] == job['id'] and calls == [job['id']]
    assert metadata['model_content_is_authoritative_metadata'] is False
    if status == 'completed':
        assert value['result']['type'] == 'MODEL_CONTENT'
        assert value['result']['authoritative'] is False and value['result']['may_update_truth_plane'] is False
        assert value['result']['verification_status'] == 'VERIFY_REQUIRED'


def test_mixed_current_turn_state_has_both_domain_sources(domain, monkeypatch):
    task_id, job, _ = queue_fixture(domain, monkeypatch, mixed=True)
    metadata = domain.get_read_only(task_id, 'fixture-owner')['execution_metadata']
    assert metadata['state'] == 'COMPLETED'
    assert metadata['provenance']['state'] == 'QUEUE_AND_OBJECTIVE_DISPATCH'
    assert metadata['provenance']['timestamps'] == 'OBJECTIVE_METADATA_AND_QUEUE'
    assert metadata['created_at'] == CREATED and metadata['completed_at'] == COMPLETED
    assert len(metadata['jobs']) == 1


def test_current_zero_job_turn_does_not_borrow_old_queue_provenance_or_times(domain, monkeypatch):
    task_id, job, _ = queue_fixture(domain, monkeypatch)
    db = domain.connect()
    db.execute('INSERT INTO objective_turns VALUES(?,?,?,?,?,?)', (task_id, 1, 'fixture-turn',
        'c' * 64, 'submitted', json.dumps([{'capability': 'responsibility.a19',
            'dispatch': {'state': 'COMPLETED', 'model_backend': 'deterministic', 'artifact': {'artifact_id': 'd' * 32}}}])))
    db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)', (task_id, 1, UPDATED, STARTED))
    domain.store_runtime(db, task_id, 1); db.commit(); db.close()
    metadata = domain.get_read_only(task_id, 'fixture-owner')['execution_metadata']
    assert metadata['revision'] == 1 and metadata['jobs'] == []
    assert metadata['provenance']['state'] == 'OBJECTIVE_DISPATCH'
    assert metadata['provenance']['timestamps'] == 'OBJECTIVE_METADATA'
    assert (metadata['created_at'], metadata['completed_at'], metadata['updated_at']) == (UPDATED, STARTED, STARTED)


def test_interrupted_turn_keeps_reconciliation_and_objective_domain(domain):
    task_id = persist(domain, [], turn={'state': 'dispatching', 'steps': []})
    metadata = domain.get_read_only(task_id, 'fixture-owner')['execution_metadata']
    assert metadata['state'] == 'reconciliation_required'
    assert metadata['provenance']['state'] == 'OBJECTIVE_DISPATCH'
    assert metadata['started_at'] is None and metadata['completed_at'] is None
    assert metadata['created_at'] == STARTED and metadata['updated_at'] == COMPLETED


def test_legacy_queue_only_timestamps_keep_queue_provenance(domain, monkeypatch):
    task_id, job, _ = queue_fixture(domain, monkeypatch, recorded=False)
    metadata = domain.get_read_only(task_id, 'fixture-owner')['execution_metadata']
    assert metadata['provenance']['state'] == 'QUEUE'
    assert metadata['provenance']['timestamps'] == 'QUEUE'
    assert metadata['provenance']['timestamp_fields'] == dict(created_at='QUEUE',
        started_at='QUEUE', completed_at='QUEUE', updated_at='QUEUE')
    assert metadata['created_at'] == job['created_at'] and metadata['completed_at'] == job['completed_at']


def test_identical_objective_and_queue_update_records_disclose_both_sources(domain, monkeypatch):
    task_id, job, _ = queue_fixture(domain, monkeypatch)
    db = domain.connect()
    db.execute('UPDATE objective_metadata SET updated_at=? WHERE task=?', (COMPLETED, task_id))
    db.commit(); db.close()
    metadata = domain.get_read_only(task_id, 'fixture-owner')['execution_metadata']
    assert metadata['updated_at'] == COMPLETED
    assert metadata['provenance']['timestamp_fields']['updated_at'] == 'OBJECTIVE_METADATA_AND_QUEUE'
    assert metadata['provenance']['timestamp_fields']['completed_at'] == 'QUEUE'


def test_unauthenticated_read_rejects_before_objective_or_queue_access(domain, monkeypatch):
    monkeypatch.setattr(domain, 'connect', lambda **_: pytest.fail('Unauthorized read must not touch data'))
    with pytest.raises(HTTPException) as error:
        domain.get_read_only(str(uuid.uuid4()), None)
    assert error.value.status_code == 401
