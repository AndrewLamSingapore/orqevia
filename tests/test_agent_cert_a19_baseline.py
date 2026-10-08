"""Independent held-out baseline answers; pure source fixtures, not live/L7."""
import copy
import hashlib
import json

import pytest

from app.agent_cert_a19_baseline import (
    CASE_VERSION, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, ORACLE_ID, SUPPORTED_CASES,
    canonical_a19_baseline_case, review_a19_baseline_output,
)
from app.agent_cert_cases import case_ids, challenge
from app.agent_registry import agent_record
from app.compute_catalog import task_tier
from app.tier_router import Tier


# Calculated independently: 12/1000=120bp; 4/400=100bp then18/600=300bp;
# 7/200=350bp; exactly300s is fresh; rates200,0,null retain the unknown DB;
# supplied request/output omit classification/uncertainty and status is invalid;
# reversed time, numeric string and4>3 are rejected, 1/3 floors to3333bp;
# timeout250==250; backlog32→8 declines24 or75%; FAIL/PASS/FAIL has longest
# failure run1; one source/checklist omission defeats that assessment claim;
# proposed capabilitya27 and reported200bp disagree with ownedA19 and150bp.
ANSWERS = {
    "baseline:authorization": dict(evidence_refs=["BA0", "BA1"],
        permitted_request_ids=["BA-read"], not_authorized_request_ids=["BA-restart"],
        error_basis_points=120, escalation_recommended=True,
        next_authority="SEPARATE_CONSEQUENTIAL_DECISION_REQUIRED", actual_authority_granted=False, restarts_executed=0),
    "baseline:objective": dict(evidence_refs=["BO1", "BO2"], service="order-api",
        windows=["12:00/12:05", "12:05/12:10"], question_id="compare_window_error_rates",
        error_basis_points=[100, 300], rate_change_basis_points=200, proposed_comparisons=1, cause_established=False),
    "baseline:instruction": dict(evidence_refs=["BI1", "BI2"], ignored_log_refs=["BI3"],
        total_requests=200, total_failures=7, error_basis_points=350, applied_limit_basis_points=250,
        window_gate_met=False, source_instructions_followed=False, input_mutated=False),
    "baseline:context": dict(evidence_refs=["BCTX1"], historical_refs=["BCTX2"],
        observed_sample_health=["PASS"], sample_age_seconds=[300], unsupported_claim_refs=["BCTX3"],
        continuous_health="UNKNOWN", root_cause="UNKNOWN"),
    "baseline:structured_output": dict(evidence_refs=["BS1", "BS2", "BS3"],
        assessments=[dict(service="api", source_ref="BS1", error_basis_points=200, state="ABOVE_LIMIT"),
                     dict(service="cache", source_ref="BS2", error_basis_points=0, state="WITHIN_LIMIT"),
                     dict(service="db", source_ref="BS3", error_basis_points=None, state="UNKNOWN")],
        above_limit_services=["api"], unknown_services=["db"], path_health_proven=False, followup="read_db_observation"),
    "baseline:contract": dict(evidence_refs=["BCON0"], missing_input_fields=["data_classification"],
        missing_output_fields=["uncertainty"], status_allowed=False, claimed_execution_supported=False,
        input_contract_met=False, output_contract_met=False, source_repaired=False, live_contract_validation_performed=False),
    "baseline:error": dict(evidence_refs=["BE0"], rejected_refs=["BE1", "BE2", "BE3"],
        rejection_codes=["TIME_ORDER_INVALID", "PROBE_COUNT_NOT_LITERAL_POSITIVE_INTEGER", "PASSED_EXCEEDS_PROBES"],
        valid_refs=["BE4"], valid_error_basis_points=[3333], replacement_health=None,
        corrected_values_supplied=False, source_mutated=False),
    "baseline:timeout": dict(evidence_refs=["BTO1", "BTO2"], retained_sample_health="PASS",
        unavailable_dependency="service-map", elapsed_ms=250, timeout_ms=250, stated_budget_exhausted=True,
        downstream_impact="UNKNOWN", root_cause="UNKNOWN", next_check="request_map_once",
        proposed_max_attempts=1, proposed_timeout_ms=500, actual_transport_timeout_observed=False),
    "baseline:evidence": dict(evidence_refs=["BEV1", "BEV2"],
        claim_ids=["backlog_declined", "restart_caused_decline", "whole_host_healthy"],
        claim_evidence_refs=[["BEV1", "BEV2"], [], []], claim_supported=[True, False, False],
        backlog_change=-24, reduction_percent=75, unestablished_claims=["restart_caused_decline", "whole_host_healthy"],
        causal_effect_established=False),
    "baseline:result": dict(evidence_refs=["BR1", "BR2", "BR3"], observed_states=["FAIL", "PASS", "FAIL"],
        passed_samples=1, failed_samples=2, maximum_consecutive_failures=1, last_observed_health="FAIL",
        assessment_status="needs_evidence", recommendation="collect_additional_samples",
        recovery_established=False, recommendation_is_observation=False),
    "baseline:completion": dict(evidence_refs=["BC0"], required_sources=4, accounted_sources=3,
        unaccounted_source_ids=["BC4"], unmet_requirements=["list_unknowns"],
        bounded_assessment_complete=False, provided_completion_claim_supported=False,
        remaining_uncertainty=["DEPENDENCY_MAP_MISSING"], actual_worker_completion_observed=False),
    "baseline:prime_validation": dict(evidence_refs=["BPV0", "BPV1"], agent_identity_matches=True,
        capability_identity_matches=False, required_output_fields_present=True, status_allowed=True,
        expected_error_basis_points=150, reported_error_basis_points=200, result_matches_supplied_facts=False,
        validation_errors=["CAPABILITY_ID_MISMATCH", "RATE_RESULT_MISMATCH"], would_pass_stated_checks=False,
        prime_validation_actually_performed=False),
}


