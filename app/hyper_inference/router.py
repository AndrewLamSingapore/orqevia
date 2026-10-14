"""Adaptive inference router.

Implements the ten-step ORQEVIA routing contract: classify the task, identify
required reasoning capabilities, retrieve relevant evidence, select inference
channels, allocate bounded parallel execution, invoke authorized models and
tools, detect contradictory results, request additional evidence when
necessary, apply independent verification, and produce a traceable result.
"""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .channels import CHANNEL_SPECS, ChannelResult, run_channel
from .engines import ENGINE_SPECS, InferenceEngineRegistry
from .matrices import CapabilityMatrix, VectorStore
from .proxies import ModelProxyRegistry, ProxyError, ToolProxyRegistry


AGENT_REGISTRY_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "agent_registry.json"


@dataclass(frozen=True)
class RouterResult:
    trace_id: str
    objective: str
    task_class: str
    required_capabilities: tuple[str, ...]
    evidence_retrieved: int
    channels_selected: tuple[str, ...]
    channel_results: tuple[dict[str, Any], ...]
    contradictions: tuple[str, ...]
    evidence_requests: tuple[str, ...]
    verification: dict[str, Any]
    escalation: dict[str, Any]
    conclusion: dict[str, Any]
    receipts: tuple[dict[str, Any], ...] = ()
    executed_external_action: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_TASK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "deduction": ("deduce", "deductive", "prove", "if then", "syllogism", "logic"),
    "induction": ("induce", "generalize", "pattern", "sample", "inductive"),
    "abduction": ("explain", "diagnose", "root cause", "why", "best explanation"),
    "causal": ("cause", "effect", "causal", "because"),
    "forecast": ("forecast", "predict", "probability", "bayes"),
    "spatial": ("near", "distance", "contained", "spatial", "map"),
    "constraint": ("constraint", "schedule", "assign", "satisfy"),
    "comparison": ("compare", "analogy", "similar"),
    "risk": ("risk", "failure", "recover", "safe"),
}

_TASK_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "deduction": ("logical_validity", "rule_application"),
    "induction": ("generalization", "sample_evidence"),
    "abduction": ("best_explanation", "hypothesis_ranking"),
    "causal": ("causal_consistency", "path_reasoning"),
    "forecast": ("belief_update", "distribution"),
    "spatial": ("distance", "containment"),
    "constraint": ("constraint_satisfaction", "unsat_detection"),
    "comparison": ("similarity", "structure_mapping"),
    "risk": ("uncertainty_governance", "strategy_selection"),
}


def classify_task(objective: str) -> str:
    text = objective.casefold()
    for task_class, keywords in _TASK_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return task_class
    return "deduction"


def _load_agent_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = path or AGENT_REGISTRY_PATH
    try:
        raw = registry_path.read_bytes()
    except OSError as exc:
        raise FileNotFoundError(f"agent registry unavailable: {registry_path}") from exc
    data = json.loads(raw)
    agents = data.get("agents")
    if not isinstance(agents, list) or not agents:
        raise ValueError("agent registry has no agents")
    return data


def build_capability_matrix(registry: dict[str, Any] | None = None) -> CapabilityMatrix:
    """Project the authoritative agent registry into a capability matrix."""
    data = registry or _load_agent_registry()
    matrix = CapabilityMatrix()
    role_capabilities = {
        "Strategic reasoning owner": {"logical_validity", "strategy_selection"},
        "Objective-to-task decomposition; Milestone and dependency planning": {"logical_validity", "constraint_satisfaction"},
        "Option evaluation; Structured comparison": {"similarity", "structure_mapping"},
        "Portfolio prioritization; Resource optimization": {"constraint_satisfaction", "strategy_selection"},
        "Research direction": {"generalization", "sample_evidence"},
        "Evidence discovery": {"generalization", "sample_evidence"},
        "Knowledge organization": {"similarity", "structure_mapping"},
        "Data and analytics coordination": {"distribution", "sample_evidence"},
        "KPI definition; Descriptive/diagnostic analysis": {"generalization", "best_explanation"},
        "Forecasting": {"belief_update", "distribution"},
        "Data quality checks": {"sample_evidence", "constraint_satisfaction"},
        "Technical execution ownership": {"constraint_satisfaction", "rule_application"},
        "System architecture design": {"structure_mapping", "constraint_satisfaction"},
        "Design-to-code conversion": {"rule_application", "constraint_satisfaction"},
        "Functional testing; Compliance verification": {"logical_validity", "constraint_satisfaction"},
        "Operational resilience evaluation": {"uncertainty_governance", "strategy_selection"},
        "Economic analysis ownership; Market and pricing analysis": {"distribution", "belief_update"},
        "Cost analysis; Value/ROI evaluation": {"distribution", "belief_update"},
        "Quality governance ownership; Independent review": {"uncertainty_governance", "logical_validity"},
        "Risk identification": {"uncertainty_governance", "best_explanation"},
        "Release readiness gate": {"constraint_satisfaction", "uncertainty_governance"},
    }
    for agent in data["agents"]:
        agent_id = agent.get("agent_id") or agent.get("id") or agent.get("immutable_id")
        role = agent.get("role", "")
        if not agent_id:
            continue
        capabilities = role_capabilities.get(role, set())
        matrix.add(agent_id, capabilities, authority="advisory")
    return matrix


