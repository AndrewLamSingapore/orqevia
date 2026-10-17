"""ORQEVIA cognitive orchestrator.

Builds governed context, routes through the canonical agent registry, executes
inference through the model gateway, and never executes consequential actions
directly.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from .agent_runtime import AgentAuthorityRuntime
from .hybrid_memory import HybridMemory
from .answer_evaluator import evaluate_generated_answer
from .memory import MemoryStore
from .model_gateway import ModelGateway
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
    agent_path: list[str]
    memory_context: list[dict[str, Any]]
    portal_context: list[dict[str, Any]]
    needs_approval: bool
    proposed_action: dict[str, Any] | None
    confidence: str
    gaps: list[str]
    reasoning_route: dict[str, Any]
    fabric_advisory: dict[str, Any] | None = None

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
    def __init__(self, memory: MemoryStore | None = None, portal: PortalGrounder | None = None,
                 routing: RoutingPolicy | None = None, gateway: ModelGateway | None = None,
                 authority_runtime: AgentAuthorityRuntime | None = None):
        self.memory = memory or MemoryStore()
        self.hybrid_memory = HybridMemory(self.memory)
        self.portal = portal or PortalGrounder()
        self.routing = routing or RoutingPolicy()
        self.gateway = gateway or ModelGateway()
        self.authority_runtime = authority_runtime or AgentAuthorityRuntime()

    def plan(self, *, intent: str, department: str = "", context: str = "", allow_frontier: bool = False) -> CognitivePlan:
        intent = (intent or "").strip()
        if not intent:
            raise ValueError("intent is required")
        memory_context = self.hybrid_memory.search(intent, limit=8)
        route = choose_specialist(department, intent, context)
        agent_path = self.authority_runtime.resolve_path(route.specialist, intent)
        use_portal = route.specialist in {"research", "strategy", "engineering"} or len(memory_context) < 2
        portal_context = self.portal.query(intent, limit=8) if use_portal else []
        consequential = has_consequential_intent(intent, context)
        action = None
        if consequential:
            action = {"action": "external.action.proposal", "parameters": {"intent": intent},
                      "context": {"department": department, "reason": "Consequential intent requires Stable Spine classification."}}
        gaps: list[str] = []
        if not memory_context:
            gaps.append("No relevant durable personal memory was found.")
        if use_portal and not portal_context:
            gaps.append("No relevant Portal grounding was available.")
        confidence = "strong" if memory_context and (portal_context or not use_portal) else "partial" if memory_context or portal_context else "limited"
        reasoning_route = self.routing.decide(local_confidence=confidence, frontier_allowed=allow_frontier,
                                               frontier_available=self.gateway.frontier_available,
                                               consequential=consequential).as_dict()
        if reasoning_route["selected_stage"] == "confidence_hold":
            gaps.append("Reasoning is held at the confidence gate; frontier inference is unavailable or not authorized.")
        fabric_advisory = None
        try:
            # Advisory-only Hyper-Inference Fabric projection. It never grants
            # authority or executes tools; failures are contained and cannot
            # block the governed reasoning plan.
            from .hyper_inference.router import AdaptiveInferenceRouter

            fabric_complexity = "high" if consequential else ("medium" if confidence == "limited" else "low")
            fabric_advisory = AdaptiveInferenceRouter().route(
                objective=intent,
                agent_id=agent_path[-1] if agent_path else "a01",
                evidence=memory_context + portal_context,
                agent_permissions={"reason.advisory"},
                complexity=fabric_complexity,
            ).as_dict()
        except Exception:
            fabric_advisory = None
        return CognitivePlan(intent, route.specialist, route.reason, agent_path, memory_context, portal_context,
                             consequential, action, confidence, gaps, reasoning_route,
                             fabric_advisory=fabric_advisory)

    @staticmethod
    def _prompt(plan: CognitivePlan, context: str) -> str:
        return f"""ORQEVIA GOVERNED REASONING REQUEST
Intent: {plan.intent}
Specialist domain: {plan.specialist}
Canonical agent path: {' -> '.join(plan.agent_path)}
Consequential action requested: {plan.needs_approval}

User context:
{context[:6000] if context else 'None supplied.'}

Governed memory context:
{json.dumps(plan.memory_context, ensure_ascii=False)[:12000]}

Portal evidence context:
{json.dumps(plan.portal_context, ensure_ascii=False)[:12000]}

