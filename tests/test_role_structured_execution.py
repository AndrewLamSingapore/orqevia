"""Source-level contract checks, never live role acceptance evidence."""
import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.direct_stream import infer, inference_request, validate_owned_inference_request
from app.job_queue import JobQueue
from app.response_schema import canonicalize_schema, validate_response_value


def isolated_schema():
    return {'type': 'object', 'properties': {'measured': {'type': 'integer'},
            'available': {'type': 'boolean'}}, 'required': ['measured', 'available'],
            'additionalProperties': False}


@pytest.mark.parametrize('raw,accepted', [
    ('{"measured":5,"available":false}', True),
    ('{"available":false}', False),
    ('{"measured":true,"available":false}', False),
    ('{"measured":5,"available":null}', False),
    ('{"measured":5,"available":false,"extra":1}', False),
])
def test_schema_survives_queue_and_rejected_bytes_usage_remain(raw, accepted, monkeypatch, tmp_path):
    for name in ('PRIME_LOCAL_ADMISSION_MODE', 'PRIME_MEASURED_COMPUTE_PROFILE',
                 'PRIME_MEASURED_COMPUTE_PROFILE_SHA256', 'PRIME_SSD_THERMAL_ENFORCE'):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / 'queue.db'
    monkeypatch.setenv('PRIME_COMPUTE_QUEUE_DB', str(path))
    queue = JobQueue(path)
    job = queue.submit(agent='a17', prompt='Independent arbitrary observation contract',
                       response_format='strict_json', response_schema=isolated_schema(),
                       model='gemma3:1b', ram_mb=1024, timeout_seconds=5, max_retries=0)
    from app.job_queue import Provider
    provider = Provider('local-unit', 'local', 'gemma3:1b', 1024, 0, 1)
    job = queue.claim('unit', (provider,))
    assert job is not None
    payloads = []
    def reply(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, text=json.dumps({'done': True, 'message': {'content': raw},
                              'prompt_eval_count': 10, 'eval_count': 8}) + '\n')
    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    settings = SimpleNamespace(ollama_base_url='http://fixture', keep_alive=0,
                               context_tokens=128, max_output_tokens=32)
    with patch('app.direct_stream.httpx.AsyncClient', return_value=client):
        result = asyncio.run(infer(job, provider, settings=settings,
                                   capacity=lambda _: None,
                                   options=lambda: {'num_ctx': 999999, 'num_predict': 999999}))
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload['format'] == canonicalize_schema(isolated_schema())
    assert payload['options'] == {'temperature': 0, 'seed': 0, 'num_ctx': 128, 'num_predict': 32}
    assert [message['role'] for message in payload['messages']] == ['system', 'user']
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    assert result['inference_receipt']['request_payload_sha256'] == hashlib.sha256(encoded).hexdigest()
    stored = queue.finish(job['id'], **result)
    assert stored['result'] == raw
    assert stored['status'] == ('completed' if accepted else 'failed')
    assert stored['attempts'] == 1
    assert stored['input_tokens'] == 10 and stored['output_tokens'] == 8
    assert json.loads(stored['inference_receipt']) == result['inference_receipt']
    if not accepted:
        assert stored['error'] == 'STRICT_JSON_CONTRACT_FAILED'
        assert result['retryable'] is False


def test_shape_contract_does_not_supply_semantic_answers():
    from app.agent_cert_response_contracts import normal_role_response_contract
    from app.agent_cert_role_group_two import review_role_json, _CASES
    contract = normal_role_response_contract('a26')
    wrong = {**_CASES['a26'][2], 'candidate_claim_supported': True}
    assert validate_response_value(wrong, contract['schema']) == ()
    passed, errors = review_role_json('a26', json.dumps(wrong))
    assert not passed and 'candidate_claim_supported' in errors


def test_all_current_normal_cases_declare_types_without_changing_registry():
    from app.agent_registry import registered_agent_ids
    from app.agent_cert_structured_roles import structured_role_case
    from app.agent_cert_response_contracts import declared_normal_role_ids
    ids = registered_agent_ids(include_orchestrator=False)
    assert set(ids) == set(declared_normal_role_ids())
    for agent in ids:
        spec = structured_role_case(agent)
        assert spec['request']['response_format'] == 'strict_json'
        assert canonicalize_schema(spec['request']['response_schema'])
        assert spec['request']['data_classification'] == 'LOCAL_ONLY'
        assert spec['request']['max_cost_usd'] == 0


@pytest.mark.parametrize('mutation', ['schema_removed', 'schema_changed', 'format_changed',
                                     'payload_digest', 'prompt_digest', 'model', 'options', 'scalar_type'])
def test_owned_peer_rejects_schema_or_receipt_changes(mutation):
    from copy import deepcopy
    schema = isolated_schema()
    original = SimpleNamespace(response_format='strict_json', response_schema=schema)
    provider = SimpleNamespace(model='gemma3:4b')
    settings = SimpleNamespace(keep_alive=0, context_tokens=256, max_output_tokens=64)
    job = {'prompt': 'Canonical owned prompt', 'response_format': 'strict_json',
           'response_schema': json.dumps(schema)}
    _, _, receipt = inference_request(job, provider, settings=settings, options=lambda: {})
    job['inference_receipt'] = json.dumps(receipt)
    validate_owned_inference_request(job, original, provider, settings=settings, options=lambda: {})
    altered = deepcopy(job)
    if mutation == 'schema_removed':
        altered['response_schema'] = None
    elif mutation == 'schema_changed':
        other = deepcopy(schema)
        other['properties']['measured']['type'] = 'boolean'
        altered['response_schema'] = json.dumps(other)
    elif mutation == 'format_changed':
        altered['response_format'] = 'text'
    else:
        wire = json.loads(altered['inference_receipt'])
        if mutation == 'payload_digest': wire['request_payload_sha256'] = '0' * 64
        if mutation == 'prompt_digest': wire['prompt_sha256'] = '0' * 64
        if mutation == 'model': wire['model'] = 'unrelated'
        if mutation == 'options': wire['effective_options']['temperature'] = 1
        if mutation == 'scalar_type': wire['effective_options']['seed'] = False
        altered['inference_receipt'] = json.dumps(wire)
    with pytest.raises(ValueError):
        validate_owned_inference_request(altered, original, provider, settings=settings, options=lambda: {})


def test_generation_option_strings_are_not_published_in_receipts():
    provider = SimpleNamespace(model='gemma3:4b')
    settings = SimpleNamespace(keep_alive=0, context_tokens=256, max_output_tokens=64)
    job = {'prompt': 'Bounded request', 'response_format': 'strict_json'}
    payload, _, receipt = inference_request(job, provider, settings=settings,
        options=lambda: {'stop': ['private-value-placeholder'], 'temperature': 0.2})
    assert payload['options']['stop'] == ['private-value-placeholder']
    assert 'private-value-placeholder' not in json.dumps(receipt)
    assert receipt['effective_options']['temperature'] == 0.2
    assert receipt['non_public_option_count'] == 1
