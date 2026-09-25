"""Independent structured-output verifier; no model or tool authority."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.structured_output import evaluate_structured_output


EVIDENCE = ROOT / "docs" / "evidence" / "structured-output-constrained-20260925.json"
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["decision", "score", "details"],
    "properties": {
        "decision": {"type": "string", "enum": ["ALLOW", "DENY"]},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "details": {"type": "object", "additionalProperties": False, "required": ["summary"], "properties": {"summary": {"type": "string", "minLength": 1, "maxLength": 200}}},
    },
}


def semantic(value):
    summary = value["details"]["summary"].lower()
    return ["unsupported_specific_cause"] if "dependency x" in summary or "vulnerability" in summary else []


def verify() -> dict:
    receipt = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    checks = []
    for model in receipt["models"]:
        for raw in model["raw_results"]:
            result = evaluate_structured_output(raw, SCHEMA, semantic_verify=semantic)
            expected = model["semantic_evidence_passed"] > 0
            if result.accepted is not expected:
                raise AssertionError(f"semantic disposition mismatch for {model['model']}")
        checks.append(f"{model['model']}:semantic_disposition_verified")
    malformed = evaluate_structured_output('{"decision":"ALLOW"}', SCHEMA)
    if malformed.accepted or malformed.grants_tool_authority:
        raise AssertionError("malformed result gained acceptance or authority")
    checks.append("malformed_output_denied")
    return {
        "status": "PASS", "checks": checks, "checks_passed": len(checks),
        "evidence_sha256": hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(),
        "authority_granted": False, "production_touched": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
