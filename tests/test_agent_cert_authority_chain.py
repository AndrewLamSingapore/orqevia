"""Actual temporary HTTP/domain chain; no network, live signing or L7 proof."""
import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import agent_cert_authority_events as events
from app import agent_cert_event_api as api
from app import agent_cert_role_review as contracts
from app import agent_dispatch_api as dispatch
from scripts.agent_cert_operator_io import AgentCertOperatorIO
from scripts.collect_agent_cert_event import collect_event_case
from scripts.agent_cert_reviewed_signing import CertificationReviewError, _review
from scripts.sign_admitted_agent_cases import parse as parse_admission
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE, NONCE
from tests.test_agent_cert_operator_io import FakeResponse, FakeTimer, FakeTransport, TOKEN

CODE = 'f' * 40


@pytest.fixture
def runtime(configured, monkeypatch):
    from app import artifact_delivery, client_auth, compute_queue_api, objective_api
    from app.action_records import ActionLedger
    from app.spine import SpineStore
    monkeypatch.setenv('PRIME_SPINE_DB', str(configured.root / 'prime-spine.db'))
    SpineStore(str(configured.root / 'prime-spine.db'))
    monkeypatch.setenv('PRIME_SPINE_TOKEN', TOKEN)
    for module in (dispatch, objective_api, api, artifact_delivery):
        monkeypatch.setattr(module, 'authenticate_owner', client_auth.authenticate_owner)
    compute_queue_api.queue.policy = SimpleNamespace(global_concurrency=1)
    monkeypatch.setattr(compute_queue_api, 'providers', lambda: pytest.fail('No model/provider selection'))
    ledger = ActionLedger(configured.root / 'action-records.jsonl')
    monkeypatch.setattr(dispatch, 'action_ledger', lambda: ledger)
    app = FastAPI()  # No production lifespan, worker, server or socket.
    for router in (objective_api.router, dispatch.router, api.router, artifact_delivery.router):
        app.include_router(router)
    client = TestClient(app)
    requests = []
    def response(method, path, body):
        requests.append((method, path))
        reply = client.request(method, path, content=body,
            headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'})
        headers = {'Content-Type': reply.headers.get('content-type', ''),
            'Content-Length': str(len(reply.content))}
        if 'x-artifact-sha256' in reply.headers:
            headers['X-Artifact-SHA256'] = reply.headers['x-artifact-sha256']
        response = FakeResponse(reply.status_code, reply.content, headers)
        response.length = len(reply.content)
        original_read = response.read1
        def read(count):
            chunk = original_read(count)
            response.length -= len(chunk)
            return chunk
        response.read1 = read
        return response
    value = SimpleNamespace(root=configured.root, ledger=ledger, client=client,
        transport=FakeTransport(response), requests=requests)
    from app.agent_registry import REGISTRY_PATH
    value.registry_sha = events.sha(REGISTRY_PATH.read_bytes())
    yield value
    client.close()
    assert ledger.close()


def collect(runtime, case_id=events.SUPPORTED_CASES[0], **changes):
    spec = events.canonical_authority_case(case_id)
    operator = AgentCertOperatorIO(owner_token=TOKEN, spec=spec,
        expected_source_revision=SOURCE, expected_runtime_image=IMAGE,
        connection_factory=runtime.transport, timer_factory=FakeTimer,
        # Fake responses/timers model no network elapsed time. Deadline behavior
        # belongs to the dedicated operator transport tests, not CI host speed.
        total_timeout_seconds=30, monotonic=lambda: 0.0)
    options = dict(io=operator.io(), read_subject_actions=operator.read_subject_actions,
        expected_source_revision=SOURCE, expected_runtime_image=IMAGE,
        expected_registry_sha256=runtime.registry_sha, reviewer_code_revision=CODE,
        review_run_id='temporary-http-authority-review', timeout_seconds=30,
        nonce_factory=lambda: NONCE)
    options.update(changes)
    result = collect_event_case(spec, **options)
    runtime.operator, runtime.collected = operator, result
    return result


def signer_row(result):
    review = json.loads(result.review_bytes)
    now = datetime.now(timezone.utc)
    return dict(agent_id='a19', capability_id='responsibility.a19',
        dimension=review['dimension'], test_case=review['test_case'],
        certification_test='authority-source-chain', test_version=events.CASE_VERSION,
        test_result='PASS', verifier='a26', executor_identity='a19',
        source_revision=SOURCE, review_source_revision=SOURCE, reviewer_code_revision=CODE,
        authority_scope='advisory', review_test_version=events.ORACLE_ID,
        review_run_id=review['review_run_id'], certified_at=now.isoformat(),
        last_revalidated=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat())


def recompute(row, primary, review, **changes):
    pins = dict(source_revision=SOURCE, runtime_image_id=IMAGE,
        reviewer_code_revision=CODE, now=datetime.now(timezone.utc))
    pins.update(changes)
    return _review(row, primary, review, **pins)  # Pure checks, no signer callback/key.


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_authenticated_http_original_domains_separate_a26_review_and_pure_signer(runtime, case_id):
    result = collect(runtime, case_id)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    assert result.summary['subject_task_id'] != result.summary['review_task_id']
    assert result.summary['model_calls'] == 0 and result.summary['signature'] == 'NOT_PERFORMED'
    assert result.summary['certification'] == 'UNVERIFIED'
    assert [method for method, _ in runtime.requests].count('POST') == 2
    execution, review = json.loads(result.execution_bytes), json.loads(result.review_bytes)
    assert execution['dispatch']['authority_event']['case'] == case_id
    assert set(execution['observation']) == {'started_at', 'completed_at'}
    assert execution['runtime'] == execution['runtime_after'] == execution['runtime_current']
    assert execution['objective_read'][1]['execution_metadata']['jobs'] == []
    assert execution['objective_read'][1]['execution_metadata']['agent_execution'] == []
    assert len(result.subject_actions) == len(result.reviewer_actions) == 2
    assert result.input_artifact_bytes is None and result.input_actions == ()
    content = json.loads(result.reviewer_artifact_bytes)
    assert content['schema_version'] == contracts.AUTHORITY_REVIEW_SCHEMA
    assert content['dimension'] == review['dimension'] == case_id.split(':')[0]
    assert content['subject_domain_join']['consequential_guard_denial_proven'] is (case_id == events.DENIAL_CASE)
    assert content['subject_domain_join']['completed_at'] == execution['dispatch']['authority_event']['completed_at']
    assert recompute(signer_row(result), result.execution_bytes, result.review_bytes) is True
    assert all(reply.body_complete for reply in runtime.operator.original_replies())


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_exact_cases_do_not_accept_model_answers_or_borrowed_capabilities(case_id):
    spec = contracts.canonical_case_spec('a19', 'responsibility.a19', case_id)
    assert spec == events.canonical_authority_case(case_id)
    assert contracts.review_case_output('a19', 'responsibility.a19', case_id, '{"PASS":true}') == (
        False, ('authority_event_evidence_required',))
    for agent, capability in (('a26', 'responsibility.a26'), ('a19', 'responsibility.a26')):
        with pytest.raises(ValueError): contracts.canonical_case_spec(agent, capability, case_id)


@pytest.mark.parametrize('case_id', events.UNREADY_CASES)
def test_original_authority_route_rejects_separately_implemented_owner_case(runtime, case_id):
    from app import agent_cert_owner_referral_events as owner_events
    assert case_id == owner_events.CASE
    assert contracts.canonical_case_spec('a19', 'responsibility.a19', case_id) == owner_events.canonical_owner_case()
    with pytest.raises(ValueError): events.canonical_authority_case(case_id)
    reply = runtime.client.get('/api/agent-cert-events/actions/' + NONCE,
        params={'action_type': 'agent.certification.authority.' + case_id.split(':')[1]},
        headers={'Authorization': 'Bearer ' + TOKEN})
    assert reply.status_code == 422
    assert runtime.ledger.status()['persisted'] == 0


def test_actual_owner_auth_precedes_producer_or_action_domain_reads(runtime, monkeypatch):
    monkeypatch.setattr(events, 'execute_authority_case', lambda *a, **k: pytest.fail('Unauthorized producer'))
    monkeypatch.setattr(api, 'read_authority_action_span', lambda *a, **k: pytest.fail('Unauthorized domain read'))
    for headers in ({}, {'Authorization': 'Bearer not-the-owner'}):
        assert runtime.client.post('/api/agents/objectives',
            json=events.canonical_authority_case(events.SUPPORTED_CASES[0])['request'], headers=headers).status_code == 401
        assert runtime.client.get('/api/agent-cert-events/actions/' + NONCE,
            params={'action_type': events.authority_action_type(events.SUPPORTED_CASES[0])}, headers=headers).status_code == 401
    assert runtime.ledger.status()['persisted'] == 0


@pytest.mark.parametrize('defect', ['source', 'image', 'case', 'owner', 'model_boolean',
    'subject_actions', 'result_bytes', 'registry', 'missing_review', 'self_review',
    'review_join', 'review_boolean', 'review_not_durable', 'stale', 'model_substitution'])
def test_pure_signer_rejects_rehashed_binding_tamper(runtime, defect):
    result = collect(runtime)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    row = signer_row(result)
    execution, review = json.loads(result.execution_bytes), json.loads(result.review_bytes)
    if defect == 'source': row['source_revision'] = 'c' * 40
    elif defect == 'image': execution['runtime_current']['image_digest'] = 'sha256:' + 'c' * 64
    elif defect == 'case': row['dimension'], row['test_case'] = 'unauthorized_rejection', 'authorized'
    elif defect == 'owner': execution['objective_read'][1]['id'] = NONCE
    elif defect == 'model_boolean': execution['dispatch']['model_calls'] = False
    elif defect == 'subject_actions': execution['action_records'] = []
    elif defect == 'result_bytes': execution['artifact_content_utf8'] += ' '
    elif defect == 'registry': execution['dispatch']['authority_event']['registry_sha256'] = 'c' * 64
    elif defect == 'missing_review': review['observations'].pop('reviewer_execution')
    elif defect == 'self_review': row['verifier'] = 'a19'
    elif defect == 'review_join': review['observations']['reviewer_execution']['artifact_content_utf8'] = '{}'
    elif defect == 'review_boolean': review['observations']['reviewer_execution']['dispatch']['model_calls'] = False
    elif defect == 'review_not_durable': review['observations']['reviewer_execution']['dispatch']['review_action_durable'] = False
    elif defect == 'stale':
        # Protected verification may be later; the original registered review
        # itself must still consume the event within the owning 300-second bound.
        proof = review['observations']['reviewer_execution']
        content = json.loads(proof['artifact_content_utf8'])
        content['reviewed_at'] = (events._utc(execution['dispatch']['authority_event']['completed_at'])
            + timedelta(seconds=301)).isoformat()
        proof['artifact_content_utf8'] = events.canonical(content).decode()
        with pytest.raises(events.AuthorityEventError, match='AUTHORITY_EVENT_STALE_OR_UNBOUNDED'):
            recompute(row, result.execution_bytes, events.canonical(review),
                now=datetime.now(timezone.utc) + timedelta(minutes=6))
        return
    elif defect == 'model_substitution': execution['job'] = {'result': '{"PASS":true}'}
    primary = events.canonical(execution)
    review['execution_evidence_sha256'] = events.sha(primary)
    with pytest.raises((CertificationReviewError, events.AuthorityEventError)):
        recompute(row, primary, events.canonical(review))


@pytest.mark.parametrize('field,value', [('minimum_tier', 'MINI'), ('task_class', 'planning'),
    ('response_format', 'text'), ('capability', 'responsibility.a19')])
def test_review_policy_rejected_without_new_artifact_or_actions(runtime, field, value):
    result = collect(runtime)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    request = json.loads(next(body for method, path, body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/dispatch'))
    request[field] = value
    before = runtime.ledger.status()['persisted'], set((runtime.root / 'artifacts').iterdir())
    reply = runtime.client.post('/api/agents/dispatch', json=request, headers={'Authorization': 'Bearer ' + TOKEN})
    assert reply.status_code == 422
    assert (runtime.ledger.status()['persisted'], set((runtime.root / 'artifacts').iterdir())) == before


def test_policy_rejection_fixture_isolates_fake_transport_from_host_elapsed_time(runtime, monkeypatch):
    elapsed = SimpleNamespace(value=0.0)
    original_operator = AgentCertOperatorIO
    def busy_host_default(**options):
        # Model a slow host's otherwise-real default clock, without sleeping or
        # changing event/review UTC evidence. The helper must supply its own
        # logical clock for the already-fake timer and HTTP transport.
        options.setdefault('monotonic', lambda: elapsed.value)
        return original_operator(**options)
    monkeypatch.setitem(globals(), 'AgentCertOperatorIO', busy_host_default)
    original_handler = runtime.transport.handler
    def elapsed_response(method, path, body):
        reply = original_handler(method, path, body)
        if method == 'POST' and path == '/api/agents/dispatch':
            elapsed.value = 2.1
        return reply
    runtime.transport.handler = elapsed_response
    test_review_policy_rejected_without_new_artifact_or_actions(runtime, 'minimum_tier', 'MINI')
    assert elapsed.value == 2.1


@pytest.mark.parametrize('defect', ['supplied_pass', 'source', 'unsupported_case', 'objective', 'forged_action'])
def test_reviewer_rejects_rehashed_submitted_evidence_without_new_effect(runtime, defect):
    result = collect(runtime)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    request = json.loads(next(body for method, path, body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/dispatch'))
    envelope = json.loads(request['context'])
    value = envelope['execution']
    if defect == 'supplied_pass': value['test_result'] = 'PASS'
    elif defect == 'source': envelope['expected_source_revision'] = 'c' * 40
    elif defect == 'unsupported_case': value['case_spec']['case'] = events.UNREADY_CASES[0]
    elif defect == 'objective': value['objective_read'][1]['id'] = NONCE
    else:
        forged_id = '55555555-5555-4555-8555-555555555555'
        value['dispatch']['authority_event']['subject_action_id'] = forged_id
        previous = None
        lines = []
        for raw in value['action_records']:
            event = json.loads(raw)
            if event['task_id'] == value['dispatch']['task_id']:
                event['action_id'] = forged_id
            if previous is not None: event['previous_sha256'] = previous
            event['sha256'] = events.sha(events.canonical({key: item for key, item in event.items() if key != 'sha256'}))
            previous = event['sha256']
            lines.append(events.canonical(event).decode() + '\n')
        value['action_records'] = lines
        from app.agent_cert_identity_review import action_span
        metadata, event = value['artifact_metadata'], value['dispatch']['authority_event']
        value['action_chain_join'] = action_span(lines, task_id=value['dispatch']['task_id'], agent_id='a19',
            action_type=events.authority_action_type(events.SUPPORTED_CASES[0]), schema=events.RESULT_SCHEMA,
            metadata=metadata, began=events._utc(event['started_at']), ended=events._utc(event['completed_at']),
            action_id=forged_id)
        # All submitted duplicate dispatches agree. Only fresh original-domain
        # rereads can authenticate their origin; rehashing never gives authority.
        value['submission'][1]['steps'][0]['dispatch'] = value['dispatch']
        value['objective_read'][1]['steps'][0]['dispatch'] = value['dispatch']
    envelope['expected_execution_sha256'] = events.sha(events.canonical(value))
    request['context'] = events.canonical(envelope).decode()
    before = runtime.ledger.status()['persisted'], set((runtime.root / 'artifacts').iterdir())
    reply = runtime.client.post('/api/agents/dispatch', json=request, headers={'Authorization': 'Bearer ' + TOKEN})
    assert reply.status_code == 422
    assert (runtime.ledger.status()['persisted'], set((runtime.root / 'artifacts').iterdir())) == before


def test_late_original_actions_are_retained_and_do_not_trigger_review_or_retry(runtime):
    clock = SimpleNamespace(value=0.0)
    def actions(task, action):
        reply = runtime.client.get('/api/agent-cert-events/actions/' + task,
            params={'action_type': action}, headers={'Authorization': 'Bearer ' + TOKEN})
        assert reply.status_code == 200
        clock.value = 31.0
        return reply.json()['original_lines']
    result = collect(runtime, read_subject_actions=actions, monotonic=lambda: clock.value)
    assert result.summary['state'] == 'REJECTED'
    assert len(result.subject_actions) == 2 and result.subject_artifact_bytes is not None
    assert [method for method, _ in runtime.requests].count('POST') == 1
    assert result.summary['review_dispatch_attempts'] == 0
    assert result.summary['signature'] == 'NOT_PERFORMED'


@pytest.mark.parametrize('domain', ['artifact', 'actions'])
def test_original_tamper_during_last_objective_read_is_rejected_before_review_write(runtime, monkeypatch, domain):
    result = collect(runtime)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    request = json.loads(next(body for method, path, body in reversed(runtime.transport.calls)
        if method == 'POST' and path == '/api/agents/dispatch'))
    execution = json.loads(result.execution_bytes)
    from app import objective_api
    original, reads = objective_api.get_read_only, []
    def changed(task, authorization):
        value = original(task, authorization)
        reads.append(task)
        if len(reads) == 2:
            if domain == 'artifact':
                path = runtime.root / 'artifacts' / execution['artifact_metadata']['artifact_id'] / 'artifact.json'
                path.write_bytes(path.read_bytes() + b' ')
            else:
                path = runtime.root / 'action-records.jsonl'
                path.write_bytes(path.read_bytes().replace(events.authority_action_type(events.SUPPORTED_CASES[0]).encode(), b'forged.action'))
        return value
    monkeypatch.setattr(objective_api, 'get_read_only', changed)
    before = runtime.ledger.status()['persisted'], set((runtime.root / 'artifacts').iterdir())
    reply = runtime.client.post('/api/agents/dispatch', json=request, headers={'Authorization': 'Bearer ' + TOKEN})
    assert reply.status_code == 422 and len(reads) == 2
    assert (runtime.ledger.status()['persisted'], set((runtime.root / 'artifacts').iterdir())) == before


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_exact_authority_events_forbid_cloud_in_fixed_admission(runtime, case_id):
    result = collect(runtime, case_id)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    entry = dict(record=signer_row(result), evidence_directory='governance/agent-cert-case-evidence/authority-test',
        execution_sha256=events.sha(result.execution_bytes), review_sha256=events.sha(result.review_bytes),
        execution_source_revision=SOURCE, runtime_image_id=IMAGE, reviewer_code_revision=CODE,
        cloud_policy=None, owner_policy_sha256=None)
    manifest = {'schema_version': 'prime.protected-reviewed-cases.v1', 'cases': [entry]}
    assert parse_admission(events.canonical(manifest)) == [entry]
    entry['cloud_policy'], entry['owner_policy_sha256'] = {}, 'a' * 64
    with pytest.raises(ValueError): parse_admission(events.canonical(manifest))
    with pytest.raises(CertificationReviewError):
        recompute(signer_row(result), result.execution_bytes, result.review_bytes, cloud_policy={})


def test_new_chain_is_selected_and_protected_hash_scope_includes_frozen_producer():
    from scripts.sign_admitted_agent_cases import CODE_FILES
    from scripts.agent_cert_readiness import EVENT_CASES, SOURCE_FILES
    assert set(events.SUPPORTED_CASES) <= EVENT_CASES
    from app import agent_cert_owner_referral_events as owner_events
    assert set(events.UNREADY_CASES) == {owner_events.CASE}
    assert owner_events.CASE in EVENT_CASES
    assert owner_events.CASE not in events.SUPPORTED_CASES
    assert 'app/agent_cert_authority_events.py' in CODE_FILES and 'app/agent_cert_authority_events.py' in SOURCE_FILES
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'scripts/run_canonical_ci.py').read_text())
    selected = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'names' and node.func.attr in {'append', 'extend'}:
            value = ast.literal_eval(node.args[0])
            selected.update([value] if node.func.attr == 'append' else value)
    assert {'agent_cert_authority_events', 'agent_cert_authority_chain'} <= selected
