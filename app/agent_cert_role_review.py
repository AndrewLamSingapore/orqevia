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


ARTIFACT_REVIEW_SCHEMA = 'prime.agent-cert-artifact-review.v1'
ARTIFACT_REVIEW_ACTION = 'agent.certification.artifact.review'
ARTIFACT_REVIEW_OPERATION = 'certification_artifact_review'
ARTIFACT_REVIEW_OBJECTIVE = ('Independently review one recorded A19 artifact event against its original '
    'Objective, immutable input and result artifacts and action records; do not certify or sign.')
AUTHORITY_REVIEW_SCHEMA = 'prime.agent-cert-authority-review.v1'
AUTHORITY_REVIEW_ACTION = 'agent.certification.authority.review'
AUTHORITY_REVIEW_OPERATION = 'certification_authority_review'
AUTHORITY_REVIEW_OBJECTIVE = ('Independently review one recorded A19 permitted authority-read event against '
    'the current owning Registry, original Objective, result artifact and action records; do not certify or sign.')


def artifact_event_review_join(execution, **pins):
    """Fixed original-event adapter; an untrusted submitted join is never used."""
    from .agent_cert_artifact_events import validate_artifact_execution
    joined = validate_artifact_execution(execution, **pins)
    return {**joined, 'completed_at': execution['dispatch']['artifact_event']['completed_at']}


def authority_event_review_join(execution, **pins):
    """Only the two owning permitted events; no generic PASS or guard-denial proof."""
    from .agent_cert_authority_events import validate_authority_execution
    joined = validate_authority_execution(execution, **pins)
    return {**joined, 'completed_at': execution['dispatch']['authority_event']['completed_at']}


def read_authority_review_action_span(data_root, task_id):
    """Bounded original fixed A26 review pair, never a caller-selected action/path."""
    from .agent_cert_artifact_events import _ledger_lines, _path, _uuid, parse, _require
    _require(_uuid(task_id), 'AUTHORITY_REVIEW_TASK_REQUIRED')
    lines = _ledger_lines(_path(data_root))
    owned = [i for i, line in enumerate(lines) if (event := parse(line.encode('utf-8'))).get('task_id') == task_id
        and event.get('action_type') == AUTHORITY_REVIEW_ACTION]
    _require(len(owned) == 2 and 2 <= owned[-1] - owned[0] + 1 <= 128,
        'AUTHORITY_REVIEW_ACTION_PAIR_REQUIRED')
    return lines[owned[0]:owned[-1] + 1]


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
    from .agent_cert_secondary_roles import SUPPORTED_CAPABILITIES, canonical_secondary_spec
    if type(capability) is str and capability in SUPPORTED_CAPABILITIES:
        try:
            return canonical_secondary_spec(agent, capability)
        except (ValueError, TypeError, KeyError):
            raise ValueError('CASE_ORACLE_UNSUPPORTED') from None
    _primary(agent, capability)
    # Lazy imports keep this shared oracle independent of runtime dispatch and
    # protected signing initialization; the existing cases own their sources.
    from .agent_cert_cases import challenge
    from .agent_cert_role_group_two import _CASES, role_case
    if agent in _CASES:
        return role_case(agent)
    return challenge('role:normal', agent_id=agent, capability_id=capability)


def canonical_case_spec(agent, capability, case_id):
    """Return an existing exact oracle case, never a generic event challenge.

    Role-normal retains its legacy source and bytes. The additional A19 cases
    judge only their supplied public quality facts; they cannot establish real
    recovery, tool execution, handoff, signing or audit events.
    """
    if type(case_id) is not str:
        raise ValueError('CASE_ORACLE_UNSUPPORTED')
    if case_id == 'role:normal':
        return canonical_role_spec(agent, capability)
    if case_id == 'baseline:initialization':
        from .agent_cert_initialization import initialization_objective
        from .agent_cert_cases import challenge
        initialization_objective(agent, capability)  # Exact registered ownership.
        return challenge(case_id, agent_id=agent, capability_id=capability)
    _primary(agent, capability)
    if agent == 'a19' and capability == 'responsibility.a19' and case_id in {
            'baseline:identity'}:
        from .agent_cert_cases import challenge
        return challenge(case_id, agent_id=agent, capability_id=capability)
    from .agent_cert_artifact_events import SUPPORTED_CASES as ARTIFACT_CASES, canonical_artifact_case
    if agent == 'a19' and case_id in ARTIFACT_CASES:
        return canonical_artifact_case(case_id, agent_id=agent, capability_id=capability)
    from .agent_cert_authority_events import SUPPORTED_CASES as AUTHORITY_CASES, canonical_authority_case
    if agent == 'a19' and case_id in AUTHORITY_CASES:
        return canonical_authority_case(case_id)
    from .agent_cert_a19_baseline import SUPPORTED_CASES as BASELINE_CASES, canonical_a19_baseline_case
    if agent == 'a19' and case_id in BASELINE_CASES:
        return canonical_a19_baseline_case(case_id)
    from .agent_cert_a19_general import SUPPORTED_CASES as GENERAL_CASES, canonical_a19_general_case
    if agent == 'a19' and case_id in GENERAL_CASES:
        return canonical_a19_general_case(case_id)
    from .agent_cert_a19_cases import SUPPORTED_CASES, canonical_a19_case
    if agent != 'a19' or case_id not in SUPPORTED_CASES:
        raise ValueError('CASE_ORACLE_UNSUPPORTED')
    return canonical_a19_case(case_id)


def review_case_output(agent, capability, case_id, response):
    """Review the specific source-owned case without promoting its evidence."""
    try:
        canonical_case_spec(agent, capability, case_id)
    except (ValueError, TypeError):
        return False, ('case_oracle_unsupported',)
    if case_id == 'role:normal':
        return review_role_output(agent, capability, response)
    if case_id == 'baseline:identity':
        # Identity is an Objective/artifact/action event, not a model answer.
        # It can only be reviewed through the owned event adapter.
        return False, ('identity_event_evidence_required',)
    if case_id == 'baseline:initialization':
        return False, ('initialization_event_evidence_required',)
    from .agent_cert_authority_events import SUPPORTED_CASES as AUTHORITY_CASES
    if case_id in AUTHORITY_CASES:
        return False, ('authority_event_evidence_required',)
    from .agent_cert_artifact_events import SUPPORTED_CASES as ARTIFACT_CASES
    if case_id in ARTIFACT_CASES:
        return False, ('artifact_event_evidence_required',)
    from .agent_cert_a19_baseline import SUPPORTED_CASES as BASELINE_CASES, review_a19_baseline_output
    if case_id in BASELINE_CASES:
        return review_a19_baseline_output(case_id, response)
    from .agent_cert_a19_general import SUPPORTED_CASES as GENERAL_CASES, review_a19_general_output
    if case_id in GENERAL_CASES:
        return review_a19_general_output(case_id, response)
    from .agent_cert_a19_cases import review_a19_case_output
    return review_a19_case_output(case_id, response)


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
    from .agent_cert_secondary_roles import SUPPORTED_CAPABILITIES, review_secondary_output
    if type(capability) is str and capability in SUPPORTED_CAPABILITIES:
        return review_secondary_output(agent, capability, response)
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
