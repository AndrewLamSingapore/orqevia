"""Challenge catalog tests are source checks, never live certification."""

import pytest

from app.agent_cert_cases import AGENT_ID, CAPABILITY_ID, case_ids, challenge
from app.agent_certification import LEVEL_DIMENSIONS, REQUIRED_CASES
from app.agent_dispatch_api import AgentRequest
from app.agent_registry import agent_record, responsibility_owner
from app.runtime_status import OBJECTIVE as RUNTIME_STATUS_OBJECTIVE


def test_a19_catalog_exactly_covers_l7_matrix_with_dispatchable_bounded_requests():
    expected = {f"{dimension}:{case}" for dimension in LEVEL_DIMENSIONS[-1]
                for case in REQUIRED_CASES.get(dimension, ("complete",))}
    assert set(case_ids()) == expected
    assert len(case_ids()) == len(expected)
    assert responsibility_owner(CAPABILITY_ID) == AGENT_ID
    assert CAPABILITY_ID in agent_record(AGENT_ID)["capability_requirements"]
    objectives = set()
    for case_id in case_ids():
        spec = challenge(case_id)
        request = AgentRequest(**spec["request"])
        assert spec["case"] == case_id
        assert spec["certification"] == "UNVERIFIED"
        assert request.capability == CAPABILITY_ID
        assert request.data_classification == "LOCAL_ONLY"
        assert request.max_cost_usd == 0
        assert "independent_verifier" in spec["independent_review"]
        assert request.objective not in objectives
        objectives.add(request.objective)


def test_identity_uses_exact_deterministic_a19_route_without_claiming_model_work():
    spec = challenge("baseline:identity")
    assert spec["request"]["objective"] == RUNTIME_STATUS_OBJECTIVE
    assert spec["request"]["context"] == ""
    assert "validated_runtime_artifact" in spec["independent_review"]
    assert "worker_observed" not in spec["independent_review"]


def test_unseen_challenge_accepts_held_out_context_without_recording_a_pass():
    held_out = "SYNTHETIC source=auditor; service=unseen-queue; health=unknown"
    spec = challenge("unseen_task:complete", context=held_out)
    assert spec["request"]["context"] == held_out
    assert "worker_observed" in spec["independent_review"]
    assert spec["certification"] == "UNVERIFIED"


def test_unknown_case_fails_closed():
    with pytest.raises(ValueError, match="unknown certification case"):
        challenge("baseline:imaginary")
