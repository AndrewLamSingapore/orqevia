"""Pure policy tests; these fixtures are not live agent certification evidence."""
import pytest

from app.agent_capability_route import select_agent_capability_route
from app.agent_registry import load_agent_registry


CAPABILITY = "responsibility.a17"


def cert(level="L7", trust="L7-CURRENT", health="HEALTHY"):
    return {"agent_id": "a17", "capability_id": CAPABILITY,
            "level": level, "trust_state": trust, "health": health}


def route(evidence=None, **overrides):
    signals = dict(authority_allowed=True, runtime_healthy=True,
                   tools_available=True, model_available=True)
    signals.update(overrides)
    return select_agent_capability_route(CAPABILITY, cert() if evidence is None else evidence, **signals)


def test_every_registered_capability_has_only_its_canonical_owner():
    for agent in load_agent_registry()["agents"]:
        for capability in agent["capability_requirements"]:
            evidence = {**cert(), "agent_id": agent["id"], "capability_id": capability}
            selected = select_agent_capability_route(
                capability, evidence, authority_allowed=True, runtime_healthy=True,
                tools_available=True, model_available=True)
            assert selected.agent_id == agent["id"]
            assert selected.state == "READY"
            assert selected.grants_execution_authority is False


@pytest.mark.parametrize("signal", ["authority_allowed", "runtime_healthy", "tools_available", "model_available"])
def test_independent_denial_or_missing_dependency_fails_closed(signal):
    assert route(**{signal: False}).state == "HOLD"


@pytest.mark.parametrize("signal", ["authority_allowed", "runtime_healthy", "tools_available",
                                     "model_available", "capacity_available", "allow_demonstration"])
@pytest.mark.parametrize("value", ["false", 1, None])
def test_malformed_live_signals_fail_closed(signal, value):
    result = route(**{signal: value})
    assert result.state == "HOLD"
    assert result.grants_execution_authority is False


@pytest.mark.parametrize("field", ["level", "trust_state"])
@pytest.mark.parametrize("value", [[], {}, None])
def test_malformed_certification_fields_fail_closed(field, value):
    result = route({**cert(), field: value}, allow_demonstration=True)
    assert result.state == "HOLD"
    assert result.grants_execution_authority is False


@pytest.mark.parametrize("trust", ["REVALIDATION-REQUIRED", "SUSPENDED", "FAILED", "L7-DEGRADED"])
def test_downgrade_cannot_be_bypassed_by_demonstration(trust):
    result = route(cert(trust=trust), allow_demonstration=True)
    assert result.state == "HOLD"
    assert result.grants_execution_authority is False


def test_wrong_owner_or_capability_and_unknown_projection_fail_closed():
    assert route({**cert(), "agent_id": "a18"}).state == "HOLD"
    assert route({**cert(), "capability_id": "responsibility.a18"}).state == "HOLD"
    assert select_agent_capability_route(
        CAPABILITY, None, authority_allowed=True, runtime_healthy=True,
        tools_available=True, model_available=True).state == "HOLD"


def test_l0_and_lower_level_are_opt_in_demonstration_only():
    unproven = cert("L0", "UNPROVEN", "UNKNOWN")
    assert route(unproven).state == "HOLD"
    demonstration = route(unproven, allow_demonstration=True)
    assert demonstration.state == "DEMONSTRATION_ONLY"
    assert demonstration.requires_independent_verification is True
    assert demonstration.grants_execution_authority is False
    lower = route(cert("L5", "CERTIFIED-DEGRADED", "UNKNOWN"), allow_demonstration=True)
    assert lower.state == "DEMONSTRATION_ONLY"


def test_high_level_requires_current_trust_and_health_and_capacity():
    assert route(cert("L6", "CERTIFIED-HEALTHY")).state == "READY"
    assert route(cert("L6", "L7-CURRENT")).state == "HOLD"
    assert route(cert("L7", "CERTIFIED-HEALTHY")).state == "HOLD"
    assert route(cert("L7", "UNPROVEN"), allow_demonstration=True).state == "HOLD"
    assert route(cert("L7", "L7-CURRENT", "DEGRADED")).state == "HOLD"
    assert route(cert("L7", "UNPROVEN")).state == "HOLD"
    queued = route(capacity_available=False)
    assert queued.state == "QUEUED"
    assert queued.requires_independent_verification is False


def test_unknown_capability_is_not_routed():
    with pytest.raises(Exception):
        select_agent_capability_route(
            "responsibility.invented", cert(), authority_allowed=True,
            runtime_healthy=True, tools_available=True, model_available=True)
