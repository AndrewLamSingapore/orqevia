"""Synthetic P-256 signatures; no Azure key, credential, or resource is used."""
import base64
import copy
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.agent_cert_azure_es256 import (
    AzureES256CertificationVerifier, azure_es256_signed_bytes,
    azure_es256_signing_digest,
)


SERVICE = "svc.cert-verifier.independent"
KID = "https://samplevault.vault.azure.net/keys/cert-key/" + "a" * 32
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def _b64(value):
    return base64.urlsafe_b64encode(value.to_bytes(32, "big")).rstrip(b"=").decode()


def _jwk(private):
    numbers = private.public_key().public_numbers()
    return {"kty": "EC", "crv": "P-256", "x": _b64(numbers.x), "y": _b64(numbers.y)}


def _row():
    return {
        "agent_id": "a17", "capability_id": "responsibility.a17",
        "dimension": "role", "test_case": "normal",
        "certification_test": "synthetic.azure-contract", "test_version": "1",
        "test_result": "PASS", "verifier": "a18", "executor_identity": "a17",
        "evidence": "result.json", "evidence_sha256": "f" * 64,
        "certified_at": (NOW - timedelta(hours=1)).isoformat(),
        "last_revalidated": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "source_revision": "a" * 40, "authority_scope": "restricted",
    }


def _signed(private, row):
    digest = azure_es256_signing_digest(row, SERVICE, KID)
    der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    r, s = utils.decode_dss_signature(der)
    return {**row, "attestation": {
        "algorithm": "ES256", "key_id": KID,
        "verifier_identity": SERVICE,
        "signature": (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex(),
    }}


def test_exact_versioned_key_and_record_signature_round_trip():
    private = ec.generate_private_key(ec.SECP256R1())
    proof = _signed(private, _row())
    verifier = AzureES256CertificationVerifier({SERVICE: {KID: _jwk(private)}})
    assert verifier(proof)
    assert not AzureES256CertificationVerifier({})(proof)
    altered = copy.deepcopy(proof)
    altered["source_revision"] = "b" * 40
    assert not verifier(altered)
    altered = copy.deepcopy(proof)
    altered["attestation"]["key_id"] = KID[:-32] + "b" * 32
    assert not verifier(altered)
    altered = copy.deepcopy(proof)
    altered["attestation"]["signature"] = "0" * 128
    assert not verifier(altered)
    altered = copy.deepcopy(proof)
    altered["attestation"]["algorithm"] = "Ed25519"
    assert not verifier(altered)
    altered = copy.deepcopy(proof)
    altered["attestation"]["verifier_identity"] = "svc.cert-verifier.other"
    assert not verifier(altered)
    altered = copy.deepcopy(proof)
    altered["test_case"] = "edge"
    assert not verifier(altered)
    assert azure_es256_signing_digest(_row(), SERVICE, KID) == __import__("hashlib").sha256(
        azure_es256_signed_bytes(_row(), SERVICE, KID)).digest()


def test_revoked_version_and_wrong_pinned_key_fail_closed():
    private = ec.generate_private_key(ec.SECP256R1())
    proof = _signed(private, _row())
    assert not AzureES256CertificationVerifier({SERVICE: {}})(proof)
    replacement = ec.generate_private_key(ec.SECP256R1())
    assert not AzureES256CertificationVerifier({SERVICE: {KID: _jwk(replacement)}})(proof)


def test_rejects_der_signature_self_review_and_unversioned_key():
    private = ec.generate_private_key(ec.SECP256R1())
    proof = _signed(private, _row())
    verifier = AzureES256CertificationVerifier({SERVICE: {KID: _jwk(private)}})
    digest = azure_es256_signing_digest(_row(), SERVICE, KID)
    proof["attestation"]["signature"] = private.sign(
        digest, ec.ECDSA(utils.Prehashed(hashes.SHA256()))).hex()
    assert not verifier(proof)
    proof = _signed(private, _row())
    proof["verifier"] = "a17"
    assert not verifier(proof)
    with pytest.raises(ValueError, match="versioned"):
        AzureES256CertificationVerifier({SERVICE: {KID[:-33]: _jwk(private)}})


def test_rejects_wrong_curve_or_public_point_and_oversized_record():
    private = ec.generate_private_key(ec.SECP256R1())
    jwk = _jwk(private)
    with pytest.raises(ValueError, match="P-256"):
        AzureES256CertificationVerifier({SERVICE: {KID: {**jwk, "crv": "P-384"}}})
    with pytest.raises(ValueError):
        AzureES256CertificationVerifier({SERVICE: {KID: {**jwk, "x": _b64(0)}}})
    row = _row()
    row["extra"] = "x" * 70000
    with pytest.raises(ValueError, match="limit"):
        azure_es256_signing_digest(row, SERVICE, KID)
