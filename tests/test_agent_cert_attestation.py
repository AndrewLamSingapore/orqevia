"""Synthetic signatures only; no agent or key is live-certified by these tests."""
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agent_cert_attestation import (
    CertificationAttestationVerifier, _authenticated_bytes,
)
from app.agent_certification import AgentCertificationRegistry, REQUIRED_CASES


KEY_A = b"a" * 32  # Synthetic test fixture, never a deployment credential.
KEY_B = b"b" * 32
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
REVISION = "a" * 40


def signed(row, key=KEY_A, key_id="test-key-v1"):
    result = dict(row)
    result["attestation"] = {"algorithm": "HMAC-SHA256", "key_id": key_id,
                             "signature": "0" * 64}
    result["attestation"]["signature"] = hmac.new(
        key, _authenticated_bytes(result, key_id), hashlib.sha256
    ).hexdigest()
    return result


def record(**overrides):
    row = {"agent_id": "a17", "capability_id": "responsibility.a17",
           "dimension": "baseline", "test_case": "identity",
           "certification_test": "synthetic.identity", "test_version": "1",
           "test_result": "PASS", "verifier": "a18", "evidence": "identity.txt",
           "evidence_sha256": "f" * 64,
           "certified_at": (NOW - timedelta(hours=1)).isoformat(),
           "last_revalidated": NOW.isoformat(),
           "expires_at": (NOW + timedelta(days=1)).isoformat(),
           "source_revision": REVISION, "authority_scope": "restricted"}
    return {**row, **overrides}


def verifier(**key_overrides):
    return CertificationAttestationVerifier(
        key_overrides or {"a18": {"test-key-v1": KEY_A}})


def test_valid_mac_requires_exact_trusted_verifier_and_key_binding():
    proof = signed(record())
    assert verifier()(proof)
    assert not CertificationAttestationVerifier({})(proof)
    assert not verifier(a18={"other-key": KEY_A})(proof)
    assert not verifier(a18={"test-key-v1": KEY_B})(proof)
    assert not verifier(a19={"test-key-v1": KEY_A})(proof)


@pytest.mark.parametrize("field,value", [
    ("agent_id", "a19"), ("capability_id", "responsibility.a18"),
    ("dimension", "role"), ("test_case", "normal"),
    ("test_result", "FAIL"), ("verifier", "a19"),
    ("evidence", "other.txt"), ("evidence_sha256", "0" * 64),
    ("source_revision", "b" * 40), ("authority_scope", "advisory"),
    ("expires_at", (NOW + timedelta(days=2)).isoformat()),
])
def test_any_unsigned_record_mutation_is_denied(field, value):
    proof = signed(record())
    proof[field] = value
    assert not verifier()(proof)


def test_unsigned_extra_field_signature_and_key_selection_tampering_denied():
    proof = signed(record())
    proof["health"] = "HEALTHY"
    assert not verifier()(proof)
    proof = signed(record())
    proof["attestation"]["key_id"] = "other-key"
    assert not verifier(a18={"test-key-v1": KEY_A, "other-key": KEY_A})(proof)
    proof = signed(record())
    proof["attestation"]["algorithm"] = "none"
    assert not verifier()(proof)
    proof = signed(record())
    proof["attestation"]["extra"] = "ignored?"
    assert not verifier()(proof)


@pytest.mark.parametrize("attestation", [
    None, {}, {"algorithm": "HMAC-SHA256", "key_id": "test-key-v1"},
    {"algorithm": "HMAC-SHA256", "key_id": "test-key-v1", "signature": "0"},
    {"algorithm": "HMAC-SHA256", "key_id": "../escape", "signature": "0" * 64},
])
def test_missing_or_malformed_attestation_denied(attestation):
    assert not verifier()({**record(), "attestation": attestation})


def test_self_attestation_aliases_invalid_key_and_oversized_record_fail_closed():
    assert not verifier()(signed(record(verifier="a17")))
    assert not verifier()(signed(record(verifier="test")))
    assert not verifier()(signed(record(agent_id="coding")))
    oversized = signed(record())
    oversized["extra"] = "x" * 70000
    assert not verifier()(oversized)
    with pytest.raises(ValueError):
        CertificationAttestationVerifier({"a18": {"short": b"short"}})
    with pytest.raises(ValueError):
        CertificationAttestationVerifier({"test": {"test-key-v1": KEY_A}})


def test_registry_accepts_only_authenticated_current_artifact_rows(tmp_path):
    agent_dir = tmp_path / "a17"
    agent_dir.mkdir()
    rows = []
    for case in REQUIRED_CASES["baseline"]:
        artifact = f"{case}.txt"
        payload = f"synthetic:{case}".encode()
        (agent_dir / artifact).write_bytes(payload)
        rows.append(signed(record(test_case=case, evidence=artifact,
                                  evidence_sha256=hashlib.sha256(payload).hexdigest())))
    manifest = agent_dir / "certification.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "records": rows}))
    project = lambda callback: AgentCertificationRegistry(
        tmp_path, source_revision=REVISION, verify_record=callback
    ).project("a17", "responsibility.a17", now=NOW)
    assert project(verifier())["level"] == "L1"
    assert project(CertificationAttestationVerifier({}))["level"] == "L0"
    rows[0]["evidence_sha256"] = "0" * 64
    manifest.write_text(json.dumps({"schema_version": "1.0", "records": rows}))
    assert project(verifier())["level"] == "L0"
