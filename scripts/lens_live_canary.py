"""One bounded local-control -> Objective Store -> Evidence Lens smoke check.

This creates one deterministic synthetic objective and one Lens projection. It
does not call a model, certify an agent, or verify production acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def _request(base: str, method: str, path: str, *, payload=None, origin=None):
    headers = {}
    if origin is not None:
        headers["Origin"] = origin
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=4) as response:
            body = response.read(131073)
            status = response.status
    except HTTPError as exc:
        status, body = exc.code, b""
    if len(body) > 131072:
        raise ValueError("Response exceeded canary size budget")
    return status, body


def run(base: str = "http://127.0.0.1:8000") -> dict:
    parsed = urlsplit(base)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.port != 8000 or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("Canary accepts only local PRIME HTTP on port 8000")
    base = base.rstrip("/")
    health_status, health_body = _request(base, "GET", "/health")
    if health_status != 200 or json.loads(health_body).get("ok") is not True:
        raise RuntimeError("PRIME local health preflight failed")
    script_status, script_body = _request(base, "GET", "/control/app.js")
    if script_status != 200 or b"record-proof" not in script_body:
        raise RuntimeError("Evidence Lens is not installed in this runtime")

    status, body = _request(base, "POST", "/control/api/objectives",
                            payload={"objective": "How many agents do you have?"}, origin=base)
    if status != 202:
        raise RuntimeError(f"Synthetic objective submission failed: HTTP {status}")
    task_id = json.loads(body)["id"]
    path = "/control/api/evidence/from-objective/" + task_id
    denied, _ = _request(base, "POST", path, payload={}, origin="https://invalid.example")
    if denied != 403:
        raise RuntimeError(f"Cross-origin evidence mutation was not denied: HTTP {denied}")
    created_status, created_body = _request(base, "POST", path, payload={}, origin=base)
    read_status, read_body = _request(base, "GET", path)
    if created_status != 201 or read_status != 200:
        raise RuntimeError(f"Evidence capture/read failed: HTTP {created_status}/{read_status}")
    created, readback = json.loads(created_body), json.loads(read_body)
    if created != readback:
        raise RuntimeError("Evidence readback differs from captured projection")
    if (readback.get("task_id") != task_id or readback.get("integrity") != "VALID"
            or readback.get("currentness") != "CURRENT"
            or readback.get("verification") != "UNVERIFIED"
            or readback.get("source") != "PRIME_OBJECTIVE_STORE"
            or "independent_claim_verification" not in readback.get("proof", {}).get("unproven", [])):
        raise RuntimeError("Evidence scope or provenance did not match the canary contract")
    return {"observed_at": datetime.now(timezone.utc).isoformat(),
            "task_id": task_id, "record_id": readback["record_id"],
            "ledger_head": readback["ledger_head"],
            "integrity": "VALID", "currentness": "CURRENT",
            "verification": "UNVERIFIED", "model_invoked": False,
            "scope": "ONE_DETERMINISTIC_LOCAL_SYNTHETIC_OBJECTIVE"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    arguments = parser.parse_args()
    try:
        print(json.dumps(run(arguments.base), sort_keys=True))
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, sort_keys=True))
        raise SystemExit(1) from None
