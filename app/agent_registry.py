"""Canonical JARVIS agent registry and deny-by-default public projection."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "agent_registry.json"
MAX_DELEGATION_DEPTH = 2

# Backward-compatible role aliases are resolved to canonical registered agent IDs
# before work reaches the shared compute fabric. Unknown agent identities fail closed.
MIGRATION_PATH = REGISTRY_PATH.with_name("agent_registry_migration.json")
LEGACY_IDS = json.loads(MIGRATION_PATH.read_text())["legacy_ids"]
AGENT_ALIASES = {
    "prime": "prime", "strategy": "a01", "planner": "a02", "planning": "a02",
    "roadmap": "a03", "decision": "a04", "portfolio": "a05", "research": "a06",
    "evidence": "a07", "comparison": "a08", "knowledge": "a09", "data": "a10",
    "metrics": "a11", "analyst": "a12", "analysis": "a12", "forecast": "a13",
    "data-quality": "a14", "engineering": "a15", "architecture": "a16",
    "coding": "a17", "implementation": "a17", "test": "a18", "reliability": "a19",
    "economic": "a20", "cost": "a21", "value": "a22", "resource": "a23",
    "commercial": "a24", "quality": "a25", "critic": "a26", "review": "a26",
    "verification": "a27", "risk": "a28", "release": "a29",
}


class RegistryError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_agent_registry() -> dict[str, Any]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.1":
        raise RegistryError("unsupported registry schema")
    aliases = {lead["id"]: lead["agent_id"] for lead in data.get("leads", [])}
    if len(aliases) != 6 or len(set(aliases.values())) != 6:
        raise RegistryError("six unique lead aliases required")
    domains = {lead["agent_id"]: lead["domain"] for lead in data["leads"]}
    agents = data.get("agents", [])
    for agent in agents:
        agent["id"] = agent["agent_id"]
        agent["reports_to"] = aliases.get(agent["reports_to"], agent["reports_to"])
        agent["division"] = domains.get(agent["id"], domains.get(agent["reports_to"], "")).title()
        if agent.get("can_delegate") != (agent["id"] in domains):
            raise RegistryError("only leads may delegate")
        if agent.get("authority") not in {"advisory", "restricted"}:
            raise RegistryError("unsupported agent authority")
        if agent.get("authority") == "restricted" and agent.get("human_approval") != "required_for_execution":
            raise RegistryError("restricted execution requires approval")
        if agent.get("status") != "planned" or agent.get("model") != "unassigned":
            raise RegistryError("runtime activation requires separately verified configuration")
    if len(agents) != 29:
        raise RegistryError(f"agent registry must contain exactly 29 agents; found {len(agents)}")
    ids = [a.get("id") for a in agents]
    if len(ids) != len(set(ids)) or any(not x for x in ids):
        raise RegistryError("agent IDs must be present and unique")
    prime = data.get("orchestrator", {}).get("id")
    if not prime:
        raise RegistryError("orchestrator ID is required")
    if set(ids) != {f"a{i:02}" for i in range(1, 30)} or prime in ids:
        raise RegistryError("canonical identity set is invalid")
    if not set(domains).issubset(ids):
        raise RegistryError("lead aliases must resolve to registered agents")
    if any(a["reports_to"] != prime for a in agents if a["id"] in domains):
        raise RegistryError("leads must report to PRIME")
    known = set(ids) | {prime}
    for agent in agents:
        if agent.get("reports_to") not in known:
            raise RegistryError(f"unknown parent for {agent.get('id')}")
    parent = {a["id"]: a["reports_to"] for a in agents}
    for start in ids:
        seen, node = set(), start
        while node != prime:
            if node in seen:
                raise RegistryError(f"hierarchy cycle at {start}")
            seen.add(node)
            node = parent.get(node)
            if node is None:
                raise RegistryError(f"orphan agent {start}")
    return data


def _index() -> dict[str, dict[str, Any]]:
    data = load_agent_registry()
    return {a["id"]: a for a in data["agents"]}


def orchestrator_id() -> str:
    return str(load_agent_registry()["orchestrator"]["id"])


def registered_agent_ids(*, include_orchestrator: bool = True) -> set[str]:
    ids = set(_index())
    if include_orchestrator:
        ids.add(orchestrator_id())
    return ids


def canonical_agent_id(value: str) -> str:
    """Resolve a canonical agent ID; reject unknown or invented identities."""
    raw = (value or "").strip()
    if not raw:
        raise RegistryError("agent identity is required")
    if raw in registered_agent_ids():
        return raw
    # Case distinguishes retired A10 from the new canonical Data Lead a10.
    alias = LEGACY_IDS.get(raw) or AGENT_ALIASES.get(raw.lower())
    alias = alias or next((x["agent_id"] for x in load_agent_registry()["leads"] if x["id"] == raw), None)
    if alias and alias in registered_agent_ids():
        return alias
    raise RegistryError(f"unregistered agent identity: {raw}")


def agent_record(agent_id: str) -> dict[str, Any]:
    canonical = canonical_agent_id(agent_id)
    if canonical == orchestrator_id():
        return dict(load_agent_registry()["orchestrator"])
    return dict(_index()[canonical])


def domain_lead(division: str) -> str:
    wanted = (division or "").strip().lower()
    for agent in _index().values():
        if agent.get("can_delegate") is True and str(agent.get("division", "")).lower() == wanted:
            return agent["id"]
    raise RegistryError(f"no registered lead for division: {division}")


def may_delegate(source: str, target: str, *, depth: int = 1) -> bool:
    """Only a direct orchestrator->lead or lead->child delegation is allowed."""
    if depth < 1 or depth > MAX_DELEGATION_DEPTH:
        return False
    try:
        src_id, dst_id = canonical_agent_id(source), canonical_agent_id(target)
    except RegistryError:
        return False
    agents = _index()
    dst = agents.get(dst_id)
    if not dst:
        return False
    prime = orchestrator_id()
    if src_id == prime:
        if depth != 1:
            return False
        return dst.get("can_delegate") is True and dst.get("reports_to") == prime
    src = agents.get(src_id)
    return bool(src and src.get("can_delegate") is True and dst.get("reports_to") == src_id)


def may_consult(source: str, target: str) -> bool:
    """Consultation is bounded to an agent's own lead or lead-to-lead peer review."""
    try:
        src_id, dst_id = canonical_agent_id(source), canonical_agent_id(target)
    except RegistryError:
        return False
    if src_id == dst_id or orchestrator_id() in {src_id, dst_id}:
        return False
    agents = _index()
    src, dst = agents.get(src_id), agents.get(dst_id)
    if not src or not dst:
        return False
    if src.get("reports_to") == dst_id and dst.get("can_delegate") is True:
        return True
    if src.get("can_delegate") is True and dst.get("can_delegate") is True:
        return True
    return False


