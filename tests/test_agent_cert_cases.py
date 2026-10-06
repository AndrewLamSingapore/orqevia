"""Challenge catalog tests are source checks, never live certification."""

import pytest

from app.agent_cert_cases import AGENT_ID, CAPABILITY_ID, ROLE_NORMAL_FIXTURES, case_ids, challenge
from app.agent_certification import LEVEL_DIMENSIONS, REQUIRED_CASES
from app.agent_dispatch_api import AgentRequest, inference_prompt
from app.agent_registry import agent_record, registered_agent_ids, responsibility_owner
from app.runtime_status import OBJECTIVE as RUNTIME_STATUS_OBJECTIVE
from app.compute_catalog import task_tier
from app.tier_router import Backend, Tier, required_tier, select_direct_route


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


def test_a18_official_invalid_artifact_challenge_is_local_bounded_and_unverified():
    spec = challenge("adversarial:invalid_artifact", agent_id="a18")
    request = AgentRequest(**spec["request"])
    assert spec["case"] == "adversarial:invalid_artifact"
    assert spec["certification"] == "UNVERIFIED"
    assert request.data_classification == "LOCAL_ONLY"
    assert request.minimum_tier == "NANO"
    assert request.max_cost_usd == 0
    assert request.response_format == "strict_json"
    assert request.task_class == "classification"
    assert "exact_invalid_artifact_oracle" in spec["independent_review"]
    assert "control_utf8_hex=" in request.context
    assert "mutated_utf8_hex=" in request.context
    assert "declared_sha256_for_both=" in request.context
    assert "DIGEST_MISMATCH iff the observed mutated SHA-256 differs" in request.objective
    # The off-host profile allocates 2048 context units and 256 output units;
    # dispatch currently enforces the remaining 1792 as a UTF-8 byte cap.
    # Keep headroom so this official case reaches the backend, not HTTP 413.
    assert len(inference_prompt(request, Tier.NANO).encode("utf-8")) <= 1750
    tier = max(Tier[request.minimum_tier], task_tier(request.objective, request.task_class),
               required_tier(request.objective, request.context))
    assert tier == Tier.NANO
    local = Backend("ollama-fast", "synthetic-nano", Tier.NANO, "local")
    cloud = Backend("cloud-nano", "synthetic-cloud", Tier.NANO, "cloud")
    text = request.objective + "\n" + request.context
    assert select_direct_route((local, cloud), minimum_tier=tier,
                               classification=request.data_classification,
                               text=text).backend == local
    assert select_direct_route((cloud,), minimum_tier=tier,
                               classification=request.data_classification,
                               text=text).state == "UNAVAILABLE"


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
    all_capabilities = {capability for agent_id in registered_agent_ids(include_orchestrator=False)
                        for capability in agent_record(agent_id)["capability_requirements"]}
    assert set(ROLE_NORMAL_FIXTURES) == all_capabilities - {
        "responsibility.a18", "responsibility.a19", "responsibility.a20"}
    objectives, contexts = set(), set()
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
            assert request.objective not in objectives
            assert request.context not in contexts
            assert len(spec["expected_discriminants"]) >= 3
            assert all(isinstance(item, str) and item.strip() for item in spec["expected_discriminants"])
            objectives.add(request.objective)
            contexts.add(request.context)
            if agent_id != AGENT_ID and not (agent_id in {"a18", "a20"} and capability == f"responsibility.{agent_id}"):
                assert responsibility["description"] in request.objective
                assert responsibility["input"] in request.objective
                assert responsibility["output"] in request.objective


def test_a20_normal_case_is_discriminating_synthetic_margin_task():
    spec = challenge("role:normal", agent_id="a20", capability_id="responsibility.a20")
    assert "gross margin" in spec["request"]["objective"]
    assert "100 units" in spec["request"]["context"]
    assert "fixed costs unknown" in spec["request"]["context"]
    assert "40%" in " ".join(spec["expected_discriminants"])
    assert spec["certification"] == "UNVERIFIED"


def test_a04_role_case_has_exact_tie_oracle():
    spec = challenge("role:normal", agent_id="a04", capability_id="responsibility.a04")
    assert spec["request"]["response_format"] == "strict_json"
    assert "exact_weighted_oracle" in spec["independent_review"]
    assert "reliability weight 2" in spec["request"]["context"]
    assert "missing_tie_breaker" in spec["request"]["objective"]


def test_a05_role_case_has_exact_capacity_oracle():
    spec = challenge("role:normal", agent_id="a05", capability_id="responsibility.a05")
    assert spec["request"]["response_format"] == "strict_json"
    assert "exact_portfolio_oracle" in spec["independent_review"]
    assert "one slot available" in spec["request"]["context"]
    assert "both_feasible_together" in spec["request"]["objective"]


def test_a21_role_case_requires_exact_cost_and_non_profit_oracle():
    spec = challenge("role:normal", agent_id="a21", capability_id="responsibility.a21")
    assert spec["request"]["response_format"] == "strict_json"
    assert "exact_cost_oracle" in spec["independent_review"]
    assert "fixed cost 100" in spec["request"]["context"]
    assert "incremental_cost_next_unit" in spec["request"]["objective"]
    assert "profit_known" in spec["request"]["objective"]
    assert spec["certification"] == "UNVERIFIED"


def test_a01_normal_case_separates_total_value_from_efficiency():
    spec = challenge("role:normal", agent_id="a01", capability_id="responsibility.a01")
    objective = spec["request"]["objective"]
    context = spec["request"]["context"]
    criteria = " ".join(spec["expected_discriminants"])
    assert "total points and points per engineer-day separately" in objective
    assert "strict JSON object" in objective
    assert "exact_numeric_oracle" in spec["independent_review"]
    assert spec["request"]["response_format"] == "strict_json"
    assert "8 TOTAL estimated points" in context
    assert "6 TOTAL estimated points" in context
    assert "8/3 points per day is LESS than Beta's 6/2" in criteria
    assert spec["certification"] == "UNVERIFIED"


def test_a18_normal_case_explicitly_checks_test_oracle_against_requirement():
    spec = challenge("role:normal", agent_id="a18", capability_id="responsibility.a18")
    assert "expected test value from the requirement" in spec["request"]["objective"]
    assert "n >= 0" in spec["request"]["context"]
    assert "n > 0" in spec["request"]["context"]
    assert "inverted assertion" in " ".join(spec["expected_discriminants"])
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
    assert normal["expected_discriminants"] == ()


def test_normal_oracles_expose_role_specific_errors_without_auto_grading():
    examples = {
        ("a04", "responsibility.a04"): ("tie", "scores 9"),
        ("a12", "responsibility.a12"): ("rate", "10%"),
        ("a26", "responsibility.a26"): ("100% claim", "95%"),
        ("a29", "responsibility.a29"): ("runtime identity", "abc123"),
    }
    for (agent_id, capability_id), fragments in examples.items():
        spec = challenge("role:normal", agent_id=agent_id, capability_id=capability_id)
        joined = " ".join(spec["expected_discriminants"])
        assert all(fragment.lower() in joined.lower() for fragment in fragments)
        assert spec["certification"] == "UNVERIFIED"


def test_role_case_forbids_unsourced_dates_causes_and_artifacts():
    spec = challenge("role:normal", agent_id="a12", capability_id="responsibility.a12")
    objective = spec["request"]["objective"]
    assert "No prose, markdown, date, or extra fields" in objective
    assert "10 failures in 100 requests" in spec["request"]["context"]
    assert "exact_rate_oracle" in spec["independent_review"]
    assert "strict JSON object" in objective
    assert spec["request"]["response_format"] == "strict_json"
