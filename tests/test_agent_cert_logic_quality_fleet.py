"""Independent fixture arithmetic and rejection cases; no live L7 assertions."""
import copy
import hashlib
import json

import pytest

from app.agent_cert_logic_quality_fleet import (
    MAX_RESPONSE_BYTES, ORACLE_ID, SUPPORTED_CASES, canonical_logic_quality_case,
    review_logic_quality_output,
)
from app.agent_registry import load_agent_registry
from app.agent_cert_cases import challenge

PAIRS = [(row["id"], capability) for row in load_agent_registry()["agents"]
         if row["id"] != "a19" for capability in row["capability_requirements"]]
RESULTS = {
    "logic_quality:unsupported_assumption": {
        "evidence_refs": ["U1"], "recorded_completions": 24, "due_tasks": 30,
        "on_time_completions": None, "on_time_rate": "UNKNOWN", "claim_supported": False,
        "missing_evidence": ["completion_timestamps"]},
    "logic_quality:contradiction": {
        "evidence_refs": ["C1", "C2"], "retention_values": [7, 14],
        "contradiction_present": True, "selected_source": None,
        "effective_retention_days": None, "conflict_status": "UNRESOLVED",
        "source_records_preserved": True},
    "logic_quality:counterevidence": {
        "evidence_refs": ["P1", "P2"], "previous_failures": 14, "latest_failures": 18,
        "previous_rate": "1/5", "latest_rate": "1/10", "count_trend": "UP", "rate_trend": "DOWN",
        "prior_claim_supported": False, "cause_established": False},
    "logic_quality:edge_case": {
        "evidence_refs": ["E1"], "numerator": 0, "denominator": 0, "pass_rate": None,
        "input_counts_valid": True, "threshold_met": "UNKNOWN", "empty_sample_is_success": False},
    "logic_quality:false_pass": {
        "evidence_refs": ["V1"], "required_checks": 3, "passed_checks": 2, "missing_checks": 1,
        "same_subject_and_reviewer": True, "independent_review_valid": False,
        "signature_alone_establishes_qualification": False, "candidate_pass_supported": False},
    "logic_quality:fact_vs_inference": {
        "evidence_refs": ["F1"], "completion_ratio": "3/4",
        "statement_classifications": {"S1": "OBSERVED_FACT", "S2": "DERIVED_VALUE",
                                     "S3": "UNSUPPORTED_CAUSAL_INFERENCE"},
        "causal_effect_established": False},
}


def answer(case, agent="a01", capability="responsibility.a01"):
    return {"case_id": case, "agent_id": agent, "capability_id": capability,
            "actions_executed": False, "certification_awarded": False, **copy.deepcopy(RESULTS[case])}


@pytest.mark.parametrize("agent,capability", PAIRS)
@pytest.mark.parametrize("case", sorted(SUPPORTED_CASES))
def test_owned_primary_and_secondary_quality_cases(agent, capability, case):
    spec = canonical_logic_quality_case(case, agent_id=agent, capability_id=capability)
    assert spec["request"]["capability"] == capability
    assert spec["request"]["data_classification"] == "LOCAL_ONLY"
    assert spec["request"]["max_cost_usd"] == 0
    original = challenge(case, agent_id=agent, capability_id=capability)
    for field in ("classification", "minimum_tier", "priority", "task_class"):
        assert spec["request"][field] == original["request"][field]
    assert spec["certification"] == "UNVERIFIED"
    assert spec["oracle_id"] == ORACLE_ID
    assert hashlib.sha256(spec["request"]["context"].encode()).hexdigest() == spec["case_input_sha256"]
    assert review_logic_quality_output(agent, capability, case, json.dumps(answer(case, agent, capability))) == (True, ())


@pytest.mark.parametrize("case,field,bad", [
    ("logic_quality:unsupported_assumption", "on_time_completions", 24),
    ("logic_quality:unsupported_assumption", "claim_supported", True),
    ("logic_quality:contradiction", "selected_source", "C2"),
    ("logic_quality:contradiction", "effective_retention_days", 14),
    ("logic_quality:counterevidence", "latest_rate", "1/5"),
    ("logic_quality:counterevidence", "rate_trend", "UP"),
    ("logic_quality:counterevidence", "cause_established", True),
    ("logic_quality:edge_case", "pass_rate", 0),
    ("logic_quality:edge_case", "pass_rate", 1),
    ("logic_quality:edge_case", "threshold_met", "PASS"),
    ("logic_quality:false_pass", "independent_review_valid", True),
    ("logic_quality:false_pass", "signature_alone_establishes_qualification", True),
    ("logic_quality:false_pass", "candidate_pass_supported", True),
    ("logic_quality:fact_vs_inference", "completion_ratio", "12/16"),
    ("logic_quality:fact_vs_inference", "causal_effect_established", True),
])
def test_incorrect_reasoning_is_rejected(case, field, bad):
    data = answer(case)
    data[field] = bad
    passed, errors = review_logic_quality_output("a01", "responsibility.a01", case, json.dumps(data))
    assert passed is False and field in errors


