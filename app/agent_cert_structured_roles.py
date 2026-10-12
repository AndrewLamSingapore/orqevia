"""Explicit new local task version; historical canonical role bytes stay fixed.

This adapter prepares a request, not an acceptance receipt or signing authority.
The legacy protected transport must reject these changed bytes. Any future
protected admission needs its own reviewed, version-aware binding.
"""
from __future__ import annotations

from .agent_cert_response_contracts import normal_role_response_contract
from .agent_cert_role_review import canonical_role_spec

CASE_VERSION = 'prime.normal-role-structured.v1'


def structured_role_case(agent_id: str) -> dict:
    """Derive an answer-free shape contract under a distinct explicit version."""
    spec = canonical_role_spec(agent_id, f'responsibility.{agent_id}')
    contract = normal_role_response_contract(agent_id)
    return {**spec, 'case_version': CASE_VERSION,
            'request': {**spec['request'],
                        'objective': spec['request']['objective'] +
                        '\nResponse contract clarification: ' + contract['clarification'],
                        'response_format': 'strict_json',
                        'response_schema': contract['schema']}}
