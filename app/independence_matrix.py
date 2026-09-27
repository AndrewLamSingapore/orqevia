"""Isolated dependency-loss classification for Supreme Independence evidence."""

from __future__ import annotations

from dataclasses import dataclass


STATES = frozenset({"UNCHANGED", "DEGRADED", "DEFERRED", "FAILED"})
COMPONENTS = (
    "identity", "authority", "registry", "memory", "queues", "orchestration",
    "local_inference", "local_retrieval", "local_jarvis_lan",
)


@dataclass(frozen=True)
class DependencyScenario:
    name: str
    results: dict[str, str]
    physical_black_start: bool = False

    def validate(self) -> None:
        if set(self.results) != set(COMPONENTS):
            raise ValueError("scenario must classify every independence component")
        if any(value not in STATES for value in self.results.values()):
            raise ValueError("unknown independence state")
        if self.physical_black_start:
            raise ValueError("physical Black Start evidence cannot be manufactured by simulation")


def scenario(name: str, **overrides: str) -> DependencyScenario:
    results = {component: "UNCHANGED" for component in COMPONENTS}
    unknown = set(overrides) - set(COMPONENTS)
    if unknown:
        raise ValueError("unknown independence components")
    results.update(overrides)
    item = DependencyScenario(name, results)
    item.validate()
    return item


def dependency_loss_matrix() -> tuple[DependencyScenario, ...]:
    return (
        scenario("cloud_ai_unavailable"),
        scenario("github_unavailable", queues="DEFERRED"),
        scenario("preferred_local_model_unavailable", local_inference="DEGRADED"),
        scenario("rag_unavailable", local_retrieval="DEGRADED"),
        scenario("optional_tool_unavailable", orchestration="DEGRADED"),
        scenario("internet_unavailable", queues="DEFERRED"),
    )
