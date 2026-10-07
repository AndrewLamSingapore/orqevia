"""Owned temporary-domain joins, not actual agent execution or certification."""
import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests import test_agent_cert_review_dispatch as fixture
from tests.test_agent_cert_review_dispatch import configured
from app import agent_dispatch_api as dispatch
from app.agent_cert_a19_cases import ORACLE_ID, SUPPORTED_CASES, _expected
from app.agent_cert_role_review import canonical_case_spec
from app.artifact_factory import ArtifactFactory
from app.tier_router import Tier


def prepare(value, case_id):
    spec = canonical_case_spec('a19', 'responsibility.a19', case_id)
    answer = fixture.canonical(_expected(case_id)).decode()
    original = dispatch.AgentRequest(**spec['request'])
    value.job.update(result=answer, task_class=original.task_class,
        prompt=dispatch.packed_inference_prompt(original, Tier.FLAGSHIP,
                                               'a19', fixture.CORRELATION))
    execution = value.payload['execution']
    dimension, test_case = case_id.split(':')
    execution.update(dimension=dimension, test_case=test_case, case_spec=spec)
    execution['job'].update(result=answer, result_sha256=fixture.digest(answer.encode()))
    rebind(value)
    return spec


def rebind(value):
    value.payload['expected_execution_sha256'] = fixture.digest(
        fixture.canonical(value.payload['execution']))


def cloud(value, monkeypatch, case_id, model):
    from app.agent_cert_transport import (bind_cloud_case, canonical_cert_case,
        case_transport_identity, transport_digest, POLICY_SCHEMA, PROVIDER_ID)
    spec = canonical_cert_case('a19', 'responsibility.a19', case_id)
    policy = dict(schema=POLICY_SCHEMA, policy_version='fixture-case-v1',
        owner_authorization_ref='synthetic-owner-approval-fixture',
        source_revision=fixture.SOURCE, **case_transport_identity(spec),
        data_classification='CLOUD_PERMITTED', public_synthetic=True,
        provider_id=PROVIDER_ID, provider_kind='huggingface', model=model,
        minimum_tier='FLAGSHIP', max_cost_usd=0.002, context_tokens=4096,
        output_tokens=1024, timeout_seconds=35, max_retries=0, concurrency_limit=1)
    binding = bind_cloud_case(spec, policy, expected_source_revision=fixture.SOURCE,
        expected_policy_sha256=transport_digest(policy))
    value.job.update(provider=PROVIDER_ID, preferred_provider=PROVIDER_ID, model=model,
        allow_cloud=1, data_classification='CLOUD_PERMITTED', max_cost_usd=0.002,
        input_tokens=150, output_tokens=90, actual_cost_usd=0.0000657)
    execution = value.payload['execution']
    execution['job']['provider'] = PROVIDER_ID
    execution['transport']['provider_locality'] = 'CLOUD'
    route = {key: value.job[key] for key in ('preferred_provider', 'model', 'allow_cloud',
        'data_classification', 'task_class', 'classification', 'max_retries',
        'max_cost_usd', 'input_tokens', 'output_tokens', 'actual_cost_usd')}
    route['prompt_sha256'] = fixture.digest(value.job['prompt'].encode())
    execution['cloud_transport'] = {'binding': binding.receipt(), 'queue_route': route}
    rebind(value)
    monkeypatch.setattr(fixture.compute_queue_api, 'providers', lambda: [
        SimpleNamespace(name=PROVIDER_ID, kind='cloud', model=model)])


def review(value):
    result = fixture.run(value)
    metadata, raw = ArtifactFactory(value.root / 'artifacts').retrieve(
        result['artifact']['artifact_id'])
    return result, metadata, json.loads(raw)


@pytest.mark.parametrize('case_id', sorted(SUPPORTED_CASES))
def test_exact_owned_a19_case_uses_its_canonical_prompt_and_oracle(configured, case_id):
    spec = prepare(configured, case_id)
    before = fixture.digest((configured.root / 'objectives.db').read_bytes())
    result, metadata, observation = review(configured)
    assert result['state'] == 'COMPLETED' and result['agent_id'] == 'a26'
    assert result['model_calls'] == 0 and result['certification'] == 'UNVERIFIED'
    assert result['review_action_durable'] is True
    assert metadata['creator_agents'] == ['a26']
    assert (observation['dimension'], observation['test_case']) == tuple(case_id.split(':'))
    assert observation['oracle_id'] == ORACLE_ID
    assert observation['test_result'] == 'PASS' and observation['review_errors'] == []
    assert observation['subject_execution_verification'] == 'QUEUE_AND_OBJECTIVE_JOINED'
    joined = observation['subject_domain_join']
    assert joined['case_spec_sha256'] == fixture.digest(fixture.canonical(spec))
    assert joined['prompt_sha256'] == fixture.digest(configured.job['prompt'].encode())
    assert joined['objective_id'] == fixture.OBJECTIVE and joined['job_id'] == fixture.JOB
    assert fixture.digest((configured.root / 'objectives.db').read_bytes()) == before
    actions = [json.loads(line) for line in configured.ledger.path.read_text().splitlines()]
    assert [row['phase'] for row in actions] == ['started', 'completed']
    assert all(row['agent_id'] == 'a26' and row['action_type'] == 'agent.certification.role.review'
               and row['action_id'] == result['review_action_id'] for row in actions)


