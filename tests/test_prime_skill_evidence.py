import json

import pytest

from scripts.export_prime_skill_evidence import AGENTS, SKILLS, build_documents


def test_skill_evidence_covers_all_agents_without_claiming_competence():
    documents = {name: json.loads(body) for name, body in
                 build_documents(AGENTS.read_bytes(), SKILLS.read_bytes()).items()}
    assert set(documents) == {
        "PRIME_CAPABILITY_MANIFEST.json", "PRIME_SKILL_PARITY_MATRIX.json",
        "PRIME_AGENT_TECHNICAL_PROFILES.json",
    }
    matrix = documents["PRIME_SKILL_PARITY_MATRIX.json"]
    assert len(matrix["agents"]) == 21
    assert all(agent["runtime_skill_competence"] == "UNVERIFIED" for agent in matrix["agents"])
    assert all(agent["production_skill_availability"] == "NOT_DEPLOYED" for agent in matrix["agents"])
    assert all(profile["candidate_tool_grants"] == [] for profile in
               documents["PRIME_AGENT_TECHNICAL_PROFILES.json"]["profiles"])
    assert documents["PRIME_CAPABILITY_MANIFEST.json"]["production_status"] == \
        "NOT_DEPLOYED_GOLDEN_GEN2_UNCHANGED"


def test_skill_evidence_rejects_tool_grant():
    skill_registry = json.loads(SKILLS.read_bytes())
    skill_registry["skills"][0]["required_tools"] = ["action.execute"]
    with pytest.raises(ValueError, match="cannot grant"):
        build_documents(AGENTS.read_bytes(), json.dumps(skill_registry).encode())


def test_skill_evidence_is_current():
    documents = build_documents(AGENTS.read_bytes(), SKILLS.read_bytes())
    for name, body in documents.items():
        assert (AGENTS.parents[1] / "docs" / "evidence" / name).read_bytes() == body
