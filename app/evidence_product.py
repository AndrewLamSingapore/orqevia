"""Portable Action Envelope, Evidence Ledger and reference SDK (v0.1).

This module is deliberately independent of PRIME.  It records evidence; it
does not create identity, authority, external truth or execution effects.
"""
from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = "action-envelope.v0.1"
CLAIM_STATES = {"SYSTEM_VERIFIED", "OBSERVED", "SOURCE_SUPPORTED", "CALCULATED",
                "INFERRED", "PREDICTED", "UNKNOWN", "CONTRADICTED", "STALE"}
VERIFICATION_STATES = {"VERIFIED", "PARTIAL", "UNVERIFIED", "FAILED", "CONTRADICTED", "NOT_APPLICABLE"}
RELATIONS = {"SUPERSEDES", "CORRECTS", "INVALIDATES", "REPLACES", "RELATED_TO"}
ACTION_STATES = {"REQUESTED", "INVOKED", "COMPLETED", "FAILED", "CANCELLED"}

OBSERVATION_PAYLOAD_BYTES = 196608
OBSERVATION_EVENTS = 64


class ObservationBudgetExceeded(RuntimeError):
    """Fixed internal failure: unavailable observation, never partial VALID."""


def observation_remaining(deadline: float) -> float:
    if type(deadline) not in (int, float) or not math.isfinite(deadline):
        raise ObservationBudgetExceeded('OBSERVATION_DEADLINE_INVALID')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ObservationBudgetExceeded('OBSERVATION_DEADLINE_EXCEEDED')
    return remaining


def observation_connection(path: str | Path, deadline: float) -> sqlite3.Connection:
    """Existing live SQLite read, not immutable: honor locks and WAL visibility."""
    remaining = observation_remaining(deadline)
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        raise FileNotFoundError('OBSERVATION_STORE_UNAVAILABLE')
    db = sqlite3.connect(target.resolve().as_uri() + '?mode=ro', uri=True,
                         timeout=min(0.05, remaining))
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA busy_timeout=' + str(max(0, int(min(0.05, observation_remaining(deadline)) * 1000))))
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        return db
    except BaseException:
        db.close()
        raise


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_digest(value: bytes, algorithm: str = "sha256") -> dict[str, str]:
    if algorithm != "sha256":
        raise ValueError("unsupported digest algorithm")
    return {"algorithm": algorithm, "value": hashlib.sha256(value).hexdigest()}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"


