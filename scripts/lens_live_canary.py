"""One authenticated HTTPS objective-to-evidence smoke check, with no model call.

Credentials come only from process environment: ORQEVIA_CANARY_CLIENT_ID and
ORQEVIA_CANARY_CLIENT_TOKEN, or ORQEVIA_CANARY_SESSION_COOKIE. No credential
is accepted on argv or included in a receipt. This creates synthetic task/evidence
records, never wallet operations or a general production-acceptance claim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import ssl
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
from uuid import uuid4


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, target):
        return None


def _credentials():
    client = os.getenv("ORQEVIA_CANARY_CLIENT_ID", "").strip()
    token = os.getenv("ORQEVIA_CANARY_CLIENT_TOKEN", "").strip()
    cookie = os.getenv("ORQEVIA_CANARY_SESSION_COOKIE", "").strip()
    if cookie and (client or token):
        raise ValueError("Choose one scoped credential mechanism")
    if cookie:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie):
            raise ValueError("Invalid session credential format")
        name = os.getenv("ORQEVIA_CANARY_COOKIE_NAME", "__Host-ORQEVIA-PWA")
        if name not in {"__Host-ORQEVIA-PWA", "__Host-JARVIS-PWA"}:
            raise ValueError("Unsupported session cookie name")
        return {"Cookie": name + "=" + cookie}
    if not client or not token or any(c in client + token for c in "\r\n"):
        raise ValueError("A scoped client credential or existing owner session is required")
    return {"X-ORQEVIA-Client-ID": client, "Authorization": "Bearer " + token}


def _request(base: str, method: str, path: str, *, payload=None, origin=None):
    headers = {**_credentials(), "X-ORQEVIA-PWA": "1", "Accept": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = "application/json"
    context = ssl.create_default_context(cafile=os.getenv("ORQEVIA_CANARY_CA_FILE") or None)
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context))
    request = Request(base + path, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read(131073)
            status = response.status
    except HTTPError as exc:
        status, body = exc.code, b""
    if len(body) > 131072:
        raise ValueError("Response exceeded canary size budget")
    return status, body


def run(base: str = "https://localhost:8443") -> dict:
    parsed = urlsplit(base)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port != 8443
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Canary requires local HTTPS on port 8443")
    base = base.rstrip("/")
    health_status, health_body = _request(base, "GET", "/interface/v1/health")
    if health_status != 200 or json.loads(health_body).get("state") != "READY":
        raise RuntimeError("Authenticated interface health preflight failed")
    shell_status, shell_body = _request(base, "GET", "/pwa/")
    if shell_status != 200 or b"command-center.mjs" not in shell_body:
        raise RuntimeError("Canonical Command Center shell is unavailable")
    status, body = _request(
        base,
        "POST",
        "/interface/v1/objectives",
        payload={"objective": "How many agents do you have?", "idempotency_key": "evidence-canary-" + uuid4().hex},
        origin=base,
    )
    if status != 202:
        raise RuntimeError(f"Synthetic objective submission failed: HTTP {status}")
    task_id = json.loads(body)["task_id"]
    path = "/interface/v1/lens/evidence/from-objective/" + task_id
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
    if (
        readback.get("task_id") != task_id
        or readback.get("integrity") != "VALID"
        or readback.get("currentness") != "CURRENT"
        or readback.get("verification") != "UNVERIFIED"
        or readback.get("source") != "ORQEVIA_OBJECTIVE_STORE"
        or readback.get("result_state") != "COMPLETED"
        or "independent_claim_verification" not in readback.get("proof", {}).get("unproven", [])
    ):
        raise RuntimeError("Evidence scope or provenance did not match the canary contract")
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "record_id": readback["record_id"],
        "ledger_head": readback["ledger_head"],
        "integrity": "VALID",
        "currentness": "CURRENT",
        "verification": "UNVERIFIED",
        "model_invoked": False,
        "scope": "ONE_DETERMINISTIC_LOCAL_SYNTHETIC_OBJECTIVE",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://localhost:8443")
    arguments = parser.parse_args()
    try:
        print(json.dumps(run(arguments.base), sort_keys=True))
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, sort_keys=True))
        raise SystemExit(1) from None
