"""Injected catalog-to-wire mode checks; no secrets, upstream call or admission uplift."""
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.cloud_execution import adapter_for
from app.compute_catalog import load_catalog
from app.provider_runtime import ModelSpec


def entry(**changes):
    return {'id': 'hf-json-fixture', 'provider_kind': 'huggingface', 'enabled': True,
        'qualification_status': 'QUALIFIED', 'location': 'cloud', 'tier': 'MINI',
        'model': 'google/gemma-3-4b-it:deepinfra',
        'endpoint': 'https://router.huggingface.co/v1/chat/completions',
        'secret_ref': 'file:HF_TOKEN', 'context_tokens': 4096, 'output_tokens': 384,
        'concurrency': 1, 'max_retries': 0, 'input_usd_million': '.05',
        'output_usd_million': '.10', **changes}


def catalog(tmp_path, value):
    path = tmp_path / 'public-fixture.json'
    path.write_text(json.dumps({'models': [value]}))
    return path


@pytest.mark.parametrize('mode', [None, True, 1, [], {}, 'auto', 'json_schema', 'JSON_OBJECT', ''])
def test_bad_catalog_output_contract_denied_before_secret(tmp_path, mode):
    with patch('app.cloud_execution.resolve_secret') as resolve:
        with pytest.raises(ValueError):
            load_catalog(catalog(tmp_path, entry(hf_response_format=mode)))
        with pytest.raises(ValueError):
            adapter_for(entry(hf_response_format=mode))
    resolve.assert_not_called()


@pytest.mark.parametrize('mode', ['text', 'json_object'])
def test_operator_contract_reaches_only_fixed_wire_field(tmp_path, mode):
    value = load_catalog(catalog(tmp_path, entry(hf_response_format=mode)))[0]
    with patch('app.cloud_execution.resolve_secret') as resolve:
        adapter = adapter_for(value)
        spec = ModelSpec(value['model'], value['id'], 'MINI', 4096, 384,
            Decimal('.05'), Decimal('.10'))
        body = adapter.request_body(spec, [{'role': 'user', 'content': 'Public fixture JSON'}], 384)
    resolve.assert_not_called()
    assert body['model'] == value['model']
    assert body['max_tokens'] == 384
    assert ('response_format' in body) is (mode == 'json_object')
    if mode == 'json_object':
        assert body['response_format'] == {'type': 'json_object'}


def test_legacy_text_catalog_does_not_silently_change_request(tmp_path):
    value = load_catalog(catalog(tmp_path, entry()))[0]
    spec = ModelSpec(value['model'], value['id'], 'MINI', 4096, 384)
    adapter = adapter_for(value)
    assert 'response_format' not in adapter.request_body(spec, [{'role': 'user', 'content': 'Public'}], 384)


def test_hf_mode_cannot_claim_another_provider_contract(tmp_path):
    value = entry(provider_kind='chat_completions', secret_ref='env:PUBLIC_FIXTURE', hf_response_format='json_object')
    with pytest.raises(ValueError, match='output contract'):
        load_catalog(catalog(tmp_path, value))


def test_json_mode_is_not_model_or_price_qualification(tmp_path):
    with pytest.raises(ValueError, match='Unqualified'):
        load_catalog(catalog(tmp_path, entry(hf_response_format='json_object', qualification_status='UNVERIFIED')))
    with pytest.raises(ValueError, match='price'):
        load_catalog(catalog(tmp_path, entry(hf_response_format='json_object', input_usd_million=None)))
