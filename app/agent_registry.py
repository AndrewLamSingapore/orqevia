"""Canonical JARVIS agent registry and deny-by-default public projection."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "agent_registry.json"
MAX_DELEGATION_DEPTH = 1

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

def may_delegate(source: str, target: str, *, depth: int = 1) -> bool:
    """Stable-Spine delegation rule: only direct lead->child delegation, one level deep."""
    if depth < 1 or depth > MAX_DELEGATION_DEPTH:
        return False
    agents = _index()
    src, dst = agents.get(source), agents.get(target)
    return bool(src and dst and src.get("role") == "Lead" and dst.get("reports_to") == source)

def may_consult(source: str, target: str) -> bool:
    """Consultation is bounded to the agent's own lead or lead-to-lead peer review."""
    if source == target:
        return False
    agents = _index()
    src, dst = agents.get(source), agents.get(target)
    if not src or not dst:
        return False
    if src.get("reports_to") == target and dst.get("role") == "Lead":
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
    edges: list[dict[str, str]] = []
    for agent in agents:
        edges.append({"source": agent["reports_to"], "target": agent["id"], "type": "reports_to"})
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
        },
        "disclosure": "Public-safe projection. Operational prompts, credentials, endpoints and internal instructions are excluded by policy."
    }
