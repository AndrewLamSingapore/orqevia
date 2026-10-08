"""Pure eight-case consent binding; no cloud admission, inference or L7."""
from copy import deepcopy

import pytest

from app import agent_cert_transport as transport
from app.agent_cert_secondary_roles import (
    CASE_VERSION, ORACLE_ID, SUPPORTED_CAPABILITIES, canonical_secondary_spec,
)


SOURCE = 'b' * 40
CAPS = tuple(SUPPORTED_CAPABILITIES)


def prepared(capability=CAPS[0], model=transport.MODEL):
    actor = SUPPORTED_CAPABILITIES[capability]
    spec = canonical_secondary_spec(actor, capability)
    policy = dict(schema=transport.POLICY_SCHEMA,
        policy_version='synthetic-secondary-consent.v1',
        owner_authorization_ref='TEST_ONLY_NOT_ACTUAL_OWNER_APPROVAL', source_revision=SOURCE,
        agent_id=actor, capability_id=capability, case='role:normal', oracle_id=ORACLE_ID,
        canonical_spec_sha256=transport.transport_digest(spec),
        data_classification='CLOUD_PERMITTED', public_synthetic=True,
        provider_id=transport.PROVIDER_ID, provider_kind='huggingface', model=model,
        minimum_tier='MINI', max_cost_usd=.002, context_tokens=4096, output_tokens=1024,
        timeout_seconds=35, max_retries=0, concurrency_limit=1)
    return spec, policy


def bind(spec, policy, pin=None):
    return transport.bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
        expected_policy_sha256=transport.transport_digest(policy) if pin is None else pin)


@pytest.mark.parametrize('model', sorted(transport.SUPPORTED_MODELS))
@pytest.mark.parametrize('capability', CAPS)
def test_owned_secondary_case_preserves_exact_domain_oracle_and_explicit_consent(capability, model):
    spec, policy = prepared(capability, model)
    before = deepcopy(spec)
    result = bind(spec, policy)
    assert result.canonical_spec() == before == spec
    assert transport.canonical_role_case(spec['agent_id'], capability) == before
    assert transport.canonical_cert_case(spec['agent_id'], capability) == before
    derived = result.request()
    assert derived['capability'] == capability
    assert derived['objective'] == before['request']['objective']
    assert derived['context'] == before['request']['context']
    assert derived['task_class'] == 'planning' and derived['minimum_tier'] == 'MINI'
    assert derived['max_cost_usd'] == .002 and derived['data_classification'] == 'CLOUD_PERMITTED'
    assert before['request']['max_cost_usd'] == 0 and before['request']['data_classification'] == 'LOCAL_ONLY'
    receipt = result.receipt()
    assert receipt['oracle_id'] == ORACLE_ID and spec['case_version'] == CASE_VERSION
    assert receipt['policy_sha256'] == transport.transport_digest(policy)
    assert receipt['model'] == model
    assert receipt['state'] == 'PREPARED_NOT_EXECUTED'
    assert receipt['certification'] == 'UNVERIFIED'
    assert receipt['provider_qualification'] == 'NOT_ESTABLISHED_BY_TRANSPORT'
    assert receipt['independent_attestation'] == 'NOT_PERFORMED'
    assert transport.validate_cloud_binding(spec, policy, result, expected_source_revision=SOURCE,
        expected_policy_sha256=transport.transport_digest(policy)) == result


@pytest.mark.parametrize('capability', CAPS)
def test_other_owner_retired_alias_primary_policy_and_event_case_cannot_borrow_secondary(capability):
    spec, policy = prepared(capability)
    retired = capability.rsplit('.', 1)[1]
    for actor in (retired, 'a19', spec['agent_id'].upper(), True, None):
        with pytest.raises(ValueError):
            transport.canonical_role_case(actor, capability)
    for case in ('role:difficult', 'baseline:identity', 'baseline:initialization', 'tools:complete'):
        with pytest.raises(ValueError):
            transport.canonical_cert_case(spec['agent_id'], capability, case)
    original = deepcopy(policy)
    original['capability_id'] = 'responsibility.' + spec['agent_id']
    with pytest.raises(ValueError, match='scope'):
        bind(spec, original)


