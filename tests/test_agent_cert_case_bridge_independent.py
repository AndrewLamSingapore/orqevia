"""Independent public fixtures/ephemeral keys; no actual operator or signing."""
from copy import deepcopy
import json

import pytest

from app.agent_cert_a19_cases import ORACLE_ID, SUPPORTED_CASES
from app.agent_certification import LOGIC_SIGNALS
from app.agent_cert_transport import PROVIDER_ID
from scripts.agent_cert_reviewed_signing import CertificationReviewError, _review
from scripts import sign_admitted_agent_cases as loader
from tests.test_agent_cert_case_bridge import (
    QualityOperator, rebind_artifact, signing_fixture,
)
from tests.test_agent_cert_reviewed_signing import (
    EXECUTION_SOURCE, IMAGE, REVIEWER_CODE, NOW, mocked_reviewer_execution, persist, run,
)
from tests.test_sign_admitted_agent_cases import entry, manifest


NEW_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507:novita"


def refreshed_review(state, case):
    """Update an explicit mock, never invent a live reviewer artifact."""
    state["review"]["observations"]["result_sha256"] = state["execution"]["job"]["result_sha256"]
    proof = mocked_reviewer_execution(state)
    rebind_artifact(proof, case)
    state["review"]["observations"]["reviewer_execution"] = proof
    persist(state)


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_declared_pass_and_consistent_artifact_cannot_hide_failed_authority_oracle(tmp_path, case):
    from tests.test_agent_cert_reviewed_signing import sha
    state = signing_fixture(tmp_path, case)
    job = state["execution"]["job"]
    answer = json.loads(job["result"])
    answer["restart_authorized"] = True
    job["result"] = json.dumps(answer)
    job["result_sha256"] = sha(job["result"].encode())
    refreshed_review(state, case)
    with pytest.raises(CertificationReviewError, match="CASE_ORACLE_FAILED"):
        run(state)
    assert state["calls"] == []


@pytest.mark.parametrize("case", [c for c in SUPPORTED_CASES if c.startswith("logic_quality:")])
def test_one_logic_case_cannot_sign_every_signal(tmp_path, case):
    state = signing_fixture(tmp_path, case)
    state["row"]["logic_signals"] = {signal: "PASS" for signal in LOGIC_SIGNALS.values()}
    with pytest.raises(CertificationReviewError, match="LOGIC_SIGNALS_BINDING_INVALID"):
        run(state)
    assert state["calls"] == []


@pytest.mark.parametrize("field,value", [
    ("recovery_result", "PASS"), ("l7_status", "L7 PRIME SOVEREIGN CERTIFIED"),
    ("health", "HEALTHY"), ("tools_executed", True),
])
def test_quality_signature_cannot_carry_unobserved_event_uplift(tmp_path, field, value):
    state = signing_fixture(tmp_path, "adversarial:invalid_artifact")
    state["row"][field] = value
    with pytest.raises(CertificationReviewError, match="PROTECTED_BINDINGS_REQUIRED"):
        run(state)
    assert state["calls"] == []


def cloud_signing_fixture(tmp_path, case):
    state = signing_fixture(tmp_path, case)
    operator = QualityOperator(case)
    options = operator.options
    execution = state["execution"]
    execution["job"]["provider"] = PROVIDER_ID
    execution["transport"]["provider_locality"] = "CLOUD"
    execution["cloud_transport"] = {"binding": options["cloud_binding"].receipt(), "queue_route": {
        "preferred_provider": PROVIDER_ID, "model": NEW_MODEL, "allow_cloud": 1,
        "data_classification": "CLOUD_PERMITTED", "task_class": "complex_reasoning",
        "classification": "R0", "max_retries": 0, "max_cost_usd": .002,
        "prompt_sha256": "b" * 64, "input_tokens": 100, "output_tokens": 50,
        "actual_cost_usd": .000038}}
    refreshed_review(state, case)
    return state, {key: options[key] for key in
        ("cloud_binding", "cloud_policy", "expected_owner_policy_sha256")}


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_new_model_quality_signature_requires_protected_policy_and_actual_review(tmp_path, case):
    state, args = cloud_signing_fixture(tmp_path, case)
    signed = run(state, **args)
    assert len(state["calls"]) == 1  # ephemeral local test key, not Azure
    assert signed["dimension"] + ":" + signed["test_case"] == case
    assert "recovery_result" not in signed and "l7_status" not in signed
    assert state["execution"]["cloud_transport"]["binding"]["minimum_tier"] == "FLAGSHIP"
    assert state["execution"]["case_spec"]["request"]["data_classification"] == "LOCAL_ONLY"


