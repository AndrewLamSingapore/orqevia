"""Sign one fixed, reviewed A18 observation on protected main; never award L7.

The witness is a checked-in copy of a synthetic, non-certifying cloud trial.
The protected signer accepts no caller payload or artifact. Its review checks
the recorded response against the source-bound oracle before signing the exact
fixture bytes. This does not independently reproduce the transport or ledger.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re

from app.agent_cert_a17_boundary import review_a17_boundary_json, review_a17_cross_review_json


FIXTURE = Path("tests/fixtures/a18-negative-clarified-observation.json")
SOURCE = "8bf13c5d6e79b2c671789d196ed9507226de372a"
JOB_ID = "3dd7b5f7-5bc2-46d7-8f0e-db17cb4429e0"
FLAWED_SHA256 = "94dc1820421de62a1b6a6bb919bade1e19e0163f8b7d82d379aa0269ef10a8c5"
RESULT_SHA256 = "6e4e6af1a7a8da27a413ed166b803192d5be6e78a5a90bd741e16c51423c8c4c"
DOMAIN = "prime.independent-verifier.agent-observation-canary.v1"


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def reviewed_message(raw: bytes, *, revision: str, run_id: str) -> bytes:
    """Validate a bounded recorded case and bind it to the protected run."""
    if (len(raw) > 8192 or not re.fullmatch(r"[0-9a-f]{40}", revision)
            or not re.fullmatch(r"[0-9]+", run_id)):
        raise ValueError("invalid observation envelope")
    try:
        item = json.loads(raw, object_pairs_hook=_unique)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("invalid observation JSON") from None
    if not isinstance(item, dict) or set(item) != {
        "schema", "source_revision", "model", "official_case_executed",
        "ephemeral_catalog_only", "flawed_a17_json", "flawed_a17_sha256",
        "expected_failed_fields", "reviewer", "consistency_check",
        "transport_requests", "ledger_agent_correlation", "ledger_retries",
        "elapsed_ms", "certification", "signing",
    }:
        raise ValueError("observation fields changed")
    if (item["schema"] != "abex.agent_a18_negative_clarified_trial.v1"
            or item["source_revision"] != SOURCE
            or item["model"] != "Qwen/Qwen3-32B:deepinfra"
            or item["official_case_executed"] is not False
            or item["ephemeral_catalog_only"] is not True
            or item["certification"] != "UNVERIFIED"
            or item["signing"] != "NOT_ATTEMPTED"
            or type(item["transport_requests"]) is not int
            or item["transport_requests"] != 1
            or item["ledger_agent_correlation"] is not True
            or not isinstance(item["ledger_retries"], list)
            or len(item["ledger_retries"]) != 1
            or type(item["ledger_retries"][0]) is not int
            or item["ledger_retries"] != [0]
            or not isinstance(item["consistency_check"], dict)
            or item["consistency_check"].get("pass") is not True
            or item["consistency_check"].get("errors") != []
            or set(item["consistency_check"]) != {"pass", "errors"}
            or type(item["elapsed_ms"]) is not int
            or item["elapsed_ms"] != 17327):
        raise ValueError("observation scope or execution claims changed")
    flawed = item["flawed_a17_json"]
    reviewer = item["reviewer"]
    if (not isinstance(flawed, str)
            or not isinstance(reviewer, dict)
            or set(reviewer) != {"agent", "job_id", "provider", "status", "result",
                                "result_sha256", "input_tokens", "output_tokens",
                                "estimated_cost_usd"}
            or reviewer["agent"] != "a18"
            or reviewer["provider"] != "hf-qwen32b-negative-trial"
            or reviewer["status"] != "completed"
            or not isinstance(reviewer["result"], str)
            or reviewer["job_id"] != JOB_ID
            or type(reviewer["input_tokens"]) is not int
            or reviewer["input_tokens"] != 240
            or type(reviewer["output_tokens"]) is not int
            or reviewer["output_tokens"] != 358
            or type(reviewer["estimated_cost_usd"]) is not float
            or reviewer["estimated_cost_usd"] != 0.00011944):
        raise ValueError("reviewer identity or result changed")
    if (item["flawed_a17_sha256"] != FLAWED_SHA256
            or reviewer["result_sha256"] != RESULT_SHA256
            or hashlib.sha256(flawed.encode()).hexdigest() != item["flawed_a17_sha256"]
            or hashlib.sha256(reviewer["result"].encode()).hexdigest()
            != reviewer["result_sha256"]):
        raise ValueError("recorded result digest mismatch")
    valid, errors = review_a17_boundary_json(flawed)
    reviewed, review_errors = review_a17_cross_review_json(flawed, reviewer["result"])
    if (valid or errors != ("negative_one_error", "string_error", "type_guard")
            or item["expected_failed_fields"] != list(errors)
            or not reviewed or review_errors):
        raise ValueError("review failed source-bound oracle")
    body = {
        "domain": DOMAIN, "protected_source_revision": revision,
        "run_id": run_id, "observation_sha256": hashlib.sha256(raw).hexdigest(),
        "observed_agent": "a18", "observed_source_revision": SOURCE,
        "scope": "non-certifying synthetic cloud-route cross-review",
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def run(pin: dict) -> None:
    # Only the protected signer job needs the Azure/cryptography dependency.
    from scripts.azure_verifier_live_canary import (KEY_PREFIX, _azure_token, _oidc,
                                                    _public, _sign, verify)
    if (os.environ.get("GITHUB_REPOSITORY") != "AndrewLamSingapore/prime"
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_REF_PROTECTED") != "true"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise ValueError("protected main required")
    key_id = pin["key_id"]
    if (not isinstance(key_id, str)
            or not re.fullmatch(re.escape(KEY_PREFIX) + r"[0-9a-f]{32}", key_id)):
        raise ValueError("unexpected verifier key")
    public = _public(pin["jwk"])
    message = reviewed_message(FIXTURE.read_bytes(), revision=os.environ["GITHUB_SHA"],
                               run_id=os.environ["GITHUB_RUN_ID"])
    bearer = _azure_token(_oidc())
    signature = _sign(key_id, hashlib.sha256(message).digest(), bearer)
    if not verify(public, message, signature):
        raise ValueError("observation signature invalid")
    if verify(public, message + b"!", signature):
        raise ValueError("tampered observation verified")
    print(json.dumps({
        "result": "AZURE_AGENT_OBSERVATION_SIGN_VERIFY_PASS",
        "scope": "non-certifying synthetic cloud-route cross-review",
        "key_id": key_id,
        "message_b64url": base64.urlsafe_b64encode(message).rstrip(b"=").decode(),
        "signature_hex": signature.hex(),
    }, sort_keys=True))


def main() -> None:
    try:
        with open("governance/agent-cert-verifier-azure-pins.json", encoding="utf-8") as stream:
            pin = json.load(stream, object_pairs_hook=_unique)
        run(pin)
    except Exception:
        # No upstream response, assertion or bearer may enter CI logs.
        raise SystemExit("protected observation signing unavailable") from None


if __name__ == "__main__":
    main()
