"""Temporary SQLite/queue fixtures; not live reviewer or certification evidence."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import agent_dispatch_api as dispatch
from app.action_records import ActionLedger
from app.artifact_factory import ArtifactFactory
from app.agent_cert_role_group_two import _CASES
from app.agent_cert_role_review import canonical_role_spec
from app.tier_router import Tier


SOURCE = 'd' * 40
IMAGE = 'sha256:' + 'e' * 64
JOB = '11111111-1111-4111-8111-111111111111'
OBJECTIVE = '22222222-2222-4222-8222-222222222222'
NONCE = '33333333-3333-4333-8333-333333333333'
CORRELATION = '44444444-4444-4444-8444-444444444444'
compute_queue_api = objective_api = None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def bind_mock_inference_request(job, original):
    """Represent the new structural metadata in this explicit source fixture."""
    from app.direct_stream import inference_request
    from app.compute_profile import generation_options
    job['response_format'] = original.response_format
    job['response_schema'] = json.dumps(original.response_schema)
    _, _, receipt = inference_request(job, SimpleNamespace(model=job['model']),
                                     settings=dispatch.SETTINGS, options=generation_options)
    job['inference_receipt'] = json.dumps(receipt)


@pytest.fixture
def configured(tmp_path, monkeypatch):
    global compute_queue_api, objective_api
    monkeypatch.setenv('PRIME_REGISTRY_V1_ENABLED', '1')
    monkeypatch.setenv('PRIME_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(tmp_path / 'fixture-queue.db'))
    monkeypatch.setenv('PRIME_RUNTIME_REVISION', SOURCE)
    monkeypatch.setenv('PRIME_RUNTIME_IMAGE_DIGEST', IMAGE)
    monkeypatch.setenv('PRIME_INTERFACE_HOST_ID', 'ABEX')
    monkeypatch.setenv('PRIME_INTERFACE_RUNTIME_VERSION', 'fixture-v1')
    monkeypatch.delenv('PRIME_CONTEXT_PACKS_ENABLED', raising=False)
    monkeypatch.delenv('PRIME_SKILL_PACKS_ENABLED', raising=False)
    # Queue construction is an import side effect. Import only after this
    # fixture owns an explicit temporary data/queue path, never /data at
    # collection time on an unprivileged off-host runner.
    from app import compute_queue_api, objective_api
    calls = []
    def authenticate(value):
        calls.append(value)
        if value != 'fixture-owner':
            raise HTTPException(401, 'Owner authentication required')
    monkeypatch.setattr(dispatch, 'authenticate_owner', authenticate)
    monkeypatch.setattr(objective_api, 'authenticate_owner', authenticate)
    now = datetime.now(timezone.utc)
    result = json.dumps(_CASES['a19'][2])
    job = dict(id=JOB, agent='a19', status='completed', result=result,
               provider='ollama-deep', attempts=1, error=None,
               model='fixture-model', allow_cloud=0, data_classification='LOCAL_ONLY',
               classification='R0', task_class='planning', max_retries=0,
               created_at=(now - timedelta(seconds=3)).isoformat(),
               started_at=(now - timedelta(seconds=2)).isoformat(),
               completed_at=(now - timedelta(seconds=1)).isoformat())
    original = dispatch.AgentRequest(**canonical_role_spec('a19', 'responsibility.a19')['request'])
    job['prompt'] = dispatch.packed_inference_prompt(original, Tier.MINI, 'a19', CORRELATION)
    bind_mock_inference_request(job, original)
    monkeypatch.setattr(compute_queue_api, 'providers', lambda: [
        SimpleNamespace(name='ollama-deep', kind='local', model='fixture-model')])
    def get_job(key):
        if key != JOB:
            raise KeyError(key)
        return copy.deepcopy(job)
    monkeypatch.setattr(compute_queue_api, 'queue', SimpleNamespace(get=get_job))
    execution = dict(schema_version='prime.agent-certification.execution.v1',
        agent_id='a19', capability_id='responsibility.a19', dimension='role',
        test_case='normal', source_revision=SOURCE, runtime_image_id=IMAGE,
        environment='LIVE_RUNTIME', executor_identity='a19',
        case_spec=canonical_role_spec('a19', 'responsibility.a19'),
        dispatch={'capability': 'responsibility.a19', 'job': {'id': JOB, 'agent': 'a19'}},
        job={**{key: job[key] for key in ('id', 'agent', 'status', 'result', 'provider',
                'attempts', 'error', 'started_at', 'completed_at')},
             'result_sha256': digest(result.encode())},
        transport=dict(authentication='OWNER_AUTHENTICATED', dispatch_http_status=202,
                       job_http_status=200, provider_locality='LOCAL',
                       runtime_source_revision=SOURCE, actual_runtime_image=IMAGE))
    payload = dict(execution=execution, expected_execution_sha256=digest(canonical(execution)),
                   expected_source_revision=SOURCE, review_nonce=NONCE,
                   subject_objective_id=OBJECTIVE)
    db = objective_api.connect()
    db.execute('INSERT INTO objectives VALUES(?,?,?,?)', (OBJECTIVE, '0' * 64, 'submitted',
        json.dumps([{'capability': 'responsibility.a19',
                     'dispatch': {'job': {'id': JOB, 'agent': 'a19'},
                                  'correlation_id': CORRELATION}}])))
    db.execute('INSERT INTO objective_metadata VALUES(?,?,?,?)',
               (OBJECTIVE, 0, job['created_at'], job['completed_at']))
    objective_api.store_runtime(db, OBJECTIVE, 0)
    db.commit()
    db.close()
    ledger = ActionLedger(tmp_path / 'review-actions.jsonl')
    monkeypatch.setattr(dispatch, 'action_ledger', lambda: ledger)
    value = SimpleNamespace(root=tmp_path, job=job, payload=payload, ledger=ledger, calls=calls)
    yield value
    ledger.close()


def request(value, **changes):
    return dispatch.AgentRequest(capability='responsibility.a26',
        objective=dispatch.ROLE_REVIEW_OBJECTIVE, context=canonical(value.payload).decode(),
        priority='low', deterministic_operation='certification_role_review', **changes)


def run(value):
    return dispatch.dispatch_request(request(value), 'fixture-owner')


def change_database(statement, params=()):
    db = objective_api.connect()
    db.execute(statement, params)
    db.commit()
    db.close()


def reject(value):
    with pytest.raises(HTTPException) as failure:
        run(value)
    assert failure.value.status_code == 422
    assert not (value.root / 'artifacts').exists()
    assert not (value.root / 'review-actions.jsonl').exists()
    assert not (value.root / 'compute-ledger.db').exists()


def test_review_joins_owned_sqlite_runtime_queue_and_durable_action(configured):
    before = digest((configured.root / 'objectives.db').read_bytes())
    result = run(configured)
    assert set(result) == {'task_id', 'state', 'artifact', 'model_calls', 'execution_model',
                          'agent_id', 'capability', 'runtime_source_revision',
                          'review_action_id', 'review_action_durable', 'certification'}
    assert result['state'] == 'COMPLETED' and result['agent_id'] == 'a26'
    assert result['model_calls'] == 0 and result['review_action_durable'] is True
    assert result['certification'] == 'UNVERIFIED'
    metadata, raw = ArtifactFactory(configured.root / 'artifacts').retrieve(result['artifact']['artifact_id'])
    review = json.loads(raw)
    assert metadata == result['artifact']
    assert metadata['creator_agents'] == ['a26'] and metadata['runtime_revision'] == SOURCE
    assert review['task_id'] == metadata['task_id'] == result['task_id']
    assert review['test_result'] == 'PASS' and review['review_errors'] == []
    assert review['subject_execution_verification'] == 'QUEUE_AND_OBJECTIVE_JOINED'
    assert review['subject_domain_join']['objective_id'] == OBJECTIVE
    assert review['subject_domain_join']['objective_revision'] == 0
    assert review['subject_domain_join']['runtime'] == objective_api.runtime_snapshot()
    assert len(review['subject_domain_join']['execution_metadata_sha256']) == 64
    assert review['subject_domain_join']['prompt_sha256'] == digest(configured.job['prompt'].encode())
    assert review['subject_domain_join']['case_spec_sha256'] == digest(canonical(configured.payload['execution']['case_spec']))
    assert digest((configured.root / 'objectives.db').read_bytes()) == before
    actions = [json.loads(line) for line in configured.ledger.path.read_text().splitlines()]
    assert [row['phase'] for row in actions] == ['started', 'completed']
    assert all(row['action_id'] == result['review_action_id'] for row in actions)
    assert all(row['agent_id'] == 'a26' and row['action_type'] == 'agent.certification.role.review'
               and row['task_id'] == result['task_id'] for row in actions)
    assert actions[-1]['success'] is True
    assert actions[-1]['result_summary']['sha256'] == digest(raw)
    for row in actions:
        claimed = row.pop('sha256')
        assert claimed == digest(canonical(row))
    # Initial dispatch + two authenticated reads of the owned subject state.
    assert configured.calls == ['fixture-owner', 'fixture-owner', 'fixture-owner']


@pytest.mark.parametrize('field,value', [('result', '{"continuous_health_proven":true}'),
    ('agent', 'a18'), ('status', 'running'), ('provider', 'another'), ('attempts', 2),
    ('completed_at', '2026-10-07T00:00:00Z'), ('error', 'PRIVATE_SYNTHETIC_ERROR')])
def test_submitted_job_must_match_actual_current_queue(configured, field, value):
    configured.job[field] = value
    reject(configured)


@pytest.mark.parametrize('field,value', [('source_revision', 'f' * 40),
    ('image_digest', 'sha256:' + 'f' * 64), ('host_id', 'OTHER'), ('version', 'old')])
def test_objective_runtime_cannot_be_replaced_by_current_request_claim(configured, field, value):
    change_database(f'UPDATE objective_runtime SET {field}=? WHERE task=?', (value, OBJECTIVE))
    reject(configured)


def test_missing_immutable_objective_runtime_fails_closed(configured):
    change_database('DELETE FROM objective_runtime WHERE task=?', (OBJECTIVE,))
    reject(configured)


@pytest.mark.parametrize('field,value', [('prompt', 'Unrelated work with a coincidentally correct answer'),
    ('classification', 'R1'), ('task_class', 'classification'), ('max_retries', 1),
    ('max_retries', False), ('allow_cloud', True), ('allow_cloud', 1),
    ('data_classification', 'CLOUD_PERMITTED'), ('model', 'unrelated-model')])
def test_actual_prompt_and_execution_locality_cannot_be_relabelled(configured, field, value):
    configured.job[field] = value
    reject(configured)


def test_missing_correlation_cannot_reconstruct_an_original_dispatch(configured):
    change_database('UPDATE objectives SET steps_json=? WHERE id=?',
        (json.dumps([{'capability': 'responsibility.a19',
                     'dispatch': {'job': {'id': JOB, 'agent': 'a19'}}}]), OBJECTIVE))
    reject(configured)


@pytest.mark.parametrize('context_on,skills_on', [(True, False), (False, True), (True, True)])
def test_existing_opt_in_context_and_skill_prefixes_are_reconstructed(configured, monkeypatch, context_on, skills_on):
    from app.skill_router import select_skill_pack
    monkeypatch.setenv('PRIME_CONTEXT_PACKS_ENABLED', '1' if context_on else '0')
    monkeypatch.setenv('PRIME_SKILL_PACKS_ENABLED', '1' if skills_on else '0')
    original = dispatch.AgentRequest(**canonical_role_spec('a19', 'responsibility.a19')['request'])
    skills = select_skill_pack('a19', original.task_class, Tier.MINI) if skills_on else None
    configured.job['prompt'] = dispatch.packed_inference_prompt(original, Tier.MINI, 'a19', CORRELATION, skills)
    bind_mock_inference_request(configured.job, original)
    result = run(configured)
    assert result['review_action_durable'] is True and result['certification'] == 'UNVERIFIED'


def cloud_fixture(value, monkeypatch):
    from app.agent_cert_transport import (bind_cloud_case, case_transport_identity,
        canonical_role_case, transport_digest, POLICY_SCHEMA, PROVIDER_ID, MODEL)
    spec = canonical_role_case('a19', 'responsibility.a19')
    policy = dict(schema=POLICY_SCHEMA, policy_version='fixture-v1',
        owner_authorization_ref='synthetic-owner-approval-fixture', source_revision=SOURCE,
        **case_transport_identity(spec), data_classification='CLOUD_PERMITTED', public_synthetic=True,
        provider_id=PROVIDER_ID, provider_kind='huggingface', model=MODEL,
        minimum_tier='MINI', max_cost_usd=0.002, context_tokens=4096, output_tokens=1024,
        timeout_seconds=35, max_retries=0, concurrency_limit=1)
    binding = bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
                              expected_policy_sha256=transport_digest(policy))
    value.job.update(provider=PROVIDER_ID, preferred_provider=PROVIDER_ID, model=MODEL,
        allow_cloud=1, data_classification='CLOUD_PERMITTED', max_cost_usd=0.002,
        input_tokens=150, output_tokens=90, actual_cost_usd=0.0000372)
    value.payload['execution']['job']['provider'] = PROVIDER_ID
    value.payload['execution']['transport']['provider_locality'] = 'CLOUD'
    route = {key: value.job[key] for key in ('preferred_provider', 'model', 'allow_cloud',
        'data_classification', 'task_class', 'classification', 'max_retries', 'max_cost_usd',
        'input_tokens', 'output_tokens', 'actual_cost_usd')}
    route['prompt_sha256'] = digest(value.job['prompt'].encode())
    value.payload['execution']['cloud_transport'] = {'binding': binding.receipt(), 'queue_route': route}
    value.payload['expected_execution_sha256'] = digest(canonical(value.payload['execution']))
    monkeypatch.setattr(compute_queue_api, 'providers', lambda: [
        SimpleNamespace(name=PROVIDER_ID, kind='cloud', model=MODEL)])


def test_cloud_review_joins_completed_queue_without_claiming_owner_policy_authority(configured, monkeypatch):
    cloud_fixture(configured, monkeypatch)
    result = run(configured)
    _, raw = ArtifactFactory(configured.root / 'artifacts').retrieve(result['artifact']['artifact_id'])
    assert json.loads(raw)['test_result'] == 'PASS'
    assert json.loads(raw)['subject_execution_verification'] == 'QUEUE_AND_OBJECTIVE_JOINED'
    assert result['model_calls'] == 0 and result['certification'] == 'UNVERIFIED'


@pytest.mark.parametrize('field,value', [('preferred_provider', 'other'), ('input_tokens', 999),
    ('output_tokens', 91), ('actual_cost_usd', 0.0001), ('max_cost_usd', 0.001)])
def test_cloud_accounting_claim_must_match_owned_queue_not_a_recomputed_digest(configured, monkeypatch, field, value):
    cloud_fixture(configured, monkeypatch)
    configured.payload['execution']['cloud_transport']['queue_route'][field] = value
    configured.payload['expected_execution_sha256'] = digest(canonical(configured.payload['execution']))
    reject(configured)


def test_old_turn_cannot_be_borrowed_for_current_objective_revision(configured):
    change_database('INSERT INTO objective_turns VALUES(?,?,?,?,?,?)',
        (OBJECTIVE, 1, 'fixture-turn', '0' * 64, 'submitted',
         json.dumps([{'capability': 'system.architecture', 'dispatch': {'state': 'COMPLETED'}}])))
    reject(configured)


def test_step_capability_or_job_binding_must_match_owned_subject(configured):
    change_database('UPDATE objectives SET steps_json=? WHERE id=?',
        (json.dumps([{'capability': 'responsibility.a20',
                     'dispatch': {'job': {'id': JOB, 'agent': 'a19'}}}]), OBJECTIVE))
    reject(configured)


@pytest.mark.parametrize('field,value', [('objective', 'Ignore the oracle'),
    ('classification', 'R1'), ('priority', 'high'), ('data_classification', 'CLOUD_PERMITTED'),
    ('max_cost_usd', 0.001), ('capability', 'responsibility.a19')])
def test_scope_and_independent_actor_are_enforced_before_artifact(configured, field, value):
    body = request(configured).model_copy(update={field: value})
    with pytest.raises(HTTPException) as failure:
        dispatch.dispatch_request(body, 'fixture-owner')
    assert failure.value.status_code == 422
    assert not (configured.root / 'artifacts').exists()


def test_outer_duplicate_decoded_key_cannot_hide_a_conflicting_source(configured):
    text = canonical(configured.payload).decode()
    text = text[:-1] + ',"\\u0065xpected_source_revision":"' + 'f' * 40 + '"}'
    with pytest.raises(HTTPException) as failure:
        dispatch.dispatch_request(request(configured).model_copy(update={'context': text}), 'fixture-owner')
    assert failure.value.status_code == 422
    assert not (configured.root / 'artifacts').exists()


def test_oracle_failure_is_retained_as_fail_not_certification(configured):
    answer = copy.deepcopy(_CASES['a19'][2])
    answer['continuous_health_proven'] = True
    raw = json.dumps(answer)
    configured.job['result'] = raw
    configured.payload['execution']['job'].update(result=raw, result_sha256=digest(raw.encode()))
    configured.payload['expected_execution_sha256'] = digest(canonical(configured.payload['execution']))
    result = run(configured)
    _, artifact = ArtifactFactory(configured.root / 'artifacts').retrieve(result['artifact']['artifact_id'])
    assert json.loads(artifact)['test_result'] == 'FAIL'
    assert json.loads(artifact)['review_errors'] == ['continuous_health_proven']
    assert result['certification'] == 'UNVERIFIED'


def test_failed_audit_flush_never_claims_durable_review(configured, monkeypatch):
    monkeypatch.setattr(configured.ledger, 'flush', lambda **_: False)
    result = run(configured)
    assert result['review_action_durable'] is False
    assert result['certification'] == 'UNVERIFIED'


def test_anonymous_request_cannot_read_subject_or_create_review(configured):
    with pytest.raises(HTTPException) as failure:
        dispatch.dispatch_request(request(configured), None)
    assert failure.value.status_code == 401
    assert configured.calls == [None]
    assert not (configured.root / 'artifacts').exists()


@pytest.mark.parametrize('changed_domain', [
    'objective_revision', 'runtime', 'queue_result', 'queue_prompt', 'queue_cost',
    'provider_model',
])
def test_subject_change_during_oracle_cannot_create_stale_review(configured, monkeypatch, changed_domain):
    """A real oracle callback may not turn an earlier snapshot into current proof.

    All state here belongs to temporary SQLite/queue fixtures; this is a source
    regression, not an actual agent execution or certification event.
    """
    from app import agent_cert_review_tool
    original = agent_cert_review_tool.execute_role_review

    def review_then_change(*args, **kwargs):
        answer = original(*args, **kwargs)
        if changed_domain == 'objective_revision':
            change_database('INSERT INTO objective_turns VALUES(?,?,?,?,?,?)',
                (OBJECTIVE, 1, 'during-review', '0' * 64, 'dispatching', '[]'))
        elif changed_domain == 'runtime':
            monkeypatch.setenv('PRIME_RUNTIME_IMAGE_DIGEST', 'sha256:' + 'f' * 64)
        elif changed_domain == 'queue_result':
            configured.job['result'] = 'a different result after review began'
        elif changed_domain == 'queue_prompt':
            configured.job['prompt'] = 'a different objective after review began'
        elif changed_domain == 'queue_cost':
            configured.job['actual_cost_usd'] = 0.5
        else:
            monkeypatch.setattr(compute_queue_api, 'providers', lambda: [
                SimpleNamespace(name='ollama-deep', kind='local', model='different-model')])
        return answer

    monkeypatch.setattr(agent_cert_review_tool, 'execute_role_review', review_then_change)
    reject(configured)


def test_final_owned_objective_read_must_succeed_before_review_artifact(configured, monkeypatch):
    original = objective_api.get_read_only
    calls = []
    def read_once(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise KeyError('synthetic lost owned state')
        return original(*args, **kwargs)
    monkeypatch.setattr(objective_api, 'get_read_only', read_once)
    reject(configured)
