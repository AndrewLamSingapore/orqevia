"""Automated isolated boundary tests: no actual model, tunnel or pilot dispatch."""
import copy
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.action_harness import ActionEnvelopeIssuer, ActionHarness, HarnessUnavailable
from app.agent_runtime import AgentAuthorityRuntime, AgentAuthorityError
from app.harness_execution import execute_job
from app.job_queue import JobQueue, Provider, QueuePolicy
from app.spine import StableSpine, SpineStore

SECRET = b"isolated-test-key-never-a-production-key"
LOCAL = Provider("ollama-fast", "local", "test-model", 8192, 0, 1)


@pytest.fixture
def rig(tmp_path):
    return (ActionEnvelopeIssuer(SECRET), ActionHarness(tmp_path / "h.db", {"authority-v0": SECRET}),
            StableSpine(SpineStore(str(tmp_path / "s.db"))),
            JobQueue(tmp_path / "q.db", QueuePolicy(global_concurrency=1)))


def queued(rig, actor="a14"):
    issuer, harness, spine, queue = rig
    parameters = dict(prompt_sha256=hashlib.sha256(b"test prompt").hexdigest(), priority="normal",
                      model_role="fast", ram_mb=1024, vram_mb=0, timeout_seconds=30,
                      max_retries=0, allow_cloud=False, external_execution=False)
    proposal = dict(tenant_id="personal", actor_id=actor, actor_type="reasoner", action="agent.infer",
                    parameters=parameters, context={"risk": "advisory", "policy_limits": {"cloud": False, "local_concurrency": 1}},
                    correlation_id=str(uuid.uuid4()), idempotency_key=str(uuid.uuid4()),
                    schema_version="1.0.0", timestamp=datetime.now(timezone.utc).isoformat())
    decision = "spine:" + str(uuid.uuid4())
    assert spine.evaluate(proposal, {"decision_id": decision})["execution_status"] == "AUTHORIZED"
    envelope = issuer.issue(proposal, decision_id=decision, policy_version=harness.policy_version)
    assert harness.authorize(envelope).authorized
    queue.submit(agent=actor, prompt="test prompt", model_role="fast", timeout_seconds=30,
                 max_retries=0, max_cost_usd=0, authorization_envelope=envelope, on_queued=harness.bind_queued)
    job = queue.claim("worker", [LOCAL])
    return job, envelope


def run(rig, job, infer=None, provider=LOCAL):
    return execute_job(job, provider, rig[1], rig[2], infer or Mock(return_value={"result": "done"}), queue=rig[3])


@pytest.mark.parametrize("actor", ["a14", "a16", "a21"])
def test_actual_execution_audit_and_separate_verification(rig, actor):
    job, envelope = queued(rig, actor)
    before = rig[1].reconstruct(envelope["correlation_id"])
    assert not before["executions"]
    infer = Mock(return_value={"result": "done"})
    run(rig, job, infer)
    infer.assert_called_once()
    trace = rig[1].reconstruct(envelope["correlation_id"])
    kinds = [e["event_type"] for e in trace["events"]]
    assert kinds == ["authorization.accepted", "execution.queued", "execution.claimed", "execution.started",
                     "execution.permitted", "execution.completed"]
    with rig[1].connect() as db:
        row = db.execute("SELECT * FROM harness_jobs WHERE job_id=?", (job["id"],)).fetchone()
    assert row["state"] == "completed" and row["verification_ref"] is None
    with pytest.raises(PermissionError):
        rig[1].record_verification(job["id"], result_digest="wrong", evidence_ref="test-evidence")
    rig[1].record_verification(job["id"], result_digest=row["result_digest"], evidence_ref="test-evidence")
    assert rig[1].reconstruct(envelope["correlation_id"])["events"][-1]["event_type"] == "execution.verified"


