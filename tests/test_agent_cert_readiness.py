"""Source-only inventory; never certify from these temporary checks."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from scripts import agent_cert_readiness as readiness
from scripts import sign_admitted_agent_cases as admission


NOW = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)
SOURCE = 'a' * 40
MAIN = 'b' * 40


@pytest.fixture
def inventory():
    return readiness.build_source_readiness(source_revision=SOURCE,
        canonical_main_revision=MAIN, now=NOW)


def test_exact21_agents29_owned_capabilities_and_existing74_case_matrix(inventory):
    rows = inventory['capability_rows']
    assert len(rows) == 29 and len({r['agent_id'] for r in rows}) == 21
    assert len({r['capability_id'] for r in rows}) == 29
    assert inventory['dimensions_per_capability'] == 28
    assert inventory['cases_per_capability'] == 74
    assert inventory['required_capability_cases'] == 2146
    assert len(set(inventory['existing_matrix_case_ids'])) == 74
    assert inventory['source_canonical_adapter_oracle_count'] == 140
    assert all('role:normal' in r['canonical_adapter_oracle_ready_cases'] for r in rows)
    assert all('baseline:initialization' in r['distinct_zero_model_event_adapter_cases'] for r in rows)


def test_distinct_a19_events_and_quality_do_not_launder_generic_event_prose(inventory):
    row = next(r for r in inventory['capability_rows'] if r['agent_id'] == 'a19')
    assert len(row['canonical_adapter_oracle_ready_cases']) == 56
    assert row['distinct_zero_model_event_adapter_cases'] == ['baseline:identity', 'baseline:initialization',
        'general:artifact_consume', 'general:artifact_produce', 'general:review', 'general:handoff', 'general:recovery',
        'authority:complete', 'tools:complete', 'context_integrity:complete', 'unauthorized_rejection:authorized', 'unauthorized_rejection:unauthorized',
        'tool_recovery:tool_failure', 'tool_recovery:bounded_response', 'evidence_integrity:complete', 'graceful_degradation:complete']
    assert len(row['source_pinned_cloud_transport_cases']) == 40
    assert 'tools:complete' not in row['locally_actionable_missing_case_adapter_ids']
    assert 'tools:complete' not in row['source_pinned_cloud_transport_cases']
    assert 'clean_room_audit:complete' in row['locally_actionable_missing_case_adapter_ids']
    assert 'baseline:authorization' in row['source_pinned_cloud_transport_cases']
    assert 'authority:complete' not in row['locally_actionable_missing_case_adapter_ids']
    assert 'unauthorized_rejection:authorized' not in row['locally_actionable_missing_case_adapter_ids']
    assert 'unauthorized_rejection:unauthorized' not in row['locally_actionable_missing_case_adapter_ids']
    assert 'unauthorized_rejection:owner_only' in row['locally_actionable_missing_case_adapter_ids']
    assert 'general:artifact_consume' not in row['locally_actionable_missing_case_adapter_ids']
    assert 'missing_event_executor_oracle_ids' not in row
    assert 'locally_actionable_missing_quality_adapter_ids' not in row
    assert 'role:difficult' not in row['missing_case_adapter_oracle_ids']
    assert row['full_l7'] == 'NOT_PROVEN_BY_SOURCE_INVENTORY'


def test_eight_secondary_source_oracles_have_only_explicit_prepared_transport(inventory):
    secondary = [r for r in inventory['capability_rows'] if not r['primary_capability']]
    assert len(secondary) == 8
    for row in secondary:
        assert row['canonical_adapter_oracle_ready_cases'] == ['baseline:identity', 'baseline:initialization', 'role:normal']
        assert row['source_pinned_cloud_transport_cases'] == ['role:normal']
        assert row['cloud_transport_missing_for_ready_quality_cases'] == []
        assert row['generic_queue_observer_quality_gap_cases'] == []


def test_source_readiness_never_awards_live_signature_or_l7(inventory):
    assert inventory['source_generated_certification_claims'] == 0
    assert inventory['runtime_observation'] == inventory['host_observation'] == 'NOT_PERFORMED'
    root = Path(__file__).resolve().parents[1]
    active = admission.parse((root / admission.MANIFEST).read_bytes())
    assert inventory['active_protected_admission_count'] == len(active)
    historical = inventory['inspected_historical_signed_evidence']
    assert len(historical['records']) == 1
    assert historical['records'][0]['expired'] is True
    assert historical['records'][0]['source_revision'] != SOURCE
    assert historical['records'][0]['signature_verification'] == 'NOT_REPEATED_BY_SOURCE_INVENTORY'
    assert all(r['current_unexpired_signed_cases'] == 'NOT_ESTABLISHED_FOR_CURRENT_RUNTIME'
               for r in inventory['capability_rows'])


@pytest.mark.parametrize('field,value', [('source_revision', True), ('source_revision', 'a' * 39),
    ('canonical_main_revision', 'UNKNOWN'), ('now', datetime(2026, 10, 8))])
def test_invalid_inventory_binding_does_not_produce_a_fresh_claim(field, value):
    args = dict(source_revision=SOURCE, canonical_main_revision=MAIN, now=NOW)
    args[field] = value
    with pytest.raises(ValueError, match='SOURCE_BINDINGS_INVALID'):
        readiness.build_source_readiness(**args)


def test_changed_source_during_inventory_is_refused(monkeypatch):
    original = readiness._pins
    calls = []
    def pins(root):
        result = original(root); calls.append(True)
        if len(calls) > 1:
            result['app/agent_certification.py'] = 'f' * 64
        return result
    monkeypatch.setattr(readiness, '_pins', pins)
    with pytest.raises(ValueError, match='SOURCE_CHANGED_DURING_INVENTORY'):
        readiness.build_source_readiness(source_revision=SOURCE, canonical_main_revision=MAIN, now=NOW)


def test_complete_cached_registry_must_match_current_original_source(monkeypatch):
    loaded = readiness.agent_registry.load_agent_registry()
    stale = copy.deepcopy(loaded); stale['agents'][0]['authority'] = 'restricted'
    monkeypatch.setattr(readiness.agent_registry, 'load_agent_registry', lambda: stale)
    with pytest.raises(ValueError, match='LOADED_REGISTRY_SOURCE_CHANGED'):
        readiness.build_source_readiness(source_revision=SOURCE, canonical_main_revision=MAIN, now=NOW)


@pytest.mark.parametrize('raw', [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e309}'])
def test_duplicate_or_nonfinite_source_is_not_normalized_into_pass(raw):
    with pytest.raises(ValueError):
        readiness._parse(raw)


def test_ready_plus_missing_partition_exact_contract_without_resetting_any_case(inventory):
    all_cases = set(inventory['existing_matrix_case_ids'])
    for row in inventory['capability_rows']:
        ready = set(row['canonical_adapter_oracle_ready_cases'])
        missing = set(row['missing_case_adapter_oracle_ids'])
        assert not ready & missing and ready | missing == all_cases
        assert set(row['canonical_case_sha256']) == ready
        assert all(len(value) == 64 for value in row['canonical_case_sha256'].values())
        assert 'NOT_QUERIED' in row['live_evidence']
        assert row['missing_adapter_state'] == 'OPEN_LOCAL_IMPLEMENTATION_NOT_EXTERNAL'
        assert row['certification_domain']['status'] == 'NOT_OBSERVED'
        assert row['certification_domain']['pass_fail_blocked_claim'] is None
