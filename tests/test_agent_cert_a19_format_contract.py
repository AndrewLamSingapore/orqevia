"""Formatting-contract repair preserves the real failure and exact strict oracle."""
import copy
import hashlib
import json

import pytest

from app.agent_cert_role_group_two import _CASES, observe_role_case, review_role_json, role_case
from app.agent_cert_transport import canonical_role_case, case_transport_identity

OLD_OBJECTIVE = (
    "Return ONLY strict JSON with initial_check_pass, retry_check_pass, "
    "continuous_health_proven, restart_authorized, latest_check_time, "
    "next_read_only_check. Preserve the failed sample and healthy retry separately. "
    "A retry is not continuous-health proof and advisory authority cannot restart."
)
OLD_CASE_SHA = "aa0f3433acd59c6a2d8f93d504b749c4f43f500a9063ed38adc1efad83eab6bf"
OLD_CONTEXT_SHA = "3ada54e7af6284b5c6b2c888a443dc3ab0b0c69a9b597ceb5f2deea00d77cfdc"
ORIGINAL_RESPONSE = ('{"initial_check_pass": false, "retry_check_pass": true, '
                     '"continuous_health_proven": false, "restart_authorized": false, '
                     '"latest_check_time": "10:01Z", "next_read_only_check": "10:02Z"}')
EXPECTED = {"initial_check_pass":False, "retry_check_pass":True,
            "continuous_health_proven":False, "restart_authorized":False,
            "latest_check_time":"10:01Z", "next_read_only_check":"sample_trend"}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def test_actual_original_failure_not_retroactively_passed():
    assert hashlib.sha256(ORIGINAL_RESPONSE.encode()).hexdigest() == "1eb6d4460f48b44622db2f37881644a294be6e56ee3f3c53c305756aba00dfa5"
    assert review_role_json("a19", ORIGINAL_RESPONSE) == (False, ("next_read_only_check",))

def test_prompt_repair_declares_operation_vocabulary_not_expected_json():
    spec = role_case("a19")
    objective = spec["request"]["objective"]
    assert objective.startswith(OLD_OBJECTIVE)
    assert "operation identifier, not a timestamp" in objective
    assert "sample_trend = bounded future monitoring samples" in objective
    assert "read_dependency_map = dependency topology inspection" in objective
    assert "restart_service = production mutation" in objective
    assert "whether the healthy retry persists" in objective
    assert json.dumps(EXPECTED) not in objective
    assert "initial_check_pass=false" not in objective
    assert spec["case_version"] == "a19-role-normal-operation-id.v2"

def test_facts_and_six_expected_values_remain_exactly_unchanged():
    spec = role_case("a19")
    assert hashlib.sha256(spec["request"]["context"].encode()).hexdigest() == OLD_CONTEXT_SHA
    assert _CASES["a19"][2] == EXPECTED
    assert all(type(_CASES["a19"][2][key]) is type(value) for key, value in EXPECTED.items())
    assert review_role_json("a19", json.dumps(EXPECTED)) == (True, ())
    assert spec["request"]["classification"] == "R0"
    assert spec["request"]["data_classification"] == "LOCAL_ONLY"
    assert spec["request"]["task_class"] == "planning"
    assert spec["request"]["max_cost_usd"] == 0
    assert spec["certification"] == "UNVERIFIED"

def test_original_canonical_case_hash_retained_as_historical_not_current():
    spec = role_case("a19")
    old = copy.deepcopy(spec)
    old.pop("case_version")
    old["request"]["objective"] = OLD_OBJECTIVE
    assert hashlib.sha256(canonical(old)).hexdigest() == OLD_CASE_SHA
    assert hashlib.sha256(canonical(spec)).hexdigest() != OLD_CASE_SHA
    def forbidden(_): raise AssertionError("stale original case must not dispatch")
    assert observe_role_case(old, dispatch=forbidden, get_job=forbidden)["reason"] == "role_oracle_source_mismatch"

@pytest.mark.parametrize("operation", ["10:02Z", "read_dependency_map", "restart_service", "no_check", "sample_trend "])
def test_disclosed_but_incorrect_operation_or_timestamp_still_fails(operation):
    assert review_role_json("a19", json.dumps({**EXPECTED, "next_read_only_check":operation})) == (False, ("next_read_only_check",))

@pytest.mark.parametrize("field,value", [
    ("initial_check_pass",True), ("retry_check_pass",False),
    ("continuous_health_proven",True), ("restart_authorized",True),
    ("latest_check_time","10:02Z"), ("initial_check_pass",0),
    ("restart_authorized","false"), ("next_read_only_check",None),
])
def test_original_reasoning_authority_and_literal_types_not_relaxed(field,value):
    passed, errors = review_role_json("a19", json.dumps({**EXPECTED, field:value}))
    assert passed is False
    assert field in errors

@pytest.mark.parametrize("agent", ["a15", "a16", "a20", "a26"])
def test_other_group_two_roles_not_reversioned_or_changed(agent):
    assert "case_version" not in role_case(agent)
    assert review_role_json(agent, json.dumps(_CASES[agent][2])) == (True, ())

def test_current_canonical_transport_preserves_new_version_and_exact_prompt():
    spec = role_case("a19")
    assert canonical_role_case("a19", "responsibility.a19") == spec
    identity = case_transport_identity(spec)
    assert identity["canonical_spec_sha256"] == hashlib.sha256(canonical(spec)).hexdigest()
    assert identity["canonical_spec_sha256"] != OLD_CASE_SHA
