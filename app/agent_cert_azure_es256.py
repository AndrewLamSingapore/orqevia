"""Offline verification contract for Azure Key Vault ES256 certification signatures.

The trusted caller pins a versioned Key Vault key ID and its P-256 public JWK.
This module never calls Azure, fetches keys, or holds signing credentials. The
protected reviewer alone may submit the digest to Key Vault's sign operation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from .agent_cert_ed25519 import (_HEX_SHA256, _REQUIRED_RECORD_FIELDS,
                                 _SERVICE_ID, _utc)
from .agent_certification import LEVEL_DIMENSIONS
from .agent_registry import RegistryError, agent_record, canonical_agent_id


_DOMAIN = "prime.agent-certification.record.azure-es256.v1"
_KEY_ID = re.compile(
    r"https://[a-z0-9-]{3,24}\.vault\.azure\.net/keys/[A-Za-z0-9-]{1,127}/[0-9a-fA-F]{32}\Z"
)
_SIGNATURE = re.compile(r"[0-9a-f]{128}\Z")
_EXECUTOR_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
_MAX_SIGNED_BYTES = 64 * 1024
_MAX_PIN_BYTES = 16 * 1024
_PIN_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PIN_SERVICE = "svc.cert-verifier.independent"


def _public_coordinate(value: object) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ValueError("invalid P-256 public coordinate")
    decoded = base64.urlsafe_b64decode(value + "=")
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() != value:
        raise ValueError("noncanonical P-256 public coordinate")
    return int.from_bytes(decoded, "big")


def azure_es256_signed_bytes(row: dict, service_identity: str, key_id: str) -> bytes:
    """Return the domain-separated record bytes whose SHA-256 Key Vault signs."""
    if not isinstance(row, dict) or "attestation" in row:
        raise ValueError("unsigned certification record required")
    if not isinstance(service_identity, str) or not _SERVICE_ID.fullmatch(service_identity):
        raise ValueError("invalid verifier service identity")
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise ValueError("versioned Azure Key Vault key ID required")
    body = {"domain": _DOMAIN, "algorithm": "ES256",
            "verifier_identity": service_identity, "key_id": key_id, "record": row}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > _MAX_SIGNED_BYTES:
        raise ValueError("certification record exceeds signature limit")
    return encoded


def azure_es256_signing_digest(row: dict, service_identity: str, key_id: str) -> bytes:
    """Digest for Key Vault `sign(ES256, digest)` after protected review."""
    return hashlib.sha256(azure_es256_signed_bytes(row, service_identity, key_id)).digest()


class AzureES256CertificationVerifier:
    """Public-only registry callback keyed by exact versioned Key Vault ID.

    ``trusted_keys`` is ``{service_identity: {key_id: public_jwk}}``. A JWK
    contains exactly ``kty=EC``, ``crv=P-256``, and base64url ``x``/``y``.
    The attestation signature is lowercase hex of the 64-byte JOSE R||S value.
    """

    def __init__(self, trusted_keys: Mapping[str, Mapping[str, Mapping[str, str]]]):
        if not isinstance(trusted_keys, Mapping):
            raise TypeError("trusted keys must be a mapping")
        keys = {}
        for service, by_id in trusted_keys.items():
            if not isinstance(service, str) or not _SERVICE_ID.fullmatch(service):
                raise ValueError("invalid verifier service identity")
            if not isinstance(by_id, Mapping):
                raise TypeError("verifier keys must be a mapping")
            current = {}
            for key_id, jwk in by_id.items():
                if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
                    raise ValueError("versioned Azure Key Vault key ID required")
                if (not isinstance(jwk, Mapping) or set(jwk) != {"kty", "crv", "x", "y"}
                        or jwk["kty"] != "EC" or jwk["crv"] != "P-256"):
                    raise ValueError("P-256 public JWK required")
                numbers = ec.EllipticCurvePublicNumbers(
                    _public_coordinate(jwk["x"]), _public_coordinate(jwk["y"]), ec.SECP256R1())
                current[key_id] = numbers.public_key()
            keys[service] = current
        self._keys = keys

    def __call__(self, row: dict) -> bool:
        try:
            if not isinstance(row, dict) or any(field not in row for field in _REQUIRED_RECORD_FIELDS):
                return False
            proof = row.get("attestation")
            if not isinstance(proof, dict) or set(proof) != {
                    "algorithm", "key_id", "verifier_identity", "signature"}:
                return False
            service, key_id, signature = (proof["verifier_identity"], proof["key_id"],
                                          proof["signature"])
            if (proof["algorithm"] != "ES256" or not isinstance(service, str)
                    or not _SERVICE_ID.fullmatch(service) or not isinstance(key_id, str)
                    or not _KEY_ID.fullmatch(key_id) or not isinstance(signature, str)
                    or not _SIGNATURE.fullmatch(signature)):
                return False
            subject, reviewer, executor = (row["agent_id"], row["verifier"],
                                           row["executor_identity"])
            if (not all(isinstance(value, str) for value in (subject, reviewer, executor))
                    or canonical_agent_id(subject) != subject
                    or canonical_agent_id(reviewer) != reviewer or subject == reviewer
                    or reviewer == executor
                    or not _EXECUTOR_ID.fullmatch(executor)
                    or service in {subject, reviewer, executor}):
                return False
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
            if (_utc(row["certified_at"]) > _utc(row["last_revalidated"])
                    or _utc(row["last_revalidated"]) >= _utc(row["expires_at"])):
                return False
            key = self._keys.get(service, {}).get(key_id)
            if key is None:
                return False
            data = dict(row)
            data.pop("attestation")
            message = azure_es256_signed_bytes(data, service, key_id)
            raw = bytes.fromhex(signature)
            der = utils.encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                             int.from_bytes(raw[32:], "big"))
            key.verify(der, message, ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, KeyError, TypeError, ValueError, OverflowError,
                RecursionError, RegistryError):
            return False


def verifier_from_azure_es256_pin_file(
    path: Path, expected_sha256: str, *, untrusted_roots: tuple[Path, ...] = ()
) -> AzureES256CertificationVerifier:
    """Load an exact public pin from protected deployment configuration.

    The file and its expected digest are supplied by the deployer, never by a
    record. A new verifier is built on each call so removing a pin takes effect
    on the next projection. Missing, empty, or malformed configuration raises.
    """
    path = Path(path)
    if (not path.is_absolute() or not isinstance(expected_sha256, str)
            or not _PIN_SHA256.fullmatch(expected_sha256)):
        raise ValueError("absolute pin path and SHA-256 required")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("pin path may not contain a symlink")
    resolved = path.resolve(strict=True)
    if any(resolved.is_relative_to(Path(root).resolve()) for root in untrusted_roots):
        raise ValueError("pin path is inside an untrusted data root")
    with path.open("rb") as stream:
        raw = stream.read(_MAX_PIN_BYTES + 1)
    if len(raw) > _MAX_PIN_BYTES:
        raise ValueError("public pin file exceeds limit")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
        raise ValueError("public pin file digest mismatch")

    def unique_fields(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("duplicate public pin field")
            result[name] = value
        return result

    data = json.loads(raw, object_pairs_hook=unique_fields)
    if (not isinstance(data, dict) or set(data) != {"key_id", "jwk"}
            or not isinstance(data["key_id"], str)
            or not isinstance(data["jwk"], dict)):
        raise ValueError("invalid Azure ES256 public pin file")
    return AzureES256CertificationVerifier(
        {_PIN_SERVICE: {data["key_id"]: data["jwk"]}})
