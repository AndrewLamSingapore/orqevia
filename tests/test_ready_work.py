from threading import Event, Lock
from time import monotonic_ns, sleep

import pytest

from app.ready_work import ReadyWorkBusy, ReadyWorkScheduler, WorkItem, run_ready_work


def test_owner_dispatches_first_and_dependencies_gate_work():
    calls = []
    items = [
        WorkItem("ordinary", lambda: calls.append("ordinary")),
        WorkItem("child", lambda: calls.append("child"), frozenset({"owner"})),
        WorkItem("owner", lambda: calls.append("owner"), owner=True),
    ]
    result = run_ready_work(items, max_parallel=1)
    assert calls == ["owner", "ordinary", "child"]
    assert all(outcome.status == "completed" for outcome in result.values())


def test_explicit_priority_and_owner_fast_lane():
    calls = []
    items = [
        WorkItem("p3", lambda: calls.append("p3"), priority="P3"),
        WorkItem("p1", lambda: calls.append("p1"), priority="P1"),
        WorkItem("p0", lambda: calls.append("p0"), priority="P0"),
        WorkItem("owner", lambda: calls.append("owner"), owner=True, priority="P0"),
        WorkItem("p2", lambda: calls.append("p2"), priority="P2"),
    ]
    run_ready_work(items, max_parallel=1)
    assert calls == ["owner", "p0", "p1", "p2", "p3"]


def test_independent_work_overlaps_with_bounded_capacity():
    entered = Event()
    release = Event()
    overlap = Event()
    active = 0
    peak = 0
    intervals = []
    lock = Lock()

    def work():
        nonlocal active, peak
        start = monotonic_ns()
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                overlap.set()
        entered.set()
        release.wait(2)
        end = monotonic_ns()
        with lock:
            active -= 1
            intervals.append((start, end))

    from threading import Thread
    result = {}
    thread = Thread(target=lambda: result.update(run_ready_work(
        [WorkItem(str(i), work) for i in range(3)], max_parallel=2)))
    thread.start()
    assert entered.wait(2)
    assert overlap.wait(2)
    sleep(0.02)
    release.set()
    thread.join(3)
    assert not thread.is_alive()
    assert peak == 2
    # An earlier suite may coarsen/mock the monotonic clock on Windows; the
    # active==2 event and peak assertion independently prove actual overlap.
    assert max(start for start, _ in intervals[:2]) <= min(end for _, end in intervals[:2])
    assert len(result) == 3


def test_aging_prevents_low_priority_starvation():
    calls = []
    items = [WorkItem("low", lambda: calls.append("low"), priority="P3")]
    # Fairness applies beneath the protected P0 owner lane.
    items += [WorkItem(f"high{i}", lambda i=i: calls.append(f"high{i}"), priority="P1")
              for i in range(10)]
    run_ready_work(items, max_parallel=1)
    assert calls.index("low") < len(calls) - 1


def test_write_locks_are_narrow_and_failure_isolated():
    calls = []

    def fail():
        raise RuntimeError("expected")

    result = run_ready_work([
        WorkItem("failed", fail, writes=frozenset({"file:a"})),
        WorkItem("dependent", lambda: calls.append("bad"), frozenset({"failed"})),
        WorkItem("unrelated", lambda: calls.append("good"), writes=frozenset({"file:b"})),
    ])
    assert [result[k].status for k in ("failed", "dependent", "unrelated")] == [
        "failed", "blocked", "completed"]
    assert calls == ["good"]


def test_same_resource_waits_while_distinct_resource_runs():
    from threading import Thread

    first_started = Event()
    release_first = Event()
    distinct_started = Event()
    conflicting_started = Event()
    result = {}

    def first():
        first_started.set()
        assert release_first.wait(2)

    thread = Thread(target=lambda: result.update(run_ready_work([
        WorkItem("first", first, writes=frozenset({"file:a"}), owner=True),
        WorkItem("conflicting", conflicting_started.set, writes=frozenset({"file:a"})),
        WorkItem("distinct", distinct_started.set, writes=frozenset({"file:b"})),
    ], max_parallel=2)))
    thread.start()
    assert first_started.wait(2)
    assert distinct_started.wait(2)
    assert not conflicting_started.is_set()
    release_first.set()
    thread.join(3)
    assert not thread.is_alive()
    assert conflicting_started.is_set()
    assert all(outcome.status == "completed" for outcome in result.values())


def test_shared_scheduler_orders_owner_across_requests_after_capacity_release():
    started = Event()
    release = Event()
    order = []

    def occupied():
        started.set()
        assert release.wait(2)

    with ReadyWorkScheduler(max_parallel=1) as scheduler:
        running = scheduler.submit(WorkItem("running", occupied, priority="P2"))
        assert started.wait(2)
        low = scheduler.submit(WorkItem("low", lambda: order.append("low"), priority="P3"))
        owner = scheduler.submit(WorkItem("owner", lambda: order.append("owner"), owner=True, priority="P0"))
        release.set()
        running.result(2)
        owner.result(2)
        low.result(2)
    assert order == ["owner", "low"]