Rules:
- Reason only from the supplied context and clearly marked general reasoning.
- Never claim an external action was executed.
- Preserve uncertainty and evidence boundaries.
- If consequential action is appropriate, return a proposal only; explicit owner approval remains required.
- Give the most useful bounded answer and list material evidence gaps.
""".strip()

    def execute(self, *, intent: str, department: str = "", context: str = "", allow_frontier: bool = False,
                deep: bool = False) -> dict[str, Any]:
        plan = self.plan(intent=intent, department=department, context=context, allow_frontier=allow_frontier)
        trace_id = self.authority_runtime.begin_path(plan.agent_path, consequential=plan.needs_approval)
        agent_id = plan.agent_path[-1]
        prompt = self._prompt(plan, context)
        started = time.perf_counter()
        self.authority_runtime.stage(trace_id=trace_id, agent_id=agent_id, stage="reasoning", status="started",
                                     consequential=plan.needs_approval)
        try:
            # Preserve the canonical compute-ledger stage name; agent identity is
            # independently recorded in the authority ledger.
            local = self.gateway.local(prompt=prompt, deep=deep, task_id=trace_id, stage="local_ai")
            result = local
            evaluation = evaluate_generated_answer(gateway=self.gateway, task_id=local.task_id, intent=intent,
                                                   answer=local.text, memory_context=plan.memory_context,
                                                   portal_context=plan.portal_context, consequential=plan.needs_approval)
            escalated = False
            if not evaluation["released"] and allow_frontier and self.gateway.frontier_available:
                self.authority_runtime.stage(trace_id=trace_id, agent_id=agent_id, stage="frontier_escalation", status="started",
                                             consequential=plan.needs_approval)
                frontier_started = time.perf_counter()
                frontier_prompt = prompt + "\n\nLOCAL DRAFT TO CRITIQUE AND IMPROVE:\n" + local.text[:12000]
                result = self.gateway.frontier(prompt=frontier_prompt, task_id=local.task_id)
                self.authority_runtime.stage(
                    trace_id=trace_id, agent_id=agent_id, stage="frontier_escalation", status="completed",
                    latency_ms=(time.perf_counter() - frontier_started) * 1000, consequential=plan.needs_approval,
                )
                evaluation = evaluate_generated_answer(gateway=self.gateway, task_id=local.task_id, intent=intent,
                                                       answer=result.text, memory_context=plan.memory_context,
                                                       portal_context=plan.portal_context, consequential=plan.needs_approval)
                escalated = True
        except Exception:
            self.authority_runtime.stage(
                trace_id=trace_id, agent_id=agent_id, stage="reasoning", status="failed",
                latency_ms=(time.perf_counter() - started) * 1000, consequential=plan.needs_approval,
            )
            raise

        post_confidence = "strong" if evaluation["released"] else "partial" if evaluation["score"] >= 0.55 else "limited"
        final_route = self.routing.decide(local_confidence=post_confidence, frontier_allowed=allow_frontier,
                                          frontier_available=self.gateway.frontier_available,
                                          consequential=plan.needs_approval).as_dict()
        plan_dict = plan.as_dict(); plan_dict["pre_inference_confidence"] = plan.confidence
        plan_dict["confidence"] = post_confidence; plan_dict["reasoning_route"] = final_route
        final_status = "completed" if evaluation["released"] else "withheld"
        self.authority_runtime.stage(
            trace_id=trace_id, agent_id=agent_id, stage="reasoning", status=final_status,
            latency_ms=(time.perf_counter() - started) * 1000, consequential=plan.needs_approval,
        )
        if not evaluation["released"]:
            metadata = {key: value for key, value in result.as_dict().items() if key != "text"}
            return {"trace_id": trace_id, "plan": plan_dict, "result": None, "withheld_result": metadata,
                    "evaluation": evaluation,
                    "confidence_hold": {"held": True, "reason": final_route["reason"], "blocking_metrics": evaluation["blocking_metrics"], "evidence_gaps": evaluation["evidence_gaps"]},
                    "escalated": escalated, "approval_required": plan.needs_approval, "executed_external_action": False}
        return {"trace_id": trace_id, "plan": plan_dict, "result": result.as_dict(),
                "local_result": local.as_dict() if escalated else None, "evaluation": evaluation,
                "confidence_hold": {"held": False}, "escalated": escalated,
                "approval_required": plan.needs_approval, "executed_external_action": False}
