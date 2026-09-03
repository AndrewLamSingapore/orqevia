"""Canonical JARVIS agent registry and deny-by-default public projection."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "agent_registry.json"

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
    known = set(ids) | {data.get("orchestrator", {}).get("id")}
    for agent in agents:
        if agent.get("reports_to") not in known:
            raise RegistryError(f"unknown parent for {agent.get('id')}")
    # Cycle check. PRIME is the only allowed root.
    parent = {a["id"]: a["reports_to"] for a in agents}
    for start in ids:
        seen, node = set(), start
        while node != data["orchestrator"]["id"]:
            if node in seen:
                raise RegistryError(f"hierarchy cycle at {start}")
            seen.add(node)
            node = parent.get(node)
            if node is None:
                raise RegistryError(f"orphan agent {start}")
    return data

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
        "disclosure": "Public-safe projection. Operational prompts, credentials, endpoints and internal instructions are excluded by policy."
    }