def requires_owner_approval(*, consequential: bool) -> bool:
    """No agent relationship can bypass owner approval for consequential action."""
    return bool(consequential)


def public_relationships() -> list[dict[str, str]]:
    data = load_agent_registry()
    agents = data["agents"]
    prime = data["orchestrator"]["id"]
    edges: list[dict[str, str]] = []
    for agent in agents:
        edges.append({"source": agent["reports_to"], "target": agent["id"], "type": "reports_to"})
        if may_delegate(prime, agent["id"]):
            edges.append({"source": prime, "target": agent["id"], "type": "may_delegate"})
    for src in agents:
        for dst in agents:
            if may_delegate(src["id"], dst["id"]):
                edges.append({"source": src["id"], "target": dst["id"], "type": "may_delegate"})
            elif may_consult(src["id"], dst["id"]):
                edges.append({"source": src["id"], "target": dst["id"], "type": "may_consult"})
    return edges


def public_agent_registry() -> dict[str, Any]:
    data = load_agent_registry()
    allowed = set(data["publication_policy"]["allowed_fields"])
    # Explicit compatibility fields for the existing public network consumer.
    allowed |= {"id", "division", "reports_to"}
    allowed -= set(data["publication_policy"]["forbidden_fields"])
    return {
        "schema_version": data["schema_version"],
        "last_updated": data["last_updated"],
        "registry_id": data["registry_id"],
        "orchestrator": {
            "id": data["orchestrator"]["id"],
            "name": data["orchestrator"]["name"],
            "role": data["orchestrator"]["role"],
            "public_description": data["orchestrator"]["public_description"],
        },
        "agents": [{k: v for k, v in agent.items() if k in allowed} for agent in data["agents"]],
        "relationships": public_relationships(),
        "relationship_policy": {
            "max_delegation_depth": MAX_DELEGATION_DEPTH,
            "consequential_actions_require_owner_approval": True,
            "network_is_enforced": True,
            "runtime_activation_verified": False,
            "unknown_agent_policy": "deny",
        },
        "disclosure": "Public-safe projection. Operational prompts, credentials, endpoints and internal instructions are excluded by policy."
    }
