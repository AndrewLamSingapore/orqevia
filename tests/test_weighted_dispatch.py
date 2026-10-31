"""Actual authenticated dispatch, persistence and action provenance in test stores."""

# ruff: noqa: F811 - deliberate pytest fixture named `api`
import json

import pytest

from tests.test_direct_execution import api, isolated  # noqa: F401
from tests.test_weighted_decision import request


@pytest.fixture(autouse=True)
def calculator_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("PRIME_DATA_DIR", str(tmp_path))


def test_a04_dispatch_calculates_persists_artifact_and_records_real_tool_actions(api, tmp_path, monkeypatch):
    from app.artifact_factory import ArtifactFactory
    from app.action_records import action_ledger

    client, compute = api

    def forbidden(*args, **kwargs):
        raise AssertionError("Calculator must not submit inference")

    monkeypatch.setattr(compute.queue, "submit", forbidden)
    body = {
        "capability": "responsibility.a04",
        "objective": "Compare the supplied weighted options.",
        "context": json.dumps(request()),
        "deterministic_operation": "weighted_decision",
    }
    assert client.post("/api/agents/dispatch", json=body).status_code == 401
    response = client.post("/api/agents/dispatch", headers={"Authorization": "Bearer isolated-test-owner"}, json=body)
    assert response.status_code == 202, response.text
    result = response.json()
    assert result["agent_id"] == "a04" and result["model_calls"] == 0
    assert result["calculation_provider"] == "deterministic" and result["calculation_action_durable"]
    _, raw = ArtifactFactory(tmp_path / "artifacts").retrieve(result["artifact"]["artifact_id"])
    artifact = json.loads(raw)
    assert artifact["scores"] == {"A": 9, "B": 9} and artifact["decision"] == "TIE"
    ledger = action_ledger()
    assert ledger.flush()
    rows = [json.loads(line) for line in ledger.path.read_text(encoding="utf-8").splitlines()]
    completed = [r for r in rows if r["phase"] == "completed"]
    assert {r["action_type"] for r in completed} == {"decision.weighted.calculate", "decision.weighted.artifact"}
    assert all(r["agent_id"] == "a04" and r["success"] is True for r in completed)
    assert result["calculation_action_id"] in {r["action_id"] for r in completed}


def test_explicit_weighted_objective_routes_to_a04_and_displays_the_persisted_calculation(api, monkeypatch):
    client, compute = api

    def forbidden(*args, **kwargs):
        raise AssertionError("Calculator must not submit inference")

    monkeypatch.setattr(compute.queue, "submit", forbidden)
    headers = {"Authorization": "Bearer isolated-test-owner"}
    response = client.post(
        "/api/agents/objectives",
        headers=headers,
        json={
            "objective": "Evaluate these facts.",
            "context": json.dumps(request()),
            "deterministic_operation": "weighted_decision",
        },
    )
    assert response.status_code == 202, response.text
    task = client.get("/api/agents/objectives/" + response.json()["id"], headers=headers).json()
    assert task["state"] == "COMPLETED"
    assert task["steps"][0]["capability"] == "responsibility.a04"
    assert task["result"]["type"] == "DETERMINISTIC_CALCULATION"
    assert task["result"]["authoritative"] is False
    assert json.loads(task["result"]["text"])["decision"] == "TIE"
    assert task["execution_metadata"]["inference_attempts"]["status"] == "NOT_APPLICABLE"


def test_wrong_role_and_missing_criterion_fail_the_affected_request_only(api):
    client, _ = api
    headers = {"Authorization": "Bearer isolated-test-owner"}
    body = {
        "capability": "responsibility.a17",
        "objective": "Compare.",
        "context": json.dumps(request()),
        "deterministic_operation": "weighted_decision",
    }
    assert client.post("/api/agents/dispatch", headers=headers, json=body).status_code == 422
    body["capability"] = "responsibility.a04"
    value = request()
    del value["option_criterion_scores"][1]["speed"]
    body["context"] = json.dumps(value)
    assert client.post("/api/agents/dispatch", headers=headers, json=body).status_code == 422
    body["context"] = json.dumps(request())
    assert client.post("/api/agents/dispatch", headers=headers, json=body).status_code == 202


def test_thin_objective_contract_accepts_the_explicit_calculator_operation():
    from app.interface_node import Objective

    body = Objective(
        objective="Compare.",
        context=json.dumps(request()),
        idempotency_key="weighted-fixture",
        deterministic_operation="weighted_decision",
    )
    assert body.deterministic_operation == "weighted_decision"


def test_thin_continuation_contract_accepts_the_calculator_operation():
    from app.interface_contract import Continuation

    body = Continuation(
        objective="Compare.",
        context=json.dumps(request()),
        expected_revision=0,
        idempotency_key="weighted-follow",
        deterministic_operation="weighted_decision",
    )
    assert body.deterministic_operation == "weighted_decision"


def test_automatic_a04_routing_with_exact_structured_context(api, monkeypatch):
    client, compute = api

    def forbidden(*args, **kwargs):
        raise AssertionError("Calculator must not submit inference")

    monkeypatch.setattr(compute.queue, "submit", forbidden)
    headers = {"Authorization": "Bearer isolated-test-owner"}
    response = client.post(
        "/api/agents/objectives",
        headers=headers,
        json={
            "objective": "Compare the supplied weighted options.",
            "context": json.dumps(request()),
            "capability": "responsibility.a04",
        },
    )
    assert response.status_code == 202, response.text
    task = client.get("/api/agents/objectives/" + response.json()["id"], headers=headers).json()
    assert task["state"] == "COMPLETED"
    assert task["steps"][0]["capability"] == "responsibility.a04"
    assert task["result"]["type"] == "DETERMINISTIC_CALCULATION"
    assert json.loads(task["result"]["text"])["decision"] == "TIE"
    assert task["execution_metadata"]["inference_attempts"]["status"] == "NOT_APPLICABLE"


def test_auto_capability_with_weighted_intent_and_structured_context(api, monkeypatch):
    client, compute = api

    def forbidden(*args, **kwargs):
        raise AssertionError("Calculator must not submit inference")

    monkeypatch.setattr(compute.queue, "submit", forbidden)
    headers = {"Authorization": "Bearer isolated-test-owner"}
    response = client.post(
        "/api/agents/objectives",
        headers=headers,
        json={
            "objective": "Compute the weighted decision across the supplied options.",
            "context": json.dumps(request()),
        },
    )
    assert response.status_code == 202, response.text
    task = client.get("/api/agents/objectives/" + response.json()["id"], headers=headers).json()
    assert task["state"] == "COMPLETED"
    assert task["steps"][0]["capability"] == "responsibility.a04"
    assert task["result"]["type"] == "DETERMINISTIC_CALCULATION"


def test_a04_or_weighted_wording_without_structured_context_keeps_model_routing(api):
    client, _ = api
    headers = {"Authorization": "Bearer isolated-test-owner"}
    for objective, context, capability in [
        ("Compare A and B.", "plain prose context", "responsibility.a04"),
        ("Compute the weighted decision.", "plain prose context", "auto"),
        ("Compute the weighted decision.", json.dumps({"criterion_weights": {}, "extra": 1}), "auto"),
    ]:
        response = client.post(
            "/api/agents/objectives",
            headers=headers,
            json={"objective": objective, "context": context, "capability": capability},
        )
        assert response.status_code == 202, response.text
        task = client.get("/api/agents/objectives/" + response.json()["id"], headers=headers).json()
        steps = task["steps"]
        assert steps and "job" in steps[0]
        assert task["state"] not in ("COMPLETED",)
