"""Bind lifecycle claims to recent, hash-checked functional execution evidence.

Evidence indexes are administrator-controlled local files. This checks their
source, scope, freshness and original receipt bytes. It is not remote attestation
or protection against an administrator rewriting both the index and its evidence.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

_HASH = re.compile(r"[a-f0-9]{64}\Z")
_REVISION = re.compile(r"[a-f0-9]{40}\Z")
MAX_INDEX_BYTES = 256_000
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024


def _timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Evidence timestamp must include a timezone")
    return result


def apply_evidence(registry, index, evidence_root: Path, *, runtime_revision: str, now=None):
    """Return an independent catalog snapshot; never alter the source catalog."""
    result = deepcopy(registry)
    now = now or datetime.now(timezone.utc)
    root = Path(evidence_root).resolve()
    if not isinstance(index, dict) or index.get("schema") != "orqevia.fabric-evidence.v1":
        raise ValueError("Unsupported fabric evidence index")
    observations = index.get("observations")
    if not isinstance(observations, list) or len(observations) > 36:
        raise ValueError("Invalid fabric evidence count")
    by_id = {item["id"]: item for item in result["fabrics"]}
    seen = set()
    for observation in observations:
        if not isinstance(observation, dict) or observation.get("fabric_id") not in by_id:
            raise ValueError("Unknown fabric observation")
        identifier = observation["fabric_id"]
        if identifier in seen:
            raise ValueError("Duplicate fabric observation")
        seen.add(identifier)
        item = by_id[identifier]
        item["verification"] = {"status": "UNVERIFIED", "reason": "INVALID_EVIDENCE"}
        # An unavailable fabric cannot become implemented just because a receipt exists.
        if item["state"] not in {"IMPLEMENTED", "VERIFIED", "DEGRADED", "FAILED"}:
            continue
        item["state"] = "IMPLEMENTED"
        try:
            if not _REVISION.fullmatch(runtime_revision) or observation["runtime_revision"] != runtime_revision:
                raise ValueError("SOURCE_MISMATCH")
            if observation["version"] != item["version"]:
                raise ValueError("VERSION_MISMATCH")
            if (
                observation["kind"] != "FUNCTIONAL"
                or not isinstance(observation["scope"], str)
                or not observation["scope"].strip()
            ):
                raise ValueError("FUNCTIONAL_EVIDENCE_REQUIRED")
            observed = _timestamp(observation["observed_at"])
            expires = _timestamp(observation["expires_at"])
            if observed > now or not 0 < (expires - observed).total_seconds() <= 86400:
                raise ValueError("INVALID_EVIDENCE_WINDOW")
            path = root / observation["path"]
            resolved = path.resolve(strict=True)
            if path.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
                raise ValueError("INVALID_EVIDENCE_PATH")
            # Reject intermediate symlinks, even when they currently point inside root.
            relative = path.relative_to(root)
            cursor = root
            for part in relative.parts:
                if part in {".", ".."}:
                    raise ValueError("INVALID_EVIDENCE_PATH")
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ValueError("INVALID_EVIDENCE_PATH")
            if resolved.stat().st_size > MAX_EVIDENCE_BYTES or not _HASH.fullmatch(observation["sha256"]):
                raise ValueError("INVALID_EVIDENCE_SIZE_OR_HASH")
            raw = resolved.read_bytes()
            if hashlib.sha256(raw).hexdigest() != observation["sha256"]:
                raise ValueError("EVIDENCE_HASH_MISMATCH")
            receipt = json.loads(raw)
            if not isinstance(receipt, dict) or receipt.get("status") not in {"PASS", "FAIL"}:
                raise ValueError("EXECUTED_RECEIPT_REQUIRED")
            # A receipt must bind itself to the exact fabric/version/source/window.
            for field in ("fabric_id", "version", "runtime_revision", "kind", "scope", "observed_at", "expires_at"):
                if receipt.get(field) != observation[field]:
                    raise ValueError("RECEIPT_BINDING_MISMATCH")
            checks = receipt.get("checks")
            if (
                not isinstance(checks, list)
                or not checks
                or not all(
                    isinstance(check, dict)
                    and isinstance(check.get("name"), str)
                    and check["name"].strip()
                    and check.get("status") in {"PASS", "FAIL"}
                    for check in checks
                )
            ):
                raise ValueError("EXECUTED_CHECKS_REQUIRED")
            if expires <= now:
                item.update(state="DEGRADED", verification={"status": "EXPIRED", "reason": "EVIDENCE_EXPIRED"})
                continue
            passed = receipt["status"] == "PASS" and all(check["status"] == "PASS" for check in checks)
            item["state"] = "VERIFIED" if passed else "FAILED"
            item["verification"] = {
                "status": "PASS" if passed else "FAIL",
                "scope": observation["scope"],
                "observed_at": observation["observed_at"],
                "expires_at": observation["expires_at"],
                "runtime_revision": runtime_revision,
                "evidence_sha256": observation["sha256"],
            }
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
            reason = (
                str(error)
                if isinstance(error, ValueError) and re.fullmatch(r"[A-Z_]+", str(error))
                else "INVALID_EVIDENCE"
            )
            item["verification"] = {"status": "UNVERIFIED", "reason": reason}
    result["verification_context"] = {
        "runtime_revision": runtime_revision,
        "observed_at": now.isoformat(),
        "scope": "local functional receipts; not hardware or independent AI attestation",
    }
    return result


def load_evidence(path: Path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INDEX_BYTES:
        raise ValueError("Evidence index unavailable or oversized")
    return json.loads(path.read_text(encoding="utf-8"))
