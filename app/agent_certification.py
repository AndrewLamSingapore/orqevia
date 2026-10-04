"""Read-only, fail-closed projection of domain-owned agent certification evidence.

Evidence belongs under each agent's directory. This module grants no execution
authority and does not write a central certification flag or mutate the registry.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .agent_registry import agent_record, canonical_agent_id, orchestrator_id


LEVEL_DIMENSIONS = (
    (),
    ("baseline",),
    ("baseline", "role"),
    ("baseline", "role", "general"),
    ("baseline", "role", "general", "collaboration"),
    ("baseline", "role", "general", "collaboration", "recovery"),
    ("baseline", "role", "general", "collaboration", "recovery",
     "authority", "tools", "models", "cross_verification", "fresh_challenge", "health"),
)
REQUIRED_CASES = {
    "baseline": ("identity", "initialization", "authorization", "objective", "instruction",
                 "context", "structured_output", "contract", "error", "timeout", "evidence",
                 "result", "completion", "prime_validation"),
    "role": ("normal", "difficult", "edge", "invalid_input", "failure"),
    "general": ("analysis", "planning", "reasoning", "communication", "evidence",
                "decomposition", "artifact_consume", "artifact_produce", "review",
                "verification", "error_recognition", "handoff", "recovery"),
}
MAX_EVIDENCE_BYTES = 1024 * 1024


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("certification timestamps require timezone")
    return parsed.astimezone(timezone.utc)


class AgentCertificationRegistry:
    """Project current evidence; never promote from registration or task invocation."""

    def __init__(self, evidence_root: Path, *, source_revision: str,
                 verify_record: Callable[[dict], bool] | None = None):
        self.root = Path(evidence_root)
        self.source_revision = source_revision
        self.verify_record = verify_record

    def _valid(self, row: dict, agent_dir: Path, agent_id: str, capability_id: str,
               now: datetime) -> bool:
        try:
            # A name in a JSON record is not independent verification. The
            # domain evidence owner must supply an authenticated verifier.
            if self.verify_record is None or not self.verify_record(row):
                return False
            if row["agent_id"] != agent_id or row["capability_id"] != capability_id:
                return False
            if row["test_result"] != "PASS" or not row["test_version"] or not row["certification_test"]:
                return False
            if canonical_agent_id(row["verifier"]) in {agent_id}:
                return False
            if row["source_revision"] != self.source_revision:
                return False
            if row["authority_scope"] != agent_record(agent_id)["authority"]:
                return False
            if row["dimension"] == "recovery" and row.get("recovery_result") != "PASS":
                return False
            if _utc(row["certified_at"]) > _utc(row["last_revalidated"]) or _utc(row["last_revalidated"]) > now:
                return False
            if _utc(row["expires_at"]) <= now:
                return False
            evidence = Path(row["evidence"])
            if evidence.is_absolute() or ".." in evidence.parts:
                return False
            cursor = agent_dir
            for part in evidence.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    return False
            artifact = (agent_dir / evidence).resolve()
            if not artifact.is_relative_to(agent_dir.resolve()) or not artifact.is_file():
                return False
            if artifact.stat().st_size > MAX_EVIDENCE_BYTES:
                return False
            return hashlib.sha256(artifact.read_bytes()).hexdigest() == row["evidence_sha256"]
        except Exception:
            return False

    def project(self, agent_id: str, capability_id: str, *, now: datetime | None = None) -> dict:
        agent_id = canonical_agent_id(agent_id)
        if agent_id == orchestrator_id():
            raise ValueError("orchestrator is not a permanent specialist agent")
        record = agent_record(agent_id)
        if capability_id not in record["capability_requirements"]:
            return {"agent_id": agent_id, "capability_id": capability_id,
                    "level": "L0", "trust_state": "UNPROVEN", "health": "UNKNOWN",
                    "authority_scope": "NOT_AUTHORIZED", "current_dimensions": []}
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("projection time requires timezone")
        agent_dir = self.root / agent_id
        try:
            if self.root.is_symlink() or agent_dir.is_symlink():
                raise ValueError("certification root or agent directory is a symlink")
            if not agent_dir.resolve().is_relative_to(self.root.resolve()):
                raise ValueError("agent directory escapes certification root")
            manifest = agent_dir / "certification.json"
            if manifest.is_symlink():
                raise ValueError("certification manifest is a symlink")
            if manifest.stat().st_size > MAX_EVIDENCE_BYTES:
                raise ValueError("certification manifest exceeds size limit")
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("certification manifest must be an object")
            rows = data["records"] if data.get("schema_version") == "1.0" else []
            if not isinstance(rows, list):
                rows = []
        except (OSError, ValueError, TypeError, KeyError):
            rows = []
        matching = [row for row in rows if isinstance(row, dict)
                    and row.get("agent_id") == agent_id and row.get("capability_id") == capability_id]
        latest = {}
        malformed = set()
        for row in matching:
            dimension = row.get("dimension")
            if dimension not in LEVEL_DIMENSIONS[-1]:
                continue
            test_case = row.get("test_case")
            if not isinstance(test_case, str) or not test_case:
                continue
            key = (dimension, test_case)
            try:
                timestamp = (_utc(row["last_revalidated"]), _utc(row["certified_at"]),
                             row.get("test_result") != "PASS")
            except (KeyError, TypeError, ValueError):
                malformed.add(key)
                continue
            if key not in latest or timestamp > latest[key][0]:
                latest[key] = (timestamp, row)
        valid = {key for key, (_, row) in latest.items() if key not in malformed
                 if self._valid(row, agent_dir, agent_id, capability_id, now)}
        current = set()
        for dimension in LEVEL_DIMENSIONS[-1]:
            required = REQUIRED_CASES.get(dimension, ("complete",))
            if all((dimension, case) in valid for case in required):
                artifacts = [latest[(dimension, case)][1]["evidence"] for case in required]
                if len(artifacts) == len(set(artifacts)):
                    current.add(dimension)
        level = max(index for index, required in enumerate(LEVEL_DIMENSIONS)
                    if set(required).issubset(current))
        latest_rows = [row for _, row in latest.values()]
        health_row = latest.get(("health", "complete"))
        health = "HEALTHY" if "health" in current and health_row and health_row[1].get("health") == "HEALTHY" else "UNKNOWN"
        if level == 6 and health != "HEALTHY":
            level = 5
        stale = bool(matching) and (len(valid) < len(latest) or not current)
        return {"agent_id": agent_id, "capability_id": capability_id,
                "level": f"L{level}",
                "trust_state": ("CERTIFIED-HEALTHY" if level == 6 else
                                "REVALIDATION-REQUIRED" if stale else "UNPROVEN" if level == 0 else "CERTIFIED-DEGRADED"),
                "health": health, "authority_scope": record["authority"],
                "current_dimensions": sorted(current),
                "failure_count": max((row.get("failure_count", 0) for row in latest_rows
                                      if isinstance(row.get("failure_count", 0), int)
                                      and row.get("failure_count", 0) >= 0), default=0)}
