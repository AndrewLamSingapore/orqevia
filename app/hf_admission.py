"""Additional fail-closed admission for the optional Hugging Face route.

The queue owns capacity and daily spend. This boundary checks the persisted job
again immediately before a credential is resolved or external data is sent.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import re

from .provider_runtime import ProviderFailure
from .tier_router import classify_for_cloud


HF_FALLBACK_POLICY_VERSION = 'hf-fallback.v1'
_TASK_CLASSES = frozenset(('auto', 'classification', 'question_answering', 'conversation', 'research',
                          'planning', 'writing', 'coding', 'architecture', 'complex_reasoning'))
_PROMPT_DIGEST = re.compile(r'[0-9a-f]{64}\Z')


def require_hf_prompt_scope(entry, job):
    """Restrict a narrow qualification to actual original prompt/agent pairs.

    A prose qualification_scope is not an executable disclosure boundary.
    The operator-owned optional allowlist is rechecked on the persisted job
    before credential resolution, including each separately admitted fallback.
    Absence preserves existing broad catalog behavior; malformed presence denies.
    This is admission only, never agent certification or general model quality.
    """
    if 'allowed_prompt_bindings' not in entry:
        return
    from .agent_registry import registered_agent_ids
    allowed = entry['allowed_prompt_bindings']
    permanent = frozenset(registered_agent_ids(include_orchestrator=False))
    valid = type(allowed) is list and 1 <= len(allowed) <= 256
    bindings = set()
    if valid:
        for binding in allowed:
            if (type(binding) is not dict or set(binding) != {'agent', 'prompt_sha256'}
                    or type(binding['agent']) is not str or binding['agent'] not in permanent
                    or type(binding['prompt_sha256']) is not str
                    or _PROMPT_DIGEST.fullmatch(binding['prompt_sha256']) is None):
                valid = False
                break
            pair = (binding['agent'], binding['prompt_sha256'])
            if pair in bindings:
                valid = False
                break
            bindings.add(pair)
    prompt = job.get('prompt')
    actor = job.get('agent')
    if (not valid or type(actor) is not str or type(prompt) is not str
            or not 1 <= len(prompt) <= 200_000):
        raise ProviderFailure('PROVIDER_UNQUALIFIED', pre_execution=True)
    try:
        actual = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    except UnicodeError:
        raise ProviderFailure('PROVIDER_UNQUALIFIED', pre_execution=True) from None
    if (actor, actual) not in bindings:
        raise ProviderFailure('PROVIDER_UNQUALIFIED', pre_execution=True)


def require_hf_task_scope(entry, job):
    """Enforce an operator's bounded qualification, not a quality certificate.

    Existing broadly qualified catalogs need not add a new policy. If a narrow
    allowlist is supplied, malformed or missing job classes cannot bypass it.
    Task labels restrict admission; they do not establish substantive quality.
    """
    require_hf_prompt_scope(entry, job)
    if 'allowed_task_classes' not in entry:
        return
    allowed = entry['allowed_task_classes']
    if (not isinstance(allowed, list) or not 1 <= len(allowed) <= len(_TASK_CLASSES) or
            any(type(value) is not str or value not in _TASK_CLASSES for value in allowed) or
            len(set(allowed)) != len(allowed) or
            type(job.get('task_class')) is not str or job['task_class'] not in allowed):
        raise ProviderFailure('PROVIDER_UNQUALIFIED', pre_execution=True)


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
    require_hf_task_scope(primary, job)
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
    require_hf_task_scope(entry, job)
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
