"""Pinned public verification of the 20261019 signed initialization closure."""

import hashlib
import json
from pathlib import Path

from scripts.agent_cert_reviewed_signing import (
    AzureES256CertificationVerifier,
    SERVICE,
)

ROOT = Path(__file__).resolve().parents[1]
SIGNED = ROOT / "governance/fresh29-20261019-signed-cases-39237401371.json"
MANIFEST = ROOT / "governance/agent-cert-reviewed-cases.json"
PIN = ROOT / "governance/agent-cert-verifier-azure-pins.json"
SIGNED_SHA256 = "192ced6249dd32218a0f89b1f70b3db22e4f32c776a9fab77265a51b968bfb50"


def test_signed_cases_match_manifest_and_verify_against_pinned_key():
    raw = SIGNED.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SIGNED_SHA256
    payload = json.loads(raw)
    manifest = json.loads(MANIFEST.read_bytes())["cases"]
    pin = json.loads(PIN.read_bytes())
    verifier = AzureES256CertificationVerifier({SERVICE: {pin["key_id"]: pin["jwk"]}})

    assert payload["state"] == "SIGNED_CASE_EVIDENCE"
    assert payload["signed_case_count"] == 29
    assert len(payload["signed_cases"]) == len(manifest) == 29
    assert payload["l7_awarded"] is False
    assert payload["protected_invocation_source_revision"] == ("3e498389e7c2aed9bdd8a02ffdfa792902d1e7ab")

    for admitted, signed in zip(manifest, payload["signed_cases"]):
        assert verifier(signed) is True
        assert signed["attestation"]["key_id"] == pin["key_id"]
        for key, value in admitted["record"].items():
            assert signed[key] == value
        assert signed["evidence_sha256"] == admitted["execution_sha256"]
        assert signed["review_evidence_sha256"] == admitted["review_sha256"]
        assert signed["expires_at"] == "2026-10-20T10:21:09.966142+00:00"
