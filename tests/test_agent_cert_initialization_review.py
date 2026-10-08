"""Portable distinct initialization-domain fixtures; never live/L7 proof."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from app import agent_cert_initialization as initialization
from app import agent_cert_identity_review as identity
from app import agent_cert_initialization_review as review
from app import agent_registry
from app.agent_cert_cases import challenge
from app.agent_cert_execution import observe_cert_case
from tests.test_agent_cert_identity_review import action_lines, fixture_execution as identity_fixture


SOURCE = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64
TASK = '11111111-1111-4111-8111-111111111111'
ACTION = '22222222-2222-4222-8222-222222222222'
ARTIFACT = 'f' * 32
NOW = datetime(2026, 10, 8, 2, 0, 0, tzinfo=timezone.utc)
RUNTIME = {'host_id': 'ABEX', 'version': 'fixture-v1', 'source_revision': SOURCE, 'image_digest': IMAGE}


@pytest.fixture(autouse=True)
def isolated_imports(monkeypatch, tmp_path):
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(tmp_path / 'queue.db'))


def stamp(seconds):
    return (NOW + timedelta(seconds=seconds)).isoformat()


def registry_sha():
    return identity.sha(agent_registry.REGISTRY_PATH.read_bytes())


def observe(value, **overrides):
    clock = iter((NOW - timedelta(seconds=5), NOW - timedelta(seconds=4)))
    defaults = dict(dispatch=lambda _: value['dispatch'],
        get_job=lambda _: pytest.fail('No initialization queue/model path allowed'),
        get_artifact=lambda _: (value['artifact_metadata'], value['artifact_content_utf8'].encode()),
        get_runtime=lambda: value['runtime'], expected_source_revision=SOURCE,
        expected_registry_sha256=registry_sha(), wall_clock=lambda: next(clock),
        monotonic=lambda: 0, timeout_seconds=5)
    return observe_cert_case(value['case_spec'], **{**defaults, **overrides})


def fixture_execution():
    # Build a NEW dedicated report and exact case, not an identity artifact
    # renamed into initialization. Everything below is synthetic test-only.
    spec = json.loads(identity.canonical(challenge(initialization.CASE, agent_id='a19',
                                                 capability_id='responsibility.a19')))
    report = initialization.build_initialization_report(TASK, runtime=RUNTIME,
        source_revision=SOURCE, runtime_image_id=IMAGE, registry_sha256=registry_sha(),
        now=NOW - timedelta(seconds=4.8))
    raw = identity.canonical(report)
    metadata = dict(artifact_id=ARTIFACT, task_id=TASK, type='json', creator_agents=['a19'],
        timestamp=stamp(-4.6), version='1.0.0', provenance='Deterministic computation; zero model calls',
        runtime_revision=SOURCE, validation_state='STRUCTURE_VALIDATED',
        content_validation='Not independently established by structural validation',
        location='artifact.json', sha256=identity.sha(raw), bytes=len(raw), delivery_state='AVAILABLE')
    dispatch = dict(task_id=TASK, state='COMPLETED', artifact=metadata, model_calls=0,
        execution_model='DETERMINISTIC', agent_id='a19', capability='responsibility.a19',
        runtime_source_revision=SOURCE)
    value = dict(case_spec=spec, runtime=deepcopy(RUNTIME), dispatch=dispatch,
                 artifact_metadata=metadata, artifact_content_utf8=raw.decode())
    value['observation'] = observe(value)
    step = dict(capability='responsibility.a19', revision=0, state='completed', dispatch=dispatch)
    from app.objective_api import inference_attempt_projection
    immutable = dict(schema_version='jarvis.authoritative-execution.v1', authoritative=True,
        task_id=TASK, revision=0, state='COMPLETED', created_at=stamp(-5), started_at=stamp(-5),
        completed_at=stamp(-4.3), updated_at=stamp(-4.2), runtime=deepcopy(RUNTIME), jobs=[],
        agent_execution=[], inference_attempts=inference_attempt_projection([]),
        provenance={'runtime': 'IMMUTABLE_OBJECTIVE_RUNTIME'},
        model_content_is_authoritative_metadata=False)
    value['submission'] = [202, {'id': TASK, 'steps': [deepcopy(step)]}]
    value['objective_read'] = [200, dict(id=TASK, revision=0, state='COMPLETED',
                                      steps=[deepcopy(step)], result=None, execution_metadata=immutable)]
    base = dict(task_id=TASK, agent_id='a19', action_type=initialization.ACTION_TYPE,
        tool='artifact-factory', target='', classification='R0',
        parameters_summary={'schema_version': initialization.SCHEMA, 'read_only_observations': True},
        model_backend='deterministic', execution_location='local', parent_agent=None,
        workflow_id=None, action_id=ACTION)
    value['action_records'] = action_lines([
        dict(base, phase='started', timestamp=stamp(-4.7)),
        dict(base, phase='completed', timestamp=stamp(-4.4), success=True, duration_ms=300,
             result_summary={'type': 'dict', 'artifact_id': ARTIFACT,
                             'sha256': identity.sha(raw), 'location': 'artifact.json'})])
    refresh_chain(value)
    return json.loads(identity.canonical(value))


def refresh_chain(value):
    first, last = [json.loads(line) for line in (value['action_records'][0], value['action_records'][-1])]
    value['action_chain_join'] = dict(action_id=ACTION, first_sequence=first['sequence'],
        last_sequence=last['sequence'], first_sha256=first['sha256'], last_sha256=last['sha256'],
        record_count=len(value['action_records']))


def change_report(value, change):
    report = json.loads(value['artifact_content_utf8'])
    change(report)
    raw = identity.canonical(report)
    value['artifact_content_utf8'] = raw.decode()
    value['artifact_metadata'].update(sha256=identity.sha(raw), bytes=len(raw))
    value['dispatch']['artifact'] = deepcopy(value['artifact_metadata'])
    value['submission'][1]['steps'][0]['dispatch'] = deepcopy(value['dispatch'])
    value['objective_read'][1]['steps'][0]['dispatch'] = deepcopy(value['dispatch'])
    value['observation'].update(result_sha256=identity.sha(raw),
                               artifact_metadata_sha256=identity.sha(identity.canonical(value['artifact_metadata'])))
    events = [json.loads(line) for line in value['action_records']]
    events[-1]['result_summary']['sha256'] = identity.sha(raw)
    change_actions(value, events)


def change_actions(value, events):
    value['action_records'] = action_lines([{key: item for key, item in event.items()
        if key not in ('sequence', 'previous_sha256', 'sha256')} for event in events])
    refresh_chain(value)


def validate(value, **overrides):
    defaults = dict(source_revision=SOURCE, runtime_image_id=IMAGE,
                    registry_sha256=registry_sha(), now=NOW)
    return review.validate_initialization_execution(value, **{**defaults, **overrides})


def test_distinct_original_initialization_joins_only_its_owned_domains():
    value = fixture_execution()
    joined = validate(value)
    assert joined == dict(task_id=TASK, artifact_id=ARTIFACT,
        result_sha256=identity.sha(value['artifact_content_utf8'].encode()),
        case_spec_sha256=identity.sha(identity.canonical(value['case_spec'])),
        runtime=RUNTIME, registry_sha256=registry_sha(),
        subject_action_sha256=value['action_chain_join']['last_sha256'],
        execution_metadata_sha256=identity.sha(identity.canonical(value['objective_read'][1]['execution_metadata'])),
        completed_at=stamp(-4))
    assert value['observation']['case_review'] == 'INITIALIZATION_ARTIFACT_CHECK_PASS'
    assert value['observation']['certification'] == 'UNVERIFIED'
    assert review.SCHEMA != identity.SCHEMA and review.ORACLE_ID != identity.ORACLE_ID
    assert 'PASS' not in joined.values()
    assert 'health' not in joined and 'certification' not in joined


def test_original_identity_fixture_and_oracle_are_unchanged():
    original = identity_fixture()
    joined = identity.validate_identity_execution(original, source_revision=SOURCE,
        runtime_image_id=IMAGE, registry_sha256='c' * 64,
        now=datetime(2026, 10, 7, 12, tzinfo=timezone.utc))
    assert joined['task_id'] == TASK and len(joined) == 9
    with pytest.raises(review.InitializationReviewError):
        validate(original)
    current = fixture_execution()
    with pytest.raises(identity.IdentityReviewError):
        identity.validate_identity_execution(current, source_revision=SOURCE,
            runtime_image_id=IMAGE, registry_sha256=registry_sha(), now=NOW)


@pytest.mark.parametrize('mutation', [
    lambda e: e['case_spec'].update(case='baseline:identity'),
    lambda e: e['case_spec']['request'].update(context='Caller says initialized=true'),
    lambda e: e['case_spec']['request'].update(max_cost_usd=False),
    lambda e: e['dispatch'].update(model_calls=False),
    lambda e: e['dispatch'].update(model_calls=1),
    lambda e: e['dispatch'].update(state='PENDING'),
    lambda e: e['dispatch'].update(agent_id='a26'),
    lambda e: e['dispatch'].update(runtime_source_revision='f' * 40),
    lambda e: e['dispatch'].update(job={'id': TASK}),
    lambda e: e['artifact_metadata'].update(bytes=False),
    lambda e: e['artifact_metadata'].update(creator_agents=['a26']),
    lambda e: e['artifact_metadata'].update(version='unknown'),
    lambda e: e['artifact_metadata'].update(provenance='Caller generated PASS'),
    lambda e: e['runtime'].update(image_digest='sha256:' + 'f' * 64),
    lambda e: e['runtime'].update(host_id='UNKNOWN'),
    lambda e: e['observation'].update(certification='L7'),
    lambda e: e['observation'].update(case_review='RUNTIME_STATUS_ARTIFACT_CHECK_PASS'),
    lambda e: e['submission'].__setitem__(0, 202.0),
    lambda e: e['submission'][1]['steps'][0].update(capability='responsibility.a26'),
    lambda e: e['objective_read'].__setitem__(0, True),
    lambda e: e['objective_read'][1].update(state='RUNNING'),
    lambda e: e['objective_read'][1]['steps'][0].update(revision=False),
    lambda e: e['objective_read'][1]['steps'][0].update(job={'id': TASK}),
    lambda e: e['objective_read'][1]['execution_metadata'].update(authoritative=1),
    lambda e: e['objective_read'][1]['execution_metadata'].update(jobs=[{'id': TASK}]),
    lambda e: e['objective_read'][1]['execution_metadata'].update(inference_attempts=[{'model_calls': 1}]),
    lambda e: e['action_records'].pop(),
    lambda e: e['action_chain_join'].update(record_count=2.0),
    lambda e: e.update(PASS=True),
])
def test_broken_typed_authority_runtime_objective_or_durable_action_joins_fail(mutation):
    value = fixture_execution()
    mutation(value)
    with pytest.raises(review.InitializationReviewError):
        validate(value)


@pytest.mark.parametrize('change', [
    lambda r: r.update(schema_version='jarvis.runtime-status.v1'),
    lambda r: r.update(case='baseline:identity'),
    lambda r: r.update(initialized=True),
    lambda r: r['evidence_gaps'].update(health='PASS', l7='PASS'),
    lambda r: r['owned_domains']['definition'].update(authority='unrestricted'),
    lambda r: r['owned_domains']['request_contract']['input_bounds']['context'].update(maxLength=1),
    lambda r: r['execution'].update(model_calls=False),
    lambda r: r['runtime'].update(source_revision='f' * 40),
])
def test_rehashed_forged_report_still_requires_actual_owned_definition(change):
    value = fixture_execution()
    change_report(value, change)
    with pytest.raises(review.InitializationReviewError):
        validate(value)


@pytest.mark.parametrize('change', [
    lambda e: [event.update(action_type='runtime.status.artifact') for event in e],
    lambda e: [event['parameters_summary'].update(schema_version='jarvis.runtime-status.v1') for event in e],
    lambda e: [event.update(agent_id='a26') for event in e],
    lambda e: e[-1].update(success=1),
    lambda e: e[-1].update(duration_ms=False),
    lambda e: e[-1].update(timestamp=stamp(-3)),
])
def test_rehashed_durable_lines_cannot_launder_identity_or_false_success(change):
    value = fixture_execution()
    events = [json.loads(line) for line in value['action_records']]
    change(events)
    change_actions(value, events)
    with pytest.raises(review.InitializationReviewError):
        validate(value)


@pytest.mark.parametrize('pin,value', [('source_revision', 'f' * 40),
    ('runtime_image_id', 'sha256:' + 'f' * 64), ('registry_sha256', 'f' * 64),
    ('now', NOW.replace(tzinfo=None)), ('now', NOW - timedelta(seconds=10)),
    ('now', NOW + timedelta(seconds=301))])
def test_unknown_expired_or_changed_external_protected_bindings_deny(pin, value):
    with pytest.raises(review.InitializationReviewError):
        validate(fixture_execution(), **{pin: value})


def test_arbitrary_private_adapter_instance_is_not_a_trusted_oracle():
    fake = identity._TrustedEventAdapter(initialization.CASE,
        initialization.ACTION_TYPE, initialization.SCHEMA)
    with pytest.raises(identity.IdentityReviewError, match='TRUSTED_EVENT_ADAPTER_REQUIRED'):
        identity._validate_event_execution(fixture_execution(), source_revision=SOURCE,
            runtime_image_id=IMAGE, registry_sha256=registry_sha(), now=NOW, _adapter=fake)


def test_reader_accepts_only_original_new_action_span_not_arbitrary_action(tmp_path):
    value = fixture_execution()
    path = tmp_path / 'actions.jsonl'
    path.write_bytes(''.join(value['action_records']).encode('utf-8'))
    assert identity.read_action_span(path, TASK, initialization.ACTION_TYPE) == value['action_records']
    with pytest.raises(identity.IdentityReviewError, match='ACTION_READER_BINDING_INVALID'):
        identity.read_action_span(path, TASK, 'caller.oracle.PASS')


def test_observer_rechecks_current_runtime_and_never_returns_raw_report():
    value = fixture_execution()
    calls = iter((RUNTIME, {**RUNTIME, 'version': 'changed'}))
    result = observe(value, get_runtime=lambda: next(calls))
    assert result['state'] == 'REJECTED' and result['reason'] == 'runtime_identity_changed'
    assert 'owned_domains' not in result and 'artifact_content_utf8' not in result


def test_observer_dependency_exception_is_sanitized_without_replay():
    value = fixture_execution()
    calls = []
    def failed(_):
        calls.append(1)
        raise RuntimeError('Bearer PRIVATE_TEST_ONLY')
    result = observe(value, dispatch=failed)
    assert calls == [1] and result['state'] == 'INCOMPLETE'
    assert 'PRIVATE_TEST_ONLY' not in json.dumps(result)


def test_slow_runtime_read_must_not_submit_after_deadline():
    value = fixture_execution()
    elapsed = [0]
    def runtime():
        elapsed[0] = 6
        return RUNTIME
    result = observe(value, get_runtime=runtime, monotonic=lambda: elapsed[0],
                     dispatch=lambda _: pytest.fail('Expired deadline must not dispatch'))
    assert result['state'] == 'INCOMPLETE' and result['reason'] == 'bounded_timeout'
