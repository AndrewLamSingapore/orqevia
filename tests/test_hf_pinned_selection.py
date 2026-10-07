"""No network: provider policy suffixes are not specific admitted providers."""
from decimal import Decimal

import pytest

from app.provider_runtime import HuggingFaceProvider, ModelSpec, ProviderFailure


@pytest.mark.parametrize('suffix', ['auto', 'fastest', 'cheapest', 'preferred', 'AUTO'])
def test_dynamic_provider_policy_is_not_a_pinned_model(suffix):
    model = ModelSpec('google/gemma-3-4b-it:' + suffix, 'hf-fixture', 'NANO', 4096, 64,
                      Decimal('0.05'), Decimal('0.10'))
    provider = HuggingFaceProvider(secret_resolver=lambda _: 'synthetic-unit-test-token')
    with pytest.raises(ProviderFailure, match='MODEL_PROVIDER_UNPINNED'):
        provider.request_body(model, [{'role': 'user', 'content': 'Synthetic public case'}], 8)


def test_explicit_existing_deepinfra_selection_remains_unchanged():
    model = ModelSpec('google/gemma-3-4b-it:deepinfra', 'hf-fixture', 'NANO', 4096, 64)
    body = HuggingFaceProvider(secret_resolver=lambda _: 'synthetic-unit-test-token').request_body(
        model, [{'role': 'user', 'content': 'Synthetic public case'}], 8)
    assert body['model'] == model.name
    assert body['max_tokens'] == 8
    assert body['stream'] is True
