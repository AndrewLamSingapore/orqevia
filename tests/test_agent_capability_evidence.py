import hashlib
import json

import pytest

from scripts.export_agent_capability_evidence import SKILL_SOURCE, SOURCE, build_documents


def test_agent_capability_projection_is_complete_and_explicitly_unverified():
    source = SOURCE.read_bytes()
    documents = {name: json.loads(body) for name, body in build_documents(source).items()}
    matrix = documents["PRIME_AGENT_MATRIX.json"]
    graph = documents["PRIME_CAPABILITY_GRAPH.json"]
    profiles = documents["PRIME_CONTEXT_PROFILES.json"]
    assert set(documents) == {
        "PRIME_AGENT_MATRIX.json",
        "PRIME_CAPABILITY_GRAPH.json",
        "PRIME_CONTEXT_PROFILES.json",
    }
    assert all(document["source"]["sha256"] == hashlib.sha256(source).hexdigest() for document in documents.values())
    assert matrix["counts"] == {
        "registered_agents": 21,
        "declared_active_lifecycle": 21,
        "runtime_activation_verified": 0,
        "responsibilities": 29,
    }
    assert len({agent["agent_id"] for agent in matrix["agents"]}) == 21
    assert all(agent["model_assignment"] == "unassigned" for agent in matrix["agents"])
    assert all(not agent["runtime_activation_verified"] for agent in matrix["agents"])
    assert len([edge for edge in graph["edges"] if edge["kind"] == "owns_declared"]) == 29
    assert len([edge for edge in graph["edges"] if edge["kind"] == "reports_to_declared"]) == 21
    assert graph["skill_source"]["sha256"] == hashlib.sha256(SKILL_SOURCE.read_bytes()).hexdigest()
    assert len([node for node in graph["nodes"] if node["kind"] == "candidate_skill"]) == 3
    assert len([edge for edge in graph["edges"] if edge["kind"] == "candidate_skill_route_not_competence_proof"]) == 63
    assert graph["runtime_edges_verified"] is False
    assert not any(edge["kind"] == "skill_grants_tool" for edge in graph["edges"])
    assert len(profiles["profiles"]) == 21
    assert all(not profile["runtime_context_handling_verified"] for profile in profiles["profiles"])
    assert all("data_classification" in profile["required_input_fields"] for profile in profiles["profiles"])


def test_agent_capability_projection_does_not_accept_unknown_owners():
    registry = json.loads(SOURCE.read_bytes())
    registry["responsibility_coverage"][0]["owner"] = "invented-agent"
    with pytest.raises(ValueError, match="owner"):
        build_documents(json.dumps(registry).encode())


def test_agent_capability_projection_is_deterministic_and_current():
    source = SOURCE.read_bytes()
    first = build_documents(source)
    assert first == build_documents(source)
    for name, body in first.items():
        assert (SOURCE.parents[1] / "docs" / "evidence" / name).read_bytes() == body