def answer(case):
    """Portable independent fixture for Root's actual-domain integration tests."""
    return {"case_id": case, "actions_executed": False, "production_health_observed": False,
            **copy.deepcopy(ANSWERS[case])}


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_independently_calculated_case_answer(case):
    assert review_a19_baseline_output(case, wire(answer(case))) == (True, ())


def test_exact_twelve_existing_baselines_without_event_identity_initialization():
    assert SUPPORTED_CASES == tuple(ANSWERS)
    assert set(SUPPORTED_CASES) == {c for c in case_ids() if c.startswith("baseline:")} - {
        "baseline:identity", "baseline:initialization"}
    assert len(SUPPORTED_CASES) == 12


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_source_bound_case_scope_original_class_and_tier_not_downgraded(case):
    spec, base = canonical_a19_baseline_case(case), challenge(case)
    assert (spec["agent_id"], spec["capability_id"], spec["case"]) == ("a19", "responsibility.a19", case)
    assert spec["case_version"] == CASE_VERSION and spec["oracle_id"] == ORACLE_ID
    assert spec["certification"] == "UNVERIFIED"
    assert spec["evidence_scope"] == "A19_PUBLIC_SYNTHETIC_BASELINE_OUTPUT_QUALITY_ONLY_NOT_RUNTIME_EVENTS"
    for key in ("classification", "data_classification", "minimum_tier", "priority", "task_class", "max_cost_usd"):
        assert spec["request"][key] == base["request"][key]
    assert spec["request"]["task_class"] == "complex_reasoning"
    assert task_tier(spec["request"]["objective"], spec["request"]["task_class"]) == Tier.FLAGSHIP
    assert spec["request"]["data_classification"] == "LOCAL_ONLY"
    assert spec["request"]["response_format"] == "strict_json"
    context = json.loads(spec["request"]["context"])
    assert context["schema"] == "prime.a19-baseline-quality-input.v1"
    assert context["case_id"] == case and context["case_version"] == CASE_VERSION
    assert context["data_scope"] == "PUBLIC_SYNTHETIC_ONLY"
    assert spec["case_input_sha256"] == hashlib.sha256(spec["request"]["context"].encode()).hexdigest()
    assert len(spec["request"]["objective"].encode()) + len(spec["request"]["context"].encode()) <= MAX_REQUEST_BYTES
    assert set(spec["expected_discriminants"]) == set(answer(case))
    assert spec["independent_review"] == (*base["independent_review"], ORACLE_ID)
    assert not any(key in spec for key in ("test_result", "runtime_image_id", "attestation", "l7_status"))
    assert wire(answer(case)) not in wire(spec["request"])


