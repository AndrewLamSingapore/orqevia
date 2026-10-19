"""Bounded fixture-only inference provenance; no provider calls or credentials."""
import copy
import hashlib
import json
import sqlite3
import uuid

import pytest

from app import compute_catalog, evidence_lens_api, objective_api
from app.outcome_metrics import OutcomeMetrics


@pytest.fixture
def evidence(monkeypatch, tmp_path):
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ORQEVIA_SPINE_TOKEN', 'fixture-inference-owner')
    monkeypatch.setattr(compute_catalog, 'load_catalog', lambda: [
        {'id': 'hf-primary', 'model': 'organization/model:provider'},
        {'id': 'hf-alternate', 'model': 'organization/alternate:provider'},
    ])
    job = {'id': str(uuid.uuid4()), 'agent': 'a01',
           'provider': 'hf-primary', 'model': 'organization/model:provider',
           'status': 'completed', 'result': 'Untrusted model output', 'error': '',
           'created_at': '2026-10-07T00:20:00+00:00',
           'started_at': '2026-10-07T00:20:01+00:00',
           'completed_at': '2026-10-07T00:20:02+00:00'}
    detail = {'agent_id': 'a01', 'provider': 'hf-alternate',
              'model': 'organization/alternate:provider', 'requested_tier': 'MINI',
              'requested_provider': job['provider'], 'requested_model': job['model'],
              'cached_tokens': 1, 'retries': 0, 'success': True, 'failure_kind': None,
              'fallback_route': [{'provider': 'hf-primary', 'code': 'CAPACITY'}],
              'error_classifications': ['CAPACITY']}
    path = tmp_path / 'compute-ledger.db'
    metrics = OutcomeMetrics(path)
    aid = uuid.uuid4().hex
    metrics.record(attempt_id=aid, task_id=job['id'], task_class='conversation',
                   tier='MINI', seconds=.75, input_tokens=5, output_tokens=3,
                   cost=.0001, **detail)
    return {'job': job, 'detail': detail, 'path': path, 'attempt_id': aid}


def _rewrite(evidence, detail):
    with sqlite3.connect(evidence['path']) as db:
        db.execute('UPDATE reasoning_attempts SET details=? WHERE id=?',
                   (json.dumps(detail), evidence['attempt_id']))


def test_selected_route_is_distinct_bound_and_digestible(evidence):
    result = objective_api.inference_attempt_projection([evidence['job']])
    assert result['status'] == 'OBSERVED'
    assert result['verification'] == 'UNVERIFIED'
    assert result['attempt_timestamp'] == 'NOT_RECORDED'
    attempt = result['attempts'][0]
    assert attempt['queue_job_id'] == evidence['job']['id']
    assert attempt['requested_provider'] == 'hf-primary'
    assert attempt['selected_provider'] == 'hf-alternate'
    assert attempt['selected_model'] == 'organization/alternate:provider'
    assert attempt['fallback_route'] == [{'provider': 'hf-primary', 'code': 'CAPACITY'}]
    assert attempt['total_tokens'] == 8 and attempt['cached_tokens'] == 1
    assert attempt['elapsed_seconds'] == .75 and attempt['cost_usd'] == .0001
    assert attempt['job_completed_at'] == evidence['job']['completed_at']
    digest = attempt.pop('evidence_sha256')
    assert digest == hashlib.sha256(json.dumps(attempt, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    assert 'Untrusted model output' not in json.dumps(result)


def test_absent_store_is_unknown_and_read_does_not_create(monkeypatch, tmp_path):
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path))
    job = {'id': str(uuid.uuid4()), 'agent': 'a01', 'status': 'running'}
    result = objective_api.inference_attempt_projection([job])
    assert result['status'] == 'UNAVAILABLE' and result['attempts'] == []
    assert result['missing_job_ids'] == [job['id']]
    assert not (tmp_path / 'compute-ledger.db').exists()
    assert objective_api.inference_attempt_projection([])['status'] == 'NOT_APPLICABLE'


def test_unrelated_attempt_never_enters_owned_projection(evidence):
    with sqlite3.connect(evidence['path']) as db:
        db.execute('UPDATE reasoning_attempts SET task_id=?', (str(uuid.uuid4()),))
    result = objective_api.inference_attempt_projection([evidence['job']])
    assert result['status'] == 'MISSING' and result['attempts'] == []
    assert result['missing_job_ids'] == [evidence['job']['id']]


