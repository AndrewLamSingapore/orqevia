"""Bounded anonymous HF metadata discovery; never catalog admission/inference.

Primary contracts: https://huggingface.co/docs/inference-providers/hub-api
and https://huggingface.co/docs/inference-providers/index . Upstream 'live',
prices, modality/feature hints and probe metrics are dated public assertions,
not PRIME health, permission, quality, billing guarantees or qualification.
No token, credential resolver, agent payload, store, SDK or inference is used.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from urllib.parse import urlencode

import httpx

from .provider_runtime import _decode_wire_json


MAX_BYTES = 98304
DEADLINE_SECONDS = 10
MAX_PROVIDER_ROWS = 32
_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z')
_PROVIDER = re.compile(r'[a-z0-9][a-z0-9-]{0,63}\Z')
_TASK = re.compile(r'[a-z][a-z-]{0,63}\Z')
TASKS = frozenset(('text-generation', 'image-text-to-text', 'text-classification',
    'token-classification', 'feature-extraction', 'sentence-similarity',
    'summarization', 'translation', 'question-answering', 'text-to-image',
    'image-to-image', 'image-classification', 'automatic-speech-recognition',
    'text-to-speech', 'text-to-video', 'audio-classification'))
_HUB = 'https://huggingface.co/api/models'
_ROUTER = 'https://router.huggingface.co/v1/models/'


class HFDiscoveryError(RuntimeError):
    """Fixed codes only: untrusted HTTP bodies/exceptions never escape."""


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _number(value, maximum, integer=False):
    if value is None:
        return None
    if (type(value) not in ((int,) if integer else (int, float))
            or not 0 <= value <= maximum or not math.isfinite(value)):
        raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
    return value


def _boolean(value):
    if value is not None and type(value) is not bool:
        raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
    return value


def _provider(value):
    if type(value) is not str or not _PROVIDER.fullmatch(value):
        raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
    return value


def _model(value):
    if type(value) is not str or not _MODEL.fullmatch(value):
        raise HFDiscoveryError('HF_DISCOVERY_MODEL_INVALID')
    return value


def _task(value):
    if value is not None and (type(value) is not str or not _TASK.fullmatch(value)):
        raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
    return value


def _mapping(value):
    """HF Hub list and single-model APIs currently use different wire shapes."""
    if type(value) is dict:
        rows = []
        for provider, fields in value.items():
            if type(fields) is not dict or ('provider' in fields and fields['provider'] != provider):
                raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
            rows.append({'provider': provider, **fields})
    elif type(value) is list:
        rows = value
    elif value is None:
        rows = []
    else:
        raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
    if len(rows) > MAX_PROVIDER_ROWS:
        raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
    projected, seen = [], set()
    for row in rows:
        if type(row) is not dict:
            raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
        provider = _provider(row.get('provider'))
        if provider in seen:
            raise HFDiscoveryError('HF_DISCOVERY_MAPPING_CONFLICT')
        seen.add(provider)
        status = row.get('status')
        if type(status) is not str or status not in {'live', 'staging', 'error'}:
            raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
        provider_id = row.get('providerId')
        if (provider_id is not None and (type(provider_id) is not str
                or not 1 <= len(provider_id) <= 200
                or any(ord(char) < 33 or ord(char) > 126 for char in provider_id))):
            raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
        task = _task(row.get('task'))
        # Task mapping is not proof that a text-only PRIME adapter accepts images/tools.
        projected.append({'provider': provider, 'provider_model_id': provider_id,
            'reported_status': status, 'reported_task': task,
            'prime_adapter_compatibility': ('TEXT_CHAT_SOURCE_ONLY_ADMISSION_REQUIRED' if task == 'conversational'
                else 'QA_SOURCE_ONLY_UNQUALIFIED' if task == 'question-answering'
                else 'NO_ADMITTED_ADAPTER_ESTABLISHED'),
            'prime_qualification': 'UNMEASURED', 'prime_authorization': 'NOT_GRANTED'})
    return sorted(projected, key=lambda row: row['provider'])


def _hub_models(value, limit):
    if type(value) is not list or len(value) > limit:
        raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
    records, seen = [], set()
    for row in value:
        if type(row) is not dict:
            raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
        model = _model(row.get('id'))
        if model in seen:
            raise HFDiscoveryError('HF_DISCOVERY_MAPPING_CONFLICT')
        seen.add(model)
        records.append({'model_id': model, 'reported_pipeline_tag': _task(row.get('pipeline_tag')),
            'providers': _mapping(row.get('inferenceProviderMapping')),
            'prime_qualification': 'UNMEASURED', 'prime_authorization': 'NOT_GRANTED'})
    return records


def _modalities(value):
    if value is None:
        return None
    if (type(value) is not list or not 1 <= len(value) <= 5
            or any(type(item) is not str or item not in {'text', 'image', 'audio', 'video', 'embedding'}
                   for item in value) or len(set(value)) != len(value)):
        raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
    return list(value)


def _router_model(value, expected):
    if type(value) is dict and 'data' in value:
        value = value['data']
    if type(value) is not dict or value.get('id') != expected:
        raise HFDiscoveryError('HF_DISCOVERY_MODEL_BINDING_INVALID')
    architecture = value.get('architecture', {})
    rows = value.get('providers')
    if (type(architecture) is not dict or type(rows) is not list
            or len(rows) > MAX_PROVIDER_ROWS):
        raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
    result, seen = [], set()
    for row in rows:
        if type(row) is not dict:
            raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
        provider = _provider(row.get('provider'))
        if provider in seen:
            raise HFDiscoveryError('HF_DISCOVERY_MAPPING_CONFLICT')
        seen.add(provider)
        if type(row.get('status')) is not str or row['status'] not in {'live', 'error'}:
            raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
        pricing = row.get('pricing', {})
        if type(pricing) is not dict:
            raise HFDiscoveryError('HF_DISCOVERY_METADATA_INVALID')
        result.append({'provider': provider, 'reported_status': row['status'],
            'context_length': _number(row.get('context_length'), 10000000, integer=True),
            'input_usd_million': _number(pricing.get('input'), 1000000),
            'output_usd_million': _number(pricing.get('output'), 1000000),
            'reported_supports_tools': _boolean(row.get('supports_tools')),
            'reported_supports_structured_output': _boolean(row.get('supports_structured_output')),
            'reported_is_free': _boolean(row.get('is_free')),
            'hf_probe_first_token_latency_ms': _number(row.get('first_token_latency_ms'), 3600000),
            'hf_probe_throughput_tokens_per_second': _number(row.get('throughput'), 1000000),
            'prime_qualification': 'UNMEASURED', 'prime_authorization': 'NOT_GRANTED'})
    return {'model_id': expected,
        'reported_input_modalities': _modalities(architecture.get('input_modalities')),
        'reported_output_modalities': _modalities(architecture.get('output_modalities')),
        'providers': sorted(result, key=lambda row: row['provider']),
        'scope': 'CHAT_MODEL_PUBLIC_METADATA_ONLY'}


async def _read(client, url, params=None):
    # Public metadata never needs a session. A Hub Set-Cookie must not become a
    # credential on the optional sibling-domain router request.
    client.cookies.clear()
    async with client.stream('GET', url, params=params,
            headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'}) as response:
        if response.status_code != 200:
            raise HFDiscoveryError('HF_DISCOVERY_HTTP_FAILURE')
        if response.headers.get('content-encoding', '').lower() not in ('', 'identity'):
            raise HFDiscoveryError('HF_DISCOVERY_COMPRESSED_RESPONSE_DENIED')
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            if len(raw) + len(chunk) > MAX_BYTES:
                raise HFDiscoveryError('HF_DISCOVERY_RESPONSE_TOO_LARGE')
            raw.extend(chunk)
        try:
            value = _decode_wire_json(bytes(raw))
        except (ValueError, UnicodeError, TypeError, RecursionError):
            raise HFDiscoveryError('HF_DISCOVERY_JSON_INVALID') from None
        return value, {'source_uri': url + ('?' + urlencode(params) if params else ''),
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'response_sha256': _hash(bytes(raw)), 'response_bytes': len(raw),
            'authentication_used': False, 'network_probe_kind': 'PUBLIC_METADATA_GET_NOT_INFERENCE'}


async def discover_hf(task, *, limit=5, model_id=None, transport=None):
    """One public Hub request, optionally one fixed router metadata request.

    The complete operation has one deadline and no pagination, redirects or
    retries. Even SDK default credential lookup is avoided. Native HF automatic
    inference remains unenabled: its policy documentation is descriptive only.
    An empty filtered list is not a negative provider-health measurement.
    """
    if type(task) is not str or task not in TASKS or type(limit) is not int or not 1 <= limit <= 10:
        raise HFDiscoveryError('HF_DISCOVERY_REQUEST_INVALID')
    if model_id is not None:
        _model(model_id)
    params = [('inference_provider', 'all'), ('pipeline_tag', task), ('limit', str(limit)),
              ('expand', 'inferenceProviderMapping'), ('expand', 'pipeline_tag')]
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            async with httpx.AsyncClient(transport=transport, trust_env=False,
                    follow_redirects=False, timeout=DEADLINE_SECONDS) as client:
                data, source = await _read(client, _HUB, params)
                models = _hub_models(data, limit)
                sources, router = [source], None
                if model_id is not None:
                    data, source = await _read(client, _ROUTER + model_id)
                    router = _router_model(data, model_id)
                    sources.append(source)
        snapshot = {'schema_version': 'jarvis.hf-public-discovery.v1',
            'scope': 'PUBLIC_METADATA_ONLY_NOT_ADMISSION_OR_QUALIFICATION',
            'requested_task': task, 'models': models, 'router_model': router, 'sources': sources,
            'complete_global_inventory': False, 'pagination_followed': False,
            'inference_requests': 0, 'catalog_changes': False,
            'provider_selection_documentation': {
                'source': 'https://huggingface.co/docs/inference-providers/index',
                'sdk_provider_auto': 'DOCUMENTED_DEFAULT_FASTEST_NOT_EXERCISED',
                'rest_default': 'FASTEST', 'rest_policy_suffixes': ['fastest', 'cheapest', 'preferred'],
                'rest_explicit_provider': 'MODEL_ID:PROVIDER', 'rest_auto_suffix': 'NOT_DOCUMENTED',
                'native_dynamic_inference_enabled': False,
                'prime_execution_contract': 'EXISTING_PINNED_QUALIFIED_CATALOG_ADMISSION_UNCHANGED'},
            'upstream_probe_metrics_are_prime_measurements': False,
            'freshness_scope': 'FETCH_TIME_OBSERVED_UPSTREAM_PROBE_TIME_UNKNOWN',
            'health': 'UNMEASURED', 'prime_authorization': 'NOT_GRANTED'}
        return {**snapshot, 'snapshot_sha256': _hash(_canonical(snapshot))}
    except HFDiscoveryError:
        raise
    except (TimeoutError, httpx.TimeoutException):
        raise HFDiscoveryError('HF_DISCOVERY_TIMEOUT') from None
    except httpx.TransportError:
        raise HFDiscoveryError('HF_DISCOVERY_TRANSPORT_UNAVAILABLE') from None
    except Exception:
        raise HFDiscoveryError('HF_DISCOVERY_INVALID_RESPONSE') from None
