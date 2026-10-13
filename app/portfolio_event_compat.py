"""Optional, pinned Portfolio Event v1 bundle compatibility; custody grants no trust.

No HTTP mount, network client, authentication or runtime gateway is introduced.
Original wire bytes remain a separate envelope. Only the documented v3 ORQEVIA
source alias is translated for the existing v2 consumer. Producer authentication
and verification of evidence maturity remain the host's separate obligations.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .generated.portfolio_contracts import SCHEMAS, assert_contract

ADAPTER_VERSION = "1.0.0"
MAX_ORIGINAL_BYTES = 1_000_000
SCHEMA_PINS = {
    "2.0.0": "59fd09162a69dd577a05547261b3408edf1e12de720a940508d2e9895ecb794e",
    "3.0.0": "5ada9bed9baa92d7cb31b714162af243a0e3ef0c0f169c90f64cf687cc4cd238",
}
V3_SOURCE = {
    "repository": "AndrewLamSingapore/AndrewLamSingapore",
    "revision": "8e81c07f0e2f149b10be1a2d221049ae28f27f7b",
    "path": "portfolio-contracts/schemas/portfolio-event-v1.schema.json",
    "raw_sha256": "1a338861ee9ba7b4e397433f5e812187b4261f16d54d0ef736a38ed36202ca2a",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _schema_bytes(value: Any) -> bytes:
    # Exact owner generator encoding: JSON.stringify(schema, null, 2) + '\n'.
    # Preserve insertion order; wire/event digests use canonical_bytes separately.
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate original event field")
        result[name] = value
    return result


def _reject_constant(_value: str):
    raise ValueError("Non-finite original event value")


def _pinned_schemas() -> tuple[dict, dict]:
    old = SCHEMAS["portfolio-event-v1"]
    if hashlib.sha256(_schema_bytes(old)).hexdigest() != SCHEMA_PINS["2.0.0"]:
        raise ValueError("Pinned consumer schema changed")
    raw = Path(__file__).with_name("contract_data").joinpath("portfolio-event-v1.v3.schema.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != V3_SOURCE["raw_sha256"]:
        raise ValueError("Pinned producer schema bytes changed")
    new = json.loads(raw)
    if hashlib.sha256(_schema_bytes(new)).hexdigest() != SCHEMA_PINS["3.0.0"]:
        raise ValueError("Pinned producer schema changed")
    normalized = copy.deepcopy(new)
    normalized["title"] = old["title"]
    normalized["properties"]["source"]["enum"] = old["properties"]["source"]["enum"]
    if normalized != old or new["properties"]["source"]["enum"] != [
        "orqevia", "the-portal", "velyqua", "game-platform", "authority-engine"
    ]:
        raise ValueError("Producer schema requires a different compatibility adapter")
    return old, new


def _parse_original(envelope: Mapping[str, Any]) -> tuple[dict, str, str, bytes]:
    if not isinstance(envelope, Mapping) or set(envelope) != {"contract_version", "schema_sha256", "raw"}:
        raise ValueError("Original envelope has an unsupported shape")
    version = envelope["contract_version"]
    if not isinstance(version, str) or version not in SCHEMA_PINS or envelope["schema_sha256"] != SCHEMA_PINS[version]:
        raise ValueError("Explicit supported producer bundle version and schema pin required")
    raw = envelope["raw"]
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_ORIGINAL_BYTES:
        raise ValueError("Original event must be bounded UTF-8 wire bytes")
    try:
        event = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Malformed original event bytes") from exc
    if not isinstance(event, dict):
        raise ValueError("Original event must be an object")
    _, producer = _pinned_schemas()
    allowed = producer["properties"]["source"]["enum"] if version == "3.0.0" else SCHEMAS["portfolio-event-v1"]["properties"]["source"]["enum"]
    if event.get("source") not in allowed:
        raise ValueError("Original source is outside the declared producer contract")
    canonical = copy.deepcopy(event)
    if version == "3.0.0" and canonical["source"] == "orqevia":
        canonical["source"] = "prime"
    assert_contract("portfolio-event-v1", canonical)
    return canonical, version, event["source"], raw


def validate_original_envelope(envelope: Mapping[str, Any], canonical_event: Mapping[str, Any]) -> dict[str, str]:
    canonical, version, original_source, raw = _parse_original(envelope)
    if canonical_bytes(canonical) != canonical_bytes(dict(canonical_event)):
        raise ValueError("Original event does not match the alias-only canonical event")
    return {
        "contract_version": version,
        "schema_sha256": SCHEMA_PINS[version],
        "original_sha256": hashlib.sha256(raw).hexdigest(),
        "original_source": original_source,
        "canonical_source": canonical["source"],
        "adapter_version": ADAPTER_VERSION,
    }


def adapt_original_event(raw: bytes, *, contract_version: str, schema_sha256: str) -> tuple[dict, dict]:
    """Prepare the canonical event and custody envelope without writing any state."""
    envelope = {"contract_version": contract_version, "schema_sha256": schema_sha256, "raw": raw}
    canonical, _, _, _ = _parse_original(envelope)
    validate_original_envelope(envelope, canonical)
    return canonical, envelope


def ingest_original_event(fabric, raw: bytes, *, contract_version: str, schema_sha256: str) -> dict:
    """Host opt-in only; inbox stores exact original and projection input together."""
    canonical, envelope = adapt_original_event(raw, contract_version=contract_version, schema_sha256=schema_sha256)
    return fabric.ingest(canonical, original_envelope=envelope)
