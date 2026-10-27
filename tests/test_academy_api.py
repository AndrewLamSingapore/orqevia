"""Isolated HTTPS-origin API contracts; no live model execution claimed."""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import academy_api
from app.agent_coaching import CoachingController
from app.job_queue import JobQueue


def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "1")
    monkeypatch.setenv("ORQEVIA_RUNTIME_REVISION", "a" * 40)
    queue = JobQueue(tmp_path / "queue.db")
    controller = CoachingController(tmp_path / "agent-coaching.db", queue, source_revision="a" * 40, model="gemma3:12b")
    app = FastAPI()
    app.include_router(academy_api.router)
    return TestClient(app, base_url="https://testserver"), queue, controller


def test_catalog_paths_auth_and_no_answers(tmp_path, monkeypatch):
    client, queue, controller = fixture(tmp_path, monkeypatch)
    value = client.get("/api/academy/probability").json()
    assert len(value["lessons"]) == 14 and len(value["agents"]) == 21
    assert value["certification_awarded"] is False
    for agent in value["agents"]:
        record = client.get("/api/academy/agents/" + agent).json()
        assert len(record["topic_ids"]) == 14 and record["retained_methods"] == []
    assert client.get("/api/academy/agents/not-an-agent").status_code == 404
    monkeypatch.setenv("ORQEVIA_OPEN_ACCESS", "0")
    monkeypatch.setenv("ORQEVIA_SPINE_TOKEN", "fixture-authority-not-a-real-secret")
    assert client.get("/api/academy/probability").status_code == 401


def test_notification_dispatches_existing_owned_job_only(tmp_path, monkeypatch):
    client, queue, controller = fixture(tmp_path, monkeypatch)
    controller.ensure_cohort()
    controller.tick()
    job = queue.list()[0]
    with patch("app.compute_queue_api.queue", queue), patch("app.compute_queue_api.dispatch") as dispatch:
        response = client.post("/api/academy/notify/" + job["id"])
        assert response.status_code == 200
        dispatch.assert_called_once_with(job["id"])
        assert len(queue.list()) == 1
        monkeypatch.setenv("ORQEVIA_RUNTIME_REVISION", "b" * 40)
        assert client.post("/api/academy/notify/" + job["id"]).status_code == 409
        assert dispatch.call_count == 1
        monkeypatch.setenv("ORQEVIA_RUNTIME_REVISION", "a" * 40)
        with queue.connect() as db:
            db.execute("UPDATE compute_jobs SET prompt='changed'")
        assert client.post("/api/academy/notify/" + job["id"]).status_code == 409
        assert dispatch.call_count == 1


def test_retention_rejects_unproven_or_modified_methods(tmp_path, monkeypatch):
    client, queue, controller = fixture(tmp_path, monkeypatch)
    controller.ensure_cohort("probability-foundations")
    from app.probability_curriculum import LESSONS, VERSION

    with controller.connect() as db:
        session = dict(db.execute("SELECT * FROM coaching_sessions LIMIT 1").fetchone())
        session.update(phase="acceptance", job_id="fixture-assessment")
        event = controller.event(db, session, "FAIL")
        topic, _, method = LESSONS[0]
        db.execute(
            "INSERT INTO academy_retained_methods VALUES(?,?,?,?,?,?,?,?)",
            (session["agent"], topic, VERSION, method, event, "fixture-assessment", "a" * 40, 1),
        )
    assert academy_api.retained_methods(session["agent"]) == []
    with controller.connect() as db:
        db.execute("UPDATE coaching_events SET outcome='PASS'")
    assert len(academy_api.retained_methods(session["agent"])) == 1
    with controller.connect() as db:
        db.execute("UPDATE academy_retained_methods SET method='untrusted model text'")
    assert academy_api.retained_methods(session["agent"]) == []
