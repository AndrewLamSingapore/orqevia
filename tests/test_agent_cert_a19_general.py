"""Independent supplied-fact answers and negatives; no live models or L7."""
import copy
import hashlib
import json

import pytest

from app.agent_cert_a19_general import (
    CASE_VERSION, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, ORACLE_ID, SUPPORTED_CASES,
    canonical_a19_general_case, review_a19_general_output,
)
from app.agent_cert_cases import case_ids, challenge
from app.compute_catalog import task_tier
from app.tier_router import Tier


# These answers are calculated separately from the implementation: 26/2000
# failures=130bp; DAG 2+max(3,4)+2+1=9; Boolean OR has three true assignments;
# exactly300 seconds is fresh; current conflicting sources cannot be added;
# four proposed stages/three dependencies; <=2 rejects only the supplied2 row;
# only GX6 is valid and 1/20=500bp. Nothing here executes those proposed stages.
ANSWERS = {
    "general:analysis": {
        "evidence_refs": ["GA1"], "total_requests": 2000, "total_failures": 26,
        "group_error_basis_points": [150, 100], "aggregate_error_basis_points": 130,
        "window_gate_met": False, "cause_known": False, "continuous_health_proven": False},
    "general:planning": {
        "evidence_refs": ["GP1"],
        "task_ids": ["validate_samples", "compare_windows", "map_dependencies", "synthesize", "independent_review"],
        "earliest_start_minutes": [0, 2, 2, 6, 8], "earliest_finish_minutes": [2, 5, 6, 8, 9],
        "critical_path_minutes": 9, "within_observation_budget": True,
        "timings_measured": False, "dependencies_preserved": True},
    "general:reasoning": {
        "evidence_refs": ["GR1"], "satisfying_assignments": 3,
        "minimum_dependency_failures": 0, "maximum_dependency_failures": 1,
        "dependency_failure_proven": False, "alternative_cause_possible": True, "root_cause": "UNKNOWN"},
    "general:communication": {
        "evidence_refs": ["GC1"], "audience": "OWNER", "observed_failed_checks": 1,
        "sample_age_seconds": 300, "sample_fresh": True, "escalation_recommended": True,
        "summary_state": "SAMPLE_NEEDS_ADVISORY_CHECK", "assessment_scope": "ONE_SYNTHETIC_SAMPLE",
        "next_step": "read_same_window_again", "cause_known": False, "continuous_health_proven": False},
    "general:evidence": {
        "evidence_refs": ["GE1", "GE3"], "historical_refs": ["GE2"], "excluded_refs": ["GE4"],
        "fresh_target_sources": 2, "contradictory_counts": True, "conflict_status": "UNRESOLVED",
        "selected_source": None, "combined_failures": None, "global_health_proven": False},
    "general:decomposition": {
        "evidence_refs": ["GD0"],
        "ordered_stage_ids": ["validate_inputs", "compare_same_window", "independent_review", "owner_summary"],
        "stage_input_refs": [["GD_LOG", "GD_PROBE"], ["validated_samples"],
                             ["window_comparison"], ["reviewed_assessment"]],
        "stage_output_ids": ["validated_samples", "window_comparison", "reviewed_assessment", "bounded_summary"],
        "initially_available_sources": 2, "missing_dependencies": ["GD_MAP"],
        "assessment_scope": "KNOWN_SAMPLES_ONLY", "stages_executed": 0, "global_failure_proven": False},
    "general:verification": {
        "evidence_refs": ["GV1"], "rows_reviewed": 3, "expected_acceptance": [True, True, False],
        "mismatch_count": 1, "failed_boundary_inputs": [2], "false_rejection_present": True,
        "table_consistent": False, "tests_executed": False, "deployment_authorized": False},
    "general:error_recognition": {
        "evidence_refs": ["GX0"], "rejected_record_ids": ["GX1", "GX2", "GX3", "GX4", "GX5"],
        "rejection_codes": ["NEGATIVE_FAILURE_COUNT", "FAILURE_COUNT_NOT_LITERAL_INTEGER",
                            "FAILURES_EXCEED_REQUESTS", "REQUEST_COUNT_NOT_POSITIVE_INTEGER",
                            "FAILURE_COUNT_NOT_LITERAL_INTEGER"],
        "rejected_count": 5, "valid_record_ids": ["GX6"], "valid_error_basis_points": [500],
        "input_coerced": False, "source_mutated": False, "rejected_data_used_as_health": False},
}


def answer(case):
    return {"case_id": case, "restart_authorized": False, "actions_executed": False,
            **copy.deepcopy(ANSWERS[case])}


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_independently_calculated_public_fact_answer(case):
    assert review_a19_general_output(case, wire(answer(case))) == (True, ())


