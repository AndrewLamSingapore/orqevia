"""Explicit local normal-role contract; legacy cases and oracles stay intact.

This creates a new source-specific task, not new roles, permissions, answers,
provider consent or certification. Historical role:normal receipts must continue
to reconstruct their original canonical bytes. Only a new pinned execution may
use this contract. The supplied raw inputs do not contain computed answers.
"""
from __future__ import annotations

from copy import deepcopy

CASE_ID = 'role:normal_structured'
CASE_VERSION = 'normal-role-structured-input.v1'


def structured_normal_role_spec(agent: str, capability: str) -> dict:
    """Derive a bounded schema/input variant from the exact primary source."""
    from .agent_cert_role_review import canonical_role_spec
    from .agent_cert_response_contracts import normal_role_response_contract
    from .agent_cert_role_inputs import normal_role_raw_input_context, INPUT_VERSION

    if capability != f'responsibility.{agent}':
        raise ValueError('CASE_ORACLE_UNSUPPORTED')
    legacy = canonical_role_spec(agent, capability)
    contract = normal_role_response_contract(agent)
    spec = deepcopy(legacy)
    spec.update(case=CASE_ID, case_version=CASE_VERSION,
                legacy_case_version=legacy.get('case_version'),
                response_contract_version=contract['contract_version'],
                input_contract_version=INPUT_VERSION,
                oracle_id=('group_two_exact_role_oracle/v1' if
                           'group_two_exact_role_oracle' in legacy['independent_review']
                           else 'existing.role-normal.v1'))
    request = spec['request']
    request['objective'] += '\nResponse contract clarification: ' + contract['clarification']
    request['context'] = normal_role_raw_input_context(agent, legacy['request']['context'])
    request['response_format'] = 'strict_json'
    request['response_schema'] = contract['schema']
    return spec
