#!/usr/bin/env python3
"""Verify the immutable Golden Gen 1 architecture identity and evidence bindings."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "governance/golden-gen1-manifest.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_bytes(revision: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{revision}:{path}"], cwd=ROOT, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def digest_matches(raw: bytes, expected: str) -> bool:
    lf = raw.replace(b"\r\n", b"\n")
    crlf = lf.replace(b"\n", b"\r\n")
    return expected in {hashlib.sha256(value).hexdigest() for value in (raw, lf, crlf)}


def validate(value: dict) -> list[str]:
    errors: list[str] = []
    require = lambda condition, message: None if condition else errors.append(message)
    source = value["source"]["accepted_commit"]
    require(value["schema_version"] == "jarvis.golden-baseline.v1", "schema")
    require(value["generation"] == 1 and value["architecture_state"] == "FROZEN", "generation")
    require(value["long_duration_stability"] == "PENDING", "stability_boundary")
    require(digest_matches((ROOT / value["architecture"]["path"]).read_bytes(), value["architecture"]["sha256"]), "architecture_digest")
    receipt_path = ROOT / value["runtime_receipt"]["path"]
    artifact_path = ROOT / value["independent_verification"]["path"]
    require(digest_matches(receipt_path.read_bytes(), value["runtime_receipt"]["sha256"]), "receipt_digest")
    require(digest_matches(artifact_path.read_bytes(), value["independent_verification"]["sha256"]), "artifact_digest")
    receipt = json.loads(receipt_path.read_bytes())
    artifact = json.loads(artifact_path.read_bytes())
    require(receipt["runtime"]["source_sha"] == source, "receipt_source")
    require(receipt["runtime"]["image_tag"] == value["build"]["image_tag"], "receipt_image")
    require(receipt["runtime"]["image_id"] == value["build"]["image_id"], "receipt_image_id")
    require(artifact["verification_id"] == value["independent_verification"]["verification_id"], "verification_id")
    require(artifact["receipt_hash_digest"] == value["runtime_receipt"]["sha256"], "verification_receipt_binding")
    require(artifact["final_verification"] == "PASS", "verification_verdict")
    registry = json.loads(git_bytes(source, value["registry"]["path"]))
    require(registry["schema_version"] == value["registry"]["schema"], "registry_schema")
    require(registry["registry_version"] == value["registry"]["version"], "registry_version")
    require(len(registry["agents"]) == value["registry"]["logical_agent_count"], "agent_count")
    require(digest_matches(git_bytes(source, value["registry"]["path"]), value["registry"]["deployed_sha256"]), "registry_digest")
    for name, expected in value["interface"]["assets"].items():
        require(digest_matches(git_bytes(source, "clients/pwa/" + name), expected), "pwa_digest:" + name)
    require(value["acceptance"]["state"] == "VERIFIED", "runtime_acceptance")
    require(value["authority"]["production_authority"] == "ABEX", "production_authority")
    require(value["authority"]["member_inherits_owner"] is False, "member_authority")
    require(value["provenance"]["model_content_authoritative"] is False, "model_metadata")
    require(value["external_gates"]["wuhan_mainland_china"] == "PHYSICAL_VERIFICATION_PENDING", "wuhan_boundary")
    require(value["phase2_boundary"]["state"] == "CANDIDATE_NOT_PART_OF_GOLDEN_GEN1", "phase2_boundary")
    require(value["unresolved_defects"] == {"p0": 0, "p1": 0, "p2": 0}, "defect_gate")
    return sorted(set(errors))


def main() -> int:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors = validate(value)
    print(json.dumps({"golden_baseline_id": value["golden_baseline_id"], "verdict": "PASS" if not errors else "FAIL", "violations": errors}, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
