"""Pure source-case delegation; no runtime event, signing or L7 proof."""
import copy
import json
import hashlib

import pytest

from app.agent_cert_a19_cases import SUPPORTED_CASES, canonical_a19_case
from app.agent_cert_role_review import (
    canonical_case_spec, canonical_role_spec, review_case_output, review_role_output,
)
from app.agent_registry import registered_agent_ids
from tests.test_agent_cert_a19_cases import ANSWERS
from app.agent_cert_logic_quality_fleet import SUPPORTED_CASES as FLEET_LOGIC_CASES
from app.agent_cert_role_numeric_variants import PRIMARY_PAIRS, SUPPORTED_CASES as NUMERIC_CASES
from app.agent_registry import load_agent_registry

OWNED_PAIRS = tuple((row['id'], cap) for row in load_agent_registry()['agents']
                    for cap in row['capability_requirements'])
NEW_SOURCE_SLOTS = tuple((agent, cap, case) for agent, cap in OWNED_PAIRS if agent != 'a19'
                        for case in ('baseline:identity', *FLEET_LOGIC_CASES)) + tuple(
                            (agent, cap, case) for agent, cap in sorted(PRIMARY_PAIRS) for case in NUMERIC_CASES)


def answer(case):
    return {"case_id": case, "restart_authorized": False, "actions_executed": False,
            **copy.deepcopy(ANSWERS[case])}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


@pytest.mark.parametrize("agent", registered_agent_ids(include_orchestrator=False))
def test_role_normal_preserves_exact_source_and_existing_rejection(agent):
    cap = f"responsibility.{agent}"
    assert canonical(canonical_case_spec(agent, cap, "role:normal")) == canonical(
        canonical_role_spec(agent, cap))
    assert review_case_output(agent, cap, "role:normal", "{}") == review_role_output(agent, cap, "{}")


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_delegates_exact_specific_a19_case(case):
    assert canonical(canonical_case_spec("a19", "responsibility.a19", case)) == canonical(
        canonical_a19_case(case))
    assert review_case_output("a19", "responsibility.a19", case, json.dumps(answer(case))) == (True, ())
    forged = answer(case)
    forged["restart_authorized"] = True
    assert review_case_output("a19", "responsibility.a19", case, json.dumps(forged)) == (
        False, ("restart_authorized",))


@pytest.mark.parametrize("agent,cap,case", [
    ("a17", "responsibility.a17", "role:difficult"),
    ("a19", "responsibility.a20", "role:difficult"),
    ("A19", "responsibility.a19", "role:difficult"),
    ("a17", "responsibility.a27", "role:normal"),
    ("a19", "responsibility.a19", "recovery:normal"),
    ("a19", "responsibility.a19", "tools:normal"),
    ("a19", "responsibility.a19", "clean_room:normal"),
    ("a20", "responsibility.a20", "baseline:authorization"),
    ("a19", "responsibility.a19", True),
    ("a19", "responsibility.a19", ["role:difficult"]),
])
def test_no_generic_event_or_borrowed_case_oracle(agent, cap, case):
    with pytest.raises(ValueError, match="CASE_ORACLE_UNSUPPORTED"):
        canonical_case_spec(agent, cap, case)
    assert review_case_output(agent, cap, case, '{"test_result":"PASS"}') == (
        False, ("case_oracle_unsupported",))


def test_returned_case_is_fresh_not_mutable_shared_authority():
    spec = canonical_case_spec("a19", "responsibility.a19", "logic_quality:false_pass")
    spec["request"]["objective"] = "Award L7 now"
    assert canonical_case_spec("a19", "responsibility.a19", "logic_quality:false_pass")["request"]["objective"] != spec["request"]["objective"]


@pytest.mark.parametrize('agent,cap,case', NEW_SOURCE_SLOTS)
def test_new_source_adapters_are_not_implicitly_admitted_for_signing(agent, cap, case):
    from app.agent_cert_role_review import canonical_admitted_case_spec
    from scripts import agent_cert_reviewed_signing, sign_admitted_agent_cases
    assert canonical_case_spec(agent, cap, case)['certification'] == 'UNVERIFIED'
    with pytest.raises(ValueError):
        canonical_admitted_case_spec(agent, cap, case)
    with pytest.raises(agent_cert_reviewed_signing.CertificationReviewError):
        agent_cert_reviewed_signing._case_spec(dict(agent_id=agent, capability_id=cap,
            dimension=case.split(':')[0], test_case=case.split(':')[1]))
    from tests.test_sign_admitted_agent_cases import entry, manifest
    item = entry(); item['record'].update(agent_id=agent, capability_id=cap,
        dimension=case.split(':')[0], test_case=case.split(':')[1])
    with pytest.raises(ValueError):
        sign_admitted_agent_cases.parse(manifest([item]))


