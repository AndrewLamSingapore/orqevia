"""Provider-neutral, authority-neutral routing plans and one-shot execution.

This optional adapter is not wired to production. It neither resolves credentials
nor creates jobs/reservations. Operator-owned model identities and existing
admitted jobs are inputs; invocation/authorization callbacks must delegate to the
existing governed runtime. A consumer login is not an API credential. Distinct
role names, deployment aliases and provider IDs do not prove distinct models.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import math
import re
import threading
import time
import unicodedata
import uuid
from typing import Callable, Mapping

from .compute_catalog import model_spec
from .hf_admission import require_hf_admission, require_hf_task_scope
from .provider_runtime import ProviderFailure, Usage, ChatCompletionProvider, HuggingFaceProvider
from .reasoning_budgets import select_budget, verify_reserved_cost
from .tier_router import Backend, CLASSIFICATIONS, Tier, classify_for_cloud


class Mode(str, Enum):
    AUTO = 'AUTO'
    PRIMARY = 'PRIMARY'
    CLOUD = 'CLOUD'
    LOCAL = 'LOCAL'
    VERIFY = 'VERIFY'
    CONSENSUS = 'CONSENSUS'
    FANOUT = 'FANOUT'


class RouterRejected(ValueError):
    """Fixed public codes only; never callback messages or raw metadata."""


_REJECTED_PROVIDER_CODES = frozenset({'CREDENTIAL_UNAVAILABLE', 'RATE_LIMIT', 'CAPACITY',
    'PROVIDER_CIRCUIT_OPEN', 'PROVIDER_CIRCUIT_BUSY', 'HF_CREDENTIAL_SCOPE_DENIED',
    'DATA_LOCALITY', 'PROVIDER_UNAVAILABLE', 'PROVIDER_UNQUALIFIED',
    'HF_EXPLICIT_SELECTION_REQUIRED', 'HF_BUDGET_NOT_RESERVED', 'FALLBACK_POLICY_DENIED',
    'FALLBACK_CONFIGURATION_INVALID', 'MODEL_PROVIDER_UNPINNED', 'INVALID_MESSAGES',
    'INVALID_RETRY_LIMIT', 'INVALID_TIMEOUT', 'REASONING_BUDGET_CONFIG_INVALID',
    'REASONING_BUDGET_EXTENSION_DENIED', 'REASONING_BUDGET_COST_EXCEEDED'})
_SAFE_PROVIDER_CODES = _REJECTED_PROVIDER_CODES | frozenset({'TASK_TIMEOUT', 'PROVIDER_TIMEOUT',
    'PROVIDER_TRANSPORT_FAILURE', 'PROVIDER_HTTP_FAILURE', 'MALFORMED_STREAM',
    'INVALID_USAGE', 'OUTPUT_BUDGET_EXHAUSTED', 'EMPTY_OR_INCOMPLETE_RESPONSE',
    'CANCELLED', 'PROVIDER_ADAPTER_FAILURE', 'PROVIDER_STREAM_FAILURE', 'INCOMPLETE_STREAM'})


def _reject(code):
    raise RouterRejected(code)


def _money(value):
    if type(value) not in (int, float, str, Decimal):
        _reject('INVALID_COST_BOUND')
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        _reject('INVALID_COST_BOUND')
    if not result.is_finite() or result < 0:
        _reject('INVALID_COST_BOUND')
    return result


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _wire_model_key(call):
    # Different HF serving-provider suffixes still refer to the same repository
    # model; they are provider diversity, not model diversity. Unknown aliases
    # additionally require protected underlying identity metadata, never guesses.
    if call.entry.get('provider_kind') == 'huggingface':
        return call.model.rsplit(':', 1)[0]
    return call.model


def _distinct(calls):
    return (len(calls) >= 2 and all(c.underlying_model_id for c in calls)
            and len({c.underlying_model_id for c in calls}) == len(calls)
            and len({_wire_model_key(c) for c in calls}) == len(calls))


@dataclass(frozen=True)
class ExecutionBudget:
    max_calls: int = 1
    max_parallel: int = 1
    max_elapsed_seconds: float = 20
    per_call_seconds: float = 20
    max_call_cost_usd: Decimal = Decimal('0')
    max_total_cost_usd: Decimal = Decimal('0')

    def __post_init__(self):
        if (type(self.max_calls) is not int or not 1 <= self.max_calls <= 16
                or type(self.max_parallel) is not int or not 1 <= self.max_parallel <= self.max_calls):
            _reject('INVALID_CALL_BOUND')
        for value in (self.max_elapsed_seconds, self.per_call_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 300:
                _reject('INVALID_DEADLINE')
        for name in ('max_call_cost_usd', 'max_total_cost_usd'):
            object.__setattr__(self, name, _money(getattr(self, name)))
        if self.max_call_cost_usd > self.max_total_cost_usd:
            _reject('INVALID_COST_BOUND')


@dataclass(frozen=True)
class PlannedCall:
    provider_id: str
    model: str
    underlying_model_id: str | None
    location: str
    tier: Tier
    reserved_cost_usd: Decimal
    binding_sha256: str
    prompt_sha256: str
    # Private configuration/job input is not a public receipt or a new authority.
    entry: dict = field(repr=False, compare=False)
    job: dict | None = field(repr=False, compare=False)


@dataclass(frozen=True)
class RoutingPlan:
    mode: Mode
    calls: tuple[PlannedCall, ...]
    budget: ExecutionBudget
    prompt_sha256: str
    grants_execution_authority: bool = False
    verified: bool = False

    def receipt(self):
        return {'schema': 'prime.model-router-plan.v1', 'mode': self.mode.value,
                'prompt_sha256': self.prompt_sha256,
                'calls': [{'provider_id': c.provider_id, 'model': c.model,
                           'underlying_model_id': c.underlying_model_id,
                           'location': c.location, 'tier': c.tier.name,
                           'binding_sha256': c.binding_sha256,
                           'reserved_cost_usd': str(c.reserved_cost_usd)} for c in self.calls],
                'grants_execution_authority': False, 'verified': False}


def _cloud_call(entry, job, identity, text, minimum, budget):
    """Existing admission and reservation validation; no secrets or execution."""
    if (type(entry) is not dict or entry.get('enabled') is not True
            or entry.get('qualification_status') != 'QUALIFIED'
            or entry.get('provider_kind', 'chat_completions') not in {'huggingface', 'chat_completions'}
            or entry.get('location') != 'cloud' or entry.get('tier') not in Tier.__members__
            or Tier[entry['tier']] < minimum or type(job) is not dict
            or job.get('prompt') != text or job.get('preferred_provider') != entry.get('id')
            or job.get('allow_cloud') not in (1, True)
            or type(job.get('allow_cloud')) not in (int, bool)
            or type(entry.get('max_retries', 0)) is not int or entry.get('max_retries', 0) != 0
            or type(job.get('max_retries', 0)) is not int or job.get('max_retries', 0) != 0
            or type(job.get('timeout_seconds')) not in (int, float)
            or not math.isfinite(job['timeout_seconds']) or not 0 < job['timeout_seconds'] <= 300
            or any(k in entry for k in ('api_key', 'secret', 'credential', 'password', 'token'))
            or not classify_for_cloud(job.get('data_classification'), text)):
        _reject('CLOUD_ADMISSION_REQUIRED')
    try:
        if entry.get('provider_kind') == 'huggingface':
            if (entry.get('endpoint') != HuggingFaceProvider.ENDPOINT
                    or entry.get('secret_ref') not in {'env:HF_TOKEN', 'file:HF_TOKEN'}
                    or type(entry.get('model')) is not str
                    or HuggingFaceProvider._PINNED_MODEL.fullmatch(entry['model']) is None):
                _reject('CLOUD_ADMISSION_REQUIRED')
        else:
            reference = entry.get('secret_ref')
            if (type(reference) is not str or re.fullmatch(r'env:[A-Z][A-Z0-9_]{0,127}', reference) is None
                    or reference == 'env:HF_TOKEN'):
                _reject('CLOUD_ADMISSION_REQUIRED')
            # Existing constructor validates HTTPS/credential-free endpoint. It
            # does not resolve this injected dummy resolver or perform network I/O.
            ChatCompletionProvider(entry['endpoint'], reference, secret_resolver=lambda _: None)
        require_hf_task_scope(entry, job)
        require_hf_admission(entry, job, entry['id'])
        spec = model_spec(entry)
        if spec.input_usd_million is None or spec.output_usd_million is None:
            _reject('CLOUD_PRICE_REQUIRED')
        reasoning = select_budget(entry, job, spec)
        verify_reserved_cost(reasoning, job, [{'role': 'user', 'content': text}])
        reserved, ceiling = _money(job['estimated_cost_usd']), _money(job['max_cost_usd'])
        upper = len(text.encode()) + 16
        estimate = (Decimal(upper) * max(spec.input_usd_million, spec.cached_usd_million or spec.input_usd_million)
                    + Decimal(reasoning.output_tokens) * spec.output_usd_million) / Decimal(1_000_000)
        if upper + reasoning.output_tokens > reasoning.model.context_tokens or estimate > min(reserved, ceiling):
            _reject('CLOUD_BUDGET_REQUIRED')
        if reserved <= 0 or ceiling < reserved or reserved > budget.max_call_cost_usd:
            _reject('CLOUD_BUDGET_REQUIRED')
        bound = deepcopy(entry)
        saved_job = deepcopy(job)
        binding = _fingerprint({'entry': bound, 'job': saved_job})
    except RouterRejected:
        raise
    except (ProviderFailure, OSError, ValueError, TypeError, KeyError, AttributeError, InvalidOperation):
        _reject('CLOUD_ADMISSION_REQUIRED')
    return PlannedCall(entry['id'], spec.name, identity, 'cloud', Tier[entry['tier']],
                       reserved, binding, hashlib.sha256(text.encode()).hexdigest(), bound, saved_job)


def build_plan(mode, *, local_backends: tuple[Backend, ...], catalog: list[dict],
               minimum_tier: Tier, classification: str, text: str,
               budget: ExecutionBudget, primary_id: str | None = None,
               selected_ids: tuple[str, ...] = (), underlying_model_ids: Mapping[str, str] | None = None,
               cloud_jobs: Mapping[str, dict] | None = None, local_saturated: bool = False,
               provider_authorized: bool = False, disclosure_authorized: bool = False,
               cost_authorized: bool = False) -> RoutingPlan:
    """Plan over domain-owned inputs without creating permission or reservations.

    Multi-model routes require protected explicit underlying identity metadata.
    Identity metadata is not independently attested by this function. Every cloud
    route needs a separate admitted persisted job; this function never relabels a
    task, chooses a new credential, fabricates a job or modifies its reservation.
    """
    try:
        mode = Mode(mode)
    except (ValueError, TypeError):
        _reject('INVALID_MODE')
    if (not isinstance(minimum_tier, Tier) or classification not in CLASSIFICATIONS
            or type(text) is not str or not 1 <= len(text) <= 120_000
            or not isinstance(budget, ExecutionBudget) or type(local_backends) is not tuple
            or type(catalog) is not list or len(catalog) > 32
            or type(selected_ids) is not tuple or len(selected_ids) > budget.max_calls
            or any(type(x) is not str or not x for x in selected_ids)
            or len(set(selected_ids)) != len(selected_ids)
            or any(type(x) is not bool for x in (local_saturated, provider_authorized,
                                               disclosure_authorized, cost_authorized))):
        _reject('INVALID_ROUTING_INPUT')
    identities = underlying_model_ids or {}
    jobs = cloud_jobs or {}
    if (not isinstance(identities, Mapping) or not isinstance(jobs, Mapping)
            or any(type(k) is not str or type(v) is not str or not 1 <= len(v) <= 256
                   or any(ord(ch) < 32 for ch in v) for k, v in identities.items())):
        _reject('INVALID_MODEL_IDENTITY')
    digest = hashlib.sha256(text.encode()).hexdigest()
    candidates = {}
    seen = set()
    for backend in local_backends:
        if (not isinstance(backend, Backend) or type(backend.name) is not str or not backend.name
                or type(backend.model) is not str or not backend.model or backend.location != 'local'
                or not isinstance(backend.tier, Tier) or type(backend.available) is not bool
                or backend.name in seen):
            _reject('INVALID_LOCAL_METADATA')
        seen.add(backend.name)
        if backend.available and backend.tier >= minimum_tier and not local_saturated:
            entry = {'id': backend.name, 'model': backend.model, 'tier': backend.tier.name,
                     'location': 'local', 'available': True}
            candidates[backend.name] = PlannedCall(backend.name, backend.model, identities.get(backend.name),
                'local', backend.tier, Decimal('0'), _fingerprint(entry), digest, entry, None)
    cloud_allowed = (provider_authorized and disclosure_authorized and cost_authorized
                     and classify_for_cloud(classification, text))
    cloud_errors = {}
    for entry in catalog:
        if type(entry) is not dict or type(entry.get('id')) is not str or not entry['id'] or entry['id'] in seen:
            _reject('INVALID_CATALOG_METADATA')
        seen.add(entry['id'])
        if entry.get('location') != 'cloud' or not cloud_allowed:
            continue
        try:
            candidates[entry['id']] = _cloud_call(entry, jobs.get(entry['id']), identities.get(entry['id']),
                                                text, minimum_tier, budget)
        except RouterRejected as exc:
            # One unavailable route must not collapse unrelated valid local routes.
            cloud_errors[entry['id']] = str(exc)
    order = sorted(candidates.values(), key=lambda c: (c.tier, c.location != 'local', c.provider_id))
    if mode in {Mode.PRIMARY, Mode.VERIFY} and (type(primary_id) is not str or not primary_id):
        _reject('PRIMARY_REQUIRED')
    if primary_id is not None and (type(primary_id) is not str or not primary_id):
        _reject('PRIMARY_REQUIRED')
    if mode == Mode.LOCAL:
        order = [c for c in order if c.location == 'local']
    elif mode == Mode.CLOUD:
        order = [c for c in order if c.location == 'cloud']
    if mode == Mode.PRIMARY:
        order = [c for c in order if c.provider_id == primary_id]
    elif primary_id is not None and primary_id in {c.provider_id for c in order}:
        order.sort(key=lambda c: c.provider_id != primary_id)
    if mode in {Mode.AUTO, Mode.PRIMARY, Mode.CLOUD, Mode.LOCAL}:
        if selected_ids:
            _reject('SINGLE_MODE_SELECTION_CONFLICT')
        calls = order[:1]
    else:
        if selected_ids:
            if any(x not in candidates for x in selected_ids):
                _reject('SELECTED_MODEL_UNAVAILABLE')
            calls = [candidates[x] for x in selected_ids]
        else:
            calls = []
            models = set()
            for c in order:
                if c.underlying_model_id and c.underlying_model_id not in models:
                    calls.append(c)
                    models.add(c.underlying_model_id)
                if len(calls) >= (2 if mode == Mode.VERIFY else budget.max_calls):
                    break
        if len(calls) > budget.max_calls or not _distinct(calls):
            _reject('DISTINCT_MODELS_UNAVAILABLE')
        if mode == Mode.VERIFY and (len(calls) != 2 or calls[0].provider_id != primary_id):
            _reject('VERIFIER_SELECTION_INVALID')
    if not calls:
        _reject('MODEL_UNAVAILABLE')
    if sum((c.reserved_cost_usd for c in calls), Decimal('0')) > budget.max_total_cost_usd:
        _reject('TOTAL_BUDGET_EXCEEDED')
    return RoutingPlan(mode, tuple(calls), budget, digest)


@dataclass(frozen=True)
class ModelOutput:
    provider_id: str
    model: str
    underlying_model_id: str | None
    text: str = field(repr=False)
    evidence_ref: str | None = field(default=None, repr=False)
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    cost_usd: Decimal | None = None


@dataclass(frozen=True)
class ExecutionResult:
    outputs: tuple[ModelOutput, ...] = field(repr=False)
    receipt: dict


def _validate_output(output, call, budget):
    if (not isinstance(output, ModelOutput) or output.provider_id != call.provider_id
            or output.model != call.model or output.underlying_model_id != call.underlying_model_id):
        _reject('RESULT_IDENTITY_MISMATCH')
    if type(output.text) is not str or not 1 <= len(output.text.encode()) <= 1_000_000:
        _reject('RESULT_FORMAT_INVALID')
    if (output.evidence_ref is not None and (type(output.evidence_ref) is not str
            or not 1 <= len(output.evidence_ref) <= 256 or '\n' in output.evidence_ref or '\r' in output.evidence_ref)):
        _reject('RESULT_PROVENANCE_INVALID')
    if any(x is not None and (type(x) is not int or x < 0) for x in
           (output.input_tokens, output.output_tokens, output.cached_tokens)):
        _reject('RESULT_ACCOUNTING_INVALID')
    if output.cached_tokens is not None and (output.input_tokens is None or output.cached_tokens > output.input_tokens):
        _reject('RESULT_ACCOUNTING_INVALID')
    if call.location == 'cloud':
        reasoning = select_budget(call.entry, call.job, model_spec(call.entry))
        if (output.input_tokens is not None and output.input_tokens > reasoning.model.context_tokens
                or output.output_tokens is not None and output.output_tokens > reasoning.output_tokens
                or output.input_tokens is not None and output.output_tokens is not None
                and output.input_tokens + output.output_tokens > reasoning.model.context_tokens):
            _reject('RESULT_ACCOUNTING_EXCEEDED')
    if output.cost_usd is not None:
        cost = _money(output.cost_usd)
        # Local calls have no fee reservation or verified electricity/hardware
        # price contract. Do not invent priced authority from a callback claim.
        if call.location == 'local' and cost != 0:
            _reject('RESULT_ACCOUNTING_INVALID')
        if cost > budget.max_call_cost_usd or (call.location == 'cloud' and cost > call.reserved_cost_usd):
            _reject('RESULT_ACCOUNTING_EXCEEDED')
        if call.location == 'cloud':
            derived = Usage(output.input_tokens, output.output_tokens, output.cached_tokens).cost(model_spec(call.entry))
            if derived is None or cost != derived:
                _reject('RESULT_ACCOUNTING_INVALID')
    return output


def execute_plan(plan: RoutingPlan, *, text: str, authorize: Callable,
                 invoke: Callable, cancelled: Callable = lambda: False) -> ExecutionResult:
    """No replay. Callback contract: honor deadline/cancel, preserve uncertainty.

    invoke(call, text, deadline_monotonic, cancellation_event) must use an existing
    governed path; authorize(call) must re-read current domain authority and must
    return literal True. A timed-out callback cannot be forcibly killed by Python:
    pending work is explicitly UNCERTAIN, never retried or falsely called stopped.
    """
    try:
        digest = hashlib.sha256(text.encode()).hexdigest() if type(text) is str else None
    except UnicodeError:
        digest = None
    if (not isinstance(plan, RoutingPlan) or digest is None or digest != plan.prompt_sha256
            or not isinstance(plan.mode, Mode) or not isinstance(plan.budget, ExecutionBudget)
            or type(plan.calls) is not tuple or not 1 <= len(plan.calls) <= plan.budget.max_calls
            or plan.grants_execution_authority is not False or plan.verified is not False
            or any(not isinstance(c, PlannedCall) or c.prompt_sha256 != digest for c in plan.calls)
            or not callable(authorize) or not callable(invoke) or not callable(cancelled)):
        _reject('EXECUTION_BINDING_INVALID')
    if sum((c.reserved_cost_usd for c in plan.calls), Decimal('0')) > plan.budget.max_total_cost_usd:
        _reject('TOTAL_BUDGET_EXCEEDED')
    if len({c.provider_id for c in plan.calls}) != len(plan.calls) or (
            plan.mode in {Mode.AUTO, Mode.PRIMARY, Mode.CLOUD, Mode.LOCAL} and len(plan.calls) != 1):
        _reject('EXECUTION_BINDING_INVALID')
    if plan.mode in {Mode.VERIFY, Mode.CONSENSUS, Mode.FANOUT} and not _distinct(plan.calls):
        _reject('DISTINCT_MODELS_UNAVAILABLE')
    started = time.monotonic()
    deadline = started + plan.budget.max_elapsed_seconds
    stop = threading.Event()
    records = {}
    outputs = {}
    invoke_started = [False] * len(plan.calls)
    pool = ThreadPoolExecutor(max_workers=plan.budget.max_parallel, thread_name_prefix='model-router')
    pending = {}
    next_call = 0
    def one(index, call):
        if stop.is_set() or time.monotonic() >= deadline:
            _reject('DEADLINE_EXCEEDED')
        if authorize(call) is not True:
            _reject('AUTHORIZATION_DENIED')
        expected_binding = (_fingerprint({'entry': call.entry, 'job': call.job})
                            if call.location == 'cloud' else _fingerprint(call.entry))
        if expected_binding != call.binding_sha256:
            _reject('PLANNED_BINDING_CHANGED')
        if call.location == 'cloud':
            renewed = _cloud_call(call.entry, call.job, call.underlying_model_id, text, call.tier, plan.budget)
            if renewed != call:
                _reject('PLANNED_BINDING_CHANGED')
        elif (call.location != 'local' or call.entry != {'id': call.provider_id, 'model': call.model,
                'tier': call.tier.name, 'location': 'local', 'available': True}
              or call.job is not None or call.reserved_cost_usd != Decimal('0')):
            _reject('PLANNED_BINDING_CHANGED')
        if stop.is_set() or time.monotonic() >= deadline:
            _reject('DEADLINE_EXCEEDED')
        call_deadline = min(deadline, time.monotonic() + plan.budget.per_call_seconds)
        invoke_started[index] = True
        result = invoke(call, text, call_deadline, stop)
        return result, not stop.is_set() and time.monotonic() <= call_deadline
    try:
        while next_call < len(plan.calls) or pending:
            try:
                owner_cancelled = cancelled()
            except Exception:
                owner_cancelled = True
            if type(owner_cancelled) is not bool or owner_cancelled or time.monotonic() >= deadline:
                stop.set()
                break
            while next_call < len(plan.calls) and len(pending) < plan.budget.max_parallel:
                call = plan.calls[next_call]
                pending[pool.submit(one, next_call, call)] = next_call
                next_call += 1
            done, _ = wait(pending, timeout=min(.02, max(0, deadline-time.monotonic())),
                           return_when=FIRST_COMPLETED)
            for future in done:
                index = pending.pop(future)
                call = plan.calls[index]
                observation = {}
                returned = False
                try:
                    output, on_time = future.result()
                    returned = True
                    # Preserve bounded output hashes even if a returned identity
                    # or accounting value fails acceptance. Never expose raw text.
                    if isinstance(output, ModelOutput) and type(output.text) is str:
                        raw = output.text.encode('utf-8')
                        if len(raw) <= 1_000_000:
                            observation = {'observed_result_sha256': hashlib.sha256(raw).hexdigest(),
                                           'observed_result_bytes': len(raw), 'observation_accepted': False}
                    if not on_time:
                        _reject('COMPLETION_AFTER_DEADLINE')
                    output = _validate_output(output, call, plan.budget)
                    outputs[index] = output
                    records[index] = {'status': 'COMPLETED', 'result_sha256': hashlib.sha256(output.text.encode()).hexdigest(),
                                      'evidence_ref_sha256': None if output.evidence_ref is None else hashlib.sha256(output.evidence_ref.encode()).hexdigest(),
                                      'accounting': 'KNOWN' if output.cost_usd is not None else 'UNKNOWN',
                                      'input_tokens': output.input_tokens,
                                      'output_tokens': output.output_tokens,
                                      'cached_tokens': output.cached_tokens,
                                      'cost_scope': 'CATALOG_RATE_COMPUTED_NOT_INDEPENDENT_BILL' if call.location == 'cloud' else 'CALLER_REPORTED_NOT_HARDWARE_ENERGY_COST',
                                      'cost_usd': None if output.cost_usd is None else str(output.cost_usd)}
                except ProviderFailure as exc:
                    # Existing transport classification is necessary: a timeout,
                    # partial/ambiguous fault or malformed pre_execution marker
                    # cannot imply stopped work or released accounting.
                    code = exc.code if type(exc.code) is str and exc.code in _SAFE_PROVIDER_CODES else 'UNKNOWN_PROVIDER_FAILURE'
                    rejected = exc.pre_execution is True and code in _REJECTED_PROVIDER_CODES
                    records[index] = {'status': 'FAILED' if rejected else 'UNCERTAIN', 'error': code,
                                      'provider_admission_rejected': rejected,
                                      'reservation_release_proved': False, **observation}
                except RouterRejected as exc:
                    # Only our fixed public codes can escape; callback exceptions
                    # of the same type are not trusted diagnostic messages.
                    code = str(exc) if str(exc) in {'DEADLINE_EXCEEDED','AUTHORIZATION_DENIED',
                        'COMPLETION_AFTER_DEADLINE','RESULT_IDENTITY_MISMATCH','RESULT_FORMAT_INVALID',
                        'RESULT_PROVENANCE_INVALID','RESULT_ACCOUNTING_INVALID','RESULT_ACCOUNTING_EXCEEDED',
                        'INVALID_COST_BOUND','PLANNED_BINDING_CHANGED','CLOUD_ADMISSION_REQUIRED',
                        'CLOUD_PRICE_REQUIRED','CLOUD_BUDGET_REQUIRED'} else 'CALLBACK_FAILURE'
                    records[index] = {'status': 'UNCERTAIN' if invoke_started[index] and not returned else 'FAILED',
                                      'error': code, 'reservation_release_proved': False, **observation}
                except Exception:
                    records[index] = {'status': 'UNCERTAIN' if invoke_started[index] and not returned else 'FAILED',
                                      'error': 'CALLBACK_FAILURE', 'reservation_release_proved': False, **observation}
        for future, index in pending.items():
            cancelled_before_start = future.cancel()
            records[index] = {'status': 'NOT_STARTED' if cancelled_before_start else 'UNCERTAIN',
                              'error': 'CANCELLED_OR_DEADLINE', 'reservation_release_proved': False}
        for index in range(next_call, len(plan.calls)):
            records[index] = {'status': 'NOT_STARTED', 'error': 'CANCELLED_OR_DEADLINE'}
    finally:
        stop.set()
        pool.shutdown(wait=False, cancel_futures=True)
    safe = [{**{'provider_id': call.provider_id, 'model': call.model,
                'underlying_model_id': call.underlying_model_id, 'binding_sha256': call.binding_sha256},
             **records[index]} for index, call in enumerate(plan.calls)]
    completed = tuple(outputs[index] for index in sorted(outputs))
    normalized = [unicodedata.normalize('NFC', x.text).replace('\r\n', '\n') for x in completed]
    receipt = {'schema': 'prime.model-router-execution.v1', 'trace_id': str(uuid.uuid4()),
               'mode': plan.mode.value, 'calls': safe, 'completed': len(completed),
               'attempted_callback_slots': next_call, 'elapsed_seconds': time.monotonic()-started,
               'uncertain_work': any(x['status'] == 'UNCERTAIN' for x in safe),
               'normalized_outputs_equal': len(normalized) >= 2 and len(set(normalized)) == 1,
               'comparison_scope': 'NFC_AND_CRLF_ONLY_NOT_TRUTH_OR_SEMANTIC_VERIFICATION',
               'verified': False, 'grants_execution_authority': False, 'retries': 0}
    return ExecutionResult(completed, receipt)
