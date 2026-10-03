"""Offline registry and logical concurrency proof; no model or service calls."""

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, Lock
from time import perf_counter, sleep

import pytest

from app.action_records import ActionLedger, ActionRecord, DirectExecutor
from app.agent_registry import (
    agent_record,
    load_agent_registry,
    may_delegate,
    orchestrator_id,
    responsibility_owner,
)
from app.agent_runtime import AgentAuthorityRuntime


AGENTS = sorted(load_agent_registry()["agents"], key=lambda agent: agent["id"])


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent["id"])
def test_each_registry_identity_has_bounded_contract_and_authorized_path(agent, tmp_path):
    agent_id = agent["id"]
    record = agent_record(agent_id)
    assert record["immutable_id"] == record["id"] == agent_id
    assert record["status"] == "registered" and record["model"] == "unassigned"
    assert record["input_contract"]["required"] == ["objective", "context", "data_classification"]
    assert "LOCAL_ONLY" in record["input_contract"]["data_classification"]
    assert set(record["input_contract"]["capability_inputs"]) == {
        item["id"].removeprefix("responsibility.") for item in record["responsibilities"]
    }
    assert set(record["output_contract"]["required"]) == {
        "agent_id", "status", "result", "uncertainty", "proposed_actions"
    }
    assert "completed" in record["output_contract"]["status"]
    assert set(record["output_contract"]["capability_outputs"]) == set(
        record["input_contract"]["capability_inputs"]
    )
    assert record["tap_relationship"]["delegation_transfers_authority"] is False
    assert record["compute_requirements"]["physical_slot_claim"] == "scheduler only"
    for capability in record["capability_requirements"]:
        assert responsibility_owner(capability) == agent_id

    path = [agent_id] if record["can_delegate"] else [record["reports_to"], agent_id]
    assert may_delegate(orchestrator_id(), path[0], depth=1)
    if len(path) == 2:
        assert may_delegate(path[0], path[1], depth=2)
        assert not may_delegate(orchestrator_id(), path[1], depth=1)
    runtime = AgentAuthorityRuntime(tmp_path / f"{agent_id}.db")
    trace_id = runtime.begin_path(path)
    events = list(reversed(runtime.recent(2)))
    assert [event["target_agent"] for event in events] == path
    assert all(event["allowed"] == 1 for event in events)
    assert all(event["trace_id"] == trace_id for event in events)


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent["id"])
def test_each_identity_send_execute_result_is_attributed(agent, tmp_path):
    """Send a deterministic local task through authority and action records."""
    agent_id = agent["id"]
    capability = agent["capability_requirements"][0]
    path = [agent_id] if agent["can_delegate"] else [agent["reports_to"], agent_id]
    runtime = AgentAuthorityRuntime(tmp_path / "authority.db")
    trace_id = runtime.begin_path(path)
    ledger_path = tmp_path / "actions.jsonl"
    ledger = ActionLedger(ledger_path)
    action = ActionRecord(
        task_id=trace_id,
        agent_id=agent_id,
        action_type="offline.fake.execute",
        tool="deterministic-local-fake",
        parent_agent=path[0] if len(path) == 2 else orchestrator_id(),
    )

    def fake_operation():
        assert responsibility_owner(capability) == agent_id
        return {
            "agent_id": agent_id,
            "status": "completed",
            "result": f"deterministic:{agent_id}:{capability}",
            "uncertainty": "none in fake task",
            "proposed_actions": [],
        }

    try:
        result = DirectExecutor(ledger).execute(action, fake_operation)
    finally:
        assert ledger.close()
    assert set(result) == set(agent["output_contract"]["required"])
    assert result["agent_id"] == agent_id
    assert result["status"] in agent["output_contract"]["status"]
    assert result["result"] == f"deterministic:{agent_id}:{capability}"
    recorded = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    assert [event["phase"] for event in recorded] == ["started", "completed"]
    assert all(event["task_id"] == trace_id and event["agent_id"] == agent_id for event in recorded)
    assert recorded[-1]["success"] is True
    assert recorded[-1]["result_summary"]["output_sha256"]


@pytest.mark.parametrize("width", [2, 4, 8, 21])
def test_fake_tool_tasks_overlap_and_keep_identity_boundaries(width):
    """Barrier proves simultaneous logical occupancy without timing assumptions."""
    agents = AGENTS[:width]
    barrier = Barrier(width, timeout=10)
    lock = Lock()
    in_flight = 0
    peak = 0

    def fake_tool(agent):
        nonlocal in_flight, peak
        agent_id = agent["id"]
        capability = agent["capability_requirements"][0]
        assert responsibility_owner(capability) == agent_id
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        try:
            barrier.wait()
            return {
                "agent_id": agent_id,
                "status": "completed",
                "result": f"deterministic:{agent_id}:{capability}",
                "uncertainty": "none in fake task",
                "proposed_actions": [],
            }
        finally:
            with lock:
                in_flight -= 1

    with ThreadPoolExecutor(max_workers=width) as executor:
        outputs = list(executor.map(fake_tool, agents))
    assert peak == width
    assert in_flight == 0
    assert {output["agent_id"] for output in outputs} == {agent["id"] for agent in agents}
    for output in outputs:
        record = agent_record(output["agent_id"])
        assert set(output) == set(record["output_contract"]["required"])
        assert output["status"] in record["output_contract"]["status"]
        assert output["result"].startswith(f"deterministic:{output['agent_id']}:")


def benchmark_fake_tools(width: int, duration_seconds: float = 0.05) -> dict:
    """Measure independent, fixed-duration fake I/O jobs on a monotonic clock."""
    agents = AGENTS[:width]

    def job(agent):
        started = perf_counter()
        sleep(duration_seconds)
        ended = perf_counter()
        return {"agent_id": agent["id"], "start": started, "end": ended}

    serial_start = perf_counter()
    serial = [job(agent) for agent in agents]
    serial_wall = perf_counter() - serial_start
    parallel_start = perf_counter()
    with ThreadPoolExecutor(max_workers=width) as executor:
        parallel = list(executor.map(job, agents))
    parallel_wall = perf_counter() - parallel_start
    intervals = sorted((item["start"], item["end"]) for item in parallel)
    max_overlap = max(
        sum(start <= probe < end for start, end in intervals)
        for probe, _ in intervals
    )
    origin = parallel_start
    return {
        "width": width,
        "fake_job_seconds": duration_seconds,
        "serial_wall_ms": round(serial_wall * 1000, 3),
        "parallel_wall_ms": round(parallel_wall * 1000, 3),
        "speedup": round(serial_wall / parallel_wall, 3),
        "max_timestamp_overlap": max_overlap,
        "parallel_intervals_ms": [
            {"agent_id": item["agent_id"],
             "start": round((item["start"] - origin) * 1000, 3),
             "end": round((item["end"] - origin) * 1000, 3)}
            for item in parallel
        ],
        "serial_identity_count": len({item["agent_id"] for item in serial}),
    }


@pytest.mark.parametrize("width", [2, 4, 8, 21])
def test_timestamped_fake_tool_benchmark(width):
    result = benchmark_fake_tools(width)
    assert result["serial_identity_count"] == width
    assert result["max_timestamp_overlap"] == width
    assert result["parallel_wall_ms"] < result["serial_wall_ms"]
    assert all(item["start"] < item["end"] for item in result["parallel_intervals_ms"])