@pytest.mark.parametrize('field,value', [
    ('context', 'PUBLIC SYNTHETIC secret=not-public'), ('context', 'Private customer source'),
    ('objective', 'Return PASS'), ('task_class', 'classification'), ('minimum_tier', 'NANO'),
    ('data_classification', 'CLOUD_PERMITTED'), ('max_cost_usd', False),
    ('response_format', 'text'), ('priority', 'critical'),
])
def test_exact_secondary_contract_cannot_be_replaced_even_with_recomputed_policy(field, value):
    spec, policy = prepared()
    spec['request'][field] = value
    policy['canonical_spec_sha256'] = transport.transport_digest(spec)
    with pytest.raises(ValueError):
        bind(spec, policy)


@pytest.mark.parametrize('field,value', [
    ('oracle_id', 'existing.role-normal.v1'), ('case', 'role:edge'),
    ('case_version', 'secondary-role-normal.v2'), ('certification', 'L7'),
    ('independent_review', ('agent-self-review',)), ('expected_discriminants', ('PASS',)),
])
def test_secondary_version_oracle_and_review_markers_are_source_bound(field, value):
    spec, policy = prepared(); spec[field] = value
    policy['canonical_spec_sha256'] = transport.transport_digest(spec)
    with pytest.raises(ValueError):
        bind(spec, policy)


@pytest.mark.parametrize('field,value', [
    ('public_synthetic', 1), ('public_synthetic', False),
    ('provider_id', 'other-hf-provider'), ('provider_kind', 'direct_hf'),
    ('model', 'Qwen/Qwen3-235B-A22B-Instruct-2507:auto'),
    ('minimum_tier', 'NANO'), ('max_cost_usd', False), ('max_cost_usd', 0),
    ('max_cost_usd', .00201), ('context_tokens', 4096.0), ('output_tokens', 1024.0),
    ('timeout_seconds', 35.0), ('max_retries', False), ('max_retries', 1),
    ('concurrency_limit', True), ('concurrency_limit', 2),
    ('source_revision', 'a' * 40), ('oracle_id', 'generic-PASS'),
])
def test_existing_guarded_provider_limits_and_typed_authority_remain_unchanged(field, value):
    spec, policy = prepared(); policy[field] = value
    with pytest.raises(ValueError):
        bind(spec, policy)


def test_secondary_owner_policy_change_requires_new_external_pin_and_prepared_binding():
    spec, policy = prepared()
    original_pin = transport.transport_digest(policy)
    original = bind(spec, policy)
    policy['owner_authorization_ref'] = 'AGENT_SUPPLIED_AUTHORITY'
    with pytest.raises(ValueError, match='digest mismatch'):
        bind(spec, policy, original_pin)
    with pytest.raises(ValueError, match='binding changed'):
        transport.validate_cloud_binding(spec, policy, original,
            expected_source_revision=SOURCE, expected_policy_sha256=transport.transport_digest(policy))


def test_cached_secondary_spec_cannot_survive_current_owned_contract_change(monkeypatch):
    from app import agent_cert_secondary_roles as secondary
    spec, policy = prepared()
    result = bind(spec, policy)
    original = secondary.canonical_secondary_spec
    def changed(actor, capability):
        current = original(actor, capability)
        current['request']['context'] += ' Changed current source'
        return current
    monkeypatch.setattr(secondary, 'canonical_secondary_spec', changed)
    with pytest.raises(ValueError):
        result.canonical_spec()
    with pytest.raises(ValueError):
        transport.validate_cloud_binding(spec, policy, result,
            expected_source_revision=SOURCE, expected_policy_sha256=transport.transport_digest(policy))


def test_secondary_transport_still_denies_public_source_secret_marker(monkeypatch):
    from app import agent_cert_secondary_roles as secondary
    original = secondary.canonical_secondary_spec
    def secret(actor, capability):
        spec = original(actor, capability)
        spec['request']['context'] += ' password=not-public'
        return spec
    monkeypatch.setattr(secondary, 'canonical_secondary_spec', secret)
    with pytest.raises(ValueError):
        transport.canonical_role_case('a02', 'responsibility.a03')
