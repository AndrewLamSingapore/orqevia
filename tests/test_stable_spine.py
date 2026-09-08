from app.spine import SpineStore, StableSpine, classify_action, validate_envelope


def envelope(action: str, key: str = "k1"):
    return {
        "tenant_id": "personal",
        "actor_id": "prime-core",
        "actor_type": "reasoner",
        "action": action,
        "parameters": {},
        "context": {"policy_limits": {}},
        "correlation_id": f"c-{key}",
        "idempotency_key": key,
        "schema_version": "1.0.0",
        "timestamp": "2026-08-30T00:00:00Z",
    }


def test_envelope_requires_personal_tenant():
    value = envelope("web.search")
    value["tenant_id"] = "other"
    assert "tenant_id" in validate_envelope(value)


def test_platform_policy_is_fail_closed():
    assert classify_action(envelope("web.search"))["state"] == "AUTO"
    assert classify_action(envelope("email.send"))["state"] == "GATED"
    assert classify_action(envelope("trust.change"))["state"] == "PROHIBITED"
    assert classify_action(envelope("unknown.action"))["state"] == "GATED"


def test_gated_action_creates_approval_and_audit_once(tmp_path):
    spine = StableSpine(SpineStore(str(tmp_path / "spine.db")))
    first = spine.evaluate(envelope("email.send", "email-1"))
    second = spine.evaluate(envelope("email.send", "email-1"))
    assert first["execution_status"] == "PENDING_APPROVAL"
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    with spine.store.connect() as db:
        assert db.execute("select count(*) from approvals").fetchone()[0] == 1
        assert db.execute("select count(*) from audit_trail").fetchone()[0] == 1
        assert db.execute("select count(*) from event_bus").fetchone()[0] == 1


def test_approval_decision_is_deterministic(tmp_path):
    spine = StableSpine(SpineStore(str(tmp_path / "spine.db")))
    spine.evaluate(envelope("calendar.create", "cal-1"))
    approved = spine.store.decide_approval("cal-1", "approve", "owner approved")
    assert approved["status"] == "APPROVED"
    repeated = spine.store.decide_approval("cal-1", "reject", "late reject")
    assert repeated["status"] == "APPROVED"
    assert repeated["decision_recorded"] is False


def test_approval_cards_and_audit_trace_are_complete_and_non_executing(tmp_path):
    spine = StableSpine(SpineStore(str(tmp_path / "spine.db")))
    value = envelope("email.send", "email-card")
    value["parameters"] = {"draft_id": "d-1"}
    value["context"].update({"title": "Send draft", "risk": "external", "source": "owner request", "evidence": ["draft:d-1"], "reversibility": "not reversible", "expected_effect": "email delivered"})
    spine.evaluate(value, {"source": "local_ai", "reasoning_route": ["local_ai", "confidence_gate"]})
    card = spine.store.list_approvals()[0]
    assert {"risk", "source", "evidence", "reversibility", "expected_effect"} <= set(card)
    modified = spine.store.decide_approval("email-card", "modify", "remove recipient", {"recipient": None})
    assert modified["status"] == "MODIFIED"
    trace = spine.store.audit_explorer()[0]
    assert list(trace)[1:7] == ["request", "evidence", "reasoning_route", "policy", "approval", "result"]
    assert trace["result"]["execution_status"] == "PENDING_APPROVAL"
