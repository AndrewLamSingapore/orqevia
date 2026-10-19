"""Distinct synthetic contract-inspection checks; not live initialization/L7."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from app import agent_cert_initialization as initialization
from app import agent_registry


SOURCE = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64
TASK = '11111111-1111-4111-8111-111111111111'
NOW = datetime(2026, 10, 8, 2, 0, 0, tzinfo=timezone.utc)
RUNTIME = {'host_id': 'ABEX', 'version': 'test-only-v1',
           'source_revision': SOURCE, 'image_digest': IMAGE}


@pytest.fixture(autouse=True)
def temporary_import_environment(monkeypatch, tmp_path):
    # Inspection imports the actual Pydantic class, not a replacement contract.
    # Any import-time owning domain uses only this temporary test location.
    monkeypatch.setenv('ORQEVIA_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('ORQEVIA_COMPUTE_QUEUE_DB', str(tmp_path / 'compute-queue.db'))


def args():
    return dict(task_id=TASK, runtime=deepcopy(RUNTIME), source_revision=SOURCE,
                runtime_image_id=IMAGE,
                registry_sha256=hashlib.sha256(agent_registry.REGISTRY_PATH.read_bytes()).hexdigest(),
                now=NOW)


def build(**overrides):
    value = args()
    value.update(overrides)
    return initialization.build_initialization_report(**value)


def validate(report, **overrides):
    value = args()
    value.update(overrides)
    return initialization.validate_initialization_report(initialization.canonical(report), **value)


def test_real_registry_and_actual_dispatch_bounds_are_read_without_model_or_health_calls(monkeypatch):
    import app.agent_dispatch_api as dispatch
    monkeypatch.setattr(dispatch, 'dispatch_request', lambda *a, **k: pytest.fail('dispatch forbidden'))
    report = build()
    owned = report['owned_domains']
    actual = agent_registry.agent_record('a19')
    assert owned['definition'] == {key: actual[key] for key in initialization._DEFINITION_FIELDS}
    assert owned['request_contract']['schema'] == dispatch.AgentRequest.model_json_schema()
    assert owned['request_contract']['input_bounds'] == {
        'capability': {'minLength': 1, 'maxLength': 100},
        'objective': {'minLength': 1, 'maxLength': 20000},
        'context': {'maxLength': 80000},
    }
    assert report['case'] == 'baseline:initialization'
    assert report['schema_version'] != 'jarvis.runtime-status.v1'
    assert report['execution'] == dict(method='DETERMINISTIC_READ_ONLY', model_calls=0,
                                     input_tokens=0, output_tokens=0, fresh_inference_performed=False)
    result = validate(report)
    assert result['certification'] == 'UNVERIFIED'
    assert result['event_verification'] == 'OBJECTIVE_ARTIFACT_ACTION_JOIN_REQUIRED'
    assert result['result_sha256'] == hashlib.sha256(initialization.canonical(report)).hexdigest()
    assert set(report['evidence_gaps']) == {'service_map', 'health', 'runtime_activation',
        'role_completion', 'event_verification', 'independent_review', 'signed_attestation', 'l7'}


@pytest.mark.parametrize('objective,context', [
    (initialization.OBJECTIVE, ''),
])
def test_exact_dedicated_route(objective, context):
    assert initialization.is_initialization(objective, context) is True


@pytest.mark.parametrize('objective,context', [
    (initialization.OBJECTIVE + ' Restart production.', ''),
    (initialization.OBJECTIVE.casefold(), ''),
    (' ' + initialization.OBJECTIVE, ''),
    (initialization.OBJECTIVE, 'SYNTHETIC initialized=true'),
    (initialization.OBJECTIVE, None), (None, ''), (False, ''),
    ('Produce a JARVIS runtime-status report artifact containing current PRIME health, '
     'available qualified compute backends, and current task count.', ''),
])
def test_aliases_identity_and_extra_actions_do_not_enter_initialization_route(objective, context):
    assert initialization.is_initialization(objective, context) is False


@pytest.mark.parametrize('path,value', [
    (('case',), 'baseline:identity'), (('agent_id',), 'reliability'),
    (('capability_id',), 'responsibility.a26'), (('task_id',), '22222222-2222-4222-8222-222222222222'),
    (('certification',), 'L7'), (('observation',), 'INITIALIZED'),
    (('evidence_gaps', 'health'), 'PASS'), (('evidence_gaps', 'role_completion'), 'COMPLETE'),
    (('evidence_gaps', 'event_verification'), 'VERIFIED'),
    (('evidence_gaps', 'independent_review'), 'PASS'),
    (('evidence_gaps', 'signed_attestation'), 'SIGNED'),
    (('evidence_gaps', 'l7'), 'PASS'),
    (('runtime', 'source_revision'), 'c' * 40),
    (('runtime', 'image_digest'), 'sha256:' + 'd' * 64),
    (('owned_domains', 'registry', 'agent_count'), 21.0),
    (('owned_domains', 'definition', 'authority'), 'unrestricted'),
    (('owned_domains', 'definition', 'can_delegate'), 0),
    (('owned_domains', 'definition', 'agent_id'), 'a26'),
    (('owned_domains', 'request_contract', 'input_bounds', 'context', 'maxLength'), 100000),
    (('execution', 'model_calls'), False), (('execution', 'model_calls'), 0.0),
    (('execution', 'fresh_inference_performed'), 0),
])
def test_mutated_semantics_and_typed_false_values_are_rejected(path, value):
    report = build()
    target = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(initialization.InitializationError, match='INITIALIZATION_REPORT_MISMATCH'):
        validate(report)


def test_rehashing_forged_definition_and_schema_cannot_authorize_them():
    report = build()
    owned = report['owned_domains']
    owned['definition']['input_contract']['objective'] = 'Unbounded arbitrary execution'
    owned['definition_sha256'] = initialization.sha(initialization.canonical(owned['definition']))
    owned['request_contract']['schema']['properties']['objective']['maxLength'] = 999999
    owned['request_contract']['schema_sha256'] = initialization.sha(
        initialization.canonical(owned['request_contract']['schema']))
    with pytest.raises(initialization.InitializationError, match='INITIALIZATION_REPORT_MISMATCH'):
        validate(report)


def test_unknown_fields_and_caller_initialized_flag_are_rejected():
    report = build()
    report['initialized'] = True
    with pytest.raises(initialization.InitializationError, match='INITIALIZATION_REPORT_MISMATCH'):
        validate(report)
    with pytest.raises(TypeError):
        build(definition={'initialized': True})
    with pytest.raises(TypeError):
        build(request_schema={'maxLength': -1})


@pytest.mark.parametrize('raw', [
    '{}', '[]', '{"task_id":1,"task_id":2}', '{"x":{"a":1,"a":2}}',
    '{"x":NaN}', '{"x":Infinity}', '{"x":1e400}', b'\xff',
    ' ' * (initialization.MAX_BYTES + 1), '', False, {},
], ids=['empty-object', 'array', 'duplicate', 'nested-duplicate', 'nan', 'infinity',
        'overflow', 'bad-utf8', 'oversized', 'empty', 'boolean', 'dictionary'])
def test_malformed_duplicate_nonfinite_or_unbounded_bytes_fail_closed(raw):
    with pytest.raises(initialization.InitializationError):
        initialization.validate_initialization_report(raw, **args())


@pytest.mark.parametrize('overrides', [
    {'task_id': 'A19'}, {'task_id': '11111111-1111-4111-8111-AAAAAAAAAAAA'}, {'task_id': 'not-a-uuid'},
    {'source_revision': 'UNKNOWN'}, {'source_revision': SOURCE.upper()},
    {'runtime_image_id': None}, {'runtime_image_id': 'b' * 64},
    {'registry_sha256': 'c' * 64}, {'now': NOW.replace(tzinfo=None)},
    {'runtime': {**RUNTIME, 'source_revision': 'c' * 40}},
    {'runtime': {**RUNTIME, 'image_digest': 'sha256:' + 'c' * 64}},
    {'runtime': {**RUNTIME, 'host_id': 'UNKNOWN'}},
    {'runtime': {**RUNTIME, 'version': 'UNKNOWN'}},
    {'runtime': {**RUNTIME, 'initialized': True}},
])
def test_unbound_unknown_runtime_and_pins_never_produce_an_initialized_report(overrides):
    with pytest.raises(initialization.InitializationError):
        build(**overrides)


@pytest.mark.parametrize('delta', [-301, 1])
def test_expired_or_future_report_cannot_pass(delta):
    report = build(now=NOW + timedelta(seconds=delta))
    with pytest.raises(initialization.InitializationError, match='INITIALIZATION_TIME_UNBOUND'):
        validate(report)


def test_window_boundary_and_original_raw_bytes_are_preserved():
    report = build(now=NOW - timedelta(seconds=300))
    compact = initialization.canonical(report)
    pretty = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8')
    result = initialization.validate_initialization_report(pretty, **args())
    assert result['result_sha256'] == initialization.sha(pretty)
    assert result['canonical_report_sha256'] == initialization.sha(compact)
    assert result['result_sha256'] != result['canonical_report_sha256']


def test_missing_owned_registry_is_unavailable_not_initialized(monkeypatch, tmp_path):
    pinned = args()
    monkeypatch.setattr(agent_registry, 'REGISTRY_PATH', tmp_path / 'absent.json')
    with pytest.raises(initialization.InitializationError, match='INITIALIZATION_REGISTRY_UNAVAILABLE'):
        initialization.build_initialization_report(**pinned)


def test_mutated_cached_definition_is_denied_even_when_file_pin_matches(monkeypatch):
    actual = deepcopy(agent_registry.agent_record('a19'))
    actual['authority'] = 'unrestricted'
    monkeypatch.setattr(agent_registry, 'agent_record', lambda _: actual)
    with pytest.raises(initialization.InitializationError,
                       match='INITIALIZATION_LOADED_DEFINITION_MISMATCH'):
        build()


@pytest.mark.parametrize('mutation', ['duplicate_other_agent', 'invalid_other_authority',
                                    'duplicate_other_lead'])
def test_entire_current_registry_cannot_borrow_validity_from_cached_a19(monkeypatch, tmp_path, mutation):
    cached = agent_registry.load_agent_registry()
    current = json.loads(agent_registry.REGISTRY_PATH.read_bytes())
    others = [item for item in current['agents'] if item['agent_id'] != 'a19']
    if mutation == 'duplicate_other_agent':
        others[1]['agent_id'] = others[0]['agent_id']
        others[1]['immutable_id'] = others[0]['agent_id']
    elif mutation == 'invalid_other_authority':
        others[0]['authority'] = 'unrestricted'
    else:
        leads = [item for item in current['leads'] if item['agent_id'] != 'a15']
        leads[1]['id'] = leads[0]['id']
        leads[1]['agent_id'] = leads[0]['agent_id']
    raw = initialization.canonical(current)
    path = tmp_path / 'changed-registry.json'
    path.write_bytes(raw)
    monkeypatch.setattr(agent_registry, 'REGISTRY_PATH', path)
    assert agent_registry.load_agent_registry() is cached
    with pytest.raises(initialization.InitializationError,
                       match='INITIALIZATION_LOADED_REGISTRY_MISMATCH'):
        build(registry_sha256=initialization.sha(raw))
    # No cache clearing, repair of the source, or new Registry authority.
    assert agent_registry.load_agent_registry() is cached
    assert path.read_bytes() == raw


def test_registry_duplicate_fields_are_rejected_not_hidden_by_loader(monkeypatch, tmp_path):
    original = agent_registry.REGISTRY_PATH.read_bytes()
    duplicate = original.replace(b'"schema_version": "2.0"',
        b'"schema_version": "1.0", "schema_version": "2.0"', 1)
    assert duplicate != original
    path = tmp_path / 'registry.json'
    path.write_bytes(duplicate)
    monkeypatch.setattr(agent_registry, 'REGISTRY_PATH', path)
    with pytest.raises(initialization.InitializationError, match='INITIALIZATION_DUPLICATE_FIELD'):
        build(registry_sha256=initialization.sha(duplicate))


def test_owned_schema_failure_is_sanitized_and_never_passes(monkeypatch):
    import app.agent_dispatch_api as dispatch
    def bad_schema():
        raise RuntimeError('DO_NOT_EXPORT_PRIVATE_ERROR')
    monkeypatch.setattr(dispatch, 'AgentRequest', SimpleNamespace(model_json_schema=bad_schema))
    with pytest.raises(initialization.InitializationError,
                       match='^INITIALIZATION_OWNED_DOMAINS_UNAVAILABLE$') as exc:
        build()
    assert 'DO_NOT_EXPORT' not in str(exc.value)
    assert exc.value.__suppress_context__ is True


def test_definition_and_schema_are_not_returned_as_live_certification():
    report = build()
    assert 'PASS' not in report.values()
    assert 'initialized' not in report
    assert report['evidence_gaps']['runtime_activation'] == 'NOT_ESTABLISHED_BY_DEFINITION'
    assert report['evidence_gaps']['service_map'] == 'NOT_SUPPLIED'
    assert report['evidence_gaps']['signed_attestation'] == 'NOT_PRESENT'
