"""Low-resource, offline send/execute/result proof for each registered identity."""

import json

import pytest

from app.action_records import ActionLedger, ActionRecord, DirectExecutor
from app.agent_registry import agent_record, load_agent_registry, responsibility_owner
from app.agent_runtime import AgentAuthorityRuntime


AGENTS = sorted(load_agent_registry()["agents"], key=lambda item: item["id"])


@pytest.mark.parametrize("agent", AGENTS, ids=lambda item: item["id"])
def test_authorized_local_task_is_attributed_from_send_to_result(agent, tmp_path):
    agent_id = agent["id"]
    assert agent_record(agent_id)["immutable_id"] == agent_id
    assert agent["status"] == "registered" and agent["model"] == "unassigned"
    capability = agent["capability_requirements"][0]
    assert responsibility_owner(capability) == agent_id
    path = [agent_id] if agent["can_delegate"] else [agent["reports_to"], agent_id]
    runtime = AgentAuthorityRuntime(tmp_path / "authority.db")
    trace_id = runtime.begin_path(path)
    handoffs = list(reversed(runtime.recent(2)))
    assert [event["target_agent"] for event in handoffs] == path
    assert all(event["trace_id"] == trace_id and event["allowed"] == 1 for event in handoffs)

    ledger_path = tmp_path / "actions.jsonl"
    ledger = ActionLedger(ledger_path)
    action = ActionRecord(
        task_id=trace_id,
        agent_id=agent_id,
        action_type="offline.fake.execute",
        tool="deterministic-local-fake",
        parent_agent=path[0] if len(path) == 2 else "prime",
    )

    def fake_operation():
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
