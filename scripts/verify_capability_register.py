"""Fail-closed validator for the canonical Supreme capability register."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"PRODUCTION_PROVEN", "CANDIDATE", "TESTED_LAB", "SIMULATED", "DEFERRED", "BLOCKED", "NOT_TESTED"}
SHA = re.compile(r"^[0-9a-f]{40}$")


def validate(path: Path | None = None) -> dict:
    payload = json.loads((path or ROOT / "governance" / "SUPREME_CAPABILITY_REGISTER.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0" or payload.get("canonical") is not True:
        raise ValueError("invalid capability register identity")
    entries = payload.get("capabilities")
    if not isinstance(entries, list) or not entries:
        raise ValueError("capability entries are required")
    names = set()
    for entry in entries:
        required = {"name", "status", "claim", "source_sha", "evidence", "limitations"}
        if set(entry) != required or entry["name"] in names:
            raise ValueError("capability entry fields must be exact and unique")
        names.add(entry["name"])
        if entry["status"] not in ALLOWED or not SHA.fullmatch(entry["source_sha"]):
            raise ValueError("capability status or source SHA is invalid")
        if not entry["evidence"] or not entry["limitations"]:
            raise ValueError("evidence and truthful limitations are mandatory")
    return payload


if __name__ == "__main__":
    value = validate()
    print({"status": "PASS", "capabilities": len(value["capabilities"])})
