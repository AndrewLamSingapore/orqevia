"""Synthetic contract checks; these do not claim live Azure signing."""
import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from scripts import azure_verifier_live_canary as canary


KEY_ID = "https://abexprimeverify26.vault.azure.net/keys/prime-agent-cert-verifier/" + "a" * 32


def _public(private):
    point = private.public_key().public_numbers()
    def enc(value):
        return base64.urlsafe_b64encode(value.to_bytes(32, "big")).rstrip(b"=").decode()
    return {"kty": "EC", "crv": "P-256", "x": enc(point.x), "y": enc(point.y)}


def test_pinned_canary_sign_verify_and_tamper(monkeypatch, capsys):
    private = ec.generate_private_key(ec.SECP256R1())
    pin = {"key_id": KEY_ID, "jwk": _public(private)}
    calls = []
    monkeypatch.setenv("GITHUB_REPOSITORY", "AndrewLamSingapore/prime")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_REF_PROTECTED", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setattr(canary, "_oidc", lambda: "protected-assertion")
    monkeypatch.setattr(canary, "_azure_token", lambda assertion: "protected-bearer")

    def fake_sign(key_id, digest, *, access_token):
        calls.append((key_id, digest, access_token))
        der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        r, s = utils.decode_dss_signature(der)
        return key_id, r.to_bytes(32, "big") + s.to_bytes(32, "big")

    monkeypatch.setattr(canary, "key_vault_sign_digest", fake_sign)
    canary.run(pin)
    output = json.loads(capsys.readouterr().out)
    assert output["result"] == "AZURE_PROTECTED_SIGN_VERIFY_TAMPER_PASS"
    assert output["scope"].endswith("not agent certification")
    assert len(calls) == 1 and calls[0][0] == KEY_ID
    assert calls[0][2] == "protected-bearer"
    assert len(calls[0][1]) == 32


def test_empty_pin_fails_before_authentication(monkeypatch):
    monkeypatch.setattr(canary, "_oidc", lambda: pytest.fail("unexpected OIDC request"))
    with pytest.raises(ValueError, match="reviewed versioned key pin required"):
        canary.run({"key_id": "", "jwk": {}})


def test_scope_mismatch_fails_before_authentication(monkeypatch):
    private = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setenv("GITHUB_REPOSITORY", "other/repo")
    monkeypatch.setattr(canary, "_oidc", lambda: pytest.fail("unexpected OIDC request"))
    with pytest.raises(ValueError, match="protected main required"):
        canary.run({"key_id": KEY_ID, "jwk": _public(private)})


def test_public_pin_and_signature_require_exact_bytes():
    private = ec.generate_private_key(ec.SECP256R1())
    public = canary._public_key(_public(private))
    message = b"bounded-case"
    signature_der = private.sign(message, ec.ECDSA(hashes.SHA256()))
    r, s = utils.decode_dss_signature(signature_der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    assert canary.verify(public, message, signature)
    assert not canary.verify(public, message + b"!", signature)
    assert not canary.verify(public, message, signature[:-1])
    with pytest.raises(ValueError):
        canary._public_key({**_public(private), "x": "broken"})


def test_oidc_reusable_revision_must_match_checkout(monkeypatch):
    head = "b" * 40
    monkeypatch.setenv("GITHUB_SHA", head)
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_URL", "https://oidc.example.test/token")
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "synthetic-test-only")
    claims = {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": canary.AUDIENCE, "sub": canary.SUBJECT,
        "repository": "AndrewLamSingapore/prime",
        "repository_id": "1345668764", "repository_owner_id": "313231443",
        "ref": "refs/heads/main", "ref_protected": "true",
        "workflow_ref": canary.CALLER, "job_workflow_ref": canary.SIGNER,
        "workflow_sha": head, "job_workflow_sha": head,
        "event_name": "workflow_dispatch",
    }

    def jwt():
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        return "header." + payload + ".signature"

    monkeypatch.setattr(canary, "_read_json", lambda operation: {"value": jwt()})
    assert canary._oidc() == jwt()
    claims["job_workflow_sha"] = "c" * 40
    with pytest.raises(ValueError, match="OIDC claims not bound"):
        canary._oidc()
    claims["job_workflow_sha"] = head
    claims["workflow_sha"] = "c" * 40
    with pytest.raises(ValueError, match="OIDC claims not bound"):
        canary._oidc()
