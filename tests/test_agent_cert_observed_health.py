"""Actual temporary owning task observations; no production health or L7."""
from copy import deepcopy
import json
import time

import pytest

from app import agent_cert_tool_events as events
from tests.test_agent_cert_tool_events import collect, validate, no_external_operations
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured, SOURCE, NONCE
from tests.test_agent_cert_operator_io import TOKEN

CASE = events.HEALTH_CASE


def original(runtime):
    result = collect(runtime, CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    return result, json.loads(result.execution_bytes)


def test_assessment_uses_actual_durable_rows_before_result_not_self_report(runtime, monkeypatch):
    real = events.produce_health_assessment
    observations = []
    def inspect(raw, lines, task, revision):
        persisted = events._ledger_lines(runtime.root)
        assert len(lines) == 6 and all(line in persisted for line in lines)
        assert not any(json.loads(line)['action_type'] == events.tool_action_type(CASE)
            and json.loads(line)['phase'] == 'completed'
            for line in persisted)
        observations.append(lines)
        return real(raw, lines, task, revision)
    monkeypatch.setattr(events, 'produce_health_assessment', inspect)
    result, execution = original(runtime)
    answer = json.loads(result.subject_artifact_bytes)
    assert json.loads(execution['input_content_utf8'])['self_report']['claim'] == 'ALL_HEALTHY'
    assert answer['observed_action_records'] == execution['original_action_records'][:6] == observations[0]
    assert len(execution['original_action_records']) == 8
    assert answer['assessment']['successful_operations'] == 2
    assert answer['assessment']['failed_operations'] == 1
    assert answer['observations'][-1]['error'] == 'FileNotFoundError'
    assert answer['assessment']['self_report_used'] is False
    assert answer['assessment']['global_agent_health'] == answer['assessment']['current_production_health'] == 'UNKNOWN'


@pytest.mark.parametrize('defect', ['successes', 'failures', 'global', 'production', 'self_report', 'included', 'error', 'duration', 'actor', 'task', 'raw_substitute'])
def test_actual_wrong_producer_output_reaches_distinct_peer_and_is_rejected(runtime, monkeypatch, defect):
    real = events.produce_health_assessment
    def faulty(*args):
        value = json.loads(real(*args))
        if defect in ('successes', 'failures'):
            value['assessment']['successful_operations' if defect == 'successes' else 'failed_operations'] += 1
        elif defect in ('global', 'production'):
            value['assessment']['global_agent_health' if defect == 'global' else 'current_production_health'] = 'HEALTHY'
        elif defect == 'self_report': value['assessment']['self_report_used'] = True
        elif defect == 'included': value['assessment']['result_operation_included'] = True
        elif defect == 'error': value['observations'][-1]['error'] = None
        elif defect == 'duration': value['observations'][0]['duration_ms'] = -1
        elif defect == 'task': value['task_id'] = '00000000-0000-4000-8000-000000000001'
        else:
            rows = [json.loads(line) for line in value['observed_action_records']]
            if defect == 'actor': rows[0]['agent_id'] = 'a26'
            else: rows[1]['duration_ms'] += 1
            for index, row in enumerate(rows):
                if index: row['previous_sha256'] = rows[index-1]['sha256']
                row['sha256'] = events.sha(events.canonical({key:item for key,item in row.items() if key != 'sha256'}))
            value['observed_action_records'] = [events.canonical(row).decode()+'\n' for row in rows]
        return events.canonical(value)
    monkeypatch.setattr(events, 'produce_health_assessment', faulty)
    # Exercise the final original-store guard even though the independent early
    # observer would already reject this faulty producer. Test-only one-call seam.
    peer_oracle, checks = events.validate_health_assessment, []
    def skip_only_early_observer(*args):
        checks.append(True)
        return True if len(checks) == 1 else peer_oracle(*args)
    with monkeypatch.context() as early:
        early.setattr(events, 'validate_health_assessment', skip_only_early_observer)
        result = collect(runtime, CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    execution = json.loads(result.execution_bytes)
    assert len(execution['original_action_records']) == 8
    from app.agent_cert_role_review import tool_review_objective, TOOL_REVIEW_OPERATION
    request = dict(classification='R0', capability='responsibility.a26', objective=tool_review_objective(CASE),
        context=events.canonical(dict(execution=execution,expected_execution_sha256=events.sha(result.execution_bytes),
            expected_source_revision=SOURCE, review_nonce=NONCE)).decode(), data_classification='LOCAL_ONLY',
        minimum_tier='NANO', priority='low', task_class='classification', max_cost_usd=0,
        response_format='strict_json', deterministic_operation=TOOL_REVIEW_OPERATION)
    before = runtime.ledger.status()['persisted'], set((runtime.root/'artifacts').iterdir())
    assert runtime.client.post('/api/agents/dispatch', json=request,
        headers={'Authorization':'Bearer '+TOKEN}).status_code == 422
    assert (runtime.ledger.status()['persisted'], set((runtime.root/'artifacts').iterdir())) == before


def test_peer_classifier_never_uses_producer(runtime, monkeypatch):
    _, execution = original(runtime)
    monkeypatch.setattr(events, 'produce_health_assessment', lambda *args: pytest.fail('Shared producer classifier'))
    monkeypatch.setattr(events, 'expected_artifact_bytes', lambda *args, **kwargs: pytest.fail('Shared builder'))
    validate(execution, runtime)


@pytest.mark.parametrize('defect', ['duration_boolean', 'duration_negative', 'duration_bound', 'missing_pair', 'action_id', 'actor'])
def test_independent_raw_original_classifier_rejects_rehashed_invalid_rows(runtime, defect):
    result, execution = original(runtime)
    rows = [json.loads(line) for line in execution['original_action_records'][:6]]
    if defect.startswith('duration'):
        rows[1]['duration_ms'] = {'duration_boolean':True,'duration_negative':-1,'duration_bound':5001}[defect]
    elif defect == 'missing_pair': rows.pop(2)
    elif defect == 'action_id': rows[2]['action_id'] = rows[0]['action_id']; rows[3]['action_id'] = rows[0]['action_id']
    else: rows[0]['agent_id'] = rows[1]['agent_id'] = 'a26'
    for index, row in enumerate(rows):
        if index:
            row['sequence'] = rows[index-1]['sequence']+1
            row['previous_sha256'] = rows[index-1]['sha256']
        row['sha256'] = events.sha(events.canonical({key:value for key,value in row.items() if key != 'sha256'}))
    lines = [events.canonical(row).decode()+'\n' for row in rows]
    answer = json.loads(result.subject_artifact_bytes); answer['observed_action_records'] = lines
    with pytest.raises(ValueError):
        events.validate_health_assessment(events.canonical(answer),execution['input_content_utf8'].encode(),
            lines,execution['dispatch']['task_id'],SOURCE)


def test_changed_untrusted_self_report_cannot_override_actual_failed_operation(runtime, monkeypatch):
    real = events.input_bytes
    def changed(case):
        raw = real(case)
        if case != CASE: return raw
        value = json.loads(raw); value['self_report']['claim'] = 'ALL_UNHEALTHY'
        return events.canonical(value)
    monkeypatch.setattr(events, 'input_bytes', changed)
    result, execution = original(runtime)
    assessment = json.loads(result.subject_artifact_bytes)['assessment']
    assert assessment['successful_operations'] == 2 and assessment['failed_operations'] == 1
    assert assessment['self_report_used'] is False
    validate(execution, runtime)


@pytest.mark.parametrize('domain', ['input', 'read_ledger'])
def test_second_original_a26_reread_rejects_custody_drift(runtime, monkeypatch, domain):
    _, execution = original(runtime)
    request = json.loads(next(body for method,path,body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/dispatch'))
    from app import objective_api
    real, reads = objective_api.get_read_only, []
    def changed(task, authorization):
        value = real(task, authorization); reads.append(task)
        if len(reads) == 2:
            if domain == 'input':
                path = runtime.root/'artifacts'/execution['dispatch']['tool_event']['input_artifact_metadata']['artifact_id']/'artifact.json'
                path.write_bytes(path.read_bytes()+b' ')
            else:
                path = runtime.ledger.path
                path.write_bytes(path.read_bytes().replace(events.tool_action_type(CASE,phase='available').encode(), b'forged.read'))
        return value
    monkeypatch.setattr(objective_api, 'get_read_only', changed)
    before = runtime.ledger.status()['persisted'], set((runtime.root/'artifacts').iterdir())
    assert runtime.client.post('/api/agents/dispatch',json=request,
        headers={'Authorization':'Bearer '+TOKEN}).status_code == 422
    assert len(reads) == 2
    assert (runtime.ledger.status()['persisted'], set((runtime.root/'artifacts').iterdir())) == before


def test_two_actual_durability_barriers_share_original_five_second_budget(runtime, monkeypatch):
    from app.action_records import ActionLedger
    real, budgets = ActionLedger.flush, []
    def delayed(self, timeout=1):
        budgets.append(timeout)
        if len(budgets) <= 2:
            time.sleep(1.05)
            return real(self, timeout=max(.01, timeout-1.05))
        return real(self, timeout=timeout)
    with monkeypatch.context() as patch:
        patch.setattr(ActionLedger, 'flush', delayed)
        original(runtime)
    assert 1 < budgets[1] < budgets[0] <= 5


def test_real_fsync_durability_precedes_assessment_with_remaining_bound(runtime, monkeypatch):
    from app import action_records as records
    import threading
    real_sync, real_flush = records.os.fsync, runtime.ledger.flush
    syncs, budgets = [], []
    def delayed(fd):
        if threading.current_thread() is runtime.ledger.worker:
            if len(syncs) in (0, 6): time.sleep(.65)
            syncs.append(fd)
        return real_sync(fd)
    def measured(timeout=5):
        budgets.append(timeout)
        return real_flush(timeout=timeout)
    monkeypatch.setattr(records.os, 'fsync', delayed)
    monkeypatch.setattr(runtime.ledger, 'flush', measured)
    result, _ = original(runtime)
    assert 1 < budgets[1] < budgets[0] <= 5
    event = json.loads(result.execution_bytes)['dispatch']['tool_event']
    assert 1 < (events._utc(event['completed_at'])-events._utc(event['started_at'])).total_seconds() <= 5
    assert len(syncs) == 10  # Eight subject rows, then two actual review rows.


def test_actual_failed_fsync_cannot_be_observed_healthy(runtime, monkeypatch):
    from app import action_records as records, agent_dispatch_api
    import threading
    failed = records.ActionLedger(runtime.ledger.path)
    real_sync = records.os.fsync
    def broken(fd):
        if threading.current_thread() is failed.worker: raise OSError('disposable source-test failure')
        return real_sync(fd)
    monkeypatch.setattr(records.os, 'fsync', broken)
    monkeypatch.setattr(agent_dispatch_api, 'action_ledger', lambda:failed)
    try:
        result = collect(runtime, CASE)
        assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
        assert failed.status()['healthy'] is False and failed.status()['dropped'] == 6
    finally:
        assert failed.close() is False


@pytest.mark.parametrize('failure', ['raw_flush', 'result_flush', 'exhausted'])
def test_failed_barriers_or_exhausted_budget_cannot_yield_event_evidence(runtime, monkeypatch, failure):
    from app.action_records import ActionLedger
    from types import SimpleNamespace
    real, calls, clock = ActionLedger.flush, [], [0.0]
    def flush(self, timeout=1):
        calls.append(timeout)
        if failure == 'raw_flush' and len(calls) == 1: return False
        if failure == 'result_flush' and len(calls) == 2: return False
        result = real(self, timeout)
        if failure == 'exhausted': clock[0] = 6
        return result
    with monkeypatch.context() as patch:
        patch.setattr(ActionLedger, 'flush', flush)
        if failure == 'exhausted': patch.setattr(events, 'time', SimpleNamespace(monotonic=lambda:clock[0]))
        result = collect(runtime, CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    assert len(calls) == (2 if failure == 'result_flush' else 1)
