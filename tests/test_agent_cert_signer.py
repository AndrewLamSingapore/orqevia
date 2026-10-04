"""Synthetic in-memory key only; no live verifier identity is provisioned."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.agent_cert_ed25519 import _signed_bytes, verifier_from_pin_file
from app.agent_cert_signer import ProtectedCertificationSigner


SERVICE = "svc.cert-verifier.independent"
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
REVISION = "a" * 40


def record(payload):
    return {
        "agent_id": "a17", "capability_id": "responsibility.a17",
        "dimension": "role", "test_case": "normal",
        "certification_test": "synthetic.reviewed-case", "test_version": "1",
        "test_result": "PASS", "verifier": "a18", "executor_identity": "a17",
        "evidence": "result.txt", "evidence_sha256": hashlib.sha256(payload).hexdigest(),
        "certified_at": (NOW - timedelta(hours=1)).isoformat(),
        "last_revalidated": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "source_revision": REVISION, "authority_scope": "restricted",
    }


def test_protected_signer_and_pinned_public_key_round_trip(tmp_path):
    subject = tmp_path / "evidence" / "a17"
    subject.mkdir(parents=True)
    payload = b"synthetic reviewed result"
    (subject / "result.txt").write_bytes(payload)
    private = Ed25519PrivateKey.generate()
    signer = ProtectedCertificationSigner(SERVICE, "test-v1", private)
    row = record(payload)
    digest = hashlib.sha256(_signed_bytes(row, SERVICE, "test-v1")).hexdigest()
    pin = tmp_path / "pins.json"
    pin.write_text(json.dumps({
        "schema_version": "1.0", "service_identity": SERVICE,
        "keys": {"test-v1": {
            "public_key_hex": signer.public_key.hex(),
            "sha256": hashlib.sha256(signer.public_key).hexdigest(),
        }},
    }), encoding="utf-8")
    signed = signer.sign(row, approved_digest=digest,
                         evidence_root=tmp_path / "evidence",
                         source_revision=REVISION, now=NOW)
    assert verifier_from_pin_file(pin)(signed)
    assert "private" not in json.dumps(signed).lower()
    signed["source_revision"] = "b" * 40
    assert not verifier_from_pin_file(pin)(signed)

    with pytest.raises(ValueError, match="independent review"):
        signer.sign(row, approved_digest="0" * 64,
                    evidence_root=tmp_path / "evidence", source_revision=REVISION, now=NOW)
    (subject / "result.txt").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="artifact digest"):
        signer.sign(row, approved_digest=digest,
                    evidence_root=tmp_path / "evidence", source_revision=REVISION, now=NOW)


def test_empty_or_substituted_pin_fails_closed(tmp_path):
    pin = tmp_path / "pins.json"
    pin.write_text(json.dumps({"schema_version": "1.0", "service_identity": SERVICE,
                               "keys": {}}), encoding="utf-8")
    assert not verifier_from_pin_file(pin)({})
    pin.write_text(json.dumps({"schema_version": "1.0", "service_identity": SERVICE,
                               "keys": {"test-v1": {"public_key_hex": "0" * 64,
                                                    "sha256": "f" * 64}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        verifier_from_pin_file(pin)
