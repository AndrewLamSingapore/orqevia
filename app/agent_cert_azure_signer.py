"""Protected reviewer boundary for Azure Key Vault ES256 certification signing.

The caller owns authentication and Key Vault access. This module holds only a
versioned key ID and public JWK; it never loads a private key or credential.
Executing agents must not be able to call the injected ``sign_digest`` operation.
"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from .agent_cert_azure_es256 import (
    AzureES256CertificationVerifier, azure_es256_signed_bytes,
    azure_es256_signing_digest,
)
from .agent_cert_ed25519 import _utc
from .agent_registry import RegistryError, canonical_agent_id


class ProtectedAzureES256Signer:
    """Sign an exact independently approved, current, artifact-backed PASS.

    ``approved_digest`` is an in-process decision of the isolated reviewer,
    not a value accepted from an agent or its evidence record. ``sign_digest``
    must perform Key Vault ``sign(ES256, digest)`` and return the response's
    exact versioned key ID and 64-byte JOSE R||S signature.
    """

    def __init__(self, service_identity: str, key_id: str,
                 public_jwk: Mapping[str, str],
                 sign_digest: Callable[[bytes], tuple[str, bytes]]):
        if not callable(sign_digest):
            raise TypeError("protected sign operation required")
        self._verifier = AzureES256CertificationVerifier(
            {service_identity: {key_id: public_jwk}})
        self._service = service_identity
        self._key_id = key_id
        self._sign_digest = sign_digest

    def sign(self, row: dict, *, approved_digest: str, evidence_root: Path,
             source_revision: str, now: datetime) -> dict:
        if not isinstance(row, dict) or "attestation" in row:
            raise ValueError("unsigned certification record required")
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("aware verification time required")
        if row.get("source_revision") != source_revision or row.get("test_result") != "PASS":
            raise ValueError("record source or result does not match approval")
        body = azure_es256_signed_bytes(row, self._service, self._key_id)
        if (not isinstance(approved_digest, str)
                or not hmac.compare_digest(approved_digest, hashlib.sha256(body).hexdigest())):
            raise ValueError("independent review does not match exact record")
        evidence, subject = row.get("evidence"), row.get("agent_id")
        if (not isinstance(evidence, str) or not isinstance(subject, str)
                or not evidence or not subject):
            raise ValueError("artifact identity required")
        try:
            if canonical_agent_id(subject) != subject:
                raise ValueError("noncanonical artifact subject")
        except RegistryError as exc:
            raise ValueError("unregistered artifact subject") from exc
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
        current = now.astimezone(timezone.utc)
        if (_utc(row["certified_at"]) > _utc(row["last_revalidated"])
                or _utc(row["last_revalidated"]) > current
                or _utc(row["expires_at"]) <= current):
            raise ValueError("certification record is not current")
        response_key_id, signature = self._sign_digest(
            azure_es256_signing_digest(row, self._service, self._key_id))
        if response_key_id != self._key_id or not isinstance(signature, bytes) or len(signature) != 64:
            raise ValueError("Key Vault response key or signature mismatch")
        candidate = dict(row)
        candidate["attestation"] = {
            "algorithm": "ES256", "key_id": self._key_id,
            "verifier_identity": self._service, "signature": signature.hex(),
        }
        if not self._verifier(candidate):
            raise ValueError("certification record fails pinned public-key verification")
        return candidate
