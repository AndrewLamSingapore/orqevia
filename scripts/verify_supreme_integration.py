"""Independent executable receipt for the Supreme integration candidate."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.capability_router import CapabilityBackend
from app.supreme_integration import IntegrationEnvelope, authorize_tool, run_model_hop


def main() -> int:
    now = time.time()
    member = IntegrationEnvelope("verify-trace", "verify-request", "member-1", "MEMBER", "household-1", "1.0", now, now + 60, "verify-idem", frozenset({"task.submit"}))
    local = (CapabilityBackend("local-4b", "gemma3:4b", "local", 6.4, frozenset({"chinese_response"})),)
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"], "additionalProperties": False}
    accepted = run_model_hop(member, backends=local, capability="chinese_response", classification="LOCAL_ONLY", raw_model_output='{"answer":"我是JARVIS"}', schema=schema)
    fabricated = run_model_hop(member, backends=local, capability="chinese_response", classification="LOCAL_ONLY", raw_model_output='{"answer":"fabricated"}', schema=schema, semantic_verify=lambda value: ["unsupported_claim"])
    checks = {
        "valid_chain_accepted": accepted.disposition == "ACCEPTED" and accepted.route_model == "gemma3:4b",
        "member_owner_denied": not authorize_tool(member, permission="owner.admin", model_claimed_role="OWNER"),
        "semantic_fabrication_denied": fabricated.disposition == "VERIFY_REQUIRED",
        "no_tool_execution": not accepted.tool_executed and not fabricated.tool_executed,
        "no_authority_change": not accepted.authority_changed and not fabricated.authority_changed,
    }
    print(json.dumps({"verifier": "supreme-integration-v1", "checks": checks, "passed": sum(checks.values()), "total": len(checks)}, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

