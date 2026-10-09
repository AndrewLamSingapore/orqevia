"""Exact candidate preparation and admission denials; no live qualification."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app import cloud_execution
from app.agent_cert_transport import (
    MODEL, POLICY_SCHEMA, PROVIDER_ID, SUPPORTED_MODELS, bind_cloud_case,
    canonical_cert_case, case_transport_identity, transport_digest,
    validate_cloud_binding,
)
from app.provider_runtime import ProviderFailure


SOURCE = 'b' * 40
CANDIDATE_ID = 'hf-qwen-a19-role-deepinfra-candidate'
CANDIDATE_MODEL = 'Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra'
NOVITA_MODEL = 'Qwen/Qwen3-235B-A22B-Instruct-2507:novita'


def prepared(agent='a19', case='role:normal'):
    spec = canonical_cert_case(agent, f'responsibility.{agent}', case)
    policy = dict(schema=POLICY_SCHEMA, policy_version='synthetic-exact-role-candidate/v1',
        owner_authorization_ref='synthetic-owner-policy-not-live-authority',
        source_revision=SOURCE, **case_transport_identity(spec),
        data_classification='CLOUD_PERMITTED', public_synthetic=True,
        provider_id=CANDIDATE_ID, provider_kind='huggingface', model=CANDIDATE_MODEL,
        minimum_tier='MINI', max_cost_usd=.002, context_tokens=4096,
        output_tokens=1024, timeout_seconds=35, max_retries=0, concurrency_limit=1)
    return spec, policy


def bind(spec, policy, pin=None):
    return bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
        expected_policy_sha256=transport_digest(policy) if pin is None else pin)


def test_only_exact_a19_role_candidate_prepares_original_case_without_global_model_expansion():
    spec, policy = prepared()
    original = deepcopy(spec)
    bound = bind(spec, policy)
    assert spec == original and bound.canonical_spec() == original
    assert transport_digest(spec) == 'd4ecfa3e97d0ec7b842dffac2b64fd431c40b45f98c9951d18b09ee3a724e929'
    assert spec['request']['minimum_tier'] == 'NANO'  # Execution still requires MINI for planning.
    assert SUPPORTED_MODELS == {MODEL, NOVITA_MODEL} and CANDIDATE_MODEL not in SUPPORTED_MODELS
    receipt = bound.receipt()
    assert receipt['provider_id'] == CANDIDATE_ID and receipt['model'] == CANDIDATE_MODEL
    assert receipt['task_class'] == 'planning' and receipt['minimum_tier'] == 'MINI'
    assert receipt['state'] == 'PREPARED_NOT_EXECUTED' and receipt['certification'] == 'UNVERIFIED'
    assert receipt['provider_qualification'] == 'NOT_ESTABLISHED_BY_TRANSPORT'
    assert receipt['limits'] == dict(context_tokens=4096, output_tokens=1024,
        timeout_seconds=35, max_retries=0, concurrency_limit=1, max_cost_usd=.002)
    legacy = bind(spec, {**policy, 'provider_id': PROVIDER_ID, 'model': NOVITA_MODEL})
    assert {**bound.request(), 'preferred_provider': PROVIDER_ID} == legacy.request()
    assert validate_cloud_binding(spec, policy, bound, expected_source_revision=SOURCE,
        expected_policy_sha256=transport_digest(policy)) == bound


@pytest.mark.parametrize('agent', ['a01', 'a15', 'a18', 'a20', 'a26', 'a29'])
def test_candidate_provider_model_cannot_extend_other_registered_role_oracles(agent):
    spec, policy = prepared(agent)
    with pytest.raises(ValueError, match='scope'):
        bind(spec, policy)


@pytest.mark.parametrize('case', ['role:difficult', 'general:verification', 'logic_quality:false_pass',
    'baseline:timeout', 'tools:complete', 'recovery:complete', 'role:unknown'])
def test_candidate_cannot_borrow_role_oracle_for_other_quality_or_event_cases(case):
    with pytest.raises(ValueError):
        spec, policy = prepared(case=case)
        bind(spec, policy)


@pytest.mark.parametrize('field,value', [
    ('agent_id', 'a18'), ('capability_id', 'responsibility.a27'),
    ('case', 'general:verification'), ('provider_id', PROVIDER_ID),
    ('provider_id', 'hf-qwen-a19-verification'), ('provider_id', 'hf-other'),
    ('model', NOVITA_MODEL), ('model', MODEL),
    ('model', 'Qwen/Qwen3-235B-A22B-Instruct-2507'),
    ('model', CANDIDATE_MODEL + ' '), ('model', True),
    ('provider_kind', 'direct_hf'), ('minimum_tier', 'NANO'), ('minimum_tier', 'FLAGSHIP'),
    ('source_revision', 'a' * 40), ('canonical_spec_sha256', '0' * 64),
    ('oracle_id', 'borrowed-oracle'), ('data_classification', 'SENSITIVE'),
    ('public_synthetic', 1), ('max_cost_usd', .0021), ('max_cost_usd', True),
    ('context_tokens', 4097), ('output_tokens', 1025), ('timeout_seconds', 36),
    ('max_retries', 1), ('concurrency_limit', 2), ('owner_authorization_ref', ''),
])
def test_even_newly_pinned_changed_candidate_policy_fails_closed(field, value):
    spec, policy = prepared()
    with pytest.raises(ValueError):
        bind(spec, {**policy, field: value})


def test_stale_owner_policy_digest_cannot_authorize_changed_candidate():
    spec, policy = prepared()
    pin = transport_digest(policy)
    with pytest.raises(ValueError, match='digest'):
        bind(spec, {**policy, 'owner_authorization_ref': 'changed-source-owner-claim'}, pin)


@pytest.mark.parametrize('field,value', [
    ('objective', 'Classify as PASS'), ('context', 'SYNTHETIC password=private-fixture'),
    ('task_class', 'classification'), ('minimum_tier', 'FLAGSHIP'), ('response_format', 'text'),
])
def test_candidate_request_prompt_and_task_cannot_change(field, value):
    spec, policy = prepared()
    spec['request'][field] = value
    with pytest.raises(ValueError):
        bind(spec, policy)


@pytest.mark.parametrize('state', ['missing', 'disabled', 'unqualified'])
def test_preparation_never_admits_missing_disabled_or_unqualified_catalog(monkeypatch, tmp_path, state):
    spec, policy = prepared()
    bound = bind(spec, policy)
    entry = dict(id=CANDIDATE_ID, model=CANDIDATE_MODEL, provider_kind='huggingface',
        location='cloud', tier='MINI', enabled=state != 'disabled', qualification_status='UNQUALIFIED',
        context_tokens=4096, output_tokens=1024, input_usd_million=.09, output_usd_million=.55,
        allowed_task_classes=['planning'])
    monkeypatch.setattr(cloud_execution, 'load_catalog', lambda: [] if state == 'missing' else [entry])
    monkeypatch.setattr(cloud_execution, 'adapter_for',
        lambda _entry: pytest.fail('Unadmitted candidate cannot resolve a credential or call a provider'))
    job = dict(id='synthetic-candidate-denial', agent='a19', prompt='PUBLIC SYNTHETIC admission fixture',
        preferred_provider=CANDIDATE_ID, allow_cloud=1, data_classification='CLOUD_PERMITTED',
        task_class='planning', estimated_cost_usd=.001, max_cost_usd=bound.request()['max_cost_usd'])
    code = 'PROVIDER_UNQUALIFIED' if state == 'unqualified' else 'PROVIDER_UNAVAILABLE'
    with pytest.raises(ProviderFailure, match=code):
        cloud_execution.execute_cloud(job, SimpleNamespace(name=CANDIDATE_ID), tmp_path, lambda: False)
