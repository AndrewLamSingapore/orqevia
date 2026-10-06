"""Synthetic signatures exercise the local Observatory boundary, not live certification."""
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from fastapi.testclient import TestClient

from app.agent_cert_azure_es256 import azure_es256_signing_digest


SOURCE = "a" * 40
SERVICE = "svc.cert-verifier.independent"
KEY_ID = "https://samplevault.vault.azure.net/keys/cert-key/" + "a" * 32
ROUTE = "/control/api/agent-capabilities"


def _coordinate(value):
    return base64.urlsafe_b64encode(value.to_bytes(32, "big")).rstrip(b"=").decode()


def _pin(private):
    point = private.public_key().public_numbers()
    return {"key_id": KEY_ID, "jwk": {"kty": "EC", "crv": "P-256",
                                     "x": _coordinate(point.x), "y": _coordinate(point.y)}}


def _sign(private, row):
    digest = azure_es256_signing_digest(row, SERVICE, KEY_ID)
    der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    r, s = utils.decode_dss_signature(der)
    return {**row, "attestation": {
        "algorithm": "ES256", "key_id": KEY_ID, "verifier_identity": SERVICE,
        "signature": (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex(),
    }}


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    from app import production_entry as entry

    data_root = tmp_path / "data"
    subject = data_root / "agent-certification" / "a17"
    subject.mkdir(parents=True)
    evidence = b"synthetic independently reviewed execution"
    review = b"synthetic distinct review receipt"
    (subject / "result.txt").write_bytes(evidence)
    (subject / "review.txt").write_bytes(review)
    now = datetime.now(timezone.utc)
    row = {
        "agent_id": "a17", "capability_id": "responsibility.a17",
        "dimension": "baseline", "test_case": "identity",
        "certification_test": "synthetic.identity", "test_version": "1",
        "test_result": "PASS", "verifier": "a18", "executor_identity": "a17",
        "evidence": "result.txt", "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        "review_evidence": "review.txt", "review_evidence_sha256": hashlib.sha256(review).hexdigest(),
        "review_run_id": "synthetic-run", "review_test_version": "synthetic-oracle.1",
        "review_source_revision": SOURCE,
        "certified_at": (now - timedelta(hours=2)).isoformat(),
        "last_revalidated": (now - timedelta(hours=1)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "source_revision": SOURCE, "authority_scope": "restricted",
    }
    private = ec.generate_private_key(ec.SECP256R1())
    pin_path = tmp_path / "public-pin.json"
    raw_pin = json.dumps(_pin(private), sort_keys=True).encode()
    pin_path.write_bytes(raw_pin)
    manifest = subject / "certification.json"

    def write_record(value):
        manifest.write_text(json.dumps({"schema_version": "1.0", "records": [value]}),
                            encoding="utf-8")

    write_record(_sign(private, row))
    monkeypatch.setenv("PRIME_DATA_DIR", str(data_root))
    monkeypatch.setenv("PRIME_SPINE_TOKEN", "fixture-owner-secret")
    monkeypatch.setenv("PRIME_RUNTIME_REVISION", SOURCE)
    monkeypatch.delenv("PRIME_INTERFACE_RUNTIME_REVISION", raising=False)
    monkeypatch.delenv("PRIME_AGENT_CERT_AZURE_ES256_ENABLED", raising=False)
    monkeypatch.delenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_FILE", raising=False)
    monkeypatch.delenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_SHA256", raising=False)
    client = TestClient(entry.app, base_url="http://127.0.0.1:8000",
                        client=("127.0.0.1", 43000))
    client.headers.update({"Authorization": "Bearer fixture-owner-secret"})

    def enable():
        monkeypatch.setenv("PRIME_AGENT_CERT_AZURE_ES256_ENABLED", "1")
        monkeypatch.setenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_FILE", str(pin_path))
        monkeypatch.setenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_SHA256",
                           hashlib.sha256(pin_path.read_bytes()).hexdigest())

    return {"client": client, "row": row, "private": private, "pin_path": pin_path,
            "manifest": manifest, "subject": subject, "write_record": write_record,
            "enable": enable, "monkeypatch": monkeypatch}


def _agent(body):
    return next(agent for agent in body["agents"] if agent["agent_id"] == "a17")


def _cases(body):
    return _agent(body)["proven"]["cases"]["responsibility.a17"]


def test_optional_public_pin_exposes_only_signed_case_and_no_runtime_claims(bridge):
    client = bridge["client"]
    default = client.get(ROUTE).json()
    assert default["independent_verifier"] == "UNCONFIGURED"
    assert _cases(default) == []
    assert all(agent["proven"]["level"] == "L0" for agent in default["agents"])

    bridge["enable"]()
    response = client.get(ROUTE)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["independent_verifier"] == "CONFIGURED"
    assert _cases(body) == ["baseline:identity"]
    assert _agent(body)["proven"]["level"] == "L0"
    assert _agent(body)["runtime_activation"] == "UNVERIFIED"
    assert {_agent(body)[field] for field in ("quality", "autonomy", "latency_ms", "cost_usd")} == {"UNKNOWN"}
    assert KEY_ID not in response.text
    assert _pin(bridge["private"])["jwk"]["x"] not in response.text
    assert client.get(ROUTE, headers={"Authorization": ""}).status_code == 401
    assert client.get(ROUTE, headers={"Host": "evil.example"}).status_code == 403
    bridge["monkeypatch"].delenv("PRIME_SPINE_TOKEN")
    assert client.get(ROUTE).status_code == 503


def test_missing_malformed_or_untrusted_pin_remains_unconfigured(bridge):
    bridge["enable"]()
    client, pin_path, monkeypatch = (bridge["client"], bridge["pin_path"],
                                   bridge["monkeypatch"])
    assert _cases(client.get(ROUTE).json()) == ["baseline:identity"]
    for mutation in ("missing-digest", "wrong-digest", "malformed", "private-field",
                     "wrong-curve", "missing-file", "untrusted-data-root"):
        pin_path.write_text(json.dumps(_pin(bridge["private"])), encoding="utf-8")
        bridge["enable"]()
        if mutation == "missing-digest":
            monkeypatch.delenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_SHA256")
        elif mutation == "wrong-digest":
            monkeypatch.setenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_SHA256", "0" * 64)
        elif mutation == "malformed":
            pin_path.write_text('{"key_id":"duplicate","key_id":"other"}', encoding="utf-8")
            monkeypatch.setenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_SHA256",
                               hashlib.sha256(pin_path.read_bytes()).hexdigest())
        elif mutation in {"private-field", "wrong-curve"}:
            pin = _pin(bridge["private"])
            if mutation == "private-field":
                pin["jwk"]["d"] = "never-accepted"
            else:
                pin["jwk"]["crv"] = "P-384"
            pin_path.write_text(json.dumps(pin), encoding="utf-8")
            monkeypatch.setenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_SHA256",
                               hashlib.sha256(pin_path.read_bytes()).hexdigest())
        elif mutation == "missing-file":
            monkeypatch.setenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_FILE", str(pin_path.parent / "absent.json"))
        else:
            pin_inside_data = bridge["subject"] / "pin.json"
            pin_inside_data.write_bytes(json.dumps(_pin(bridge["private"])).encode())
            monkeypatch.setenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_FILE", str(pin_inside_data))
            monkeypatch.setenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_SHA256",
                               hashlib.sha256(pin_inside_data.read_bytes()).hexdigest())
        body = client.get(ROUTE).json()
        assert body["independent_verifier"] == "UNCONFIGURED", mutation
        assert _cases(body) == [], mutation
        assert all(agent["proven"]["level"] == "L0" for agent in body["agents"])