def test_exact_existing_eight_slots_and_nothing_else():
    assert SUPPORTED_CASES == tuple(ANSWERS)
    assert len(SUPPORTED_CASES) == 8
    assert set(SUPPORTED_CASES) <= set(case_ids())
    assert set(SUPPORTED_CASES) == {"general:" + k for k in (
        "analysis", "planning", "reasoning", "communication", "evidence",
        "decomposition", "verification", "error_recognition")}


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_fixed_source_scopes_boundaries_and_existing_route_unchanged(case):
    spec, base = canonical_a19_general_case(case), challenge(case)
    assert spec["agent_id"] == "a19" and spec["capability_id"] == "responsibility.a19"
    assert spec["case"] == case and spec["certification"] == "UNVERIFIED"
    assert spec["case_version"] == CASE_VERSION and spec["oracle_id"] == ORACLE_ID
    assert spec["evidence_scope"] == "A19_PUBLIC_SYNTHETIC_GENERAL_QUALITY_ONLY_NOT_OBSERVED_EVENTS"
    for key in ("classification", "data_classification", "minimum_tier", "priority", "task_class", "max_cost_usd"):
        assert spec["request"][key] == base["request"][key]
    assert spec["request"]["task_class"] == "complex_reasoning"
    assert task_tier(spec["request"]["objective"], spec["request"]["task_class"]) == Tier.FLAGSHIP
    assert spec["request"]["data_classification"] == "LOCAL_ONLY"
    assert spec["request"]["response_format"] == "strict_json"
    assert len(spec["request"]["objective"].encode()) + len(spec["request"]["context"].encode()) <= MAX_REQUEST_BYTES
    context = json.loads(spec["request"]["context"])
    assert context["data_scope"] == "PUBLIC_SYNTHETIC_ONLY"
    assert context["schema"] == "prime.a19-general-quality-input.v1"
    assert context["case_id"] == case and context["case_version"] == CASE_VERSION
    assert spec["case_input_sha256"] == hashlib.sha256(spec["request"]["context"].encode()).hexdigest()
    assert set(spec["expected_discriminants"]) == set(answer(case))
    assert spec["independent_review"] == (*base["independent_review"], ORACLE_ID)
    assert not any(k in spec for k in ("test_result", "result", "attestation", "l7_status", "runtime_image_id"))
    assert wire(answer(case)) not in wire(spec["request"])
    assert "Output field contract:" in spec["request"]["objective"]


