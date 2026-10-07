"""Public-key-only verifier tests. No private key or live certificate is used."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app import agent_cert_ed25519 as attestation
from app.agent_certification import AgentCertificationRegistry, REQUIRED_CASES


SERVICE = "svc.cert-verifier.abex-independent"
PUBLIC = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
SIGNATURE = bytes.fromhex(
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
    "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def record():
    return {
        "agent_id": "a17", "capability_id": "responsibility.a17",
        "dimension": "role", "test_case": "failure",
        "certification_test": "repair.same-case", "test_version": "2",
        "test_result": "PASS", "verifier": "a18",
        "executor_identity": "a17", "evidence": "repair.json",
        "evidence_sha256": "f" * 64,
        "certified_at": (NOW - timedelta(hours=1)).isoformat(),
        "last_revalidated": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "source_revision": "a" * 40, "authority_scope": "restricted",
        "attestation": {
            "algorithm": "Ed25519", "key_id": "test-v1",
            "verifier_identity": SERVICE, "signature": "0" * 128,
        },
    }


class FixedMessagePublicKey:
    def __init__(self, expected):
        self.expected = expected

    def verify(self, signature, message):
        if signature != bytes(64) or message != self.expected:
            raise InvalidSignature


def verifier_for(monkeypatch, row):
    expected = attestation._signed_bytes(row, SERVICE, "test-v1")
    class FakePublicKeyType:
        @staticmethod
        def from_public_bytes(_public):
            return FixedMessagePublicKey(expected)

    monkeypatch.setattr(attestation, "Ed25519PublicKey", FakePublicKeyType)
    return attestation.Ed25519CertificationVerifier({SERVICE: {"test-v1": PUBLIC}})


def test_real_ed25519_public_verification_uses_published_rfc8032_vector():
    key = Ed25519PublicKey.from_public_bytes(PUBLIC)
    key.verify(SIGNATURE, b"")
    with pytest.raises(InvalidSignature):
        key.verify(SIGNATURE, b"changed")


def test_full_record_round_trip_uses_real_signature_only_in_memory():
    row = record()
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    row["attestation"]["signature"] = private_key.sign(
        attestation._signed_bytes(row, SERVICE, "test-v1")
    ).hex()
    verifier = attestation.Ed25519CertificationVerifier(
        {SERVICE: {"test-v1": public_bytes}}
    )
    assert verifier(row)
    altered = copy.deepcopy(row)
    altered["evidence_sha256"] = "0" * 64
    assert not verifier(altered)


def test_rejects_validly_signed_executor_self_review():
    row = record()
    row["executor_identity"] = row["verifier"]
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    row["attestation"]["signature"] = private_key.sign(
        attestation._signed_bytes(row, SERVICE, "test-v1")
    ).hex()
    verifier = attestation.Ed25519CertificationVerifier(
        {SERVICE: {"test-v1": public_bytes}}
    )
    assert not verifier(row)


def test_registry_projection_accepts_only_real_signed_current_artifacts(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    verifier = attestation.Ed25519CertificationVerifier(
        {SERVICE: {"test-v1": public_bytes}}
    )
    agent_dir = tmp_path / "a17"
    agent_dir.mkdir()
    rows = []
    for case in REQUIRED_CASES["baseline"]:
        row = record()
        row["dimension"] = "baseline"
        row["test_case"] = case
        row["evidence"] = f"{case}.txt"
        payload = f"synthetic:{case}".encode()
        (agent_dir / row["evidence"]).write_bytes(payload)
        row["evidence_sha256"] = hashlib.sha256(payload).hexdigest()
        row["attestation"]["signature"] = private_key.sign(
            attestation._signed_bytes(row, SERVICE, "test-v1")
        ).hex()
        rows.append(row)
    (agent_dir / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": rows}), encoding="utf-8"
    )
    def project(callback):
        return AgentCertificationRegistry(
            tmp_path, source_revision="a" * 40, verify_record=callback
        ).project("a17", "responsibility.a17", now=NOW)

    assert project(verifier)["level"] == "L1"
    assert project(attestation.Ed25519CertificationVerifier({}))["level"] == "L0"
    (agent_dir / rows[0]["evidence"]).write_text("tampered", encoding="utf-8")
    assert project(verifier)["level"] == "L0"


def test_complete_record_passes_with_explicit_trusted_service(monkeypatch):
    row = record()
    verifier = verifier_for(monkeypatch, row)
    assert verifier(row)
    assert not attestation.Ed25519CertificationVerifier({})(row)


@pytest.mark.parametrize("field,value", [
    ("agent_id", "a19"), ("capability_id", "responsibility.a18"),
    ("dimension", "recovery"), ("test_case", "normal"),
    ("certification_test", "generic.fixture"), ("test_version", "3"),
    ("test_result", "FAIL"), ("verifier", "a19"),
    ("executor_identity", "temporary-worker-1"), ("evidence", "other.json"),
    ("evidence_sha256", "0" * 64), ("certified_at", NOW.isoformat()),
    ("last_revalidated", (NOW + timedelta(minutes=1)).isoformat()),
    ("expires_at", (NOW + timedelta(days=2)).isoformat()),
    ("source_revision", "b" * 40), ("authority_scope", "advisory"),
])
def test_record_field_mutation_fails_signature(monkeypatch, field, value):
    row = record()
    verifier = verifier_for(monkeypatch, row)
    row[field] = value
    assert not verifier(row)


@pytest.mark.parametrize("field,value", [
    ("algorithm", "HMAC-SHA256"), ("key_id", "other-v1"),
    ("verifier_identity", "svc.cert-verifier.other"),
    ("signature", "1" * 128),
])
def test_attestation_field_mutation_fails(monkeypatch, field, value):
    row = record()
    verifier = verifier_for(monkeypatch, row)
    row["attestation"][field] = value
    assert not verifier(row)


def test_untrusted_or_revoked_key_and_extra_field_fail_closed(monkeypatch):
    row = record()
    verifier = verifier_for(monkeypatch, row)
    assert not attestation.Ed25519CertificationVerifier({SERVICE: {"revoked": PUBLIC}})(row)
    row["extra"] = "unsigned health claim"
    assert not verifier(row)
    row = record()
    row["attestation"]["extra"] = "ignored?"
    assert not verifier(row)


def test_missing_malformed_and_self_review_fail_closed(monkeypatch):
    row = record()
    verifier = verifier_for(monkeypatch, row)
    for changed in (
        {**row, "attestation": None},
        {**row, "verifier": "a17"},
        {**row, "agent_id": "coding"},
        {**row, "executor_identity": SERVICE},
        {**row, "certified_at": "2026-10-04"},
        {**row, "evidence_sha256": "short"},
        {key: value for key, value in row.items() if key != "test_version"},
    ):
        assert not verifier(changed)
    oversized = copy.deepcopy(row)
    oversized["metadata"] = "x" * 70000
    assert not verifier(oversized)
    with pytest.raises(ValueError):
        attestation.Ed25519CertificationVerifier({"a18": {"test-v1": PUBLIC}})
    with pytest.raises(ValueError):
        attestation.Ed25519CertificationVerifier({SERVICE: {"test-v1": b"short"}})
