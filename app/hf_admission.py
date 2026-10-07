"""Additional fail-closed admission for the optional Hugging Face route.

The queue owns capacity and daily spend. This boundary checks the persisted job
again immediately before a credential is resolved or external data is sent.
"""
from decimal import Decimal, InvalidOperation

from .provider_runtime import ProviderFailure
from .tier_router import classify_for_cloud


HF_FALLBACK_POLICY_VERSION = 'hf-fallback.v1'


def require_hf_fallback_policy(primary, job, target=None):
    """Authorize a bounded, explicitly configured HF-primary fallback chain.

    Consent belongs to the operator-controlled primary catalog entry. It is not
    inferred from token availability, an alternate's registration, or task text.
    Generic cloud routes cannot silently acquire permission to send work to HF.
    """
    if primary.get('provider_kind') != 'huggingface':
        raise ProviderFailure('HF_FALLBACK_NOT_PERMITTED', pre_execution=True)
    if not primary.get('enabled') or primary.get('qualification_status') != 'QUALIFIED':
        raise ProviderFailure('PROVIDER_UNQUALIFIED', pre_execution=True)
    if job.get('preferred_provider') != primary.get('id') or job.get('allow_cloud') != 1:
        raise ProviderFailure('HF_EXPLICIT_SELECTION_REQUIRED', pre_execution=True)
    if not classify_for_cloud(job.get('data_classification'), job.get('prompt', '')):
        raise ProviderFailure('DATA_LOCALITY', pre_execution=True)
    policy = primary.get('hf_fallback_policy')
    if policy is None:
        raise ProviderFailure('HF_FALLBACK_NOT_PERMITTED', pre_execution=True)
    ids = primary.get('fallback_ids')
    if (not isinstance(policy, dict) or
            set(policy) != {'version', 'allowed_provider_ids', 'allow_non_hf'} or
            policy.get('version') != HF_FALLBACK_POLICY_VERSION or
            type(policy.get('allow_non_hf')) is not bool or
            not isinstance(ids, list) or not 1 <= len(ids) <= 3 or
            any(not isinstance(value, str) or not 1 <= len(value) <= 100 for value in ids) or
            len(set(ids)) != len(ids) or primary.get('id') in ids or
            policy.get('allowed_provider_ids') != ids):
        raise ProviderFailure('HF_FALLBACK_POLICY_INVALID', pre_execution=True)
    if target is not None:
        if target.get('id') not in ids:
            raise ProviderFailure('HF_FALLBACK_NOT_PERMITTED', pre_execution=True)
        if target.get('provider_kind') != 'huggingface' and not policy['allow_non_hf']:
            raise ProviderFailure('HF_NON_HF_FALLBACK_NOT_PERMITTED', pre_execution=True)
    return {'version': HF_FALLBACK_POLICY_VERSION,
            'primary_provider': primary['id'], 'allowed_provider_ids': list(ids),
            'allow_non_hf': policy['allow_non_hf']}


def require_hf_admission(entry, job, provider_name, *, primary=None):
    if entry.get('provider_kind') != 'huggingface':
        return
    if not entry.get('enabled') or entry.get('qualification_status') != 'QUALIFIED':
        raise ProviderFailure('PROVIDER_UNQUALIFIED', pre_execution=True)
    if primary is not None:
        require_hf_fallback_policy(primary, job, entry)
    elif entry.get('fallback_ids'):
        require_hf_fallback_policy(entry, job)
    # An alternate is admitted only under the explicitly selected HF primary's
    # validated policy, never as an implicit generic cloud route.
    elif job.get('preferred_provider') != provider_name or job.get('allow_cloud') != 1:
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
