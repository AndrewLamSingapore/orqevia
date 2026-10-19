"""Independent portable identity-event review fixtures; never live proof.

The envelope is a bounded synthetic original-domain example. It does not
dispatch, infer, enroll, sign, or claim a production/Owner/health result.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import traceback

import pytest

from app.agent_cert_cases import challenge
from app import agent_cert_identity_review as review


SOURCE = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64
REGISTRY = 'c' * 64
TASK = '11111111-1111-4111-8111-111111111111'
ACTION = '22222222-2222-4222-8222-222222222222'
ARTIFACT = 'f' * 32
NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def stamp(seconds):
    return (NOW + timedelta(seconds=seconds)).isoformat()


def action_lines(events):
    previous = '0' * 64
    lines = []
    for sequence, event in enumerate(events, 1):
        value = {**event, 'sequence': sequence, 'previous_sha256': previous}
        value['sha256'] = sha(canonical(value))
        previous = value['sha256']
        lines.append(canonical(value).decode() + '\n')
    return lines


def fixture_execution():
    runtime = {'host_id': 'ABEX', 'version': 'fixture-v1',
               'source_revision': SOURCE, 'image_digest': IMAGE}
    report = {'schema_version': 'jarvis.runtime-status.v1', 'task_id': TASK,
        'captured_at': stamp(-4.8), 'prime_health': {'status': 'UNKNOWN', 'observation': 'UNAVAILABLE'},
        'registry': {'status': 'OBSERVED', 'agent_count': 21,
                     'registry_version': 'fixture', 'source_sha256': REGISTRY},
        'tasks': {'count': 1, 'active_count': 0},
        'qualified_compute': {'status': 'UNAVAILABLE'},
        'protocol': {'interface_contract': 'orqevia.interface.v1',
                     'report_schema': 'jarvis.runtime-status.v1',
                     'broader_governance_protocol_version': 'UNKNOWN'},
        'execution': {'model_calls': 0, 'input_tokens': 0, 'output_tokens': 0,
                      'method': 'DETERMINISTIC_READ_ONLY', 'fresh_inference_performed': False}}
    artifact = canonical(report)
    metadata = {'artifact_id': ARTIFACT, 'task_id': TASK, 'type': 'json',
        'creator_agents': ['a19'], 'timestamp': stamp(-4.6), 'version': '1.0.0',
        'provenance': 'Deterministic computation; zero model calls', 'runtime_revision': SOURCE,
        'validation_state': 'STRUCTURE_VALIDATED',
        'content_validation': 'Not independently established by structural validation',
        'location': 'artifact.json', 'sha256': sha(artifact), 'bytes': len(artifact),
        'delivery_state': 'AVAILABLE'}
    dispatch = {'task_id': TASK, 'state': 'COMPLETED', 'artifact': metadata,
        'model_calls': 0, 'execution_model': 'DETERMINISTIC', 'agent_id': 'a19',
        'capability': 'responsibility.a19', 'runtime_source_revision': SOURCE}
    observation = {'agent_id': 'a19', 'capability_id': 'responsibility.a19',
        'case': 'baseline:identity', 'certification': 'UNVERIFIED', 'state': 'EXECUTED',
        'execution_model': 'DETERMINISTIC', 'task_id': TASK, 'artifact_id': ARTIFACT,
        'model_calls': 0, 'source_revision': SOURCE, 'registry_sha256': REGISTRY,
        'runtime_identity_sha256': sha(canonical(runtime)), 'result_sha256': sha(artifact),
        'artifact_metadata_sha256': sha(canonical(metadata)), 'started_at': stamp(-5),
        'completed_at': stamp(-4), 'captured_at': stamp(-4.8),
        'case_review': 'RUNTIME_STATUS_ARTIFACT_CHECK_PASS', 'review_errors': []}
    step = {'capability': 'responsibility.a19', 'revision': 0, 'state': 'completed',
            'dispatch': dispatch}
    objective = {'id': TASK, 'revision': 0, 'state': 'COMPLETED', 'steps': [step], 'result': None,
        'execution_metadata': {'schema_version': 'jarvis.authoritative-execution.v1',
            'authoritative': True, 'task_id': TASK, 'revision': 0, 'state': 'COMPLETED',
            'created_at': stamp(-5), 'started_at': stamp(-5), 'completed_at': stamp(-4.3),
            'updated_at': stamp(-4.2), 'runtime': runtime, 'jobs': [], 'agent_execution': [],
            'inference_attempts': [], 'provenance': {'runtime': 'IMMUTABLE_OBJECTIVE_RUNTIME'},
            'model_content_is_authoritative_metadata': False}}
    action = {'task_id': TASK, 'agent_id': 'a19', 'action_type': 'runtime.status.artifact',
        'tool': 'artifact-factory', 'target': '', 'classification': 'R0',
        'parameters_summary': {'schema_version': 'jarvis.runtime-status.v1', 'read_only_observations': True},
        'model_backend': 'deterministic', 'execution_location': 'local',
        'parent_agent': None, 'workflow_id': None, 'action_id': ACTION}
    lines = action_lines([{**action, 'phase': 'started', 'timestamp': stamp(-4.7)},
        {**action, 'phase': 'completed', 'timestamp': stamp(-4.4), 'success': True,
         'duration_ms': 300, 'result_summary': {'type': 'dict', 'artifact_id': ARTIFACT,
                                              'sha256': sha(artifact), 'location': 'artifact.json'}}])
    first, last = [json.loads(line) for line in lines]
    return {'case_spec': json.loads(canonical(challenge('baseline:identity', agent_id='a19',
                                                       capability_id='responsibility.a19'))),
        'runtime': runtime, 'submission': [202, {'id': TASK, 'steps': [deepcopy(step)]}],
        'dispatch': dispatch, 'artifact_metadata': metadata,
        'artifact_content_utf8': artifact.decode('utf-8'), 'observation': observation,
        'objective_read': [200, objective], 'action_records': lines,
        'action_chain_join': {'action_id': ACTION, 'first_sequence': 1, 'last_sequence': 2,
            'first_sha256': first['sha256'], 'last_sha256': last['sha256'], 'record_count': 2}}


def validate(value, **kwargs):
    return review.validate_identity_execution(value, source_revision=SOURCE,
        runtime_image_id=IMAGE, registry_sha256=REGISTRY, now=NOW, **kwargs)


def refresh_artifact(value, change):
    """Keep all claimed hashes consistent, so a semantic guard discriminates."""
    report = json.loads(value['artifact_content_utf8'])
    change(report)
    raw = canonical(report)
    value['artifact_content_utf8'] = raw.decode()
    value['artifact_metadata'].update(sha256=sha(raw), bytes=len(raw))
    value['dispatch']['artifact'] = deepcopy(value['artifact_metadata'])
    value['submission'][1]['steps'][0]['dispatch'] = deepcopy(value['dispatch'])
    value['objective_read'][1]['steps'][0]['dispatch'] = deepcopy(value['dispatch'])
    value['observation'].update(result_sha256=sha(raw),
        artifact_metadata_sha256=sha(canonical(value['artifact_metadata'])))
    events = [json.loads(line) for line in value['action_records']]
    events[-1]['result_summary']['sha256'] = sha(raw)
    refresh_actions(value, events)


def refresh_actions(value, events):
    lines = action_lines([{k: v for k, v in e.items()
                          if k not in ('sequence', 'previous_sha256', 'sha256')} for e in events])
    first, last = [json.loads(line) for line in (lines[0], lines[-1])]
    value['action_records'] = lines
    value['action_chain_join'].update(first_sequence=first['sequence'], last_sequence=last['sequence'],
        first_sha256=first['sha256'], last_sha256=last['sha256'], record_count=len(lines))


def test_genuine_joined_synthetic_identity_is_only_quality_review_and_sanitized():
    value = fixture_execution()
    result = validate(value)
    assert type(result) is dict
    assert set(result) == {'task_id', 'artifact_id', 'result_sha256', 'case_spec_sha256',
                          'runtime', 'registry_sha256', 'subject_action_sha256',
                          'execution_metadata_sha256', 'completed_at'}
    assert result['task_id'] == TASK and result['artifact_id'] == ARTIFACT
    assert result['result_sha256'] == sha(value['artifact_content_utf8'].encode())
    assert result['case_spec_sha256'] == sha(canonical(value['case_spec']))
    assert result['runtime'] == value['runtime'] and result['registry_sha256'] == REGISTRY
    assert result['subject_action_sha256'] == value['action_chain_join']['last_sha256']
    assert result['execution_metadata_sha256'] == sha(canonical(value['objective_read'][1]['execution_metadata']))
    assert result['completed_at'] == value['observation']['completed_at']
    assert 'artifact_content_utf8' not in result and 'action_records' not in result
    rendered = canonical(result).decode()
    assert 'fresh_inference_performed' not in rendered
    assert 'L7_CERTIFIED' not in rendered and 'CERTIFICATION_PASS' not in rendered
    assert canonical(value) == canonical(fixture_execution())


@pytest.mark.parametrize('change', [
    lambda v: v['case_spec']['request'].update(objective='NOT THE CANONICAL CASE'),
    lambda v: v['case_spec']['request'].update(context='hidden context'),
    lambda v: v['case_spec']['request'].update(data_classification='CLOUD_PERMITTED'),
    lambda v: v['case_spec'].update(certification='L7'),
    lambda v: v['runtime'].update(source_revision='d' * 40),
    lambda v: v['runtime'].update(image_digest='sha256:' + 'd' * 64),
    lambda v: v['runtime'].update(host_id='UNKNOWN'),
    lambda v: v['dispatch'].update(agent_id='a26'),
    lambda v: v['dispatch'].update(task_id='-' * 36),
    lambda v: v['dispatch'].update(model_calls=False),
    lambda v: v['artifact_metadata'].update(creator_agents=['a26']),
    lambda v: v['artifact_metadata'].update(runtime_revision='d' * 40),
    lambda v: v['artifact_metadata'].update(bytes=True),
    lambda v: v['artifact_metadata'].update(location='../artifact.json'),
    lambda v: v['observation'].update(state='PASS'),
    lambda v: v['observation'].update(model_calls=False),
    lambda v: v['observation'].update(review_errors=['wrong_actor']),
    lambda v: v['observation'].update(case_review='GENERIC_PASS'),
    lambda v: v['observation'].update(registry_sha256='d' * 64),
    lambda v: v['submission'].__setitem__(0, True),
    lambda v: v['submission'].__setitem__(0, 200),
    lambda v: v['submission'][1]['steps'][0].update(capability='responsibility.a26'),
    lambda v: v['objective_read'].__setitem__(0, 202),
    lambda v: v['objective_read'][1].update(revision=False),
    lambda v: v['objective_read'][1]['execution_metadata'].update(authoritative=1),
    lambda v: v['objective_read'][1]['execution_metadata'].update(jobs=[{'job_id': 'invented'}]),
    lambda v: v['objective_read'][1]['execution_metadata'].update(provenance={'runtime': 'CALLER_ASSERTED'}),
    lambda v: v.update(action_records=[]),
    lambda v: v.update(action_chain_join={}),
    lambda v: v.update(private_extra='Bearer NEVER_EXPOSE_THIS'),
], ids=[f'joined-mutation-{i}' for i in range(30)])
def test_joined_domain_mutations_never_become_quality_pass(change):
    value = fixture_execution()
    change(value)
    with pytest.raises(review.IdentityReviewError):
        validate(value)


@pytest.mark.parametrize('change', [
    lambda r: r['registry'].update(agent_count=True),
    lambda r: r['registry'].update(agent_count=20),
    lambda r: r['registry'].update(source_sha256='d' * 64),
    lambda r: r['execution'].update(model_calls=False),
    lambda r: r['execution'].update(input_tokens=1),
    lambda r: r['execution'].update(output_tokens=False),
    lambda r: r['execution'].update(fresh_inference_performed=0),
    lambda r: r.update(task_id='99999999-9999-4999-8999-999999999999'),
    lambda r: r.update(captured_at=stamp(1)),
], ids=[f'rehashed-report-{i}' for i in range(9)])
def test_semantically_wrong_report_rejects_even_with_all_digests_rewritten(change):
    value = fixture_execution()
    refresh_artifact(value, change)
    with pytest.raises(review.IdentityReviewError):
        validate(value)


@pytest.mark.parametrize('change', [
    lambda e: e[0].update(agent_id='a26'),
    lambda e: e[0].update(classification='R1'),
    lambda e: e[0].update(action_type='agent.certification.role.review'),
    lambda e: e[0].update(parameters_summary={'schema_version': 'jarvis.runtime-status.v1',
                                             'read_only_observations': 1}),
    lambda e: e[-1].update(success=1),
    lambda e: e[-1].update(duration_ms=True),
    lambda e: e[-1].update(duration_ms=6000),
    lambda e: e[-1].update(timestamp=stamp(1)),
    lambda e: e[-1].update(action_id='33333333-3333-4333-8333-333333333333'),
], ids=[f'rehashed-action-{i}' for i in range(9)])
def test_rechained_action_semantics_are_not_authoritative_by_hash_alone(change):
    value = fixture_execution()
    events = [json.loads(line) for line in value['action_records']]
    change(events)
    refresh_actions(value, events)
    with pytest.raises(review.IdentityReviewError):
        validate(value)


@pytest.mark.parametrize('field,value', [
    ('started_at', '2026-10-07T11:59:55'),
    ('completed_at', stamp(2)),
    ('captured_at', stamp(-6)),
], ids=('naive', 'future', 'inverted'))
def test_aware_ordered_observation_times_are_required(field, value):
    execution = fixture_execution()
    execution['observation'][field] = value
    with pytest.raises(review.IdentityReviewError):
        validate(execution)


@pytest.mark.parametrize('key,value', [
    ('source_revision', True), ('source_revision', 'not a revision'),
    ('runtime_image_id', 'sha256:' + 'z' * 64), ('registry_sha256', False),
    ('now', datetime(2026, 10, 7, 12)), ('now', '2026-10-07T12:00:00Z'),
], ids=('bool-source', 'bad-source', 'bad-image', 'bool-registry', 'naive-now', 'string-now'))
def test_required_protected_pins_and_now_are_not_inferred(key, value):
    pins = dict(source_revision=SOURCE, runtime_image_id=IMAGE, registry_sha256=REGISTRY, now=NOW)
    pins[key] = value
    with pytest.raises(review.IdentityReviewError):
        review.validate_identity_execution(fixture_execution(), **pins)


def test_historical_event_time_is_preserved_not_relabelled_fresh_or_given_invented_ttl():
    value = fixture_execution()
    result = review.validate_identity_execution(value, source_revision=SOURCE,
        runtime_image_id=IMAGE, registry_sha256=REGISTRY, now=NOW + timedelta(days=365))
    assert result['completed_at'] == stamp(-4)
    assert not any(key in result for key in ('fresh', 'current', 'certified_at', 'expires_at', 'l7_awarded'))


@pytest.mark.parametrize('raw', [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}',
    b'{"x":1e999}', b'[]', b'\xff', b'', b' ' * (1024 * 1024 + 1)],
    ids=('duplicate', 'nan', 'infinity', 'overflow', 'array', 'utf8', 'empty', 'oversized'))
def test_strict_parser_rejects_ambiguous_nonfinite_or_unbounded_json(raw):
    with pytest.raises(review.IdentityReviewError):
        review.parse(raw)


def test_strict_parser_and_canonical_sha_preserve_valid_original_bytes():
    value = fixture_execution()
    encoded = canonical(value)
    assert review.parse(encoded) == value
    assert review.canonical(value) == encoded and review.sha(encoded) == sha(encoded)


def test_nested_duplicate_report_and_action_lines_are_rejected():
    value = fixture_execution()
    value['artifact_content_utf8'] = '{"schema_version":"jarvis.runtime-status.v1","schema_version":"evil"}'
    with pytest.raises(review.IdentityReviewError):
        validate(value)
    value = fixture_execution()
    value['action_records'][0] = value['action_records'][0].rstrip()[:-1] + ',"sequence":true}\n'
    with pytest.raises(review.IdentityReviewError):
        validate(value)


def test_rejection_traceback_does_not_reveal_private_artifact_text():
    value = fixture_execution()
    value['artifact_content_utf8'] = 'Bearer NEVER_EXPOSE_THIS'
    try:
        validate(value)
    except review.IdentityReviewError as exc:
        rendered = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        assert 'Bearer NEVER_EXPOSE_THIS' not in str(exc)
        assert 'Bearer NEVER_EXPOSE_THIS' not in rendered
    else:
        pytest.fail('private invalid artifact accepted')


def test_read_action_span_keeps_original_interleaved_lines(tmp_path):
    events = [json.loads(line) for line in fixture_execution()['action_records']]
    unrelated = deepcopy(events[0])
    unrelated.update(task_id='99999999-9999-4999-8999-999999999999', action_id='33333333-3333-4333-8333-333333333333')
    lines = action_lines([events[0], unrelated, events[-1]])
    path = tmp_path / 'actions.jsonl'
    path.write_bytes(''.join(lines).encode())
    actual = review.read_action_span(path, TASK, 'runtime.status.artifact')
    assert actual == lines and ''.join(actual).encode() == path.read_bytes()


@pytest.mark.parametrize('kind', ('missing', 'directory', 'partial', 'oversized', 'no-owned-pair', 'duplicate-owned-pair'))
def test_read_action_span_fails_closed_for_non_original_or_missing_pair(tmp_path, kind):
    path = tmp_path / 'actions.jsonl'
    lines = fixture_execution()['action_records']
    if kind == 'directory':
        path.mkdir()
    elif kind == 'partial':
        path.write_bytes(''.join(lines).encode()[:-1])
    elif kind == 'oversized':
        path.write_bytes(b'x' * 129)
    elif kind == 'no-owned-pair':
        path.write_bytes(b'{"task_id":"foreign","phase":"started"}\n')
    elif kind == 'duplicate-owned-pair':
        path.write_bytes(''.join(lines + lines).encode())
    with pytest.raises(review.IdentityReviewError):
        review.read_action_span(path, TASK, 'runtime.status.artifact', max_bytes=128 if kind == 'oversized' else 8 * 1024 * 1024)


def test_read_action_span_rejects_symlink_without_reading_target(tmp_path):
    target = tmp_path / 'real.jsonl'
    target.write_bytes(''.join(fixture_execution()['action_records']).encode())
    link = tmp_path / 'linked.jsonl'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('Unprivileged Windows symlink creation unavailable; off-host executes this guard')
    with pytest.raises(review.IdentityReviewError):
        review.read_action_span(link, TASK, 'runtime.status.artifact')


def test_read_action_span_does_not_truncate_more_than_128_interleaved_events(tmp_path):
    pair = [json.loads(line) for line in fixture_execution()['action_records']]
    middle = [{**pair[0], 'task_id': '99999999-9999-4999-8999-999999999999',
               'action_id': f'{i:08x}-3333-4333-8333-333333333333'} for i in range(127)]
    path = tmp_path / 'actions.jsonl'
    path.write_bytes(''.join(action_lines([pair[0], *middle, pair[1]])).encode())
    with pytest.raises(review.IdentityReviewError):
        review.read_action_span(path, TASK, 'runtime.status.artifact')


@pytest.mark.parametrize('key,value', [('sequence', True), ('sequence', 1.0),
    ('previous_sha256', 'x' * 64), ('sha256', '0' * 64)],
    ids=('bool-sequence', 'float-sequence', 'bad-predecessor', 'wrong-hash'))
def test_original_ledger_sequence_and_link_are_typed_and_bound(key, value):
    execution = fixture_execution()
    first = json.loads(execution['action_records'][0])
    first[key] = value
    execution['action_records'][0] = canonical(first).decode() + '\n'
    with pytest.raises(review.IdentityReviewError):
        validate(execution)


@pytest.mark.parametrize('task,action_type,cap', [
    ('-' * 36, 'runtime.status.artifact', 1024),
    (TASK, 'arbitrary.command', 1024),
    (TASK, 'runtime.status.artifact', True),
    (TASK, 'runtime.status.artifact', 0),
    (TASK, 'runtime.status.artifact', 8 * 1024 * 1024 + 1),
], ids=('bad-task', 'bad-operation', 'bool-cap', 'zero-cap', 'oversized-cap'))
def test_action_reader_invalid_bindings_fail_before_open(tmp_path, monkeypatch, task, action_type, cap):
    def forbidden(*args, **kwargs):
        raise AssertionError('FILE OPEN IS FORBIDDEN FOR INVALID READER BINDINGS')
    monkeypatch.setattr(Path, 'open', forbidden)
    with pytest.raises(review.IdentityReviewError):
        review.read_action_span(tmp_path / 'actions.jsonl', task, action_type, max_bytes=cap)


def test_action_reader_relative_or_link_path_fails_before_open(tmp_path, monkeypatch):
    opened = []
    def forbidden(*args, **kwargs):
        opened.append(True)
        raise AssertionError('FILE OPEN IS FORBIDDEN FOR INVALID READER PATH')
    monkeypatch.setattr(Path, 'open', forbidden)
    with pytest.raises(review.IdentityReviewError):
        review.read_action_span(Path('relative.jsonl'), TASK, 'runtime.status.artifact')
    monkeypatch.setattr(Path, 'is_symlink', lambda value: value == tmp_path / 'linked.jsonl')
    with pytest.raises(review.IdentityReviewError):
        review.read_action_span(tmp_path / 'linked.jsonl', TASK, 'runtime.status.artifact')
    assert opened == []
