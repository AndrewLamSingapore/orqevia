"""Fail-closed validator for the canonical Supreme capability register."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    "LAB", "TESTED", "CANDIDATE", "DEGRADED", "VERIFIED",
    "PRODUCTION_PARTIAL", "PRODUCTION", "PRODUCTION_PROVEN",
    "DEFERRED", "BLOCKED",
}
SHA = re.compile(r"^[0-9a-f]{40}$")


def validate(path: Path | None = None) -> dict:
    payload = json.loads((path or ROOT / "governance" / "SUPREME_CAPABILITY_REGISTER.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != "2.0" or payload.get("canonical") is not True:
        raise ValueError("invalid capability register identity")
    entries = payload.get("capabilities")
    if not isinstance(entries, list) or not entries:
        raise ValueError("capability entries are required")
    names = set()
    for entry in entries:
        required = {"capability", "purpose", "component", "maturity", "source_sha", "test_evidence",
                    "independent_verification", "known_limitations", "security_boundary", "offline_behavior",
                    "recovery_method", "portability", "commercial_reuse_potential"}
        if set(entry) != required or entry["capability"] in names:
            raise ValueError("capability entry fields must be exact and unique")
        names.add(entry["capability"])
        if entry["maturity"] not in ALLOWED or not SHA.fullmatch(entry["source_sha"]):
            raise ValueError("capability status or source SHA is invalid")
        if not entry["test_evidence"] or not entry["independent_verification"] or not entry["known_limitations"] or not entry["recovery_method"]:
            raise ValueError("evidence and truthful limitations are mandatory")
    return payload


if __name__ == "__main__":
    value = validate()
    print({"status": "PASS", "capabilities": len(value["capabilities"])})
