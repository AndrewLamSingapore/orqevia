"""Source tests on retained originals, never manufactured current certificates."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import shutil
from copy import deepcopy
import pytest

from app import agent_cert_revalidation as revalidation
from app.agent_cert_artifact_events import canonical, parse
from tests.test_agent_cert_tool_events import collect, validate, no_external_operations
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured
from tests.test_agent_cert_operator_io import TOKEN

SOURCE = '60b265c7155d70fb5384cee3b6d3e83e24e6932c'


def test_actual_original_public_signature_and_current_expiry():
    original = revalidation.original_context()
    row = original['signed_record']
    assert original['original_signature_valid'] is True
    actual = datetime.now(timezone.utc).isoformat()
    result = revalidation.temporal_assessment(row, actual, SOURCE)
    assert result['temporal_status'] == 'EXPIRED'
    assert result['source_compatible'] is False
    assert result['fresh_check_required'] is True
    assert result['current_certification'] == 'NOT_AWARDED'
    assert result['original_times_modified'] is False


@pytest.mark.parametrize('defect', ['signature', 'verifier', 'source', 'copied_expiry'])
def test_original_public_signature_rejects_corrupted_memory_copy_no_renewal(defect):
    from app.agent_cert_azure_es256 import verifier_from_azure_es256_pin_file
    original = revalidation.original_context()
    row = deepcopy(original['signed_record'])
    if defect == 'signature':
        row['attestation']['signature'] = '0' * 128
    elif defect == 'verifier':
        row['verifier'] = 'a19'
    elif defect == 'source':
        row['source_revision'] = 'f' * 40
    else:
        row['expires_at'] = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    pin = 'governance/agent-cert-verifier-azure-pins.json'
    verifier = verifier_from_azure_es256_pin_file(revalidation.ROOT/pin,
        revalidation.ORIGINALS[pin], normalize_crlf=True)
    assert verifier(original['signed_record']) is True
    assert verifier(row) is False
    assert original['signed_record']['expires_at'] == '2026-10-07T11:52:32+00:00'


@pytest.mark.parametrize('offset,status', [(-1,'WITHIN_SIGNED_INTERVAL'),(0,'EXPIRED'),(1,'EXPIRED')])
def test_explicit_historical_interval_boundary_not_current_certification(offset, status):
    row = revalidation.original_context()['signed_record']
    historical = datetime.fromisoformat(row['expires_at']) + timedelta(microseconds=offset)
    answer = revalidation.temporal_assessment(row, historical.isoformat(), row['source_revision'])
    assert answer['temporal_status'] == status
    assert answer['current_certification'] == 'NOT_AWARDED'
    assert row['expires_at'] == '2026-10-07T11:52:32+00:00'


def test_actual_producer_time_and_independent_oracle_never_calls_builder(monkeypatch):
    context = canonical(revalidation.original_context())
    began = datetime.now(timezone.utc).isoformat()
    result = revalidation.produce_assessment(context, SOURCE)
    ended = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(revalidation, 'produce_assessment', lambda *a: pytest.fail('producer called by peer'))
    assert revalidation.validate_assessment(result, context, SOURCE, began, ended)


@pytest.mark.parametrize('field,value', [('original_signature_valid',False), ('certification','L7'),
    ('health','HEALTHY'), ('assessment_clock','HISTORICAL_TEST_CLOCK'),
    ('observed_runtime_source_revision','f'*40), ('assessed_at','2026-10-07T10:52:32+00:00')])
def test_peer_rejects_original_result_corruption(field, value):
    context = canonical(revalidation.original_context())
    began = datetime.now(timezone.utc).isoformat()
    raw = revalidation.produce_assessment(context, SOURCE)
    ended = datetime.now(timezone.utc).isoformat()
    answer = parse(raw)
    answer[field] = value
    with pytest.raises(revalidation.RevalidationError):
        revalidation.validate_assessment(canonical(answer), context, SOURCE, began, ended)


@pytest.mark.parametrize('index', range(5))
def test_real_copied_original_custody_corruption_rejected(tmp_path, monkeypatch, index):
    for relative in revalidation.ORIGINALS:
        source = revalidation.ROOT / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    target = tmp_path / list(revalidation.ORIGINALS)[index]
    target.write_bytes(target.read_bytes() + b' ')
    monkeypatch.setattr(revalidation, 'ROOT', tmp_path)
    with pytest.raises(revalidation.RevalidationError, match='ORIGINAL_DIGEST'):
        revalidation.original_context()


def test_original_expiry_assessment_actual_owned_execution_and_distinct_peer(runtime):
    from app import agent_cert_tool_events as events
    result = collect(runtime, events.REVALIDATION_CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    execution = parse(result.execution_bytes)
    answer = parse(result.subject_artifact_bytes)
    assert answer['original_signature_valid'] is True
    assert answer['assessment']['temporal_status'] == 'EXPIRED'
    assert answer['assessment']['fresh_check_required'] is True
    assert answer['assessment']['source_compatible'] is False
    assert answer['assessment_clock'] == 'ACTUAL_REALTIME_UTC'
    assert answer['observed_runtime_source_revision'] == execution['runtime']['source_revision']
    assert answer['certification'] == 'UNVERIFIED' and answer['health'] == 'UNKNOWN'
    assert len(execution['original_action_records']) == 6
    assert 'failed_read_action_records' not in execution
    assert result.summary['subject_task_id'] != result.summary['review_task_id']
    assert result.summary['model_calls'] == 0 and result.summary['signature'] == 'NOT_PERFORMED'
    validate(execution, runtime)


@pytest.mark.parametrize('defect', ['expiry','source','health','renewal'])
def test_independent_custody_oracle_rejects_actual_defective_producer(runtime, monkeypatch, defect):
    from app import agent_cert_tool_events as events
    real = events.expected_artifact_bytes
    def defective(case, **kwargs):
        raw = real(case, **kwargs)
        if case != events.REVALIDATION_CASE:
            return raw
        answer = parse(raw)
        if defect == 'expiry':
            answer['assessment']['temporal_status'] = 'WITHIN_SIGNED_INTERVAL'
        elif defect == 'source':
            answer['assessment']['source_compatible'] = True
        elif defect == 'health':
            answer['health'] = 'HEALTHY'
        else:
            answer['assessment']['renewal_performed'] = True
        return canonical(answer)
    monkeypatch.setattr(events, 'expected_artifact_bytes', defective)
    result = collect(runtime, events.REVALIDATION_CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    assert runtime.ledger.flush()
    rows = [parse(line.encode()) for line in runtime.ledger.path.read_text().splitlines()]
    actual = [row for row in rows if row['action_type'].startswith('agent.certification.tool.continuous_revalidation.')]
    assert len(actual) == 6 and all(row.get('success') is True for row in actual if row['phase'] == 'completed')
    assert not any(method == 'POST' and path == '/api/agents/dispatch' for method,path,body in runtime.transport.calls)


def test_actual_peer_does_not_use_output_builder(runtime, monkeypatch):
    from app import agent_cert_tool_events as events
    result = collect(runtime, events.REVALIDATION_CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    monkeypatch.setattr(events, 'expected_artifact_bytes', lambda *a, **k: pytest.fail('Peer called producer'))
    validate(parse(result.execution_bytes), runtime)


@pytest.mark.parametrize('domain', ['input', 'read_ledger'])
def test_actual_distinct_peer_second_original_read_rejects_drift(runtime, monkeypatch, domain):
    from app import agent_cert_tool_events as events, objective_api
    result = collect(runtime, events.REVALIDATION_CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE'
    execution = parse(result.execution_bytes)
    request = parse(next(body for method,path,body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/dispatch'))
    real, reads = objective_api.get_read_only, []
    def drift(task, authorization):
        value = real(task, authorization)
        reads.append(task)
        if len(reads) == 2:
            if domain == 'input':
                identifier = execution['dispatch']['tool_event']['input_artifact_metadata']['artifact_id']
                path = runtime.root/'artifacts'/identifier/'artifact.json'
                path.write_bytes(path.read_bytes()+b' ')
            else:
                path = runtime.ledger.path
                path.write_bytes(path.read_bytes().replace(events.tool_action_type(events.REVALIDATION_CASE,phase='available').encode(), b'forged.read'))
        return value
    monkeypatch.setattr(objective_api, 'get_read_only', drift)
    before = runtime.ledger.status()['persisted'], set((runtime.root/'artifacts').iterdir())
    response = runtime.client.post('/api/agents/dispatch', json=request,
        headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code == 422 and len(reads) == 2
    assert (runtime.ledger.status()['persisted'], set((runtime.root/'artifacts').iterdir())) == before


@pytest.mark.parametrize('line_ending', [b'\n', b'\r\n'])
def test_all_five_prior_case_bytes_preserved(tmp_path, monkeypatch, line_ending):
    from app import agent_cert_tool_events as events
    from app import agent_registry
    # The proposal binds exact registry bytes. Exercise both Git checkout
    # encodings without changing the live registry or accepting arbitrary pins.
    raw = agent_registry.REGISTRY_PATH.read_bytes().replace(b'\r\n', b'\n')
    registry = tmp_path / 'registry.json'
    registry.write_bytes(raw.replace(b'\n', line_ending))
    monkeypatch.setattr(agent_registry, 'REGISTRY_PATH', registry)
    expected = {
        'tool_recovery:tool_failure':'0f34ccd882d68b9347d4504c2236c7e55ac764cd8f232b4db4e8d937aceb8d46',
        'tool_recovery:bounded_response':'f6e2c123aeb13ee77b032ff9336daf9abe564b37a539b1695cc03e1877f04707',
        'graceful_degradation:complete':'191006e9f939564fb234e18f880a1fc33452f49afb208780e34b2144369cfdfb',
        'tools:complete':'2152b2d3e180a9becb3e21e48117a41c382d4ed5df3325f5a98545d98503befa',
        'independent_verification:complete': (
            '50713d536f4fca236ddaf2dffa6b3be752d4deeec2ef99234a87ed8639d5688b'
            if line_ending == b'\r\n' else
            '0e69b1487df6cd2a002131b40f51f0b4cea173b63e140b1aca96f747b62265f0'),
    }
    assert {case:events.sha(canonical(events.canonical_tool_case(case))) for case in expected} == expected


def test_actual_wrong_producer_classifier_rejected_by_independent_peer(runtime, monkeypatch):
    from app import agent_cert_tool_events as events
    real = revalidation.temporal_assessment
    def wrong(row, observed, source):
        answer = real(row, observed, source)
        answer['temporal_status'] = 'WITHIN_SIGNED_INTERVAL'
        answer['source_compatible'] = True
        answer['fresh_check_required'] = False
        return answer
    monkeypatch.setattr(revalidation, 'temporal_assessment', wrong)
    result = collect(runtime, events.REVALIDATION_CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    assert runtime.ledger.flush()
    rows = [parse(line.encode()) for line in runtime.ledger.path.read_text().splitlines()]
    actual = [row for row in rows if row['action_type'].startswith('agent.certification.tool.continuous_revalidation.')]
    assert len(actual) == 6
    outputs = [parse(path.read_bytes()) for path in (runtime.root/'artifacts').glob('*/artifact.json')]
    assert any(value.get('assessment', {}).get('fresh_check_required') is False for value in outputs)


def test_real_six_row_writer_over_one_second_uses_remaining_original_budget(runtime, monkeypatch):
    from app import agent_cert_tool_events as events, action_records as records
    import threading, time
    real_sync, real_flush = records.os.fsync, runtime.ledger.flush
    syncs, drains = [], []
    def delayed(fd):
        if threading.current_thread() is runtime.ledger.worker:
            if not syncs:
                time.sleep(1.2)
            syncs.append(fd)
        return real_sync(fd)
    def observed_flush(timeout=5):
        drains.append(timeout)
        return real_flush(timeout=timeout)
    monkeypatch.setattr(records.os, 'fsync', delayed)
    monkeypatch.setattr(runtime.ledger, 'flush', observed_flush)
    result = collect(runtime, events.REVALIDATION_CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    event = parse(result.execution_bytes)['dispatch']['tool_event']
    assert 1 < drains[0] <= 5
    assert 1 < (events._utc(event['completed_at'])-events._utc(event['started_at'])).total_seconds() <= 5
    assert len(syncs) == 8  # Six owning original rows, two later peer review rows.
    monkeypatch.setattr(runtime.ledger, 'flush', real_flush)


def test_exhausted_case_budget_never_flushes_or_completes(runtime, monkeypatch):
    from app import agent_cert_tool_events as events, action_records as records
    real_execute, real_flush = records.DirectExecutor.execute, runtime.ledger.flush
    drains = []
    class ExpiredClock:
        @staticmethod
        def now(zone):
            return datetime.now(zone) + timedelta(seconds=6)
    def expire_after_result(executor, record, operation):
        result = real_execute(executor, record, operation)
        if record.action_type == events.tool_action_type(events.REVALIDATION_CASE):
            monkeypatch.setattr(events, 'datetime', ExpiredClock)
        return result
    monkeypatch.setattr(records.DirectExecutor, 'execute', expire_after_result)
    monkeypatch.setattr(runtime.ledger, 'flush', lambda **kwargs: drains.append(kwargs))
    result = collect(runtime, events.REVALIDATION_CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE' and drains == []
    monkeypatch.setattr(runtime.ledger, 'flush', real_flush)
    assert real_flush(timeout=2)


def test_actual_fsync_failed_writer_cannot_return_durable_original(runtime, monkeypatch):
    from app import agent_cert_tool_events as events, action_records as records, agent_dispatch_api
    import threading
    failed = records.ActionLedger(runtime.ledger.path)
    real_sync = records.os.fsync
    def failure(fd):
        if threading.current_thread() is failed.worker:
            raise OSError('disposable source-test fsync failure')
        return real_sync(fd)
    monkeypatch.setattr(records.os, 'fsync', failure)
    monkeypatch.setattr(agent_dispatch_api, 'action_ledger', lambda: failed)
    try:
        result = collect(runtime, events.REVALIDATION_CASE)
        assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
        assert failed.status()['healthy'] is False and failed.status()['dropped'] == 6
    finally:
        assert failed.close() is False
