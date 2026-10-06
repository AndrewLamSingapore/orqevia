"""Disposable off-host image smoke; creates only synthetic signing material."""
import base64
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SERVICE = "svc.cert-verifier.independent"
KEY_ID = "https://samplevault.vault.azure.net/keys/cert-key/" + "a" * 32
TOKEN = "fixture-owner-secret"
ROUTE = "http://127.0.0.1:8000/control/api/agent-capabilities"


def _coordinate(number):
    return base64.urlsafe_b64encode(number.to_bytes(32, "big")).rstrip(b"=").decode()


def prepare(directory: Path, revision: str):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    from app.agent_cert_azure_es256 import azure_es256_signing_digest

    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("exact source revision required")
    directory.mkdir(parents=True, exist_ok=True)
    subject = directory / "data" / "agent-certification" / "a17"
    subject.mkdir(parents=True)
    private = ec.generate_private_key(ec.SECP256R1())
    point = private.public_key().public_numbers()
    pin = {"key_id": KEY_ID, "jwk": {"kty": "EC", "crv": "P-256",
                                     "x": _coordinate(point.x), "y": _coordinate(point.y)}}
    pin_bytes = json.dumps(pin, sort_keys=True).encode()
    (directory / "public-pin.json").write_bytes(pin_bytes)
    (directory / "pin.sha256").write_text(hashlib.sha256(pin_bytes).hexdigest(),
                                           encoding="ascii")
    execution = b"synthetic off-host case result"
    review = b"synthetic off-host independent review"
    (subject / "execution.txt").write_bytes(execution)
    (subject / "review.txt").write_bytes(review)
    now = datetime.now(timezone.utc)
    row = {
        "agent_id": "a17", "capability_id": "responsibility.a17",
        "dimension": "baseline", "test_case": "identity",
        "certification_test": "synthetic.offhost", "test_version": "1",
        "test_result": "PASS", "verifier": "a18", "executor_identity": "a17",
        "evidence": "execution.txt", "evidence_sha256": hashlib.sha256(execution).hexdigest(),
        "review_evidence": "review.txt", "review_evidence_sha256": hashlib.sha256(review).hexdigest(),
        "review_run_id": "synthetic-offhost", "review_test_version": "synthetic-oracle.1",
        "review_source_revision": revision,
        "certified_at": (now - timedelta(minutes=2)).isoformat(),
        "last_revalidated": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "source_revision": revision, "authority_scope": "restricted",
    }
    digest = azure_es256_signing_digest(row, SERVICE, KEY_ID)
    der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    r, s = utils.decode_dss_signature(der)
    row["attestation"] = {
        "algorithm": "ES256", "key_id": KEY_ID, "verifier_identity": SERVICE,
        "signature": (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex(),
    }
    (subject / "certification.json").write_text(
        json.dumps({"schema_version": "1.0", "records": [row]}), encoding="utf-8")


def _get(url, headers=None):
    try:
        with urlopen(Request(url, headers=headers or {}), timeout=3) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8")


def probe():
    for _ in range(30):
        try:
            status, _ = _get("http://127.0.0.1:8000/health")
            if status == 200:
                break
        except URLError:
            pass
        time.sleep(1)
    else:
        raise AssertionError("packaged control shell did not start")
    assert _get(ROUTE)[0] == 401
    authorization = {"Authorization": "Bearer " + TOKEN}
    assert _get(ROUTE, {**authorization, "Host": "evil.example"})[0] == 403
    status, raw = _get(ROUTE, authorization)
    assert status == 200, status
    body = json.loads(raw)
    assert body["independent_verifier"] == "CONFIGURED"
    assert len(body["agents"]) == 21
    subject = next(agent for agent in body["agents"] if agent["agent_id"] == "a17")
    assert subject["proven"]["cases"]["responsibility.a17"] == ["baseline:identity"]
    assert subject["proven"]["level"] == "L0"
    assert subject["runtime_activation"] == "UNVERIFIED"
    assert {subject[field] for field in ("quality", "autonomy", "latency_ms", "cost_usd")} == {"UNKNOWN"}
    assert KEY_ID not in raw
    assert _get("http://127.0.0.1:8000/governance/agent-cert-verifier-azure-pins.json")[0] == 404
    print("PACKAGED_OBSERVATORY_PUBLIC_VERIFIER_PASS")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "prepare":
        prepare(Path(sys.argv[2]), sys.argv[3])
    elif len(sys.argv) == 2 and sys.argv[1] == "probe":
        probe()
    else:
        raise SystemExit("usage: prepare DIR REVISION | probe")
