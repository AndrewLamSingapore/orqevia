"""Bounded advisory skill selection; never grants tools or execution authority.

The registry is immutable configuration in this branch. This router deliberately
does not load arbitrary code from registry strings or expand an agent's declared
tool eligibility. Runtime competence still requires separate execution proof.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .agent_registry import agent_record, canonical_agent_id, registered_agent_ids
from .tier_router import Tier


SKILL_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "prime_skill_registry.json"
ALLOWED_TASK_CLASSES = frozenset({
    "auto", "classification", "conversation", "research", "planning", "writing",
    "coding", "architecture", "complex_reasoning",
})


class SkillRegistryError(ValueError):
    pass


def load_skill_registry() -> tuple[dict, str]:
    # The registry is small. Read it for each selection so the returned digest
    # always identifies the guidance actually loaded, even after a file update.
    try:
        raw = SKILL_REGISTRY_PATH.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillRegistryError("advisory skill registry unavailable") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if (not isinstance(data, dict) or data.get("schema_version") != "1.0"
            or not isinstance(data.get("skills"), list)):
        raise SkillRegistryError("unsupported skill registry")
    ids: set[str] = set()
    for item in data["skills"]:
        required = {
            "skill_id", "name", "purpose", "inputs", "outputs", "required_tools",
            "required_context", "authority_required", "dependencies", "failure_modes",
            "verification_method", "applicable_agents", "task_classes",
            "implementation_kind", "instruction", "version", "status",
        }
        if not isinstance(item, dict) or not required <= item.keys():
            raise SkillRegistryError("incomplete skill definition")
        skill_id = item["skill_id"]
        if not isinstance(skill_id, str) or not skill_id or skill_id in ids:
            raise SkillRegistryError("duplicate or invalid skill ID")
        ids.add(skill_id)
        if (item["implementation_kind"] != "prompt_guidance"
                or item["authority_required"] != "advisory_only"
                or item["required_tools"] != []
                or item["status"] != "BRANCH_CANDIDATE"):
            raise SkillRegistryError("candidate registry cannot grant tools or authority")
        if (item["applicable_agents"] != "all_registered_agents"
                or not isinstance(item["instruction"], str)
                or not 1 <= len(item["instruction"]) <= 240):
            raise SkillRegistryError("invalid bounded guidance")
        if (not isinstance(item["task_classes"], list)
                or not item["task_classes"]
                or any(not isinstance(task_class, str) for task_class in item["task_classes"])
                or not set(item["task_classes"]) <= ALLOWED_TASK_CLASSES):
            raise SkillRegistryError("invalid task class")
        if (not isinstance(item["dependencies"], list)
                or any(not isinstance(dependency, str) for dependency in item["dependencies"])):
            raise SkillRegistryError("invalid skill dependency")
    for item in data["skills"]:
        if not set(item["dependencies"]) <= ids or item["skill_id"] in item["dependencies"]:
            raise SkillRegistryError("unknown or self-referential skill dependency")
    by_id = {item["skill_id"]: item for item in data["skills"]}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(skill_id: str) -> None:
        if skill_id in visiting:
            raise SkillRegistryError("cyclic skill dependency")
        if skill_id in visited:
            return
        visiting.add(skill_id)
        for dependency in by_id[skill_id]["dependencies"]:
            visit(dependency)
        visiting.remove(skill_id)
        visited.add(skill_id)

    for skill_id in by_id:
        visit(skill_id)
    return data, digest


def select_skill_pack(agent_id: str, task_class: str, tier: Tier) -> dict:
    """Resolve compact shared guidance for a canonical agent, without tool rights."""
    actor = canonical_agent_id(agent_id)
    if actor not in registered_agent_ids(include_orchestrator=False):
        raise SkillRegistryError("skill packs are for registered specialist agents")
    if task_class not in ALLOWED_TASK_CLASSES or not isinstance(tier, Tier):
        raise SkillRegistryError("invalid task class or tier")
    agent_record(actor)  # Fail closed if the canonical registry is inconsistent.
    registry, digest = load_skill_registry()
    if tier == Tier.NANO:
        selected = []  # Preserve the measured minimal-prompt classification path.
    else:
        selected = [item for item in registry["skills"] if task_class in item["task_classes"]]
    chosen = {item["skill_id"] for item in selected}
    if any(not set(item["dependencies"]) <= chosen for item in selected):
        raise SkillRegistryError("selected skill is missing a dependency")
    try:
        from .hyper_inference.channels import CHANNEL_SPECS
        from .hyper_inference.engines import ENGINE_SPECS

        advisory_fabric = {
            "engine_families": sorted({spec["family"] for spec in ENGINE_SPECS.values()}),
            "channel_ids": sorted(CHANNEL_SPECS),
            "status": "DRAFT_CANDIDATE",
            "authority": "ADVISORY_ONLY",
        }
    except Exception:
        advisory_fabric = {"available": False, "authority": "ADVISORY_ONLY"}
    return {
        "agent_id": actor,
        "registry_sha256": digest,
        "skill_ids": [item["skill_id"] for item in selected],
        "guidance": [item["instruction"] for item in selected],
        "tool_grants": [],
        "authority": "ADVISORY_ONLY",
        "evidence_state": "BRANCH_ROUTING_ONLY_NOT_AGENT_COMPETENCE",
        "advisory_fabric": advisory_fabric,
    }
