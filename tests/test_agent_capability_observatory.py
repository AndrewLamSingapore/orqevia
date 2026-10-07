import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent_capability_observatory import project_capability_observatory
from app.agent_certification import AgentCertificationRegistry, MAX_EVIDENCE_BYTES
from app.agent_registry import load_agent_registry


NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)
REVISION = "a" * 40


def _rows(root, verifier=None):
    registry = AgentCertificationRegistry(root, source_revision=REVISION,
                                          verify_record=verifier)
    return project_capability_observatory(registry, now=NOW)


def test_all_21_declared_capabilities_are_not_proven_without_evidence(tmp_path):
    rows = _rows(tmp_path)
    agents = load_agent_registry()["agents"]
    assert len(rows) == 21
    assert {row["agent_id"] for row in rows} == {agent["id"] for agent in agents}
    for row in rows:
        assert row["intended"]["capabilities"]
        assert row["proven"]["level"] == "L0"
        assert row["proven"]["trust_state"] == "UNPROVEN"
        assert all(not cases for cases in row["proven"]["cases"].values())
        assert all(cases for cases in row["missing_cases"].values())
        assert row["runtime_activation"] == "UNVERIFIED"
        assert row["provenance"]["source_revision"] == REVISION
        assert row["provenance"]["registry_version"] == "1.0.0"
        assert {row[key] for key in ("quality", "autonomy", "latency_ms", "cost_usd")} == {"UNKNOWN"}


def test_verified_case_is_visible_but_does_not_imply_dimension_or_l7(tmp_path):
    agent_dir = tmp_path / "a17"
    agent_dir.mkdir()
    payload = b"bounded independent case evidence"
    (agent_dir / "identity.txt").write_bytes(payload)
    record = {
        "agent_id": "a17", "capability_id": "responsibility.a17",
        "dimension": "baseline", "test_case": "identity",
        "certification_test": "bounded.identity", "test_version": "1",
        "test_result": "PASS", "verifier": "a18",
        "evidence": "identity.txt", "evidence_sha256": hashlib.sha256(payload).hexdigest(),
        "certified_at": (NOW - timedelta(hours=1)).isoformat(),
        "last_revalidated": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "source_revision": REVISION, "authority_scope": "restricted",
    }
    (agent_dir / "certification.json").write_text(json.dumps({
        "schema_version": "1.0", "records": [record],
    }), encoding="utf-8")

    unsigned = next(row for row in _rows(tmp_path) if row["agent_id"] == "a17")
    assert unsigned["proven"]["cases"]["responsibility.a17"] == []
    reviewed = next(row for row in _rows(tmp_path, lambda row: row["verifier"] == "a18")
                    if row["agent_id"] == "a17")
    assert reviewed["proven"]["cases"]["responsibility.a17"] == ["baseline:identity"]
    assert reviewed["proven"]["complete_dimensions"]["responsibility.a17"] == []
    assert reviewed["proven"]["level"] == "L0"
    assert reviewed["runtime_activation"] == "UNVERIFIED"

    (agent_dir / "identity.txt").write_bytes(b"tampered")
    tampered = next(row for row in _rows(tmp_path, lambda row: True)
                    if row["agent_id"] == "a17")
    assert tampered["proven"]["cases"]["responsibility.a17"] == []

    (agent_dir / "identity.txt").write_bytes(payload)
    changed_source = project_capability_observatory(
        AgentCertificationRegistry(tmp_path, source_revision="b" * 40,
                                   verify_record=lambda row: True), now=NOW)
    stale = next(row for row in changed_source if row["agent_id"] == "a17")
    assert stale["proven"]["cases"]["responsibility.a17"] == []
    assert stale["proven"]["trust_state"] == "REVALIDATION-REQUIRED"


def test_matrix_reads_each_manifest_once_and_rechecks_next_request(tmp_path, monkeypatch):
    agent = next(item for item in load_agent_registry()["agents"] if item["id"] == "a02")
    assert len(agent["capability_requirements"]) > 1
    capability = agent["capability_requirements"][0]
    agent_dir = tmp_path / "a02"
    agent_dir.mkdir()
    evidence = b"independently reviewed case"
    (agent_dir / "case.txt").write_bytes(evidence)
    manifest = agent_dir / "certification.json"
    record = {
        "agent_id": "a02", "capability_id": capability,
        "dimension": "baseline", "test_case": "identity",
        "certification_test": "bounded.identity", "test_version": "1",
        "test_result": "PASS", "verifier": "a18",
        "evidence": "case.txt", "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        "certified_at": (NOW - timedelta(hours=1)).isoformat(),
        "last_revalidated": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "source_revision": REVISION, "authority_scope": agent["authority"],
    }
    manifest.write_text(json.dumps({"schema_version": "1.0", "records": [record]}),
                        encoding="utf-8")
    original_open = Path.open
    reads = []

    def tracked_open(path, *args, **kwargs):
        if path == manifest and args and args[0] == "rb":
            reads.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)
    registry = AgentCertificationRegistry(tmp_path, source_revision=REVISION,
                                          verify_record=lambda _: True)
    first = next(row for row in registry.matrix(now=NOW) if row["agent_id"] == "a02")
    assert first["capabilities"][0]["valid_cases"] == ["baseline:identity"]
    assert reads == [manifest]

    # The next request must not reuse a stale positive projection.
    manifest.write_text(json.dumps({"schema_version": "1.0", "records": []}),
                        encoding="utf-8")
    second = next(row for row in registry.matrix(now=NOW) if row["agent_id"] == "a02")
    assert all(not item["valid_cases"] for item in second["capabilities"])
    assert reads == [manifest, manifest]


def test_oversized_manifest_fails_closed(tmp_path):
    agent_dir = tmp_path / "a17"
    agent_dir.mkdir()
    (agent_dir / "certification.json").write_bytes(b" " * (MAX_EVIDENCE_BYTES + 1))
    row = next(row for row in _rows(tmp_path, lambda _: True) if row["agent_id"] == "a17")
    assert row["proven"]["level"] == "L0"
    assert not row["proven"]["cases"]["responsibility.a17"]
