"""Exact existing primary role:normal oracles; no execution or certification.

This pure reviewer is shared by the registered review tool and the protected
signing bridge. A correct answer proves only these supplied synthetic facts,
not health, recovery, tool use, review execution, or any L7 level.
"""
from __future__ import annotations

import json
import math
import re

from .agent_registry import RegistryError, canonical_agent_id, registered_agent_ids


def _primary(agent, capability):
    if type(agent) is not str or type(capability) is not str:
        raise ValueError('CASE_ORACLE_UNSUPPORTED')
    try:
        if (agent not in registered_agent_ids(include_orchestrator=False) or
                canonical_agent_id(agent) != agent or capability != f'responsibility.{agent}'):
            raise ValueError('CASE_ORACLE_UNSUPPORTED')
    except RegistryError:
        raise ValueError('CASE_ORACLE_UNSUPPORTED') from None


def canonical_role_spec(agent, capability):
    """Return the exact existing case, never an arbitrary caller's challenge."""
    _primary(agent, capability)
    # Lazy imports keep this shared oracle independent of runtime dispatch and
    # protected signing initialization; the existing cases own their sources.
    from .agent_cert_cases import challenge
    from .agent_cert_role_group_two import _CASES, role_case
    if agent in _CASES:
        return role_case(agent)
    return challenge('role:normal', agent_id=agent, capability_id=capability)


def _unique(pairs):
    answer = {}
    for key, value in pairs:
        if key in answer:
            raise ValueError('DUPLICATE_FIELD')
        answer[key] = value
    return answer


def _finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('NONFINITE_NUMBER')
    return result


def _constant(_):
    raise ValueError('NONFINITE_NUMBER')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def review_role_output(agent, capability, response):
    """Return a literal verdict and fixed errors; never export the raw answer."""
    try:
        _primary(agent, capability)
    except (ValueError, TypeError):
        return False, ('case_oracle_unsupported',)
    if type(response) is not str:
        return False, ('response_not_bounded_text',)
    try:
        if not 1 <= len(response.encode('utf-8')) <= 64 * 1024:
            return False, ('response_not_bounded_text',)
        answer = json.loads(response, object_pairs_hook=_unique, parse_float=_finite,
                            parse_constant=_constant)
        if type(answer) is not dict:
            return False, ('not_strict_json',)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        return False, ('not_strict_json',)

    from .agent_cert_execution import (
        _A01_SOURCE, _A04_SOURCE, _A05_SOURCE, _A12_SOURCE, _A14_SOURCE,
        _A21_SOURCE, _A28_SOURCE, _A29_SOURCE,
    )
    from .agent_cert_numeric import review_priority_json
    from .agent_cert_rates import review_rate_json
    from .agent_cert_weighted import review_weighted_json
    from .agent_cert_boundary import review_zero_boundary_json
    from .agent_cert_a17_boundary import review_a17_boundary_json
    from .agent_cert_data_quality import review_data_quality_json
    from .agent_cert_portfolio import review_portfolio_json
    from .agent_cert_cost import review_cost_json
    from .agent_cert_risk import review_risk_json
    from .agent_cert_release import review_release_json
    from .agent_cert_role_g1 import SOURCES, role_facts, review_role_json
    from .agent_cert_role_group_two import _CASES, review_role_json as review_group_two_json

    oracles = {
        'a01': lambda: review_priority_json(_A01_SOURCE, response),
        'a04': lambda: review_weighted_json(_A04_SOURCE, response),
        'a05': lambda: review_portfolio_json(_A05_SOURCE, response),
        'a12': lambda: review_rate_json(_A12_SOURCE, response),
        'a14': lambda: review_data_quality_json(_A14_SOURCE, response),
        'a17': lambda: review_a17_boundary_json(response),
        'a18': lambda: review_zero_boundary_json(response),
        'a21': lambda: review_cost_json(_A21_SOURCE, response),
        'a28': lambda: review_risk_json(_A28_SOURCE, response),
        'a29': lambda: review_release_json(_A29_SOURCE, response),
    }
    try:
        if agent in SOURCES:
            valid, errors = review_role_json(agent, SOURCES[agent], response)
            # Nested Python equality must not collapse literal number types.
            if valid is True and _canonical(answer) != _canonical(role_facts(agent, SOURCES[agent])):
                return False, ('literal_field_type_mismatch',)
        elif agent in _CASES:
            valid, errors = review_group_two_json(agent, response)
        elif agent in oracles:
            valid, errors = oracles[agent]()
        else:
            return False, ('case_oracle_unsupported',)
        if (type(valid) is not bool or type(errors) is not tuple or len(errors) > 32 or
                any(type(item) is not str or not re.fullmatch(r'[A-Za-z0-9_]{1,80}', item)
                    for item in errors)):
            return False, ('case_oracle_contract_invalid',)
        return valid is True and not errors, errors
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError, KeyError):
        return False, ('case_oracle_failed',)
