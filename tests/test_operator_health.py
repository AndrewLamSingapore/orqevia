import copy
import json
import sqlite3
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import operator_health, control_surface, harness_api
from app.deterministic_compute import assess
from app.job_queue import JobQueue, QueuePolicy, Provider


def evidence():
    return {"authority": {"configured": True, "pilot_enabled": True},
            "stores": {k: {"ok": True} for k in ("spine", "harness", "queue", "compute")},
            "worker": {"configured_ceiling": 1, "running_workers": 1, "stopping": False, "attention_required": False},
            "local_ready": True, "work": {"queued": 2, "completed": 3}, "uncertain_executions": 0}


def test_runtime_health_is_not_production_qualification():
    result = operator_health.interpret(evidence())
    assert result["state"] == "HEALTHY"
    assert not result["production_ready"] and not result["authority_granted"]
    assert result["work"]["queued"] == 2
    assert result["priority_order"] == ["Work", "Web3", "VELYQUA"]


@pytest.mark.parametrize("store", ["spine", "harness", "queue"])
def test_required_ledger_outage_is_never_healthy(store):
    data = evidence()
    data["stores"][store] = {"ok": False}
    assert operator_health.interpret(data)["state"] == "SAFE_STOP"


@pytest.mark.parametrize("ceiling", [0, 2, 29])
def test_unqualified_concurrency_is_a_safety_failure(ceiling):
    data = evidence(); data["worker"]["configured_ceiling"] = ceiling
    assert operator_health.interpret(data)["state"] == "SAFE_STOP"


def test_unknown_evidence_and_uncertain_execution_fail_closed():
    assert operator_health.interpret({})["state"] == "SAFE_STOP"
    data = evidence(); data["uncertain_executions"] = 1
    assert operator_health.interpret(data)["state"] == "SAFE_STOP"


def test_cloud_loss_does_not_disable_safe_local_work():
    data = evidence(); data["cloud_ready"] = False
    result = operator_health.interpret(data)
    assert result["state"] == "HEALTHY"
    assert result["operating_state"]["cloud"] == "disabled_by_pilot_policy"


def test_local_loss_and_exhausted_recovery_have_different_outcomes():
    data = evidence(); data["local_ready"] = False
    assert operator_health.interpret(data)["state"] == "DEGRADED"
    data["worker"]["attention_required"] = True
    assert operator_health.interpret(data)["state"] == "ACTION_REQUIRED"


def test_probe_is_read_only_and_does_not_create_missing_ledger(tmp_path):
    missing = tmp_path / "missing" / "ledger.db"
    assert not operator_health.read_store(missing, {})["ok"]
    assert not missing.parent.exists()
    path = tmp_path / "existing.db"
    with sqlite3.connect(path) as db:
        db.execute("create table evidence(value text)")
        db.execute("insert into evidence values('retained')")
    original = path.read_bytes()
    assert operator_health.read_store(path, {"items": "select * from evidence"})["items"] == [{"value": "retained"}]
    assert not operator_health.read_store(path, {"bad": "delete from evidence"})["ok"]
    assert path.read_bytes() == original


def test_operator_endpoint_uses_trusted_local_boundary_and_hides_diagnostics(monkeypatch):
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "fixture-token")
    monkeypatch.setattr(operator_health, "snapshot", lambda: {"state": "DEGRADED", "diagnostics": {"detail": "engineering only"}})
    app = FastAPI(); app.include_router(control_surface.router)
    client = TestClient(app, base_url="http://127.0.0.1")
    path = "/api/control-surface/trusted/operator-status"
    assert "diagnostics" not in client.get(path).json()
    assert "diagnostics" in client.get(path + "?diagnostics=true").json()
    assert client.get(path, headers={"Origin": "https://outside.invalid"}).status_code == 403
    assert TestClient(app, base_url="https://outside.invalid").get(path).status_code == 403


