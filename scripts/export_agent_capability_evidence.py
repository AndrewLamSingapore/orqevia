"""Export deterministic, configuration-only agent capability evidence.

This is a projection of the repository registry, not a live activation probe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "config" / "agent_registry.json"
SKILL_SOURCE = ROOT / "config" / "prime_skill_registry.json"
DESTINATION = ROOT / "docs" / "evidence"


def _document(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build_documents(source: bytes, skill_source: bytes | None = None) -> dict[str, bytes]:
    registry = json.loads(source)
    skill_raw = SKILL_SOURCE.read_bytes() if skill_source is None else skill_source
    skill_registry = json.loads(skill_raw)
    if skill_registry.get("schema_version") != "1.0":
        raise ValueError("unsupported skill registry")
    skills = skill_registry.get("skills", [])
    skill_ids = {item["skill_id"] for item in skills}
    if len(skill_ids) != len(skills):
        raise ValueError("duplicate skill ID")
    agents = sorted(registry["agents"], key=lambda agent: agent["agent_id"])
    responsibility_coverage = sorted(
        registry["responsibility_coverage"], key=lambda item: item["responsibility_id"]
    )
    identities = {agent["agent_id"] for agent in agents}
    if len(agents) != 21 or len(identities) != 21:
        raise ValueError("expected 21 unique canonical agent identities")
    responsibility_ids = [item["responsibility_id"] for item in responsibility_coverage]
    if len(responsibility_ids) != len(set(responsibility_ids)):
        raise ValueError("duplicate responsibility identity")
    if any(item["owner"] not in identities for item in responsibility_coverage):
        raise ValueError("responsibility owner is not a canonical agent")

    source_ref = {
        "path": "config/agent_registry.json",
        "sha256": hashlib.sha256(source).hexdigest(),
        "registry_version": registry["registry_version"],
    }
    limitation = (
        "Registry declarations only. No live dispatch, model assignment, tool execution, "
        "runtime reachability, or production concurrency is proven by these files."
    )
    matrix = {
        "schema_version": "1.0",
        "evidence_kind": "configuration_projection",
        "source": source_ref,
        "limitation": limitation,
        "counts": {
            "registered_agents": len(agents),
            "declared_active_lifecycle": sum(a["lifecycle_status"] == "active" for a in agents),
            "runtime_activation_verified": 0,
            "responsibilities": len(responsibility_coverage),
        },
        "agents": [
            {
                "agent_id": a["agent_id"],
                "name": a["name"],
                "role": a["role"],
                "reports_to": a["reports_to"],
                "registry_status": a["status"],
                "declared_lifecycle_status": a["lifecycle_status"],
                "model_assignment": a["model"],
                "authority": a["authority"],
                "can_delegate": a["can_delegate"],
                "declared_tools": sorted(a["tool_eligibility"]),
                "declared_model_tiers": sorted(a["model_tier_eligibility"]),
                "owned_responsibilities": sorted(a["capability_requirements"]),
                "runtime_activation_verified": False,
                "live_task_execution_verified_by_this_export": False,
            }
            for a in agents
        ],
    }
    lead_ids = {lead["id"]: lead["agent_id"] for lead in registry["leads"]}
    nodes = [{"id": "prime", "kind": "orchestrator"}]
    nodes += [{"id": a["agent_id"], "kind": "agent", "name": a["name"]} for a in agents]
    nodes += [
        {"id": item["responsibility_id"], "kind": "responsibility", "description": item["description"]}
        for item in responsibility_coverage
    ]
    nodes += [{"id": item["skill_id"], "kind": "candidate_skill", "name": item["name"]}
              for item in skills]
    tool_ids = sorted({tool for agent in agents for tool in agent["tool_eligibility"]})
    nodes += [{"id": "tool:" + tool, "kind": "declared_tool_eligibility"} for tool in tool_ids]
    nodes += [{"id": "authority:" + authority, "kind": "declared_authority"}
              for authority in sorted({a["authority"] for a in agents})]
    edges = []
    for a in agents:
        parent = lead_ids.get(a["reports_to"], a["reports_to"])
        if parent != "prime" and parent not in identities:
            raise ValueError(f"unknown reporting parent: {parent}")
        edges.append({"from": a["agent_id"], "to": parent, "kind": "reports_to_declared"})
        for child in sorted(a["allowed_delegation_targets"]):
            if child not in identities:
                raise ValueError(f"unknown delegation target: {child}")
            edges.append({"from": a["agent_id"], "to": child, "kind": "may_delegate_declared"})
    for item in responsibility_coverage:
        edges.append({"from": item["owner"], "to": item["responsibility_id"], "kind": "owns_declared"})
    for agent in agents:
        for tool in agent["tool_eligibility"]:
            edges.append({"from": agent["agent_id"], "to": "tool:" + tool,
                          "kind": "tool_eligible_declared_not_runtime_proven"})
        edges.append({"from": agent["agent_id"], "to": "authority:" + agent["authority"],
                      "kind": "authority_declared"})
    for skill in skills:
        if skill["applicable_agents"] == "all_registered_agents":
            for actor in sorted(identities):
                edges.append({"from": actor, "to": skill["skill_id"],
                              "kind": "candidate_skill_route_not_competence_proof"})
        for dependency in skill["dependencies"]:
            if dependency not in skill_ids:
                raise ValueError("unknown skill dependency")
            edges.append({"from": skill["skill_id"], "to": dependency,
                          "kind": "candidate_skill_depends_on"})
        for tool in skill["required_tools"]:
            if tool not in tool_ids:
                raise ValueError("unknown skill tool")
            edges.append({"from": skill["skill_id"], "to": "tool:" + tool,
                          "kind": "skill_requires_declared_tool"})
    graph = {
        "schema_version": "1.0",
        "evidence_kind": "configuration_projection",
        "source": source_ref,
        "skill_source": {"path": "config/prime_skill_registry.json",
                         "sha256": hashlib.sha256(skill_raw).hexdigest()},
        "limitation": limitation,
        "nodes": nodes,
        "edges": sorted(edges, key=lambda e: (e["kind"], e["from"], e["to"])),
        "runtime_edges_verified": False,
    }
    profiles = {
        "schema_version": "1.0",
        "evidence_kind": "declared_input_contract_projection",
        "source": source_ref,
        "limitation": limitation,
        "shared_boundary": {
            "source_labelled_context_required": True,
            "credentials_in_context": "prohibited by registry declaration",
            "context_window_or_token_budget": "not specified by registry; no value inferred",
            "data_classification_required": True,
            "consequential_execution": "requires independent authority; registry grants none",
        },
        "profiles": [
            {
                "agent_id": a["agent_id"],
                "role": a["role"],
                "declared_receives": a["receives"],
                "required_input_fields": a["input_contract"]["required"],
                "declared_context_rule": a["input_contract"]["context"],
                "allowed_classification_labels": a["input_contract"]["data_classification"],
                "declared_capability_inputs": a["input_contract"]["capability_inputs"],
                "required_output_fields": a["output_contract"]["required"],
                "allowed_output_status": a["output_contract"]["status"],
                "model_assignment": a["model"],
                "runtime_context_handling_verified": False,
            }
            for a in agents
        ],
    }
    return {
        "PRIME_AGENT_MATRIX.json": _document(matrix),
        "PRIME_CAPABILITY_GRAPH.json": _document(graph),
        "PRIME_CONTEXT_PROFILES.json": _document(profiles),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if checked-in projections differ")
    args = parser.parse_args()
    documents = build_documents(SOURCE.read_bytes(), SKILL_SOURCE.read_bytes())
    if args.check:
        stale = [name for name, body in documents.items() if not (DESTINATION / name).exists() or (DESTINATION / name).read_bytes() != body]
        if stale:
            parser.error("stale agent evidence: " + ", ".join(stale))
    else:
        DESTINATION.mkdir(parents=True, exist_ok=True)
        for name, body in documents.items():
            (DESTINATION / name).write_bytes(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