def validate_envelope(envelope: dict[str, Any], *, artifact_bytes: dict[str, bytes] | None = None,
                      observation_verifier=None) -> dict[str, Any]:
    """Validate structure and internal integrity, never unverifiable external facts."""
    errors: list[str] = []
    unresolved: list[str] = []
    if not isinstance(envelope,dict):
        return {"verdict":"INVALID","errors":["INVALID_SCHEMA:envelope_type"],"unresolved":[]}
    required = {"schema_version", "action_id", "objective", "actor", "authority", "started_at",
                "status", "inputs", "claims", "observations", "effects", "artifacts",
                "verification", "provenance", "relations"}
    if set(envelope) < required: errors.append("INVALID_SCHEMA:missing_fields")
    mapping_fields=("actor","authority","verification","provenance")
    list_fields=("inputs","claims","observations","effects","artifacts","relations")
    if any(not isinstance(envelope.get(field),dict) for field in mapping_fields):errors.append("INVALID_SCHEMA:mapping_field")
    if any(not isinstance(envelope.get(field),list) for field in list_fields):errors.append("INVALID_SCHEMA:list_field")
    if errors:
        return {"verdict":"INVALID","errors":sorted(set(errors)),"unresolved":[]}
    if any(not isinstance(item,dict) for field in list_fields for item in envelope[field]):
        return {"verdict":"INVALID","errors":["INVALID_SCHEMA:list_item"],"unresolved":[]}
    nested_lists=[*(claim.get("evidence_refs") for claim in envelope["claims"]),
                  *(effect.get("observation_refs") for effect in envelope["effects"]),
                  envelope["verification"].get("evidence")]
    if any(not isinstance(value,list) for value in nested_lists):
        return {"verdict":"INVALID","errors":["INVALID_SCHEMA:nested_list"],"unresolved":[]}
    if any(not isinstance(artifact.get("digest"),dict) for artifact in envelope["artifacts"]):
        return {"verdict":"INVALID","errors":["INVALID_SCHEMA:artifact_digest_type"],"unresolved":[]}
    if envelope.get("schema_version") != SCHEMA: errors.append("INVALID_SCHEMA:version")
    if envelope.get("status") not in ACTION_STATES: errors.append("INVALID_SCHEMA:action_status")
    actor = envelope.get("actor", {})
    authority = envelope.get("authority", {})
    if not actor.get("type") or not actor.get("id"): errors.append("INVALID_SCHEMA:actor")
    if not authority.get("scope") or not authority.get("source"): errors.append("INVALID_SCHEMA:authority")
    observations = {item.get("observation_id"): item for item in envelope.get("observations", [])}
    artifacts = {item.get("artifact_id"): item for item in envelope.get("artifacts", [])}
    evidence_ids = set(observations) | set(artifacts)
    governed_observations: set[str] = set()
    for observation_id, observation in observations.items():
        proof = observation.get("verification_ref")
        if not isinstance(proof, dict) or proof.get("state") != "SYSTEM_VERIFIED":
            continue
        expected = content_digest(canonical_bytes(observation.get("value")))
        if proof.get("digest") != expected:
            errors.append("DIGEST_MISMATCH:observation:" + str(observation_id))
        elif observation_verifier is None:
            unresolved.append("host_verification_not_supplied:" + str(observation_id))
        elif observation_verifier(proof, observation) is True:
            governed_observations.add(observation_id)
        else:
            errors.append("INVALID_REFERENCE:unverified_observation:" + str(observation_id))
    for claim in envelope.get("claims", []):
        if claim.get("state") not in CLAIM_STATES: errors.append("INVALID_SCHEMA:claim_state")
        refs = claim.get("evidence_refs", [])
        if any(ref not in evidence_ids for ref in refs): errors.append("INVALID_REFERENCE:claim_evidence")
        if not refs and claim.get("state") in {"SYSTEM_VERIFIED", "OBSERVED", "SOURCE_SUPPORTED", "CALCULATED"}:
            errors.append("INVALID_REFERENCE:verified_claim_without_evidence")
        if claim.get("state") == "SYSTEM_VERIFIED" and any(ref in observations and ref not in governed_observations for ref in refs):
            errors.append("INVALID_REFERENCE:system_claim_without_host_verified_evidence")
        if not refs: unresolved.append("claim_without_evidence:" + str(claim.get("claim_id")))
    for effect in envelope.get("effects", []):
        effect_refs = effect.get("observation_refs", [])
        if any(ref not in observations for ref in effect_refs):
            errors.append("INVALID_REFERENCE:effect_observation")
        if effect.get("state") == "VERIFIED" and not effect_refs:
            errors.append("INVALID_REFERENCE:verified_effect_without_observation")
        if effect.get("state") == "VERIFIED" and any(ref not in governed_observations for ref in effect_refs):
            errors.append("INVALID_REFERENCE:verified_effect_without_host_verified_observation")
        if effect.get("state") not in {"REQUESTED", "INVOKED", "OBSERVED", "VERIFIED", "FAILED"}:
            errors.append("INVALID_SCHEMA:effect_state")
    for artifact_id, artifact in artifacts.items():
        digest = artifact.get("digest", {})
        if digest.get("algorithm") != "sha256" or len(digest.get("value", "")) != 64:
            errors.append("INVALID_SCHEMA:artifact_digest")
        if artifact_bytes and artifact_id in artifact_bytes:
            actual = content_digest(artifact_bytes[artifact_id])
            if actual != digest: errors.append("DIGEST_MISMATCH:" + str(artifact_id))
        else:
            unresolved.append("artifact_bytes_not_supplied:" + str(artifact_id))
    relation_targets = {item.get("record_id") for item in envelope.get("relations", [])}
    if envelope.get("action_id") in relation_targets: errors.append("INVALID_SUPERSESSION:self_reference")
    for relation in envelope.get("relations", []):
        if relation.get("type") not in RELATIONS: errors.append("INVALID_SUPERSESSION:relation")
    verification = envelope.get("verification", {})
    if verification.get("state") not in VERIFICATION_STATES: errors.append("INVALID_SCHEMA:verification_state")
    verification_refs = verification.get("evidence", [])
    if any(ref not in evidence_ids for ref in verification_refs):
        errors.append("INVALID_REFERENCE:verification_evidence")
    if verification.get("state") == "VERIFIED" and (unresolved or not verification_refs):
        errors.append("INVALID_REFERENCE:verified_with_unresolved_evidence")
    if verification.get("state") == "VERIFIED":
        for ref in verification_refs:
            proof=observations[ref].get("verification_ref") if ref in observations else None
            if ref in observations and ref not in governed_observations:
                errors.append("INVALID_REFERENCE:unverified_observation")
    verdict = "INVALID" if errors else "UNVERIFIED" if unresolved else "VALID"
    return {"verdict": verdict, "errors": sorted(set(errors)), "unresolved": sorted(set(unresolved))}


