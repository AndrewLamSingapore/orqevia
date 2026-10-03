"""Skill routing is branch-only prompt guidance, not live agent competence."""
import json
import os
from unittest.mock import patch

import pytest

from app import compute_queue_api
from app.agent_registry import registered_agent_ids
from app.skill_router import SKILL_REGISTRY_PATH, SkillRegistryError, load_skill_registry, select_skill_pack
from app.tier_router import Backend, Tier
from tests.test_harness_api import HarnessApiTests


def test_all_registered_agents_resolve_one_shared_core_without_tool_grants():
    agents = registered_agent_ids(include_orchestrator=False)
    assert len(agents) == 21
    for actor in agents:
        pack = select_skill_pack(actor, "planning", Tier.MINI)
        assert pack["agent_id"] == actor
        assert pack["skill_ids"] == ["core.evidence-boundary", "core.verification-discipline"]
        assert pack["tool_grants"] == []
        assert pack["authority"] == "ADVISORY_ONLY"
        assert pack["evidence_state"] == "BRANCH_ROUTING_ONLY_NOT_AGENT_COMPETENCE"
    assert len(load_skill_registry()[1]) == 64


def test_nano_remains_minimal_and_unknown_identity_fails_closed():
    assert select_skill_pack("a17", "classification", Tier.NANO)["guidance"] == []
    with pytest.raises(Exception, match="unregistered agent identity"):
        select_skill_pack("a99", "planning", Tier.MINI)
    with pytest.raises(SkillRegistryError, match="invalid task"):
        select_skill_pack("a17", "unsupported", Tier.MINI)


def test_invalid_or_missing_registry_fails_closed(tmp_path):
    candidate = tmp_path / "skills.json"
    candidate.write_text("{invalid", encoding="utf-8")
    with patch("app.skill_router.SKILL_REGISTRY_PATH", candidate):
        load_skill_registry.cache_clear()
        with pytest.raises(SkillRegistryError, match="unavailable"):
            select_skill_pack("a17", "planning", Tier.MINI)
        candidate.unlink()
        with pytest.raises(SkillRegistryError, match="unavailable"):
            select_skill_pack("a17", "planning", Tier.MINI)
    load_skill_registry.cache_clear()


@pytest.mark.parametrize("mutation,error", [
    (lambda data: [], "unsupported skill registry"),
    (lambda data: {**data, "skills": [{**data["skills"][0], "task_classes": "planning"}]},
     "invalid task class"),
    (lambda data: {**data, "skills": [{**data["skills"][0], "dependencies": {}}]},
     "invalid skill dependency"),
    (lambda data: {**data, "skills": [
        {**data["skills"][0], "dependencies": ["core.verification-discipline"]},
        data["skills"][1], data["skills"][2]]}, "cyclic skill dependency"),
])
def test_malformed_registry_shape_and_dependency_cycle_fail_closed(tmp_path, mutation, error):
    original = json.loads(SKILL_REGISTRY_PATH.read_text(encoding="utf-8"))
    candidate = tmp_path / "skills.json"
    candidate.write_text(json.dumps(mutation(original)), encoding="utf-8")
    with patch("app.skill_router.SKILL_REGISTRY_PATH", candidate):
        load_skill_registry.cache_clear()
        with pytest.raises(SkillRegistryError, match=error):
            load_skill_registry()
    load_skill_registry.cache_clear()


class SkillDispatchTests(HarnessApiTests):
    def test_opt_in_skill_pack_reaches_actual_advisory_enqueue(self):
        os.environ["PRIME_REGISTRY_V1_ENABLED"] = "1"
        os.environ["PRIME_SKILL_PACKS_ENABLED"] = "1"
        try:
            backend = (Backend("fixture-mini", "fixture:mini", Tier.MINI, "local"),)
            with patch("app.agent_dispatch_api.local_model_backends", return_value=backend), \
                 patch.object(compute_queue_api.queue, "submit", wraps=compute_queue_api.queue.submit) as submit:
                response = self.client.post("/api/agents/dispatch", headers=self.headers, json={
                    "capability": "responsibility.a17", "objective": "Plan a bounded inspection.",
                    "task_class": "planning", "context": "A supplied observation."})
            assert response.status_code == 202, response.text
            routing = response.json()["skill_routing"]
            assert routing["skill_ids"] == ["core.evidence-boundary", "core.verification-discipline"]
            assert routing["evidence_state"] == "BRANCH_ROUTING_ONLY_NOT_AGENT_COMPETENCE"
            prompt = submit.call_args.kwargs["prompt"]
            assert "Shared advisory methods (no tool or action authority granted):" in prompt
            assert "core.evidence-boundary:" in prompt
            assert "A supplied observation." in prompt
        finally:
            os.environ.pop("PRIME_REGISTRY_V1_ENABLED", None)
            os.environ.pop("PRIME_SKILL_PACKS_ENABLED", None)
