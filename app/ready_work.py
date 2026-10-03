"""Opt-in, in-process DAG execution for bounded non-inference work.

This module does not start workers or alter the governed inference queue.
Callers supply work functions and persist any outcomes they require.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Callable, Literal


@dataclass(frozen=True)
class WorkItem:
    id: str
    run: Callable[[], object] = field(repr=False, compare=False)
    dependencies: frozenset[str] = frozenset()
    writes: frozenset[str] = frozenset()
    owner: bool = False
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    kind: Literal["non_inference"] = "non_inference"


@dataclass(frozen=True)
class WorkOutcome:
    status: Literal["completed", "failed", "blocked"]
    value: object = None
    error: BaseException | None = None


def _validate(items: list[WorkItem], max_parallel: int) -> dict[str, WorkItem]:
    if isinstance(max_parallel, bool) or not isinstance(max_parallel, int) or max_parallel < 1:
        raise ValueError("max_parallel must be a positive integer")
    by_id: dict[str, WorkItem] = {}
    for item in items:
        if not item.id or item.id in by_id:
            raise ValueError("work ids must be nonempty and unique")
        if item.kind != "non_inference":
            raise ValueError("inference work is not eligible for ready-work execution")
        if item.priority not in {"P0", "P1", "P2", "P3"}:
            raise ValueError("priority must be P0, P1, P2, or P3")
        if not callable(item.run):
            raise ValueError("work function must be callable")
        if not all(isinstance(resource, str) and resource.strip() for resource in item.writes):
            raise ValueError("write resources must be nonempty strings")
        by_id[item.id] = item
    for item in items:
        if item.id in item.dependencies or not item.dependencies <= by_id.keys():
            raise ValueError(f"invalid dependencies for {item.id}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(work_id: str) -> None:
        if work_id in visiting:
            raise ValueError("work graph contains a cycle")
        if work_id in visited:
            return
        visiting.add(work_id)
        for dependency in by_id[work_id].dependencies:
            visit(dependency)
        visiting.remove(work_id)
        visited.add(work_id)

    for work_id in by_id:
        visit(work_id)
    return by_id


def run_ready_work(items: list[WorkItem], *, max_parallel: int = 2) -> dict[str, WorkOutcome]:
    """Run independent work concurrently, returning an outcome for every item.

    Ready work is ordered by P0 through P3, with an owner fast lane and one
    priority boost after four scheduling rounds deferred. Aging never outranks
    P0 owner work. A write resource is held only during the
    corresponding function call. A failed item blocks its descendants while
    unrelated branches continue. No automatic retry occurs.
    """
    by_id = _validate(items, max_parallel)
    order = {item.id: index for index, item in enumerate(items)}
    outcomes: dict[str, WorkOutcome] = {}
    running = {}
    held_writes: set[str] = set()
    deferred: dict[str, int] = {item.id: 0 for item in items}
    with ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="prime-ready") as executor:
        while len(outcomes) < len(items):
            for item in items:
                if item.id in outcomes or item.id in running.values():
                    continue
                if any(outcomes.get(dep, WorkOutcome("completed")).status in {"failed", "blocked"}
                       for dep in item.dependencies):
                    outcomes[item.id] = WorkOutcome("blocked")
            ready = sorted(
                (item for item in items
                 if item.id not in outcomes and item.id not in running.values()
                 and all(outcomes.get(dep, WorkOutcome("blocked")).status == "completed"
                         for dep in item.dependencies)),
                key=lambda item: (
                    0 if item.owner or item.priority == "P0" else
                    max(1, int(item.priority[1]) - deferred[item.id] // 4),
                    not item.owner,
                    order[item.id],
                ),
            )
            dispatched: set[str] = set()
            for item in ready:
                if len(running) >= max_parallel:
                    break
                if item.writes & held_writes:
                    continue
                held_writes.update(item.writes)
                running[executor.submit(item.run)] = item.id
                dispatched.add(item.id)
            for item in ready:
                if item.id not in dispatched:
                    deferred[item.id] += 1
            if not running:
                # Validation excludes cycles, so this can only follow blocked ancestors.
                continue
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                work_id = running.pop(future)
                held_writes.difference_update(by_id[work_id].writes)
                try:
                    outcomes[work_id] = WorkOutcome("completed", future.result())
                except Exception as exc:
                    outcomes[work_id] = WorkOutcome("failed", error=exc)
    return outcomes