def make_receipt(envelope: dict[str, Any], *, observation_verifier=None) -> dict[str, Any]:
    validation = validate_envelope(envelope, observation_verifier=observation_verifier)
    body = {"schema_version": "evidence-receipt.v0.1", "envelope": envelope,
            "validation": validation, "signature": None}
    return {**body, "digest": content_digest(canonical_bytes(body))}


def validate_receipt(receipt: dict[str, Any], *, artifact_bytes: dict[str, bytes] | None = None,
                     observation_verifier=None) -> dict[str, Any]:
    if not isinstance(receipt,dict):return {"verdict":"INVALID","errors":["INVALID_SCHEMA:receipt_type"],"unresolved":[]}
    body = {key: receipt.get(key) for key in ("schema_version", "envelope", "validation", "signature")}
    errors = []
    if receipt.get("schema_version") != "evidence-receipt.v0.1": errors.append("INVALID_SCHEMA:receipt")
    if receipt.get("digest") != content_digest(canonical_bytes(body)): errors.append("DIGEST_MISMATCH:receipt")
    current = validate_envelope(receipt.get("envelope", {}), artifact_bytes=artifact_bytes,
                                observation_verifier=observation_verifier)
    if current["errors"]: errors.extend(current["errors"])
    verdict = "INVALID" if errors else current["verdict"]
    return {"verdict": verdict, "errors": sorted(set(errors)), "unresolved": current["unresolved"]}


