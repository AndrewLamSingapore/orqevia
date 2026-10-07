"""Task-scoped HF-owned serverless QA transport, not chat qualification.

This optional adapter has no catalog activation, queue, authority, cost approval,
retry or fallback policy. The caller must govern admission/price/disclosure and
validate the answer against its task oracle. A valid source span is not proof of
factual correctness; provider score is not independently measured confidence.
The model ID is allowlisted, not an immutable remote weights/version assertion.
"""
from __future__ import annotations

import asyncio
import json
import math
import time

import httpx

from .provider_runtime import ProviderFailure, capacity_rejection
from .provider_circuit import CircuitRejected, ProviderCircuits
from .secret_refs import resolve_secret
from .tier_router import classify_for_cloud


class HFServerlessQA:
    MODEL = 'deepset/roberta-base-squad2'
    ENDPOINT = 'https://router.huggingface.co/hf-inference/models/' + MODEL
    MAX_CONTEXT_BYTES = 2048
    MAX_QUESTION_BYTES = 256
    MAX_RESPONSE_BYTES = 16384
    CIRCUIT_ID = 'hf-inference-qa'

    def __init__(self, secret_ref='file:HF_TOKEN', *, model=MODEL,
                 secret_resolver=resolve_secret, transport=None):
        if not isinstance(secret_ref, str) or secret_ref not in {'env:HF_TOKEN', 'file:HF_TOKEN'}:
            raise ValueError('HF serverless requires the governed HF_TOKEN reference')
        if model != self.MODEL:
            raise ValueError('HF serverless QA model is not admitted')
        if not callable(secret_resolver):
            raise ValueError('Invalid governed credential resolver')
        self.secret_ref = secret_ref
        self.resolve = secret_resolver
        self.transport = transport

    def _credential(self):
        try:
            value = self.resolve(self.secret_ref)
        except Exception:
            raise ProviderFailure('CREDENTIAL_UNAVAILABLE', pre_execution=True) from None
        if (not isinstance(value, str) or not 1 <= len(value) <= 4096 or
                any(ord(char) < 33 or ord(char) > 126 for char in value)):
            raise ProviderFailure('CREDENTIAL_UNAVAILABLE', pre_execution=True)
        return value

    def health(self):
        try:
            self._credential()
            readiness = 'READY'
        except ProviderFailure:
            readiness = 'CREDENTIAL_UNAVAILABLE'
        return {'readiness': readiness, 'provider_health': 'UNMEASURED',
                'network_probe_performed': False, 'task': 'question-answering',
                'provider': 'hf-inference', 'route': 'DIRECT_HF'}

    @staticmethod
    def _decode(raw):
        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError()
                result[key] = value
            return result
        try:
            return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_keys)
        except (ValueError, UnicodeError, RecursionError):
            raise ProviderFailure('MALFORMED_QA_RESPONSE') from None

    @staticmethod
    def _answer_span(value, context):
        if isinstance(value, list):
            if len(value) != 1:
                raise ProviderFailure('MALFORMED_QA_RESPONSE')
            value = value[0]
        if not isinstance(value, dict):
            raise ProviderFailure('MALFORMED_QA_RESPONSE')
        answer, score = value.get('answer'), value.get('score')
        start, end = value.get('start'), value.get('end')
        try:
            answer_bytes = len(answer.encode('utf-8')) if isinstance(answer, str) else 0
        except UnicodeError:
            raise ProviderFailure('INVALID_QA_ANSWER_SPAN') from None
        if (not isinstance(answer, str) or not answer.strip() or
                answer_bytes > 1024 or type(score) not in (int, float) or
                not 0 <= score <= 1 or not math.isfinite(score) or
                type(start) is not int or type(end) is not int or
                not 0 <= start < end <= len(context) or context[start:end] != answer):
            raise ProviderFailure('INVALID_QA_ANSWER_SPAN')
        return {'answer': answer, 'provider_score': score, 'start': start, 'end': end}

    @classmethod
    def validate_request(cls, *, context, question, data_classification,
                         timeout_seconds=15):
        if (not isinstance(context, str) or not context.strip() or
                not isinstance(question, str) or not question.strip()):
            raise ProviderFailure('INVALID_QA_INPUT', pre_execution=True)
        try:
            context_bytes = len(context.encode('utf-8'))
            question_bytes = len(question.encode('utf-8'))
        except UnicodeError:
            raise ProviderFailure('INVALID_QA_INPUT', pre_execution=True) from None
        if (context_bytes > cls.MAX_CONTEXT_BYTES or
                question_bytes > cls.MAX_QUESTION_BYTES or
                any(ord(char) < 32 and char not in '\n\r\t' for char in context + question)):
            raise ProviderFailure('QA_INPUT_BUDGET_EXCEEDED', pre_execution=True)
        if not classify_for_cloud(data_classification, context + '\n' + question):
            raise ProviderFailure('DATA_LOCALITY', pre_execution=True)
        if (type(timeout_seconds) not in (int, float) or
                not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30):
            raise ProviderFailure('INVALID_TIMEOUT', pre_execution=True)

    @staticmethod
    def _cancelled(callback):
        if callback is None:
            return False
        try:
            value = callback()
        except Exception:
            raise ProviderFailure('CANCELLATION_STATE_UNAVAILABLE', pre_execution=True) from None
        if type(value) is not bool:
            raise ProviderFailure('CANCELLATION_STATE_INVALID', pre_execution=True)
        return value

    async def answer(self, *, context, question, data_classification,
                     timeout_seconds=15, circuits=None, cancelled=None):
        self.validate_request(context=context, question=question,
                              data_classification=data_classification,
                              timeout_seconds=timeout_seconds)
        if cancelled is not None and not callable(cancelled):
            raise ProviderFailure('CANCELLATION_STATE_INVALID', pre_execution=True)
        if circuits is not None and not isinstance(circuits, ProviderCircuits):
            raise ProviderFailure('CIRCUIT_CONFIGURATION_INVALID', pre_execution=True)
        if self._cancelled(cancelled):
            raise ProviderFailure('CANCELLED', pre_execution=True)
        permit = None
        task = None
        try:
            if circuits is not None:
                try:
                    permit = circuits.acquire(self.CIRCUIT_ID)
                except CircuitRejected as exc:
                    raise ProviderFailure(exc.code, pre_execution=True) from None
            recovery_probe = bool(permit and permit.recovery_probe)
            task = asyncio.create_task(self._answer_once(context=context,
                question=question, timeout_seconds=timeout_seconds))
            if cancelled is not None:
                while not task.done():
                    if self._cancelled(cancelled):
                        # Once dispatched, cancellation never proves rejected
                        # provider admission and cannot authorize fallback.
                        raise ProviderFailure('CANCELLED')
                    await asyncio.wait({task}, timeout=.05)
            result = await task
            if self._cancelled(cancelled):
                raise ProviderFailure('CANCELLED')
            if permit is not None:
                circuits.succeed(permit)
                permit = None
            return {**result, 'circuit_recovery_probe': recovery_probe}
        except ProviderFailure as exc:
            if task is not None and self._cancelled(cancelled):
                # Cancellation may race a completed rejection/error. It still
                # cannot authorize replay or count as a provider fault.
                exc = ProviderFailure('CANCELLED')
            if permit is not None:
                circuits.fail(permit, exc.code, pre_execution=exc.pre_execution is True)
                permit = None
            raise exc from None
        finally:
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if permit is not None:
                # Caller cancellation/local faults never claim provider failure
                # or recovery, and release an exclusive half-open permit.
                circuits.abandon(permit)

    async def _answer_once(self, *, context, question, timeout_seconds):
        key = self._credential()
        payload = {'inputs': {'context': context, 'question': question},
                   'parameters': {'top_k': 1, 'max_answer_len': 64,
                                  'handle_impossible_answer': True}}
        started = time.perf_counter()
        try:
            # One request only. No redirect, retry or implicit provider selection.
            async with asyncio.timeout(timeout_seconds):
                async with httpx.AsyncClient(transport=self.transport,
                                             timeout=timeout_seconds,
                                             follow_redirects=False) as client:
                    async with client.stream('POST', self.ENDPOINT,
                                             headers={'Authorization': 'Bearer ' + key},
                                             json=payload) as response:
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(raw) + len(chunk) > self.MAX_RESPONSE_BYTES:
                                raise ProviderFailure('QA_RESPONSE_SIZE_EXCEEDED')
                            raw.extend(chunk)
                        if response.status_code >= 300:
                            if response.status_code in (401, 403):
                                raise ProviderFailure('AUTHENTICATION')
                            if response.status_code in (429, 503):
                                try:
                                    fault = self._decode(raw)
                                    # Contradictory output/usage or malformed
                                    # bodies cannot prove rejected admission.
                                    clean_rejection = (isinstance(fault, dict)
                                        and not any(key in fault for key in (
                                            'answer', 'score', 'start', 'end',
                                            'usage', 'choices', 'generated_text',
                                            'output', 'outputs', 'result')))
                                    rejected = clean_rejection and capacity_rejection(fault)
                                except ProviderFailure:
                                    clean_rejection = False
                                    rejected = False
                                if response.status_code == 429 and clean_rejection:
                                    raise ProviderFailure('RATE_LIMIT', pre_execution=True)
                                if rejected:
                                    raise ProviderFailure('CAPACITY', pre_execution=True)
                            raise ProviderFailure('PROVIDER_HTTP_FAILURE')
                        if response.status_code != 200:
                            raise ProviderFailure('PROVIDER_HTTP_FAILURE')
                        value = self._decode(raw)
                        span = self._answer_span(value, context)
        except TimeoutError:
            raise ProviderFailure('PROVIDER_TIMEOUT') from None
        except httpx.TimeoutException:
            raise ProviderFailure('PROVIDER_TIMEOUT') from None
        except httpx.TransportError:
            raise ProviderFailure('PROVIDER_TRANSPORT_FAILURE') from None
        except ProviderFailure:
            raise
        except Exception:
            raise ProviderFailure('PROVIDER_ADAPTER_FAILURE') from None
        return {**span, 'provider': 'hf-inference', 'route': 'DIRECT_HF',
                'task': 'question-answering', 'model': self.MODEL,
                'latency_ms': round((time.perf_counter() - started) * 1000, 3),
                'span_validation': 'MATCHES_INPUT_CONTEXT',
                'quality_oracle': 'CALLER_VERIFICATION_REQUIRED',
                'input_tokens': None, 'output_tokens': None, 'cost_usd': None,
                'time_to_first_token_ms': None, 'tokens_per_second': None,
                'usage_measurement': 'NOT_EXPOSED', 'retries': 0}
