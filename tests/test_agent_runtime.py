from app.agent_runtime import AgentAuthorityError, AgentAuthorityRuntime
from app.agent_registry import RegistryError, canonical_agent_id


def runtime(tmp_path):
    return AgentAuthorityRuntime(tmp_path / "agent-authority.db")


def assert_raises(exc_type, fn):
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__}")


def test_deterministic_path_uses_registered_lead_and_specialist(tmp_path):
    rt = runtime(tmp_path)
    assert rt.resolve_path("engineering", "implement code for the service") == ["a15", "a17"]
    assert rt.resolve_path("research", "compare benchmark options") == ["a06", "a08"]


def test_prime_to_lead_and_lead_to_child_handoffs_are_enforced(tmp_path):
    rt = runtime(tmp_path)
    trace = rt.begin_path(["a15", "a17"])
    rows = list(reversed(rt.recent(10)))
    assert trace
    assert [(row["source_agent"], row["target_agent"], row["status"]) for row in rows] == [
        ("prime", "a15", "allowed"),
        ("a15", "a17", "allowed"),
    ]


def test_cross_division_delegation_is_denied_and_audited(tmp_path):
    rt = runtime(tmp_path)
    assert_raises(AgentAuthorityError, lambda: rt.handoff(source="a15", target="a07", relation="delegate"))
    event = rt.recent(1)[0]
    assert event["status"] == "denied"
    assert event["allowed"] == 0


def test_unknown_agent_fails_closed():
    assert_raises(RegistryError, lambda: canonical_agent_id("invented-agent"))


def test_consequential_external_action_requires_owner_approval(tmp_path):
    rt = runtime(tmp_path)
    assert_raises(AgentAuthorityError, lambda: rt.handoff(source="a15", target="a17", relation="delegate", consequential=True, external_action=True))
    allowed = rt.handoff(source="a15", target="a17", relation="delegate", consequential=True,
                         external_action=True, owner_approved=True)
    assert allowed["allowed"] is True


def test_public_snapshot_is_sanitized_and_observable(tmp_path):
    rt = runtime(tmp_path)
    trace = rt.begin_path(["a25", "a27"])
    rt.stage(trace_id=trace, agent_id="a27", stage="verification", status="started")
    rt.stage(trace_id=trace, agent_id="a27", stage="verification", status="completed", latency_ms=12.5)
    snapshot = rt.public_snapshot()
    assert snapshot["summary"]["registered_agents"] == 29
    assert snapshot["summary"]["executions_today"] >= 1
    allowed = {"trace_id", "timestamp", "agent_id", "stage", "status", "sequence"}
    assert snapshot["events"]
    assert all(set(event) == allowed for event in snapshot["events"])
    forbidden_keys = {"prompt", "credentials", "endpoint", "result", "filesystem_path", "reason", "source_agent"}
    assert all(not forbidden_keys.intersection(event) for event in snapshot["events"])
