"""Actual disposable originals, never runtime health, model calls or L7."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app import agent_cert_tool_events as events
from tests.test_agent_cert_tool_events import collect, validate, no_external_operations
from tests.test_agent_cert_authority_chain import runtime
from tests.test_agent_cert_review_dispatch import configured
from tests.test_agent_cert_operator_io import TOKEN

CASE = events.DEGRADATION_CASE


def original(runtime):
    result = collect(runtime, CASE)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    return result, json.loads(result.execution_bytes)


def test_narrow_assessment_binds_actual_available_read_and_distinct_review(runtime):
    result, execution = original(runtime)
    assessment = json.loads(result.subject_artifact_bytes)['assessment']
    observation = json.loads(execution['input_content_utf8'])['known_observation']
    assert assessment['api_failure_basis_points'] == observation['api_failures'] * 10000 // observation['api_checks'] == 500
    assert assessment['assessment_scope'] == 'API_WINDOW_ONLY'
    assert assessment['system_health'] == assessment['dependency_health'] == assessment['cause'] == 'UNKNOWN'
    assert assessment['recovery'] == 'NOT_ESTABLISHED'
    completion = events.parse(execution['available_read_action_records'][-1].encode())
    raw = execution['input_content_utf8'].encode()
    assert completion['result_summary'] == dict(type='dict', source_sha256=events.sha(raw), output_sha256=events.sha(raw), output_length=len(raw.decode()))
    assert assessment['available_observation_sha256'] == events.sha(raw)
    assert result.summary['subject_task_id'] != result.summary['review_task_id']
    assert len(execution['original_action_records']) == 8
    validate(execution, runtime)


def test_no_narrowed_result_without_actual_available_bytes():
    for raw in (None, b'', events.input_bytes(CASE) + b'\n', events.input_bytes(events.SUPPORTED_CASES[0])):
        with pytest.raises(ValueError): events.expected_artifact_bytes(CASE, available_bytes=raw)


@pytest.mark.parametrize('defect', ['success', 'output_hash', 'source_hash', 'length', 'target', 'actor', 'model', 'duration', 'extra', 'missing', 'duplicate'])
def test_available_read_rehashed_counterevidence_rejected(runtime, defect):
    _, execution = original(runtime)
    event = execution['dispatch']['tool_event']
    values = [events.parse(line.encode()) for line in execution['available_read_action_records']]
    if defect == 'success': values[-1]['success'] = False
    elif defect == 'output_hash': values[-1]['result_summary']['output_sha256'] = 'c' * 64
    elif defect == 'source_hash': values[-1]['result_summary']['source_sha256'] = 'c' * 64
    elif defect == 'length': values[-1]['result_summary']['output_length'] += 1
    elif defect in ('target', 'actor', 'model'):
        key, replacement = {'target': ('target', '../private.json'), 'actor': ('agent_id', 'a26'), 'model': ('model_backend', 'cloud')}[defect]
        for value in values: value[key] = replacement
    elif defect == 'duration': values[-1]['duration_ms'] = False
    elif defect == 'extra': values[-1]['result_summary']['cached'] = True
    elif defect == 'missing': values.pop()
    elif defect == 'duplicate': values += deepcopy(values)
    lines = []
    for index, value in enumerate(values):
        if index:
            value['sequence'] = values[index-1]['sequence'] + 1
            value['previous_sha256'] = values[index-1]['sha256']
        value['sha256'] = events.sha(events.canonical({key: item for key,item in value.items() if key != 'sha256'}))
        lines.append(events.canonical(value).decode() + '\n')
    with pytest.raises(ValueError):
        events.available_read_span(lines, task_id=event['task_id'], case=CASE,
            setup_metadata=event['input_artifact_metadata'], input_raw=execution['input_content_utf8'].encode(),
            began=events._utc(event['started_at']), ended=events._utc(event['completed_at']), action_id=event['available_read_action_id'])


@pytest.mark.parametrize('defect', ['available_omitted', 'join', 'event_hash', 'full_omitted', 'arithmetic', 'scope', 'system', 'dependency', 'recovery', 'retries'])
def test_independent_oracle_rejects_missing_originals_or_invented_assessment(runtime, defect):
    _, execution = original(runtime)
    if defect == 'available_omitted': execution['available_read_action_records'] = []
    elif defect == 'join': execution['available_read_action_chain_join']['source_sha256'] = 'c' * 64
    elif defect == 'event_hash': execution['dispatch']['tool_event']['available_input_sha256'] = 'c' * 64
    elif defect == 'full_omitted': execution['original_action_records'].pop(2)
    else:
        content = json.loads(execution['artifact_content_utf8'])
        key, replacement = {'arithmetic': ('api_failure_basis_points', 0), 'scope': ('assessment_scope', 'SYSTEM_WIDE'),
            'system': ('system_health', 'PASS'), 'dependency': ('dependency_health', 'PASS'),
            'recovery': ('recovery', 'PROVEN'), 'retries': ('retries', 1)}[defect]
        content['assessment'][key] = replacement
        execution['artifact_content_utf8'] = events.canonical(content).decode()
    with pytest.raises(ValueError): validate(execution, runtime)


@pytest.mark.parametrize('defect', ['changed_available', 'absent_available', 'unexpected_dependency'])
def test_actual_owning_read_drift_cannot_produce_degraded_result(runtime, monkeypatch, defect):
    from app.deterministic_ops import DeterministicOps
    real = DeterministicOps.retrieve_file
    calls = []
    def changed(self, root, relative, **kwargs):
        calls.append(relative)
        if relative == 'artifact.json':
            if defect == 'changed_available': (Path(root) / relative).write_bytes(b'{"invented":true}')
            elif defect == 'absent_available': (Path(root) / relative).unlink()
            else: (Path(root) / events.MISSING_SLOT).write_bytes(b'{}')
        return real(self, root, relative, **kwargs)
    monkeypatch.setattr(DeterministicOps, 'retrieve_file', changed)
    result = collect(runtime, CASE)
    assert result.summary['state'] != 'UNSIGNED_EVENT_EVIDENCE'
    assert calls == ['artifact.json']
    assert runtime.ledger.flush()
    assert not any(json.loads(line).get('action_type') == events.tool_action_type(CASE)
        for line in runtime.ledger.path.read_text(encoding='utf-8').splitlines())


def test_original_tool_contract_bytes_remain_exact():
    assert [events.sha(events.canonical(events.canonical_tool_case(case))) for case in events.SUPPORTED_CASES[:2]] == [
        '0f34ccd882d68b9347d4504c2236c7e55ac764cd8f232b4db4e8d937aceb8d46',
        'f6e2c123aeb13ee77b032ff9336daf9abe564b37a539b1695cc03e1877f04707']


@pytest.mark.parametrize('domain', ['available_action', 'input_artifact'])
def test_a26_final_independent_reread_rejects_original_drift_before_write(runtime, monkeypatch, domain):
    result, execution = original(runtime)
    request = json.loads(next(body for method,path,body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/dispatch'))
    from app import objective_api
    real, reads = objective_api.get_read_only, []
    def changed(task, authorization):
        value = real(task, authorization)
        reads.append(task)
        if len(reads) == 2:
            if domain == 'input_artifact':
                identifier = execution['dispatch']['tool_event']['input_artifact_metadata']['artifact_id']
                path = runtime.root / 'artifacts' / identifier / 'artifact.json'
                path.write_bytes(path.read_bytes() + b' ')
            else:
                path = runtime.ledger.path
                path.write_bytes(path.read_bytes().replace(events.tool_action_type(CASE, phase='available').encode(), b'forged.available'))
        return value
    monkeypatch.setattr(objective_api, 'get_read_only', changed)
    before = runtime.ledger.status()['persisted'], set((runtime.root / 'artifacts').iterdir())
    reply = runtime.client.post('/api/agents/dispatch', json=request, headers={'Authorization': 'Bearer ' + TOKEN})
    assert reply.status_code == 422 and len(reads) == 2
    assert (runtime.ledger.status()['persisted'], set((runtime.root / 'artifacts').iterdir())) == before
