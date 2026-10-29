"""Deterministic single-slot scheduling lane: solver, gate and dispatch input."""

import json

import pytest

from app.deterministic_scheduling import (
    SchedulingSpecError,
    check_answer,
    oracle_agreement,
    parse_jobs,
    solve_from_context,
    solve_schedule,
)


DEEP_TRIAL_JOBS = [
    {"name": "b1", "arrival": 0, "duration": 40, "priority_class": "background"},
    {"name": "i1", "arrival": 5, "duration": 10, "priority_class": "interactive"},
    {"name": "b2", "arrival": 8, "duration": 20, "priority_class": "background"},
]

DEEP_TRIAL_ORACLE = {
    "i1_start": 40,
    "i1_finish": 50,
    "i1_wait": 35,
    "b2_start": 50,
    "b2_finish": 70,
    "b2_wait": 42,
    "waiting_consumes_execution_budget": False,
}

FAILED_MODEL_ANSWER = {
    "b2_finish": 28,
    "b2_start": 8,
    "b2_wait": 0,
    "i1_finish": 15,
    "i1_start": 5,
    "i1_wait": 0,
    "waiting_consumes_execution_budget": False,
}


def test_deep_trial_oracle_is_reproduced_from_first_principles():
    solved = solve_schedule(DEEP_TRIAL_JOBS)
    assert solved == {
        "b1_start": 0,
        "b1_finish": 40,
        "b1_wait": 0,
        "i1_start": 40,
        "i1_finish": 50,
        "i1_wait": 35,
        "b2_start": 50,
        "b2_finish": 70,
        "b2_wait": 42,
        "waiting_consumes_execution_budget": False,
    }
    assert all(solved[key] == value for key, value in DEEP_TRIAL_ORACLE.items())
    assert oracle_agreement(DEEP_TRIAL_ORACLE, DEEP_TRIAL_JOBS)["agreement"] is True


def test_interactive_priority_applies_only_when_slot_becomes_free():
    jobs = [
        {"name": "b1", "arrival": 0, "duration": 20, "priority_class": "background"},
        {"name": "i1", "arrival": 19, "duration": 5, "priority_class": "interactive"},
        {"name": "b2", "arrival": 2, "duration": 5, "priority_class": "background"},
    ]
    solved = solve_schedule(jobs)
    # B1 is nonpreemptive: I1 arriving at 19 cannot preempt a running slot.
    assert solved["b1_finish"] == 20
    assert solved["i1_start"] == 20
    assert solved["b2_start"] == 25
    assert solved["i1_wait"] == 1
    assert solved["b2_wait"] == 23


def test_idle_gap_and_same_class_fifo():
    jobs = [
        {"name": "a", "arrival": 0, "duration": 5, "priority_class": "background"},
        {"name": "b", "arrival": 0, "duration": 5, "priority_class": "background"},
        {"name": "c", "arrival": 30, "duration": 5, "priority_class": "background"},
    ]
    solved = solve_schedule(jobs)
    assert (solved["a_start"], solved["a_finish"]) == (0, 5)
    assert (solved["b_start"], solved["b_finish"]) == (5, 10)
    assert (solved["c_start"], solved["c_finish"]) == (30, 35)
    assert solved["c_wait"] == 0
    assert solved["waiting_consumes_execution_budget"] is False


def test_zero_duration_jobs_do_not_move_the_slot_forward():
    jobs = [
        {"name": "a", "arrival": 0, "duration": 0, "priority_class": "background"},
        {"name": "b", "arrival": 0, "duration": 0, "priority_class": "background"},
    ]
    solved = solve_schedule(jobs)
    assert solved["a_finish"] == 0 and solved["b_finish"] == 0
    assert solved["a_wait"] == 0 and solved["b_wait"] == 0


def test_dispatch_context_roundtrip():
    context = json.dumps({"jobs": DEEP_TRIAL_JOBS})
    assert solve_from_context(context) == solve_schedule(DEEP_TRIAL_JOBS)
    assert solve_from_context(context.encode("utf-8")) == solve_schedule(DEEP_TRIAL_JOBS)


def test_check_answer_gate_rejects_the_recorded_deep_failure():
    gate = check_answer(FAILED_MODEL_ANSWER, DEEP_TRIAL_JOBS, required_keys=list(DEEP_TRIAL_ORACLE))
    assert gate["match"] is False
    assert gate["reason"] == "answer-values-or-types-mismatch"
    assert gate["expected"]["i1_start"] == 40


