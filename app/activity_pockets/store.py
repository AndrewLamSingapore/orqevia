"""SQLite lifecycle storage with atomic transitions, fencing and chained evidence."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

from .contracts import ExecutionEvent, Provenance


def canonical(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Store:
    def __init__(self, path, revision, *, origin="runtime"):
        self.path = Path(path)
        self.revision, self.origin = revision, origin
        self.provenance("factory", "initialization")  # Validate before opening storage.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS pockets(
                  id TEXT PRIMARY KEY, owner TEXT NOT NULL, manifest TEXT NOT NULL,
                  state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', version TEXT NOT NULL,
                  cursor INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                  bytes INTEGER NOT NULL DEFAULT 0, records INTEGER NOT NULL DEFAULT 0,
                  seconds REAL NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0,
                  failures INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL, updated REAL NOT NULL,
                  lease TEXT, lease_until REAL, idempotency_key TEXT NOT NULL,
                  request_digest TEXT NOT NULL,
                  UNIQUE(owner,idempotency_key));
                CREATE TABLE IF NOT EXISTS pocket_records(
                  kind TEXT NOT NULL, id TEXT NOT NULL, owner TEXT NOT NULL, pocket_id TEXT NOT NULL,
                  body TEXT NOT NULL, PRIMARY KEY(kind,id));
                CREATE INDEX IF NOT EXISTS records_scope ON pocket_records(owner,pocket_id,kind);
                CREATE TABLE IF NOT EXISTS pocket_events(
                  sequence INTEGER PRIMARY KEY, pocket_id TEXT NOT NULL, owner TEXT NOT NULL,
                  body TEXT NOT NULL, previous_sha256 TEXT NOT NULL, sha256 TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS pocket_evidence_lookup ON pocket_events(
                  owner,json_extract(body,'$.details.kind'),json_extract(body,'$.details.id'));
                CREATE TABLE IF NOT EXISTS source_access(source_id TEXT PRIMARY KEY, next_at REAL NOT NULL,
                  lease TEXT, lease_until REAL, robots_cache TEXT);
                CREATE TABLE IF NOT EXISTS pocket_runs(
                  id TEXT PRIMARY KEY, pocket_id TEXT NOT NULL, owner TEXT NOT NULL,
                  idempotency_key TEXT NOT NULL, lease TEXT NOT NULL, started REAL NOT NULL,
                  status TEXT NOT NULL, report TEXT NOT NULL, reserved_bytes INTEGER NOT NULL, reserved_seconds REAL NOT NULL,
                  UNIQUE(pocket_id,idempotency_key));
                CREATE TABLE IF NOT EXISTS pocket_worker(
                  id INTEGER PRIMARY KEY CHECK(id=1), observed REAL NOT NULL, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pocket_control(owner TEXT PRIMARY KEY, stopped INTEGER NOT NULL);
            """)

    def provenance(self, component, reference):
        return Provenance(component=component, source_revision=self.revision, origin=self.origin, reference=reference)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def put(self, db, kind, record, pocket_id=""):
        body = record.model_dump(mode="json")
        db.execute("INSERT INTO pocket_records VALUES(?,?,?,?,?)",
                   (kind, record.id, record.owner, pocket_id, canonical(body)))
        self.event(db, pocket_id or "library", record.owner, record.provenance.component,
                   "evidence.recorded", {"kind": kind, "id": record.id, "sha256": digest(body)})
        return body

    def get(self, db, kind, record_id, owner, pocket_id=None):
        row = db.execute("SELECT body,pocket_id FROM pocket_records WHERE kind=? AND id=? AND owner=?",
                         (kind, record_id, owner)).fetchone()
        if row is None or (pocket_id is not None and row["pocket_id"] != pocket_id):
            raise KeyError("record unavailable in this scope")
        body = json.loads(row["body"])
        evidence = db.execute("SELECT * FROM pocket_events WHERE owner=? AND "
            "json_extract(body,'$.event_type')='evidence.recorded' AND json_extract(body,'$.details.kind')=? "
            "AND json_extract(body,'$.details.id')=?", (owner, kind, record_id)).fetchone()
        if evidence is None:
            raise ValueError("record has no original audit evidence")
        event = json.loads(evidence["body"])
        event_value = {"sequence": evidence["sequence"], "event": event, "previous_sha256": evidence["previous_sha256"]}
        if digest(event_value) != evidence["sha256"] or event["details"]["sha256"] != digest(body):
            raise ValueError("stored record differs from its original audit evidence")
        return body

    def records(self, db, kind, owner, pocket_id):
        return [self.get(db, kind, row[0], owner, pocket_id) for row in db.execute(
            "SELECT id FROM pocket_records WHERE kind=? AND owner=? AND pocket_id=? ORDER BY rowid",
            (kind, owner, pocket_id)).fetchall()]

    def event(self, db, pocket_id, owner, actor, event_type, details=None):
        event = ExecutionEvent(pocket_id=pocket_id, owner=owner, actor=actor, event_type=event_type,
                               details=details or {}, provenance=self.provenance("factory", pocket_id))
        last = db.execute("SELECT sequence,sha256 FROM pocket_events ORDER BY sequence DESC LIMIT 1").fetchone()
        sequence, previous = (last[0] + 1, last[1]) if last else (1, "0" * 64)
        value = {"sequence": sequence, "event": event.model_dump(mode="json"), "previous_sha256": previous}
        db.execute("INSERT INTO pocket_events VALUES(?,?,?,?,?,?)",
                   (sequence, pocket_id, owner, canonical(value["event"]), previous, digest(value)))
        return event.id

    def verify_events(self, db):
        previous, sequence = "0" * 64, 0
        for row in db.execute("SELECT * FROM pocket_events ORDER BY sequence"):
            sequence += 1
            value = {"sequence": sequence, "event": json.loads(row["body"]), "previous_sha256": previous}
            if row["sequence"] != sequence or row["previous_sha256"] != previous or digest(value) != row["sha256"]:
                return False
            previous = row["sha256"]
        try:
            for row in db.execute("SELECT kind,id,owner FROM pocket_records").fetchall():
                self.get(db, row["kind"], row["id"], row["owner"])
        except (ValueError, KeyError):
            return False
        return True
