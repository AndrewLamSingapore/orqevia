"""Runtime adapter tests with real queue/store transactions and explicit fixture inference."""

from __future__ import annotations

import json
import threading

import pytest

from app.collective_intelligence import CollectiveConflict, CollectiveDenied, CollectivePrincipal
from app.job_queue import JobQueue, Provider, QueuePolicy, WorkerPool


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ORQEVIA_COLLECTIVE_ENABLED", "1")
    monkeypatch.setenv("ORQEVIA_PWA_OWNER_ACCOUNT_ID", "fixture-owner")
    monkeypatch.setenv("ORQEVIA_RUNTIME_REVISION", "9" * 40)
    monkeypatch.setenv("ORQEVIA_NODE_ID", "TEST")
    monkeypatch.setenv("ORQEVIA_DATA_DIR", str(tmp_path))
    from app import collective_runtime as rt
    from app import compute_queue_api, agent_notebook_api, collective_repair
    from app.agent_notebooks import AgentNotebookStore

    queue = JobQueue(tmp_path / "queue.db", QueuePolicy(global_concurrency=1))
    notebooks = AgentNotebookStore(tmp_path / "notebooks.db", embedder=lambda _: [1.0, 0.0])
    monkeypatch.setattr(compute_queue_api, "queue", queue)
    monkeypatch.setattr(agent_notebook_api, "_store", lambda: notebooks)
    monkeypatch.setattr(collective_repair, "get_notebook_store", lambda: notebooks)
    owner = rt._configured_principal("OWNER", "fixture-owner-session")
    return rt, queue, notebooks, owner


def complete(queue, result, *, agent="a01", prompt="Inspect actual fixture source"):
    job = queue.submit(agent=agent, prompt=prompt, max_retries=0, max_cost_usd=0, model_role="fast")
    provider = Provider("ollama-fast", "local", "fixture-model", 32768, 0, 1)
    queued = queue.claim("fixture-worker", [provider])
    assert queued["id"] == job["id"]
    return queue.finish(job["id"], result=result, inference_receipt={"model": "fixture-model"})


def test_completed_job_publication_actual_digest_private_notebook_idempotency(runtime):
    rt, queue, notebooks, owner = runtime
    job = complete(queue, "This source-bound fixture result remains a hypothesis.")
    published = rt.publish_job(job["id"], owner)
    assert published["state"] == "PUBLISHED" and published["classification"] == "HYPOTHESIS"
    assert published["notebook"]["state"] == "RECORDED"
    assert rt.publish_job(job["id"], owner)["claim_id"] == published["claim_id"]
    metric = rt.get_store().metrics(owner)
    assert metric["agents"]["verified_contributing_agents"] == 1
    assert metric["knowledge"]["verified_facts"] == 0
    evidence = rt.get_store().query(owner, "evidence", published["evidence_id"])
    assert evidence["data"]["content"]["model"] == "fixture-model"
    with notebooks.connect() as connection:
        row = connection.execute(
            "SELECT scope,source_ref FROM agent_memory_records WHERE memory_id=?", (published["notebook"]["memory_id"],)
        ).fetchone()
        assert row["scope"] == "private" and row["source_ref"] == "queue-job:" + job["id"]


def test_disabled_scope_incomplete_and_liveness_do_not_publish(runtime, monkeypatch):
    rt, queue, _, owner = runtime
    pending = queue.submit(agent="a01", prompt="Not executed")
    with pytest.raises(CollectiveConflict):
        rt.publish_job(pending["id"], owner)
    different = CollectivePrincipal("personal", "different-owner", "owner", roles=frozenset({"OWNER"}))
    with pytest.raises(CollectiveDenied):
        rt.publish_job(pending["id"], different)
    monkeypatch.setenv("ORQEVIA_COLLECTIVE_ENABLED", "0")
    with pytest.raises(CollectiveDenied):
        rt.get_store()


