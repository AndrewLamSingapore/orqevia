"""Interoperable intelligence matrix structures.

Lightweight, in-memory logical structures for relational evidence, vector
retrieval, knowledge graphs, temporal records, causal models, spatial
relationships, agent capabilities, tool compatibility, authority/risk,
evidence provenance, confidence/uncertainty and operational state. These reuse
plain Python containers rather than introducing standalone databases.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable


class RelationalMatrix:
    def __init__(self, rows: Iterable[dict[str, Any]] = ()) -> None:
        self.rows = list(rows)

    def add(self, row: dict[str, Any]) -> None:
        if not isinstance(row, dict):
            raise ValueError("relational row must be a mapping")
        self.rows.append(dict(row))

    def query(self, **filters: Any) -> list[dict[str, Any]]:
        return [row for row in self.rows if all(row.get(key) == value for key, value in filters.items())]


class VectorStore:
    def __init__(self, vectors: dict[str, list[float]] | None = None) -> None:
        self.vectors = dict(vectors or {})

    def put(self, key: str, vector: list[float]) -> None:
        if not vector:
            raise ValueError("vector cannot be empty")
        self.vectors[key] = [float(value) for value in vector]

    def _cosine(self, left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        norm_l = math.sqrt(sum(a * a for a in left))
        norm_r = math.sqrt(sum(b * b for b in right))
        if norm_l == 0 or norm_r == 0:
            return 0.0
        return dot / (norm_l * norm_r)

    def search(self, query: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        scored = sorted(
            ((key, self._cosine(query, vector)) for key, vector in self.vectors.items()),
            key=lambda pair: -pair[1],
        )
        return scored[:top_k]


class KnowledgeGraph:
    def __init__(self) -> None:
        self.adjacency: dict[str, list[str]] = {}

    def add_edge(self, source: str, target: str) -> None:
        self.adjacency.setdefault(source, []).append(target)
        self.adjacency.setdefault(target, [])

    def neighbors(self, node: str) -> list[str]:
        return list(self.adjacency.get(node, ()))

    def path(self, start: str, goal: str) -> list[str] | None:
        queue = [(start, [start])]
        seen = {start}
        while queue:
            node, trail = queue.pop(0)
            if node == goal:
                return trail
            for neighbor in self.adjacency.get(node, ()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, trail + [neighbor]))
        return None


class TemporalRecords:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def add(self, record_id: str, at: int, value: Any) -> None:
        self.records.append({"id": record_id, "at": at, "value": value})

    def between(self, start: int, end: int) -> list[dict[str, Any]]:
        return [r for r in self.records if start <= r["at"] <= end]

    def ordered_ids(self) -> list[str]:
        return [r["id"] for r in sorted(self.records, key=lambda r: r["at"])]


class CausalModel:
    def __init__(self, edges: Iterable[tuple[str, str]] = ()) -> None:
        self.edges = set(edges)
        self.nodes = {node for edge in self.edges for node in edge}

    def add_edge(self, source: str, target: str) -> None:
        if source == target:
            raise ValueError("causal self-loop is not allowed")
        self.edges.add((source, target))
        self.nodes.update((source, target))

    def acyclic(self) -> bool:
        adjacency: dict[str, list[str]] = {node: [] for node in self.nodes}
        for source, target in self.edges:
            adjacency[source].append(target)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return False
            if node in visited:
                return True
            visiting.add(node)
            for neighbor in adjacency[node]:
                if not visit(neighbor):
                    return False
            visiting.remove(node)
            visited.add(node)
            return True

        return all(visit(node) for node in self.nodes)

    def descendants(self, node: str) -> set[str]:
        adjacency: dict[str, list[str]] = {n: [] for n in self.nodes}
        for source, target in self.edges:
            adjacency[source].append(target)
        found: set[str] = set()
        stack = [node]
        while stack:
            current = stack.pop()
            for child in adjacency.get(current, ()):
                if child not in found:
                    found.add(child)
                    stack.append(child)
        return found


class SpatialIndex:
    def __init__(self) -> None:
        self.points: dict[str, tuple[float, float]] = {}

    def add(self, key: str, x: float, y: float) -> None:
        self.points[key] = (float(x), float(y))

    def nearest(self, x: float, y: float, k: int = 1) -> list[tuple[str, float]]:
        if k < 1:
            raise ValueError("k must be positive")
        scored = sorted(
            ((key, math.dist((x, y), point)) for key, point in self.points.items()),
            key=lambda pair: pair[1],
        )
        return scored[:k]


class CapabilityMatrix:
    def __init__(self, agents: dict[str, dict[str, Any]] | None = None) -> None:
        self.agents = {key: dict(value) for key, value in (agents or {}).items()}

    def add(self, agent_id: str, capabilities: set[str], authority: str = "advisory") -> None:
        self.agents[agent_id] = {"capabilities": set(capabilities), "authority": authority}

    def capable(self, capability: str) -> list[str]:
        return sorted(
            agent for agent, record in self.agents.items()
            if capability in record.get("capabilities", set())
        )

    def profile(self, agent_id: str) -> dict[str, Any]:
        record = self.agents.get(agent_id)
        if record is None:
            raise KeyError(f"unknown agent: {agent_id}")
        return {"agent_id": agent_id, "capabilities": sorted(record["capabilities"]),
                "authority": record["authority"]}


class ToolCompatibilityMatrix:
    def __init__(self) -> None:
        self.rows: dict[str, set[str]] = {}

    def add(self, tool_id: str, required_capabilities: set[str]) -> None:
        self.rows[tool_id] = set(required_capabilities)

    def compatible(self, tool_id: str, capabilities: set[str]) -> bool:
        return self.rows.get(tool_id, set()) <= set(capabilities)


class AuthorityRiskMatrix:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def add(self, agent_id: str, authority: str, risk: str) -> None:
        self.rows[agent_id] = {"authority": authority, "risk": risk}

    def get(self, agent_id: str) -> dict[str, Any]:
        if agent_id not in self.rows:
            raise KeyError(f"unknown agent: {agent_id}")
        return dict(self.rows[agent_id])


class ProvenanceLedger:
    """Append-only, hash-chained provenance ledger."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self._last_hash = ""

    def add(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not kind or not isinstance(payload, dict):
            raise ValueError("provenance entry requires kind and payload")
        body = repr({"kind": kind, "payload": payload, "prev": self._last_hash})
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        entry = {"kind": kind, "payload": payload, "hash": digest, "prev_hash": self._last_hash}
        self.entries.append(entry)
        self._last_hash = digest
        return dict(entry)

    def head_hash(self) -> str:
        return self._last_hash

    def verify(self) -> bool:
        previous = ""
        for entry in self.entries:
            body = repr({"kind": entry["kind"], "payload": entry["payload"], "prev": previous})
            if hashlib.sha256(body.encode("utf-8")).hexdigest() != entry["hash"]:
                return False
            if entry["prev_hash"] != previous:
                return False
            previous = entry["hash"]
        return True


class ConfidenceStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def put(self, key: str, confidence: float, uncertainty: float) -> None:
        if not 0.0 <= confidence <= 1.0 or not 0.0 <= uncertainty <= 1.0:
            raise ValueError("confidence and uncertainty must be within [0,1]")
        self.rows[key] = {"confidence": confidence, "uncertainty": uncertainty}

    def get(self, key: str) -> dict[str, Any]:
        if key not in self.rows:
            raise KeyError(f"unknown confidence key: {key}")
        return dict(self.rows[key])


class OperationalState:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def set(self, key: str, state: str, detail: dict[str, Any] | None = None) -> None:
        self.rows[key] = {"state": state, "detail": dict(detail or {})}

    def get(self, key: str) -> dict[str, Any]:
        if key not in self.rows:
            raise KeyError(f"unknown operational key: {key}")
        return dict(self.rows[key])
