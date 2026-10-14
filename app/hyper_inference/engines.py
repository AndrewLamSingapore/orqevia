"""Inference engine registry and deterministic engine implementations.

Each engine exposes identity, version, capability tags and an evidence
contract, and returns an :class:`EngineResult` that is always advisory: it can
carry conclusions and confidence but never grants authority or triggers a
consequential tool.

Families that are implemented here use bounded deterministic solvers. Families
whose full guarantee would require a language model are still registered, but
their ``implementation_kind`` is ``language_model_bound`` and their
deterministic fallback is conservative rather than over-confident.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class EngineResult:
    engine_id: str
    ok: bool
    conclusion: dict[str, Any]
    confidence: float
    evidence_ids: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    trace: tuple[str, ...] = ()
    grants_authority: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evidence_contract(inputs: tuple[str, ...], outputs: tuple[str, ...]) -> dict[str, Any]:
    return {"inputs": list(inputs), "outputs": list(outputs), "authority": "advisory_only"}


ENGINE_SPECS: dict[str, dict[str, Any]] = {
    "reasoning.deductive": {
        "name": "Deductive reasoning",
        "version": "1.0.0",
        "family": "deductive",
        "capabilities": ("logical_validity", "rule_application"),
        "implementation_kind": "deterministic",
        "evidence_contract": _evidence_contract(
            ("antecedent", "consequent", "antecedent_true", "consequent_true", "rule"),
            ("conclusion", "valid", "premise_verified"),
        ),
        "cost": 0.0001,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
    "reasoning.inductive": {
        "name": "Inductive reasoning",
        "version": "1.0.0",
        "family": "inductive",
        "capabilities": ("generalization", "sample_evidence"),
        "implementation_kind": "deterministic",
        "evidence_contract": _evidence_contract(
            ("proposition", "observations", "minimum"),
            ("hypothesis", "support", "counterexamples", "uncertainty"),
        ),
        "cost": 0.0001,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
    "reasoning.abductive": {
        "name": "Abductive reasoning",
        "version": "1.0.0",
        "family": "abductive",
        "capabilities": ("best_explanation", "hypothesis_ranking"),
        "implementation_kind": "deterministic",
        "evidence_contract": _evidence_contract(
            ("observations", "hypotheses"),
            ("best_explanation", "ranked_hypotheses"),
        ),
        "cost": 0.0002,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
    "reasoning.causal": {
        "name": "Causal reasoning",
        "version": "1.0.0",
        "family": "causal",
        "capabilities": ("causal_consistency", "path_reasoning"),
        "implementation_kind": "deterministic",
        "evidence_contract": _evidence_contract(
            ("model", "claim"),
            ("consistent", "relation", "path"),
        ),
        "cost": 0.0002,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
    "reasoning.bayesian": {
        "name": "Bayesian reasoning",
        "version": "1.0.0",
        "family": "bayesian",
        "capabilities": ("belief_update", "posterior"),
        "implementation_kind": "deterministic",
        "evidence_contract": _evidence_contract(
            ("prior", "likelihood_positive", "likelihood_negative", "evidence_observed"),
            ("posterior", "evidence_ratio"),
        ),
        "cost": 0.0001,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
    "reasoning.probabilistic": {
        "name": "Probabilistic reasoning",
        "version": "1.0.0",
        "family": "probabilistic",
        "capabilities": ("distribution", "summary_statistics"),
        "implementation_kind": "deterministic",
        "evidence_contract": _evidence_contract(
            ("values", "method"),
            ("mean", "variance", "entropy"),
        ),
        "cost": 0.0001,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
    "reasoning.analogical": {
        "name": "Analogical reasoning",
        "version": "1.0.0",
        "family": "analogical",
        "capabilities": ("similarity", "structure_mapping"),
        "implementation_kind": "deterministic_scoring",
        "evidence_contract": _evidence_contract(
            ("source", "target"),
            ("similarity", "shared_features"),
        ),
        "cost": 0.0001,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
    "reasoning.counterfactual": {
        "name": "Counterfactual reasoning",
        "version": "1.0.0",
        "family": "counterfactual",
        "capabilities": ("minimal_edit", "intervention"),
        "implementation_kind": "deterministic_scoring",
        "evidence_contract": _evidence_contract(
            ("world", "intervention", "query"),
            ("counterfactual_value", "minimal_edits"),
        ),
        "cost": 0.0002,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
    "reasoning.temporal": {
        "name": "Temporal reasoning",
        "version": "1.0.0",
        "family": "temporal",
        "capabilities": ("ordering", "interval_consistency"),
        "implementation_kind": "deterministic",
        "evidence_contract": _evidence_contract(
            ("events",),
            ("consistent", "violations"),
        ),
        "cost": 0.0001,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
    "reasoning.spatial": {
        "name": "Spatial reasoning",
        "version": "1.0.0",
        "family": "spatial",
        "capabilities": ("distance", "containment"),
        "implementation_kind": "deterministic",
        "evidence_contract": _evidence_contract(
            ("points", "relation"),
            ("satisfied", "distance"),
        ),
        "cost": 0.0001,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
    "reasoning.constraint": {
        "name": "Constraint-based reasoning",
        "version": "1.0.0",
        "family": "constraint",
        "capabilities": ("constraint_satisfaction", "unsat_detection"),
        "implementation_kind": "deterministic",
        "evidence_contract": _evidence_contract(
            ("variables", "domains", "constraints"),
            ("satisfiable", "assignment"),
        ),
        "cost": 0.0003,
        "latency_ms": 2,
        "permissions": ("reason.advisory",),
    },
    "reasoning.meta": {
        "name": "Meta-reasoning",
        "version": "1.0.0",
        "family": "meta",
        "capabilities": ("strategy_selection", "uncertainty_governance"),
        "implementation_kind": "deterministic",
        "evidence_contract": _evidence_contract(
            ("objective", "strategies"),
            ("selected_strategy", "alternatives"),
        ),
        "cost": 0.0002,
        "latency_ms": 1,
        "permissions": ("reason.advisory",),
    },
}


class InferenceEngineRegistry:
    """Versioned engine registry with identity/contract validation."""

    def __init__(self, specs: dict[str, dict[str, Any]] | None = None) -> None:
        self.specs = dict(specs or ENGINE_SPECS)
        self._validate()

    def _validate(self) -> None:
        if not self.specs:
            raise ValueError("engine registry cannot be empty")
        seen: set[str] = set()
        for engine_id, spec in self.specs.items():
            if engine_id in seen:
                raise ValueError(f"duplicate engine id: {engine_id}")
            seen.add(engine_id)
            required = {"name", "version", "family", "capabilities", "implementation_kind",
                        "evidence_contract", "cost", "latency_ms", "permissions"}
            if not required <= spec.keys():
                raise ValueError(f"incomplete engine spec: {engine_id}")
            if spec["implementation_kind"] not in {"deterministic", "deterministic_scoring", "language_model_bound"}:
                raise ValueError(f"unknown implementation kind: {engine_id}")
            if any(p not in {"reason.advisory", "reason.internal"} for p in spec["permissions"]):
                raise ValueError(f"engine grants disallowed permission: {engine_id}")

    def ids(self) -> tuple[str, ...]:
        return tuple(self.specs)

    def spec(self, engine_id: str) -> dict[str, Any]:
        try:
            return dict(self.specs[engine_id])
        except KeyError:
            raise KeyError(f"unknown inference engine: {engine_id}") from None

    def capable(self, capabilities: set[str]) -> tuple[str, ...]:
        return tuple(
            engine_id
            for engine_id, spec in self.specs.items()
            if capabilities <= set(spec["capabilities"])
        )


def _require(mapping: dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ValueError("missing required input(s): " + ", ".join(missing))


def _deduce(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "antecedent", "consequent", "rule")
    rule = payload["rule"]
    antecedent_true = payload.get("antecedent_true")
    consequent_true = payload.get("consequent_true")
    valid = False
    if rule == "modus_ponens":
        valid = antecedent_true is True
    elif rule == "modus_tollens":
        valid = consequent_true is False
    elif rule == "affirming_consequent":
        valid = False  # formal fallacy; always invalid as a rule
    elif rule == "denying_antecedent":
        valid = False  # formal fallacy; always invalid as a rule
    else:
        raise ValueError(f"unsupported deductive rule: {rule}")
    conclusion = {
        "conclusion": payload["consequent"] if valid else None,
        "valid": valid,
        "premise_verified": bool(payload.get("premise_evidence", False)),
        "rule": rule,
    }
    confidence = 1.0 if valid else 0.0
    uncertainties = () if valid else ("invalid_rule_application",)
    return EngineResult("reasoning.deductive", True, conclusion, confidence,
                        evidence_ids=tuple(payload.get("evidence_ids", ())),
                        uncertainties=uncertainties, trace=(f"rule={rule}",))


def _induce(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "proposition", "observations")
    observations = payload["observations"]
    minimum = int(payload.get("minimum", 3))
    if minimum < 1:
        raise ValueError("minimum must be positive")
    support = sum(1 for row in observations if row.get("supports") is True)
    counterexamples = sum(1 for row in observations if row.get("supports") is False)
    total = len(observations)
    uncertainties: list[str] = []
    if total < minimum:
        uncertainties.append("insufficient_sample")
    if counterexamples:
        uncertainties.append("counterexamples_present")
    groups = {row.get("group") for row in observations}
    if len(groups) < 2:
        uncertainties.append("distribution_coverage")
    confidence = round(support / total, 4) if total else 0.0
    hypothesis = {
        "proposition": payload["proposition"],
        "support": support,
        "counterexamples": counterexamples,
        "sample_size": total,
    }
    return EngineResult("reasoning.inductive", True, hypothesis, confidence,
                        uncertainties=tuple(uncertainties), trace=(f"n={total}",))


def _abduce(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "observations", "hypotheses")
    observations = list(payload["observations"])
    hypotheses = list(payload["hypotheses"])
    if not hypotheses:
        raise ValueError("abduction requires at least one hypothesis")
    scored: list[tuple[float, dict[str, Any]]] = []
    for hypothesis in hypotheses:
        explains = set(hypothesis.get("explains", ()))
        coverage = len(explains & set(range(len(observations)))) / max(1, len(observations))
        prior = float(hypothesis.get("prior", 0.5))
        if not 0.0 <= prior <= 1.0:
            raise ValueError("hypothesis prior must be within [0,1]")
        simplicity = 1.0 / (1.0 + len(explains))
        score = round(0.5 * coverage + 0.3 * prior + 0.2 * simplicity, 4)
        scored.append((score, dict(hypothesis)))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("id", "")))
    best = scored[0]
    tied = len(scored) > 1 and math.isclose(best[0], scored[1][0], abs_tol=1e-9)
    conclusion = {
        "best_explanation": best[1],
        "ranked_hypotheses": [item for _, item in scored],
        "underdetermined": tied,
    }
    uncertainties = ("underdetermined_explanation",) if tied else ()
    return EngineResult("reasoning.abductive", True, conclusion, best[0],
                        uncertainties=uncertainties, trace=(f"scored={len(scored)}",))


def _causal(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "model", "claim")
    model = payload["model"]
    edges = list(model.get("edges", ()))
    nodes = set(model.get("nodes", ()))
    for edge in edges:
        if edge[0] not in nodes or edge[1] not in nodes:
            raise ValueError("causal edge references an unknown node")
    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in edges:
        adjacency[source].append(target)

    def reaches(start: str, goal: str, seen: set[str]) -> bool:
        if start == goal:
            return True
        for nxt in adjacency.get(start, ()):
            if nxt not in seen:
                if reaches(nxt, goal, seen | {nxt}):
                    return True
        return False

    cause = payload["claim"].get("cause")
    effect = payload["claim"].get("effect")
    relation = None
    if cause and effect:
        direct = (cause, effect) in [tuple(edge) for edge in edges]
        indirect = reaches(cause, effect, {cause}) and not direct
        if direct:
            relation = "direct"
        elif indirect:
            relation = "indirect"
        else:
            relation = "absent"
    conclusion = {"consistent": relation in {"direct", "indirect"}, "relation": relation,
                  "cause": cause, "effect": effect}
    confidence = 1.0 if relation in {"direct", "indirect"} else 0.0
    return EngineResult("reasoning.causal", True, conclusion, confidence,
                        trace=(f"relation={relation}",))


def _bayesian(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "prior", "likelihood_positive", "likelihood_negative", "evidence_observed")
    prior = float(payload["prior"])
    lik_pos = float(payload["likelihood_positive"])
    lik_neg = float(payload["likelihood_negative"])
    observed = bool(payload["evidence_observed"])
    for value in (prior, lik_pos, lik_neg):
        if not 0.0 <= value <= 1.0:
            raise ValueError("bayesian probabilities must be within [0,1]")
    if observed:
        numerator = prior * lik_pos
        denominator = numerator + (1.0 - prior) * lik_neg
        posterior = numerator / denominator if denominator else prior
    else:
        numerator = prior * (1.0 - lik_pos)
        denominator = numerator + (1.0 - prior) * (1.0 - lik_neg)
        posterior = numerator / denominator if denominator else prior
    conclusion = {"posterior": round(posterior, 4), "evidence_observed": observed}
    return EngineResult("reasoning.bayesian", True, conclusion, round(posterior, 4),
                        trace=("bayes_update",))


def _probabilistic(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "values")
    values = [float(value) for value in payload["values"]]
    if not values:
        raise ValueError("probabilistic reasoning requires values")
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    entropy = 0.0
    if min(values) >= 0.0 and abs(sum(values) - 1.0) < 1e-6:
        entropy = -sum(value * math.log(value) for value in values if value > 0)
    conclusion = {"mean": round(mean, 4), "variance": round(variance, 4),
                  "entropy": round(entropy, 4), "sample_size": len(values)}
    confidence = round(1.0 - math.sqrt(min(1.0, variance)), 4)
    return EngineResult("reasoning.probabilistic", True, conclusion, confidence,
                        trace=("summary_statistics",))


def _analogical(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "source", "target")
    source = payload["source"].get("features", payload["source"])
    target = payload["target"].get("features", payload["target"])
    if not isinstance(source, dict) or not isinstance(target, dict):
        raise ValueError("analogical features must be mappings")
    shared = [key for key in source if key in target]
    matched = [key for key in shared if source[key] == target[key]]
    union = set(source) | set(target)
    jaccard = len(shared) / len(union) if union else 0.0
    value_match = len(matched) / len(shared) if shared else 0.0
    similarity = round(0.6 * jaccard + 0.4 * value_match, 4)
    conclusion = {"similarity": similarity, "shared_features": sorted(matched)}
    return EngineResult("reasoning.analogical", True, conclusion, similarity,
                        trace=(f"jaccard={round(jaccard,4)}",))


def _counterfactual(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "world", "intervention", "query")
    world = dict(payload["world"])
    intervention = dict(payload["intervention"])
    query = payload["query"]
    original = world.get(query)
    edits = [var for var in intervention if var in world and world[var] != intervention[var]]
    world.update(intervention)
    value = world.get(query)
    conclusion = {"counterfactual_value": value, "minimal_edits": edits,
                  "original_value": original, "intervened": dict(intervention)}
    confidence = 1.0 if edits else 0.5
    return EngineResult("reasoning.counterfactual", True, conclusion, confidence,
                        trace=(f"edits={len(edits)}",))


def _temporal(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "events")
    events = payload["events"]
    ordering: dict[str, int] = {}
    violations: list[str] = []
    for event in events:
        event_id = event.get("id")
        at = event.get("at")
        before = event.get("before")
        after = event.get("after")
        if at is not None:
            ordering[event_id] = int(at)
    for event in events:
        event_id = event.get("id")
        if event.get("before") in ordering and event_id in ordering:
            if ordering[event_id] >= ordering[event["before"]]:
                violations.append(f"{event_id} must precede {event['before']}")
        if event.get("after") in ordering and event_id in ordering:
            if ordering[event_id] <= ordering[event["after"]]:
                violations.append(f"{event_id} must follow {event['after']}")
    conclusion = {"consistent": not violations, "violations": violations,
                  "ordering": ordering}
    confidence = 0.0 if violations else 1.0
    return EngineResult("reasoning.temporal", True, conclusion, confidence,
                        uncertainties=tuple(violations), trace=("ordering_check",))


def _spatial(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "points", "relation")
    points = {key: tuple(value) for key, value in payload["points"].items()}
    relation = payload["relation"]
    left, right = relation["a"], relation["b"]
    if left not in points or right not in points:
        raise ValueError("spatial relation references an unknown point")
    distance = math.dist(points[left], points[right])
    kind = relation.get("kind", "near")
    threshold = float(relation.get("threshold", 10.0))
    satisfied = False
    if kind == "near":
        satisfied = distance <= threshold
    elif kind == "far":
        satisfied = distance > threshold
    elif kind == "contained":
        center, radius = points[left], threshold
        satisfied = math.dist(points[right], center) <= radius
    else:
        raise ValueError(f"unsupported spatial relation: {kind}")
    conclusion = {"satisfied": satisfied, "distance": round(distance, 4), "kind": kind}
    return EngineResult("reasoning.spatial", True, conclusion, float(satisfied),
                        trace=(f"distance={round(distance,4)}",))


def _constraint(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "variables", "domains", "constraints")
    variables = list(payload["variables"])
    domains = {var: list(payload["domains"][var]) for var in variables}
    constraints = list(payload["constraints"])

    def satisfied(assignment: dict[str, Any], constraint: dict[str, Any]) -> bool:
        values = [assignment[var] for var in constraint["vars"]]
        op = constraint["type"]
        if op == "neq":
            return len(set(values)) == len(values)
        if op == "eq":
            return len(set(values)) == 1
        if op == "lt":
            return values[0] < values[1]
        raise ValueError(f"unsupported constraint type: {op}")

    assignment: dict[str, Any] = {}
    def backtrack(index: int) -> bool:
        if index == len(variables):
            return True
        var = variables[index]
        for value in domains[var]:
            candidate = {**assignment, var: value}
            if all(satisfied(candidate, c) for c in constraints if all(v in candidate for v in c["vars"])):
                assignment[var] = value
                if backtrack(index + 1):
                    return True
                del assignment[var]
        return False

    satisfiable = backtrack(0)
    conclusion = {"satisfiable": satisfiable, "assignment": assignment if satisfiable else None}
    return EngineResult("reasoning.constraint", True, conclusion, float(satisfiable),
                        trace=("backtracking_search",))


def _meta(payload: dict[str, Any]) -> EngineResult:
    _require(payload, "objective", "strategies")
    strategies = list(payload["strategies"])
    if not strategies:
        raise ValueError("meta-reasoning requires at least one strategy")
    alternatives: list[dict[str, Any]] = []
    for strategy in strategies:
        if not strategy.get("available", True):
            continue
        gain = float(strategy.get("expected_information_gain", 0.0))
        cost = float(strategy.get("cost", 1.0))
        if cost <= 0:
            raise ValueError("strategy cost must be positive")
        score = gain / cost
        alternatives.append({"name": strategy["name"], "score": round(score, 4),
                             "requires": strategy.get("requires", ())})
    alternatives.sort(key=lambda item: (-item["score"], item["name"]))
    selected = alternatives[0] if alternatives else None
    conclusion = {"selected_strategy": selected, "alternatives": alternatives}
    confidence = round(min(1.0, selected["score"]), 4) if selected else 0.0
    uncertainties = ("no_available_strategy",) if not selected else ()
    return EngineResult("reasoning.meta", True, conclusion, confidence,
                        uncertainties=uncertainties, trace=("strategy_selection",))


_DISPATCH: dict[str, Callable[[dict[str, Any]], EngineResult]] = {
    "reasoning.deductive": _deduce,
    "reasoning.inductive": _induce,
    "reasoning.abductive": _abduce,
    "reasoning.causal": _causal,
    "reasoning.bayesian": _bayesian,
    "reasoning.probabilistic": _probabilistic,
    "reasoning.analogical": _analogical,
    "reasoning.counterfactual": _counterfactual,
    "reasoning.temporal": _temporal,
    "reasoning.spatial": _spatial,
    "reasoning.constraint": _constraint,
    "reasoning.meta": _meta,
}


def run_engine(engine_id: str, payload: dict[str, Any]) -> EngineResult:
    """Run one registered engine with a validated evidence contract."""
    registry = InferenceEngineRegistry()
    registry.spec(engine_id)  # fail closed on unknown identity
    runner = _DISPATCH.get(engine_id)
    if runner is None:
        raise NotImplementedError(f"no deterministic implementation for {engine_id}")
    result = runner(payload)
    return result
