"""Synthetic signing operation only; no Azure credential or live key is used."""
import base64
import hashlib
import io
import json
from email.message import Message
from urllib import error
from urllib import request, response
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.agent_cert_azure_es256 import (
    AzureES256CertificationVerifier, azure_es256_signed_bytes,
)
from app.agent_cert_azure_signer import (
    ProtectedAzureES256Signer, _NoRedirect, _NO_REDIRECT_OPENER,
    key_vault_sign_digest,
)


SERVICE = "svc.cert-verifier.independent"
KEY_ID = "https://samplevault.vault.azure.net/keys/cert-key/" + "a" * 32
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


def _b64(number):
    return base64.urlsafe_b64encode(number.to_bytes(32, "big")).rstrip(b"=").decode()


def _fixture(tmp_path):
    private = ec.generate_private_key(ec.SECP256R1())
    point = private.public_key().public_numbers()
    public = {"kty": "EC", "crv": "P-256", "x": _b64(point.x), "y": _b64(point.y)}
    calls = []

    def key_vault_stub(digest):
        calls.append(digest)
        der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        r, s = utils.decode_dss_signature(der)
        return KEY_ID, r.to_bytes(32, "big") + s.to_bytes(32, "big")

    signer = ProtectedAzureES256Signer(SERVICE, KEY_ID, public, key_vault_stub)
    payload = b"independently checked result"
    root = tmp_path / "evidence"
    subject = root / "a17"
    subject.mkdir(parents=True)
    (subject / "result.txt").write_bytes(payload)
    row = {
        "agent_id": "a17", "capability_id": "responsibility.a17",
        "dimension": "role", "test_case": "normal",
        "certification_test": "synthetic.reviewed-case", "test_version": "1",
        "test_result": "PASS", "verifier": "a18", "executor_identity": "a17",
        "evidence": "result.txt", "evidence_sha256": hashlib.sha256(payload).hexdigest(),
        "certified_at": (NOW - timedelta(hours=1)).isoformat(),
        "last_revalidated": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "source_revision": "a" * 40, "authority_scope": "restricted",
    }
    digest = hashlib.sha256(azure_es256_signed_bytes(row, SERVICE, KEY_ID)).hexdigest()
    return signer, public, calls, root, row, digest


def test_protected_azure_signer_round_trip_and_tamper(tmp_path):
    signer, public, calls, root, row, digest = _fixture(tmp_path)
    signed = signer.sign(row, approved_digest=digest, evidence_root=root,
                         source_revision=row["source_revision"], now=NOW)
    assert len(calls) == 1
    assert AzureES256CertificationVerifier({SERVICE: {KEY_ID: public}})(signed)
    signed["evidence_sha256"] = "0" * 64
    assert not AzureES256CertificationVerifier({SERVICE: {KEY_ID: public}})(signed)


def test_review_or_artifact_failure_never_calls_key_vault(tmp_path):
    signer, _, calls, root, row, digest = _fixture(tmp_path)
    with pytest.raises(ValueError, match="independent review"):
        signer.sign(row, approved_digest="0" * 64, evidence_root=root,
                    source_revision=row["source_revision"], now=NOW)
    (root / "a17" / "result.txt").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="artifact digest"):
        signer.sign(row, approved_digest=digest, evidence_root=root,
                    source_revision=row["source_revision"], now=NOW)
    assert calls == []


def test_wrong_key_response_fails_closed(tmp_path):
    signer, public, _, root, row, digest = _fixture(tmp_path)
    wrong = ProtectedAzureES256Signer(SERVICE, KEY_ID, public,
                                        lambda digest: (KEY_ID[:-32] + "b" * 32, b"x" * 64))
    with pytest.raises(ValueError, match="response key"):
        wrong.sign(row, approved_digest=digest, evidence_root=root,
                   source_revision=row["source_revision"], now=NOW)
    wrong = ProtectedAzureES256Signer(SERVICE, KEY_ID, public,
                                        lambda digest: (KEY_ID, b"x" * 64))
    with pytest.raises(ValueError, match="pinned public-key"):
        wrong.sign(row, approved_digest=digest, evidence_root=root,
                   source_revision=row["source_revision"], now=NOW)


