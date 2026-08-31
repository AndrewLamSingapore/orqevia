"""Authenticated, non-physical Portal result write/read smoke.

The caller supplies a result fixture and protected token. This script never
constructs or authorizes physical evidence and never prints the credential.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portal", default=os.getenv("PORTAL_BASE_URL", "https://the-portal-ten.vercel.app"))
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    token = os.getenv("PORTAL_RESULT_TOKEN", "")
    if not token:
        raise SystemExit("PORTAL_RESULT_TOKEN is required")
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
    print(json.dumps({"ok": True, "result_id": result["result_id"], "experiment_id": result["experiment_id"], "write": "accepted", "read": "verified", "physical_actuation": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