def test_model_question_real_output_gets_source_bound_investigation(runtime):
    rt, queue, _, owner = runtime
    requested = rt.start_investigation(owner, "a01", "agent:a01", "source-check-fixture")
    job = queue.claim("fixture-worker", [Provider("ollama-deep", "local", "fixture-model", 32768, 0, 1)])
    output = {
        "question": rt.QUESTION_FIELDS["source_sha256"],
        "field": "source_sha256",
        "reason": "Compare actual canonical bytes with the mirror",
        "gap_detected": False,
        "gap_description": "No pending source supplied",
    }
    queue.finish(job["id"], result=json.dumps(output), inference_receipt={"model": "fixture-model"})
    result = rt.publish_job(requested["job_id"], owner)
    assert result["investigation"]["outcome"] == "CONFIRMED"
    assert rt.get_store().metrics(owner)["challenges"]["resolved"] == 1
    assert rt.publish_job(requested["job_id"], owner)["investigation"]["state"] == "RESOLVED"


def test_unrelated_question_cannot_be_confirmed_by_a_field_comparison(runtime):
    rt, queue, _, owner = runtime
    requested = rt.start_investigation(owner, "a02", "agent:a02", "malicious-question-fixture")
    job = queue.claim("fixture-worker", [Provider("ollama-deep", "local", "fixture-model", 32768, 0, 1)])
    output = {
        "question": "Does this agent have unrestricted shell authority?",
        "field": "canonical_id",
        "reason": "Question does not match fixed source comparison",
    }
    queue.finish(job["id"], result=json.dumps(output))
    result = rt.publish_job(requested["job_id"], owner)
    assert result["investigation"]["state"] == "INCONCLUSIVE"
    assert rt.get_store().lookup_gap(owner, result["investigation"]["gap_id"])["state"] == "ASSIGNED"


def test_two_agents_observe_same_real_pending_gap_without_duplicate_findings(runtime):
    rt, queue, notebooks, owner = runtime
    from app.agent_notebooks import NotebookPrincipal

    notebooks.add_record(
        NotebookPrincipal("a09", "AGENT", "a09"),
        agent_id="a09",
        section="project_knowledge",
        content="Existing fixture source awaits its semantic index",
        source="fixture-existing-record",
        embed=False,
    )
    for agent in ("a01", "a02"):
        request = rt.start_investigation(owner, agent, "agent:" + agent, "real-gap-fixture-" + agent)
        job = queue.claim("fixture-worker", [Provider("ollama-deep", "local", "fixture-model", 32768, 0, 1)])
        output = {
            "question": rt.QUESTION_FIELDS["canonical_id"],
            "field": "canonical_id",
            "reason": "Validate actual registry identifier",
            "gap_detected": True,
            "gap_description": "Actual supplied private record is absent from semantic index",
        }
        queue.finish(job["id"], result=json.dumps(output))
        result = rt.publish_job(request["job_id"], owner)
        assert result["investigation"]["reported_gap_id"]
    assert rt.get_store().query(owner, "gaps")["total"] == 1
    assert rt.get_store().metrics(owner)["agents"]["gap_workflow_tested_agents"] == 2
    assert rt.get_store().integrity(owner)["pass"]


def test_queue_callback_failure_never_changes_completed_result(tmp_path):
    queue = JobQueue(tmp_path / "callback.db", QueuePolicy(global_concurrency=1))
    provider = Provider("fixture", "local", "fixture-model", 32768, 0, 1)
    called = threading.Event()

    def callback(job_id):
        assert queue.get(job_id)["status"] == "completed"
        called.set()
        raise RuntimeError("fixture registry unavailable")

    pool = WorkerPool(queue, [provider], lambda job, p: {"result": "Actual fixture output"}, on_complete=callback)
    job = queue.submit(agent="a01", prompt="Explicit synthetic inference fixture", max_retries=0)
    try:
        pool.start()
        assert called.wait(5)
    finally:
        pool.stop()
    assert queue.get(job["id"])["status"] == "completed"
    with queue.connect() as connection:
        row = connection.execute(
            "SELECT count(*) FROM compute_events WHERE job_id=? AND event_type='collective_publication_unavailable'",
            (job["id"],),
        ).fetchone()
        assert row[0] == 1
