"""Signer boundary for a separately operated certification verifier service.

This module never loads or persists a private key. Only the protected verifier
process may construct this class after an independent reviewer has approved an
exact evidence record. Keep that process and its signing key inaccessible to
the executing agents; importing this module grants no signing authority.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .agent_cert_ed25519 import (
    Ed25519CertificationVerifier, _KEY_ID, _SERVICE_ID, _signed_bytes,
)


class ProtectedCertificationSigner:
    """Sign only a reviewer's exact, current, artifact-backed PASS record.

    ``approved_digest`` must come from the protected review process after it
    checks the actual case result. It is an in-process authorization input, not
    a portable approval token supplied by a worker or certification record.
    """

    def __init__(self, service_identity: str, key_id: str,
                 private_key: Ed25519PrivateKey):
        if not isinstance(service_identity, str) or not _SERVICE_ID.fullmatch(service_identity):
            raise ValueError("invalid verifier service identity")
        if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
            raise ValueError("invalid verifier key id")
        if not isinstance(private_key, Ed25519PrivateKey):
            raise TypeError("protected Ed25519 private key required")
        self._service = service_identity
        self._key_id = key_id
        self._private_key = private_key
        public = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        self.public_key = public

    def sign(self, row: dict, *, approved_digest: str, evidence_root: Path,
             source_revision: str, now: datetime) -> dict:
        if not isinstance(row, dict) or "attestation" in row:
            raise ValueError("unsigned certification record required")
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("aware verification time required")
        if row.get("source_revision") != source_revision or row.get("test_result") != "PASS":
            raise ValueError("record source or result does not match approval")
        body = _signed_bytes(row, self._service, self._key_id)
        if (not isinstance(approved_digest, str)
                or not hmac.compare_digest(approved_digest, hashlib.sha256(body).hexdigest())):
            raise ValueError("independent review does not match exact record")
        evidence = row.get("evidence")
        subject = row.get("agent_id")
        if (not isinstance(evidence, str) or not isinstance(subject, str)
                or not evidence or not subject):
            raise ValueError("artifact identity required")
        relative = Path(evidence)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("artifact path escapes subject directory")
        root = Path(evidence_root)
        subject_dir = root / subject
        artifact = subject_dir / relative
        if root.is_symlink() or subject_dir.is_symlink() or any(
                (subject_dir.joinpath(*relative.parts[:index])).is_symlink()
                for index in range(1, len(relative.parts) + 1)):
            raise ValueError("symlink in artifact path")
        if not artifact.resolve().is_relative_to(subject_dir.resolve()):
            raise ValueError("artifact path escapes subject directory")
        if not artifact.is_file() or artifact.stat().st_size > 1024 * 1024:
            raise ValueError("artifact missing or oversized")
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != row.get("evidence_sha256"):
            raise ValueError("artifact digest mismatch")
        candidate = dict(row)
        candidate["attestation"] = {
            "algorithm": "Ed25519", "key_id": self._key_id,
            "verifier_identity": self._service,
            "signature": self._private_key.sign(body).hex(),
        }
        verifier = Ed25519CertificationVerifier({self._service: {self._key_id: self.public_key}})
        if not verifier(candidate):
            raise ValueError("certification record fails verifier contract")
        from .agent_certification import _utc
        if _utc(row["last_revalidated"]) > now.astimezone(timezone.utc) or _utc(row["expires_at"]) <= now.astimezone(timezone.utc):
            raise ValueError("certification record is not current")
        return candidate
