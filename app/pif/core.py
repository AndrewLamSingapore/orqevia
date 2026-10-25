"""Pure, deterministic Markov mathematics and explicitly labelled simulation.

No scheduler, authorization, network access, neural runtime or executable model
deserialization lives here. A horizon counts state-change events, not seconds.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence


EVIDENCE_KINDS = frozenset({"fixture", "simulation", "observational_unclassified", "observed_production"})
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def identifier(value: str) -> str:
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError("invalid stable identifier")
    return value


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO-8601 string with timezone")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc).isoformat()


def integer(value: int, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError("invalid nonnegative integer")
    return value


@dataclass(frozen=True)
class Observation:
    state: str
    timestamp: str
    event_id: str

    def __post_init__(self) -> None:
        identifier(self.state)
        identifier(self.event_id)
        object.__setattr__(self, "timestamp", timestamp(self.timestamp))

    def as_dict(self) -> dict[str, str]:
        return {"state": self.state, "timestamp": self.timestamp, "event_id": self.event_id}


@dataclass(frozen=True)
class History:
    entity_id: str
    observations: tuple[Observation, ...]
    evidence_kind: str = "observational_unclassified"

    def __post_init__(self) -> None:
        identifier(self.entity_id)
        if not isinstance(self.observations, tuple) or not self.observations:
            raise ValueError("history requires an immutable, nonempty observation tuple")
        if self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError("unrecognized evidence kind")
        previous = None
        event_ids = set()
        for row in self.observations:
            if not isinstance(row, Observation):
                raise ValueError("invalid observation")
            if previous is not None and row.timestamp < previous:
                raise ValueError("observations must be chronological")
            if row.event_id in event_ids:
                raise ValueError("duplicate observation event")
            event_ids.add(row.event_id)
            previous = row.timestamp

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "evidence_kind": self.evidence_kind,
            "observations": [row.as_dict() for row in self.observations],
        }


def validate_histories(histories: Iterable[History]) -> tuple[History, ...]:
    rows = tuple(histories)
    entities: set[str] = set()
    events: set[str] = set()
    for row in rows:
        if not isinstance(row, History) or row.entity_id in entities:
            raise ValueError("invalid or duplicate entity history")
        entities.add(row.entity_id)
        for event in row.observations:
            if event.event_id in events:
                raise ValueError("event reused across histories")
            events.add(event.event_id)
    return rows


def distribution(values: Sequence[float], size: int) -> tuple[float, ...]:
    if len(values) != size:
        raise ValueError("probability dimension mismatch")
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 or v > 1 for v in values):
        raise ValueError("invalid probability")
    total = math.fsum(values)
    if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-10):
        raise ValueError("probabilities must sum to one")
    return tuple(v / total for v in values)


@dataclass(frozen=True)
class MarkovModel:
    states: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]
    counts: tuple[tuple[int, ...], ...]
    absorbing_states: tuple[str, ...]
    alpha: float
    observation_start: str | None
    observation_end: str | None
    evidence_digest: str
    evidence_kinds: tuple[str, ...]
    entity_count: int
    allowed_edges: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.states or len(set(self.states)) != len(self.states):
            raise ValueError("states must be nonempty and unique")
        for state in self.states:
            identifier(state)
        n = len(self.states)
        if len(self.matrix) != n or len(self.counts) != n:
            raise ValueError("matrix dimension mismatch")
        if type(self.alpha) not in (int, float) or not math.isfinite(self.alpha) or self.alpha < 0:
            raise ValueError("alpha must be finite and nonnegative")
        for probs, counts in zip(self.matrix, self.counts):
            distribution(probs, n)
            if len(counts) != n or any(type(c) is not int or c < 0 for c in counts):
                raise ValueError("invalid transition counts")
        if not set(self.absorbing_states) <= set(self.states):
            raise ValueError("unknown absorbing state")
        allowed = set(self.allowed_edges)
        if not allowed or any(a not in self.states or b not in self.states for a, b in allowed):
            raise ValueError("invalid transition topology")
        for i, state in enumerate(self.states):
            for j, target in enumerate(self.states):
                if (state, target) not in allowed and (self.matrix[i][j] or self.counts[i][j]):
                    raise ValueError("probability outside permitted topology")
            if state in self.absorbing_states:
                if any(self.matrix[i][j] != float(i == j) for j in range(n)):
                    raise ValueError("absorbing state is not exact")
        if not re.fullmatch(r"[0-9a-f]{64}", self.evidence_digest):
            raise ValueError("invalid evidence digest")
        if not set(self.evidence_kinds) <= EVIDENCE_KINDS:
            raise ValueError("invalid evidence provenance")
        integer(self.entity_count)
        if (self.observation_start is None) != (self.observation_end is None):
            raise ValueError("incomplete observation period")
        if self.observation_start is not None:
            if timestamp(self.observation_start) > timestamp(self.observation_end):
                raise ValueError("invalid observation period")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "orqevia.pif.markov.v1",
            "states": list(self.states),
            "matrix": [list(r) for r in self.matrix],
            "counts": [list(r) for r in self.counts],
            "absorbing_states": list(self.absorbing_states),
            "alpha": self.alpha,
            "observation_start": self.observation_start,
            "observation_end": self.observation_end,
            "evidence_digest": self.evidence_digest,
            "evidence_kinds": list(self.evidence_kinds),
            "entity_count": self.entity_count,
            "allowed_edges": [list(e) for e in self.allowed_edges],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MarkovModel:
        keys = {
            "schema",
            "states",
            "matrix",
            "counts",
            "absorbing_states",
            "alpha",
            "observation_start",
            "observation_end",
            "evidence_digest",
            "evidence_kinds",
            "entity_count",
            "allowed_edges",
        }
        if set(value) != keys or value.get("schema") != "orqevia.pif.markov.v1":
            raise ValueError("unsupported model schema")
        return cls(
            tuple(value["states"]),
            tuple(tuple(r) for r in value["matrix"]),
            tuple(tuple(r) for r in value["counts"]),
            tuple(value["absorbing_states"]),
            value["alpha"],
            value["observation_start"],
            value["observation_end"],
            value["evidence_digest"],
            tuple(value["evidence_kinds"]),
            value["entity_count"],
            tuple(tuple(e) for e in value["allowed_edges"]),
        )

    @property
    def version(self) -> str:
        return digest(self.as_dict())

    @property
    def transition_count(self) -> int:
        return sum(sum(row) for row in self.counts)

    def initial(self, start: str | Mapping[str, float]) -> tuple[float, ...]:
        if isinstance(start, str):
            if start not in self.states:
                raise ValueError("unknown state")
            return tuple(float(state == start) for state in self.states)
        if not isinstance(start, Mapping) or set(start) - set(self.states):
            raise ValueError("invalid initial distribution")
        return distribution([start.get(state, 0.0) for state in self.states], len(self.states))

    def forecast(self, start: str | Mapping[str, float], steps: int) -> dict[str, float]:
        integer(steps)
        current = self.initial(start)
        # Exponentiation avoids a horizon-sized loop. Matrix multiplication is
        # intentionally CPU/stdlib for these small discrete state models.
        power = self.matrix
        exponent = steps
        while exponent:
            if exponent & 1:
                current = distribution(
                    [
                        math.fsum(current[i] * power[i][j] for i in range(len(self.states)))
                        for j in range(len(self.states))
                    ],
                    len(self.states),
                )
            exponent >>= 1
            if exponent:
                power = tuple(
                    distribution(
                        [
                            math.fsum(power[i][k] * power[k][j] for k in range(len(self.states)))
                            for j in range(len(self.states))
                        ],
                        len(self.states),
                    )
                    for i in range(len(self.states))
                )
        return dict(zip(self.states, current))

    def unsupported_states(
        self, start: str | Mapping[str, float], steps: int, minimum_observations: int = 1
    ) -> list[str]:
        """Find reachable unobserved rows before a requested horizon, not after it."""
        integer(steps)
        integer(minimum_observations, minimum=1)
        reachable = {self.states[i] for i, p in enumerate(self.initial(start)) if p > 0}
        unsupported = set()
        seen: set[str] = set()
        for _ in range(min(steps, len(self.states))):
            next_states = set()
            for state in reachable - seen:
                i = self.states.index(state)
                if state not in self.absorbing_states and sum(self.counts[i]) < minimum_observations:
                    unsupported.add(state)
                next_states.update(self.states[j] for j, p in enumerate(self.matrix[i]) if p > 0)
            seen.update(reachable)
            reachable = next_states
            if not reachable - seen:
                break
        return sorted(unsupported)


def estimate_markov(
    histories: Iterable[History],
    *,
    states: Sequence[str],
    absorbing_states: Sequence[str] = (),
    alpha: float = 0.5,
    allowed_edges: Iterable[tuple[str, str]] | None = None,
    since: str | None = None,
    until: str | None = None,
) -> MarkovModel:
    rows = sorted(validate_histories(histories), key=lambda h: h.entity_id)
    names = tuple(states)
    if not names or len(names) != len(set(names)):
        raise ValueError("states must be unique and nonempty")
    for state in names:
        identifier(state)
    absorbing = tuple(sorted(set(absorbing_states)))
    if not set(absorbing) <= set(names):
        raise ValueError("unknown absorbing states")
    if type(alpha) not in (int, float) or not math.isfinite(alpha) or alpha < 0:
        raise ValueError("invalid smoothing alpha")
    edges = (
        set(allowed_edges)
        if allowed_edges is not None
        else {(a, b) for a in names for b in names if a not in absorbing or a == b}
    )
    if any(a not in names or b not in names for a, b in edges):
        raise ValueError("unknown state in topology")
    for state in names:
        if not any(a == state for a, _ in edges):
            raise ValueError("state has no permitted successors")
        if state in absorbing and {b for a, b in edges if a == state} != {state}:
            raise ValueError("absorbing topology has outgoing transition")
    lower = timestamp(since) if since else None
    upper = timestamp(until) if until else None
    if lower and upper and lower > upper:
        raise ValueError("invalid time window")
    counts = [[0 for _ in names] for _ in names]
    retained = []
    observed_times = []
    kinds = set()
    entities = set()
    for history in rows:
        for observation in history.observations:
            if observation.state not in names:
                raise ValueError("unknown observed state")
        for source, target in zip(history.observations, history.observations[1:]):
            if (source.state, target.state) not in edges:
                raise ValueError("observation violates transition topology")
            # Both observations must be in the training window; do not smuggle
            # a pre-window state or post-cutoff outcome into the fit.
            if lower and source.timestamp < lower or upper and target.timestamp > upper:
                continue
            counts[names.index(source.state)][names.index(target.state)] += 1
            retained.append([history.entity_id, history.evidence_kind, source.as_dict(), target.as_dict()])
            observed_times.extend((source.timestamp, target.timestamp))
            kinds.add(history.evidence_kind)
            entities.add(history.entity_id)
    matrix = []
    for i, state in enumerate(names):
        if state in absorbing:
            matrix.append(tuple(float(i == j) for j in range(len(names))))
            continue
        permitted = [j for j, target in enumerate(names) if (state, target) in edges]
        total = sum(counts[i]) + alpha * len(permitted)
        if total:
            row = tuple((counts[i][j] + alpha) / total if j in permitted else 0.0 for j in range(len(names)))
        else:
            # A normalized computational prior is not an evidence-backed row.
            row = tuple(1.0 / len(permitted) if j in permitted else 0.0 for j in range(len(names)))
        matrix.append(row)
    return MarkovModel(
        names,
        tuple(matrix),
        tuple(tuple(r) for r in counts),
        absorbing,
        alpha,
        min(observed_times) if observed_times else None,
        max(observed_times) if observed_times else None,
        digest(retained),
        tuple(sorted(kinds)),
        len(entities),
        tuple(sorted(edges)),
    )


def simulate(
    model: MarkovModel, start: str | Mapping[str, float], *, steps: int, samples: int, seed: int
) -> dict[str, Any]:
    integer(steps)
    integer(samples, minimum=1)
    integer(seed)
    rng = random.Random(seed)
    initial = model.initial(start)
    final = [0] * len(model.states)
    trajectories = []
    for _ in range(samples):
        state = rng.choices(range(len(model.states)), weights=initial, k=1)[0]
        trajectory = [model.states[state]]
        for _ in range(steps):
            state = rng.choices(range(len(model.states)), weights=model.matrix[state], k=1)[0]
            trajectory.append(model.states[state])
        final[state] += 1
        trajectories.append(trajectory)
    frequencies = {state: final[i] / samples for i, state in enumerate(model.states)}
    # Wilson intervals quantify Monte Carlo sampling variation, not model or
    # real-world uncertainty. The latter remains separately unvalidated.
    intervals = {state: list(wilson(final[i], samples)) for i, state in enumerate(model.states)}
    return {
        "seed": seed,
        "samples": samples,
        "trajectories": trajectories,
        "final_distribution": frequencies,
        "analytic_distribution": model.forecast(start, steps),
        "monte_carlo_95pct_intervals": intervals,
        "interval_scope": "MONTE_CARLO_SAMPLING_ONLY",
        "causal_intervention": False,
    }


def wilson(successes: int, observations: int, z: float = 1.959963984540054) -> tuple[float, float]:
    integer(successes)
    integer(observations, minimum=1)
    if successes > observations:
        raise ValueError("successes exceed observations")
    p = successes / observations
    denominator = 1 + z * z / observations
    center = (p + z * z / (2 * observations)) / denominator
    radius = z * math.sqrt(p * (1 - p) / observations + z * z / (4 * observations**2)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def _solve(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> list[float]:
    size = len(rhs)
    augmented = [list(row) + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            raise ValueError("singular system; unique finite solution unsupported")
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        divisor = augmented[col][col]
        augmented[col] = [value / divisor for value in augmented[col]]
        for row in range(size):
            if row != col:
                factor = augmented[row][col]
                augmented[row] = [a - factor * b for a, b in zip(augmented[row], augmented[col])]
    return [row[-1] for row in augmented]


def absorbing_analysis(model: MarkovModel) -> dict[str, Any]:
    absorbing = [
        i for i, state in enumerate(model.states) if all(p == float(i == j) for j, p in enumerate(model.matrix[i]))
    ]
    transient = [i for i in range(len(model.states)) if i not in absorbing]
    if not absorbing:
        return {"status": "NOT_APPLICABLE", "reason": "NO_ABSORBING_STATES"}
    # Every nonabsorbing state must reach absorption; otherwise I-Q is singular
    # and a finite expected absorption time cannot be asserted for all states.
    reachable = set(absorbing)
    for _ in model.states:
        reachable.update(i for i in transient if any(model.matrix[i][j] > 0 for j in reachable))
    if len(reachable) != len(model.states):
        return {"status": "UNAVAILABLE", "reason": "NONABSORBING_CLOSED_CLASS"}
    matrix = [[float(i == j) - model.matrix[i][j] for j in transient] for i in transient]
    try:
        expected = _solve(matrix, [1.0] * len(transient)) if transient else []
        probabilities = {
            model.states[j]: _solve(matrix, [model.matrix[i][j] for i in transient]) if transient else []
            for j in absorbing
        }
    except ValueError:
        return {"status": "UNAVAILABLE", "reason": "NUMERICALLY_SINGULAR_ABSORPTION_SYSTEM"}
    result = {}
    for i, state in enumerate(model.states):
        position = transient.index(i) if i in transient else None
        result[state] = {
            "expected_state_changes_to_absorption": expected[position] if position is not None else 0.0,
            "absorption_probabilities": {
                model.states[j]: min(1.0, max(0.0, probabilities[model.states[j]][position]))
                if position is not None
                else float(i == j)
                for j in absorbing
            },
        }
    return {"status": "AVAILABLE", "states": result}


def stationary_distribution(model: MarkovModel) -> dict[str, Any]:
    # Distinguish a stationary solution from convergence of P^n. A periodic
    # irreducible chain has a unique stationary law but no general pointwise limit.
    size = len(model.states)
    for start in range(size):
        reachable = {start}
        for _ in range(size):
            reachable.update(j for i in tuple(reachable) for j, p in enumerate(model.matrix[i]) if p > 0)
        if len(reachable) != size:
            return {"status": "NOT_APPLICABLE", "reason": "REDUCIBLE_CHAIN_NO_UNIQUE_LAW_ASSERTED"}
    matrix = [[model.matrix[j][i] - float(i == j) for j in range(size)] for i in range(size)]
    matrix[-1] = [1.0] * size
    try:
        solution = _solve(matrix, [0.0] * (size - 1) + [1.0])
        probs = distribution([max(0.0, value) for value in solution], size)
    except ValueError:
        return {"status": "UNAVAILABLE", "reason": "NUMERICALLY_SINGULAR_STATIONARY_SYSTEM"}
    residual = max(abs(math.fsum(probs[i] * model.matrix[i][j] for i in range(size)) - probs[j]) for j in range(size))
    return {
        "status": "AVAILABLE",
        "probabilities": dict(zip(model.states, probs)),
        "residual": residual,
        "limiting_distribution_claimed": False,
    }


def hidden_filter(
    *,
    states: Sequence[str],
    transitions: Sequence[Sequence[float]],
    initial: Sequence[float],
    emissions: Mapping[str, Sequence[float]],
    observations: Sequence[str],
) -> dict[str, Any]:
    """Scaled forward filtering for an explicitly supplied, offline HMM.

    Emission maps are observation -> P(observation | hidden state), and each
    hidden-state emission column must sum to one across all observations.
    There is no fit, calibration, deployment or causal claim in this function.
    """
    names = tuple(states)
    if not names or len(set(names)) != len(names):
        raise ValueError("invalid hidden states")
    for name in names:
        identifier(name)
    size = len(names)
    if len(transitions) != size:
        raise ValueError("invalid transition dimension")
    matrix = [distribution(row, size) for row in transitions]
    belief = distribution(initial, size)
    if not emissions or any(len(row) != size for row in emissions.values()):
        raise ValueError("invalid emission dimension")
    for name in emissions:
        identifier(name)
    for i in range(size):
        distribution([emissions[name][i] for name in emissions], len(emissions))
    log_likelihood = 0.0
    filters = []
    for index, observation in enumerate(observations):
        if observation not in emissions:
            raise ValueError("unknown observation")
        prior = (
            belief
            if index == 0
            else tuple(math.fsum(belief[i] * matrix[i][j] for i in range(size)) for j in range(size))
        )
        weights = [prior[i] * emissions[observation][i] for i in range(size)]
        scale = math.fsum(weights)
        if scale == 0:
            return {
                "status": "IMPOSSIBLE_OBSERVATION",
                "log_likelihood": None,
                "filters": filters,
                "forecasting_quality": "NOT_VALIDATED",
            }
        belief = tuple(w / scale for w in weights)
        log_likelihood += math.log(scale)
        filters.append(dict(zip(names, belief)))
    return {
        "status": "AVAILABLE_OFFLINE",
        "log_likelihood": log_likelihood,
        "filters": filters,
        "posterior": dict(zip(names, belief)),
        "forecasting_quality": "NOT_VALIDATED",
    }