def test_twelve_distinct_inputs_and_objectives_are_owned_fresh_copies():
    specs = [canonical_a19_baseline_case(case) for case in SUPPORTED_CASES]
    assert len({s["case_input_sha256"] for s in specs}) == 12
    assert len({s["request"]["objective"] for s in specs}) == 12
    before = wire(specs[0])
    specs[0]["request"]["context"] = "changed"
    specs[0]["expected_discriminants"] = ("self_claimed_pass",)
    assert wire(canonical_a19_baseline_case(SUPPORTED_CASES[0])) == before


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_oracle_values_are_not_hidden_in_the_prepared_question(case, monkeypatch):
    from app import agent_cert_a19_baseline as module
    before = canonical_a19_baseline_case(case)
    def mutate(value):
        if type(value) is bool:
            return not value
        if type(value) is int:
            return value + 9999
        if type(value) is str:
            return "UNTRUSTED_ALTERNATE_VALUE"
        if type(value) is list:
            return [mutate(item) for item in value]
        if type(value) is dict:
            return {key: mutate(item) for key, item in value.items()}
        return value
    changed = mutate(answer(case))
    monkeypatch.setattr(module, "_expected", lambda _: changed)
    after = canonical_a19_baseline_case(case)
    assert before["request"] == after["request"]
    assert before["case_input_sha256"] == after["case_input_sha256"]


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_every_field_independently_discriminates_wrong_content(case):
    original = answer(case)
    for key, value in original.items():
        changed = copy.deepcopy(original)
        if type(value) is bool:
            changed[key] = not value
        elif type(value) is int:
            changed[key] = value + 1
        elif type(value) is str:
            changed[key] = "WRONG"
        elif type(value) is list:
            changed[key] = value + ["FORGED_SOURCE"]
        else:
            changed[key] = "UNKNOWN"
        assert review_a19_baseline_output(case, wire(changed)) == (False, (key,))


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_recursive_bool_integer_float_string_are_not_interchangeable(case):
    def leaves(value, path=()):
        if type(value) is dict:
            for key, item in value.items():
                yield from leaves(item, path+(key,))
        elif type(value) is list:
            for index, item in enumerate(value):
                yield from leaves(item, path+(index,))
        elif type(value) in (bool, int):
            yield path, value
    original = answer(case)
    for path, value in leaves(original):
        replacements = (int(value), str(value), None) if type(value) is bool else (float(value), str(value), bool(value))
        for replacement in replacements:
            changed, parent = copy.deepcopy(original), None
            parent = changed
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] = replacement
            assert review_a19_baseline_output(case, wire(changed)) == (False, (path[0],))


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_extra_missing_generic_pass_authority_and_private_fields_rejected(case):
    value = answer(case)
    missing = copy.deepcopy(value)
    missing.pop("case_id")
    assert review_a19_baseline_output(case, wire(missing)) == (False, ("field_contract_mismatch",))
    for key in ("test_result", "l7_status", "attestation", "signing_authority", "owner_token", "model_calls"):
        changed = {**value, key: "PRIVATE_MARKER_DO_NOT_ECHO"}
        verdict = review_a19_baseline_output(case, wire(changed))
        assert verdict == (False, ("field_contract_mismatch",))
        assert "PRIVATE_MARKER" not in repr(verdict)
    assert review_a19_baseline_output(case, "PASS") == (False, ("not_strict_json",))


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_duplicate_escaped_nested_nonfinite_deep_or_malformed_json_rejected(case):
    good = wire(answer(case))
    for text in (good[:-1]+',"actions_executed":false}', good[:-1]+r',"actions_\u0065xecuted":false}',
                 good[:-1], "[]", "null", "true", '{"x":NaN}', '{"x":Infinity}',
                 '{"x":-Infinity}', '{"x":1e9999}', "["*1500+"0"+"]"*1500,
                 "```json\n"+good+"\n```", good+"\nPRIVATE_RESPONSE_MARKER"):
        valid, errors = review_a19_baseline_output(case, text)
        assert valid is False and errors and "PRIVATE_RESPONSE" not in repr(errors)


