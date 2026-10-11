"""Operator-only collection of ONE existing public synthetic role case.

All I/O is injected by a protected authenticated operator. There is deliberately
no CLI, login, environment/credential reader, HTTP client, Docker client, store,
signing operation or certification mutation here. Callbacks must be bounded and
authenticate existing Owner authority, not trust an agent-supplied bearer claim.
The separate read_review_actions callback is an operator read-only audit reader;
it must NOT grant PRIME/agents access to Docker, a socket or the host filesystem.

The returned bytes contain public synthetic outputs and belong in protected
evidence custody, not automatic logs. Even a valid collection is UNSIGNED case
evidence, never signed attestation, L7, broad model qualification or deployment.
An interrupted submit/dispatch is never retried by this collector. Callers must
preserve the returned uncertainty and reconcile the original request separately.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import time
import uuid
from collections.abc import Callable

from app.agent_cert_role_review import canonical_case_spec, review_case_output
from app.agent_cert_transport import CertificationTransport, validate_cloud_binding
from app.compute_catalog import task_tier
from app.tier_router import Tier, required_tier
from scripts.agent_cert_reviewed_signing import (
    CertificationReviewError, _reviewer_execution,
)


ROLE_REVIEW_OBJECTIVE = (
    'Independently review one recorded public synthetic role result against its '
    'existing oracle; do not certify or sign.'
)
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_SOURCE = re.compile(r'[0-9a-f]{40}\Z')
_IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
_IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z')
_JOB_FIELDS = ('id', 'agent', 'status', 'result', 'provider', 'attempts',
               'started_at', 'completed_at', 'error')
_STEP_JOB_FIELDS = ('id', 'agent', 'model', 'provider', 'status', 'result',
                    'error', 'created_at', 'started_at', 'completed_at')
_QUEUE_ROUTE_FIELDS = ('preferred_provider', 'model', 'allow_cloud',
    'data_classification', 'task_class', 'classification', 'max_retries',
    'max_cost_usd', 'input_tokens', 'output_tokens', 'actual_cost_usd')


@dataclass(frozen=True)
class OperatorIO:
    """Existing authenticated operations; NOT portable authorization tokens.

    authorize() must authenticate the protected Owner caller and return None.
    HTTP callbacks return (literal_status_integer, decoded_owned_response).
    read_artifact returns (status, ORIGINAL bytes, X-Artifact-SHA256 header).
    read_review_actions returns original JSON-line strings from the durable
    action ledger. read_provider_entry returns the owning catalog entry, without
    any credential value; its digest must also be pinned outside this callback.
    No callback may auto-retry mutation, follow redirects or start a worker.
    """
    authorize: Callable[[], None]
    runtime: Callable[[], dict]
    submit_objective: Callable[[dict], tuple[int, dict]]
    read_objective: Callable[[str], tuple[int, dict]]
    read_job: Callable[[str], tuple[int, dict]]
    dispatch_reviewer: Callable[[dict], tuple[int, dict]]
    read_artifact: Callable[[str], tuple[int, bytes, str]]
    read_review_actions: Callable[[str], list[str]]
    read_provider_entry: Callable[[str], dict] | None = None


@dataclass(frozen=True)
class CollectedCase:
    summary: dict
    execution_bytes: bytes | None = field(default=None, repr=False)
    review_bytes: bytes | None = field(default=None, repr=False)
    reviewer_artifact_bytes: bytes | None = field(default=None, repr=False)
    action_records: tuple[str, ...] = field(default=(), repr=False)


class CollectionError(ValueError):
    """Fixed redacted code; never stringify callback errors or model outputs."""


def _require(condition, code):
    if condition is not True:
        raise CollectionError(code) from None


def _call(callback, *args):
    try:
        return callback(*args)
    except Exception:
        # Callback exceptions are not trusted diagnostic codes, even when they
        # reuse this module's or the reviewer's exception class.
        raise CollectionError('OPERATOR_CALLBACK_FAILED') from None


def _tick(clock):
    value = _call(clock)
    _require(type(value) in (int, float) and math.isfinite(value),
             'OPERATOR_CLOCK_INVALID')
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _copy(value):
    raw = _canonical(value)
    _require(len(raw) <= 1024 * 1024, 'OWNED_RESPONSE_TOO_LARGE')
    return json.loads(raw)


def _equal(left, right):
    return _canonical(left) == _canonical(right)


def _uuid(value):
    try:
        return type(value) is str and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _utc(value):
    _require(type(value) is str and 1 <= len(value) <= 40, 'TIMESTAMP_INVALID')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        _require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
                 'TIMESTAMP_INVALID')
        return parsed
    except ValueError:
        raise CollectionError('TIMESTAMP_INVALID') from None


def _now(clock):
    value = _call(clock)
    _require(type(value) is datetime and value.tzinfo is not None and
             value.utcoffset() is not None, 'OPERATOR_CLOCK_INVALID')
    return value


def _response(value, status, code):
    _require(type(value) is tuple and len(value) == 2 and type(value[0]) is int
             and value[0] == status and type(value[1]) is dict, code)
    return _copy(value[1])


def _runtime(io, source, image):
    value = _copy(_call(io.runtime))
    _require(type(value) is dict and set(value) == {
        'host_id', 'source_revision', 'version', 'image_digest'} and
        value['source_revision'] == source and value['image_digest'] == image and
        all(type(value[key]) is str and value[key] != 'UNKNOWN' and
            bool(_IDENTITY.fullmatch(value[key])) for key in ('host_id', 'version')),
        'RUNTIME_IDENTITY_MISMATCH')
    return value


def _provider(io, prepared, expected_sha):
    """Check a pinned owned catalog contract; a QUALIFIED flag is not evidence."""
    _require(callable(io.read_provider_entry) and type(expected_sha) is str and
             bool(_SHA.fullmatch(expected_sha)), 'PROVIDER_CONTRACT_PIN_REQUIRED')
    entry = _copy(_call(io.read_provider_entry, prepared['provider_id']))
    _require(type(entry) is dict and _sha(_canonical(entry)) == expected_sha,
             'PROVIDER_CONTRACT_CHANGED')
    _require(not any(key.lower() in {'token', 'api_key', 'secret', 'password',
             'credential'} for key in entry), 'PROVIDER_CREDENTIAL_VALUE_FORBIDDEN')
    limits = prepared['limits']
    expected = {'id': prepared['provider_id'], 'model': prepared['model'],
        'provider_kind': 'huggingface', 'location': 'cloud', 'enabled': True,
        'qualification_status': 'QUALIFIED', 'endpoint':
        'https://router.huggingface.co/v1/chat/completions',
        'context_tokens': limits['context_tokens'], 'output_tokens': limits['output_tokens'],
        'concurrency': limits['concurrency_limit'], 'max_retries': limits['max_retries']}
    _require(all(_equal(entry.get(key), value) for key, value in expected.items()),
             'PROVIDER_LIMITS_INVALID')
    _require(entry.get('secret_ref') in {'env:HF_TOKEN', 'file:HF_TOKEN'} and
             type(entry.get('tier')) is str and entry['tier'] in Tier.__members__ and
             Tier[entry['tier']] >= Tier[prepared['minimum_tier']] and
             _equal(entry.get('allowed_task_classes'), [prepared['task_class']]) and
             _equal(entry.get('fallback_ids', []), []), 'PROVIDER_SCOPE_INVALID')
    _require(_equal(entry.get('task_budgets', {}).get(prepared['task_class']), {
        'context_tokens': limits['context_tokens'], 'output_tokens': limits['output_tokens'],
        'timeout_seconds': limits['timeout_seconds']}), 'PROVIDER_DEADLINE_UNPROVEN')
    for key in ('input_usd_million', 'output_usd_million'):
        value = entry.get(key)
        _require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                 'PROVIDER_PRICE_UNKNOWN')
    _require(entry.get('cached_usd_million') is None,
             'UNREVIEWED_CACHE_PRICE_CONTRACT')
    return entry


def _route(job, request, prepared=None):
    _require(type(job) is dict and type(job.get('prompt')) is str and
             1 <= len(job['prompt'].encode('utf-8')) <= 16_000,
             'QUEUE_PROMPT_INVALID')
    expected = {'classification': 'R0', 'task_class': request['task_class'], 'max_retries': 0,
        'data_classification': request['data_classification'],
        'max_cost_usd': request['max_cost_usd'], 'allow_cloud': 1 if prepared else 0}
    if prepared:
        expected.update(preferred_provider=prepared['provider_id'], model=prepared['model'])
    # SQLite REAL columns serialize an authorized zero ceiling as 0.0. Compare
    # money numerically while retaining exact types/contracts for other fields.
    cost, ceiling = job.get('max_cost_usd'), expected['max_cost_usd']
    _require(type(cost) in (int, float) and type(ceiling) in (int, float)
             and math.isfinite(cost) and math.isfinite(ceiling)
             and cost >= 0 and ceiling >= 0
             and Decimal(str(cost)) == Decimal(str(ceiling)),
             'QUEUE_ROUTE_MISMATCH')
    _require(all(_equal(job.get(key), value) for key, value in expected.items()
                 if key != 'max_cost_usd'),
             'QUEUE_ROUTE_MISMATCH')
    _require(type(job.get('preferred_provider')) is str and
             bool(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', job['preferred_provider'])) and
             type(job.get('model')) is str and 1 <= len(job['model']) <= 200,
             'QUEUE_PROVIDER_INVALID')
    if prepared is None:
        _require(job['preferred_provider'] in {'ollama-fast', 'ollama-deep'},
                 'UNBOUND_LOCAL_PROVIDER')
    if job.get('status') in {'running', 'completed'}:
        _require(job.get('provider') == job['preferred_provider'], 'QUEUE_PROVIDER_MISMATCH')
    return {key: (expected[key] if key == 'max_cost_usd' else job.get(key))
            for key in expected} | {
        'preferred_provider': job['preferred_provider'], 'model': job['model'],
        'prompt_sha256': _sha(job['prompt'].encode('utf-8'))}


def _cloud_accounting(job, entry, prepared):
    limits = prepared['limits']
    for field_name, cap in (('input_tokens', limits['context_tokens']),
                            ('output_tokens', limits['output_tokens'])):
        _require(type(job.get(field_name)) is int and 0 <= job[field_name] <= cap,
                 'CLOUD_USAGE_UNPROVEN')
    actual, reserved = job.get('actual_cost_usd'), job.get('estimated_cost_usd')
    _require(type(actual) in (int, float) and type(reserved) in (int, float) and
             math.isfinite(actual) and math.isfinite(reserved) and
             0 <= actual <= reserved <= limits['max_cost_usd'], 'CLOUD_COST_UNPROVEN')
    upper = len(job['prompt'].encode('utf-8')) + 16
    _require(upper + limits['output_tokens'] <= limits['context_tokens'],
             'CLOUD_CONTEXT_BUDGET_EXCEEDED')
    try:
        rate_in, rate_out = (Decimal(str(entry[key])) for key in
                            ('input_usd_million', 'output_usd_million'))
        estimated = (upper * rate_in + limits['output_tokens'] * rate_out) / Decimal(1_000_000)
        charged = (job['input_tokens'] * rate_in + job['output_tokens'] * rate_out) / Decimal(1_000_000)
        _require(estimated <= Decimal(str(reserved)) and
                 math.isclose(actual, float(charged), rel_tol=1e-12, abs_tol=1e-15),
                 'CLOUD_RESERVATION_PRICE_MISMATCH')
    except InvalidOperation:
        raise CollectionError('CLOUD_RESERVATION_PRICE_MISMATCH') from None


def _objective(io, objective_id, job, capability, runtime):
    value = _response(_call(io.read_objective, objective_id), 200, 'OBJECTIVE_READ_FAILED')
    metadata, steps = value.get('execution_metadata'), value.get('steps')
    _require(value.get('id') == objective_id and type(value.get('revision')) is int and
             value['revision'] == 0 and value.get('state') == 'COMPLETED' and
             type(steps) is list and len(steps) == 1 and type(metadata) is dict,
             'OBJECTIVE_JOIN_INVALID')
    step = steps[0]
    expected_step = {key: job.get(key) for key in _STEP_JOB_FIELDS}
    _require(type(step) is dict and step.get('capability') == capability and
             type(step.get('revision')) is int and step['revision'] == 0 and
             _equal(step.get('job'), expected_step) and
             _uuid(step.get('dispatch', {}).get('correlation_id')) and
             step.get('dispatch', {}).get('job', {}).get('id') == job['id'] and
             step.get('dispatch', {}).get('job', {}).get('agent') == job['agent'],
             'OBJECTIVE_STEP_MISMATCH')
    _require(metadata.get('schema_version') == 'jarvis.authoritative-execution.v1' and
             metadata.get('authoritative') is True and metadata.get('task_id') == objective_id and
             type(metadata.get('revision')) is int and metadata['revision'] == 0 and
             metadata.get('state') == 'COMPLETED' and _equal(metadata.get('runtime'), runtime) and
             metadata.get('provenance', {}).get('runtime') == 'IMMUTABLE_OBJECTIVE_RUNTIME' and
             metadata.get('model_content_is_authoritative_metadata') is False,
             'OBJECTIVE_RUNTIME_MISMATCH')
    expected_job = {'job_id': job['id'], 'agent': job['agent'], 'model': job['model'],
        'provider': job['provider'], 'state': job['status'], 'created_at': job.get('created_at'),
        'started_at': job['started_at'], 'completed_at': job['completed_at']}
    _require(_equal(metadata.get('jobs'), [expected_job]), 'OBJECTIVE_QUEUE_MISMATCH')
    return value


def collect_role_case(spec, *, io: OperatorIO, expected_source_revision: str,
                      expected_runtime_image: str, reviewer_code_revision: str,
                      review_run_id: str, cloud_binding: CertificationTransport | None = None,
                      cloud_policy: dict | None = None,
                      expected_owner_policy_sha256: str | None = None,
                      expected_provider_entry_sha256: str | None = None,
                      timeout_seconds: float = 60, poll_seconds: float = 0.25,
                      monotonic: Callable[[], float] = time.monotonic,
                      pause: Callable[[float], None] = time.sleep,
                      wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                      nonce_factory: Callable[[], str] = lambda: str(uuid.uuid4())) -> CollectedCase:
    """Collect one immutable Objective and one registered reviewer execution.

    Trusted source/image/policy/catalog pins come from the protected operator,
    not callbacks that merely repeat agent-provided claims. A failure preserves
    captured bytes and submission uncertainty; this function never retries a
    POST, signs, supplies credentials, or relaxes the existing role oracle.
    """
    summary = {'schema': 'prime.agent-cert-case-collection.v1', 'state': 'REJECTED',
        'certification': 'UNVERIFIED', 'signature': 'NOT_PERFORMED',
        'subject_submission_attempts': 0, 'review_dispatch_attempts': 0,
        'submission_uncertain': False, 'review_dispatch_uncertain': False,
        'stage': 'PRECHECK', 'source_revision': None, 'runtime_image_id': None}
    primary = review_raw = artifact_raw = None
    actions = ()
    try:
        _require(type(io) is OperatorIO and all(callable(getattr(io, name)) for name in
            ('authorize', 'runtime', 'submit_objective', 'read_objective', 'read_job',
             'dispatch_reviewer', 'read_artifact', 'read_review_actions')),
            'AUTHENTICATED_CALLBACKS_REQUIRED')
        _require(type(expected_source_revision) is str and bool(_SOURCE.fullmatch(expected_source_revision))
            and type(expected_runtime_image) is str and bool(_IMAGE.fullmatch(expected_runtime_image))
            and type(reviewer_code_revision) is str and bool(_SOURCE.fullmatch(reviewer_code_revision))
            and type(review_run_id) is str and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}', review_run_id)),
            'PROTECTED_RUNTIME_BINDINGS_REQUIRED')
        summary.update(source_revision=expected_source_revision,
                       runtime_image_id=expected_runtime_image)
        _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds) and
            0 < timeout_seconds <= 120 and type(poll_seconds) in (int, float) and
            math.isfinite(poll_seconds) and 0 < poll_seconds <= 1,
            'BOUNDED_POLL_REQUIRED')
        _require(_call(io.authorize) is None, 'OWNER_AUTHENTICATION_FAILED')
        _require(type(spec) is dict, 'CANONICAL_ROLE_CASE_REQUIRED')
        canonical = canonical_case_spec(spec.get('agent_id'), spec.get('capability_id'), spec.get('case'))
        _require(_equal(spec, canonical), 'CANONICAL_ROLE_CASE_CHANGED')
        agent, capability = canonical['agent_id'], canonical['capability_id']
        dimension, test_case = canonical['case'].split(':')
        summary.update(agent_id=agent, capability_id=capability, case=canonical['case'])
        request = _copy(canonical['request'])
        tier = max(Tier[request['minimum_tier']], task_tier(request['objective'], request['task_class']),
                   required_tier(request['objective'], request['context']))
        prepared = entry = None
        cloud = any(value is not None for value in (cloud_binding, cloud_policy,
            expected_owner_policy_sha256, expected_provider_entry_sha256))
        def check_cloud():
            checked = validate_cloud_binding(canonical, cloud_policy, cloud_binding,
                expected_source_revision=expected_source_revision,
                expected_policy_sha256=expected_owner_policy_sha256)
            current = _provider(io, checked.receipt(), expected_provider_entry_sha256)
            return checked, current
        if cloud:
            checked, entry = check_cloud()
            prepared, request = checked.receipt(), checked.request()
            timeout_seconds = min(timeout_seconds, prepared['limits']['timeout_seconds'])
        before = _runtime(io, expected_source_revision, expected_runtime_image)
        summary.update(canonical_spec_sha256=_sha(_canonical(canonical)),
                       execution_request_sha256=_sha(_canonical(request)))
        deadline = _tick(monotonic) + timeout_seconds
        _require(math.isfinite(deadline), 'OPERATOR_CLOCK_INVALID')
        if cloud:
            check_cloud()
        _require(_tick(monotonic) < deadline, 'BOUNDED_OBSERVATION_INCOMPLETE')
        summary.update(stage='SUBJECT_SUBMIT', subject_submission_attempts=1,
                       submission_uncertain=True)
        submitted = _response(_call(io.submit_objective, _copy(request)), 202, 'OBJECTIVE_SUBMIT_FAILED')
        _require(_uuid(submitted.get('id')) and type(submitted.get('steps')) is list and
                 len(submitted['steps']) == 1, 'OBJECTIVE_SUBMIT_BINDING_INVALID')
        objective_id = submitted['id']
        summary['objective_id'] = objective_id
        step = submitted['steps'][0]
        reply = step.get('dispatch') if type(step) is dict else None
        _require(type(reply) is dict and step.get('capability') == capability and
                 reply.get('capability') == capability and reply.get('tier') == tier.name and
                 type(reply.get('job')) is dict and _uuid(reply['job'].get('id')) and
                 reply['job']['agent'] == agent and reply['job']['id'] != objective_id,
                 'OBJECTIVE_DISPATCH_BINDING_INVALID')
        job_id = reply['job']['id']
        summary.update(job_id=job_id, submission_uncertain=False, stage='SUBJECT_READ')
        bound_route = _route(reply['job'], request, prepared)
        job = None
        # Finite polling count also bounds a faulty/nonadvancing injected clock.
        for _ in range(min(500, math.ceil(timeout_seconds / poll_seconds) + 1)):
            _require(_tick(monotonic) < deadline, 'BOUNDED_OBSERVATION_INCOMPLETE')
            row = _response(_call(io.read_job, job_id), 200, 'JOB_READ_FAILED')
            _require(row.get('id') == job_id and row.get('agent') == agent,
                     'QUEUE_IDENTITY_MISMATCH')
            _require(_equal(_route(row, request, prepared), bound_route), 'QUEUE_ROUTE_CHANGED')
            status = row.get('status')
            if status == 'completed':
                job = row
                break
            _require(status in {'queued', 'running'}, 'SUBJECT_EXECUTION_FAILED')
            _call(pause, min(poll_seconds, max(0, deadline - _tick(monotonic))))
        _require(job is not None, 'BOUNDED_OBSERVATION_INCOMPLETE')
        result = job.get('result')
        _require(type(result) is str and 1 <= len(result.encode('utf-8')) <= 16_384 and
                 type(job.get('attempts')) is int and job['attempts'] == 1 and
                 (job.get('error') is None or
                  (type(job.get('error')) is str and job['error'] == '')) and
                 _utc(job.get('started_at')) <= _utc(job.get('completed_at')) <= _now(wall_clock),
                 'COMPLETED_JOB_INVALID')
        execution = {'schema_version': 'prime.agent-certification.execution.v1',
            'agent_id': agent, 'capability_id': capability, 'dimension': dimension, 'test_case': test_case,
            'source_revision': expected_source_revision, 'runtime_image_id': expected_runtime_image,
            'environment': 'LIVE_RUNTIME', 'executor_identity': agent, 'case_spec': canonical,
            'dispatch': {'capability': capability, 'job': {'id': job_id, 'agent': agent}},
            'job': {key: job[key] for key in _JOB_FIELDS} | {'result_sha256': _sha(result.encode('utf-8'))},
            'transport': {'authentication': 'OWNER_AUTHENTICATED', 'dispatch_http_status': 202,
                'job_http_status': 200, 'provider_locality': 'CLOUD' if cloud else 'LOCAL',
                'runtime_source_revision': expected_source_revision, 'actual_runtime_image': expected_runtime_image}}
        if cloud:
            # Capture before validation so a failed usage/reservation join retains
            # the real completed observation, not an invented accepted charge.
            execution['cloud_transport'] = {'binding': prepared, 'queue_route':
                {key: job.get(key) for key in _QUEUE_ROUTE_FIELDS} |
                {'prompt_sha256': bound_route['prompt_sha256']}}
        primary = _canonical(execution)
        summary.update(execution_sha256=_sha(primary), result_sha256=execution['job']['result_sha256'],
                       stage='SUBJECT_JOIN', validation='PENDING_NOT_ACCEPTED')
        if cloud:
            _, fresh_entry = check_cloud()
            _cloud_accounting(job, fresh_entry, prepared)
        objective = _objective(io, objective_id, job, capability, before)
        _require(_equal(before, _runtime(io, expected_source_revision, expected_runtime_image)),
                 'RUNTIME_IDENTITY_CHANGED')
        passed, errors = review_case_output(agent, capability, canonical['case'], result)
        _require(passed is True and not errors, 'CASE_ORACLE_FAILED')
        nonce = _call(nonce_factory)
        _require(_uuid(nonce), 'REVIEW_NONCE_INVALID')
        actor, actor_cap = ('a18', 'responsibility.a27') if agent == 'a26' else ('a26', 'responsibility.a26')
        context = _canonical({'execution': execution, 'expected_execution_sha256': _sha(primary),
            'expected_source_revision': expected_source_revision, 'review_nonce': nonce,
            'subject_objective_id': objective_id}).decode('utf-8')
        _require(len(context.encode('utf-8')) <= 65_536, 'REVIEW_CONTEXT_TOO_LARGE')
        review_request = {'classification': 'R0', 'capability': actor_cap,
            'objective': ROLE_REVIEW_OBJECTIVE, 'context': context, 'data_classification': 'LOCAL_ONLY',
            'minimum_tier': 'NANO', 'priority': 'low', 'task_class': 'planning', 'max_cost_usd': 0,
            'response_format': 'strict_json', 'deterministic_operation': 'certification_role_review'}
        _require(_tick(monotonic) < deadline, 'BOUNDED_OBSERVATION_INCOMPLETE')
        if cloud:
            check_cloud()
        _require(_tick(monotonic) < deadline, 'BOUNDED_OBSERVATION_INCOMPLETE')
        summary.update(stage='REVIEW_DISPATCH', review_dispatch_attempts=1, review_dispatch_uncertain=True)
        reviewer = _response(_call(io.dispatch_reviewer, review_request), 202, 'REVIEW_DISPATCH_FAILED')
        summary['review_task_id'] = reviewer.get('task_id') if _uuid(reviewer.get('task_id')) else None
        _require(reviewer.get('agent_id') == actor and reviewer.get('capability') == actor_cap and
                 reviewer.get('review_action_durable') is True and type(reviewer.get('artifact')) is dict,
                 'DURABLE_REGISTERED_REVIEW_REQUIRED')
        summary.update(stage='REVIEW_ARTIFACT', review_dispatch_uncertain=False)
        artifact_id = reviewer['artifact'].get('artifact_id')
        _require(type(artifact_id) is str and bool(re.fullmatch(r'[0-9a-f]{32}', artifact_id)),
                 'REVIEW_ARTIFACT_ID_INVALID')
        reply_artifact = _call(io.read_artifact, artifact_id)
        _require(type(reply_artifact) is tuple and len(reply_artifact) == 3 and
                 type(reply_artifact[0]) is int and reply_artifact[0] == 200 and
                 type(reply_artifact[1]) is bytes and 1 <= len(reply_artifact[1]) <= 65_536,
                 'REVIEW_ARTIFACT_READ_FAILED')
        artifact_raw = reply_artifact[1]
        _require(reply_artifact[2] == _sha(artifact_raw) == reviewer['artifact'].get('sha256'),
                 'REVIEW_ARTIFACT_DIGEST_MISMATCH')
        events = _call(io.read_review_actions, reviewer.get('review_action_id'))
        _require(type(events) is list and 2 <= len(events) <= 128 and
                 all(type(line) is str and 1 <= len(line.encode('utf-8')) <= 65_536 for line in events),
                 'DURABLE_ACTION_READER_REQUIRED')
        actions = tuple(events)
        proof = {'dispatch': reviewer, 'artifact_content_utf8': artifact_raw.decode('utf-8'),
            'transport': {'authentication': 'OWNER_AUTHENTICATED', 'dispatch_http_status': 202,
                'artifact_http_status': 200, 'runtime_source_revision': expected_source_revision,
                'actual_runtime_image': expected_runtime_image}, 'action_records': events}
        now = _now(wall_clock)
        _reviewer_execution(proof, row={'agent_id': agent, 'capability_id': capability,
            'dimension': dimension, 'test_case': test_case,
            'verifier': actor, 'certified_at': now.isoformat()}, job=execution['job'], spec=canonical,
            execution_sha256=_sha(primary), source_revision=expected_source_revision,
            runtime_image_id=expected_runtime_image, now=now,
            queue_prompt_sha256=bound_route['prompt_sha256'])
        # This decoder is safe only after the existing strict duplicate-key,
        # finite/type/bounds validator above accepted the exact original bytes.
        content = json.loads(artifact_raw)
        join = content['subject_domain_join']
        _require(content['review_nonce'] == nonce and join['objective_id'] == objective_id and
                 type(join['objective_revision']) is int and join['objective_revision'] == 0 and
                 _equal(join['runtime'], before) and join['execution_metadata_sha256'] ==
                 _sha(_canonical(objective['execution_metadata'])), 'REVIEW_OBJECTIVE_JOIN_MISMATCH')
        final_job = _response(_call(io.read_job, job_id), 200, 'JOB_FINAL_READ_FAILED')
        _require(_equal(job, final_job), 'COMPLETED_QUEUE_CHANGED')
        final_objective = _objective(io, objective_id, final_job, capability, before)
        _require(_equal(objective['execution_metadata'], final_objective['execution_metadata']),
                 'COMPLETED_OBJECTIVE_CHANGED')
        _require(_equal(before, _runtime(io, expected_source_revision, expected_runtime_image)),
                 'RUNTIME_IDENTITY_CHANGED')
        if cloud:
            check_cloud()
        _require(_tick(monotonic) < deadline, 'BOUNDED_OBSERVATION_INCOMPLETE')
        version = 'group_two_exact_role_oracle.v1' if content['oracle_id'] == 'group_two_exact_role_oracle/v1' else content['oracle_id']
        review = {'schema_version': 'prime.agent-certification.review.v1',
            'reviewer_identity': actor, 'review_run_id': review_run_id,
            'source_revision': expected_source_revision, 'agent_id': agent, 'capability_id': capability,
            'dimension': dimension, 'test_case': test_case, 'execution_evidence_sha256': _sha(primary),
            'test_result': 'PASS', 'review_test_version': version,
            'observations': {'execution_job_id': job_id, 'result_sha256': execution['job']['result_sha256'],
                'case_spec_sha256': _sha(_canonical(canonical)), 'runtime_image_id': expected_runtime_image,
                'reviewer_code_revision': reviewer_code_revision, 'oracle_id': content['oracle_id'],
                'oracle_pass': True, 'reviewer_execution': proof}}
        review_raw = _canonical(review)
        # The existing protected signer reads bounded artifacts, including
        # original interleaved action lines. Do not advertise a collection it
        # cannot consume; retain the oversized bytes as rejected counterevidence.
        _require(1 <= len(review_raw) <= 1024 * 1024,
                 'REVIEW_ENVELOPE_EXCEEDS_SIGNER_BOUND')
        summary.update(state='UNSIGNED_CASE_EVIDENCE', stage='COLLECTED', reason=None,
            validation='EXISTING_ROLE_ORACLE_AND_REGISTERED_REVIEW_JOINED',
            reviewer_identity=actor, reviewer_artifact_id=artifact_id,
            reviewer_artifact_sha256=_sha(artifact_raw), review_sha256=_sha(review_raw),
            review_action_chain_sha256=_sha(_canonical(events)),
            runtime_before_sha256=_sha(_canonical(before)), runtime_after_sha256=_sha(_canonical(before)),
            provider_locality='CLOUD' if cloud else 'LOCAL',
            provider_qualification='NOT_ESTABLISHED_BY_COLLECTION', collected_at=now.isoformat())
    except (CollectionError, CertificationReviewError) as exc:
        summary.update(reason=str(exc), validation='NOT_ACCEPTED')
    except Exception:
        # Callback exceptions can contain raw credentials, URLs, filesystem
        # paths or generated output. Preserve uncertainty, never their message.
        summary.update(reason='OPERATOR_COLLECTION_FAILED', validation='NOT_ACCEPTED')
    return CollectedCase(summary, primary, review_raw, artifact_raw, actions)
