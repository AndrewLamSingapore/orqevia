"""PRIME CORE cognitive orchestrator v1.

Assembles bounded context from Personal JARVIS Memory and The Portal before
routing to a specialist. It never executes consequential actions directly.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from .memory import MemoryStore
from .orchestration import choose_specialist, has_consequential_intent
from .routing_policy import RoutingPolicy

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")


def tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall((text or "").lower()))


@dataclass(frozen=True)
class CognitivePlan:
    intent: str
    specialist: str
    route_reason: str
    memory_context: list[dict[str, Any]]
    portal_context: list[dict[str, Any]]
    needs_approval: bool
    proposed_action: dict[str, Any] | None
    confidence: str
    gaps: list[str]
    reasoning_route: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PortalGrounder:
    def __init__(self, base_url: str | None = None, timeout: float = 3.0):
        self.base_url = (base_url or os.getenv("PORTAL_BASE_URL") or "").rstrip("/")
        self.timeout = timeout

    def query(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        if not self.base_url:
            return []
        capped = max(1, min(int(limit), 20))
        params = urllib.parse.urlencode({"q": query, "limit": capped})
        try:
            request = urllib.request.Request(f"{self.base_url}/api/graph?{params}", headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                graph = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return []
        ranked: list[tuple[int, dict[str, Any]]] = []
        for node in graph.get("nodes", []) if isinstance(graph, dict) else []:
            if not isinstance(node, dict):
                continue
            score = int(node.get("grounding_score") or 0)
            if not score:
                text = " ".join(str(node.get(k, "")) for k in ("label", "title", "name", "summary", "description", "type"))
                score = len(tokens(query) & tokens(text))
            if score:
                ranked.append((score, node))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [{"score": score, "node": node} for score, node in ranked[:capped]]


class CognitiveOrchestrator:
    def __init__(self, memory: MemoryStore | None = None, portal: PortalGrounder | None = None, routing: RoutingPolicy | None = None):
        self.memory = memory or MemoryStore()
        self.portal = portal or PortalGrounder()
        self.routing = routing or RoutingPolicy()

    def plan(self, *, intent: str, department: str = "", context: str = "", allow_frontier: bool = False) -> CognitivePlan:
        intent = (intent or "").strip()
        if not intent:
            raise ValueError("intent is required")
        memory_context = self.memory.search(intent, limit=8)
        route = choose_specialist(department, intent, context)
        use_portal = route.specialist in {"research", "strategy", "engineering"} or len(memory_context) < 2
        portal_context = self.portal.query(intent, limit=8) if use_portal else []
        consequential = has_consequential_intent(intent, context)
        action = None
        if consequential:
            action = {
                "action": "external.action.proposal",
                "parameters": {"intent": intent},
                "context": {"department": department, "reason": "Consequential intent requires Stable Spine classification."},
            }
        gaps: list[str] = []
        if not memory_context:
            gaps.append("No relevant durable personal memory was found.")
        if use_portal and not portal_context:
            gaps.append("No relevant Portal grounding was available.")
        confidence = "strong" if memory_context and (portal_context or not use_portal) else "partial" if memory_context or portal_context else "limited"
        reasoning_route = self.routing.decide(
            local_confidence=confidence,
            frontier_allowed=allow_frontier,
            frontier_available=False,
            consequential=consequential,
        ).as_dict()
        if reasoning_route["selected_stage"] == "confidence_hold":
            gaps.append("Reasoning is held at the confidence gate; no frontier inference resource is currently available.")
        return CognitivePlan(
            intent=intent,
            specialist=route.specialist,
            route_reason=route.reason,
            memory_context=memory_context,
            portal_context=portal_context,
            needs_approval=consequential,
            proposed_action=action,
            confidence=confidence,
            gaps=gaps,
            reasoning_route=reasoning_route,
        )
