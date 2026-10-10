"""Bounded source readiness, not a live matrix, attestation, or L7 grant.

Reuse the existing owned Registry, case catalogue and canonical oracle adapters.
No dispatch, model, certification-store read, signing, credential, or network
operation occurs. An unsupported case remains locally actionable source work;
generic challenge prose is never counted as an implemented event oracle.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from app import agent_registry
from app.agent_cert_cases import case_ids
from app.agent_certification import LEVEL_DIMENSIONS
from app.agent_cert_role_review import canonical_case_spec
from app.agent_cert_transport import canonical_cert_case


MAX_BYTES = 1024 * 1024
SOURCE_FILES = (
    'config/agent_registry.json', 'config/agent_registry_migration.json',
    'app/agent_registry.py', 'app/agent_certification.py', 'app/agent_cert_cases.py',
    'app/agent_cert_role_review.py', 'app/agent_cert_role_g1.py',
    'app/agent_cert_role_group_two.py', 'app/agent_cert_secondary_roles.py',
    'app/agent_cert_a19_cases.py', 'app/agent_cert_a19_general.py',
    'app/agent_cert_a19_baseline.py', 'app/agent_cert_artifact_events.py',
    'app/handoff.py',
    'app/agent_cert_authority_events.py',
    'app/agent_cert_tool_events.py', 'app/deterministic_ops.py', 'app/sink_guard.py',
    'app/agent_cert_event_api.py', 'app/agent_cert_execution.py',
    'app/agent_cert_identity_review.py', 'app/agent_cert_initialization.py',
    'app/agent_cert_initialization_review.py', 'app/agent_cert_review_tool.py',
    'app/agent_cert_owned_identity.py',
    'app/agent_cert_transport.py', 'app/agent_dispatch_api.py',
    'app/production_entry.py', 'scripts/collect_agent_cert_case.py',
    'scripts/collect_agent_cert_event.py', 'scripts/agent_cert_operator_io.py',
    'scripts/agent_cert_reviewed_signing.py', 'scripts/sign_admitted_agent_cases.py',
    'governance/agent-cert-reviewed-cases.json',
    'governance/agent-cert-historical-admissions/a19-role-normal-signed-37613202210.json',
)
EVENT_CASES = frozenset({'baseline:identity', 'baseline:initialization',
    'general:artifact_consume', 'general:artifact_produce', 'general:review', 'general:handoff', 'general:recovery',
    'evidence_integrity:complete',
    'authority:complete', 'unauthorized_rejection:authorized',
    'tool_recovery:tool_failure', 'tool_recovery:bounded_response'})
GROUP_TWO = frozenset({'a15', 'a16', 'a19', 'a20', 'a26'})


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_SOURCE_FIELD')
        result[key] = value
    return result


def _parse(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('SOURCE_SIZE_INVALID')
    def finite(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('NONFINITE_SOURCE')
        return value
    return json.loads(raw, object_pairs_hook=_unique, parse_float=finite,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_SOURCE')))


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('SOURCE_FILE_UNAVAILABLE')
    with path.open('rb') as stream:
        return stream.read(MAX_BYTES + 1)


def _pins(root):
    return {name: hashlib.sha256(_read(root / name)).hexdigest() for name in SOURCE_FILES}


def _registry():
    raw = _read(agent_registry.REGISTRY_PATH)
    source = _parse(raw)
    normalized = copy.deepcopy(source)
    leads = normalized.get('leads')
    if type(leads) is not list or len(leads) != 6:
        raise ValueError('REGISTRY_INVALID')
    aliases = {item['id']: item['agent_id'] for item in leads}
    domains = {item['agent_id']: item['domain'] for item in leads}
    for item in normalized['agents']:
        item['id'] = item['agent_id']
        item['reports_to'] = aliases.get(item['reports_to'], item['reports_to'])
        item['division'] = domains.get(item['id'], domains.get(item['reports_to'], '')).title()
    loaded = agent_registry.load_agent_registry()
    if canonical(normalized) != canonical(loaded):
        raise ValueError('LOADED_REGISTRY_SOURCE_CHANGED')
    if len(loaded['agents']) != 21 or sum(len(a['capability_requirements'])
                                         for a in loaded['agents']) != 29:
        raise ValueError('REGISTRY_POPULATION_INVALID')
    return loaded, hashlib.sha256(raw).hexdigest()


def _supported(actor, capability, key):
    try:
        return canonical_case_spec(actor, capability, key)
    except (ValueError, TypeError, KeyError):
        return None


def _cloud_supported(actor, capability, key):
    try:
        canonical_cert_case(actor, capability, key)
        return True
    except (ValueError, TypeError, KeyError):
        return False


def _historical(root, now):
    name = SOURCE_FILES[-1]
    raw = _read(root / name)
    batch = _parse(raw)
    if (type(batch) is not dict or batch.get('schema_version') != 'prime.protected-signed-cases.v1'
            or type(batch.get('signed_case_count')) is not int
            or type(batch.get('l7_awarded')) is not bool or batch['l7_awarded'] is not False
            or type(batch.get('signed_cases')) is not list
            or batch['signed_case_count'] != len(batch['signed_cases'])):
        raise ValueError('HISTORICAL_BATCH_INVALID')
    rows = []
    for row in batch['signed_cases']:
        expiry = datetime.fromisoformat(row['expires_at'].replace('Z', '+00:00'))
        if expiry.tzinfo is None:
            raise ValueError('HISTORICAL_TIME_INVALID')
        rows.append({key: row[key] for key in ('agent_id', 'capability_id', 'dimension',
                    'test_case', 'source_revision', 'expires_at')})
        rows[-1].update(expired=expiry <= now, signature_verification='NOT_REPEATED_BY_SOURCE_INVENTORY')
    return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'records': rows,
            'scope': 'HISTORICAL_BATCH_ONLY_NOT_RUNTIME_CERTIFICATION_STORE'}


def build_source_readiness(*, source_revision, canonical_main_revision, now, root=None):
    """Produce 29 individual ownership rows; never project fabricated live rows."""
    if (type(source_revision) is not str or re.fullmatch('[0-9a-f]{40}', source_revision) is None
            or type(canonical_main_revision) is not str
            or re.fullmatch('[0-9a-f]{40}', canonical_main_revision) is None
            or type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None):
        raise ValueError('SOURCE_BINDINGS_INVALID')
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    before = _pins(root)
    registry, registry_sha = _registry()
    keys = case_ids()
    if len(keys) != 74 or len(set(keys)) != 74 or len(LEVEL_DIMENSIONS[-1]) != 28:
        raise ValueError('EXISTING_CASE_MATRIX_CHANGED')
    active = _parse(_read(root / 'governance/agent-cert-reviewed-cases.json'))
    if (type(active) is not dict or active.get('schema_version') != 'prime.protected-reviewed-cases.v1'
            or type(active.get('cases')) is not list):
        raise ValueError('ACTIVE_ADMISSION_INVALID')
    historical = _historical(root, now)
    rows = []
    for agent in registry['agents']:
        for capability in agent['capability_requirements']:
            supported, event, cloud = [], [], []
            specs = {}
            for key in keys:
                spec = _supported(agent['id'], capability, key)
                if spec is not None:
                    supported.append(key)
                    specs[key] = hashlib.sha256(canonical(spec)).hexdigest()
                    if key in EVENT_CASES:
                        event.append(key)
                    elif _cloud_supported(agent['id'], capability, key):
                        cloud.append(key)
            missing = [key for key in keys if key not in supported]
            rows.append({
                'agent_id': agent['id'], 'capability_id': capability,
                'role': agent['role'], 'version': agent['version'],
                'authority_scope': agent['authority'],
                'primary_capability': capability == 'responsibility.' + agent['id'],
                'canonical_adapter_oracle_ready_cases': supported,
                'canonical_case_sha256': specs,
                'distinct_zero_model_event_adapter_cases': event,
                'source_pinned_cloud_transport_cases': cloud,
                'cloud_transport_missing_for_ready_quality_cases': [
                    key for key in supported if key not in event and key not in cloud],
                'generic_queue_observer_quality_gap_cases': [
                    key for key in supported if key not in event and
                    (key != 'role:normal' or (agent['id'] in GROUP_TWO and
                                             capability == 'responsibility.' + agent['id']))],
                'collection_paths': {
                    'quality': 'scripts/collect_agent_cert_case.py (actual job/oracle + registered review joins)',
                    'zero_model_event': 'app/agent_cert_execution.py + owned event validator; operator collection required',
                },
                'missing_case_adapter_oracle_ids': missing,
                'locally_actionable_missing_case_adapter_ids': missing,
                'missing_adapter_state': 'OPEN_LOCAL_IMPLEMENTATION_NOT_EXTERNAL',
                'certification_domain': {
                    'status': 'NOT_OBSERVED',
                    'pass_fail_blocked_claim': None,
                    'reason': 'No actual current domain manifest or authenticated runtime projection read',
                },
                'live_evidence': 'NOT_QUERIED_BY_SOURCE_INVENTORY_RUNTIME_REMAINS_SEPARATE',
                'current_unexpired_signed_cases': 'NOT_ESTABLISHED_FOR_CURRENT_RUNTIME',
                'full_l7': 'NOT_PROVEN_BY_SOURCE_INVENTORY',
                'requirements_after_source_readiness': [
                    'Accepted exact source/image runtime and authenticated actual subject case',
                    'Permitted model/tier/cost/current policy or real deterministic event as applicable',
                    'Original Objective/queue/artifact/durable action joins and separate registered reviewer',
                    'Protected fixed main admission and independent signature, freshness/source-bound projection',
                    'All 74 distinct cases including actual event/recovery/tool/clean-room/revalidation requirements',
                ],
            })
    after = _pins(root)
    if before != after:
        raise ValueError('SOURCE_CHANGED_DURING_INVENTORY')
    return {
        'schema': 'prime.agent-cert-source-readiness.v1', 'captured_at': now.astimezone(timezone.utc).isoformat(),
        'source_revision': source_revision, 'canonical_main_revision': canonical_main_revision,
        'source_scope': 'WORKTREE_FILE_PINS_NOT_AN_ACCEPTED_DEPLOYMENT',
        'revision_reference_scope': 'CALLER_SUPPLIED_GIT_REFERENCE_WITH_ACTUAL_FILE_PINS',
        'registry_sha256': registry_sha, 'source_file_sha256': before,
        'permanent_agents': 21, 'owned_capabilities': 29, 'dimensions_per_capability': 28,
        'cases_per_capability': 74, 'required_capability_cases': 2146,
        'existing_matrix_case_ids': list(keys), 'capability_rows': rows,
        'source_canonical_adapter_oracle_count': sum(len(row['canonical_adapter_oracle_ready_cases']) for row in rows),
        'active_protected_admission_count': len(active['cases']),
        'inspected_historical_signed_evidence': historical,
        'source_generated_certification_claims': 0,
        'runtime_observation': 'NOT_PERFORMED', 'host_observation': 'NOT_PERFORMED',
        'limits': [
            'Canonical challenges without an owned event/output oracle are missing implementation, not external-only gaps',
            'Source tests or adapters never establish live case execution, signature currentness or L7',
            'Historical signed evidence remains retained; this inventory neither revokes nor resets valid cases',
            'No current certification store or private runtime configuration was inspected',
            'Unsupported cases are not classified as model-answer quality: authorization, authority, denial, evidence integrity and event requirements need their actual domain contracts',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--canonical-main-revision', required=True)
    args = parser.parse_args()
    value = build_source_readiness(source_revision=args.source_revision,
        canonical_main_revision=args.canonical_main_revision, now=datetime.now(timezone.utc))
    print(canonical(value).decode('utf-8'))


if __name__ == '__main__':
    main()
