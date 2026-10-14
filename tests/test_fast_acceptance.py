"""Fast acceptance gate for the 21 registered ORQEVIA agents.

A deliberately small, fast set of checks for routine verification. It does not
replace the full suite for qualification or certification; use it when only
agent-identity and advisory-fabric acceptance are needed.
"""
from __future__ import annotations

from app.agent_registry import registered_agent_ids
from app.hyper_inference.router import AdaptiveInferenceRouter
from app.skill_router import select_skill_pack
from app.tier_router import Tier
from app.uief import DIMENSION_IDS


def test_authoritative_registry_has_exactly_21_registered_agents():
    agents = registered_agent_ids(include_orchestrator=False)
    assert len(agents) == 21
    assert len(set(agents)) == 21


def test_every_agent_resolves_an_advisory_skill_pack_without_tool_grants():
    for agent_id in registered_agent_ids(include_orchestrator=False):
        pack = select_skill_pack(agent_id, "planning", Tier.MINI)
        assert pack["agent_id"] == agent_id
        assert pack["authority"] == "ADVISORY_ONLY"
        assert pack["tool_grants"] == []
        assert pack["advisory_fabric"]["authority"] == "ADVISORY_ONLY"


def test_every_agent_routes_a_traceable_advisory_result():
    router = AdaptiveInferenceRouter()
    for agent_id in registered_agent_ids(include_orchestrator=False):
        result = router.route(
            objective="Validate the governed advisory reasoning path",
            agent_id=agent_id,
            agent_permissions={"reason.advisory"},
        )
        assert result.trace_id
        assert result.channels_selected
        assert result.executed_external_action is False
        assert result.escalation["channel"] in {"none", "owner_or_independent_review"}


def test_uief_taxonomy_has_15_dimensions():
    assert len(DIMENSION_IDS) == 15
