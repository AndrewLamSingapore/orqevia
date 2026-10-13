import copy
import hashlib
import json
from pathlib import Path

import pytest

from app import portfolio_event_compat as compat


def event(source="orqevia", identity="compat-event-0001"):
    return {"schema_version":"1.0.0","event_id":identity,"event_type":"portfolio.observation.recorded",
            "source":source,"occurred_at":"2026-10-13T00:00:00Z","correlation_id":"compat-fixture",
            "subject_id":"local-subject-1","evidence_level":"E1","provenance":["fixture:unverified-producer"],
            "payload":{"summary":"Structured journal · no hidden reasoning","verification":"UNVERIFIED"}}


@pytest.mark.parametrize("version,source",[("2.0.0","prime"),("2.0.0","the-portal"),
    ("3.0.0","orqevia"),("3.0.0","the-portal"),("3.0.0","velyqua"),
    ("3.0.0","game-platform"),("3.0.0","authority-engine")])
def test_explicit_versions_preserve_original_bytes_and_every_field_except_declared_alias(version,source):
    original=event(source)
    raw=json.dumps(original,indent=2,ensure_ascii=False).encode("utf-8")
    canonical,envelope=compat.adapt_original_event(raw,contract_version=version,schema_sha256=compat.SCHEMA_PINS[version])
    expected=copy.deepcopy(original)
    if source=="orqevia":expected["source"]="prime"
    assert canonical==expected
    assert envelope["raw"] is raw
    receipt=compat.validate_original_envelope(envelope,canonical)
    assert receipt["original_sha256"]==hashlib.sha256(raw).hexdigest()
    assert receipt["original_source"]==source and receipt["canonical_source"]==expected["source"]
    assert "authenticated" not in receipt and "verified" not in receipt
    assert canonical["evidence_level"]=="E1" and canonical["payload"]["verification"]=="UNVERIFIED"


@pytest.mark.parametrize("version,source",[("3.0.0","prime"),("2.0.0","orqevia"),("2.0.0","sky-tablet"),("3.0.0","sky-tablet")])
def test_invalid_version_source_pairs_cannot_expand_existing_producer_contract(version,source):
    with pytest.raises(ValueError):compat.adapt_original_event(json.dumps(event(source)).encode(),contract_version=version,schema_sha256=compat.SCHEMA_PINS[version])


@pytest.mark.parametrize("raw",[b'{"source":"orqevia","source":"prime"}',b'[]',b'{"x":NaN}',b'\xff',b'{',b' '*(compat.MAX_ORIGINAL_BYTES+1)])
def test_malformed_duplicate_nonfinite_and_oversized_originals_fail_before_ingest(raw):
    class NoEffects:
        def ingest(self,*args,**kwargs):raise AssertionError("Invalid original reached persistent effects")
    with pytest.raises(ValueError):compat.ingest_original_event(NoEffects(),raw,contract_version="3.0.0",schema_sha256=compat.SCHEMA_PINS["3.0.0"])


@pytest.mark.parametrize("change",["unknown-version","wrong-pin","extra-envelope","non-byte-wire","extra-event","wrong-time","missing-provenance","changed-canonical"])
def test_declared_pins_shape_and_alias_only_correspondence_are_enforced(change):
    original=event();raw=json.dumps(original).encode()
    canonical,envelope=compat.adapt_original_event(raw,contract_version="3.0.0",schema_sha256=compat.SCHEMA_PINS["3.0.0"])
    if change=="unknown-version":envelope["contract_version"]="4.0.0"
    elif change=="wrong-pin":envelope["schema_sha256"]="0"*64
    elif change=="extra-envelope":envelope["verified"]=True
    elif change=="non-byte-wire":envelope["raw"]=raw.decode()
    elif change=="changed-canonical":canonical["payload"]["summary"]="changed"
    else:
        if change=="extra-event":original["may_execute"]=True
        elif change=="wrong-time":original["occurred_at"]="not-a-date"
        elif change=="missing-provenance":original["provenance"]=[]
        envelope["raw"]=json.dumps(original).encode()
    with pytest.raises(ValueError):compat.validate_original_envelope(envelope,canonical)


def test_consumer_schema_drift_cannot_be_hidden_by_a_supplied_old_pin(monkeypatch):
    schema=copy.deepcopy(compat.SCHEMAS["portfolio-event-v1"])
    schema["properties"]["evidence_level"]["enum"].append("E9")
    monkeypatch.setitem(compat.SCHEMAS,"portfolio-event-v1",schema)
    with pytest.raises(ValueError,match="consumer schema changed"):
        compat.adapt_original_event(json.dumps(event()).encode(),contract_version="3.0.0",schema_sha256=compat.SCHEMA_PINS["3.0.0"])


def test_pinned_producer_schema_bytes_cannot_be_changed(monkeypatch):
    original_read=Path.read_bytes
    def changed(path):
        raw=original_read(path)
        return raw+b" " if path.name=="portfolio-event-v1.v3.schema.json" else raw
    monkeypatch.setattr(Path,"read_bytes",changed)
    with pytest.raises(ValueError,match="producer schema bytes changed"):
        compat.adapt_original_event(json.dumps(event()).encode(),contract_version="3.0.0",schema_sha256=compat.SCHEMA_PINS["3.0.0"])
