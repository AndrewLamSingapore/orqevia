"""Declared synthetic metadata proves review checks, not actual domain events."""
import copy
import json

import pytest

from app.agent_cert_a19_cases import SUPPORTED_CASES
from app.agent_cert_review_tool import RoleReviewError
from app.agent_cert_role_review import canonical_case_spec
from app.agent_cert_transport import (
    POLICY_SCHEMA, PROVIDER_ID, SUPPORTED_MODELS, bind_cloud_case,
    case_transport_identity, transport_digest,
)
from app.compute_catalog import task_tier
from app.tier_router import Tier, required_tier
from tests.test_agent_cert_a19_cases import ANSWERS
from tests.test_agent_cert_review_tool import SOURCE, canonical, fixture, repin, run, sha


def case_fixture(case, model=None):
    payload = fixture()
    execution = payload["execution"]
    execution["dimension"], execution["test_case"] = case.split(":")
    execution["case_spec"] = canonical_case_spec("a19", "responsibility.a19", case)
    result = json.dumps({"case_id": case, "restart_authorized": False,
                         "actions_executed": False, **copy.deepcopy(ANSWERS[case])})
    execution["job"].update(result=result, result_sha256=sha(result.encode()))
    if model is not None:
        spec = execution["case_spec"]
        request = spec["request"]
        tier = max(Tier[request["minimum_tier"]], task_tier(request["objective"], request["task_class"]),
                   required_tier(request["objective"], request["context"]))
        policy = {"schema": POLICY_SCHEMA, "policy_version": "owner-test.v1",
                  "owner_authorization_ref": "owner.synthetic-test", "source_revision": SOURCE,
                  **case_transport_identity(spec), "data_classification": "CLOUD_PERMITTED",
                  "public_synthetic": True, "provider_id": PROVIDER_ID, "provider_kind": "huggingface",
                  "model": model, "minimum_tier": tier.name, "max_cost_usd": .002,
                  "context_tokens": 4096, "output_tokens": 1024, "timeout_seconds": 35,
                  "max_retries": 0, "concurrency_limit": 1}
        bound = bind_cloud_case(spec, policy, expected_source_revision=SOURCE,
                                expected_policy_sha256=transport_digest(policy))
        execution["job"]["provider"] = PROVIDER_ID
        execution["transport"]["provider_locality"] = "CLOUD"
        execution["cloud_transport"] = {"binding": bound.receipt(), "queue_route": {
            "preferred_provider": PROVIDER_ID, "model": model, "allow_cloud": 1,
            "data_classification": "CLOUD_PERMITTED", "task_class": request["task_class"],
            "classification": "R0", "max_retries": 0, "max_cost_usd": .002,
            "prompt_sha256": "a" * 64, "input_tokens": 201, "output_tokens": 127,
            "actual_cost_usd": .0001}}
    repin(payload)
    return payload


@pytest.mark.parametrize("case", SUPPORTED_CASES)
@pytest.mark.parametrize("model", [None, *sorted(SUPPORTED_MODELS)])
def test_specific_quality_cases_retain_bindings_and_no_event_or_certification_claim(case, model):
    payload = case_fixture(case, model)
    result = run(payload)
    assert result["dimension"] + ":" + result["test_case"] == case
    assert result["oracle_id"] == "a19-substantive-quality-oracle.v1"
    assert result["test_result"] == "PASS" and result["review_errors"] == ()
    assert result["case_spec_sha256"] == sha(canonical(payload["execution"]["case_spec"]))
    assert result["execution_evidence_sha256"] == payload["expected_execution_sha256"]
    assert result["result_sha256"] == payload["execution"]["job"]["result_sha256"]
    assert result["model_calls"] == 0 and result["execution_model"] == "DETERMINISTIC"
    assert result["subject_execution_verification"] == "DOMAIN_JOIN_REQUIRED"
    assert result["certification"] == "UNVERIFIED" and "result" not in result
    if model:
        assert payload["execution"]["cloud_transport"]["binding"]["minimum_tier"] == "FLAGSHIP"
        assert payload["execution"]["cloud_transport"]["queue_route"]["task_class"] == "complex_reasoning"


@pytest.mark.parametrize("case", SUPPORTED_CASES)
@pytest.mark.parametrize("field", ["restart_authorized", "actions_executed"])
def test_quality_cases_do_not_accept_claimed_authority_or_event_execution(case, field):
    payload = case_fixture(case)
    job = payload["execution"]["job"]
    answer = json.loads(job["result"])
    answer[field] = True
    job["result"] = json.dumps(answer)
    job["result_sha256"] = sha(job["result"].encode())
    repin(payload)
    result = run(payload)
    assert result["test_result"] == "FAIL" and field in result["review_errors"]
    assert result["certification"] == "UNVERIFIED"


@pytest.mark.parametrize("path,value", [
    (("dimension",), "recovery"), (("test_case",), "normal"),
    (("agent_id",), "a20"), (("capability_id",), "responsibility.a20"),
    (("source_revision",), "b" * 40), (("runtime_image_id",), "sha256:" + "f" * 64),
    (("case_spec", "case_input_sha256"), "0" * 64),
    (("case_spec", "oracle_id"), "forged-pass.v1"),
    (("case_spec", "request", "data_classification"), "CLOUD_PERMITTED"),
    (("case_spec", "request", "context"), '{"state":"PASS"}'),
    (("job", "status"), "running"), (("job", "result_sha256"), "0" * 64),
    (("transport", "authentication"), "SELF_DECLARED"),
    (("transport", "runtime_source_revision"), "c" * 40),
])
def test_quality_case_rejects_forged_or_stale_execution_binding(path, value):
    payload = case_fixture("logic_quality:false_pass")
    cursor = payload["execution"]
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    repin(payload)
    with pytest.raises(RoleReviewError):
        run(payload)


@pytest.mark.parametrize("path,value", [
    (("binding", "model"), "Qwen/Qwen3-235B-A22B-Instruct-2507:auto"),
    (("queue_route", "model"), "Qwen/Qwen3-32B:deepinfra"),
    (("queue_route", "task_class"), "planning"),
    (("queue_route", "max_retries"), 1),
    (("queue_route", "allow_cloud"), True),
    (("binding", "minimum_tier"), "MINI"),
    (("binding", "oracle_id"), "group_two_exact_role_oracle/v1"),
    (("binding", "canonical_spec_sha256"), "0" * 64),
])
def test_new_model_and_higher_case_tier_are_not_free_form_cloud_authority(path, value):
    payload = case_fixture("adversarial:injection_attempt", "Qwen/Qwen3-235B-A22B-Instruct-2507:novita")
    cursor = payload["execution"]["cloud_transport"]
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    repin(payload)
    with pytest.raises(RoleReviewError):
        run(payload)


def test_undeclared_cloud_route_still_rejected_for_specific_case():
    payload = case_fixture("role:difficult")
    payload["execution"]["transport"]["provider_locality"] = "CLOUD"
    repin(payload)
    with pytest.raises(RoleReviewError, match="CLOUD_BINDING_REQUIRED"):
        run(payload)


def test_arbitrary_pass_label_is_not_a_specific_quality_oracle():
    payload = case_fixture("adversarial:false_completion")
    job = payload["execution"]["job"]
    job["result"] = '{"test_result":"PASS","certification":"L7"}'
    job["result_sha256"] = sha(job["result"].encode())
    repin(payload)
    result = run(payload)
    assert result["test_result"] == "FAIL" and result["review_errors"] == ("field_contract_mismatch",)
    assert result["certification"] == "UNVERIFIED"
