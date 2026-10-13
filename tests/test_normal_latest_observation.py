"""Source fixtures exercise custody and unchanged review; no live model claims."""
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

import pytest

from app.agent_coaching import digest, effective_prompt
from app.agent_cert_role_group_two import _CASES
from app.agent_registry import registered_agent_ids
from app.normal_latest_observation import MANIFEST_NAME, SCHEMA, normal_latest_snapshot, oracle_fingerprints


def fixture(root):
    jobs = []
    with sqlite3.connect(root/'compute-queue.db') as db:
        db.execute('CREATE TABLE compute_jobs(id TEXT PRIMARY KEY, agent TEXT, prompt TEXT, status TEXT, model TEXT,'
            'preferred_provider TEXT, provider TEXT, max_retries INTEGER, max_cost_usd REAL, allow_cloud INTEGER,'
            'external_execution INTEGER, data_classification TEXT, response_format TEXT, result TEXT,'
            'completed_at TEXT, actual_cost_usd REAL)')
        for agent in sorted(registered_agent_ids(include_orchestrator=False)):
            request, prompt = effective_prompt(agent, 'baseline', 1001)
            response = json.dumps(_CASES['a19'][2]) if agent == 'a19' else '{}'
            key = str(uuid.uuid4())
            completed = '2020-01-01T00:00:00+00:00'
            db.execute('INSERT INTO compute_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (key, agent, prompt, 'completed', 'fixture/model:pinned', 'fixture-provider', 'fixture-provider',
                 0, .005, 1, 0, 'CLOUD_PERMITTED', 'strict_json', response, completed, .00001))
            jobs.append({'agent': agent, 'job_id': key, 'model': 'fixture/model:pinned', 'provider': 'fixture-provider',
                'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(), 'request_sha256': digest(request),
                'output_sha256': hashlib.sha256(response.encode()).hexdigest(), 'completed_at': completed})
    manifest = {'schema_version': SCHEMA, 'wave': 'isolated-fixture', 'jobs': jobs,
        'recorded_at': '2020-01-01T00:00:01+00:00', 'assessment_runtime_revision': 'a'*40,
        'oracle_sha256': oracle_fingerprints(), 'prompt': 'PRIVATE_PROMPT', 'original_output': 'PRIVATE_RESULT'}
    (root/MANIFEST_NAME).write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


def save(root, manifest):
    (root/MANIFEST_NAME).write_text(json.dumps(manifest), encoding='utf-8')


def test_absent_receipt_is_unavailable_and_creates_no_database(tmp_path):
    report = normal_latest_snapshot(tmp_path)
    assert report['status'] == 'UNAVAILABLE' and report['normal_pass_count'] is None
    assert not list(tmp_path.iterdir())


def test_read_only_replay_keeps_all_criteria_and_source_times_without_exporting_answers(tmp_path):
    fixture(tmp_path)
    original = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    report = normal_latest_snapshot(tmp_path)
    assert report['status'] == 'OBSERVED' and report['normal_pass_count'] == 1 and report['normal_fail_count'] == 20
    assert report['normal_denominator'] == report['reassessed_count'] == 21
    assert report['full_role_accepted_count'] == 0 and report['model_calls'] == 0
    assert report['last_execution_at'] == '2020-01-01T00:00:00+00:00'
    assert report['assessment_runtime_revision'] == 'a'*40
    assert report['known_selected_cost_usd'] == '0.00021'
    assert all('prompt' not in agent and 'result' not in agent for agent in report['agents'])
    assert 'PRIVATE_PROMPT' not in json.dumps(report) and 'PRIVATE_RESULT' not in json.dumps(report)
    assert original == {path.name: path.read_bytes() for path in tmp_path.iterdir()}


@pytest.mark.parametrize('column,value', [('result', '{}'), ('provider', 'different-provider'),
    ('prompt', 'changed input'), ('completed_at', '2020-02-01T00:00:00+00:00'), ('max_retries', 1)])
def test_mutated_job_cannot_retain_pass_counts(tmp_path, column, value):
    manifest = fixture(tmp_path)
    agent = next(item for item in manifest['jobs'] if item['agent'] == 'a19')
    with sqlite3.connect(tmp_path/'compute-queue.db') as db:
        db.execute(f'UPDATE compute_jobs SET {column}=? WHERE id=?', (value, agent['job_id']))
    report = normal_latest_snapshot(tmp_path)
    assert report['status'] == 'UNVERIFIED' and report['normal_pass_count'] is None


def test_repinning_a_wrong_answer_still_fails_the_unchanged_oracle(tmp_path):
    manifest = fixture(tmp_path)
    agent = next(item for item in manifest['jobs'] if item['agent'] == 'a19')
    wrong = json.dumps({**_CASES['a19'][2], 'latest_check_time': '10:00Z'})
    with sqlite3.connect(tmp_path/'compute-queue.db') as db:
        db.execute('UPDATE compute_jobs SET result=? WHERE id=?', (wrong, agent['job_id']))
    agent['output_sha256'] = hashlib.sha256(wrong.encode()).hexdigest()
    save(tmp_path, manifest)
    report = normal_latest_snapshot(tmp_path)
    assert report['normal_pass_count'] == 0 and report['normal_fail_count'] == 21
    assert next(item for item in report['agents'] if item['agent_id'] == 'a19')['errors'] == ['latest_check_time']


def test_oracle_changes_and_incomplete_identity_set_are_unverified(tmp_path):
    manifest = fixture(tmp_path)
    manifest['oracle_sha256']['agent_cert_numeric.py'] = 'f'*64
    save(tmp_path, manifest)
    assert normal_latest_snapshot(tmp_path)['status'] == 'UNVERIFIED'
    manifest['oracle_sha256'] = oracle_fingerprints()
    manifest['jobs'][0]['agent'] = manifest['jobs'][1]['agent']
    save(tmp_path, manifest)
    assert normal_latest_snapshot(tmp_path)['status'] == 'UNAVAILABLE'


def test_telemetry_surfaces_latest_results_separately_from_historical_coaching(tmp_path, monkeypatch):
    from app.interface_telemetry import snapshot
    fixture(tmp_path)
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    report = snapshot('fixture-client', 'OWNER')
    assert report['normal_latest']['normal_pass_count'] == 1
    assert report['coaching']['status'] == 'UNAVAILABLE'
    assert report['ready_agent_count'] is None and report['normal_latest']['full_role_accepted_count'] == 0


def test_declared_current_observer_and_original_assessment_revisions_stay_separate(tmp_path, monkeypatch):
    fixture(tmp_path)
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', 'b'*40)
    monkeypatch.setenv('PRIME_INTERFACE_RUNTIME_REVISION', 'c'*40)
    report = normal_latest_snapshot(tmp_path)
    assert report['assessment_runtime_revision'] == 'a'*40
    assert report['observer_runtime_revision'] == 'b'*40
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', 'PRIVATE_INVALID_REVISION')
    assert normal_latest_snapshot(tmp_path)['observer_runtime_revision'] == 'UNKNOWN'