@pytest.mark.parametrize("change", ["expiry", "revocation", "policy", "nonce", "spine", "trust", "signature", "decision", "prompt", "parameters"])
def test_queued_changes_fail_before_inference(rig, monkeypatch, change):
    job, envelope = queued(rig)
    harness, spine = rig[1:3]
    if change == "expiry":
        monkeypatch.setattr("app.action_harness.utcnow", lambda: datetime.now(timezone.utc) + timedelta(minutes=6))
    elif change == "revocation":
        harness.revoke(envelope["authorization"]["lease_id"], reason="test revocation", revoked_by="test operator")
    elif change == "policy":
        other = ActionHarness(harness.db_path, {"authority-v0": SECRET})
        other.set_policy_version("new-policy")
        assert harness.policy_version == "new-policy"
    elif change == "nonce":
        with harness.connect() as db:
            db.execute("DELETE FROM harness_nonces")
    elif change == "spine":
        with spine.store.connect() as db:
            db.execute("DELETE FROM audit_trail")
    elif change == "trust":
        monkeypatch.setitem(__import__('app.spine', fromlist=['PLATFORM_POLICY']).PLATFORM_POLICY, "agent.infer", "PROHIBITED")
    elif change in {"signature", "decision"}:
        envelope["authorization"]["signature" if change == "signature" else "decision_id"] = "forged"
        job["authorization_envelope"] = json.dumps(envelope)
    elif change == "prompt":
        job["prompt"] = "changed"
    else:
        job["timeout_seconds"] += 1
    infer = Mock()
    with pytest.raises((PermissionError, HarnessUnavailable)):
        run(rig, job, infer)
    infer.assert_not_called()


@pytest.mark.parametrize("ledger", ["harness", "spine"])
def test_ledger_failure_is_closed_before_executor(rig, monkeypatch, ledger):
    job, _ = queued(rig)
    target = rig[1] if ledger == "harness" else rig[2].store
    def failed():
        raise sqlite3.OperationalError("test outage")
    monkeypatch.setattr(target, "connect", failed)
    infer = Mock()
    with pytest.raises((PermissionError, HarnessUnavailable)):
        run(rig, job, infer)
    infer.assert_not_called()


def test_replay_and_rebinding_are_closed(rig):
    job, envelope = queued(rig)
    run(rig, job)
    infer = Mock()
    with pytest.raises(PermissionError):
        run(rig, job, infer)
    with pytest.raises(HarnessUnavailable):
        rig[1].bind_queued("another-job", envelope)
    infer.assert_not_called()


@pytest.mark.parametrize("tamper", ["unsigned", "nonpilot", "cloud", "external", "retry", "binding"])
def test_worker_bypass_is_closed(rig, tamper):
    job, _ = queued(rig)
    provider = LOCAL
    if tamper == "unsigned": job["authorization_envelope"] = None
    if tamper == "nonpilot": job["agent"] = "a17"
    if tamper == "cloud": provider = Provider(LOCAL.name, "cloud", "test-model", 8192, 0, 1)
    if tamper == "external": job["external_execution"] = True
    if tamper == "retry": job["attempts"] = 2
    if tamper == "binding": job["id"] = "unbound-job"
    infer = Mock()
    with pytest.raises(PermissionError): run(rig, job, infer, provider)
    infer.assert_not_called()


def test_uncertain_inference_retains_slot_and_does_not_retry(rig):
    job, _ = queued(rig)
    with pytest.raises(TimeoutError): run(rig, job, Mock(side_effect=TimeoutError()))
    assert rig[3].finish(job["id"], error="timeout")["status"] == "failed"
    second, _ = queued(rig, "a16")
    infer = Mock()
    with pytest.raises(PermissionError, match="slot unavailable"): run(rig, second, infer)
    infer.assert_not_called()


def test_worker_loss_never_requeues_signed_job(rig):
    job, _ = queued(rig)
    with rig[3].connect() as db:
        db.execute("UPDATE compute_jobs SET lease_until=0 WHERE id=?", (job["id"],))
    assert rig[3].recover_expired() == 1
    assert rig[3].get(job["id"])["status"] == "failed"
    assert rig[3].claim("other", [LOCAL]) is None


def test_expiry_is_rechecked_after_transaction_wait(rig, monkeypatch):
    job, envelope = queued(rig)
    first = datetime.now(timezone.utc)
    times = iter([first, first + timedelta(minutes=6)])
    monkeypatch.setattr("app.action_harness.utcnow", lambda: next(times, first + timedelta(minutes=6)))
    infer = Mock()
    with pytest.raises(PermissionError, match="expired"):
        run(rig, job, infer)
    infer.assert_not_called()


@pytest.mark.parametrize("actor", ["a14", "a16", "a21", "architecture"])
def test_legacy_specialist_entry_cannot_start_pilot(tmp_path, actor):
    rt = AgentAuthorityRuntime(tmp_path / "legacy.db")
    with pytest.raises(AgentAuthorityError, match="Harness"):
        rt.stage(trace_id="legacy", agent_id=actor, stage="inference", status="started")
