from threading import Event, Lock
from time import monotonic_ns, sleep

import pytest

from app.ready_work import WorkItem, run_ready_work


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


@pytest.mark.parametrize("items", [
    [WorkItem("a", lambda: None, frozenset({"missing"}))],
    [WorkItem("a", lambda: None, frozenset({"b"})), WorkItem("b", lambda: None, frozenset({"a"}))],
    [WorkItem("a", lambda: None), WorkItem("a", lambda: None)],
    [WorkItem("a", lambda: None, kind="inference")],
    [WorkItem("a", lambda: None, priority="P9")],
])
def test_invalid_graph_or_inference_rejected_before_execution(items):
    with pytest.raises(ValueError):
        run_ready_work(items)
