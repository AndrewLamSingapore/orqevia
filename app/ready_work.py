"""Opt-in, in-process DAG execution for bounded non-inference work.

This module does not start workers or alter the governed inference queue.
Callers supply work functions and persist any outcomes they require.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from contextlib import nullcontext
import os
from threading import Condition, Thread
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
    estimated_ram_mb: int = 0


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
        if isinstance(item.estimated_ram_mb, bool) or not isinstance(item.estimated_ram_mb, int) or item.estimated_ram_mb < 0:
            raise ValueError("estimated RAM must be a nonnegative integer")
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


class ReadyWorkBusy(RuntimeError):
    """The bounded shared ready queue cannot safely admit more work."""


class ReadyWorkScheduler:
    """Shared, bounded lane for non-inference calls across objective requests.

    This does not grant tool or effect authority. Jobs already running cannot be
    preempted; P0 is selected first whenever capacity becomes available. Lower
    lanes age one rank per four dispatches so a sustained P1 stream cannot keep
    P2/P3 queued forever. Resource locks and declared RAM apply across requests.
    """

    def __init__(self, *, max_parallel: int = 3, max_pending: int = 128,
                 memory_budget_mb: int = 8192):
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
               for value in (max_parallel, max_pending, memory_budget_mb)):
            raise ValueError("scheduler limits must be positive integers")
        self.max_parallel = max_parallel
        self.max_pending = max_pending
        self.memory_budget_mb = memory_budget_mb
        self._condition = Condition()
        self._pool = ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="prime-ready")
        self._pending: list[tuple[int, int, WorkItem, Future]] = []
        self._sequence = 0
        self._dispatches = 0
        self._active = 0
        self._used_ram_mb = 0
        self._held_writes: set[str] = set()
        self._closed = False
        self._dispatcher = Thread(target=self._dispatch, name="prime-ready-dispatch", daemon=True)
        self._dispatcher.start()

    def submit(self, item: WorkItem) -> Future:
        if item.kind != "non_inference" or item.priority not in {"P0", "P1", "P2", "P3"}:
            raise ValueError("only P0-P3 non-inference work is eligible")
        if not callable(item.run) or not all(isinstance(x, str) and x.strip() for x in item.writes):
            raise ValueError("invalid ready-work function or write resource")
        if isinstance(item.estimated_ram_mb, bool) or not isinstance(item.estimated_ram_mb, int) or item.estimated_ram_mb < 0:
            raise ValueError("estimated RAM must be a nonnegative integer")
        if item.estimated_ram_mb > self.memory_budget_mb:
            raise ReadyWorkBusy("work exceeds declared RAM budget")
        with self._condition:
            if self._closed:
                raise ReadyWorkBusy("ready-work scheduler is closed")
            if len(self._pending) >= self.max_pending:
                raise ReadyWorkBusy("ready-work queue is full")
            self._sequence += 1
            future = Future()
            self._pending.append((self._sequence, self._dispatches, item, future))
            future.add_done_callback(self._drop_cancelled)
            self._condition.notify_all()
            return future

    def _drop_cancelled(self, result: Future) -> None:
        if not result.cancelled():
            return
        with self._condition:
            self._pending = [entry for entry in self._pending if entry[3] is not result]
            self._condition.notify_all()

    def _rank(self, sequence: int, queued_dispatches: int, item: WorkItem) -> tuple[int, int]:
        if item.owner or item.priority == "P0":
            return (0, sequence)
        age = max(0, self._dispatches - queued_dispatches) // 4
        return (max(1, int(item.priority[1]) - age), sequence)

    def _dispatch(self) -> None:
        while True:
            with self._condition:
                while True:
                    if self._closed and not self._pending and self._active == 0:
                        return
                    if self._active < self.max_parallel:
                        eligible = [entry for entry in self._pending
                                    if not entry[2].writes & self._held_writes
                                    and self._used_ram_mb + entry[2].estimated_ram_mb <= self.memory_budget_mb]
                        if eligible:
                            sequence, queued_dispatches, item, result = min(
                                eligible, key=lambda entry: self._rank(entry[0], entry[1], entry[2]))
                            self._pending.remove((sequence, queued_dispatches, item, result))
                            if not result.set_running_or_notify_cancel():
                                continue
                            self._active += 1
                            self._used_ram_mb += item.estimated_ram_mb
                            self._held_writes.update(item.writes)
                            self._dispatches += 1
                            break
                    self._condition.wait()
            worker = self._pool.submit(item.run)
            worker.add_done_callback(lambda completed, item=item, result=result: self._finish(completed, item, result))

    def _finish(self, worker: Future, item: WorkItem, result: Future) -> None:
        try:
            result.set_result(worker.result())
        except BaseException as exc:
            result.set_exception(exc)
        finally:
            with self._condition:
                self._active -= 1
                self._used_ram_mb -= item.estimated_ram_mb
                self._held_writes.difference_update(item.writes)
                self._condition.notify_all()

    def shutdown(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._dispatcher.join()
        self._pool.shutdown(wait=True)

    def __enter__(self) -> "ReadyWorkScheduler":
        return self

    def __exit__(self, *_: object) -> None:
        self.shutdown()


_shared_scheduler: ReadyWorkScheduler | None = None
_shared_lock = Condition()


def shared_ready_scheduler() -> ReadyWorkScheduler:
    """Create one opt-in scheduler per process; never expand the inference pool."""
    global _shared_scheduler
    with _shared_lock:
        if _shared_scheduler is None:
            def bound(name: str, default: int, maximum: int) -> int:
                try:
                    value = int(os.getenv(name, str(default)))
                except ValueError:
                    value = default
                return max(1, min(maximum, value))
            _shared_scheduler = ReadyWorkScheduler(
                max_parallel=bound("PRIME_READY_WORK_CONCURRENCY", 3, 8),
                max_pending=bound("PRIME_READY_WORK_PENDING", 128, 1024),
                memory_budget_mb=bound("PRIME_READY_WORK_MEMORY_MB", 8192, 32768),
            )
        return _shared_scheduler


def run_ready_work(items: list[WorkItem], *, max_parallel: int = 2,
                   scheduler: ReadyWorkScheduler | None = None) -> dict[str, WorkOutcome]:
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
    if scheduler is None and os.getenv("PRIME_SHARED_READY_WORK_ENABLED", "0") == "1":
        scheduler = shared_ready_scheduler()
    scope = nullcontext(scheduler) if scheduler else ThreadPoolExecutor(
        max_workers=max_parallel, thread_name_prefix="prime-ready")
    with scope as executor:
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
                try:
                    future = executor.submit(item) if scheduler else executor.submit(item.run)
                except ReadyWorkBusy as exc:
                    held_writes.difference_update(item.writes)
                    outcomes[item.id] = WorkOutcome("failed", error=exc)
                    dispatched.add(item.id)
                    continue
                running[future] = item.id
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