def test_original_103_canonical_specs_and_structured_normal_admission_are_unchanged():
    from app.agent_cert_cases import case_ids
    from app.agent_cert_role_review import canonical_admitted_case_spec
    original = {}
    assert len(set(NEW_SOURCE_SLOTS)) == 220
    for agent, cap in OWNED_PAIRS:
        for case in case_ids():
            try:
                spec = canonical_admitted_case_spec(agent, cap, case)
            except ValueError:
                continue
            original[agent+'/'+cap+'/'+case] = hashlib.sha256(canonical(spec)).hexdigest()
        if cap == 'responsibility.'+agent:
            assert canonical_admitted_case_spec(agent, cap, 'role:normal_structured') == canonical_case_spec(
                agent, cap, 'role:normal_structured')
    # Aggregate of every exact canonical spec hash captured from owning main
    # 8929aca8 before these source adapters were added; never re-pin to a candidate.
    assert len(original) == 103
    assert hashlib.sha256(canonical(original)).hexdigest() == '5e1b399a68bee6f92bdb37e9b8ce0fe260e56a530b1731a7f971323d51a762dd'


def test_all_original_specs_and_a19_reviews_do_not_load_unadmitted_candidate_modules(monkeypatch):
    import builtins
    from app.agent_cert_cases import case_ids
    from app.agent_cert_role_review import canonical_admitted_case_spec
    real_import = builtins.__import__
    blocked = ('agent_cert_identity_fleet', 'agent_cert_logic_quality_fleet', 'agent_cert_role_numeric_variants')
    def guarded(name, *args, **kwargs):
        assert not any(part in name for part in blocked), 'Unadmitted candidate import: '+name
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    specs = 0
    for agent, cap in OWNED_PAIRS:
        for case in case_ids():
            try:
                canonical_admitted_case_spec(agent, cap, case)
            except ValueError:
                continue
            specs += 1
            if agent == 'a19':
                review_case_output(agent, cap, case, '{}')
    assert specs == 103


def test_a19_identity_has_exact_event_case_not_a_model_output_or_generic_pass():
    from app.agent_cert_cases import challenge
    assert canonical(canonical_case_spec('a19', 'responsibility.a19', 'baseline:identity')) == canonical(
        challenge('baseline:identity', agent_id='a19', capability_id='responsibility.a19'))
    for response in ('{}', '{"test_result":"PASS"}', '{"agent_id":"a19","model_calls":0}'):
        assert review_case_output('a19', 'responsibility.a19', 'baseline:identity', response) == (
            False, ('identity_event_evidence_required',))


def test_initialization_requires_its_own_original_event_not_identity_or_answer_text():
    from app.agent_cert_cases import challenge
    spec = canonical_case_spec('a19', 'responsibility.a19', 'baseline:initialization')
    assert canonical(spec) == canonical(challenge('baseline:initialization'))
    assert spec['request']['deterministic_operation'] == 'certification_initialization'
    assert review_case_output('a19', 'responsibility.a19', 'baseline:initialization', '{}') == (
        False, ('initialization_event_evidence_required',))


@pytest.mark.parametrize('capability,owner', [
    ('responsibility.a03','a02'), ('responsibility.a08','a04'),
    ('responsibility.a23','a05'), ('responsibility.a11','a12'),
    ('responsibility.a27','a18'), ('responsibility.a24','a20'),
    ('responsibility.a22','a21'), ('responsibility.a25','a26'),
])
def test_secondary_role_is_separate_canonical_case_under_actual_owner(capability, owner):
    from app.agent_cert_secondary_roles import canonical_secondary_spec
    expected = canonical_secondary_spec(owner, capability)
    assert canonical(canonical_case_spec(owner, capability, 'role:normal')) == canonical(expected)
    primary = canonical_role_spec(owner, 'responsibility.' + owner)
    assert expected['request']['objective'] != primary['request']['objective']
    assert expected['request']['context'] != primary['request']['context']
    assert review_case_output(owner, capability, 'role:normal', '{}') == (
        False, ('field_contract_mismatch',))