@pytest.mark.parametrize('model', ['Qwen/Qwen3-32B:deepinfra',
                                  'Qwen/Qwen3-235B-A22B-Instruct-2507:novita'])
@pytest.mark.parametrize('case_id', ['role:difficult', 'logic_quality:contradiction',
                                   'adversarial:injection_attempt'])
def test_cloud_case_preserves_flagship_requirement_and_exact_route(configured, monkeypatch, model, case_id):
    prepare(configured, case_id)
    cloud(configured, monkeypatch, case_id, model)
    result, _, observation = review(configured)
    assert observation['test_result'] == 'PASS'
    assert result['certification'] == 'UNVERIFIED' and result['model_calls'] == 0
    assert configured.payload['execution']['cloud_transport']['binding']['model'] == model
    assert configured.job['task_class'] == 'complex_reasoning'
    # The original challenge's NANO minimum is not its effective requirement:
    # complex_reasoning raises routing to FLAGSHIP without relabelling the case.
    assert configured.payload['execution']['cloud_transport']['binding']['minimum_tier'] == 'FLAGSHIP'


@pytest.mark.parametrize('field,value', [
    ('dimension', None), ('dimension', True), ('dimension', []),
    ('dimension', 'role:normal'), ('dimension', 'Role'), ('dimension', 'role '),
    ('test_case', False), ('test_case', {}), ('test_case', 'difficult:normal'),
    ('test_case', 'normal '), ('test_case', 'unknown'), ('test_case', 'recovery'),
])
def test_untyped_or_unsupported_case_cannot_relabel_completed_work(configured, field, value):
    prepare(configured, 'role:difficult')
    configured.payload['execution'][field] = value
    rebind(configured)
    fixture.reject(configured)


@pytest.mark.parametrize('field', ['prompt', 'task_class'])
def test_correct_answer_to_different_owned_task_cannot_be_borrowed(configured, field):
    prepare(configured, 'logic_quality:counterevidence')
    configured.job[field] = ('a different canonical public task' if field == 'prompt'
                             else 'planning')
    fixture.reject(configured)


def test_other_canonical_case_spec_is_not_accepted_with_recomputed_digest(configured):
    prepare(configured, 'adversarial:stale_information')
    configured.payload['execution']['case_spec'] = canonical_case_spec(
        'a19', 'responsibility.a19', 'role:edge')
    rebind(configured)
    fixture.reject(configured)


def test_new_case_cannot_be_attributed_to_other_agent(configured):
    prepare(configured, 'role:difficult')
    configured.payload['execution']['agent_id'] = 'a18'
    configured.payload['execution']['executor_identity'] = 'a18'
    rebind(configured)
    fixture.reject(configured)


def test_wrong_substantive_answer_retains_fail_without_certification(configured):
    prepare(configured, 'logic_quality:false_pass')
    answer = copy.deepcopy(_expected('logic_quality:false_pass'))
    first = next(iter(answer))
    answer[first] = 'incorrect-public-synthetic-value'
    raw = fixture.canonical(answer).decode()
    configured.job['result'] = raw
    configured.payload['execution']['job'].update(result=raw,
        result_sha256=fixture.digest(raw.encode()))
    rebind(configured)
    result, _, observation = review(configured)
    assert observation['test_result'] == 'FAIL' and observation['review_errors']
    assert result['certification'] == 'UNVERIFIED' and result['model_calls'] == 0


def test_anonymous_new_case_never_reads_subject_or_creates_artifact(configured, monkeypatch):
    prepare(configured, 'adversarial:unauthorized_action')
    def forbidden(_):
        raise AssertionError('anonymous queue read')
    monkeypatch.setattr(fixture.compute_queue_api, 'queue', SimpleNamespace(get=forbidden))
    with pytest.raises(HTTPException) as failure:
        dispatch.dispatch_request(fixture.request(configured), None)
    assert failure.value.status_code == 401
    assert configured.calls == [None] and not (configured.root / 'artifacts').exists()
