import copy
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.action_harness import (
    ActionEnvelopeIssuer,
    ActionHarness,
    HarnessPolicy,
    HarnessUnavailable,
    HarnessedExecutor,
)


SECRET = b"0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def proposal(actor="a14", action="web.search", risk="advisory"):
    return {
        "tenant_id": "personal",
        "actor_id": actor,
        "actor_type": "reasoner",
        "action": action,
        "parameters": {"query": "water quality"},
        "context": {"risk": risk},
        "correlation_id": f"trace-{actor}-{action}",
        "idempotency_key": f"job-{actor}-{action}",
        "schema_version": "1.0.0",
        "timestamp": NOW.isoformat(),
    }


def setup(tmp_path):
    issuer = ActionEnvelopeIssuer(SECRET)
    harness = ActionHarness(tmp_path / "harness.db", {"authority-v0": SECRET})
    return issuer, harness


def issue(issuer, value, **kwargs):
    return issuer.issue(
        value,
        decision_id="spine-decision-1",
        policy_version="harness-v0",
        now=NOW,
        **kwargs,
    )


def test_three_pilot_agents_receive_signed_leases(tmp_path):
    issuer, harness = setup(tmp_path)
    for actor in ("a14", "a16", "a21"):
        envelope = issue(issuer, proposal(actor=actor))
        assert harness.authorize(envelope, now=NOW).authorized


def test_unknown_agent_and_forged_envelope_fail_closed(tmp_path):
    issuer, harness = setup(tmp_path)
    unknown = issue(issuer, proposal(actor="a17"))
    assert harness.authorize(unknown, now=NOW).reason == "actor is outside the Harness v0 pilot"

    forged = issue(issuer, proposal())
    forged["parameters"]["query"] = "changed after signing"
    decision = harness.authorize(forged, now=NOW)
    assert not decision.authorized
    assert decision.reason == "signature verification failed"


def test_expiry_nonce_replay_and_execution_replay_are_rejected(tmp_path):
    issuer, harness = setup(tmp_path)
    expired = issuer.issue(
        proposal(),
        decision_id="old",
        policy_version="harness-v0",
        ttl_seconds=30,
        now=NOW - timedelta(minutes=2),
    )
    assert harness.authorize(expired, now=NOW).reason == "authorization or lease expired"

    envelope = issue(issuer, proposal())
    assert harness.authorize(envelope, now=NOW).authorized
    assert harness.authorize(envelope, now=NOW).reason == "nonce replay"
    assert harness.revalidate_for_execution(envelope, now=NOW).authorized
    assert harness.revalidate_for_execution(envelope, now=NOW).reason == "lease replay"


def test_revocation_and_policy_change_are_checked_at_execution_time(tmp_path):
    issuer, harness = setup(tmp_path)
    revoked = issue(issuer, proposal())
    assert harness.authorize(revoked, now=NOW).authorized
    harness.revoke(revoked["authorization"]["lease_id"], reason="operator stop", revoked_by="human")
    assert harness.revalidate_for_execution(revoked, now=NOW).reason == "lease revoked"

    changed = issue(issuer, proposal(actor="a16"))
    assert harness.authorize(changed, now=NOW).authorized
    harness.set_policy_version("harness-v0.1")
    assert harness.revalidate_for_execution(changed, now=NOW).reason == "policy version changed"


def test_privileged_actions_require_owner_approval(tmp_path):
    issuer, harness = setup(tmp_path)
    denied = issue(
        issuer, proposal(actor="a16", action="executor.run", risk="privileged"),
        privileged=True,
    )
    assert harness.authorize(denied, now=NOW).reason == "owner approval is required for privileged execution"

    approved = issue(
        issuer, proposal(actor="a16", action="executor.run", risk="privileged"),
        privileged=True, owner_approval_id="owner-approval-1",
    )
    assert harness.authorize(approved, now=NOW).authorized


def test_privileged_ledger_failure_halts_before_executor(tmp_path):
    issuer, harness = setup(tmp_path)
    envelope = issue(
        issuer, proposal(actor="a16", action="executor.run", risk="privileged"),
        privileged=True, owner_approval_id="owner-approval-1",
    )

    def unavailable():
        raise sqlite3.OperationalError("disk unavailable")

    harness.connect = unavailable
    with pytest.raises(HarnessUnavailable):
        harness.authorize(envelope, now=NOW)


def test_executor_is_unreachable_when_lease_is_invalid(tmp_path):
    issuer, harness = setup(tmp_path)
    envelope = issue(issuer, proposal())
    assert harness.authorize(envelope, now=NOW).authorized
    harness.revoke(envelope["authorization"]["lease_id"], reason="stop", revoked_by="human")
    calls = []
    executor = HarnessedExecutor(harness, lambda value: calls.append(value) or "executed")
    with pytest.raises(PermissionError):
        executor.execute(envelope, now=NOW)
    assert calls == []


def test_audit_reconstruction_is_ordered_and_complete(tmp_path):
    issuer, harness = setup(tmp_path)
    envelope = issue(issuer, proposal())
    assert harness.authorize(envelope, now=NOW).authorized
    assert harness.revalidate_for_execution(envelope, now=NOW).authorized
    trace = harness.reconstruct(envelope["correlation_id"])
    assert len(trace["decisions"]) == 1
    assert len(trace["executions"]) == 1
    assert [event["event_type"] for event in trace["events"]] == [
        "authorization.accepted", "execution.permitted"
    ]


def test_advisory_ledger_failure_is_closed_by_default(tmp_path):
    issuer, harness = setup(tmp_path)
    envelope = issue(issuer, proposal())

    def unavailable():
        raise sqlite3.OperationalError("disk unavailable")

    harness.connect = unavailable
    decision = harness.authorize(envelope, now=NOW)
    assert not decision.authorized
    assert decision.reason == "ledger unavailable"
