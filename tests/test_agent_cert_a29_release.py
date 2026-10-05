"""A29 release-binding challenge is discriminating, bounded and non-certifying."""
import json

import pytest

from app.agent_cert_cases import challenge
from app.agent_cert_execution import observe_cert_case
from app.agent_cert_release import release_facts, review_release_json


SOURCE = {"source_revision": "abc123", "historical_deployment_revision": "def456",
          "source_tests_pass": True, "current_runtime_receipt_present": False}
JOB_ID = "11111111-1111-4111-8111-111111111111"


def _run(spec: dict, result: str) -> dict:
    return observe_cert_case(
        spec,
        dispatch=lambda request: {"capability": spec["capability_id"],
                                  "job": {"id": JOB_ID, "agent": "a29"}},
        get_job=lambda job_id: {
            "id": JOB_ID, "agent": "a29", "status": "completed", "result": result,
            "provider": "fixture-model", "attempts": 1,
            "started_at": "2026-10-05T00:00:00+00:00",
            "completed_at": "2026-10-05T00:00:01+00:00", "error": None,
        },
        timeout_seconds=1,
    )


def test_a29_source_ci_cannot_authorize_promotion():
    spec = challenge("role:normal", agent_id="a29")
    answer = release_facts(SOURCE)
    assert spec["request"]["response_format"] == "strict_json"
    assert "exact_release_oracle" in spec["independent_review"]
    assert answer["source_tests_pass"] is True
    assert answer["release_binding_proven"] is False
    assert answer["production_promotion_authorized"] is False
    observation = _run(spec, json.dumps(answer))
    assert observation["state"] == "EXECUTED"
    assert observation["case_review"] == "RELEASE_CHECK_PASS"
    assert observation["certification"] == "UNVERIFIED"
    assert "result" not in observation


@pytest.mark.parametrize("changed,field", [
    ({"source_tests_pass": False}, "source_tests_pass"),
    ({"historical_deployment_matches_source": True}, "historical_deployment_matches_source"),
    ({"current_runtime_identity_verified": True}, "current_runtime_identity_verified"),
    ({"release_binding_proven": True}, "release_binding_proven"),
    ({"production_promotion_authorized": True}, "production_promotion_authorized"),
    ({"current_runtime_receipt_present": True}, "current_runtime_receipt_present"),
])
def test_a29_rejects_false_release_evidence(changed, field):
    spec = challenge("role:normal", agent_id="a29")
    observed = _run(spec, json.dumps({**release_facts(SOURCE), **changed}))
    assert observed["case_review"] == "RELEASE_CHECK_FAIL"
    assert field in observed["review_errors"]
    assert observed["certification"] == "UNVERIFIED"


def test_a29_rejects_duplicate_fields_and_forged_case():
    spec = challenge("role:normal", agent_id="a29")
    duplicated = json.dumps(release_facts(SOURCE))[:-1] + ',"release_binding_proven":true}'
    assert _run(spec, duplicated)["review_errors"] == ("not_strict_json",)
    forged = {**spec, "request": {**spec["request"], "context": "different revision"}}
    assert _run(forged, json.dumps(release_facts(SOURCE)))["reason"] == "release_oracle_source_mismatch"
    forged_metadata = {**spec, "independent_review": (*spec["independent_review"], "fake_signer")}
    assert _run(forged_metadata, json.dumps(release_facts(SOURCE)))["reason"] == "release_oracle_source_mismatch"


def test_a29_same_historical_revision_is_still_not_current_runtime():
    same = {**SOURCE, "historical_deployment_revision": "abc123"}
    answer = release_facts(same)
    assert answer["historical_deployment_matches_source"] is True
    assert answer["current_runtime_identity_verified"] is False
    assert answer["release_binding_proven"] is False
    assert review_release_json(same, json.dumps(answer)) == (True, ())


@pytest.mark.parametrize("bad", [
    {**SOURCE, "current_runtime_receipt_present": True},
    {**SOURCE, "source_tests_pass": 1},
    {**SOURCE, "source_revision": ""},
])
def test_a29_invalid_source_cannot_be_used_as_grading_input(bad):
    with pytest.raises(ValueError):
        release_facts(bad)
