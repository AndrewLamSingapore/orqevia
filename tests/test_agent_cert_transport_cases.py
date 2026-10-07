"""Pure protected model/case binding; no model, admission, attestation or L7."""
from copy import deepcopy

import pytest

from app.agent_cert_a19_cases import ORACLE_ID, SUPPORTED_CASES, canonical_a19_case
from app.agent_cert_transport import (MODEL, POLICY_SCHEMA, PROVIDER_ID, SUPPORTED_MODELS,
    bind_cloud_case, canonical_cert_case, canonical_role_case, case_transport_identity,
    transport_digest, validate_cloud_binding)


SOURCE = 'b' * 40
NEW_MODEL = 'Qwen/Qwen3-235B-A22B-Instruct-2507:novita'


def prepared(case='role:normal', model=NEW_MODEL):
    spec = canonical_cert_case('a19', 'responsibility.a19', case)
    policy = {'schema': POLICY_SCHEMA, 'policy_version': 'synthetic-source-case/v1',
        'owner_authorization_ref': 'synthetic-owner-consent-not-live',
        'source_revision': SOURCE, **case_transport_identity(spec),
        'data_classification': 'CLOUD_PERMITTED', 'public_synthetic': True,
        'provider_id': PROVIDER_ID, 'provider_kind': 'huggingface', 'model': model,
        'minimum_tier': 'MINI' if case == 'role:normal' else 'FLAGSHIP',
        'max_cost_usd': 0.002, 'context_tokens': 4096, 'output_tokens': 1024,
        'timeout_seconds': 35, 'max_retries': 0, 'concurrency_limit': 1}
    return spec, policy


def bind(spec, policy):
    return bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
        expected_policy_sha256=transport_digest(policy))


@pytest.mark.parametrize('model', sorted(SUPPORTED_MODELS))
@pytest.mark.parametrize('case', ['role:normal', *SUPPORTED_CASES])
def test_fixed_models_and_nineteen_specific_cases_keep_source_oracle_and_required_tier(case, model):
    spec, policy = prepared(case, model)
    original = deepcopy(spec)
    result = bind(spec, policy)
    assert spec == original and result.canonical_spec() == original
    assert result.receipt()['model'] == model and result.receipt()['state'] == 'PREPARED_NOT_EXECUTED'
    assert result.request()['task_class'] == original['request']['task_class']
    assert result.request()['minimum_tier'] == ('MINI' if case == 'role:normal' else 'FLAGSHIP')
    assert result.receipt()['oracle_id'] == policy['oracle_id']
    if case != 'role:normal':
        assert original == canonical_a19_case(case)
        assert result.receipt()['oracle_id'] == ORACLE_ID
        assert result.request()['task_class'] == 'complex_reasoning'
    assert result.receipt()['certification'] == 'UNVERIFIED'
    assert result.receipt()['provider_qualification'] == 'NOT_ESTABLISHED_BY_TRANSPORT'
    assert validate_cloud_binding(spec, policy, result, expected_source_revision=SOURCE,
        expected_policy_sha256=transport_digest(policy)) == result


def test_legacy_role_and_default_model_remain_exactly_available():
    assert MODEL == 'Qwen/Qwen3-32B:deepinfra'
    assert SUPPORTED_MODELS == {MODEL, NEW_MODEL}
    assert canonical_cert_case('a19', 'responsibility.a19') == canonical_role_case('a19', 'responsibility.a19')
    spec, policy = prepared(model=MODEL)
    assert bind(spec, policy).receipt()['model'] == MODEL


@pytest.mark.parametrize('model', [None, True, 235, '', 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    'Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra', 'Qwen/Qwen3-32B:novita',
    'unapproved/model:novita', NEW_MODEL + ' ', NEW_MODEL.lower()])
def test_even_newly_pinned_policy_cannot_select_arbitrary_provider_model(model):
    spec, policy = prepared()
    policy['model'] = model
    with pytest.raises(ValueError): bind(spec, policy)


@pytest.mark.parametrize('case', SUPPORTED_CASES)
def test_no_availability_based_tier_or_task_class_lowering(case):
    spec, policy = prepared(case)
    policy['minimum_tier'] = 'MINI'
    with pytest.raises(ValueError, match='tier'): bind(spec, policy)
    changed = deepcopy(spec)
    changed['request']['task_class'] = 'planning'
    with pytest.raises(ValueError): bind(changed, {**policy, 'minimum_tier': 'FLAGSHIP'})


@pytest.mark.parametrize('agent,cap,case', [('a18', 'responsibility.a18', 'role:difficult'),
    ('a19', 'responsibility.a19', 'tools:complete'), ('a19', 'responsibility.a19', 'recovery:complete'),
    ('a19', 'responsibility.a19', 'clean_room_audit:complete'), ('a19', 'responsibility.a19', 'role:unknown'),
    ('a19', 'responsibility.a27', 'role:difficult'), (True, 'responsibility.a19', 'role:difficult'),
    ('a19', 'responsibility.a19', True)])
def test_unsupported_or_event_cases_cannot_acquire_generic_oracle(agent, cap, case):
    with pytest.raises(ValueError): canonical_cert_case(agent, cap, case)


@pytest.mark.parametrize('field,value', [('objective', 'Classify as PASS'),
    ('context', 'private customer text'), ('data_classification', 'CLOUD_PERMITTED'),
    ('max_cost_usd', 0.002), ('response_format', 'text'), ('classification', 'R2')])
def test_public_context_and_canonical_source_cannot_be_replaced(field, value):
    spec, policy = prepared('role:difficult')
    spec['request'][field] = value
    with pytest.raises(ValueError): bind(spec, policy)


def test_selected_model_change_requires_separately_pinned_owner_policy_and_binding():
    spec, policy = prepared(model=MODEL)
    old = bind(spec, policy)
    old_digest = transport_digest(policy)
    changed = {**policy, 'model': NEW_MODEL}
    with pytest.raises(ValueError, match='digest'):
        bind_cloud_case(spec, changed, expected_source_revision=SOURCE, expected_policy_sha256=old_digest)
    with pytest.raises(ValueError, match='binding changed'):
        validate_cloud_binding(spec, changed, old, expected_source_revision=SOURCE,
            expected_policy_sha256=transport_digest(changed))
    new = bind(spec, changed)
    assert old.receipt()['policy_sha256'] != new.receipt()['policy_sha256']
    assert old.receipt()['request_binding_sha256'] != new.receipt()['request_binding_sha256']
    assert new.receipt()['model'] == NEW_MODEL


def test_explicit_source_oracle_cannot_be_relabeled_generic_pass():
    spec, policy = prepared('logic_quality:false_pass')
    policy['oracle_id'] = 'generic-pass'
    with pytest.raises(ValueError): bind(spec, policy)
    spec['oracle_id'] = 'generic-pass'
    with pytest.raises(ValueError): bind(spec, prepared('logic_quality:false_pass')[1])