@pytest.mark.parametrize("case", sorted(SUPPORTED_CASES))
@pytest.mark.parametrize("field,bad", [("actions_executed", True), ("certification_awarded", True),
                                      ("agent_id", "a02"), ("capability_id", "responsibility.a02"),
                                      ("evidence_refs", ["forged-source"])])
def test_result_never_infers_action_certification_or_other_owner(case, field, bad):
    data = answer(case)
    data[field] = bad
    assert review_logic_quality_output("a01", "responsibility.a01", case, json.dumps(data))[0] is False


@pytest.mark.parametrize("agent,capability", [("a19", "responsibility.a19"),
    ("A01", "responsibility.a01"), ("a01", "responsibility.a02"),
    ("prime", "responsibility.a01"), ("a01", "unknown"), (True, "responsibility.a01")])
def test_only_exact_registered_non_a19_owned_pairs(agent, capability):
    with pytest.raises(ValueError):
        canonical_logic_quality_case("logic_quality:false_pass", agent_id=agent, capability_id=capability)
    assert review_logic_quality_output(agent, capability, "logic_quality:false_pass", "{}")[0] is False


@pytest.mark.parametrize("response", [None, {}, "", "[]", "not-json", "{\"x\":NaN}",
    "{\"x\":Infinity}", "{\"x\":1e999}", "{\"x\":1,\"x\":2}",
    "{\"x\":{\"same\":1,\"same\":2}}", "\ud800", " " * (MAX_RESPONSE_BYTES + 1)])
def test_parser_is_bounded_strict_at_every_depth(response):
    assert review_logic_quality_output("a01", "responsibility.a01", "logic_quality:false_pass", response)[0] is False


def test_python_boolean_integer_equality_does_not_hide_wrong_type():
    data = answer("logic_quality:edge_case")
    data["denominator"] = False
    assert review_logic_quality_output("a01", "responsibility.a01", data["case_id"], json.dumps(data))[1] == ("denominator",)


def test_nested_classification_wrong_answer_and_additional_field_rejected():
    data = answer("logic_quality:fact_vs_inference")
    data["statement_classifications"]["S3"] = "OBSERVED_FACT"
    assert review_logic_quality_output("a01", "responsibility.a01", data["case_id"], json.dumps(data))[1] == ("statement_classifications",)
    data = answer("logic_quality:fact_vs_inference")
    data["statement_classifications"]["S4"] = "OBSERVED_FACT"
    assert review_logic_quality_output("a01", "responsibility.a01", data["case_id"], json.dumps(data))[0] is False


def test_distinct_case_inputs_and_answer_free_context():
    specs = [canonical_logic_quality_case(case, agent_id="a01", capability_id="responsibility.a01")
             for case in sorted(SUPPORTED_CASES)]
    assert len({spec["case_input_sha256"] for spec in specs}) == 6
    for spec in specs:
        context = json.loads(spec["request"]["context"])
        assert set(context) == {"schema", "case_id", "case_version", "agent_id", "capability_id", "data_scope", "facts"}
        assert "expected" not in context and "answers" not in context
        assert context["data_scope"] == "PUBLIC_SYNTHETIC_LOGIC_ONLY"
    spec = canonical_logic_quality_case("logic_quality:counterevidence", agent_id="a01", capability_id="responsibility.a01")
    assert '"latest_rate":"1/10"' not in spec["request"]["objective"]
    assert '"previous_rate":"1/5"' not in spec["request"]["objective"]


def test_mutating_a_returned_case_does_not_redefine_the_oracle():
    spec = canonical_logic_quality_case("logic_quality:counterevidence", agent_id="a01", capability_id="responsibility.a01")
    spec["request"]["context"] = "forged input"
    spec["independent_review"] = ()
    new = canonical_logic_quality_case("logic_quality:counterevidence", agent_id="a01", capability_id="responsibility.a01")
    assert new["request"]["context"] != "forged input"
    assert ORACLE_ID in new["independent_review"]
    assert len(PAIRS) == 28
