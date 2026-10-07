"""Synthetic hand-built numeric artifact; no training, network or production data."""
from copy import deepcopy
import hashlib
import json

import pytest

from app.mlp_execution import GovernedMLPExecution, MLPExecutionError
from app.mlp_fabric import MLPCapabilityFabric, validate_artifact

TRACE = '687845ae-6032-4355-a5e2-f124c8b22e07'
AUTH = 'Bearer synthetic-mlp-execution-unit-test'


def synthetic_artifact():
    metrics = {'mae': 0, 'mse': 0, 'rmse': 0, 'r2': 1}
    body = {'schema_version': '1.0', 'model_type': 'MLP', 'version': '1.0.0', 'task': 'regression',
        'input_schema': {'features': ['x'], 'types': ['float']},
        'output_schema': {'type': 'float', 'dimensions': 1},
        'architecture': {'hidden_layers': [1], 'activation': 'relu', 'output_dimensions': 1},
        'training_configuration': {'seed': 1, 'epochs': 1, 'learning_rate': .03, 'split': [.6, .2, .2]},
        'dataset_reference': 'synthetic-unit-fixture-not-trained-or-production-approved', 'dataset_hash': 'b' * 64,
        'preprocessing': {'mean': [0], 'scale': [1], 'encoding': 'numeric_only', 'missing': 'reject'},
        'weights': [{'weights': [[1]], 'biases': [0]}, {'weights': [[2]], 'biases': [.5]}],
        'framework': 'prime-stdlib-mlp-v1',
        'evaluation_result': {'validation': deepcopy(metrics), 'test': deepcopy(metrics),
                              'baseline_test': {'type': 'linear', **metrics}}}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    model_id = 'mlp-' + digest[:20]
    return {**body, 'model_id': model_id, 'model_artifact_hash': digest,
        'created_at': '2026-10-07T04:00:00+00:00', 'approval_state': 'APPROVED', 'health': 'HEALTHY',
        'provenance': {'origin': 'local_training', 'split_seed': 1, 'training_rows': 12,
                       'validation_rows': 4, 'test_rows': 4},
        'approval': {'reviewer': 'synthetic-independent-reviewer', 'requesting_agent_id': 'a12',
            'rationale': 'Hand-built test only, not real training or independent approval.',
            'approved_at': '2026-10-07T04:01:00+00:00', 'model_id': model_id,
            'model_artifact_hash': digest, 'receipt': {'id': 'synthetic-model-approval'}}}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('PRIME_SPINE_TOKEN', AUTH[7:])
    artifact = synthetic_artifact()
    current = deepcopy(artifact)
    events = []
    def verify_approval(value):
        return value.get('receipt') == {'id': 'synthetic-model-approval'} and value.get('reviewer') == 'synthetic-independent-reviewer'
    def verify_decision(value):
        return value.get('decision_id') == 'synthetic-independent-authority'
    fabric = MLPCapabilityFabric(verify_approval=verify_approval, verify_capability_decision=verify_decision)
    model_id = fabric.register(artifact)
    certification = {'agent_id': 'a12', 'capability_id': 'responsibility.a12',
        'level': 'L6', 'trust_state': 'CERTIFIED-HEALTHY', 'health': 'HEALTHY'}
    def lineage(identity):
        events.append('lineage')
        assert identity == model_id
        return deepcopy(current)
    def read_certification(actor, capability):
        events.append('certification')
        assert (actor, capability) == ('a12', 'responsibility.a12')
        return deepcopy(certification)
    recorded = []
    def record_evidence(value):
        events.append('evidence')
        recorded.append(deepcopy(value))
        return {'record_id': 'synthetic-mlp-record', 'evidence_sha256': value['evidence_sha256']}
    executor = GovernedMLPExecution(fabric, read_current_artifact=lineage,
        read_certification=read_certification, runtime_health=lambda: True, record_evidence=record_evidence)
    request = {'agent_id': 'a12', 'model_id': model_id, 'model_artifact_hash': artifact['model_artifact_hash'],
        'model_version': '1.0.0', 'trace_id': TRACE, 'rows': [{'x': 1}, {'x': -1}],
        'capability_decision': {'decision_id': 'synthetic-independent-authority', 'agent_id': 'a12',
            'model_id': model_id, 'model_artifact_hash': artifact['model_artifact_hash'],
            'trace_id': TRACE, 'capability': 'ml.mlp.regression'}}
    return executor, request, artifact, current, certification, events, recorded


def test_current_synthetic_l6_not_l7_may_execute_exact_approved_numeric_model(setup):
    executor, request, _, _, _, events, recorded = setup
    result = executor.execute(request, AUTH)
    assert result['output'] == [2.5, .5]
    assert result['trace_id'] == TRACE and result['agent_id'] == 'a12'
    assert result['model_artifact_hash'] == request['model_artifact_hash']
    assert result['verification'] == result['production_acceptance'] == result['independent_attestation'] == 'UNVERIFIED'
    assert result['status'] == 'EXECUTED_VERIFY_REQUIRED'
    assert result['evidence_ref'] == 'synthetic-mlp-record'
    assert executor.fabric.health(request['model_id'])['inferences'] == 1
    assert len(recorded) == 1 and events.count('lineage') == 3
    assert 'rows' not in recorded[0] and 'output' not in recorded[0]
    assert result['persistence'] == 'CALLBACK_ACKNOWLEDGED_NOT_RESTART_PROOF'
    assert request['rows'] == [{'x': 1}, {'x': -1}]


