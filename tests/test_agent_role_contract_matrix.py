"""Static 21-role dispatch contracts, not live agent competence evidence.

The queue and ledger are in-memory fakes: no worker, model, tool, or network call.
"""

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

# This existing test app configures a temporary data root before importing the
# production routers. It does not start a queue worker or contact a model.
from tests.test_harness_api import app
from app import agent_dispatch_api, compute_catalog, compute_queue_api
from app.agent_registry import agent_record, load_agent_registry, responsibility_owner


@dataclass
class FakeQueue:
    submitted: list[dict] = field(default_factory=list)

    def submit(self, **kwargs):
        self.submitted.append(kwargs)
        return {"id": f"fake-{len(self.submitted)}", "agent": kwargs["agent"], "status": "queued"}


@dataclass
class FakeLedger:
    events: list[str] = field(default_factory=list)

    def emit(self, _record, phase, **_details):
        self.events.append(phase)
        return phase

    def status(self):
        return {"healthy": True, "persisted": len(self.events), "pending": 0, "dropped": 0}


@pytest.fixture
def dispatch_harness(monkeypatch):
    queue, ledger = FakeQueue(), FakeLedger()
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "fixture-owner-token")
    monkeypatch.setenv("PRIME_REGISTRY_V1_ENABLED", "1")
    monkeypatch.setattr(compute_queue_api, "queue", queue)
    monkeypatch.setattr(compute_queue_api, "providers", lambda: [])
    monkeypatch.setattr(compute_catalog, "load_catalog", lambda: [])
    monkeypatch.setattr(agent_dispatch_api, "action_ledger", lambda: ledger)
    with TestClient(app) as client:
        yield client, queue, ledger


REGISTRY = load_agent_registry()
OWNED_CAPABILITIES = [
    (agent["agent_id"], capability)
    for agent in REGISTRY["agents"]
    for capability in agent["capability_requirements"]
]
CANONICAL_AGENTS = [agent["agent_id"] for agent in REGISTRY["agents"]]


@pytest.mark.parametrize("owner,capability", OWNED_CAPABILITIES, ids=lambda value: str(value))
def test_registered_capability_routes_to_unique_canonical_owner(dispatch_harness, owner, capability):
    client, queue, ledger = dispatch_harness
    assert responsibility_owner(capability) == owner
    record = agent_record(owner)
    response = client.post(
        "/api/agents/dispatch",
        headers={"Authorization": "Bearer fixture-owner-token"},
        json={
            "capability": capability,
            "objective": "Provide one short advisory answer.",
            "task_class": "classification",
            "data_classification": "LOCAL_ONLY",
            "max_cost_usd": 0,
            "requested_agent": "invented-agent",  # Client-supplied identity is not authority.
        },
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["capability"] == capability
    assert body["job"]["agent"] == owner
    assert body["agent_path"] == ([owner] if record["can_delegate"] else [record["reports_to"], owner])
    assert len(queue.submitted) == 1
    assert queue.submitted[0]["agent"] == owner
    assert queue.submitted[0]["allow_cloud"] is False
    assert queue.submitted[0]["max_retries"] == 0
    assert ledger.events == ["started", "completed"]


@pytest.mark.parametrize("agent_id", CANONICAL_AGENTS)
def test_forged_capability_fails_before_enqueue(dispatch_harness, agent_id):
    client, queue, ledger = dispatch_harness
    response = client.post(
        "/api/agents/dispatch",
        headers={"Authorization": "Bearer fixture-owner-token"},
        json={"capability": f"responsibility.{agent_id}.forged", "objective": "Advise."},
    )
    assert response.status_code == 422
    assert queue.submitted == []
    assert ledger.events == []


def test_authentication_and_registry_switch_fail_before_enqueue(dispatch_harness, monkeypatch):
    client, queue, ledger = dispatch_harness
    payload = {"capability": "responsibility.a01", "objective": "Advise."}
    assert client.post("/api/agents/dispatch", json=payload).status_code == 401
    monkeypatch.setenv("PRIME_REGISTRY_V1_ENABLED", "0")
    response = client.post(
        "/api/agents/dispatch",
        headers={"Authorization": "Bearer fixture-owner-token"},
        json=payload,
    )
    assert response.status_code == 503
    assert queue.submitted == []
    assert ledger.events == []


def test_fixture_scope_is_registration_not_runtime_certification():
    assert len(CANONICAL_AGENTS) == 21
    assert len(set(CANONICAL_AGENTS)) == 21
    assert len(OWNED_CAPABILITIES) == 29
    assert all(agent["status"] == "registered" and agent["model"] == "unassigned"
               for agent in REGISTRY["agents"])
