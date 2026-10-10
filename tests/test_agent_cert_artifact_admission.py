"""Source admission inventory only; no executed case/admission/cloud/L7 award."""
from datetime import datetime, timezone
import copy
import json
from pathlib import Path

import pytest

from app import agent_cert_artifact_events as events
from app import agent_cert_transport as transport
from scripts import sign_admitted_agent_cases as loader
from scripts import agent_cert_readiness as readiness
from tests.test_sign_admitted_agent_cases import entry, manifest, REVIEW


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_exact_owned_artifact_admissions_stay_local_distinct_events(case_id):
    value = entry()
    value['record'].update(dimension=case_id.split(':')[0], test_case=case_id.split(':')[1])
    assert loader.parse(manifest([value])) == [value]
    wrong = copy.deepcopy(value)
    wrong['record'].update(agent_id='a20', capability_id='responsibility.a20')
    with pytest.raises(ValueError): loader.parse(manifest([wrong]))
    for policy, pin in (({}, 'f' * 64), (None, 'f' * 64), ({}, None)):
        wrong = dict(value, cloud_policy=policy, owner_policy_sha256=pin)
        with pytest.raises(ValueError): loader.parse(manifest([wrong]))


@pytest.mark.parametrize('case_id', events.SUPPORTED_CASES)
def test_artifact_custody_cannot_acquire_cloud_model_oracle_or_policy(case_id):
    spec = events.canonical_artifact_case(case_id)
    with pytest.raises(ValueError, match='zero-model artifact events forbid cloud transport'):
        transport.canonical_cert_case('a19', 'responsibility.a19', case_id)
    with pytest.raises(ValueError): transport.case_transport_identity(spec)
    with pytest.raises(ValueError):
        transport.bind_cloud_case(spec, {}, expected_source_revision='a' * 40, expected_policy_sha256='b' * 64)


def test_artifact_producer_and_validator_added_to_complete_protected_code_pins(tmp_path):
    assert len(loader.CODE_FILES) == len(set(loader.CODE_FILES)) == 67
    assert 'app/agent_cert_revalidation.py' in loader.CODE_FILES
    assert 'app/agent_cert_revalidation.py' in loader.RUNTIME_REVIEW_CODE_FILES
    assert 'app/agent_cert_fresh_input.py' in loader.CODE_FILES and 'app/agent_cert_fresh_input.py' in loader.RUNTIME_REVIEW_CODE_FILES
    assert 'app/agent_cert_clean_room.py' in loader.CODE_FILES
    assert 'app/agent_cert_clean_room.py' in loader.RUNTIME_REVIEW_CODE_FILES
    for dependency in ('app/spine.py', 'app/generated/portfolio_contracts.py'):
        assert dependency in loader.CODE_FILES and dependency in loader.RUNTIME_REVIEW_CODE_FILES
    assert 'app/context_pack.py' in loader.CODE_FILES and 'app/context_pack.py' in loader.RUNTIME_REVIEW_CODE_FILES
    assert 'app/agent_cert_owned_identity.py' in loader.CODE_FILES
    assert 'app/agent_cert_owned_identity.py' in loader.RUNTIME_REVIEW_CODE_FILES
    assert 'app/handoff.py' in loader.CODE_FILES and 'app/handoff.py' in loader.RUNTIME_REVIEW_CODE_FILES
    assert 'app/agent_cert_artifact_events.py' in loader.CODE_FILES
    assert 'app/agent_cert_authority_events.py' in loader.CODE_FILES
    assert 'app/agent_cert_recovery_events.py' in loader.CODE_FILES
    assert 'app/agent_cert_recovery_events.py' in loader.RUNTIME_REVIEW_CODE_FILES
    originals = {}
    for name in loader.CODE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'TEMPORARY_SOURCE_ONLY_FIXTURE')
        originals[name] = path.read_bytes()
    loader.unchanged_reviewer_code(tmp_path, REVIEW, read_revision=originals.__getitem__)
    originals['app/agent_cert_artifact_events.py'] += b'CHANGED_VALIDATOR_OR_PRODUCER'
    with pytest.raises(ValueError): loader.unchanged_reviewer_code(tmp_path, REVIEW, read_revision=originals.__getitem__)