@pytest.mark.parametrize('change', [
    {'agent_id': 'a02'},
    {'requested_provider': 'hf-alternate'},
    {'requested_model': 'wrong-model'},
    {'requested_tier': 'FLAGSHIP'},
    {'provider': 'unregistered'},
    {'model': 'Bearer never-export-this'},
    {'prompt': 'never-export-this'},
    {'upstream_body': 'never-export-this'},
    {'secret_ref': 'env:never-export-this'},
    {'error_classifications': ['never-export-this']},
    {'fallback_route': [{'provider': 'hf-primary', 'code': 'CAPACITY',
                         'body': 'never-export-this'}]},
    {'fallback_route': [{'provider': 'hf-primary', 'code': 'CAPACITY'}] * 2},
    {'success': 'true'},
    {'fallback_route': []},
    {'error_classifications': []},
    {'provider': 'hf-primary', 'model': 'organization/model:provider'},
    {'retries': None},
    {'retries': True},
    {'cached_tokens': 9},
    {'failure_kind': 'CAPACITY'},
])
def test_unsafe_or_mismatched_detail_is_rejected_without_export(evidence, change):
    detail = {**evidence['detail'], **change}
    _rewrite(evidence, detail)
    result = objective_api.inference_attempt_projection([evidence['job']])
    assert result['status'] == 'INVALID' and result['attempts'] == []
    assert 'never-export-this' not in json.dumps(result)


@pytest.mark.parametrize('column,value', [
    ('seconds', -1), ('seconds', 86401), ('seconds', float('inf')),
    ('tokens', -1), ('tokens', 1.5), ('cost', -1), ('cost', 101),
    ('id', 'not-an-attempt-id'),
])
def test_invalid_recorded_measurement_is_not_projected(evidence, column, value):
    with sqlite3.connect(evidence['path']) as db:
        db.execute(f'UPDATE reasoning_attempts SET {column}=?', (value,))
    result = objective_api.inference_attempt_projection([evidence['job']])
    assert result['status'] == 'INVALID' and result['attempts'] == []


def test_duplicate_decoded_key_cannot_hide_contradictory_evidence(evidence):
    raw = json.dumps(evidence['detail'])
    raw = raw[:-1] + ',"agent_id":"a02","agent_id":"a01"}'
    with sqlite3.connect(evidence['path']) as db:
        db.execute('UPDATE reasoning_attempts SET details=?', (raw,))
    assert objective_api.inference_attempt_projection([evidence['job']])['status'] == 'INVALID'


def test_duplicate_job_binding_and_attempt_limit_fail_closed(evidence):
    assert objective_api.inference_attempt_projection([evidence['job']] * 2)['status'] == 'INVALID'
    assert objective_api.inference_attempt_projection([evidence['job']] * 7)['status'] == 'INVALID'
    with sqlite3.connect(evidence['path']) as db:
        row = db.execute('SELECT * FROM reasoning_attempts').fetchone()
        for _ in range(64):
            db.execute('INSERT INTO reasoning_attempts VALUES(?,?,?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, *row[1:]))
    assert objective_api.inference_attempt_projection([evidence['job']])['status'] == 'INVALID'


def test_failed_attempt_and_unknown_usage_remain_observed_failure(evidence):
    detail = {**evidence['detail'], 'success': False, 'failure_kind': 'PROVIDER_TIMEOUT',
              'cached_tokens': None, 'error_classifications': ['CAPACITY', 'PROVIDER_TIMEOUT']}
    _rewrite(evidence, detail)
    with sqlite3.connect(evidence['path']) as db:
        db.execute('UPDATE reasoning_attempts SET tokens=NULL,cost=NULL')
    evidence['job']['status'] = 'failed'
    result = objective_api.inference_attempt_projection([evidence['job']])
    assert result['status'] == 'OBSERVED'
    attempt = result['attempts'][0]
    assert attempt['success'] is False and attempt['failure_code'] == 'PROVIDER_TIMEOUT'
    assert attempt['cost_usd'] is None and attempt['total_tokens'] is None
    assert result['verification'] == 'UNVERIFIED'


def test_objective_and_lens_bind_attempts_without_promoting_claims(evidence, monkeypatch):
    task_id = str(uuid.uuid4())
    job = evidence['job']
    steps = [{'capability': 'responsibility.a01', 'dispatch': {'job': {'id': job['id']}}}]
    with objective_api.connect() as db:
        db.execute('INSERT INTO objectives VALUES(?,?,?,?)',
                   (task_id, 'fixture-digest', 'submitted', json.dumps(steps)))
        db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)',
                   (task_id, 0, job['created_at'], job['completed_at']))
    monkeypatch.setattr(objective_api.compute_queue_api.queue, 'get', lambda jid: copy.deepcopy(job))
    authorization = 'Bearer fixture-inference-owner'
    task = objective_api.get(task_id, authorization)
    attempt = task['execution_metadata']['inference_attempts']['attempts'][0]
    assert attempt['queue_job_id'] != task_id
    assert task['execution_metadata']['jobs'][0]['provider'] == 'hf-primary'
    assert attempt['selected_provider'] == 'hf-alternate'
    captured = evidence_lens_api.materialize(task_id, authorization)
    assert captured['observed']['inference_attempts']['attempts'][0] == attempt
    assert captured['verification'] == 'UNVERIFIED'
    assert captured['proof']['time_freshness'] == 'UNKNOWN'
    with sqlite3.connect(evidence['path']) as db:
        db.execute('UPDATE reasoning_attempts SET seconds=1')
    changed = evidence_lens_api.read(task_id, authorization)
    assert changed['integrity'] == 'VALID' and changed['currentness'] == 'STALE'
    assert changed['verification'] == 'UNVERIFIED'
