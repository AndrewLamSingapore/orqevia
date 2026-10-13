"""Bounded identity-probe driver fixtures; no model execution or certification."""
import copy
import io
import json
from pathlib import Path

import pytest

from app.job_queue import JobQueue
from app.product_identity import IDENTITY_CONTRACT, PRODUCT_NAME
from scripts import identity_probe_21_runtime as probe


def test_plan_is_21_public_source_prompts_with_no_corrected_response_or_private_context():
    jobs = probe.build_requests()
    assert len(jobs) == len({job['agent'] for job in jobs}) == 21
    assert all(job['prompt'].startswith(IDENTITY_CONTRACT) for job in jobs)
    assert all(job['request']['context'] == '' and job['request']['objective'] == probe.OBJECTIVE for job in jobs)
    assert PRODUCT_NAME not in probe.OBJECTIVE
    assert all('expected_answer' not in job for job in jobs)
    assert sum(job['provider'] == 'hf-qwen-normal-deepinfra' for job in jobs) == 19


def test_idempotency_keys_bind_source_and_actor_with_no_automatic_retry():
    first, second = probe.build_requests()[:2]
    body = probe.queue_body(first, 'a'*40)
    assert body == probe.queue_body(first, 'a'*40)
    assert body['idempotency_key'] != probe.queue_body(second, 'a'*40)['idempotency_key']
    assert body['idempotency_key'] != probe.queue_body(first, 'b'*40)['idempotency_key']
    assert body['max_retries'] == 0 and body['max_cost_usd'] == .005


def completed(planned, result):
    return {**probe.queue_body(planned, 'a'*40), 'provider': planned['provider'], 'status': 'completed',
        'attempts': 1, 'result': result, 'actual_cost_usd': .00001, 'started_at': 'start', 'completed_at': 'finish'}


def test_assessor_preserves_failed_identity_bytes_instead_of_rewriting_name():
    planned = probe.build_requests()[0]
    original = completed(planned, 'My name is JARVIS.')
    before = copy.deepcopy(original)
    report = probe.assess(planned, original)
    assert report['passed'] is False and 'jarvis_identity_missing' in report['errors']
    assert 'product_identity_overridden' in report['errors']
    assert original == before
    assert probe.assess(planned, completed(planned, f'My name is {PRODUCT_NAME}.'))['passed'] is True


def test_wrong_provider_or_multiple_attempts_cannot_pass_identity_validation():
    planned = probe.build_requests()[0]
    for update in ({'provider': 'different-provider'}, {'attempts': 2}, {'prompt': 'rewritten'}):
        report = probe.assess(planned, {**completed(planned, f'My name is {PRODUCT_NAME}.'), **update})
        assert report['passed'] is False and report['execution_bound'] is False


def test_retained_evidence_is_immutable(tmp_path):
    path = tmp_path/'receipt.json'
    probe.write_new_or_same(path, {'raw_bytes': 'retained'})
    before = path.read_bytes()
    probe.write_new_or_same(path, {'raw_bytes': 'retained'})
    with pytest.raises(ValueError):
        probe.write_new_or_same(path, {'raw_bytes': 'different'})
    assert path.read_bytes() == before


def test_restart_collects_pending_jobs_without_resubmitting_and_queue_must_start_idle(tmp_path, monkeypatch):
    from app import compute_catalog
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', 'a'*40)
    monkeypatch.setenv('PRIME_SPINE_TOKEN', 'fixture-owner')
    queue = JobQueue(tmp_path/'compute-queue.db')
    plans = probe.build_requests()
    entries = [{'id': provider, 'model': model, 'enabled': True,
        'allowed_prompt_bindings': [{'agent': item['agent'], 'prompt_sha256': item['prompt_sha256']}
                                   for item in plans if item['provider'] == provider]}
        for provider, model in probe.MODELS.items()]
    monkeypatch.setattr(compute_catalog, 'load_catalog', lambda: entries)
    calls = []

    def submit(request, timeout):
        body = json.loads(request.data)
        calls.append(body)
        return io.StringIO(json.dumps(queue.submit(**body)))

    monkeypatch.setattr(probe.urllib.request, 'urlopen', submit)
    result = probe.run('tick', 'a'*40)
    assert result['jobs_submitted'] == 2 and result['completed_count'] == 0 and len(calls) == 2
    assert result['unknown_cost_count'] == 2
    restarted = probe.run('tick', 'a'*40)
    assert restarted['jobs_submitted'] == 2 and len(calls) == 2
    assert probe.run('collect', 'a'*40)['completed_count'] == 0 and len(calls) == 2
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', 'b'*40)
    with pytest.raises(ValueError, match='queue must be idle'):
        probe.run('tick', 'b'*40)


def test_wrong_installed_revision_fails_before_submission(monkeypatch):
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', 'b'*40)
    with pytest.raises(ValueError, match='exact installed runtime revision'):
        probe.run('tick', 'a'*40)