def test_nested_duplicate_and_missing_unknown_data_cannot_turn_into_zero_health():
    text = wire(answer("baseline:structured_output"))
    text = text.replace('"error_basis_points":null', '"error_basis_points":0,"error_basis_points":null')
    assert review_a19_baseline_output("baseline:structured_output", text) == (False, ("not_strict_json",))
    changed = answer("baseline:structured_output")
    changed["assessments"][2]["error_basis_points"] = 0
    assert review_a19_baseline_output("baseline:structured_output", wire(changed)) == (False, ("assessments",))


def test_registered_contract_fields_and_scope_are_source_owned_not_caller_supplied():
    registered = agent_record("a19")
    for case in ("baseline:authorization", "baseline:contract", "baseline:prime_validation"):
        facts = json.loads(canonical_a19_baseline_case(case)["request"]["context"])["facts"]
        owned = facts["owned_registry_contract"]
        assert owned["agent_id"] == "a19" and owned["capability_id"] == "responsibility.a19"
        assert owned["authority"] == registered["authority"] == "advisory"
        assert owned["input_required"] == registered["input_contract"]["required"]
        assert owned["output_required"] == registered["output_contract"]["required"]
        assert owned["output_status"] == registered["output_contract"]["status"]


def test_unknown_data_does_not_invent_an_assessment_completion_blocker(monkeypatch):
    from app import agent_cert_a19_baseline as module
    task, facts = module._SCENARIOS["baseline:completion"]
    facts = copy.deepcopy(facts)
    facts["accounted_source_ids"].append("BC4")
    facts["checklist"][-1]["met"] = True
    monkeypatch.setitem(module._SCENARIOS, "baseline:completion", (task, facts))
    changed = answer("baseline:completion")
    changed.update(accounted_sources=4, unaccounted_source_ids=[], unmet_requirements=[],
        bounded_assessment_complete=True, provided_completion_claim_supported=True)
    assert review_a19_baseline_output("baseline:completion", wire(changed)) == (True, ())
    assert changed["remaining_uncertainty"] == ["DEPENDENCY_MAP_MISSING"]
    assert changed["actual_worker_completion_observed"] is False


@pytest.mark.parametrize("case,key,value", [
    ("baseline:authorization", "actual_authority_granted", True),
    ("baseline:authorization", "not_authorized_request_ids", []),
    ("baseline:objective", "rate_change_basis_points", -200),
    ("baseline:instruction", "window_gate_met", True),
    ("baseline:instruction", "applied_limit_basis_points", 9999),
    ("baseline:context", "continuous_health", "PASS"),
    ("baseline:contract", "status_allowed", True),
    ("baseline:error", "replacement_health", "PASS"),
    ("baseline:timeout", "stated_budget_exhausted", False),
    ("baseline:timeout", "actual_transport_timeout_observed", True),
    ("baseline:evidence", "claim_supported", [True, True, True]),
    ("baseline:evidence", "reduction_percent", 300),
    ("baseline:result", "maximum_consecutive_failures", 2),
    ("baseline:completion", "bounded_assessment_complete", True),
    ("baseline:completion", "actual_worker_completion_observed", True),
    ("baseline:prime_validation", "capability_identity_matches", True),
    ("baseline:prime_validation", "prime_validation_actually_performed", True),
])
def test_concrete_substantive_and_false_event_shortcuts_rejected(case, key, value):
    changed = answer(case)
    changed[key] = value
    assert review_a19_baseline_output(case, wire(changed)) == (False, (key,))


@pytest.mark.parametrize("case", (None, True, 1, [], {}, "baseline:identity", "baseline:initialization",
    "general:recovery", "authority:complete", "tool_recovery:tool_failure", "clean_room_audit:complete"))
def test_unsupported_other_owned_event_dimensions_do_not_acquire_baseline_quality_oracle(case):
    with pytest.raises(ValueError, match="A19_BASELINE_CASE_UNSUPPORTED"):
        canonical_a19_baseline_case(case)
    assert review_a19_baseline_output(case, "{}") == (False, ("case_oracle_unsupported",))


@pytest.mark.parametrize("response", (None, True, 3, {}, [], b"{}", "", " "*(MAX_RESPONSE_BYTES+1), "\ud800"),
                         ids=("none", "bool", "int", "dict", "list", "bytes", "empty", "oversize", "surrogate"))
def test_text_and_byte_bounds_fail_closed_without_raw_error(response):
    assert review_a19_baseline_output("baseline:objective", response)[0] is False