def test_shared_scheduler_releases_capacity_after_failure_and_isolates_write_resource():
    started = Event()
    release = Event()
    conflicting = Event()
    distinct = Event()

    def fail_after_release():
        started.set()
        assert release.wait(2)
        raise RuntimeError("expected")

    with ReadyWorkScheduler(max_parallel=2) as scheduler:
        first = scheduler.submit(WorkItem("first", fail_after_release, writes=frozenset({"file:a"})))
        assert started.wait(2)
        blocked = scheduler.submit(WorkItem("blocked", conflicting.set, writes=frozenset({"file:a"})))
        other = scheduler.submit(WorkItem("other", distinct.set, writes=frozenset({"file:b"})))
        assert distinct.wait(2)
        assert not conflicting.is_set()
        release.set()
        with pytest.raises(RuntimeError, match="expected"):
            first.result(2)
        blocked.result(2)
        other.result(2)
    assert conflicting.is_set()


def test_shared_scheduler_declared_memory_and_pending_bounds():
    started = Event()
    release = Event()

    def occupied():
        started.set()
        assert release.wait(2)

    with ReadyWorkScheduler(max_parallel=1, max_pending=1, memory_budget_mb=100) as scheduler:
        first = scheduler.submit(WorkItem("first", occupied, estimated_ram_mb=80))
        assert started.wait(2)
        second = scheduler.submit(WorkItem("second", lambda: None, estimated_ram_mb=80))
        with pytest.raises(ReadyWorkBusy, match="full"):
            scheduler.submit(WorkItem("third", lambda: None))
        with pytest.raises(ReadyWorkBusy, match="RAM budget"):
            scheduler.submit(WorkItem("too-big", lambda: None, estimated_ram_mb=101))
        release.set()
        first.result(2)
        second.result(2)


def test_shared_scheduler_ages_lower_lanes_without_displacing_owner():
    started = Event()
    release = Event()
    calls = []

    def occupied():
        started.set()
        assert release.wait(2)

    with ReadyWorkScheduler(max_parallel=1) as scheduler:
        first = scheduler.submit(WorkItem("first", occupied))
        assert started.wait(2)
        low = scheduler.submit(WorkItem("low", lambda: calls.append("low"), priority="P3"))
        high = [scheduler.submit(WorkItem(f"high-{i}", lambda i=i: calls.append(f"high-{i}"),
                                          priority="P1")) for i in range(10)]
        owner = scheduler.submit(WorkItem("owner", lambda: calls.append("owner"),
                                          owner=True, priority="P0"))
        release.set()
        first.result(2)
        owner.result(2)
        low.result(2)
        for task in high:
            task.result(2)
    assert calls[0] == "owner"
    assert calls.index("low") < len(calls) - 1


def test_shared_scheduler_cancelled_pending_work_never_executes_or_holds_capacity():
    started = Event()
    release = Event()
    calls = []

    def occupied():
        started.set()
        assert release.wait(2)

    with ReadyWorkScheduler(max_parallel=1, max_pending=1) as scheduler:
        first = scheduler.submit(WorkItem("first", occupied))
        assert started.wait(2)
        cancelled = scheduler.submit(WorkItem("cancelled", lambda: calls.append("bad")))
        assert cancelled.cancel()
        next_work = scheduler.submit(WorkItem("next", lambda: calls.append("next")))
        release.set()
        first.result(2)
        next_work.result(2)
    assert calls == ["next"]


def test_ready_work_can_use_shared_scheduler_without_cross_request_inference():
    with ReadyWorkScheduler(max_parallel=2) as scheduler:
        result = run_ready_work([WorkItem("a", lambda: "done")], scheduler=scheduler)
    assert result["a"].status == "completed"
    assert result["a"].value == "done"


@pytest.mark.parametrize("items", [
    [WorkItem("a", lambda: None, frozenset({"missing"}))],
    [WorkItem("a", lambda: None, frozenset({"b"})), WorkItem("b", lambda: None, frozenset({"a"}))],
    [WorkItem("a", lambda: None), WorkItem("a", lambda: None)],
    [WorkItem("a", lambda: None, kind="inference")],
    [WorkItem("a", lambda: None, priority="P9")],
    [WorkItem("a", lambda: None, estimated_ram_mb=-1)],
])
def test_invalid_graph_or_inference_rejected_before_execution(items):
    with pytest.raises(ValueError):
        run_ready_work(items)
