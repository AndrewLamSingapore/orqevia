"""Canonical JARVIS agent registry and deny-by-default public projection."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "agent_registry.json"
MAX_DELEGATION_DEPTH = 1

# Backward-compatible role aliases are resolved to canonical registered agent IDs
# before work reaches the shared compute fabric. Unknown agent identities fail closed.
AGENT_ALIASES = {
    "prime": "prime",
    "strategy": "A01", "planner": "A02", "planning": "A02", "roadmap": "A03", "decision": "A04", "portfolio": "A05",
    "research": "A06", "evidence": "A07", "comparison": "A08", "knowledge": "A09", "gap": "A10",
    "data": "A11", "metrics": "A12", "analyst": "A13", "analysis": "A13", "forecast": "A14", "data-quality": "A15",
    "engineering": "A16", "architecture": "A17", "coding": "A18", "implementation": "A18", "test": "A19", "reliability": "A20",
    "economic": "A21", "value": "A22", "cost": "A23", "asset": "A24",
    "quality": "A25", "verification": "A26", "critic": "A27", "risk": "A28", "policy": "A29",
}


class RegistryError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_agent_registry() -> dict[str, Any]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    agents = data.get("agents", [])
    if len(agents) != 29:
        raise RegistryError(f"agent registry must contain exactly 29 agents; found {len(agents)}")
    ids = [a.get("id") for a in agents]
    if len(ids) != len(set(ids)) or any(not x for x in ids):
        raise RegistryError("agent IDs must be present and unique")
    prime = data.get("orchestrator", {}).get("id")
    if not prime:
        raise RegistryError("orchestrator ID is required")
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
    alias = AGENT_ALIASES.get(raw.lower())
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
        if agent.get("role") == "Lead" and str(agent.get("division", "")).lower() == wanted:
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
        return dst.get("role") == "Lead" and dst.get("reports_to") == prime
    src = agents.get(src_id)
    return bool(src and src.get("role") == "Lead" and dst.get("reports_to") == src_id)


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
    if src.get("reports_to") == dst_id and dst.get("role") == "Lead":
        return True
    if src.get("role") == "Lead" and dst.get("role") == "Lead":
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
            "unknown_agent_policy": "deny",
        },
        "disclosure": "Public-safe projection. Operational prompts, credentials, endpoints and internal instructions are excluded by policy."
    }
