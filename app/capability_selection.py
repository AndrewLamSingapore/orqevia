"""Select one owned reasoning capability without a reporting hierarchy."""

from __future__ import annotations

import json
from pathlib import Path
import re

from .agent_registry import RegistryError, load_agent_registry

ROUTES_PATH = Path(__file__).resolve().parents[1] / "config/task_capability_routes.json"


def select_capability(objective: str) -> str:
    routes = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
    if routes.get("schema") != "orqevia.task-capability-routes.v1":
        raise RegistryError("unsupported task capability routes")
    available = {
        capability
        for agent in load_agent_registry()["agents"]
        if agent.get("lifecycle_status") == "active"
        for capability in agent["capability_requirements"]
    }
    fallback = routes.get("default")
    if fallback not in available:
        raise RegistryError("default reasoning capability is unavailable")
    text = " ".join(re.findall(r"[a-z0-9]+", objective.lower()))
    best, best_score = fallback, 0
    seen = set()
    for route in routes["routes"]:
        capability, terms = route["capability"], route["terms"]
        if capability in seen or not isinstance(terms, list) or not terms:
            raise RegistryError("invalid task capability route")
        seen.add(capability)
        if any(not isinstance(term, str) or not re.fullmatch(r"[a-z0-9]+(?: [a-z0-9]+)*", term) for term in terms):
            raise RegistryError("invalid task capability term")
        if capability not in available:
            continue
        score = sum(bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text)) for term in set(terms))
        if score > best_score:
            best, best_score = capability, score
    return best