class EvidenceLedger:
    """SQLite reference ledger: append-only events with a per-action hash chain."""

    def __init__(self, path: str | Path, *, read_only: bool = False,
                 observation_deadline: float | None = None):
        self.path = str(path)
        self.read_only = read_only
        self.observation_deadline = observation_deadline
        if observation_deadline is not None:
            if not read_only:
                raise ValueError('OBSERVATION_REQUIRES_READ_ONLY')
            observation_remaining(observation_deadline)
        self._lock = threading.RLock()
        if read_only:
            if not Path(self.path).is_file(): raise FileNotFoundError(self.path)
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
            create table if not exists evidence_actions(
              action_id text primary key, namespace text not null, envelope_json text not null,
              envelope_digest text not null, revision integer not null, created_at text not null, updated_at text not null);
            create table if not exists evidence_events(
              sequence integer primary key autoincrement, event_id text unique not null,
              idempotency_key text unique not null, action_id text not null,
              event_type text not null, payload_json text not null, previous_digest text,
              event_digest text not null, created_at text not null,
              foreign key(action_id) references evidence_actions(action_id));
            create index if not exists evidence_action_events on evidence_events(action_id,sequence);
            """)

    def _connect(self) -> sqlite3.Connection:
        if self.observation_deadline is not None:
            db = observation_connection(self.path, self.observation_deadline)
            db.row_factory = sqlite3.Row
            return db
        target = Path(self.path).resolve().as_uri() + "?mode=ro" if self.read_only else self.path
        db = sqlite3.connect(target, timeout=10, uri=self.read_only)
        db.row_factory = sqlite3.Row
        db.execute("pragma foreign_keys=on")
        db.execute("pragma busy_timeout=10000")
        return db

    @contextmanager
    def _reading(self):
        db = self._connect()
        try:
            with db:
                if self.observation_deadline is not None:
                    db.execute('BEGIN')
                yield db
                if self.observation_deadline is not None:
                    observation_remaining(self.observation_deadline)
        finally:
            db.close()

    def _bounded_action(self, db, action_id, namespace):
        if self.observation_deadline is not None:
            observation_remaining(self.observation_deadline)
            size = db.execute('SELECT length(CAST(envelope_json AS BLOB))+'
                              'COALESCE(length(CAST(envelope_digest AS BLOB)),0)+'
                              'COALESCE(length(CAST(revision AS BLOB)),0) FROM evidence_actions '
                              'WHERE action_id=? AND namespace=?', (action_id, namespace)).fetchone()
            if size is None:
                raise KeyError('UNKNOWN_ACTION')
            if type(size[0]) is not int or not 0 <= size[0] <= OBSERVATION_PAYLOAD_BYTES:
                raise ObservationBudgetExceeded('OBSERVATION_PAYLOAD_EXCEEDED')
        return db.execute('SELECT envelope_json,envelope_digest,revision FROM evidence_actions '
                          'WHERE action_id=? AND namespace=?', (action_id, namespace)).fetchone()

    def _bounded_events(self, db, action_id, envelope_bytes=0):
        if self.observation_deadline is not None:
            sizes = db.execute('SELECT length(CAST(payload_json AS BLOB))+'
                'length(CAST(event_id AS BLOB))+length(CAST(idempotency_key AS BLOB))+'
                'length(CAST(action_id AS BLOB))+length(CAST(event_type AS BLOB))+'
                'length(CAST(created_at AS BLOB))+COALESCE(length(CAST(previous_digest AS BLOB)),0)+'
                'length(CAST(event_digest AS BLOB)) FROM evidence_events WHERE action_id=? '
                'ORDER BY sequence LIMIT ?', (action_id, OBSERVATION_EVENTS + 1)).fetchall()
            if (len(sizes) > OBSERVATION_EVENTS or any(type(r[0]) is not int or r[0] < 0 for r in sizes)
                    or envelope_bytes + sum(r[0] for r in sizes) > OBSERVATION_PAYLOAD_BYTES):
                raise ObservationBudgetExceeded('OBSERVATION_CHAIN_BUDGET_EXCEEDED')
            observation_remaining(self.observation_deadline)
            return [dict(r) for r in db.execute('SELECT * FROM evidence_events WHERE action_id=? '
                    'ORDER BY sequence LIMIT ?', (action_id, OBSERVATION_EVENTS + 1))]
        return [dict(r) for r in db.execute('SELECT * FROM evidence_events WHERE action_id=? '
                                          'ORDER BY sequence', (action_id,))]

    def create(self, *, namespace: str, objective: str, actor: dict[str, str], authority: dict[str, str],
               inputs: list[Any] | None = None, action_id: str | None = None,
               idempotency_key: str | None = None) -> dict[str, Any]:
        action_id = action_id or _id("act")
        envelope = {"schema_version": SCHEMA, "action_id": action_id, "objective": objective,
                    "actor": dict(actor), "authority": dict(authority), "started_at": _now(),
                    "completed_at": None, "status": "REQUESTED", "inputs": inputs or [],
                    "claims": [], "observations": [], "effects": [], "artifacts": [],
                    "verification": {"state": "UNVERIFIED", "evidence": []},
                    "provenance": {"record_owner": "HOST_SYSTEM", "namespace": namespace}, "relations": []}
        with self._lock, self._connect() as db:
            # The lock is per instance; SQLite must serialize duplicate requests
            # arriving through distinct API workers before the idempotency read.
            db.execute("begin immediate")
            existing = db.execute("select action_id from evidence_events where idempotency_key=?",
                                  (idempotency_key or f"create:{action_id}",)).fetchone()
            if existing: return self.get(existing["action_id"], namespace=namespace)
            if db.execute("select 1 from evidence_actions where action_id=?", (action_id,)).fetchone():
                raise ValueError("LEDGER_INTEGRITY:missing_creation_event")
            envelope_digest=content_digest(canonical_bytes(envelope))["value"]
            db.execute("insert into evidence_actions values(?,?,?,?,?,?,?)",
                       (action_id, namespace, canonical_bytes(envelope).decode(), envelope_digest, 1, envelope["started_at"], envelope["started_at"]))
            self._append(db, action_id, idempotency_key or f"create:{action_id}", "ACTION_CREATED", envelope["started_at"], {"objective": objective,"envelope_digest":envelope_digest,"revision":1})
        return envelope

    def _append(self, db: sqlite3.Connection, action_id: str, key: str, event_type: str,
                created_at: str, payload: Any) -> None:
        previous = db.execute("select event_digest from evidence_events where action_id=? order by sequence desc limit 1", (action_id,)).fetchone()
        previous_digest = previous[0] if previous else None
        event_id = _id("evt")
        protected = {"event_id": event_id, "idempotency_key": key, "action_id": action_id,
                     "event_type": event_type, "payload": payload, "previous_digest": previous_digest,
                     "created_at": created_at}
        db.execute("insert into evidence_events(event_id,idempotency_key,action_id,event_type,payload_json,previous_digest,event_digest,created_at) values(?,?,?,?,?,?,?,?)",
                   (event_id, key, action_id, event_type, canonical_bytes(payload).decode(), previous_digest,
                    content_digest(canonical_bytes(protected))["value"], created_at))

    def get(self, action_id: str, *, namespace: str) -> dict[str, Any]:
        with self._reading() as db:
            row = self._bounded_action(db, action_id, namespace)
        if row is None: raise KeyError("UNKNOWN_ACTION")
        return json.loads(row["envelope_json"])

    def mutate(self, action_id: str, *, namespace: str, event_type: str, idempotency_key: str,
               apply: Any) -> dict[str, Any]:
        if self.verify_chain(action_id, namespace=namespace)["verdict"] != "VALID":
            raise ValueError("LEDGER_INTEGRITY:mutation_denied")
        with self._lock, self._connect() as db:
            db.execute("begin immediate")
            duplicate = db.execute("select action_id from evidence_events where idempotency_key=?", (idempotency_key,)).fetchone()
            if duplicate:
                if duplicate["action_id"] != action_id: raise ValueError("INVALID_REFERENCE:idempotency_collision")
                return self.get(action_id, namespace=namespace)
            row = db.execute("select * from evidence_actions where action_id=? and namespace=?", (action_id, namespace)).fetchone()
            if row is None: raise KeyError("UNKNOWN_ACTION")
            envelope = json.loads(row["envelope_json"])
            apply(envelope)
            now = _now(); revision = row["revision"] + 1
            envelope_digest=content_digest(canonical_bytes(envelope))["value"]
            db.execute("update evidence_actions set envelope_json=?,envelope_digest=?,revision=?,updated_at=? where action_id=?",
                       (canonical_bytes(envelope).decode(), envelope_digest, revision, now, action_id))
            self._append(db, action_id, idempotency_key, event_type, now, {"revision": revision,"envelope_digest":envelope_digest})
        return envelope

    def events(self, action_id: str, *, namespace: str) -> list[dict[str, Any]]:
        if self.observation_deadline is None:
            self.get(action_id, namespace=namespace)
            with self._reading() as db:
                return self._bounded_events(db, action_id)
        with self._reading() as db:
            row = self._bounded_action(db, action_id, namespace)
            if row is None: raise KeyError('UNKNOWN_ACTION')
            return self._bounded_events(db, action_id, len(row['envelope_json'].encode()))

    def verify_chain(self, action_id: str, *, namespace: str) -> dict[str, Any]:
        # Read the event chain and head from one SQLite snapshot. Separate
        # connections could observe opposite sides of a concurrent append.
        with self._reading() as db:
            if self.observation_deadline is None:
                db.execute("begin")
            action_row=self._bounded_action(db, action_id, namespace)
            if action_row is None: raise KeyError("UNKNOWN_ACTION")
            events=self._bounded_events(db, action_id, len(action_row['envelope_json'].encode()))
        previous = None; errors = []
        if not events or events[0]["event_type"] != "ACTION_CREATED":
            errors.append("LEDGER_INTEGRITY:missing_creation_event")
        for event in events:
            if self.observation_deadline is not None:
                observation_remaining(self.observation_deadline)
            payload = json.loads(event["payload_json"])
            protected = {"event_id": event["event_id"], "idempotency_key": event["idempotency_key"],
                         "action_id": event["action_id"], "event_type": event["event_type"],
                         "payload": payload, "previous_digest": event["previous_digest"], "created_at": event["created_at"]}
            if event["previous_digest"] != previous or event["event_digest"] != content_digest(canonical_bytes(protected))["value"]:
                errors.append("LEDGER_INTEGRITY:" + event["event_id"])
            previous = event["event_digest"]
        actual=content_digest(action_row["envelope_json"].encode())["value"]
        if actual!=action_row["envelope_digest"]: errors.append("LEDGER_INTEGRITY:envelope_digest")
        if events:
            final_payload=json.loads(events[-1]["payload_json"])
            if final_payload.get("envelope_digest")!=action_row["envelope_digest"] or final_payload.get("revision")!=action_row["revision"]:
                errors.append("LEDGER_INTEGRITY:envelope_head_binding")
        result={"verdict": "VALID" if not errors else "INVALID", "errors": errors, "events": len(events), "head": previous}
        if self.observation_deadline is not None:
            observation_remaining(self.observation_deadline)
            result['envelope_digest']=actual
        return result

    def query(self, *, namespace: str, actor_id: str | None = None,
              verification_state: str | None = None) -> list[dict[str, Any]]:
        with self._reading() as db:
            if self.observation_deadline is not None:
                sizes=db.execute('SELECT length(CAST(envelope_json AS BLOB)) FROM evidence_actions '
                    'WHERE namespace=? ORDER BY created_at LIMIT 65',(namespace,)).fetchall()
                if len(sizes)>64 or any(type(r[0]) is not int or r[0]<0 for r in sizes) or sum(r[0] for r in sizes)>OBSERVATION_PAYLOAD_BYTES:
                    raise ObservationBudgetExceeded('OBSERVATION_QUERY_PAYLOAD_EXCEEDED')
                observation_remaining(self.observation_deadline)
            rows = db.execute("select envelope_json from evidence_actions where namespace=? order by created_at"+
                              (' LIMIT 65' if self.observation_deadline is not None else ''), (namespace,)).fetchall()
        values = [json.loads(row[0]) for row in rows]
        if actor_id: values = [item for item in values if item["actor"]["id"] == actor_id]
        if verification_state: values = [item for item in values if item["verification"]["state"] == verification_state]
        return values


class EvidenceAction:
    """Small reference SDK facade around EvidenceLedger."""
    def __init__(self, ledger: EvidenceLedger, namespace: str, envelope: dict[str, Any]):
        self.ledger, self.namespace, self.envelope = ledger, namespace, envelope

    @property
    def action_id(self) -> str: return self.envelope["action_id"]

    def _change(self, event: str, key: str, fn: Any) -> dict[str, Any]:
        self.envelope = self.ledger.mutate(self.action_id, namespace=self.namespace, event_type=event,
                                           idempotency_key=key, apply=fn)
        return self.envelope

    def invoke(self, *, tool_ref: str, idempotency_key: str) -> dict[str, Any]:
        def apply(e): e.update(status="INVOKED"); e["provenance"]["tool_ref"] = tool_ref
        return self._change("ACTION_INVOKED", idempotency_key, apply)

    def claim(self, text: str, *, state: str = "INFERRED", evidence_refs: list[str] | None = None,
              claim_id: str | None = None, idempotency_key: str) -> str:
        if state not in CLAIM_STATES: raise ValueError("INVALID_SCHEMA:claim_state")
        claim_id = claim_id or _id("clm")
        self._change("CLAIM_RECORDED", idempotency_key,
                     lambda e: e["claims"].append({"claim_id": claim_id, "text": text, "state": state,
                                                   "evidence_refs": evidence_refs or [], "created_at": _now()}))
        return claim_id

    def observe(self, source: str, value: Any, *, verification_ref: dict[str, Any] | None = None,
                observation_id: str | None = None, idempotency_key: str) -> str:
        observation_id = observation_id or _id("obs")
        item = {"observation_id": observation_id, "source": source, "value": value,
                "observed_at": _now(), "verification_ref": verification_ref}
        self._change("OBSERVATION_RECORDED", idempotency_key, lambda e: e["observations"].append(item))
        return observation_id

    def effect(self, description: str, *, state: str, observation_refs: list[str],
               effect_id: str | None = None, idempotency_key: str) -> str:
        effect_id = effect_id or _id("eff")
        item = {"effect_id": effect_id, "description": description, "state": state,
                "observation_refs": observation_refs, "recorded_at": _now()}
        self._change("EFFECT_RECORDED", idempotency_key, lambda e: e["effects"].append(item))
        return effect_id

    def attach(self, path: str | Path, *, artifact_id: str | None = None,
               idempotency_key: str) -> str:
        path = Path(path); raw = path.read_bytes(); artifact_id = artifact_id or _id("art")
        item = {"artifact_id": artifact_id, "name": path.name, "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "bytes": len(raw), "digest": content_digest(raw), "created_at": _now(), "action_id": self.action_id,
                "availability": "HOST_MANAGED"}
        self._change("ARTIFACT_ATTACHED", idempotency_key, lambda e: e["artifacts"].append(item))
        return artifact_id

    def verify(self, state: str, evidence_refs: list[str], *, idempotency_key: str) -> dict[str, Any]:
        if state not in VERIFICATION_STATES: raise ValueError("INVALID_SCHEMA:verification_state")
        available={item["observation_id"] for item in self.envelope["observations"]}|{item["artifact_id"] for item in self.envelope["artifacts"]}
        if any(ref not in available for ref in evidence_refs): raise ValueError("INVALID_REFERENCE:verification_evidence")
        if state=="VERIFIED" and not evidence_refs: raise ValueError("INVALID_REFERENCE:verified_without_evidence")
        def apply(e):
            e["verification"] = {"state": state, "evidence": list(evidence_refs)}
            e["status"] = "COMPLETED" if state in {"VERIFIED", "PARTIAL", "UNVERIFIED", "CONTRADICTED"} else "FAILED"
            e["completed_at"] = _now()
        return self._change("VERIFICATION_RECORDED", idempotency_key, apply)

    def relate(self, relation: str, record_id: str, *, reason: str, idempotency_key: str) -> dict[str, Any]:
        if relation not in RELATIONS: raise ValueError("INVALID_SUPERSESSION")
        return self._change("RELATION_RECORDED", idempotency_key,
                            lambda e: e["relations"].append({"type": relation, "record_id": record_id,
                                                             "reason": reason, "created_at": _now()}))

    def receipt(self, *, observation_verifier=None) -> dict[str, Any]:
        return make_receipt(self.envelope, observation_verifier=observation_verifier)


@contextmanager
def action(ledger: EvidenceLedger, *, namespace: str, objective: str, actor: dict[str, str],
           authority: dict[str, str], idempotency_key: str) -> Iterator[EvidenceAction]:
    envelope = ledger.create(namespace=namespace, objective=objective, actor=actor, authority=authority,
                             idempotency_key=idempotency_key)
    yield EvidenceAction(ledger, namespace, envelope)