def test_check_answer_gate_accepts_the_exact_oracle_answer():
    gate = check_answer(DEEP_TRIAL_ORACLE, DEEP_TRIAL_JOBS, required_keys=list(DEEP_TRIAL_ORACLE))
    assert gate["match"] is True
    assert gate["reason"] == "exact-match"


def test_check_answer_gate_is_type_strict():
    floats = {key: float(value) for key, value in DEEP_TRIAL_ORACLE.items()
              if key != "waiting_consumes_execution_budget"}
    floats["waiting_consumes_execution_budget"] = False
    assert check_answer(floats, DEEP_TRIAL_JOBS,
                        required_keys=list(DEEP_TRIAL_ORACLE))["match"] is False


def test_full_schedule_gate_requires_every_job_key():
    assert check_answer(DEEP_TRIAL_ORACLE, DEEP_TRIAL_JOBS)["match"] is False
    full = solve_schedule(DEEP_TRIAL_JOBS)
    assert check_answer(full, DEEP_TRIAL_JOBS)["match"] is True


@pytest.mark.parametrize(
    "jobs",
    [
        [],
        [{"name": "a", "arrival": -1, "duration": 1}],
        [{"name": "a", "arrival": 0, "duration": -1}],
        [{"name": "a", "arrival": 0, "duration": 1, "priority_class": "realtime"}],
        [{"name": "a", "arrival": True, "duration": 1}],
        [{"name": "1a", "arrival": 0, "duration": 1}],
        [{"name": "a", "arrival": 0, "duration": 1}, {"name": "a", "arrival": 1, "duration": 1}],
        [{"name": "a", "arrival": 0, "duration": 1}] * 101,
    ],
)
def test_invalid_specs_are_rejected(jobs):
    with pytest.raises(SchedulingSpecError):
        parse_jobs(jobs)


def test_malformed_or_absent_context_is_rejected():
    for context in (b"", "{not json", json.dumps({}), json.dumps({"jobs": []})):
        with pytest.raises(SchedulingSpecError):
            solve_from_context(context)


def test_dispatch_end_to_end_schedule_single_slot(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PRIME_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORQEVIA_REGISTRY_V1_ENABLED", "1")
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", "test-owner-token")
    from app import agent_dispatch_api, artifact_delivery

    app = FastAPI()
    app.include_router(agent_dispatch_api.router)
    app.include_router(artifact_delivery.router)
    headers = {"Authorization": "Bearer test-owner-token"}
    payload = {
        "capability": "responsibility.a19",
        "objective": "Compute the exact nonpreemptive single-slot schedule.",
        "context": json.dumps({"jobs": DEEP_TRIAL_JOBS}),
        "classification": "R0",
        "data_classification": "LOCAL_ONLY",
        "priority": "background",
        "max_cost_usd": 0,
        "deterministic_operation": "schedule_single_slot",
    }
    with TestClient(app) as client:
        denied = client.post("/api/agents/dispatch", json=payload)
        assert denied.status_code == 401
        result = client.post("/api/agents/dispatch", headers=headers, json=payload)
        assert result.status_code == 202, result.text
        body = result.json()
        assert body["state"] == "COMPLETED"
        assert body["execution_model"] == "DETERMINISTIC"
        assert body["model_calls"] == 0
        artifact = client.get(f"/api/artifacts/{body['artifact']['artifact_id']}",
                              headers=headers)
    assert artifact.status_code == 200, artifact.text
    solved = json.loads(artifact.content)
    assert solved == solve_schedule(DEEP_TRIAL_JOBS)
    assert (tmp_path / "compute-ledger.db").exists()


def test_dispatch_rejects_malformed_schedule_spec(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PRIME_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORQEVIA_REGISTRY_V1_ENABLED", "1")
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", "test-owner-token")
    from app import agent_dispatch_api

    app = FastAPI()
    app.include_router(agent_dispatch_api.router)
    headers = {"Authorization": "Bearer test-owner-token"}
    payload = {
        "capability": "responsibility.a19",
        "objective": "Broken schedule.",
        "context": json.dumps({"jobs": [{"name": "a", "arrival": 0, "duration": -1}]}),
        "deterministic_operation": "schedule_single_slot",
    }
    with TestClient(app) as client:
        result = client.post("/api/agents/dispatch", headers=headers, json=payload)
    assert result.status_code == 422