@pytest.mark.parametrize("intent", ["Check PRIME.", "What needs my attention?", "Show me what was completed.", "Fix the problem."])
def test_status_intents_never_use_a_model_or_issue_a_lease(monkeypatch, intent):
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "fixture-token")
    monkeypatch.setattr(operator_health, "snapshot", lambda: {"state": "SAFE_STOP", "diagnostics": {}})
    forbidden = Mock(side_effect=AssertionError("issuer reached"))
    monkeypatch.setattr(harness_api, "_runtime", forbidden)
    app = FastAPI(); app.include_router(harness_api.router)
    response = TestClient(app).post("/api/harness/intent", headers={"Authorization": "Bearer fixture-token"}, json={"intent": intent})
    assert response.status_code == 200
    assert response.json()["model_invocations"] == 0
    forbidden.assert_not_called()


@pytest.mark.parametrize("intent", ["Work on Web3.", "Continue VELYQUA."])
def test_unavailable_dependent_artifacts_do_not_trigger_speculative_work(monkeypatch, intent):
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "fixture-token")
    app = FastAPI(); app.include_router(harness_api.router)
    response = TestClient(app).post("/api/harness/intent", headers={"Authorization": "Bearer fixture-token"}, json={"intent": intent})
    assert response.status_code == 409
    assert response.json()["reason_code"] == "DEPENDENT_PHASE_EVIDENCE_REQUIRED"


def test_exact_schema_validity_and_invalidity_are_both_deterministic():
    for value, valid in [('"AUTO"', True), ('"SELF_AUTHORIZED"', False)]:
        result = assess('validate schema policy-state-v1: ' + value)
        assert result.resolution_path == "deterministic"
        assert json.loads(result.result)["valid"] is valid


@pytest.mark.parametrize("prompt", ['validate schema no-such-schema: {}', 'validate schema policy-state-v1: NaN',
                                   'validate schema action-envelope-v1: {"x":1e999}',
                                   'validate schema action-envelope-v1: {"x":1,"x":2}'])
def test_invalid_schema_contract_rejects_without_inference(prompt):
    assert assess(prompt).resolution_path == "reject"


def test_exact_registry_lookup_never_confers_execution_authority():
    result = assess('lookup agent a14')
    assert result.resolution_path == "deterministic"
    entry = json.loads(result.result)
    assert entry["agent_id"] == "a14"
    assert "authority" not in entry
    assert assess('lookup agent nonexistent').resolution_path == "reject"


def test_explicit_deep_role_cannot_silently_use_fast_provider(tmp_path):
    queue = JobQueue(tmp_path / 'q.db', QueuePolicy())
    queue.submit(agent='a16', prompt='deep reasoning', model_role='deep')
    fast = Provider('ollama-fast', 'local', 'small', 8192, 0, 1)
    assert queue.claim('worker', [fast]) is None
    deep = Provider('ollama-deep', 'local', 'large', 8192, 0, 1)
    assert queue.claim('worker', [fast, deep])["provider"] == 'ollama-deep'


def test_recovery_events_are_durable_and_share_existing_ledger(tmp_path):
    queue = JobQueue(tmp_path / 'q.db', QueuePolicy())
    queue.record_recovery('worker-1', 1, 'OperationalError', 'retry_wait')
    queue.record_recovery('worker-1', 1, '', 'recovered')
    with queue.connect() as db:
        rows = db.execute("select event_type,details_json from compute_events order by created_at").fetchall()
    assert [json.loads(r[1])["state"] for r in rows] == ['retry_wait', 'recovered']
    assert all(r[0] == 'queue.recovery' for r in rows)
    assert not any(json.loads(r[1])["authority_expanded"] for r in rows)


def test_compute_records_unavailable_are_not_a_healthy_zero_cost_result():
    data = evidence(); data["stores"]["compute"] = {"ok": False}
    result = operator_health.interpret(data)
    assert result["state"] == "DEGRADED"
    assert result["operating_state"]["exact_computation"] == "not verified"


def test_event_fabric_connections_close_and_failure_text_is_not_logged(tmp_path):
    from app.event_fabric import EventFabric
    fabric = EventFabric(str(tmp_path / 'events.db'))
    with fabric.connect() as db:
        db.execute('select 1')
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute('select 1')
    def fail():
        raise ValueError('TOKEN-DO-NOT-STORE')
    result = fabric._once('fixture-only', 'fixture-projector', fail)
    assert result['status'] == 'failed'
    with fabric.connect() as connection:
        saved = connection.execute('select details_json from event_projections').fetchone()[0]
    assert saved == '{"error": "ValueError"}'
