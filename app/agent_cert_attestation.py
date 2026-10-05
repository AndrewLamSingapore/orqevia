"""Authenticated verifier callback for agent certification projections.

Use ``CertificationAttestationVerifier(...)`` as the ``verify_record`` callback
of :class:`AgentCertificationRegistry`. Keys are supplied by a separately
trusted authority at runtime; this module never loads keys, signs records, or
grants agent execution authority. An empty/revoked key map denies every row.

Key custody boundary: HMAC is symmetric. The verifier process can forge proofs
if compromised, so the authority that provisions keys must keep them outside
Git, manifests, artifacts, agent tools, prompts, frontend code and logs. Do
not give an individual agent its own verification key. A deployment unable to
enforce that separation must leave certification at L0. Key rotation/revocation
is the caller's responsibility; recreate the verifier with only current keys.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping

from .agent_registry import RegistryError, agent_record, canonical_agent_id


_DOMAIN = "prime.agent-certification.record.v1"
_ALGORITHM = "HMAC-SHA256"
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_KEY_ID = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
_MAX_SIGNED_BYTES = 64 * 1024


def _authenticated_bytes(row: dict, key_id: str) -> bytes:
    """Bind every record field and the selected key to a domain-separated MAC."""
    body = {
        "domain": _DOMAIN,
        "algorithm": _ALGORITHM,
        "key_id": key_id,
        "record": {field: value for field, value in row.items() if field != "attestation"},
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > _MAX_SIGNED_BYTES:
        raise ValueError("certification record exceeds authentication limit")
    return encoded


class CertificationAttestationVerifier:
    """Callable, deny-by-default ``verify_record`` adapter.

    ``trusted_keys`` maps canonical verifier agent IDs to current key IDs and
    32+-byte secrets. Keys are injected by a trusted caller, not read from the
    record or filesystem. The callback authenticates evidence *claims*; the
    registry separately validates artifacts, roles, freshness and source.
    """

    def __init__(self, trusted_keys: Mapping[str, Mapping[str, bytes]]):
        keys: dict[str, dict[str, bytes]] = {}
        for verifier, by_id in trusted_keys.items():
            try:
                if not isinstance(verifier, str) or canonical_agent_id(verifier) != verifier:
                    raise ValueError("verifier must be a canonical registered agent")
                agent_record(verifier)
            except RegistryError as error:
                raise ValueError("verifier must be a canonical registered agent") from error
            if not isinstance(by_id, Mapping):
                raise TypeError("verifier keys must be a mapping")
            current: dict[str, bytes] = {}
            for key_id, secret in by_id.items():
                if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
                    raise ValueError("invalid verifier key id")
                if not isinstance(secret, bytes) or len(secret) < 32:
                    raise ValueError("verifier key must be at least 32 bytes")
                current[key_id] = secret
            keys[verifier] = current
        self._keys = keys

    def __call__(self, row: dict) -> bool:
        try:
            if not isinstance(row, dict):
                return False
            attestation = row.get("attestation")
            if not isinstance(attestation, dict) or set(attestation) != {
                "algorithm", "key_id", "signature"
            }:
                return False
            if attestation["algorithm"] != _ALGORITHM:
                return False
            key_id = attestation["key_id"]
            signature = attestation["signature"]
            if (not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id)
                    or not isinstance(signature, str)
                    or not _HEX_SHA256.fullmatch(signature)):
                return False
            verifier = row.get("verifier")
            subject = row.get("agent_id")
            if (not isinstance(verifier, str) or not isinstance(subject, str)
                    or canonical_agent_id(verifier) != verifier
                    or canonical_agent_id(subject) != subject
                    or verifier == subject):
                return False
            key = self._keys.get(verifier, {}).get(key_id)
            if key is None:
                return False
            expected = hmac.new(key, _authenticated_bytes(row, key_id),
                                hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, signature)
        except (KeyError, TypeError, ValueError, OverflowError, RecursionError,
                RegistryError):
            return False