def test_tamper_source_staleness_and_key_rotation_reject_case(bridge):
    bridge["enable"]()
    client, row, private = bridge["client"], bridge["row"], bridge["private"]
    assert _cases(client.get(ROUTE).json()) == ["baseline:identity"]

    signed = _sign(private, row)
    signed["test_case"] = "edge"
    bridge["write_record"](signed)
    assert _cases(client.get(ROUTE).json()) == []

    bridge["write_record"](_sign(private, row))
    bridge["subject"].joinpath("result.txt").write_bytes(b"tampered artifact")
    assert _cases(client.get(ROUTE).json()) == []
    bridge["subject"].joinpath("result.txt").unlink()
    missing = client.get(ROUTE).json()
    assert _cases(missing) == []
    assert _agent(missing)["runtime_activation"] == "UNVERIFIED"
    bridge["subject"].joinpath("result.txt").write_bytes(b"synthetic independently reviewed execution")

    bridge["monkeypatch"].setenv("PRIME_RUNTIME_REVISION", "b" * 40)
    assert _cases(client.get(ROUTE).json()) == []
    bridge["monkeypatch"].setenv("PRIME_RUNTIME_REVISION", SOURCE)

    now = datetime.now(timezone.utc)
    stale = {**row, "certified_at": (now - timedelta(days=2)).isoformat(),
             "last_revalidated": (now - timedelta(days=1)).isoformat(),
             "expires_at": (now - timedelta(hours=1)).isoformat()}
    bridge["write_record"](_sign(private, stale))
    assert _cases(client.get(ROUTE).json()) == []

    bridge["write_record"](_sign(private, row))
    replacement = ec.generate_private_key(ec.SECP256R1())
    pin_path = bridge["pin_path"]
    pin_path.write_text(json.dumps(_pin(replacement)), encoding="utf-8")
    bridge["monkeypatch"].setenv("PRIME_AGENT_CERT_AZURE_ES256_PIN_SHA256",
                               hashlib.sha256(pin_path.read_bytes()).hexdigest())
    body = client.get(ROUTE).json()
    assert body["independent_verifier"] == "CONFIGURED"
    assert _cases(body) == []


def test_baked_public_pin_is_exact_and_source_controlled(bridge):
    monkeypatch = bridge["monkeypatch"]
    monkeypatch.setenv("PRIME_AGENT_CERT_AZURE_ES256_ENABLED", "1")
    body = bridge["client"].get(ROUTE).json()
    assert body["independent_verifier"] == "CONFIGURED"
    assert _cases(body) == []  # Synthetic key is not the reviewed Azure key.