def test_wrong_auth_precedes_lineage_verifiers_and_store_callbacks(setup):
    executor, request, _, _, _, events, recorded = setup
    with pytest.raises(Exception) as error:
        executor.execute(request, 'Bearer wrong-synthetic-test-token')
    assert error.value.status_code == 401
    assert events == [] and recorded == []
    assert executor.fabric.health(request['model_id'])['inferences'] == 0


@pytest.mark.parametrize('field,value', [('agent_id', 'a99'), ('agent_id', 'prime'),
    ('agent_id', 'analysis'), ('model_id', '../model'), ('model_artifact_hash', False),
    ('model_version', 'latest'), ('trace_id', 'not-a-trace'), ('rows', []),
    ('rows', [{'x': 1}] * 1001), ('capability_decision', False)])
def test_malformed_request_fails_before_lineage_or_execution(setup, field, value):
    executor, request, _, _, _, events, _ = setup
    request[field] = value
    with pytest.raises(MLPExecutionError, match='MLP_REQUEST_INVALID') as error:
        executor.execute(request, AUTH)
    assert error.value.execution_admitted is False and error.value.retry_authorized is False
    assert events == []


@pytest.mark.parametrize('rows', [[{'x': False}], [{'x': None}], [{'x': float('nan')}],
    [{'x': float('inf')}], [{'unknown': 1}], [{'x': 1, 'other': 2}], [1]])
def test_invalid_numeric_feature_input_never_runs_model(setup, rows):
    executor, request, _, _, _, _, _ = setup
    request['rows'] = rows
    with pytest.raises(MLPExecutionError, match='MLP_INPUT_OR_COMPUTE_BUDGET_INVALID'):
        executor.execute(request, AUTH)
    assert executor.fabric.health(request['model_id'])['inferences'] == 0


@pytest.mark.parametrize('mutation', ['candidate', 'hash', 'version', 'weights', 'approval-revoked', 'unregistered'])
def test_unapproved_unregistered_or_wrong_current_lineage_cannot_execute(setup, mutation):
    executor, request, _, current, _, _, _ = setup
    if mutation == 'candidate':
        current.update(approval_state='CANDIDATE', health='UNVERIFIED')
        current.pop('approval')
    elif mutation == 'hash': request['model_artifact_hash'] = 'c' * 64
    elif mutation == 'version': request['model_version'] = '2.0.0'
    elif mutation == 'weights': current['weights'][0]['weights'][0][0] = 2
    elif mutation == 'approval-revoked': executor.fabric.verify_approval = lambda _: False
    else: executor.fabric.models.clear()
    with pytest.raises(MLPExecutionError, match='MLP_CURRENT_APPROVED_LINEAGE_UNAVAILABLE'):
        executor.execute(request, AUTH)


@pytest.mark.parametrize('mutation', ['l0', 'stale', 'wrong-agent', 'wrong-capability', 'unhealthy', 'runtime-unknown'])
def test_current_certified_role_and_runtime_requirements_are_not_weakened(setup, mutation):
    executor, request, _, _, cert, _, _ = setup
    if mutation == 'l0': cert.update(level='L0', trust_state='UNPROVEN')
    elif mutation == 'stale': cert['trust_state'] = 'REVALIDATION-REQUIRED'
    elif mutation == 'wrong-agent': cert['agent_id'] = 'a18'
    elif mutation == 'wrong-capability': cert['capability_id'] = 'responsibility.a11'
    elif mutation == 'unhealthy': cert['health'] = 'UNKNOWN'
    else: executor.runtime_health = lambda: 'true'
    with pytest.raises(MLPExecutionError, match='MLP_CURRENT_AGENT_ROUTE_UNAVAILABLE'):
        executor.execute(request, AUTH)
    assert executor.fabric.health(request['model_id'])['inferences'] == 0


@pytest.mark.parametrize('field,value', [('agent_id', 'a18'), ('capability', 'ml.mlp.classification'),
    ('model_artifact_hash', 'c' * 64), ('model_id', 'other'), ('trace_id', 'other'),
    ('decision_id', 'self-asserted')])
def test_independent_decision_binds_actor_capability_model_hash_and_trace(setup, field, value):
    executor, request, _, _, _, _, _ = setup
    request['capability_decision'][field] = value
    with pytest.raises(MLPExecutionError, match='MLP_INDEPENDENT_CAPABILITY_DECISION_DENIED'):
        executor.execute(request, AUTH)
    assert executor.fabric.health(request['model_id'])['inferences'] == 0


