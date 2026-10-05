"""Admission checks use only fixtures; no credential or external request."""
import pytest

from app.hf_admission import require_hf_admission
from app.provider_runtime import ProviderFailure


ENTRY = {'id': 'hf-fixture', 'provider_kind': 'huggingface', 'enabled': True,
         'qualification_status': 'QUALIFIED', 'input_usd_million': '0.10',
         'output_usd_million': '0.50', 'output_tokens': 64}
JOB = {'preferred_provider': 'hf-fixture', 'allow_cloud': 1,
       'data_classification': 'CLOUD_PERMITTED', 'prompt': 'Synthetic greeting',
       'estimated_cost_usd': .0001, 'max_cost_usd': .0001}


def test_explicit_hf_route_with_reserved_cost_is_admitted():
    assert require_hf_admission(ENTRY, JOB, 'hf-fixture') is None


@pytest.mark.parametrize('field,value,code', [
    ('preferred_provider', None, 'HF_EXPLICIT_SELECTION_REQUIRED'),
    ('preferred_provider', 'other-provider', 'HF_EXPLICIT_SELECTION_REQUIRED'),
    ('allow_cloud', 0, 'HF_EXPLICIT_SELECTION_REQUIRED'),
    ('data_classification', 'LOCAL_ONLY', 'DATA_LOCALITY'),
    ('prompt', 'password=private-fixture', 'DATA_LOCALITY'),
    ('estimated_cost_usd', 0, 'HF_BUDGET_NOT_RESERVED'),
    ('max_cost_usd', 0, 'HF_BUDGET_NOT_RESERVED'),
    ('estimated_cost_usd', float('nan'), 'HF_BUDGET_NOT_RESERVED'),
])
def test_hf_admission_fails_closed(field, value, code):
    with pytest.raises(ProviderFailure) as failure:
        require_hf_admission(ENTRY, {**JOB, field: value}, 'hf-fixture')
    assert failure.value.code == code and failure.value.pre_execution
    assert 'private-fixture' not in str(failure.value)


def test_catalog_price_change_after_queue_claim_is_denied():
    with pytest.raises(ProviderFailure, match='HF_BUDGET_NOT_RESERVED'):
        require_hf_admission({**ENTRY, 'output_usd_million': '100'}, JOB, 'hf-fixture')


def test_selected_hf_cannot_fallback_to_another_cloud_provider():
    with pytest.raises(ProviderFailure, match='HF_FALLBACK_NOT_PERMITTED') as failure:
        require_hf_admission({**ENTRY, 'fallback_ids': ['other-cloud']}, JOB, 'hf-fixture')
    assert failure.value.pre_execution


def test_non_hf_provider_has_no_new_restriction():
    assert require_hf_admission({'provider_kind': 'chat_completions'}, {}, 'other') is None