def test_key_vault_transport_posts_one_exact_digest_without_exposing_token():
    digest = bytes(range(32))
    signature = bytes(range(64))
    expected = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    calls = []

    def opener(operation, *, timeout):
        calls.append((operation, timeout))
        return io.BytesIO(json.dumps({"kid": KEY_ID, "value": expected}).encode())

    assert key_vault_sign_digest(KEY_ID, digest, access_token="protected-test-token",
                                 opener=opener) == (KEY_ID, signature)
    assert len(calls) == 1
    operation, timeout = calls[0]
    assert operation.full_url == KEY_ID + "/sign?api-version=7.4"
    assert timeout == 15
    assert operation.get_method() == "POST"
    assert operation.get_header("Authorization") == "Bearer protected-test-token"
    assert json.loads(operation.data) == {
        "alg": "ES256",
        "value": base64.urlsafe_b64encode(digest).rstrip(b"=").decode(),
    }


@pytest.mark.parametrize("response", [
    {"kid": KEY_ID[:-32] + "b" * 32, "value": "A" * 86},
    {"kid": KEY_ID, "value": "A" * 85},
    {"kid": KEY_ID, "value": "!" * 86},
])
def test_key_vault_transport_rejects_wrong_key_or_invalid_signature(response):
    with pytest.raises(ValueError):
        key_vault_sign_digest(KEY_ID, b"x" * 32, access_token="protected-test-token",
                              opener=lambda operation, timeout: io.BytesIO(json.dumps(response).encode()))


def test_key_vault_transport_rejects_duplicate_fields_and_malformed_input():
    with pytest.raises(ValueError, match="duplicate"):
        key_vault_sign_digest(KEY_ID, b"x" * 32, access_token="protected-test-token",
                              opener=lambda operation, timeout: io.BytesIO(
                                  ('{"kid":"' + KEY_ID + '","kid":"' + KEY_ID + '","value":"' +
                                   base64.urlsafe_b64encode(b"s" * 64).rstrip(b"=").decode() + '"}').encode()))
    with pytest.raises(ValueError, match="digest"):
        key_vault_sign_digest(KEY_ID, b"x", access_token="protected-test-token")
    with pytest.raises(ValueError, match="token"):
        key_vault_sign_digest(KEY_ID, b"x" * 32, access_token="unsafe\nheader")


def test_key_vault_transport_redacts_remote_error_and_bounds_response():
    def denied(operation, timeout):
        raise error.HTTPError(operation.full_url, 403, "private upstream detail", {}, None)

    with pytest.raises(ValueError, match="^Key Vault signing unavailable$") as failure:
        key_vault_sign_digest(KEY_ID, b"x" * 32, access_token="protected-test-token",
                              opener=denied)
    assert failure.value.__cause__ is None
    with pytest.raises(ValueError, match="response exceeds limit"):
        key_vault_sign_digest(KEY_ID, b"x" * 32, access_token="protected-test-token",
                              opener=lambda operation, timeout: io.BytesIO(b"x" * 8193))


def test_key_vault_transport_never_forwards_bearer_on_redirect():
    assert any(isinstance(handler, _NoRedirect) for handler in _NO_REDIRECT_OPENER.handlers)
    visited = []

    class RedirectingHTTPS(request.HTTPSHandler):
        def https_open(self, operation):
            visited.append(operation.full_url)
            headers = Message()
            headers["Location"] = "https://example.org/capture"
            reply = response.addinfourl(io.BytesIO(), headers, operation.full_url, code=302)
            reply.msg = "Found"
            return reply

    isolated = request.build_opener(RedirectingHTTPS(), _NoRedirect())
    with pytest.raises(ValueError, match="^Key Vault signing unavailable$"):
        key_vault_sign_digest(KEY_ID, b"x" * 32, access_token="protected-test-token",
                              opener=isolated.open)
    assert visited == [KEY_ID + "/sign?api-version=7.4"]
