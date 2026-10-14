"""Inference channel registry and channel orchestration.

Channels coordinate reasoning engines but never call external models or tools
directly; that separation belongs to the proxy layer. Each channel exposes
identity, version, capability, cost, latency, permissions and an evidence
contract, and every result remains advisory.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass
from typing import Any

from .engines import EngineResult, InferenceEngineRegistry, run_engine


@dataclass(frozen=True)
class ChannelResult:
    channel_id: str
    ok: bool
    result: dict[str, Any]
    confidence: float
    evidence_ids: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    trace: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _contract(inputs: tuple[str, ...], outputs: tuple[str, ...]) -> dict[str, Any]:
    return {"inputs": list(inputs), "outputs": list(outputs), "authority": "advisory_only"}


CHANNEL_SPECS: dict[str, dict[str, Any]] = {
    "channel.direct": {
        "name": "Direct inference",
        "version": "1.0.0",
        "capabilities": ("single_pass",),
        "cost_class": "low",
        "latency_class": "low",
        "permissions": ("reason.advisory",),
        "evidence_contract": _contract(("task",), ("result", "confidence")),
    },
    "channel.parallel-hypotheses": {
        "name": "Parallel hypotheses",
        "version": "1.0.0",
        "capabilities": ("hypothesis_ranking", "bounded_parallelism"),
        "cost_class": "medium",
        "latency_class": "low",
        "permissions": ("reason.advisory",),
        "evidence_contract": _contract(("task", "hypotheses"), ("ranked_hypotheses",)),
    },
    "channel.sequential-refinement": {
        "name": "Sequential refinement",
        "version": "1.0.0",
        "capabilities": ("iterative_improvement",),
        "cost_class": "medium",
        "latency_class": "medium",
        "permissions": ("reason.advisory",),
        "evidence_contract": _contract(("task", "hypotheses"), ("refined_hypothesis",)),
    },
    "channel.tree-search": {
        "name": "Tree-based search",
        "version": "1.0.0",
        "capabilities": ("bounded_search", "backtracking"),
        "cost_class": "high",
        "latency_class": "high",
        "permissions": ("reason.advisory",),
        "evidence_contract": _contract(("task", "children"), ("best_path",)),
    },
    "channel.graph-search": {
        "name": "Graph-based search",
        "version": "1.0.0",
        "capabilities": ("graph_traversal", "shortest_path"),
        "cost_class": "medium",
        "latency_class": "medium",
        "permissions": ("reason.advisory",),
        "evidence_contract": _contract(("graph", "start", "goal"), ("path",)),
    },
    "channel.multi-agent-debate": {
        "name": "Multi-agent debate",
        "version": "1.0.0",
        "capabilities": ("adversarial_reasoning", "contradiction_detection"),
        "cost_class": "high",
        "latency_class": "high",
        "permissions": ("reason.advisory",),
        "evidence_contract": _contract(("task", "hypotheses"), ("disposition", "objections")),
    },
    "channel.independent-critique": {
        "name": "Independent critique",
        "version": "1.0.0",
        "capabilities": ("independent_review",),
        "cost_class": "medium",
        "latency_class": "medium",
        "permissions": ("reason.advisory",),
        "evidence_contract": _contract(("task", "candidate"), ("objections",)),
    },
    "channel.retrieval-grounded": {
        "name": "Retrieval-grounded inference",
        "version": "1.0.0",
        "capabilities": ("evidence_grounding", "ranking"),
        "cost_class": "low",
        "latency_class": "low",
        "permissions": ("reason.advisory",),
        "evidence_contract": _contract(("task", "evidence"), ("grounded_evidence",)),
    },
    "channel.simulation-driven": {
        "name": "Simulation-driven inference",
        "version": "1.0.0",
        "capabilities": ("scenario_sampling",),
        "cost_class": "high",
        "latency_class": "high",
        "permissions": ("reason.advisory",),
        "evidence_contract": _contract(("task", "scenarios"), ("outcome_distribution",)),
    },
    "channel.verifier-guided": {
        "name": "Verifier-guided execution",
        "version": "1.0.0",
        "capabilities": ("verification", "constraint_checking"),
        "cost_class": "medium",
        "latency_class": "medium",
        "permissions": ("reason.advisory",),
        "evidence_contract": _contract(("task", "constraints"), ("verified_result",)),
    },
}


class InferenceChannelRegistry:
    def __init__(self, specs: dict[str, dict[str, Any]] | None = None) -> None:
        self.specs = dict(specs or CHANNEL_SPECS)
        self._validate()

    def _validate(self) -> None:
        if not self.specs:
            raise ValueError("channel registry cannot be empty")
        seen: set[str] = set()
        for channel_id, spec in self.specs.items():
            if channel_id in seen:
                raise ValueError(f"duplicate channel id: {channel_id}")
            seen.add(channel_id)
            required = {"name", "version", "capabilities", "cost_class", "latency_class",
                        "permissions", "evidence_contract"}
            if not required <= spec.keys():
                raise ValueError(f"incomplete channel spec: {channel_id}")

    def ids(self) -> tuple[str, ...]:
        return tuple(self.specs)

    def spec(self, channel_id: str) -> dict[str, Any]:
        try:
            return dict(self.specs[channel_id])
        except KeyError:
            raise KeyError(f"unknown inference channel: {channel_id}") from None


def _tokens(text: str) -> set[str]:
    return {word.casefold() for word in str(text).split() if len(word) > 2}


def _rank_evidence(task: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query = _tokens(task.get("objective", ""))
    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in evidence:
        text = " ".join(str(item.get(key, "")) for key in ("proposition", "text", "label", "summary"))
        score = len(query & _tokens(text))
        if score:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: -pair[0])
    return [item for _, item in ranked]


def _hypotheses(task: dict[str, Any]) -> list[dict[str, Any]]:
    return list(task.get("hypotheses") or [])


def _score_hypotheses(task: dict[str, Any], hypotheses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observations = task.get("observations") or task.get("evidence") or []
    payload = {"observations": observations, "hypotheses": hypotheses}
    result = run_engine("reasoning.abductive", payload)
    return result.conclusion.get("ranked_hypotheses", [])


def _direct(task: dict[str, Any]) -> ChannelResult:
    if task.get("rule"):
        result = run_engine("reasoning.deductive", {
            "antecedent": task.get("antecedent", ""),
            "consequent": task.get("consequent", ""),
            "antecedent_true": task.get("antecedent_true"),
            "consequent_true": task.get("consequent_true"),
            "rule": task["rule"],
            "premise_evidence": bool(task.get("premise_evidence")),
        })
    elif task.get("hypotheses"):
        ranked = _score_hypotheses(task, _hypotheses(task))
        result = EngineResult("reasoning.abductive", True,
                              {"best_explanation": ranked[0] if ranked else None, "ranked_hypotheses": ranked},
                              ranked[0]["prior"] if ranked else 0.0)
    else:
        result = run_engine("reasoning.meta", {
            "objective": task.get("objective", ""),
            "strategies": task.get("strategies") or [
                {"name": "bounded_default", "expected_information_gain": 1.0, "cost": 1.0},
            ],
        })
    return ChannelResult("channel.direct", True, result.conclusion, result.confidence,
                         evidence_ids=result.evidence_ids, trace=result.trace)


def _parallel_hypotheses(task: dict[str, Any]) -> ChannelResult:
    ranked = _score_hypotheses(task, _hypotheses(task))
    confidence = ranked[0].get("prior", 0.0) if ranked else 0.0
    return ChannelResult("channel.parallel-hypotheses", bool(ranked),
                         {"ranked_hypotheses": ranked}, confidence,
                         trace=(f"ranked={len(ranked)}",))


def _sequential_refinement(task: dict[str, Any]) -> ChannelResult:
    hypotheses = _hypotheses(task)
    if not hypotheses:
        return ChannelResult("channel.sequential-refinement", False, {}, 0.0,
                             contradictions=("no_initial_hypothesis",))
    refined = dict(hypotheses[0])
    for _ in range(min(3, int(task.get("max_refinements", 3)))):
        critique = run_engine("reasoning.meta", {
            "objective": refined.get("proposition", task.get("objective", "")),
            "strategies": [
                {"name": "tighten_scope", "expected_information_gain": 0.4, "cost": 0.5},
                {"name": "gather_evidence", "expected_information_gain": 0.8, "cost": 1.0},
                {"name": "reject_hypothesis", "expected_information_gain": 0.3, "cost": 0.2},
            ],
        })
        selected = critique.conclusion.get("selected_strategy") or {}
        refined["refinements"] = refined.get("refinements", []) + [selected.get("name")]
    return ChannelResult("channel.sequential-refinement", True, {"refined_hypothesis": refined},
                         refined.get("prior", 0.5), trace=("refined",))


def _tree_search(task: dict[str, Any]) -> ChannelResult:
    children = task.get("children") or {}
    start = task.get("root", "root")
    goal = task.get("goal", "goal")
    beam = int(task.get("beam_width", 3))
    best: tuple[float, list[str]] | None = None
    frontier = [(0.0, [start])]
    while frontier:
        score, path = frontier.pop(0)
        node = path[-1]
        if node == goal:
            if best is None or score > best[0]:
                best = (score, path)
            continue
        for child in children.get(node, []):
            frontier.append((score + child.get("score", 0.0), path + [child["id"]]))
        frontier.sort(key=lambda item: -item[0])
        frontier = frontier[:beam]
    if best is None:
        return ChannelResult("channel.tree-search", False, {}, 0.0, contradictions=("goal_unreachable",))
    return ChannelResult("channel.tree-search", True, {"best_path": best[1], "score": best[0]},
                         min(1.0, max(0.0, best[0])), trace=("bounded_beam",))


def _graph_search(task: dict[str, Any]) -> ChannelResult:
    graph = task.get("graph") or {}
    start = task.get("start")
    goal = task.get("goal")
    if start is None or goal is None:
        raise ValueError("graph search requires start and goal")
    queue = [(start, [start])]
    seen = {start}
    while queue:
        node, path = queue.pop(0)
        if node == goal:
            return ChannelResult("channel.graph-search", True, {"path": path}, 1.0,
                                 trace=("bfs_shortest_path",))
        for neighbor in graph.get(node, []):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append((neighbor, path + [neighbor]))
    return ChannelResult("channel.graph-search", False, {}, 0.0, contradictions=("goal_unreachable",))


def _multi_agent_debate(task: dict[str, Any]) -> ChannelResult:
    hypotheses = _hypotheses(task)
    if not hypotheses:
        return ChannelResult("channel.multi-agent-debate", False, {}, 0.0,
                             contradictions=("no_hypothesis",))
    observations = task.get("observations") or []
    objections: list[str] = []
    for hypothesis in hypotheses:
        explains = set(hypothesis.get("explains", ()))
        if explains != set(range(len(observations))):
            objections.append(f"{hypothesis.get('id', '?')} leaves observations unexplained")
        if hypothesis.get("prior", 0.5) < 0.5:
            objections.append(f"{hypothesis.get('id', '?')} has low prior support")
    disposition = "CONTESTED" if objections else "SUPPORTED"
    confidence = 0.5 if objections else max((h.get("prior", 0.0) for h in hypotheses), default=0.0)
    return ChannelResult("channel.multi-agent-debate", True, {"disposition": disposition,
                                                              "objections": objections}, confidence,
                         contradictions=tuple(objections), trace=("adversarial_review",))


def _independent_critique(task: dict[str, Any]) -> ChannelResult:
    candidate = task.get("candidate") or {}
    objections: list[str] = []
    if not candidate.get("proposition"):
        objections.append("candidate lacks a proposition")
    if candidate.get("confidence", 0.0) > 0.99:
        objections.append("candidate confidence is implausibly certain")
    confidence = max(0.0, 1.0 - 0.2 * len(objections))
    return ChannelResult("channel.independent-critique", True, {"objections": objections},
                         confidence, contradictions=tuple(objections), trace=("critique",))


def _retrieval_grounded(task: dict[str, Any]) -> ChannelResult:
    evidence = _rank_evidence(task, list(task.get("evidence") or []))
    confidence = min(1.0, len(evidence) / max(1, int(task.get("required_evidence", 1))))
    return ChannelResult("channel.retrieval-grounded", bool(evidence),
                         {"grounded_evidence": evidence}, confidence,
                         trace=(f"grounded={len(evidence)}",))


def _simulation_driven(task: dict[str, Any]) -> ChannelResult:
    scenarios = list(task.get("scenarios") or [])
    if not scenarios:
        return ChannelResult("channel.simulation-driven", False, {}, 0.0,
                             contradictions=("no_scenarios",))
    rng = random.Random(int(task.get("seed", 0)))
    outcomes: list[dict[str, Any]] = []
    for scenario in scenarios:
        base = float(scenario.get("base_probability", 0.5))
        count = sum(1 for _ in range(int(scenario.get("trials", 20)))
                    if rng.random() < base)
        outcomes.append({"scenario": scenario.get("id"), "successes": count,
                         "trials": scenario.get("trials", 20),
                         "rate": round(count / max(1, int(scenario.get("trials", 20))), 4)})
    confidence = min(1.0, len(outcomes) / max(1, len(scenarios)))
    return ChannelResult("channel.simulation-driven", True, {"outcomes": outcomes}, confidence,
                         trace=(f"scenarios={len(scenarios)}",))


def _verifier_guided(task: dict[str, Any]) -> ChannelResult:
    candidate = task.get("candidate") or {}
    constraints = task.get("constraints") or {}
    if constraints.get("variables"):
        result = run_engine("reasoning.constraint", {
            "variables": constraints["variables"],
            "domains": constraints["domains"],
            "constraints": constraints["constraints"],
        })
        ok = bool(result.conclusion.get("satisfiable"))
        return ChannelResult("channel.verifier-guided", ok,
                             {"verified_result": candidate, "constraint_check": result.conclusion},
                             float(ok), trace=("constraint_verification",))
    if candidate.get("confidence", 0.0) >= 0.5:
        return ChannelResult("channel.verifier-guided", True, {"verified_result": candidate},
                             candidate.get("confidence", 0.5), trace=("threshold_verification",))
    return ChannelResult("channel.verifier-guided", False, {}, 0.0,
                         contradictions=("candidate_below_confidence_threshold",))


_CHANNEL_DISPATCH = {
    "channel.direct": _direct,
    "channel.parallel-hypotheses": _parallel_hypotheses,
    "channel.sequential-refinement": _sequential_refinement,
    "channel.tree-search": _tree_search,
    "channel.graph-search": _graph_search,
    "channel.multi-agent-debate": _multi_agent_debate,
    "channel.independent-critique": _independent_critique,
    "channel.retrieval-grounded": _retrieval_grounded,
    "channel.simulation-driven": _simulation_driven,
    "channel.verifier-guided": _verifier_guided,
}


def run_channel(channel_id: str, task: dict[str, Any]) -> ChannelResult:
    """Run one registered channel over a task payload."""
    registry = InferenceChannelRegistry()
    registry.spec(channel_id)  # fail closed on unknown identity
    runner = _CHANNEL_DISPATCH.get(channel_id)
    if runner is None:
        raise NotImplementedError(f"no implementation for channel {channel_id}")
    return runner(task)


def digest_of(result: ChannelResult) -> str:
    payload = asdict(result)
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()[:16]
