from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import harness_api, operator_health


@pytest.mark.parametrize("intent", ["Continue my highest-priority work.", "Continue my highest priority work!", "Continue the highest-priority work."])
@pytest.mark.parametrize("state,available,ready,work,expected", [
    ("HEALTHY", True, True, {"queued":2}, "EXISTING_SCHEDULER"),
    ("HEALTHY", True, True, {"running":1}, "EXISTING_SCHEDULER"),
    ("HEALTHY", True, True, {"completed":4}, "NO_ELIGIBLE_WORK"),
    ("SAFE_STOP", True, False, {"queued":2}, "WAIT_FOR_READINESS"),
    ("DEGRADED", False, False, {}, "WAIT_FOR_VERIFIED_WORK_STATE"),
])
def test_continue_uses_recorded_work_without_new_authority(monkeypatch, intent, state, available, ready, work, expected):
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "fixture-only")
    monkeypatch.setattr(operator_health, "snapshot", lambda: {
        "state":state, "work_available":available, "ready_for_local_work":ready,
        "work":work, "diagnostics":{"private":"not for owner"}
    })
    issuer = Mock(side_effect=AssertionError("new authority issued"))
    monkeypatch.setattr(harness_api, "_runtime", issuer)
    app = FastAPI()
    app.include_router(harness_api.router)
    client = TestClient(app)
    for _ in range(2):
        response = client.post("/api/harness/intent", headers={"Authorization":"Bearer fixture-only"}, json={"intent":intent})
        assert response.status_code == 200
        body = response.json()
        assert body["next_automatic_action"] == expected
        assert body["model_invocations"] == 0
        assert not body["action_authority"] and not body["resubmitted"]
        assert body["priority_order"] == ["Work", "Web3", "VELYQUA"]
        assert "diagnostics" not in body["status"]
        assert isinstance(body["result"], str) and body["result"]
    issuer.assert_not_called()