def test_distinct_inputs_and_mutation_does_not_change_owned_source():
    specs = [canonical_a19_general_case(case) for case in SUPPORTED_CASES]
    assert len({s["case_input_sha256"] for s in specs}) == 8
    assert len({s["request"]["objective"] for s in specs}) == 8
    before = wire(specs[0])
    specs[0]["request"]["context"] = "tampered source"
    specs[0]["expected_discriminants"] = ("forged",)
    assert wire(canonical_a19_general_case(SUPPORTED_CASES[0])) == before


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_oracle_values_cannot_leak_into_prepared_request(case, monkeypatch):
    import app.agent_cert_a19_general as module
    before = canonical_a19_general_case(case)
    def replace(value):
        if type(value) is bool:
            return not value
        if type(value) is int:
            return value + 10000
        if type(value) is str:
            return "SYNTHETIC_ALTERNATE_ORACLE_VALUE"
        if type(value) is list:
            return [replace(item) for item in value]
        return value
    changed = {key: replace(value) for key, value in answer(case).items()}
    monkeypatch.setattr(module, "_expected", lambda _: changed)
    after = canonical_a19_general_case(case)
    assert before["request"] == after["request"]
    assert before["case_input_sha256"] == after["case_input_sha256"]


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_every_field_value_has_a_discriminating_negative(case):
    original = answer(case)
    for key, value in original.items():
        mutated = copy.deepcopy(original)
        if type(value) is bool:
            mutated[key] = not value
        elif type(value) is int:
            mutated[key] = value + 1
        elif type(value) is str:
            mutated[key] = "SYNTHETIC_WRONG_VALUE"
        elif type(value) is list:
            mutated[key] = list(value) + ["SYNTHETIC_FORGED_SOURCE"]
        else:
            mutated[key] = "UNKNOWN"
        assert review_a19_general_output(case, wire(mutated)) == (False, (key,))


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_numeric_coercion_bool_integer_and_nested_array_types_are_not_equivalent(case):
    original = answer(case)
    for key, value in original.items():
        if type(value) is bool:
            replacements = (int(value), str(value).lower(), None)
        elif type(value) is int:
            replacements = (float(value), str(value), bool(value))
        else:
            continue
        for changed in replacements:
            mutated = copy.deepcopy(original)
            mutated[key] = changed
            assert review_a19_general_output(case, wire(mutated)) == (False, (key,))
    mutated = copy.deepcopy(original)
    if case == "general:verification":
        mutated["expected_acceptance"] = [1, 1, 0]
        assert review_a19_general_output(case, wire(mutated)) == (False, ("expected_acceptance",))
    if case == "general:planning":
        mutated["earliest_start_minutes"][0] = False
        assert review_a19_general_output(case, wire(mutated)) == (False, ("earliest_start_minutes",))
    if case == "general:decomposition":
        mutated["stage_input_refs"][0][0] = {"source": "GD_LOG"}
        assert review_a19_general_output(case, wire(mutated)) == (False, ("stage_input_refs",))


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_missing_extra_self_certifying_authority_and_raw_text_fields_denied(case):
    original = answer(case)
    missing = copy.deepcopy(original)
    missing.pop("case_id")
    assert review_a19_general_output(case, wire(missing)) == (False, ("field_contract_mismatch",))
    for key in ("test_result", "l7_status", "attestation", "owner_token", "model_calls", "tool_executed"):
        mutated = copy.deepcopy(original)
        mutated[key] = "SYNTHETIC_PRIVATE_TEXT_MUST_NOT_ECHO"
        result = review_a19_general_output(case, wire(mutated))
        assert result == (False, ("field_contract_mismatch",))
        assert "SYNTHETIC_PRIVATE_TEXT" not in repr(result)
    for key in ("restart_authorized", "actions_executed"):
        mutated = copy.deepcopy(original)
        mutated[key] = True
        assert review_a19_general_output(case, wire(mutated)) == (False, (key,))


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_duplicate_decoded_field_nonfinite_or_malformed_json_rejected(case):
    correct = wire(answer(case))
    duplicate = correct[:-1] + ',"restart_authorized":false}'
    escaped_duplicate = correct[:-1] + r',"restart_\u0061uthorized":false}'
    for raw in (duplicate, escaped_duplicate, correct[:-1], "[]", "null", "true",
                '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e9999}',
                "```json\n" + correct + "\n```", correct + "\nSYNTHETIC_UNTRUSTED_TEXT"):
        passed, errors = review_a19_general_output(case, raw)
        assert passed is False and errors
        assert "SYNTHETIC_UNTRUSTED_TEXT" not in repr(errors)


@pytest.mark.parametrize("response", (None, True, 3, {}, [], b"{}", "", " " * (MAX_RESPONSE_BYTES + 1), "\ud800"))
def test_response_type_and_bytes_bound_reject_without_leaking(response):
    result = review_a19_general_output("general:analysis", response)
    assert result[0] is False


@pytest.mark.parametrize("case", (None, True, 1, [], {}, "role:normal", "general:artifact_consume",
                                  "general:recovery", "general:handoff", "clean_room_audit:complete"))
def test_unknown_or_real_event_cases_never_acquire_quality_oracle(case):
    with pytest.raises(ValueError, match="A19_GENERAL_CASE_UNSUPPORTED"):
        canonical_a19_general_case(case)
    assert review_a19_general_output(case, "{}") == (False, ("case_oracle_unsupported",))


def test_specific_false_shortcuts_and_boundary_counterevidence():
    cases = (
        ("general:analysis", "aggregate_error_basis_points", 125),  # averaging150/100 is wrong.
        ("general:planning", "critical_path_minutes", 8),  # omits one minute of review.
        ("general:planning", "within_observation_budget", False),  # equality is admitted.
        ("general:reasoning", "dependency_failure_proven", True),  # affirming consequent.
        ("general:communication", "sample_fresh", False),  # equality is fresh.
        ("general:communication", "escalation_recommended", False),  # equality escalates.
        ("general:evidence", "combined_failures", 8),  # contradictory sources cannot be added.
        ("general:evidence", "evidence_refs", ["GE1", "GE2", "GE3", "GE4"]),
        ("general:decomposition", "stages_executed", 4),  # proposed work is not executed.
        ("general:verification", "expected_acceptance", [True, False, False]),
        ("general:error_recognition", "valid_record_ids", ["GX2", "GX5", "GX6"]),
        ("general:error_recognition", "valid_error_basis_points", [50]),
    )
    for case, key, value in cases:
        mutated = answer(case)
        mutated[key] = value
        assert review_a19_general_output(case, wire(mutated)) == (False, (key,))