def test_inventory_counts_artifact_events_without_inference_or_certification_claims():
    result = readiness.build_source_readiness(source_revision='a' * 40, canonical_main_revision='b' * 40,
        now=datetime.now(timezone.utc))
    a19 = next(row for row in result['capability_rows'] if row['agent_id'] == 'a19')
    assert len(a19['canonical_adapter_oracle_ready_cases']) == 72
    assert set(events.SUPPORTED_CASES) <= set(a19['distinct_zero_model_event_adapter_cases'])
    assert not set(events.SUPPORTED_CASES) & set(a19['source_pinned_cloud_transport_cases'])
    assert not set(events.SUPPORTED_CASES) & set(a19['cloud_transport_missing_for_ready_quality_cases'])
    assert not set(events.SUPPORTED_CASES) & set(a19['generic_queue_observer_quality_gap_cases'])
    assert result['source_canonical_adapter_oracle_count'] == 156
    assert 'health:complete' in a19['distinct_zero_model_event_adapter_cases']
    assert 'health:complete' not in a19['source_pinned_cloud_transport_cases']
    assert 'health:complete' not in a19['locally_actionable_missing_case_adapter_ids']
    assert 'recovery:complete' in a19['distinct_zero_model_event_adapter_cases']
    assert 'recovery:complete' not in a19['source_pinned_cloud_transport_cases']
    assert 'conflict_resolution:complete' in a19['distinct_zero_model_event_adapter_cases']
    assert 'conflict_resolution:complete' not in a19['source_pinned_cloud_transport_cases']
    assert 'conflict_resolution:complete' not in a19['locally_actionable_missing_case_adapter_ids']
    assert 'cross_agent_conflict:complete' in a19['distinct_zero_model_event_adapter_cases']
    assert 'cross_agent_conflict:complete' not in a19['source_pinned_cloud_transport_cases']
    assert 'cross_agent_conflict:complete' not in a19['locally_actionable_missing_case_adapter_ids']
    assert {'fresh_challenge:complete','unseen_task:complete'} <= set(a19['distinct_zero_model_event_adapter_cases'])
    assert 'independent_verification:complete' in a19['distinct_zero_model_event_adapter_cases']
    assert 'cross_verification:complete' in a19['distinct_zero_model_event_adapter_cases']
    assert 'cross_verification:complete' not in a19['source_pinned_cloud_transport_cases']
    assert 'collaboration:complete' in a19['distinct_zero_model_event_adapter_cases']
    assert 'collaboration:complete' not in a19['source_pinned_cloud_transport_cases']
    assert 'collaboration:complete' not in a19['locally_actionable_missing_case_adapter_ids']
    assert 'clean_room_audit:complete' in a19['distinct_zero_model_event_adapter_cases']
    assert 'clean_room_audit:complete' not in a19['source_pinned_cloud_transport_cases']
    assert 'clean_room_audit:complete' not in a19['locally_actionable_missing_case_adapter_ids']
    assert 'independent_verification:complete' not in a19['source_pinned_cloud_transport_cases']
    assert 'independent_verification:complete' not in a19['locally_actionable_missing_case_adapter_ids']
    assert 'continuous_revalidation:complete' in a19['distinct_zero_model_event_adapter_cases']
    assert 'continuous_revalidation:complete' not in a19['source_pinned_cloud_transport_cases']
    assert {'authority:complete', 'unauthorized_rejection:authorized', 'unauthorized_rejection:unauthorized'} <= set(
        a19['distinct_zero_model_event_adapter_cases'])
    assert 'unauthorized_rejection:owner_only' not in a19['locally_actionable_missing_case_adapter_ids']
    assert 'unauthorized_rejection:owner_only' in a19['distinct_zero_model_event_adapter_cases']
    root = Path(__file__).resolve().parents[1]
    active = loader.parse((root / loader.MANIFEST).read_bytes())
    assert result['active_protected_admission_count'] == len(active)
    assert result['source_generated_certification_claims'] == 0
    assert result['runtime_observation'] == 'NOT_PERFORMED'
    assert a19['full_l7'] == 'NOT_PROVEN_BY_SOURCE_INVENTORY'
    assert 'app/agent_cert_artifact_events.py' in result['source_file_sha256']
    assert 'app/handoff.py' in result['source_file_sha256']
    assert 'app/context_pack.py' in result['source_file_sha256']


def test_handoff_helper_is_closed_and_source_only():
    assert "app/agent_cert_handoff_gap.py" in loader.CODE_FILES
    assert "app/agent_cert_handoff_gap.py" in loader.RUNTIME_REVIEW_CODE_FILES
