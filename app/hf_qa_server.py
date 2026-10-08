"""Trusted, optional HF QA integration with the existing Model Fabric queue.

Direct serverless QA requires a real expiring maximum-charge contract. Explicit
Router-only QA instead uses the selected operator catalog's token prices and
question-answering scope. No default price, allowance or qualification is
invented. Requests cannot supply admission/executors or price authority.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from time import monotonic
import hashlib
import json
import re

from .client_auth import authenticate_owner
from .compute_catalog import load_catalog, model_spec
from .hf_admission import require_hf_task_scope, require_hf_admission
from .hf_qa_execution import (QAReservation, execute_direct_qa, qa_router_prompt,
                              validate_qa_identity, validate_router_span)
from .hf_serverless import HFServerlessQA
from .job_queue import Provider
from .provider_runtime import ProviderFailure
from . import cloud_execution


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _contract(entry):
    """A catalog assertion needs operator price evidence and a finite expiry.

    v1 bounds are the fixed HFServerlessQA model/endpoint, at most 2048 context
    bytes and 256 question bytes, one request, and no retry. The evidence digest
    references the actual commercial maximum-charge agreement, not a token rate
    or a claim that HF's unmetered task is free.
    """
    try:
        value = entry['serverless_qa']
        if (type(value) is not dict or set(value) != {'version', 'model',
                'maximum_charge_usd', 'price_contract_sha256', 'valid_until_utc',
                'router_fallback'} or value['version'] != 'hf-serverless-qa.price.v1'
                or value['model'] != HFServerlessQA.MODEL
                or type(value['router_fallback']) is not bool
                or type(value['maximum_charge_usd']) is not str
                or type(value['price_contract_sha256']) is not str
                or re.fullmatch('[0-9a-f]{64}', value['price_contract_sha256']) is None):
            raise ValueError()
        charge = Decimal(value['maximum_charge_usd'])
        expiry = datetime.fromisoformat(value['valid_until_utc'])
        if (not charge.is_finite() or charge <= 0 or expiry.utcoffset() is None
                or expiry <= datetime.now(timezone.utc)):
            raise ValueError()
        return value, charge
    except (KeyError, ValueError, TypeError, ArithmeticError):
        raise ProviderFailure('QA_PRICE_CONTRACT_UNAVAILABLE', pre_execution=True) from None


def _entry(provider_id):
    entries = [item for item in load_catalog() if item['id'] == provider_id]
    if (len(entries) != 1 or entries[0].get('provider_kind') != 'huggingface'
            or entries[0].get('location') != 'cloud' or not entries[0].get('enabled')
            or entries[0].get('qualification_status') != 'QUALIFIED'):
        raise ProviderFailure('PROVIDER_UNQUALIFIED', pre_execution=True)
    return deepcopy(entries[0])


def execute_governed_router_qa(*, authorization, queue, data, available_providers,
        provider_id, agent_id, task_id, context, question, data_classification,
        max_cost_usd, timeout_seconds=30, primary_timeout_seconds=15):
    """One explicit token-metered HF Router request; no serverless attempt."""
    authenticate_owner(authorization)
    ceiling = validate_qa_identity(agent_id, task_id, max_cost_usd)
    HFServerlessQA.validate_request(context=context, question=question,
        data_classification=data_classification, timeout_seconds=timeout_seconds)
    deadline = monotonic() + timeout_seconds
    selected = _entry(provider_id)
    if selected.get('fallback_ids'):
        raise ProviderFailure('QA_ROUTER_CHAIN_DENIED', pre_execution=True)
    prompt = qa_router_prompt(context, question)
    scope = {'agent': agent_id, 'prompt': prompt, 'task_class': 'question_answering'}
    require_hf_task_scope(selected, scope)
    spec = model_spec(selected)
    matches = [p for p in available_providers if p.name == provider_id and p.kind == 'cloud'
               and p.model == spec.name]
    if (len(matches) != 1 or spec.input_usd_million is None or spec.output_usd_million is None
            or len(prompt.encode()) + 16 + spec.output_tokens > spec.context_tokens):
        raise ProviderFailure('QA_ROUTER_BUDGET_INVALID', pre_execution=True)
    provider = Provider(provider_id, 'cloud', spec.name, 0, 0,
        int(selected.get('concurrency', 1)),
        float(max(spec.input_usd_million, spec.cached_usd_million or spec.input_usd_million)),
        float(spec.output_usd_million), spec.output_tokens, True)
    selected_digest = _digest(selected)
    binding = {'schema': 'prime.hf-router-qa-admission.v1', 'agent_id': agent_id,
        'task_id': task_id, 'task': 'question-answering', 'task_class': 'question_answering',
        'provider_id': provider_id, 'model': spec.name, 'data_classification': data_classification,
        'context_sha256': hashlib.sha256(context.encode()).hexdigest(),
        'question_sha256': hashlib.sha256(question.encode()).hexdigest(),
        'max_cost_usd': str(ceiling), 'deadline_monotonic': deadline,
        'catalog_sha256': selected_digest}
    binding_digest = _digest(binding)
    job = None
    entered = False
    result = None
    failure = None

    def revalidate():
        current = _entry(provider_id)
        if _digest(current) != selected_digest:
            raise ProviderFailure('QA_CATALOG_CHANGED', pre_execution=True)
        require_hf_task_scope(current, scope)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ProviderFailure('TASK_TIMEOUT')
        return remaining

    def cancelled():
        return queue.get(job['id'])['status'] == 'cancelled'

    try:
        revalidate()
        cap = min(ceiling, Decimal(str(queue.policy.max_job_cost_usd)))
        try:
            job = queue.reserve_cloud_chain(agent=agent_id, requests=[{
                'provider': provider, 'prompt': prompt, 'max_cost_usd': str(cap)}],
                timeout_seconds=timeout_seconds, task_class='question_answering', binding={
                    'parent_task_id': task_id, 'request_binding_sha256': binding_digest,
                    'catalog_sha256': selected_digest})[0]
        except (ValueError, ArithmeticError):
            raise ProviderFailure('QA_BUDGET_NOT_RESERVED', pre_execution=True) from None
        revalidate()
        claimed = queue.claim('hf-router-qa', [provider], held_job_id=job['id'])
        if claimed is None:
            raise ProviderFailure('CAPACITY', pre_execution=True)
        job = claimed
        job['timeout_seconds'] = min(job['timeout_seconds'], revalidate())
        if cancelled():
            raise ProviderFailure('CANCELLED')
        entered = True
        result = cloud_execution.execute_cloud(job, provider, data, cancelled,
            include_identity=True, expected_entry=selected)
        if cancelled():
            raise ProviderFailure('CANCELLED')
        if monotonic() >= deadline:
            raise ProviderFailure('TASK_TIMEOUT')
        if result.get('provider') != provider_id or result.get('model') != spec.name:
            raise ProviderFailure('QA_ROUTER_IDENTITY_MISMATCH')
        start, end = validate_router_span(result.get('result'), context)
        try:
            charge = Decimal(str(result['actual_cost_usd']))
            if not charge.is_finite() or not 0 <= charge <= min(cap, Decimal(str(job['estimated_cost_usd']))):
                raise ValueError()
        except (KeyError, ValueError, TypeError, ArithmeticError):
            raise ProviderFailure('QA_ROUTER_COST_NOT_VERIFIED') from None
        return {'answer': result['result'], 'start': start, 'end': end,
            'provider': provider_id, 'model': spec.name, 'route': 'HF_ROUTER_QA',
            'task_class': 'question_answering', 'agent_id': agent_id, 'task_id': task_id,
            'router_task_id': job['id'], 'reservation_id': job['id'],
            'request_binding_sha256': binding_digest, 'catalog_sha256': selected_digest,
            'input_tokens': result['input_tokens'], 'output_tokens': result['output_tokens'],
            'cost_usd': float(charge), 'cost_measurement': 'USAGE_X_CATALOG_RATES_NOT_INVOICE',
            'span_validation': 'MATCHES_INPUT_CONTEXT', 'quality_oracle': 'CALLER_VERIFICATION_REQUIRED',
            'direct_qa_attempted': False, 'retries': 0, 'automatic_qualification': False,
            'l7_awarded': False}
    except ProviderFailure as exc:
        failure = exc
        raise
    except Exception:
        failure = ProviderFailure('QA_ROUTER_EXECUTION_FAILURE')
        raise failure from None
    finally:
        if job is not None:
            current = queue.get(job['id'])
            if current['status'] == 'held':
                queue.cancel(job['id'])
            elif current['status'] == 'running' or current['cloud_inflight']:
                # Only never-entered execution proves zero. Generic final error
                # flags cannot erase dispatched usage or an unknown reservation.
                queue.finish(job['id'], result=result.get('result', '') if result else '',
                    error=failure.code if failure else '', retryable=False,
                    actual_cost_usd=result['actual_cost_usd'] if result else (None if entered else 0),
                    input_tokens=result['input_tokens'] if result else None,
                    output_tokens=result['output_tokens'] if result else None)


def execute_governed_qa(*, authorization, queue, data, available_providers,
                        provider_id, **request):
    """One bounded worker request; all authority/callbacks are server-owned."""
    authenticate_owner(authorization)
    # Validate byte bounds/locality and UTF-8 before constructing or sizing the
    # router prompt. Pydantic strings can contain escaped lone surrogates.
    HFServerlessQA.validate_request(context=request['context'], question=request['question'],
        data_classification=request['data_classification'],
        timeout_seconds=request.get('timeout_seconds', 30))
    selected = _entry(provider_id)
    contract, direct_charge = _contract(selected)
    # This adapter has one explicitly selected alternate. Catalog fallback
    # chains require their own general cloud path and cannot widen this request.
    if selected.get('fallback_ids'):
        raise ProviderFailure('QA_ROUTER_CHAIN_DENIED', pre_execution=True)
    selected_digest = _digest(selected)
    prompt = qa_router_prompt(request['context'], request['question'])
    permit = None
    jobs = []
    direct_authority_delivered = False
    router_executor_entered = False
    providers = list(available_providers)
    direct = Provider(HFServerlessQA.CIRCUIT_ID, 'cloud', HFServerlessQA.MODEL,
                      0, 0, 1, explicit_selection_required=True,
                      maximum_charge_usd=str(direct_charge))
    providers.append(direct)
    router_provider = None
    if contract['router_fallback']:
        matches = [p for p in providers if p.name == provider_id and p.kind == 'cloud'
                   and p.model == selected['model']]
        if len(matches) != 1:
            raise ProviderFailure('QA_ROUTER_UNAVAILABLE', pre_execution=True)
        spec = model_spec(selected)
        if (spec.input_usd_million is None or spec.output_usd_million is None
                or len(prompt.encode()) + 16 + spec.output_tokens > spec.context_tokens):
            raise ProviderFailure('QA_ROUTER_BUDGET_INVALID', pre_execution=True)
        # Rebuild from the same pinned catalog snapshot used for admission;
        # an earlier providers() read cannot establish current rates/caps.
        router_provider = Provider(provider_id, 'cloud', spec.name, 0, 0,
            int(selected.get('concurrency', 1)),
            float(max(spec.input_usd_million, spec.cached_usd_million or spec.input_usd_million)),
            float(spec.output_usd_million), spec.output_tokens, True)
        providers = [p for p in providers if p.name != provider_id] + [router_provider]

    def revalidate(binding):
        current = _entry(provider_id)
        _contract(current)
        if _digest(current) != selected_digest:
            raise ProviderFailure('QA_CATALOG_CHANGED', pre_execution=True)
        require_hf_task_scope(current, {'agent': binding['agent_id'], 'prompt': prompt,
                                      'task_class': 'classification'})

    def admit(binding, previous, phase):
        nonlocal permit, jobs, direct_authority_delivered
        revalidate(binding)
        if phase == 'reserve':
            router_charge = (Decimal(str(queue.estimate_cost({'prompt': prompt}, router_provider)))
                             if router_provider is not None else Decimal(0))
            if direct_charge + router_charge > Decimal(binding['max_cost_usd']):
                raise ProviderFailure('QA_BUDGET_NOT_RESERVED', pre_execution=True)
            chain = [{'provider': direct, 'prompt': prompt, 'max_cost_usd': str(direct_charge)}]
            if router_provider is not None:
                chain.append({'provider': router_provider, 'prompt': prompt,
                              'max_cost_usd': str(router_charge)})
            jobs = queue.reserve_cloud_chain(agent=binding['agent_id'], requests=chain,
                timeout_seconds=request.get('timeout_seconds', 30), binding={
                    'request_binding_sha256': _digest(binding),
                    'parent_task_id': binding['task_id'],
                    'price_contract_sha256': contract['price_contract_sha256']})
            permit = QAReservation(jobs[0]['id'], _digest(binding),
                contract['price_contract_sha256'], binding['deadline_monotonic'],
                str(direct_charge), str(router_charge),
                provider_id if router_provider else None,
                selected['model'] if router_provider else None)
        elif previous != permit or not jobs:
            raise ProviderFailure('QA_BUDGET_NOT_RESERVED', pre_execution=True)
        elif phase == 'direct':
            claimed = queue.claim('hf-qa-direct', providers, held_job_id=jobs[0]['id'])
            if claimed is None:
                raise ProviderFailure('CAPACITY', pre_execution=True)
            jobs[0] = claimed
            # An atomic SQLite claim can wait past the price-contract expiry.
            # Admission authority is not delivered until the pinned contract
            # and scope are revalidated after that wait.
            revalidate(binding)
            direct_authority_delivered = True
        elif phase == 'hf_router':
            require_hf_admission(selected, queue.get(jobs[1]['id']), provider_id)
        else:
            raise ProviderFailure('QA_ADMISSION_PHASE_INVALID', pre_execution=True)
        return permit

    def record_direct_rejection(*, binding, reservation, code):
        if (reservation != permit or not jobs or _digest(binding) != permit.binding_sha256):
            raise ProviderFailure('QA_BUDGET_NOT_RESERVED')
        # The fixed wrapper invokes this only at the direct attempt's clean
        # transport/circuit/credential rejection, including when no alternate
        # exists. Later state/guard failures cannot fabricate this evidence.
        queue.finish(jobs[0]['id'], error=code, retryable=False, actual_cost_usd=0,
                     input_tokens=None, output_tokens=None)

    def execute_router(*, prompt, binding, request_binding_sha256, reservation,
                       timeout_seconds, cancelled):
        nonlocal router_executor_entered
        revalidate(binding)
        if (reservation != permit or request_binding_sha256 != permit.binding_sha256
                or len(jobs) != 2 or prompt != jobs[1]['prompt']):
            raise ProviderFailure('QA_BUDGET_NOT_RESERVED', pre_execution=True)
        job = queue.claim('hf-qa-router', providers, held_job_id=jobs[1]['id'])
        if job is None:
            raise ProviderFailure('CAPACITY', pre_execution=True)
        jobs[1] = job
        revalidate(binding)
        # Timeout is the chain's remaining deadline, never a fresh full timeout.
        job['timeout_seconds'] = min(timeout_seconds, job['timeout_seconds'])
        router_executor_entered = True
        result = cloud_execution.execute_cloud(job, router_provider, data,
            lambda: (bool(cancelled and cancelled()) or
                     queue.get(job['id'])['status'] == 'cancelled'), include_identity=True,
            expected_entry=selected)
        queue.finish(job['id'], **{key: result[key] for key in (
            'result', 'input_tokens', 'output_tokens', 'actual_cost_usd')})
        return {**result, 'agent_id': binding['agent_id'], 'parent_task_id': binding['task_id'],
            'task_id': job['id'], 'reservation_id': reservation.reservation_id,
            'request_binding_sha256': request_binding_sha256}

    failure = None
    result = None
    try:
        result = execute_direct_qa(authorization=authorization, admit=admit,
            record_direct_rejection=record_direct_rejection,
            execute_hf_router=execute_router if router_provider else None,
            qa=HFServerlessQA(secret_ref=selected['secret_ref']),
            circuits=cloud_execution.PROVIDER_CIRCUITS,
            cancelled=lambda: any(queue.get(job['id'])['status'] == 'cancelled' for job in jobs),
            **request)
        return result
    except Exception as exc:
        failure = exc
        raise
    finally:
        for index, held in enumerate(jobs):
            job = queue.get(held['id'])
            if job['status'] == 'held':
                queue.cancel(job['id'])  # Proven never dispatched; zero charge.
            elif job['status'] == 'running' or job['cloud_inflight']:
                # No eventual error flag proves an earlier attempt unspent.
                # Only server-owned never-delivered authority proves zero here;
                # affirmative clean direct rejection was settled at its source.
                unspent = not (direct_authority_delivered if index == 0 else router_executor_entered)
                queue.finish(job['id'], result=json.dumps(result) if result and index == 0 else '',
                    error=(failure.code if isinstance(failure, ProviderFailure) else
                           'QA_EXECUTION_FAILED') if failure else '', retryable=False,
                    actual_cost_usd=0 if unspent else None,
                    input_tokens=None, output_tokens=None)
