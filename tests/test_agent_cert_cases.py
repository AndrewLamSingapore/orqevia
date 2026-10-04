"""Challenge catalog tests are source checks, never live certification."""

import pytest

from app.agent_cert_cases import AGENT_ID, CAPABILITY_ID, case_ids, challenge
from app.agent_certification import LEVEL_DIMENSIONS, REQUIRED_CASES
from app.agent_dispatch_api import AgentRequest
from app.agent_registry import agent_record, registered_agent_ids, responsibility_owner
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


def test_normal_role_case_uses_available_mini_tier_without_downgrading_hard_cases():
    assert challenge("role:normal")["request"]["task_class"] == "planning"
    assert challenge("role:difficult")["request"]["task_class"] == "complex_reasoning"


def test_unseen_challenge_accepts_held_out_context_without_recording_a_pass():
    held_out = "SYNTHETIC source=auditor; service=unseen-queue; health=unknown"
    spec = challenge("unseen_task:complete", context=held_out)
    assert spec["request"]["context"] == held_out
    assert "worker_observed" in spec["independent_review"]
    assert spec["certification"] == "UNVERIFIED"


def test_unknown_case_fails_closed():
    with pytest.raises(ValueError, match="unknown certification case"):
        challenge("baseline:imaginary")


def test_all_permanent_agents_receive_owned_role_specific_unverified_challenges():
    for agent_id in sorted(registered_agent_ids(include_orchestrator=False)):
        record = agent_record(agent_id)
        for capability in record["capability_requirements"]:
            responsibility = next(row for row in record["responsibilities"] if row["id"] == capability)
            spec = challenge("role:normal", agent_id=agent_id, capability_id=capability)
            request = AgentRequest(**spec["request"])
            assert spec["agent_id"] == agent_id
            assert spec["capability_id"] == capability
            assert spec["certification"] == "UNVERIFIED"
            assert request.capability == capability
            assert request.data_classification == "LOCAL_ONLY"
            assert request.max_cost_usd == 0
            assert "independent_verifier" in spec["independent_review"]
            if agent_id != AGENT_ID and not (agent_id == "a20" and capability == "responsibility.a20"):
                assert responsibility["description"] in request.objective
                assert responsibility["input"] in request.objective
                assert responsibility["output"] in request.objective


def test_a20_normal_case_is_discriminating_synthetic_margin_task():
    spec = challenge("role:normal", agent_id="a20", capability_id="responsibility.a20")
    assert "gross margin" in spec["request"]["objective"]
    assert "100 units" in spec["request"]["context"]
    assert "fixed costs unknown" in spec["request"]["context"]
    assert spec["certification"] == "UNVERIFIED"


def test_challenge_rejects_aliases_unknown_ids_and_cross_owner_capabilities():
    for agent_id in ("engineering", "a03", "prime", "invented-agent"):
        with pytest.raises(ValueError, match="registered permanent ID"):
            challenge("role:normal", agent_id=agent_id)
    with pytest.raises(ValueError, match="not owned"):
        challenge("role:normal", agent_id="a17", capability_id="responsibility.a19")
    with pytest.raises(ValueError, match="not owned"):
        challenge("role:normal", agent_id="a17", capability_id="")


def test_other_role_cases_are_distinct_and_held_out_context_is_preserved():
    held_out = "SYNTHETIC source=auditor; approved design=partial"
    normal = challenge("role:normal", agent_id="a17", context=held_out)
    invalid = challenge("role:invalid_input", agent_id="a17", context=held_out)
    assert normal["request"]["context"] == invalid["request"]["context"] == held_out
    assert normal["request"]["objective"] != invalid["request"]["objective"]
    assert "Design-to-code conversion" in normal["request"]["objective"]
    assert "invalid" in invalid["request"]["objective"].lower()
