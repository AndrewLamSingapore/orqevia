"""Exercise the coaching -> SQLite -> provider boundary, without inference."""

import json
from types import SimpleNamespace

import pytest

from app.agent_coaching import CoachingController, request_for
from app.direct_stream import inference_request
from app.job_queue import JobQueue


@pytest.fixture
def exercise(tmp_path):
    queue = JobQueue(tmp_path / "queue.db")
    controller = CoachingController(
        tmp_path / "coaching.db",
        queue,
        source_revision="a" * 40,
        model="fixture-local",
        clock=lambda: 2_000_000.0,
    )
    controller.ensure_cohort()
    return queue, controller


def submit_role(exercise, agent, phase="baseline"):
    queue, controller = exercise
    with controller.connect() as db:
        db.execute("UPDATE coaching_sessions SET state='DONE' WHERE agent!=?", (agent,))
        db.execute("UPDATE coaching_sessions SET phase=? WHERE agent=?", (phase, agent))
    assert controller.tick() == "SUBMITTED"
    return queue, controller, queue.list()[0]


@pytest.mark.parametrize("agent", ["a01", "a04"])
def test_coaching_preserves_source_first_fields_through_real_queue_and_provider(exercise, agent):
    queue, _, job = submit_role(exercise, agent)
    # Reopen SQLite instead of inspecting only the submit() call arguments.
    restored = JobQueue(queue.db_path).get(job["id"])
    assert restored["response_schema_order"] == "declared"
    request = request_for(agent, "baseline", 1001)
    fields = request["response_schema"]["required"]
    payload, _, receipt = inference_request(
        restored,
        SimpleNamespace(model="fixture-local"),
        settings=SimpleNamespace(keep_alive=0, context_tokens=8192, max_output_tokens=4096),
        options=lambda: {},
    )
    assert list(payload["format"]["properties"]) == fields
    assert payload["format"]["required"] == fields
    assert receipt["response_schema_order"] == "declared"
    if agent == "a04":
        assert fields.index("reliability_weight") < fields.index("a_score") < fields.index("decision")
    else:
        assert fields.index("beta_total_points") < fields.index("higher_efficiency_project")


@pytest.mark.parametrize("changed", ["order", "schema", "field_order", "format", "invalid_json"])
def test_mismatched_output_contract_is_retained_without_semantic_grade(exercise, changed):
    queue, controller, job = submit_role(exercise, "a04")
    with queue.connect() as db:
        if changed == "order":
            db.execute("UPDATE compute_jobs SET response_schema_order='canonical' WHERE id=?", (job["id"],))
        elif changed == "schema":
            schema = json.loads(job["response_schema"])
            schema["properties"]["a_score"] = {"type": "string"}
            db.execute("UPDATE compute_jobs SET response_schema=? WHERE id=?", (json.dumps(schema), job["id"]))
        elif changed == "field_order":
            schema = json.loads(job["response_schema"])
            schema["required"].reverse()
            db.execute("UPDATE compute_jobs SET response_schema=? WHERE id=?", (json.dumps(schema), job["id"]))
        elif changed == "format":
            db.execute("UPDATE compute_jobs SET response_format='text' WHERE id=?", (job["id"],))
        else:
            db.execute("UPDATE compute_jobs SET response_schema='{' WHERE id=?", (job["id"],))
        db.execute("UPDATE compute_jobs SET status='completed',result='{}' WHERE id=?", (job["id"],))
    assert controller.tick() == "SELF_REPAIRED"
    assert queue.get(job["id"])["result"] == "{}"
    with controller.connect() as db:
        assert db.execute("SELECT count(*) FROM coaching_events WHERE outcome IN ('PASS','FAIL')").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM coaching_events WHERE outcome='SELF_REPAIRED'").fetchone()[0] == 1
    with queue.connect() as db:
        assert db.execute("SELECT count(*) FROM compute_submission_keys").fetchone()[0] == 1


def test_practice_keeps_its_existing_canonical_order(exercise):
    _, _, job = submit_role(exercise, "a04", "practice")
    assert job["response_schema_order"] == "canonical"
    assert json.loads(job["response_schema"])["required"] == ["additional_evidence_required", "scores", "winner"]
