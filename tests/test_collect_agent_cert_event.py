"""Original temporary-domain events and injected failures; never live/L7."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

import pytest

from app import agent_registry, agent_dispatch_api as dispatch
from app.action_records import ActionLedger
from app.artifact_factory import ArtifactFactory
from app.agent_cert_identity_review import canonical, read_action_span
from app.agent_cert_initialization import CASE, ACTION_TYPE
from app.agent_cert_role_review import canonical_case_spec
from scripts.collect_agent_cert_case import CollectionError, OperatorIO
from scripts.collect_agent_cert_event import collect_event_case
from tests.test_agent_cert_review_dispatch import configured, SOURCE, IMAGE, NONCE


CODE = 'f' * 40


class TemporaryOperator:
    """Actual existing temporary Objective/artifact/action domains, fake auth."""
    def __init__(self, configured, monkeypatch):
        from app import compute_queue_api, objective_api, runtime_status
        self.objectives = objective_api
        self.root = configured.root
        self.calls = []
        self.review = None
        self.artifacts = {}
        self.subject_lines = self.review_lines = None
        self.registry_sha = hashlib.sha256(agent_registry.REGISTRY_PATH.read_bytes()).hexdigest()
        compute_queue_api.queue.policy = SimpleNamespace(global_concurrency=1)
        monkeypatch.setattr(compute_queue_api, 'providers', lambda: pytest.fail('No model/provider selection'))
        monkeypatch.setattr(runtime_status, 'production_health',
            lambda: {'status': 'UNAVAILABLE', 'memory': {'status': 'UNKNOWN'},
                     'storage': {'status': 'UNKNOWN'}})
        monkeypatch.delenv('PRIME_QUALIFIED_HOST_PROFILE_PATH', raising=False)
        self.ledger = ActionLedger(self.root / 'action-records.jsonl')
        monkeypatch.setattr(dispatch, 'action_ledger', lambda: self.ledger)

    def authorize(self):
        self.calls.append('authorize')
        dispatch.authenticate_owner('fixture-owner')

    def runtime(self):
        self.calls.append('runtime')
        return self.objectives.runtime_snapshot()

    def submit(self, request):
        self.calls.append('submit')
        value = self.objectives.submit(self.objectives.ObjectiveRequest(**request), 'fixture-owner')
        # Identity's existing async ledger has no durable flag. This explicit
        # test-domain drain is not a collector callback operation or live proof.
        if request.get('deterministic_operation') == 'runtime_status':
            assert self.ledger.flush(timeout=1) is True
        return 202, value

    def objective(self, task):
        self.calls.append('objective')
        return 200, self.objectives.get_read_only(task, 'fixture-owner')

    def reviewer(self, request):
        self.calls.append('review')
        self.review = dispatch.dispatch_request(dispatch.AgentRequest(**request), 'fixture-owner')
        return 202, self.review

    def artifact(self, identifier):
        self.calls.append('artifact')
        metadata, raw = ArtifactFactory(self.root / 'artifacts').retrieve(identifier)
        self.artifacts[identifier] = raw
        return 200, raw, metadata['sha256']

    def subject_actions(self, task, action):
        self.calls.append('subject_actions')
        self.subject_lines = read_action_span(self.ledger.path, task, action)
        return list(self.subject_lines)

    def reviewer_actions(self, action):
        self.calls.append('review_actions')
        assert action == self.review['review_action_id']
        kind = json.loads(ArtifactFactory(self.root / 'artifacts').retrieve(
            self.review['artifact']['artifact_id'])[1])['test_case']
        self.review_lines = read_action_span(self.ledger.path, self.review['task_id'],
            'agent.certification.' + kind + '.review')
        return list(self.review_lines)

    def io(self):
        return OperatorIO(self.authorize, self.runtime, self.submit, self.objective,
            lambda _: pytest.fail('Zero-model event must never read a queue job'),
            self.reviewer, self.artifact, self.reviewer_actions)


@pytest.fixture
def operator(configured, monkeypatch):
    value = TemporaryOperator(configured, monkeypatch)
    yield value
    value.ledger.close()


def collect(operator, *, agent='a19', cap='responsibility.a19', case=CASE,
            io=None, actions=None, spec=None, **changes):
    options = dict(io=io or operator.io(),
        read_subject_actions=actions or operator.subject_actions,
        expected_source_revision=SOURCE, expected_runtime_image=IMAGE,
        expected_registry_sha256=operator.registry_sha, reviewer_code_revision=CODE,
        review_run_id='injected-temporary-event-review', timeout_seconds=10,
        nonce_factory=lambda: NONCE)
    options.update(changes)
    return collect_event_case(spec or canonical_case_spec(agent, cap, case), **options)


def reject(result, operator, *, submits=0, reviews=0):
    assert result.summary['state'] == 'REJECTED'
    assert result.summary['validation'] == 'NOT_ACCEPTED'
    assert operator.calls.count('submit') == submits
    assert operator.calls.count('review') == reviews
    assert result.summary['signature'] == 'NOT_PERFORMED'
    assert result.summary['certification'] == 'UNVERIFIED'


@pytest.mark.parametrize('agent,cap,reviewer,review_cap', [
    ('a19', 'responsibility.a19', 'a26', 'responsibility.a26'),
    ('a26', 'responsibility.a25', 'a18', 'responsibility.a27'),
    ('a17', 'responsibility.a17', 'a26', 'responsibility.a26'),
    ('a12', 'responsibility.a11', 'a26', 'responsibility.a26'),
])
def test_actual_temporary_owned_event_and_distinct_review(operator, agent, cap, reviewer, review_cap):
    result = collect(operator, agent=agent, cap=cap)
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    assert result.summary['model_calls'] == 0
    assert result.summary['reviewer_identity'] == reviewer
    assert result.summary['reviewer_capability_id'] == review_cap
    assert operator.calls.count('submit') == operator.calls.count('review') == 1
    assert result.summary['subject_task_id'] != result.summary['review_task_id']
    assert result.summary['signature'] == 'NOT_PERFORMED'
    assert result.summary['certification'] == 'UNVERIFIED'
    assert result.summary['protected_signing'] == 'PENDING_SEPARATE_ADMISSION'
    assert result.subject_actions == tuple(operator.subject_lines)
    assert result.reviewer_actions == tuple(operator.review_lines)
    assert result.subject_artifact_bytes == operator.artifacts[result.summary['subject_artifact_id']]
    assert result.reviewer_artifact_bytes == operator.artifacts[result.summary['reviewer_artifact_id']]
    execution, review = json.loads(result.execution_bytes), json.loads(result.review_bytes)
    assert execution['dispatch']['agent_id'] == agent
    assert review['observations']['reviewer_execution']['dispatch']['agent_id'] == reviewer
    assert review['execution_evidence_sha256'] == hashlib.sha256(result.execution_bytes).hexdigest()
    assert result.subject_artifact_bytes.decode() not in repr(result)
    assert result.reviewer_artifact_bytes.decode() not in repr(result)


def test_identity_uses_original_a19_contract_and_never_a_queue(operator):
    result = collect(operator, case='baseline:identity')
    assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', result.summary
    assert json.loads(result.review_bytes)['review_test_version'] == 'a19.runtime-identity.v1'
    assert len(result.subject_actions) == len(result.reviewer_actions) == 2


@pytest.mark.parametrize('late_observation_start', [False, True])
def test_owned_identity_collector_uses_outer_observation_without_admitting_earlier_actions(
        operator, monkeypatch, late_observation_start):
    from scripts import collect_agent_cert_event as collector
    from app.agent_cert_owned_identity import REVIEW_ACTION
    from app import agent_cert_owned_identity
    from app.agent_cert_identity_review import utc
    import time
    original_report = agent_cert_owned_identity.build_identity_report
    def delayed_report(*args, **kwargs):
        # Real elapsed producer work makes the ordering deterministic even
        # when the Windows clock gives consecutive operations equal times.
        time.sleep(0.003)
        return original_report(*args, **kwargs)
    monkeypatch.setattr(agent_cert_owned_identity, 'build_identity_report', delayed_report)
    original = collector.observe_cert_case
    observed = []
    def observe(*args, **kwargs):
        value = original(*args, **kwargs)
        observed.append(deepcopy(value))
        if late_observation_start:
            # Keep genuine original ledger/artifact bytes; narrow only the
            # offered outer observation to exclude the already-started action.
            value['started_at'] = value['captured_at']
        return value
    monkeypatch.setattr(collector, 'observe_cert_case', observe)
    def review_actions(action):
        operator.calls.append('review_actions')
        assert action == operator.review['review_action_id']
        operator.review_lines = read_action_span(operator.ledger.path,
            operator.review['task_id'], REVIEW_ACTION)
        return list(operator.review_lines)
    io = replace(operator.io(), read_review_actions=review_actions)
    result = collect(operator, agent='a01', cap='responsibility.a01',
        case='baseline:identity', io=io)
    first = json.loads(operator.subject_lines[0])
    assert utc(observed[0]['started_at']) <= utc(first['timestamp']) < utc(observed[0]['captured_at'])
    if late_observation_start:
        reject(result, operator, submits=1)
        assert result.summary['stage'] == 'SUBJECT_JOIN'
    else:
        assert result.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE', json.dumps(result.summary,sort_keys=True)
        assert operator.calls.count('submit') == operator.calls.count('review') == 1
        assert result.subject_actions == tuple(operator.subject_lines)
        assert result.reviewer_actions == tuple(operator.review_lines)


@pytest.mark.parametrize('field,value', [
    ('expected_source_revision', 'UNKNOWN'), ('expected_runtime_image', IMAGE.upper()),
    ('expected_registry_sha256', False), ('reviewer_code_revision', 'a'*39),
    ('review_run_id', 'secret\nnot-a-code'), ('timeout_seconds', True),
    ('timeout_seconds', 0), ('timeout_seconds', 31),
    ('timeout_seconds', float('nan')), ('timeout_seconds', float('inf')),
])
def test_invalid_protected_bindings_or_deadline_do_not_submit(operator, field, value):
    result = collect(operator, **{field: value})
    reject(result, operator)
    assert result.summary['source_revision'] is None


def test_registry_raw_mismatch_not_normalized_or_labeled_current(operator):
    result = collect(operator, expected_registry_sha256='0'*64)
    reject(result, operator)
    assert result.summary['reason'] == 'LOCAL_REVIEW_SOURCE_MISMATCH'


def test_missing_bounded_subject_audit_callback_denied_before_auth(operator):
    result = collect_event_case(canonical_case_spec('a19', 'responsibility.a19', CASE),
        io=operator.io(), read_subject_actions=None, expected_source_revision=SOURCE,
        expected_runtime_image=IMAGE, expected_registry_sha256=operator.registry_sha,
        reviewer_code_revision=CODE, review_run_id='temporary')
    reject(result, operator)
    assert operator.calls == []


@pytest.mark.parametrize('change', [
    lambda s: s['request'].update(max_cost_usd=1),
    lambda s: s['request'].update(data_classification='CLOUD_PERMITTED'),
    lambda s: s['request'].update(context='caller invented state'),
    lambda s: s.update(agent_id='a26'),
    lambda s: s.update(capability_id='responsibility.a26'),
    lambda s: s.update(certification='PASS'),
])
def test_modified_canonical_contract_has_no_mutation(operator, change):
    spec = canonical_case_spec('a19', 'responsibility.a19', CASE)
    change(spec)
    reject(collect(operator, spec=spec), operator)


@pytest.mark.parametrize('value', [True, False, {}, 'Owner'])
def test_non_none_authorization_result_not_authority(operator, value):
    reject(collect(operator, io=replace(operator.io(), authorize=lambda: value)), operator)


@pytest.mark.parametrize('callback', ['authorize', 'runtime', 'submit_objective', 'dispatch_reviewer'])
def test_callback_secret_exception_is_sanitized_and_not_replayed(operator, callback):
    def fail(*args):
        raise CollectionError('DO_NOT_PUBLISH_SUPER_SECRET')
    result = collect(operator, io=replace(operator.io(), **{callback: fail}))
    assert result.summary['state'] == 'REJECTED'
    assert 'DO_NOT_PUBLISH' not in repr(result)
    assert operator.calls.count('submit') <= 1 and operator.calls.count('review') <= 1
    if callback == 'submit_objective':
        assert result.summary['submission_uncertain'] is True
        assert result.summary['subject_submission_attempts'] == 1
    if callback == 'dispatch_reviewer':
        assert result.summary['review_dispatch_uncertain'] is True
        assert result.summary['review_dispatch_attempts'] == 1


def test_slow_authorization_exhausts_shared_budget_before_mutation(operator):
    clock = [0.0]
    def slow():
        clock[0] = 31.0
    result = collect(operator, io=replace(operator.io(), authorize=slow), monotonic=lambda: clock[0])
    reject(result, operator)
    assert result.summary['reason'] == 'BOUNDED_EVENT_OBSERVATION_INCOMPLETE'


def test_submit_timeout_keeps_original_result_and_uncertainty_no_retry(operator):
    clock = [0.0]
    def slow(request):
        result = operator.submit(request)
        clock[0] = 31.0
        return result
    result = collect(operator, io=replace(operator.io(), submit_objective=slow), monotonic=lambda: clock[0])
    reject(result, operator, submits=1)
    assert result.summary['submission_uncertain'] is True
    original = json.loads(result.execution_bytes)['submission']
    assert original[0] == 202
    assert result.summary['subject_task_id'] == original[1]['id']


def test_reviewer_timeout_preserves_decoded_original_reply_and_uncertainty(operator):
    clock = [0.0]
    def slow(request):
        result = operator.reviewer(request)
        clock[0] = 31.0
        return result
    result = collect(operator, io=replace(operator.io(), dispatch_reviewer=slow), monotonic=lambda: clock[0])
    reject(result, operator, submits=1, reviews=1)
    assert result.summary['review_dispatch_uncertain'] is True
    assert result.reviewer_dispatch_response_bytes == canonical([202, operator.review])
    assert result.summary['review_task_id'] == operator.review['task_id']
    assert result.subject_artifact_bytes is not None
    assert result.reviewer_dispatch_response_bytes.decode() not in repr(result)


def test_deadline_before_initial_runtime_callback_prevents_even_read(operator, monkeypatch):
    from scripts import collect_agent_cert_event as event
    clock = [0.0]
    def slow_source_read(expected):
        clock[0] = 31.0
    monkeypatch.setattr(event, '_registry_pin', slow_source_read)
    result = collect(operator, monotonic=lambda: clock[0])
    reject(result, operator)
    assert 'runtime' not in operator.calls


def test_deadline_before_final_runtime_callback_prevents_even_read(operator, monkeypatch):
    from scripts import collect_agent_cert_event as event
    clock = [0.0]
    original = event._now
    def expired_after_subject_read(callback):
        now = original(callback)
        clock[0] = 31.0
        return now
    monkeypatch.setattr(event, '_now', expired_after_subject_read)
    result = collect(operator, monotonic=lambda: clock[0])
    reject(result, operator, submits=1)
    # Before/observer before/observer after only; no extra post-join runtime.
    assert operator.calls.count('runtime') == 3


@pytest.mark.parametrize('status', [True, 200, 201, 302, '202'])
def test_non_202_mutation_reply_does_not_retry_or_reach_review(operator, status):
    def changed(request):
        _, reply = operator.submit(request)
        return status, reply
    result = collect(operator, io=replace(operator.io(), submit_objective=changed))
    reject(result, operator, submits=1)
    assert result.summary['submission_uncertain'] is True


def test_original_artifact_digest_failure_retains_exact_bytes(operator):
    def artifact(identifier):
        status, raw, digest = operator.artifact(identifier)
        return status, raw, '0'*64
    result = collect(operator, io=replace(operator.io(), read_artifact=artifact))
    reject(result, operator, submits=1)
    assert result.subject_artifact_bytes in operator.artifacts.values()
    assert result.subject_artifact_bytes.decode() not in repr(result)


@pytest.mark.parametrize('mutation', [
    lambda lines: [], lambda lines: [line.rstrip('\n') for line in lines],
    lambda lines: [lines[0], lines[0]],
    lambda lines: [json.dumps({**json.loads(lines[0]), 'agent_id': 'a26'})+'\n', lines[1]],
])
def test_original_action_span_required_before_independent_review(operator, mutation):
    def changed(task, action):
        return mutation(operator.subject_actions(task, action))
    reject(collect(operator, actions=changed), operator, submits=1)


@pytest.mark.parametrize('field,value', [
    ('agent_id', 'a19'), ('capability', 'responsibility.a19'),
    ('model_calls', False), ('review_action_durable', 1),
    ('certification', 'PASS'), ('runtime_source_revision', '0'*40),
])
def test_untrusted_reviewer_reply_not_independent_durable_proof(operator, field, value):
    def changed(request):
        status, result = operator.reviewer(request)
        return status, {**result, field: value}
    result = collect(operator, io=replace(operator.io(), dispatch_reviewer=changed))
    reject(result, operator, submits=1, reviews=1)
    assert result.summary['review_dispatch_uncertain'] is True


def test_readonly_objective_drift_prevents_review(operator):
    reads = [0]
    def changed(task):
        status, result = operator.objective(task)
        reads[0] += 1
        if reads[0] >= 2:
            result['state'] = 'caller-PASS'
        return status, result
    reject(collect(operator, io=replace(operator.io(), read_objective=changed)), operator, submits=1)


def test_stale_runtime_after_subject_stops_review(operator):
    def changed():
        value = operator.runtime()
        if 'subject_actions' in operator.calls:
            value['image_digest'] = 'sha256:'+'0'*64
        return value
    reject(collect(operator, io=replace(operator.io(), runtime=changed)), operator, submits=1)


def test_duplicate_review_json_cannot_be_proof_even_with_fresh_digest(operator):
    def artifact(identifier):
        status, raw, digest = operator.artifact(identifier)
        if operator.review is not None:
            raw = raw[:-1] + b',"test_result":"PASS"}'
            operator.review['artifact']['sha256'] = hashlib.sha256(raw).hexdigest()
            operator.review['artifact']['bytes'] = len(raw)
            return status, raw, operator.review['artifact']['sha256']
        return status, raw, digest
    result = collect(operator, io=replace(operator.io(), read_artifact=artifact))
    reject(result, operator, submits=1, reviews=1)
    assert b'"test_result":"PASS"' in result.reviewer_artifact_bytes


def test_reviewer_original_chain_failure_never_returns_collected(operator):
    def changed(action):
        return list(reversed(operator.reviewer_actions(action)))
    result = collect(operator, io=replace(operator.io(), read_review_actions=changed))
    reject(result, operator, submits=1, reviews=1)
    assert result.reviewer_artifact_bytes is not None
    assert result.reviewer_actions == tuple(reversed(operator.review_lines))


@pytest.mark.parametrize('reviewer', [False, True])
def test_late_original_action_read_kept_as_unaccepted_counterevidence(operator, reviewer):
    clock = [0.0]
    def late_subject(task, action):
        original = operator.subject_actions(task, action)
        clock[0] = 11.0
        return original
    def late_reviewer(action):
        original = operator.reviewer_actions(action)
        clock[0] = 11.0
        return original
    result = collect(operator, monotonic=lambda: clock[0],
        actions=operator.subject_actions if reviewer else late_subject,
        io=replace(operator.io(), read_review_actions=late_reviewer) if reviewer else operator.io())
    reject(result, operator, submits=1, reviews=int(reviewer))
    assert result.summary['reason'] == 'BOUNDED_EVENT_OBSERVATION_INCOMPLETE'
    assert result.subject_actions == tuple(operator.subject_lines)
    assert result.subject_artifact_bytes is not None
    if reviewer:
        assert result.reviewer_actions == tuple(operator.review_lines)
        assert result.reviewer_artifact_bytes is not None
    else:
        assert json.loads(result.execution_bytes)['action_records'] == operator.subject_lines
        assert result.summary['review_dispatch_attempts'] == 0


@pytest.mark.parametrize('invalid', [
    ['{}\n']*129, ['{}\n'], ['x'*65536+'\n', '{}\n'],
    ['\u00e9'*40000+'\n', '{}\n'], [b'{}\n', '{}\n'],
])
def test_late_malformed_or_oversize_span_is_not_retained_or_accepted(operator, invalid):
    clock = [0.0]
    def late(task, action):
        clock[0] = 11.0
        return invalid
    result = collect(operator, actions=late, monotonic=lambda: clock[0])
    reject(result, operator, submits=1)
    assert result.subject_actions == ()
    assert result.summary['reason'] == 'ORIGINAL_DURABLE_ACTIONS_REQUIRED'


def test_source_module_contains_no_live_client_or_cli_operator():
    from pathlib import Path
    from scripts import collect_agent_cert_event
    source = Path(collect_agent_cert_event.__file__).read_text(encoding='utf-8')
    for forbidden in ('requests.', 'httpx.', 'subprocess.', 'os.getenv', 'docker ',
                      'if __name__', 'sign_digest(', 'write_bytes(', 'write_text('):
        assert forbidden not in source
