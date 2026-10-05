"""Fail-closed Ed25519 verification for certification evidence records.

Only public keys enter this module. A trusted caller supplies an explicit map of
current verifier service identities and key IDs; an empty map rejects all rows.
The service that signs records must retain its private key outside PRIME, agent
tools, prompts, logs, artifacts, and frontend code. This callback authenticates
claims; the certification registry still checks evidence bytes and authority.
"""
from __future__ import annotations

import json
import re
import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .agent_registry import RegistryError, agent_record, canonical_agent_id
from .agent_certification import LEVEL_DIMENSIONS


_DOMAIN = "prime.agent-certification.record.ed25519.v1"
_ALGORITHM = "Ed25519"
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_HEX_SIGNATURE = re.compile(r"[0-9a-f]{128}\Z")
_KEY_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
_SERVICE_ID = re.compile(r"svc\.cert-verifier\.[A-Za-z0-9._-]{1,64}\Z")
_EXECUTOR_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
_MAX_SIGNED_BYTES = 64 * 1024
_REQUIRED_RECORD_FIELDS = (
    "agent_id", "capability_id", "dimension", "test_case",
    "certification_test", "test_version", "test_result", "verifier",
    "executor_identity", "evidence", "evidence_sha256", "certified_at",
    "last_revalidated", "expires_at", "source_revision", "authority_scope",
)


def _signed_bytes(row: dict, verifier_identity: str, key_id: str) -> bytes:
    """Canonical domain-separated bytes, including every non-attestation field."""
    body = {
        "domain": _DOMAIN,
        "algorithm": _ALGORITHM,
        "verifier_identity": verifier_identity,
        "key_id": key_id,
        "record": {field: value for field, value in row.items() if field != "attestation"},
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > _MAX_SIGNED_BYTES:
        raise ValueError("certification record exceeds signature limit")
    return encoded


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


class Ed25519CertificationVerifier:
    """Callable ``verify_record`` adapter using trusted raw 32-byte public keys.

    ``trusted_keys`` has shape ``{service_identity: {key_id: public_key_bytes}}``.
    A verifier service identity is distinct from the candidate agent, executing
    identity, and the human/agent reviewer named by ``row['verifier']``.
    Remove revoked keys from the map before constructing a new verifier.
    """

    def __init__(self, trusted_keys: Mapping[str, Mapping[str, bytes]]):
        if not isinstance(trusted_keys, Mapping):
            raise TypeError("trusted keys must be a mapping")
        keys: dict[str, dict[str, Ed25519PublicKey]] = {}
        for service, by_id in trusted_keys.items():
            if not isinstance(service, str) or not _SERVICE_ID.fullmatch(service):
                raise ValueError("invalid verifier service identity")
            if not isinstance(by_id, Mapping):
                raise TypeError("verifier keys must be a mapping")
            current = {}
            for key_id, public_bytes in by_id.items():
                if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
                    raise ValueError("invalid verifier key id")
                if not isinstance(public_bytes, bytes) or len(public_bytes) != 32:
                    raise ValueError("Ed25519 public key must be 32 bytes")
                current[key_id] = Ed25519PublicKey.from_public_bytes(public_bytes)
            keys[service] = current
        self._keys = keys

    def __call__(self, row: dict) -> bool:
        try:
            if not isinstance(row, dict) or any(field not in row for field in _REQUIRED_RECORD_FIELDS):
                return False
            attestation = row.get("attestation")
            if not isinstance(attestation, dict) or set(attestation) != {
                    "algorithm", "key_id", "verifier_identity", "signature"}:
                return False
            if attestation["algorithm"] != _ALGORITHM:
                return False
            service = attestation["verifier_identity"]
            key_id = attestation["key_id"]
            signature = attestation["signature"]
            if (not isinstance(service, str) or not _SERVICE_ID.fullmatch(service)
                    or not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id)
                    or not isinstance(signature, str) or not _HEX_SIGNATURE.fullmatch(signature)):
                return False
            subject, reviewer, executor = (row["agent_id"], row["verifier"],
                                           row["executor_identity"])
            if (not all(isinstance(value, str) for value in (subject, reviewer, executor))
                    or canonical_agent_id(subject) != subject
                    or canonical_agent_id(reviewer) != reviewer
                    or subject == reviewer or reviewer == executor
                    or not _EXECUTOR_ID.fullmatch(executor)
                    or service in {subject, reviewer, executor}):
                return False
            agent_record(subject)
            agent_record(reviewer)
            if (not isinstance(row["capability_id"], str)
                    or row["capability_id"] not in agent_record(subject)["capability_requirements"]
                    or row["dimension"] not in LEVEL_DIMENSIONS[-1]
                    or not all(isinstance(row[field], str) and row[field]
                               for field in ("test_case", "certification_test", "test_version",
                                             "evidence", "source_revision", "authority_scope"))
                    or row["test_result"] != "PASS"
                    or not isinstance(row["evidence_sha256"], str)
                    or not _HEX_SHA256.fullmatch(row["evidence_sha256"])):
                return False
            certified = _utc(row["certified_at"])
            revalidated = _utc(row["last_revalidated"])
            expires = _utc(row["expires_at"])
            if certified > revalidated or revalidated >= expires:
                return False
            key = self._keys.get(service, {}).get(key_id)
            if key is None:
                return False
            key.verify(bytes.fromhex(signature), _signed_bytes(row, service, key_id))
            return True
        except (InvalidSignature, KeyError, TypeError, ValueError, OverflowError,
                RecursionError, RegistryError):
            return False


def verifier_from_pin_file(path: Path) -> Ed25519CertificationVerifier:
    """Load an operator controlled public-key pin set; empty pins deny all rows.

    The pin file is deployment configuration, never selected by a record. A
    fingerprint protects against accidental key substitution in that file;
    custody and integrity of the file itself remain the deployer's boundary.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or set(data) != {"schema_version", "service_identity", "keys"}
            or data["schema_version"] != "1.0"
            or not isinstance(data["service_identity"], str)
            or not _SERVICE_ID.fullmatch(data["service_identity"])
            or not isinstance(data["keys"], dict)):
        raise ValueError("invalid certification verifier pin file")
    keys = {}
    for key_id, pin in data["keys"].items():
        if (not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id)
                or not isinstance(pin, dict) or set(pin) != {"public_key_hex", "sha256"}
                or not isinstance(pin["public_key_hex"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", pin["public_key_hex"])
                or not isinstance(pin["sha256"], str)
                or not _HEX_SHA256.fullmatch(pin["sha256"])):
            raise ValueError("invalid certification verifier public key pin")
        public = bytes.fromhex(pin["public_key_hex"])
        if hashlib.sha256(public).hexdigest() != pin["sha256"]:
            raise ValueError("certification verifier fingerprint mismatch")
        keys[key_id] = public
    return Ed25519CertificationVerifier({data["service_identity"]: keys})
