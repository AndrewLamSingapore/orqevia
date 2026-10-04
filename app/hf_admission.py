"""Additional fail-closed admission for the optional Hugging Face route.

The queue owns capacity and daily spend. This boundary checks the persisted job
again immediately before a credential is resolved or external data is sent.
"""
from decimal import Decimal, InvalidOperation

from .provider_runtime import ProviderFailure
from .tier_router import classify_for_cloud


def require_hf_admission(entry, job, provider_name):
    if entry.get('provider_kind') != 'huggingface':
        return
    if not entry.get('enabled') or entry.get('qualification_status') != 'QUALIFIED':
        raise ProviderFailure('PROVIDER_UNQUALIFIED', pre_execution=True)
    # HF never becomes an implicit fallback for an agent's generic cloud request.
    if job.get('preferred_provider') != provider_name or job.get('allow_cloud') != 1:
        raise ProviderFailure('HF_EXPLICIT_SELECTION_REQUIRED', pre_execution=True)
    if not classify_for_cloud(job.get('data_classification'), job.get('prompt', '')):
        raise ProviderFailure('DATA_LOCALITY', pre_execution=True)
    try:
        input_rate = Decimal(str(entry['input_usd_million']))
        output_rate = Decimal(str(entry['output_usd_million']))
        output_cap = entry['output_tokens']
        reserved = Decimal(str(job['estimated_cost_usd']))
        ceiling = Decimal(str(job['max_cost_usd']))
        if (type(output_cap) is not int or output_cap <= 0 or
                not all(value.is_finite() and value >= 0 for value in
                        (input_rate, output_rate, reserved, ceiling))):
            raise ValueError()
        # Match the queue's conservative byte-based token upper estimate. A
        # changed catalog price after claim must not silently spend more.
        input_cap = len(job['prompt'].encode()) + 16
        estimate = (input_cap * input_rate + output_cap * output_rate) / Decimal(1_000_000)
        if estimate > reserved or estimate > ceiling:
            raise ValueError()
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        raise ProviderFailure('HF_BUDGET_NOT_RESERVED', pre_execution=True) from None
