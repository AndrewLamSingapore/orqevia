"""Missing-case planning never promotes a task into certification evidence."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agent_cert_plan import plan_missing_cases
from app.agent_certification import AgentCertificationRegistry
from app.agent_registry import load_agent_registry


NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
REVISION = "a" * 40


def test_partial_dimension_preserves_valid_case_and_only_schedules_missing(tmp_path):
    agent_dir = tmp_path / "a17"
    agent_dir.mkdir()
    payload = b"independently checked identity evidence"
    (agent_dir / "identity.txt").write_bytes(payload)
    row = {
        "agent_id": "a17", "capability_id": "responsibility.a17",
        "dimension": "baseline", "test_case": "identity",
        "certification_test": "fixture.identity", "test_version": "1",
        "test_result": "PASS", "verifier": "a18", "evidence": "identity.txt",
        "evidence_sha256": hashlib.sha256(payload).hexdigest(),
        "certified_at": (NOW - timedelta(hours=1)).isoformat(),
        "last_revalidated": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "source_revision": REVISION, "authority_scope": "restricted",
    }
    manifest = agent_dir / "certification.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "records": [row]}))
    original = manifest.read_bytes()
    registry = AgentCertificationRegistry(tmp_path, source_revision=REVISION,
                                          verify_record=lambda record: record is not None)
    projected = registry.project("a17", "responsibility.a17", now=NOW)
    assert projected["level"] == "L0"
    assert projected["valid_cases"] == ["baseline:identity"]
    assert "baseline:identity" not in projected["missing_cases"]
    planned = plan_missing_cases(registry, max_jobs=500, now=NOW)
    assert not any(p["agent_id"] == "a17" and p["case"] == "baseline:identity"
                   for p in planned)
    assert manifest.read_bytes() == original


def test_bounded_first_round_covers_21_agents_with_fixed_owned_identity_events(tmp_path):
    registry = AgentCertificationRegistry(tmp_path, source_revision=REVISION)
    plan = plan_missing_cases(registry, max_jobs=21, now=NOW)
    expected = {a["id"] for a in load_agent_registry()["agents"]}
    assert len(plan) == 21
    assert {p["agent_id"] for p in plan} == expected
    assert {p["state"] for p in plan} == {"READY_FOR_DISPATCH"}
    assert all(p['challenge']['request']['context'] == '' for p in plan)
    assert all(p['challenge']['certification'] == 'UNVERIFIED' for p in plan)
    assert all(p['challenge']['request']['max_cost_usd'] == 0 for p in plan)
    assert all(p["wave"] == 1 and p["case"] == "baseline:identity" for p in plan)
    selected = plan[0]
    key = (selected["agent_id"], selected["capability_id"], selected["case"])
    with pytest.raises(ValueError, match='reject supplied context'):
        plan_missing_cases(registry, max_jobs=1,
            case_contexts={key: 'SYNTHETIC distinct identity case'}, now=NOW)


def test_model_case_still_requires_distinct_supplied_context(tmp_path, monkeypatch):
    registry = AgentCertificationRegistry(tmp_path, source_revision=REVISION)
    item = dict(agent_id='a20', capability_id='responsibility.a20', case='role:normal')
    monkeypatch.setattr(registry,'pending_waves',lambda **_: [[item]])
    missing = plan_missing_cases(registry,max_jobs=1,now=NOW)[0]
    assert missing['state'] == 'NEEDS_CASE_CONTEXT' and missing['challenge'] is None
    key = ('a20','responsibility.a20','role:normal')
    prepared = plan_missing_cases(registry,max_jobs=1,
        case_contexts={key:'SYNTHETIC revenue=2000; variable_cost=1200'},now=NOW)[0]
    assert prepared['state'] == 'READY_FOR_DISPATCH'
    assert prepared['challenge']['request']['context'] == 'SYNTHETIC revenue=2000; variable_cost=1200'
    assert prepared['challenge']['certification'] == 'UNVERIFIED'


@pytest.mark.parametrize("limit", [0, -1, True, 1.2])
def test_reject_unbounded_or_invalid_limits(tmp_path, limit):
    with pytest.raises(ValueError):
        plan_missing_cases(AgentCertificationRegistry(tmp_path, source_revision=REVISION),
                           max_jobs=limit)
