"""Authenticated, non-physical Portal result write/read smoke.

The caller supplies a result fixture and protected token. This script never
constructs or authorizes physical evidence and never prints the credential.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portal", default=os.getenv("PORTAL_BASE_URL", "https://the-portal-ten.vercel.app"))
    result_source = parser.add_mutually_exclusive_group(required=True)
    result_source.add_argument("--result", type=Path)
    result_source.add_argument("--generate-safe-smoke", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    token = os.getenv("PORTAL_RESULT_TOKEN", "")
    if not token:
        raise SystemExit("PORTAL_RESULT_TOKEN is required")
    if args.generate_safe_smoke:
        now = datetime.now(timezone.utc)
        suffix = now.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4).upper()
        result = {
            "schema_version": "1.0",
            "result_id": "PRM-RES-P1-SMOKE-" + suffix,
            "result_version": 1,
            "source": "prime",
            "experiment_id": "PRM-EXP-P1-SMOKE-" + suffix,
            "candidate_id": "PTL-P1-SMOKE-" + suffix,
            "node_ids": [],
            "status": "completed",
            "conclusion": "completed_without_observations",
            "evidence_summary": {"observation_count": 0, "evidence_levels": {"raw": 0, "reference": 0, "derived": 0}, "provenance_complete": True, "first_observed_at": None, "last_observed_at": None},
            "safety": {"actuation_authorized": False, "owner_approval_inferred": False, "scientific_support_claimed": False},
            "updated_at": now.isoformat(),
        }
    else:
        result = json.loads(args.result.read_text(encoding="utf-8"))
    safety = result.get("safety", {})
    required_safety = {"actuation_authorized": False, "owner_approval_inferred": False, "scientific_support_claimed": False}
    if any(safety.get(key) is not value for key, value in required_safety.items()):
        raise SystemExit("result must explicitly deny actuation, inferred approval, and scientific-support claims")
    endpoint = args.portal.rstrip("/") + "/api/experiment-result"
    request = urllib.request.Request(endpoint, data=json.dumps({"result": result}).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        accepted = json.load(response)
    if accepted.get("accepted") is not True or accepted.get("result_id") != result.get("result_id"):
        raise SystemExit("Portal acknowledgement did not match the submitted result")
    graph = get_json(args.portal.rstrip("/") + "/api/graph")
    expected_node = "RESULT-" + result["experiment_id"]
    if not any(node.get("id") == expected_node for node in graph.get("nodes", [])):
        raise SystemExit("written result was not readable from the Portal graph")
    report = {"ok": True, "result_id": result["result_id"], "experiment_id": result["experiment_id"], "write": "accepted", "read": "verified", "physical_actuation": False, "credential_exposed": False}
    encoded = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