@pytest.mark.parametrize("key", ["cloud_binding", "cloud_policy", "expected_owner_policy_sha256"])
def test_new_model_case_evidence_is_not_its_own_policy_authority(tmp_path, key):
    state, args = cloud_signing_fixture(tmp_path, "logic_quality:counterevidence")
    args[key] = None
    with pytest.raises(CertificationReviewError):
        run(state, **args)
    assert state["calls"] == []


@pytest.mark.parametrize("field,value", [
    ("preferred_provider", "hf-other"), ("model", "Qwen/Qwen3-32B:deepinfra"),
    ("task_class", "planning"), ("max_retries", 1), ("allow_cloud", True),
    ("actual_cost_usd", None), ("input_tokens", True),
])
def test_new_model_observed_route_cannot_drift_even_with_new_mock_hashes(tmp_path, field, value):
    case = "role:difficult"
    state, args = cloud_signing_fixture(tmp_path, case)
    state["execution"]["cloud_transport"]["queue_route"][field] = value
    refreshed_review(state, case)
    with pytest.raises(CertificationReviewError, match="CLOUD_QUEUE_BINDING_INVALID"):
        run(state, **args)
    assert state["calls"] == []


@pytest.mark.parametrize("case", SUPPORTED_CASES)
def test_collector_preserves_case_identity_before_unsigned_review(case):
    operator = QualityOperator(case)
    operator.job["estimated_cost_usd"] = .001  # enough for output cap + bounded prompt
    observed = operator.run()
    assert observed.summary["state"] == "UNSIGNED_CASE_EVIDENCE", observed.summary
    assert operator.calls.count("submit") == operator.calls.count("review") == 1
    execution, reviewed = json.loads(observed.execution_bytes), json.loads(observed.review_bytes)
    dimension, test_case = case.split(":")
    row = {"agent_id": "a19", "capability_id": "responsibility.a19", "verifier": "a26",
        "executor_identity": "a19", "dimension": dimension, "test_case": test_case,
        "test_result": "PASS", "source_revision": EXECUTION_SOURCE,
        "review_source_revision": EXECUTION_SOURCE, "reviewer_code_revision": REVIEWER_CODE,
        "authority_scope": "advisory", "certification_test": case.replace(":", "-"),
        "test_version": "1", "review_run_id": reviewed["review_run_id"],
        "review_test_version": ORACLE_ID, "certified_at": NOW.isoformat(),
        "last_revalidated": NOW.isoformat(), "expires_at": "2026-10-07T09:00:00+00:00"}
    if dimension == "logic_quality":
        row["logic_signals"] = {LOGIC_SIGNALS[test_case]: "PASS"}
    assert _review(row, observed.execution_bytes, observed.review_bytes,
        source_revision=EXECUTION_SOURCE, runtime_image_id=IMAGE, reviewer_code_revision=REVIEWER_CODE,
        now=NOW, **{key: operator.options[key] for key in
            ("cloud_binding", "cloud_policy", "expected_owner_policy_sha256")}) is True
    assert execution["case_spec"]["certification"] == "UNVERIFIED"


@pytest.mark.parametrize("bad", [.0004, True, None, -1, .0021])
def test_collector_no_weakening_for_missing_or_insufficient_bound_reservation(bad):
    operator = QualityOperator("role:difficult")
    operator.job["estimated_cost_usd"] = bad
    observed = operator.run()
    assert observed.summary["state"] == "REJECTED"
    assert observed.execution_bytes is not None
    assert operator.calls.count("submit") == 1 and operator.calls.count("review") == 0
    assert observed.summary["signature"] == "NOT_PERFORMED"


@pytest.mark.parametrize("change", [
    {"dimension": "recovery", "test_case": "complete"},
    {"dimension": "tools", "test_case": "complete"},
    {"dimension": "clean_room_audit", "test_case": "complete"},
    {"dimension": True, "test_case": "difficult"},
    {"agent_id": "a22", "capability_id": "responsibility.a22"},
])
def test_manifest_does_not_invent_event_or_agent_population(change):
    item = entry()
    item["record"].update(change)
    with pytest.raises(ValueError):
        loader.parse(manifest([item]))


def test_manifest_case_duplication_cannot_evade_cap_by_relabeling_fields():
    item = entry()
    item["record"].update(dimension="logic_quality", test_case="false_pass")
    assert len(loader.parse(manifest([item]))) == 1
    with pytest.raises(ValueError):
        loader.parse(manifest([item, deepcopy(item)]))
