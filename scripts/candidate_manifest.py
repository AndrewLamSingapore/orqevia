"""Build a deterministic, non-deploying candidate provenance manifest."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def build_manifest(*, source_sha: str, artifact_digest: str, branch: str, tests: dict[str, int], verification: dict[str, Any], security: dict[str, Any], risk: list[str], migrations: list[str], recovery: list[str], acceptance_gates: list[str]) -> dict[str, Any]:
    if not SHA.fullmatch(source_sha):
        raise ValueError("source SHA must be an immutable full commit")
    if not DIGEST.fullmatch(artifact_digest):
        raise ValueError("artifact must use an immutable sha256 digest")
    if "latest" in artifact_digest.lower() or not branch.strip():
        raise ValueError("floating or missing candidate identity")
    if tests.get("failed", 1) != 0 or tests.get("passed", 0) <= 0:
        raise ValueError("passing test evidence is required")
    if verification.get("status") != "PASS" or security.get("status") != "PASS":
        raise ValueError("independent verification and security evidence must pass")
    if not risk or not recovery or not acceptance_gates:
        raise ValueError("risk, recovery and acceptance gates are mandatory")
    body = {
        "schema_version": "1.0",
        "status": "CANDIDATE_ONLY_NOT_DEPLOYED",
        "source_sha": source_sha,
        "artifact_digest": artifact_digest,
        "branch": branch,
        "tests": tests,
        "independent_verification": verification,
        "security": security,
        "change_risk_fingerprint": sorted(set(risk)),
        "migration_requirements": migrations,
        "recovery_method": recovery,
        "acceptance_gates": acceptance_gates,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return {**body, "manifest_sha256": hashlib.sha256(canonical).hexdigest()}


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