def test_absent_independent_decision_or_domain_callback_is_a_specific_closed_gate(setup):
    executor, request, _, _, _, _, _ = setup
    executor.fabric.verify_capability_decision = None
    with pytest.raises(MLPExecutionError, match='MLP_INDEPENDENT_CAPABILITY_DECISION_DENIED'):
        executor.execute(request, AUTH)
    executor.read_current_artifact = None
    with pytest.raises(MLPExecutionError, match='MLP_DOMAIN_INTEGRATION_UNAVAILABLE'):
        executor.execute(request, AUTH)


def test_persist_callback_failure_does_not_replay_or_expose_private_errors(setup):
    executor, request, _, _, _, _, _ = setup
    def fail(_): raise RuntimeError('PRIVATE_STORAGE_SENTINEL')
    executor.record_evidence = fail
    with pytest.raises(MLPExecutionError, match='MLP_EVIDENCE_PERSISTENCE_UNCERTAIN') as error:
        executor.execute(request, AUTH)
    assert error.value.execution_admitted is True and error.value.retry_authorized is False
    assert 'PRIVATE_STORAGE_SENTINEL' not in str(error.value)
    assert executor.fabric.health(request['model_id'])['inferences'] == 1
    assert executor._slot.acquire(blocking=False)
    executor._slot.release()


def test_wrong_persisted_evidence_hash_cannot_claim_delivery(setup):
    executor, request, _, _, _, _, _ = setup
    executor.record_evidence = lambda _: {'record_id': 'record', 'evidence_sha256': '0' * 64}
    with pytest.raises(MLPExecutionError, match='MLP_EVIDENCE_PERSISTENCE_UNCERTAIN') as error:
        executor.execute(request, AUTH)
    assert error.value.execution_admitted is True


def test_busy_numeric_slot_cannot_start_a_second_operation(setup):
    executor, request, _, _, _, events, _ = setup
    executor._slot.acquire()
    try:
        with pytest.raises(MLPExecutionError, match='MLP_EXECUTION_BUSY'):
            executor.execute(request, AUTH)
        assert events == []
    finally:
        executor._slot.release()


def test_approval_details_private_inputs_and_extra_result_fields_are_not_exported(setup):
    executor, request, _, current, _, _, recorded = setup
    current['approval']['receipt']['private'] = 'PRIVATE_SENTINEL'
    executor.fabric.models[request['model_id']]['approval']['receipt']['private'] = 'PRIVATE_SENTINEL'
    # Synthetic verifier for this privacy case alone permits additional receipt
    # metadata; the production wrapper still requires its literal True verdict.
    executor.fabric.verify_approval = lambda value: (
        value.get('receipt', {}).get('id') == 'synthetic-model-approval'
        and value.get('reviewer') == 'synthetic-independent-reviewer')
    original = executor.fabric.infer_for_agent
    def with_private(*args, **kwargs):
        return {**original(*args, **kwargs), 'private': 'PRIVATE_SENTINEL'}
    executor.fabric.infer_for_agent = with_private
    result = executor.execute(request, AUTH)
    assert 'PRIVATE_SENTINEL' not in json.dumps(result)
    assert 'PRIVATE_SENTINEL' not in json.dumps(recorded)


def test_lineage_changed_after_execution_is_not_accepted_or_replayed(setup):
    executor, request, _, current, _, _, recorded = setup
    original = executor.fabric.infer_for_agent
    def revoked_after_work(*args, **kwargs):
        result = original(*args, **kwargs)
        current['approval']['receipt']['id'] = 'revoked-after-work'
        return result
    executor.fabric.infer_for_agent = revoked_after_work
    with pytest.raises(MLPExecutionError) as error:
        executor.execute(request, AUTH)
    assert error.value.execution_admitted is True and error.value.retry_authorized is False
    assert recorded == []
    assert executor.fabric.health(request['model_id'])['inferences'] == 1


@pytest.mark.parametrize('revoked', ['certification', 'runtime'])
def test_pre_execution_lineage_read_cannot_leave_stale_authority_or_readiness(setup, revoked):
    executor, request, _, _, certification, _, recorded = setup
    original = executor.read_current_artifact
    calls = 0
    def current(model_id):
        nonlocal calls
        calls += 1
        value = original(model_id)
        if calls == 2:
            if revoked == 'certification':
                certification['trust_state'] = 'SUSPENDED'
            else:
                executor.runtime_health = lambda: False
        return value
    executor.read_current_artifact = current
    with pytest.raises(MLPExecutionError, match='MLP_CURRENT_AGENT_ROUTE_UNAVAILABLE') as error:
        executor.execute(request, AUTH)
    assert error.value.execution_admitted is False and error.value.retry_authorized is False
    assert executor.fabric.health(request['model_id'])['inferences'] == 0 and recorded == []


def test_model_result_wrong_actor_binding_cannot_pass_even_after_real_numeric_work(setup):
    executor, request, _, _, _, _, recorded = setup
    original = executor.fabric.infer_for_agent
    def wrong_actor(*args, **kwargs): return {**original(*args, **kwargs), 'agent_id': 'a18'}
    executor.fabric.infer_for_agent = wrong_actor
    with pytest.raises(MLPExecutionError, match='MLP_RESULT_BINDING_INVALID') as error:
        executor.execute(request, AUTH)
    assert error.value.execution_admitted is True and recorded == []
