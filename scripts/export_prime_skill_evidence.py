"""Project bounded candidate skill routing without claiming live competence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "config" / "agent_registry.json"
SKILLS = ROOT / "config" / "prime_skill_registry.json"
DESTINATION = ROOT / "docs" / "evidence"


def build_documents(agent_source: bytes, skill_source: bytes) -> dict[str, bytes]:
    registry = json.loads(agent_source)
    skill_registry = json.loads(skill_source)
    agents = sorted(registry["agents"], key=lambda item: item["agent_id"])
    skills = skill_registry["skills"]
    if len(agents) != 21 or len({a["agent_id"] for a in agents}) != 21:
        raise ValueError("expected 21 canonical agents")
    if len({s["skill_id"] for s in skills}) != len(skills):
        raise ValueError("duplicate skill IDs")
    if any(s["required_tools"] or s["authority_required"] != "advisory_only"
           or s["status"] != "BRANCH_CANDIDATE" for s in skills):
        raise ValueError("candidate skills cannot grant tools or authority")
    sources = {
        "agent_registry": {"path": "config/agent_registry.json", "sha256": hashlib.sha256(agent_source).hexdigest()},
        "skill_registry": {"path": "config/prime_skill_registry.json", "sha256": hashlib.sha256(skill_source).hexdigest()},
    }
    limitation = (
        "Branch configuration and routing projection, not live agent skill competence, "
        "production deployment, tool execution, or authority proof."
    )
    matrix = {
        "schema_version": "1.0", "evidence_kind": "branch_candidate_projection",
        "sources": sources, "limitation": limitation,
        "agents": [
            {
                "agent_id": a["agent_id"], "role": a["role"],
                "declared_tools": sorted(a["tool_eligibility"]),
                "declared_authority": a["authority"],
                "candidate_shared_skills": [s["skill_id"] for s in skills],
                "route_test_scope": "shared registry selection only; no live per-agent execution proof",
                "runtime_skill_competence": "UNVERIFIED",
                "production_skill_availability": "NOT_DEPLOYED",
            }
            for a in agents
        ],
    }
    profiles = {
        "schema_version": "1.0", "evidence_kind": "declared_and_branch_candidate",
        "sources": sources, "limitation": limitation,
        "profiles": [
            {
                "agent_id": a["agent_id"], "name": a["name"], "role": a["role"],
                "responsibilities": sorted(a["capability_requirements"]),
                "declared_tools": sorted(a["tool_eligibility"]),
                "declared_model_tiers": sorted(a["model_tier_eligibility"]),
                "model_assignment": a["model"], "authority": a["authority"],
                "candidate_skill_ids": [s["skill_id"] for s in skills],
                "candidate_tool_grants": [],
                "live_execution_evidence": "UNVERIFIED",
            }
            for a in agents
        ],
    }
    manifest = {
        "schema_version": "1.0", "evidence_kind": "source_inspected_branch_candidate",
        "sources": sources, "limitation": limitation,
        "production_status": "NOT_DEPLOYED_GOLDEN_GEN2_UNCHANGED",
        "capabilities": [
            {"id": "agent_registry", "source": "config/agent_registry.json", "state": "DECLARED_21_IDENTITIES"},
            {"id": "advisory_skill_registry", "source": "config/prime_skill_registry.json", "state": "BRANCH_CANDIDATE"},
            {"id": "advisory_skill_router", "source": "app/skill_router.py", "state": "BRANCH_TESTED_NOT_PRODUCTION_VERIFIED"},
            {"id": "dispatch_prompt_integration", "source": "app/agent_dispatch_api.py", "state": "OPT_IN_BRANCH_TESTED_NOT_LIVE_21_AGENT_PROOF"},
            {"id": "tool_authority", "source": "app/spine.py", "state": "SEPARATE_FROM_SKILLS_NO_NEW_GRANTS"},
        ],
        "open_proofs": [
            "live per-agent task completion and result quality",
            "tool availability and execution per eligible role",
            "safe production trial and host stability qualification",
        ],
    }
    return {
        name: (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        for name, payload in {
            "PRIME_CAPABILITY_MANIFEST.json": manifest,
            "PRIME_SKILL_PARITY_MATRIX.json": matrix,
            "PRIME_AGENT_TECHNICAL_PROFILES.json": profiles,
        }.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    documents = build_documents(AGENTS.read_bytes(), SKILLS.read_bytes())
    if args.check:
        stale = [name for name, body in documents.items()
                 if not (DESTINATION / name).exists() or (DESTINATION / name).read_bytes() != body]
        if stale:
            parser.error("stale skill evidence: " + ", ".join(stale))
    else:
        DESTINATION.mkdir(parents=True, exist_ok=True)
        for name, body in documents.items():
            (DESTINATION / name).write_bytes(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