class AdaptiveInferenceRouter:
    """Ten-step adaptive router with bounded parallelism and traceability."""

    def __init__(self, *, capability_matrix: CapabilityMatrix | None = None,
                 vector_store: VectorStore | None = None,
                 model_proxy: ModelProxyRegistry | None = None,
                 tool_proxy: ToolProxyRegistry | None = None,
                 max_parallel: int = 4) -> None:
        self.capability_matrix = capability_matrix or build_capability_matrix()
        self.vector_store = vector_store or VectorStore()
        self.model_proxy = model_proxy or ModelProxyRegistry()
        self.tool_proxy = tool_proxy or ToolProxyRegistry()
        self.max_parallel = max(1, max_parallel)

    def route(self, *, objective: str, agent_id: str,
              evidence: list[dict[str, Any]] | None = None,
              hypotheses: list[dict[str, Any]] | None = None,
              agent_permissions: set[str] | None = None,
              complexity: str = "low") -> RouterResult:
        if not objective or not objective.strip():
            raise ValueError("objective is required")
        agent_id = agent_id.strip()
        if not agent_id:
            raise ValueError("agent_id is required")
        permissions = set(agent_permissions or {"reason.advisory"})
        trace_id = str(uuid.uuid4())
        trace: list[str] = []

        # 1. Classify the task.
        task_class = classify_task(objective)
        trace.append(f"classify={task_class}")

        # 2. Identify required reasoning capabilities.
        required_capabilities = _TASK_CAPABILITIES.get(task_class, ("logical_validity",))
        trace.append(f"capabilities={','.join(required_capabilities)}")

        # 3. Retrieve relevant evidence.
        evidence_rows = list(evidence or [])
        if not evidence_rows and self.vector_store.vectors:
            query = [hash(word) % 7 for word in objective.split()] or [0]
            evidence_rows = [
                {"proposition": key, "score": score}
                for key, score in self.vector_store.search(query, top_k=3)
            ]
        trace.append(f"evidence={len(evidence_rows)}")

        # 4. Select appropriate inference channels.
        channels = self._select_channels(task_class, complexity, hypotheses)
        trace.append(f"channels={','.join(channels)}")

        # 5. Allocate bounded parallel execution.
        selected = channels[: self.max_parallel]
        task = {
            "objective": objective,
            "task_class": task_class,
            "evidence": evidence_rows,
            "hypotheses": hypotheses or [],
            "observations": evidence_rows,
        }
        channel_results: list[ChannelResult] = []
        with ThreadPoolExecutor(max_workers=len(selected) or 1) as pool:
            futures = {pool.submit(run_channel, channel_id, task): channel_id
                       for channel_id in selected}
            for future in futures:
                try:
                    channel_results.append(future.result())
                except Exception as exc:
                    channel_id = futures[future]
                    channel_results.append(ChannelResult(channel_id, False,
                                                          {"error": str(exc)}, 0.0))

        # 6. Invoke authorised models and tools.
        receipts: list[dict[str, Any]] = []
        try:
            route = self.model_proxy.route(
                required_capabilities=set(required_capabilities),
                agent_permissions=permissions,
            )
            receipts.append(self.model_proxy.invoke(
                agent_id=agent_id, prompt=objective, route=route,
                agent_permissions=permissions,
            ).as_dict())
        except ProxyError as exc:
            trace.append(f"model_denied={type(exc).__name__}")
        for tool_id in self.tool_proxy.discover(
            capabilities=set(required_capabilities), agent_permissions=permissions
        ):
            receipts.append(self.tool_proxy.invoke(
                agent_id=agent_id, tool_id=tool_id, params={"objective": objective},
                agent_permissions=permissions,
            ).as_dict())

        # 7. Detect contradictory results.
        contradictions = self._detect_contradictions(channel_results)
        trace.append(f"contradictions={len(contradictions)}")

        # 8. Request additional evidence when necessary.
        evidence_requests: list[str] = []
        if contradictions:
            evidence_requests.append("discriminating evidence for contradictory results")
        if not evidence_rows:
            evidence_requests.append("grounding evidence for objective")
        if complexity in {"high", "critical"}:
            evidence_requests.append("independent verification evidence")
        trace.append(f"evidence_requests={len(evidence_requests)}")

        # 9. Apply independent verification.
        verification_task = dict(task)
        verification_task["candidate"] = self._best_result(channel_results)
        verification = run_channel("channel.verifier-guided", verification_task).result
        trace.append("independent_verification=complete")

        # 10. Produce a traceable result.
        escalation = self._escalation(
            task_class=task_class, complexity=complexity,
            contradictions=contradictions, confidence=self._best_confidence(channel_results),
        )
        conclusion = {
            "objective": objective,
            "agent_id": agent_id,
            "task_class": task_class,
            "best_result": self._best_result(channel_results),
            "confidence": self._best_confidence(channel_results),
            "verified": bool(verification.get("verified_result")),
        }
        trace.append("result=traced")
        return RouterResult(
            trace_id=trace_id,
            objective=objective,
            task_class=task_class,
            required_capabilities=required_capabilities,
            evidence_retrieved=len(evidence_rows),
            channels_selected=tuple(selected),
            channel_results=tuple(result.as_dict() for result in channel_results),
            contradictions=tuple(contradictions),
            evidence_requests=tuple(evidence_requests),
            verification=verification,
            escalation=escalation,
            conclusion=conclusion,
            receipts=tuple(receipts),
        )

    @staticmethod
    def _select_channels(task_class: str, complexity: str,
                         hypotheses: list[dict[str, Any]] | None) -> list[str]:
        channels = ["channel.direct"]
        if hypotheses:
            channels.append("channel.parallel-hypotheses")
        if task_class in {"abduction", "causal", "risk"}:
            channels.append("channel.retrieval-grounded")
        if complexity in {"medium", "high", "critical"}:
            channels.extend(["channel.independent-critique", "channel.multi-agent-debate"])
        if complexity in {"high", "critical"}:
            channels.append("channel.verifier-guided")
        return channels

    @staticmethod
    def _detect_contradictions(results: list[ChannelResult]) -> list[str]:
        contradictions: list[str] = []
        for result in results:
            contradictions.extend(result.contradictions)
            if result.confidence == 0.0:
                contradictions.append(f"{result.channel_id} produced zero-confidence result")
        return sorted(set(contradictions))

    @staticmethod
    def _best_result(results: list[ChannelResult]) -> dict[str, Any]:
        if not results:
            return {}
        return max(results, key=lambda result: result.confidence).result

    @staticmethod
    def _best_confidence(results: list[ChannelResult]) -> float:
        if not results:
            return 0.0
        return max(result.confidence for result in results)

    @staticmethod
    def _escalation(*, task_class: str, complexity: str,
                    contradictions: list[str], confidence: float) -> dict[str, Any]:
        required = complexity in {"high", "critical"} or bool(contradictions) or confidence < 0.5
        reasons: list[str] = []
        if complexity in {"high", "critical"}:
            reasons.append(f"task_complexity={complexity}")
        if contradictions:
            reasons.append("contradictory_results")
        if confidence < 0.5:
            reasons.append("low_confidence")
        return {"required": required, "reasons": reasons,
                "channel": "owner_or_independent_review" if required else "none"}
