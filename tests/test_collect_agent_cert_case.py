"""Synthetic authenticated API/domain fixtures; ZERO network/model/signing calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from app.agent_cert_boundary import review_zero_boundary_json
from app.agent_cert_role_group_two import _CASES
from app.agent_cert_role_review import canonical_role_spec
from app.agent_cert_transport import (MODEL, POLICY_SCHEMA, PROVIDER_ID,
    bind_cloud_case, case_transport_identity, transport_digest)
from app.agent_registry import agent_record
from scripts.agent_cert_reviewed_signing import _review
from scripts.collect_agent_cert_case import (
    CollectedCase, CollectionError, OperatorIO, ROLE_REVIEW_OBJECTIVE, collect_role_case,
)


SOURCE = 'd' * 40
IMAGE = 'sha256:' + 'a' * 64
CODE = 'f' * 40
NOW = datetime(2026, 10, 7, 8, tzinfo=timezone.utc)
JOB = '11111111-1111-4111-8111-111111111111'
OBJECTIVE = '22222222-2222-4222-8222-222222222222'
REVIEW_TASK = '33333333-3333-4333-8333-333333333333'
REVIEW_ACTION = '44444444-4444-4444-8444-444444444444'
NONCE = '55555555-5555-4555-8555-555555555555'
CORRELATION = '66666666-6666-4666-8666-666666666666'
ANSWER = {'required_zero_result': True, 'buggy_zero_result': False,
    'corrected_zero_result': True, 'negative_one_result': False,
    'positive_one_result': True, 'corrected_condition': 'n >= 0',
    'discriminating_assertion': 'assert is_nonnegative(0) is True', 'tests_executed': False}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def moment(milliseconds):
    return (NOW - timedelta(milliseconds=milliseconds)).isoformat()


class SyntheticOperator:
    """Explicit mocks, not a claim that API labels authenticate real callers."""
    def __init__(self, *, agent='a18', cloud=False):
        self.agent = agent
        self.spec = canonical_role_spec(agent, f'responsibility.{agent}')
        self.runtime_value = {'host_id': 'ABEX', 'source_revision': SOURCE,
                              'version': 'fixture-current', 'image_digest': IMAGE}
        self.answer = deepcopy(_CASES[agent][2] if agent in _CASES else ANSWER)
        self.job = {'id': JOB, 'agent': agent, 'model': MODEL if cloud else 'gemma3:4b',
            'provider': PROVIDER_ID if cloud else 'ollama-deep', 'status': 'completed',
            'result': json.dumps(self.answer), 'error': None, 'attempts': 1,
            'created_at': moment(3000), 'started_at': moment(2000), 'completed_at': moment(1000),
            'preferred_provider': PROVIDER_ID if cloud else 'ollama-deep',
            'prompt': 'Bound public synthetic prompt', 'allow_cloud': 1 if cloud else 0,
            'data_classification': 'CLOUD_PERMITTED' if cloud else 'LOCAL_ONLY',
            'classification': 'R0', 'task_class': 'planning', 'max_retries': 0,
            'max_cost_usd': 0.002 if cloud else 0, 'timeout_seconds': 300,
            'input_tokens': 100, 'output_tokens': 50, 'estimated_cost_usd': 0.0004,
            'actual_cost_usd': 0.000022 if cloud else 0}
        self.calls = []
        self.last_request = None
        self.last_review_request = None
        self.proof = None
        self.ticks = 0
        self.entry = {'id': PROVIDER_ID, 'model': MODEL, 'provider_kind': 'huggingface',
            'location': 'cloud', 'enabled': True, 'qualification_status': 'QUALIFIED',
            'endpoint': 'https://router.huggingface.co/v1/chat/completions',
            'tier': 'MINI', 'secret_ref': 'file:HF_TOKEN', 'context_tokens': 4096,
            'output_tokens': 1024, 'concurrency': 1, 'max_retries': 0,
            'input_usd_million': 0.08, 'output_usd_million': 0.28,
            'allowed_task_classes': ['planning'], 'fallback_ids': [],
            'task_budgets': {'planning': {'context_tokens': 4096, 'output_tokens': 1024,
                                         'timeout_seconds': 35}}}
        identity = case_transport_identity(self.spec)
        self.policy = {'schema': POLICY_SCHEMA, 'policy_version': 'owner.role-transport.v1',
            'owner_authorization_ref': 'Owner:test-role-consent', 'source_revision': SOURCE,
            **identity, 'data_classification': 'CLOUD_PERMITTED', 'public_synthetic': True,
            'provider_id': PROVIDER_ID, 'provider_kind': 'huggingface', 'model': MODEL,
            'minimum_tier': 'MINI', 'max_cost_usd': 0.002, 'context_tokens': 4096,
            'output_tokens': 1024, 'timeout_seconds': 35, 'max_retries': 0, 'concurrency_limit': 1}
        self.options = {}
        if cloud:
            self.options = {'cloud_binding': bind_cloud_case(self.spec, self.policy,
                expected_source_revision=SOURCE, expected_policy_sha256=transport_digest(self.policy)),
                'cloud_policy': self.policy, 'expected_owner_policy_sha256': transport_digest(self.policy),
                'expected_provider_entry_sha256': sha(canonical(self.entry))}

    def authorize(self):
        self.calls.append('authorize')

    def runtime(self):
        self.calls.append('runtime')
        return deepcopy(self.runtime_value)

    def submit(self, request):
        self.calls.append('submit')
        self.last_request = request
        return 202, {'id': OBJECTIVE, 'steps': [{'capability': f'responsibility.{self.agent}',
            'dispatch': {'capability': f'responsibility.{self.agent}', 'job': deepcopy(self.job),
                         'correlation_id': CORRELATION, 'tier': 'MINI'}}]}

    def read_job(self, job_id):
        self.calls.append('job')
        assert job_id == JOB
        return 200, deepcopy(self.job)

    def objective_body(self):
        job = self.job
        projected = {key: job.get(key) for key in ('id', 'agent', 'model', 'provider', 'status',
                         'result', 'error', 'created_at', 'started_at', 'completed_at')}
        metadata = {'schema_version': 'jarvis.authoritative-execution.v1', 'authoritative': True,
            'task_id': OBJECTIVE, 'revision': 0, 'state': 'COMPLETED',
            'runtime': deepcopy(self.runtime_value), 'model_content_is_authoritative_metadata': False,
            'provenance': {'runtime': 'IMMUTABLE_OBJECTIVE_RUNTIME'},
            'jobs': [{'job_id': JOB, 'agent': self.agent, 'model': job['model'],
                'provider': job['provider'], 'state': 'completed', 'created_at': job['created_at'],
                'started_at': job['started_at'], 'completed_at': job['completed_at']}]}
        return {'id': OBJECTIVE, 'revision': 0, 'state': 'COMPLETED', 'execution_metadata': metadata,
            'steps': [{'capability': f'responsibility.{self.agent}', 'revision': 0, 'job': projected,
                'dispatch': {'correlation_id': CORRELATION, 'job': {'id': JOB, 'agent': self.agent}}}]}

    def read_objective(self, objective_id):
        self.calls.append('objective')
        assert objective_id == OBJECTIVE
        return 200, self.objective_body()

    def dispatch_review(self, request):
        self.calls.append('review')
        self.last_review_request = deepcopy(request)
        context = json.loads(request['context'])
        execution = context['execution']
        actor = 'a18' if self.agent == 'a26' else 'a26'
        cap = 'responsibility.a27' if self.agent == 'a26' else 'responsibility.a26'
        content = {'schema_version': 'prime.agent-cert-role-review.v1', 'task_id': REVIEW_TASK,
            'reviewer_id': actor, 'reviewer_capability_id': cap, 'subject_agent_id': self.agent,
            'subject_capability_id': f'responsibility.{self.agent}', 'dimension': 'role', 'test_case': 'normal',
            'source_revision': SOURCE, 'runtime_image_id': IMAGE, 'subject_job_id': JOB,
            'review_nonce': context['review_nonce'], 'reviewed_at': moment(800),
            'execution_evidence_sha256': context['expected_execution_sha256'],
            'case_spec_sha256': sha(canonical(self.spec)), 'result_sha256': execution['job']['result_sha256'],
            'oracle_id': 'group_two_exact_role_oracle/v1' if self.agent in _CASES else 'existing.role-normal.v1',
            'test_result': 'PASS', 'review_errors': [], 'model_calls': 0, 'execution_model': 'DETERMINISTIC',
            'subject_execution_verification': 'QUEUE_AND_OBJECTIVE_JOINED', 'certification': 'UNVERIFIED',
            'subject_domain_join': {'objective_id': OBJECTIVE, 'objective_revision': 0, 'job_id': JOB,
                'runtime': deepcopy(self.runtime_value), 'observed_at': moment(700),
                'execution_metadata_sha256': sha(canonical(self.objective_body()['execution_metadata'])),
                'prompt_sha256': sha(self.job['prompt'].encode()), 'case_spec_sha256': sha(canonical(self.spec))}}
        raw = json.dumps(content, indent=2).encode('utf-8')
        metadata = {'artifact_id': 'e' * 32, 'task_id': REVIEW_TASK, 'type': 'json',
            'creator_agents': [actor], 'timestamp': moment(300), 'version': '1.0.0',
            'provenance': 'Deterministic computation; zero model calls', 'runtime_revision': SOURCE,
            'validation_state': 'STRUCTURE_VALIDATED',
            'content_validation': 'Not independently established by structural validation',
            'location': 'artifact.json', 'sha256': sha(raw), 'bytes': len(raw), 'delivery_state': 'AVAILABLE'}
        dispatch = {'task_id': REVIEW_TASK, 'state': 'COMPLETED', 'artifact': metadata,
            'model_calls': 0, 'execution_model': 'DETERMINISTIC', 'agent_id': actor, 'capability': cap,
            'runtime_source_revision': SOURCE, 'review_action_id': REVIEW_ACTION,
            'review_action_durable': True, 'certification': 'UNVERIFIED'}
        base = {'task_id': REVIEW_TASK, 'agent_id': actor, 'action_type': 'agent.certification.role.review',
            'tool': 'artifact-factory', 'target': '', 'classification': 'R0',
            'parameters_summary': {'schema_version': content['schema_version'], 'read_only_observations': True},
            'model_backend': 'deterministic', 'execution_location': 'local', 'parent_agent': None,
            'workflow_id': None, 'action_id': REVIEW_ACTION}
        start = dict(base, phase='started', timestamp=moment(500), sequence=10, previous_sha256='0' * 64)
        start['sha256'] = sha(canonical(start))
        end = dict(base, phase='completed', timestamp=moment(100), sequence=11,
            previous_sha256=start['sha256'], success=True, duration_ms=400,
            result_summary={'type': 'dict', 'artifact_id': metadata['artifact_id'],
                            'sha256': metadata['sha256'], 'location': 'artifact.json'})
        end['sha256'] = sha(canonical(end))
        self.proof = {'dispatch': dispatch, 'raw': raw, 'actions': [json.dumps(start), json.dumps(end)]}
        return 202, deepcopy(dispatch)

    def artifact(self, artifact_id):
        self.calls.append('artifact')
        assert artifact_id == 'e' * 32
        return 200, self.proof['raw'], self.proof['dispatch']['artifact']['sha256']

    def actions(self, action_id):
        self.calls.append('actions')
        assert action_id == REVIEW_ACTION
        return deepcopy(self.proof['actions'])

    def provider(self, provider_id):
        self.calls.append('provider')
        assert provider_id == PROVIDER_ID
        return deepcopy(self.entry)

    def io(self, **changes):
        values = dict(authorize=self.authorize, runtime=self.runtime, submit_objective=self.submit,
            read_objective=self.read_objective, read_job=self.read_job, dispatch_reviewer=self.dispatch_review,
            read_artifact=self.artifact, read_review_actions=self.actions, read_provider_entry=self.provider)
        values.update(changes)
        return OperatorIO(**values)

    def run(self, *, io=None, **options):
        return collect_role_case(self.spec, io=io or self.io(), expected_source_revision=SOURCE,
            expected_runtime_image=IMAGE, reviewer_code_revision=CODE, review_run_id='synthetic-operator-run',
            monotonic=lambda: self.ticks, pause=lambda duration: setattr(self, 'ticks', self.ticks + duration),
            wall_clock=lambda: NOW, nonce_factory=lambda: NONCE, **dict(self.options, **options))


def test_one_local_objective_and_real_shaped_registered_review_unsigned_only():
    state = SyntheticOperator()
    result = state.run()
    assert result.summary['state'] == 'UNSIGNED_CASE_EVIDENCE', result.summary
    assert state.calls.count('submit') == state.calls.count('review') == 1
    assert state.last_request == state.spec['request']
    assert state.last_review_request['objective'] == ROLE_REVIEW_OBJECTIVE
    assert result.execution_bytes == canonical(json.loads(result.execution_bytes))
    assert result.reviewer_artifact_bytes == state.proof['raw']
    assert result.action_records == tuple(state.proof['actions'])
    assert result.summary['certification'] == 'UNVERIFIED'
    assert result.summary['signature'] == 'NOT_PERFORMED'
    assert 'attestation' not in result.summary and 'l7_status' not in result.summary
    assert 'corrected_condition' not in repr(result)


@pytest.mark.parametrize('agent', ['a18', 'a19', 'a20', 'a26'])
@pytest.mark.parametrize('cloud', [False, True])
def test_exact_signing_bridge_compatibility_without_signing(agent, cloud):
    state = SyntheticOperator(agent=agent, cloud=cloud)
    result = state.run()
    assert result.summary['state'] == 'UNSIGNED_CASE_EVIDENCE', result.summary
    review = json.loads(result.review_bytes)
    row = {'agent_id': agent, 'capability_id': f'responsibility.{agent}', 'dimension': 'role',
        'test_case': 'normal', 'certification_test': 'role-normal', 'test_version': '1',
        'test_result': 'PASS', 'verifier': review['reviewer_identity'], 'executor_identity': agent,
        'source_revision': SOURCE, 'review_source_revision': SOURCE, 'reviewer_code_revision': CODE,
        'authority_scope': agent_record(agent)['authority'], 'certified_at': NOW.isoformat(),
        'last_revalidated': NOW.isoformat(), 'expires_at': (NOW + timedelta(hours=1)).isoformat(),
        'review_run_id': review['review_run_id'], 'review_test_version': review['review_test_version']}
    bridge_options = {'cloud_binding': state.options.get('cloud_binding'),
        'cloud_policy': state.options.get('cloud_policy'),
        'expected_owner_policy_sha256': state.options.get('expected_owner_policy_sha256')}
    assert _review(row, result.execution_bytes, result.review_bytes, source_revision=SOURCE,
        runtime_image_id=IMAGE, reviewer_code_revision=CODE, now=NOW, **bridge_options) is True
    if cloud:
        execution = json.loads(result.execution_bytes)
        assert execution['case_spec']['request']['data_classification'] == 'LOCAL_ONLY'
        assert execution['transport']['provider_locality'] == 'CLOUD'
        assert execution['cloud_transport']['queue_route']['task_class'] == 'planning'
        assert state.last_request['minimum_tier'] == 'MINI'
        assert state.calls.count('provider') >= 3


def test_authority_denial_before_any_owned_reader_or_submission():
    state = SyntheticOperator()
    def deny():
        raise RuntimeError('secret-token-not-for-output')
    result = state.run(io=state.io(authorize=deny))
    assert result.summary['reason'] == 'OPERATOR_CALLBACK_FAILED'
    assert state.calls == []
    assert 'secret-token' not in repr(result)


def test_interrupted_submit_is_attempted_once_and_never_replayed():
    state = SyntheticOperator()
    def interrupted(request):
        state.calls.append('submit')
        raise RuntimeError('provider-secret-and-private-path')
    result = state.run(io=state.io(submit_objective=interrupted))
    assert result.summary['submission_uncertain'] is True
    assert result.summary['subject_submission_attempts'] == 1
    assert state.calls.count('submit') == 1 and 'review' not in state.calls
    assert 'private-path' not in repr(result)


@pytest.mark.parametrize('reply', [(202, {'id': OBJECTIVE, 'steps': []}),
    (503, {}), (True, {}), (202, {'id': OBJECTIVE, 'steps': [{'state': 'indeterminate'}]})])
def test_ambiguous_or_bad_submission_retains_uncertainty_no_second_post(reply):
    state = SyntheticOperator()
    def submit(request):
        state.calls.append('submit')
        return deepcopy(reply)
    result = state.run(io=state.io(submit_objective=submit))
    assert result.summary['state'] == 'REJECTED'
    assert result.summary['submission_uncertain'] is True
    assert state.calls.count('submit') == 1 and 'review' not in state.calls


@pytest.mark.parametrize('key,value', [('source_revision', 'e' * 40),
    ('image_digest', 'sha256:' + 'b' * 64), ('host_id', 'UNKNOWN'), ('version', False)])
def test_runtime_pin_mismatch_stops_before_subject_submission(key, value):
    state = SyntheticOperator()
    state.runtime_value[key] = value
    result = state.run()
    assert result.summary['reason'] == 'RUNTIME_IDENTITY_MISMATCH'
    assert 'submit' not in state.calls


def test_runtime_drift_after_subject_preserves_raw_evidence_and_stops_review():
    state = SyntheticOperator()
    counter = 0
    def runtime():
        nonlocal counter
        counter += 1
        return dict(state.runtime_value, image_digest=IMAGE if counter == 1 else 'sha256:' + 'b' * 64)
    result = state.run(io=state.io(runtime=runtime))
    assert result.summary['state'] == 'REJECTED' and result.execution_bytes is not None
    assert state.calls.count('submit') == 1 and 'review' not in state.calls


def test_oracle_failure_retained_without_dispatching_a_false_pass_review():
    state = SyntheticOperator()
    state.job['result'] = json.dumps(dict(ANSWER, required_zero_result=False))
    result = state.run()
    assert result.summary['reason'] == 'CASE_ORACLE_FAILED'
    assert json.loads(result.execution_bytes)['job']['result'] == state.job['result']
    assert 'review' not in state.calls


@pytest.mark.parametrize('mutation', [lambda value: value.update(revision=True),
    lambda value: value.update(state='RUNNING'),
    lambda value: value['steps'].append(deepcopy(value['steps'][0])),
    lambda value: value['steps'][0]['job'].update(result='unrelated'),
    lambda value: value['execution_metadata']['runtime'].update(source_revision='e' * 40),
    lambda value: value['execution_metadata'].update(authoritative=1),
    lambda value: value['execution_metadata']['jobs'][0].update(job_id=REVIEW_TASK)])
def test_current_owned_objective_joins_reject_malformed_or_wrong_state(mutation):
    state = SyntheticOperator()
    def reader(objective_id):
        body = state.objective_body()
        mutation(body)
        return 200, body
    result = state.run(io=state.io(read_objective=reader))
    assert result.summary['state'] == 'REJECTED' and result.execution_bytes is not None
    assert 'review' not in state.calls


@pytest.mark.parametrize('key,value', [('context_tokens', 8192), ('output_tokens', 2048),
    ('concurrency', 2), ('max_retries', 1), ('max_retries', False),
    ('allowed_task_classes', ['classification']), ('tier', 'NANO'),
    ('fallback_ids', ['other']), ('input_usd_million', None), ('output_usd_million', 0),
    ('token', 'do-not-read-me')])
def test_pinned_but_unsafe_provider_entry_denies_before_submit(key, value):
    state = SyntheticOperator(cloud=True)
    state.entry[key] = value
    result = state.run(expected_provider_entry_sha256=sha(canonical(state.entry)))
    assert result.summary['state'] == 'REJECTED' and 'submit' not in state.calls
    assert 'do-not-read-me' not in repr(result)


@pytest.mark.parametrize('budgets', [None, {}, {'planning': {'context_tokens': 4096,
    'output_tokens': 1024, 'timeout_seconds': 36}}, {'planning': {'context_tokens': 4096,
    'output_tokens': 1024, 'timeout_seconds': True}}])
def test_effective_provider_deadline_not_inferred_from_queue_timeout(budgets):
    state = SyntheticOperator(cloud=True)
    state.entry['task_budgets'] = budgets
    result = state.run(expected_provider_entry_sha256=sha(canonical(state.entry)))
    assert result.summary['state'] == 'REJECTED' and 'submit' not in state.calls


@pytest.mark.parametrize('key,value', [('input_tokens', None), ('input_tokens', True),
    ('input_tokens', 4097), ('output_tokens', None), ('output_tokens', 1025),
    ('actual_cost_usd', None), ('actual_cost_usd', True), ('actual_cost_usd', 0.001),
    ('estimated_cost_usd', 0.0)])
def test_cloud_unknown_or_invalid_usage_cost_never_accepted(key, value):
    state = SyntheticOperator(cloud=True)
    state.job[key] = value
    result = state.run()
    assert result.summary['state'] == 'REJECTED' and result.execution_bytes is not None
    assert 'review' not in state.calls


def test_catalog_mutation_after_submission_is_not_hot_swapped():
    state = SyntheticOperator(cloud=True)
    calls = 0
    def entry(provider_id):
        nonlocal calls
        calls += 1
        return dict(state.entry, output_tokens=2048) if calls >= 3 else deepcopy(state.entry)
    result = state.run(io=state.io(read_provider_entry=entry))
    assert result.summary['reason'] == 'PROVIDER_CONTRACT_CHANGED'
    assert result.execution_bytes is not None and 'review' not in state.calls


@pytest.mark.parametrize('key,value', [('preferred_provider', 'wrong-route'),
    ('model', 'other-model'), ('allow_cloud', True), ('max_retries', False),
    ('task_class', 'classification'), ('max_cost_usd', 0.003), ('classification', 'R1')])
def test_cloud_actual_queue_route_not_submission_labels(key, value):
    state = SyntheticOperator(cloud=True)
    def job_reader(job_id):
        return 200, dict(state.job, **{key: value})
    result = state.run(io=state.io(read_job=job_reader))
    assert result.summary['state'] == 'REJECTED'
    assert state.calls.count('submit') == 1 and 'review' not in state.calls


@pytest.mark.parametrize('durable', [False, 1, None])
def test_nondurable_reviewer_never_advances_to_artifact(durable):
    state = SyntheticOperator()
    def reviewer(request):
        status, body = state.dispatch_review(request)
        body['review_action_durable'] = durable
        return status, body
    result = state.run(io=state.io(dispatch_reviewer=reviewer))
    assert result.summary['reason'] == 'DURABLE_REGISTERED_REVIEW_REQUIRED'
    assert result.summary['review_dispatch_uncertain'] is True
    assert state.calls.count('review') == 1 and 'artifact' not in state.calls


def test_interrupted_review_never_retries_after_admission():
    state = SyntheticOperator()
    def reviewer(request):
        state.calls.append('review')
        raise RuntimeError('host-private-value')
    result = state.run(io=state.io(dispatch_reviewer=reviewer))
    assert result.summary['review_dispatch_uncertain'] is True
    assert result.execution_bytes is not None and state.calls.count('review') == 1
    assert 'host-private-value' not in repr(result)


@pytest.mark.parametrize('mutation', [lambda value: value.update(model_calls=False),
    lambda value: value.update(agent_id='a18'),
    lambda value: value.update(capability='responsibility.a18'),
    lambda value: value.update(task_id=JOB),
    lambda value: value.update(runtime_source_revision='e' * 40),
    lambda value: value['artifact'].update(runtime_revision='e' * 40),
    lambda value: value['artifact'].update(bytes=True)])
def test_actual_registered_reviewer_metadata_is_strict_and_independent(mutation):
    state = SyntheticOperator()
    def reviewer(request):
        status, body = state.dispatch_review(request)
        mutation(body)
        return status, body
    result = state.run(io=state.io(dispatch_reviewer=reviewer))
    assert result.summary['state'] == 'REJECTED' and result.execution_bytes is not None
    assert state.calls.count('review') == 1


def test_wrong_artifact_bytes_retained_but_never_bound_by_header():
    state = SyntheticOperator()
    def artifact(artifact_id):
        status, raw, header = state.artifact(artifact_id)
        return status, raw + b'\n', header
    result = state.run(io=state.io(read_artifact=artifact))
    assert result.summary['reason'] == 'REVIEW_ARTIFACT_DIGEST_MISMATCH'
    assert result.reviewer_artifact_bytes.endswith(b'\n') and result.review_bytes is None


@pytest.mark.parametrize('mutation', [lambda content: content.update(review_nonce=CORRELATION),
    lambda content: content['subject_domain_join'].update(objective_id=CORRELATION),
    lambda content: content['subject_domain_join'].update(execution_metadata_sha256='b' * 64),
    lambda content: content['subject_domain_join'].update(prompt_sha256='b' * 64),
    lambda content: content.update(test_result='FAIL')])
def test_review_contents_must_join_exact_observed_domains_not_merely_self_hash(mutation):
    state = SyntheticOperator()
    def reviewer(request):
        status, body = state.dispatch_review(request)
        content = json.loads(state.proof['raw'])
        mutation(content)
        state.proof['raw'] = json.dumps(content).encode()
        digest = sha(state.proof['raw'])
        state.proof['dispatch']['artifact'].update(sha256=digest, bytes=len(state.proof['raw']))
        body['artifact'].update(sha256=digest, bytes=len(state.proof['raw']))
        end = json.loads(state.proof['actions'][1])
        end['result_summary']['sha256'] = digest
        end['sha256'] = sha(canonical({k: v for k, v in end.items() if k != 'sha256'}))
        state.proof['actions'][1] = json.dumps(end)
        return status, body
    result = state.run(io=state.io(dispatch_reviewer=reviewer))
    assert result.summary['state'] == 'REJECTED' and result.reviewer_artifact_bytes is not None
    assert result.review_bytes is None


@pytest.mark.parametrize('events', [[], ['{}'], ['{}', '{}'], None])
def test_missing_or_malformed_actual_durable_actions(events):
    state = SyntheticOperator()
    result = state.run(io=state.io(read_review_actions=lambda action_id: events))
    assert result.summary['state'] == 'REJECTED' and result.review_bytes is None


@pytest.mark.parametrize('mutation', [lambda end: end.update(sequence=13),
    lambda end: end.update(previous_sha256='0' * 64), lambda end: end.update(success=1),
    lambda end: end.update(agent_id='a18'), lambda end: end.update(action_id=CORRELATION)])
def test_rehashed_but_unjoined_action_chain_rejects(mutation):
    state = SyntheticOperator()
    def actions(action_id):
        events = state.actions(action_id)
        end = json.loads(events[1])
        mutation(end)
        end['sha256'] = sha(canonical({key: value for key, value in end.items() if key != 'sha256'}))
        return [events[0], json.dumps(end)]
    result = state.run(io=state.io(read_review_actions=actions))
    assert result.summary['state'] == 'REJECTED' and result.review_bytes is None


def test_unchanged_queue_and_objective_are_rechecked_after_review():
    state = SyntheticOperator()
    reads = 0
    def job_reader(job_id):
        nonlocal reads
        reads += 1
        return 200, dict(state.job, result='changed') if reads > 1 else deepcopy(state.job)
    result = state.run(io=state.io(read_job=job_reader))
    assert result.summary['reason'] == 'COMPLETED_QUEUE_CHANGED'
    assert result.reviewer_artifact_bytes is not None and result.review_bytes is None


def test_queue_timeout_preserves_known_identity_and_never_replays_or_reviews():
    state = SyntheticOperator()
    def pending(job_id):
        return 200, dict(state.job, status='queued', provider=None)
    result = state.run(io=state.io(read_job=pending), timeout_seconds=0.5, poll_seconds=0.25)
    assert result.summary['reason'] == 'BOUNDED_OBSERVATION_INCOMPLETE'
    assert result.summary['job_id'] == JOB and result.summary['submission_uncertain'] is False
    assert state.calls.count('submit') == 1 and 'review' not in state.calls


def test_nonadvancing_clock_has_finite_read_bound():
    state = SyntheticOperator()
    reads = 0
    def pending(job_id):
        nonlocal reads
        reads += 1
        return 200, dict(state.job, status='queued', provider=None)
    result = collect_role_case(state.spec, io=state.io(read_job=pending),
        expected_source_revision=SOURCE, expected_runtime_image=IMAGE, reviewer_code_revision=CODE,
        review_run_id='synthetic-clock', timeout_seconds=0.01, poll_seconds=0.01,
        monotonic=lambda: 0, pause=lambda _: None, wall_clock=lambda: NOW)
    assert result.summary['state'] == 'REJECTED' and reads == 2
    assert state.calls.count('submit') == 1


def test_no_credentials_environment_or_network_defaults_in_interface():
    assert OperatorIO.__dataclass_fields__['authorize'].default.__class__.__name__ == '_MISSING_TYPE'
    assert isinstance(SyntheticOperator().run(), CollectedCase)
    assert review_zero_boundary_json(json.dumps(ANSWER))[0] is True


@pytest.mark.parametrize('kind', [CollectionError, RuntimeError])
def test_injected_exception_class_cannot_turn_private_text_into_diagnostics(kind):
    state = SyntheticOperator()
    def secret_callback():
        raise kind('PRIVATE_CALLBACK_TOKEN_TEXT')
    result = state.run(io=state.io(authorize=secret_callback))
    assert result.summary['reason'] == 'OPERATOR_CALLBACK_FAILED'
    assert 'PRIVATE_CALLBACK_TOKEN_TEXT' not in repr(result)


@pytest.mark.parametrize('target', ['subject', 'review'])
def test_final_pre_mutation_metadata_callback_consumes_deadline_no_late_mutation(target):
    state = SyntheticOperator(cloud=True)
    reads = 0
    # Call 2 is the final subject precheck; call 4 is the final reviewer precheck.
    expire_at = 2 if target == 'subject' else 4
    def entry(provider_id):
        nonlocal reads
        reads += 1
        if reads == expire_at:
            state.ticks = 36
        return deepcopy(state.entry)
    result = state.run(io=state.io(read_provider_entry=entry))
    assert result.summary['reason'] == 'BOUNDED_OBSERVATION_INCOMPLETE'
    assert state.calls.count('submit') == (0 if target == 'subject' else 1)
    assert state.calls.count('review') == 0


def test_invalid_pin_not_returned_in_public_summary():
    state = SyntheticOperator()
    result = collect_role_case(state.spec, io=state.io(),
        expected_source_revision='accidental-private-input', expected_runtime_image='private-image-input',
        reviewer_code_revision=CODE, review_run_id='synthetic-pin')
    assert result.summary['source_revision'] is None and result.summary['runtime_image_id'] is None
    assert 'private-input' not in repr(result) and state.calls == []


@pytest.mark.parametrize('interleaved,expected', [(16, 'UNSIGNED_CASE_EVIDENCE'), (25, 'REJECTED')])
def test_original_interleaved_action_lines_respect_existing_signer_envelope_bound(interleaved, expected):
    state = SyntheticOperator()
    def actions(action_id):
        raw = state.actions(action_id)
        start, end = map(json.loads, raw)
        events = [start]
        for index in range(interleaved):
            event = {'action_id': CORRELATION, 'sequence': start['sequence'] + index + 1,
                'previous_sha256': events[-1]['sha256'], 'public_synthetic_padding': 'x' * 45_000}
            event['sha256'] = sha(canonical(event))
            events.append(event)
        end['sequence'] = events[-1]['sequence'] + 1
        end['previous_sha256'] = events[-1]['sha256']
        end['sha256'] = sha(canonical({key: value for key, value in end.items() if key != 'sha256'}))
        events.append(end)
        return [json.dumps(event) for event in events]
    result = state.run(io=state.io(read_review_actions=actions))
    assert result.summary['state'] == expected
    assert result.action_records and result.reviewer_artifact_bytes == state.proof['raw']
    assert len(result.action_records) == interleaved + 2
    if expected == 'REJECTED':
        assert result.summary['reason'] == 'REVIEW_ENVELOPE_EXCEEDS_SIGNER_BOUND'
        assert len(result.review_bytes) > 1024 * 1024
        assert result.summary['certification'] == 'UNVERIFIED'
    else:
        assert len(result.review_bytes) < 1024 * 1024
