"""Protected-main Azure signing canary; no agent certification is awarded here.

The public pin is reviewed source configuration. No private key or bearer is
persisted. The workflow uses this only after its protected-main OIDC guard.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from urllib import parse, request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.agent_cert_azure_signer import _NO_REDIRECT_OPENER, key_vault_sign_digest
from app.agent_cert_azure_es256 import _KEY_ID


CLIENT_ID = "d3779443-01fe-4bdc-9986-9db3ae98893e"
TENANT_ID = "067196c1-a282-4f8d-a7c5-753ca4ae5b48"
AUDIENCE = "api://AzureADTokenExchange"
SUBJECT = "repo:AndrewLamSingapore@313231443/prime@1345668764:ref:refs/heads/main"
CALLER = "AndrewLamSingapore/prime/.github/workflows/prime-verifier-oidc.yml@refs/heads/main"
SIGNER = "AndrewLamSingapore/prime/.github/workflows/prime-verifier-signer.yml@refs/heads/main"
SERVICE = "svc.cert-verifier.independent"


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response field")
        result[key] = value
    return result


def _read_json(operation, *, limit=8192):
    # No bearer may follow a redirect, including to a different origin.
    try:
        with _NO_REDIRECT_OPENER.open(operation, timeout=15) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("response exceeds limit")
        value = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise ValueError("response must be object")
        return value
    except Exception:
        # Upstream error bodies and URLs may contain bearer material.
        raise ValueError("protected identity exchange unavailable") from None


def _b64decode(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64url")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != value:
        raise ValueError("noncanonical base64url")
    return raw


def _oidc():
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    if not url.startswith("https://"):
        raise ValueError("invalid OIDC endpoint")
    token = os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]
    separator = "&" if "?" in url else "?"
    operation = request.Request(
        url + separator + parse.urlencode({"audience": AUDIENCE}),
        headers={"Authorization": "Bearer " + token},
    )
    assertion = _read_json(operation)["value"]
    if not isinstance(assertion, str) or len(assertion) > 16384:
        raise ValueError("invalid OIDC assertion")
    segments = assertion.split(".")
    if len(segments) != 3:
        raise ValueError("invalid OIDC assertion")
    claims = json.loads(_b64decode(segments[1]), object_pairs_hook=_unique)
    required = {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": AUDIENCE, "sub": SUBJECT,
        "repository": "AndrewLamSingapore/prime",
        "repository_id": "1345668764", "repository_owner_id": "313231443",
        "ref": "refs/heads/main", "ref_protected": "true",
        "workflow_ref": CALLER, "job_workflow_ref": SIGNER,
        "event_name": "workflow_dispatch",
    }
    if any(str(claims.get(name)).lower() != value.lower()
           for name, value in required.items()):
        raise ValueError("OIDC claims not bound to protected verifier")
    return assertion


def _azure_token(assertion):
    endpoint = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    body = parse.urlencode({
        "client_id": CLIENT_ID,
        "scope": "https://vault.azure.net/.default",
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion,
    }).encode("ascii")
    result = _read_json(request.Request(
        endpoint, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    ))
    token = result.get("access_token")
    if result.get("token_type") != "Bearer" or not isinstance(token, str) or not token:
        raise ValueError("Azure bearer unavailable")
    return token


def _public_key(pin):
    if set(pin) != {"kty", "crv", "x", "y"} or pin["kty"] != "EC" or pin["crv"] != "P-256":
        raise ValueError("reviewed P-256 public pin required")
    x, y = (_b64decode(pin[name]) for name in ("x", "y"))
    if len(x) != 32 or len(y) != 32:
        raise ValueError("invalid P-256 coordinate")
    return ec.EllipticCurvePublicNumbers(
        int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
    ).public_key()


def verify(public, message, signature):
    if len(signature) != 64:
        return False
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    try:
        public.verify(utils.encode_dss_signature(r, s), message, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False


def run(pin):
    key_id = pin.get("key_id")
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise ValueError("reviewed versioned key pin required")
    if not key_id.startswith("https://abexprimeverify26.vault.azure.net/keys/prime-agent-cert-verifier/"):
        raise ValueError("unexpected verifier key")
    public = _public_key(pin.get("jwk", {}))
    if (os.environ.get("GITHUB_REPOSITORY") != "AndrewLamSingapore/prime"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_REF_PROTECTED") != "true"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise ValueError("protected main required")
    assertion = _oidc()
    bearer = _azure_token(assertion)
    message = ("prime.independent-verifier.live-canary.v1\n"
               + os.environ["GITHUB_SHA"] + "\n" + os.environ["GITHUB_RUN_ID"]).encode("ascii")
    observed_key, signature = key_vault_sign_digest(
        key_id, hashlib.sha256(message).digest(), access_token=bearer)
    if observed_key != key_id or not verify(public, message, signature):
        raise ValueError("Azure signature did not verify against reviewed pin")
    tampered = message + b"!"
    if verify(public, tampered, signature):
        raise ValueError("tampered canary unexpectedly verified")
    print(json.dumps({
        "result": "AZURE_PROTECTED_SIGN_VERIFY_TAMPER_PASS",
        "scope": "isolated cryptographic canary, not agent certification",
        "key_id": key_id,
        "source_revision": os.environ["GITHUB_SHA"],
        "run_id": os.environ["GITHUB_RUN_ID"],
        "message_sha256": hashlib.sha256(message).hexdigest(),
        "signature_sha256": hashlib.sha256(signature).hexdigest(),
    }, sort_keys=True))


def main():
    try:
        with open("governance/agent-cert-verifier-azure-pins.json", encoding="utf-8") as stream:
            pin = json.load(stream, object_pairs_hook=_unique)
        run(pin)
    except Exception:
        # Never print assertion, bearer, upstream body or exception chain.
        raise SystemExit("protected Azure signing canary unavailable") from None


if __name__ == "__main__":
    main()
