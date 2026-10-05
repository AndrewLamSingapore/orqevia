"""Protected-main Azure ES256 sign/verify canary; never certifies an agent."""
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


CLIENT_ID = "d3779443-01fe-4bdc-9986-9db3ae98893e"
TENANT_ID = "067196c1-a282-4f8d-a7c5-753ca4ae5b48"
AUDIENCE = "api://AzureADTokenExchange"
SUBJECT = "repo:AndrewLamSingapore@313231443/prime@1345668764:ref:refs/heads/main"
CALLER = "AndrewLamSingapore/prime/.github/workflows/prime-verifier-oidc.yml@refs/heads/main"
SIGNER = "AndrewLamSingapore/prime/.github/workflows/prime-verifier-signer.yml@refs/heads/main"
KEY_PREFIX = "https://abexprimeverify26.vault.azure.net/keys/prime-agent-cert-verifier/"


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = request.build_opener(_NoRedirect())


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _read_json(operation, *, limit=8192):
    try:
        with _OPENER.open(operation, timeout=15) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("oversize response")
        value = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise ValueError("non-object response")
        return value
    except Exception:
        # Upstream error text or URL may contain a bearer.
        raise ValueError("protected exchange unavailable") from None


def _decode(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64url")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != value:
        raise ValueError("noncanonical base64url")
    return raw


def _oidc():
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
    if not url.startswith("https://"):
        raise ValueError("invalid OIDC endpoint")
    separator = "&" if "?" in url else "?"
    operation = request.Request(
        url + separator + parse.urlencode({"audience": AUDIENCE}),
        headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]},
    )
    assertion = _read_json(operation).get("value")
    if not isinstance(assertion, str) or len(assertion) > 16384:
        raise ValueError("invalid OIDC assertion")
    parts = assertion.split(".")
    if len(parts) != 3:
        raise ValueError("invalid OIDC assertion")
    claims = json.loads(_decode(parts[1]), object_pairs_hook=_unique)
    required = {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": AUDIENCE, "sub": SUBJECT,
        "repository": "AndrewLamSingapore/prime",
        "repository_id": "1345668764", "repository_owner_id": "313231443",
        "ref": "refs/heads/main", "ref_protected": "true",
        "workflow_ref": CALLER, "job_workflow_ref": SIGNER,
        "workflow_sha": os.environ["GITHUB_SHA"],
        "job_workflow_sha": os.environ["GITHUB_SHA"],
        "event_name": "workflow_dispatch",
    }
    if any(str(claims.get(name)).lower() != value.lower() for name, value in required.items()):
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


def _sign(key_id, digest, bearer):
    payload = json.dumps({
        "alg": "ES256",
        "value": base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii"),
    }, separators=(",", ":")).encode("ascii")
    operation = request.Request(
        key_id + "/sign?api-version=7.4", data=payload, method="POST",
        headers={"Authorization": "Bearer " + bearer, "Content-Type": "application/json"},
    )
    result = _read_json(operation)
    if result.get("kid") != key_id:
        raise ValueError("Key Vault response key mismatch")
    signature = _decode(result.get("value"))
    if len(signature) != 64:
        raise ValueError("invalid ES256 signature")
    return signature


def _public(pin):
    if set(pin) != {"kty", "crv", "x", "y"} or pin["kty"] != "EC" or pin["crv"] != "P-256":
        raise ValueError("reviewed P-256 public pin required")
    x, y = (_decode(pin[name]) for name in ("x", "y"))
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
    if not isinstance(key_id, str) or not re.fullmatch(re.escape(KEY_PREFIX) + r"[0-9a-f]{32}", key_id):
        raise ValueError("reviewed versioned key pin required")
    public = _public(pin.get("jwk", {}))
    if (os.environ.get("GITHUB_REPOSITORY") != "AndrewLamSingapore/prime"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_REF_PROTECTED") != "true"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise ValueError("protected main required")
    assertion = _oidc()
    bearer = _azure_token(assertion)
    message = ("prime.independent-verifier.live-canary.v1\n"
               + os.environ["GITHUB_SHA"] + "\n" + os.environ["GITHUB_RUN_ID"]).encode("ascii")
    signature = _sign(key_id, hashlib.sha256(message).digest(), bearer)
    if not verify(public, message, signature) or verify(public, message + b"!", signature):
        raise ValueError("Azure signature verification failed")
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
        raise SystemExit("protected Azure signing canary unavailable") from None


if __name__ == "__main__":
    main()
