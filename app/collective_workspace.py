"""Private structured engineering notes and bounded shared collaboration.

The API composition must authenticate principals before calling this module.
Core PRIME has its own private pad, never an override of other principals.
Notes are explicit work records, not hidden model reasoning. This isolated store
does not promote MemoryStore knowledge, publish EventFabric events, grant tool
permissions or claim agent acceptance. SQLite transactions follow those stores'
local durability convention while avoiding their differing authority scopes.
Credential rejection is defense in depth, not a complete DLP classifier; callers
must supply minimized engineering summaries, never raw user messages or secrets.
Evidence labels are submitted classifications, not truth established by agreement.
References are opaque IDs; artifact provenance/permission validation belongs to
the authenticated composition. Delivery replay covers subscribed messages only;
new subscriptions do not backfill old messages. Archival preserves original
content and cannot reclaim a capacity ceiling; reviewed export/retention and
physical database backup are operational work outside this incremental module.
Task leases record work coordination, never execute tools or authorize retries
of external side effects. Three total claims per task is deliberately stricter
than three attempts per unchanged failure; new diagnostic tasks require new IDs.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import re
import sqlite3
import time
import uuid
import unicodedata
import math
from pathlib import Path

from .agent_registry import registered_agent_ids, agent_record

BOARDS = ("GLOBAL", "TASKS", "RESEARCH", "ENGINEERING", "INCIDENTS", "DECISIONS", "EVIDENCE", "BLOCKERS", "HANDOFFS", "CERTIFICATION")
ENGINEERING_FIELDS = frozenset({"objective", "decomposition", "hypotheses", "assumptions", "plans", "alternatives", "calculations", "analysis", "tool_results", "experiments", "questions", "dependencies", "next_actions", "completion_criteria"})
NOTE_FIELDS = ENGINEERING_FIELDS | frozenset({"summary", "decision", "next_action", "failure", "evidence_refs", "task_refs", "evidence_level", "confidence", "uncertainty"})
HIDDEN_FIELDS = frozenset({"thoughts", "chain_of_thought", "hidden_reasoning", "raw_prompt", "raw_user_message", "raw_user_messages"})
SECRET = re.compile(r"(?i)(?:\b(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|authorization|credential|private[_ -]?key)\b[\s\"'\\]*[:=]|\bbearer\s+\S+|\b(?:sk-[a-z0-9_-]{8,}|hf_[a-z0-9]{8,}|gh[pousr]_[a-z0-9]{8,})\b|-----BEGIN[^\n]*PRIVATE KEY|[a-z]+://[^\s/:]+:[^\s/@]+@|\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class Conflict(ValueError):
    """Stale revision, conflicting idempotency key or lease."""


class _Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value) or SECRET.search(value):
        raise ValueError("invalid identifier")
    return value


def structured_note(value):
    if not isinstance(value, dict) or not value or set(value) - NOTE_FIELDS:
        raise ValueError("structured engineering fields required")
    for key, field in value.items():
        if key in ENGINEERING_FIELDS:
            bounded_engineering_value(field)
        elif key in ("confidence", "uncertainty"):
            if type(field) not in (int, float) or not 0 <= field <= 1 or not math.isfinite(field):
                raise ValueError("confidence/uncertainty must be finite between zero and one")
        elif key == "evidence_level":
            if field not in ("verified_fact", "hypothesis", "unknown"):
                raise ValueError("invalid evidence label")
            if field == "verified_fact" and not value.get("evidence_refs"):
                raise ValueError("verified fact label requires evidence references")
        elif key.endswith("_refs"):
            if not isinstance(field, list) or len(field) > 32:
                raise ValueError("bounded references required")
            for ref in field:
                identifier(ref)
        elif not isinstance(field, str) or len(field) > 4000:
            raise ValueError("bounded summary string required")
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    normalized = ''.join(c for c in unicodedata.normalize('NFKC', text) if unicodedata.category(c) != 'Cf')
    if len(text.encode()) > 16000 or SECRET.search(normalized) or re.search(r"(?i)\b(chain.of.thought|hidden.reasoning|raw.user.message)\b", normalized):
        raise ValueError("credential-bearing or oversized note rejected")
    return text


def bounded_engineering_value(value, depth=0):
    """Explicit inspectable notes, bounded JSON; never implicit model state."""
    if depth > 4:
        raise ValueError("engineering note nesting exceeds bound")
    if isinstance(value, dict):
        if len(value) > 32:
            raise ValueError("too many engineering fields")
        for key, child in value.items():
            identifier(key)
            if key.lower() in HIDDEN_FIELDS:
                raise ValueError("hidden reasoning/raw user input forbidden")
            bounded_engineering_value(child, depth+1)
    elif isinstance(value, list):
        if len(value) > 32:
            raise ValueError("too many engineering items")
        for child in value:
            bounded_engineering_value(child, depth+1)
    elif isinstance(value, str):
        if len(value) > 4000:
            raise ValueError("engineering string exceeds bound")
    elif value is None or type(value) is bool:
        return
    elif type(value) in (int,float):
        if abs(value) > 1e100 or not math.isfinite(value):
            raise ValueError("numeric value exceeds bound")
    else:
        raise ValueError("JSON engineering types required")


class CollectiveWorkspace:
    def __init__(self, path, *, clock=time.time, max_records=10000, max_attempts=3):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.principals = frozenset(registered_agent_ids())
        if len(self.principals) != 22 or "prime" not in self.principals:
            raise ValueError("canonical 21 agents plus PRIME required")
        if not 1 <= max_records <= 100000 or not 1 <= max_attempts <= 3:
            raise ValueError("invalid resource bound")
        self.max_records, self.max_attempts = max_records, max_attempts
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sketch(owner TEXT, entry TEXT, revision INTEGER,
              content TEXT, archived INTEGER NOT NULL, checkpoint INTEGER NOT NULL,
              created REAL NOT NULL, PRIMARY KEY(owner,entry,revision));
            CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, board TEXT NOT NULL,
              author TEXT NOT NULL, key TEXT NOT NULL, thread TEXT NOT NULL, content TEXT NOT NULL,
              digest TEXT NOT NULL, created REAL NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
              UNIQUE(author,board,key));
            CREATE TABLE IF NOT EXISTS subscriptions(principal TEXT,board TEXT,PRIMARY KEY(principal,board));
            CREATE TABLE IF NOT EXISTS deliveries(message TEXT,principal TEXT,acked REAL,
              PRIMARY KEY(message,principal),FOREIGN KEY(message) REFERENCES messages(id));
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,creator TEXT NOT NULL,
              assigned TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL,
              note TEXT NOT NULL,attempts INTEGER NOT NULL,lease_token TEXT,lease_until REAL,
              updated REAL NOT NULL,retry_at REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS task_events(task TEXT,revision INTEGER,principal TEXT NOT NULL,
              state TEXT NOT NULL,note TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(task,revision));
            CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,
              principal TEXT NOT NULL,operation TEXT NOT NULL,subject TEXT NOT NULL,created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS sketch_latest ON sketch(owner,entry,revision DESC);
            CREATE INDEX IF NOT EXISTS delivery_principal ON deliveries(principal,acked);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, factory=_Connection)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def principal(self, actor):
        if actor not in self.principals:
            raise PermissionError("unknown principal")
        return actor

    def private(self, actor, owner):
        self.principal(actor)
        if actor != owner:
            raise PermissionError("private pad belongs to another principal")

    def board(self, board):
        if board not in BOARDS:
            raise ValueError("unknown board")

    def delegation(self, actor, target):
        """Task coordination does not transfer execution authority."""
        self.principal(actor); self.principal(target)
        if actor != 'prime' and target != actor and target not in agent_record(actor).get('allowed_delegation_targets', []):
            raise PermissionError("registered delegation edge required")

    def capacity(self, db, table):
        # Hard ceilings fail visibly; no automatic evidence deletion.
        if db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] >= self.max_records:
            raise ValueError("retention capacity reached; explicit archival/export required")

    def log(self, db, actor, operation, subject):
        self.capacity(db, "audit")
        db.execute("INSERT INTO audit(principal,operation,subject,created) VALUES(?,?,?,?)",
                   (actor, operation, subject, self.clock()))

    def write_sketch(self, actor, owner, entry, note, *, expected_revision=0, checkpoint=False, archived=False):
        self.private(actor, owner)
        identifier(entry)
        content = structured_note(note)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("invalid revision")
        with self.transaction() as db:
            latest = db.execute("SELECT max(revision) FROM sketch WHERE owner=? AND entry=?", (owner, entry)).fetchone()[0] or 0
            if latest != expected_revision:
                raise Conflict("stale sketch revision")
            self.capacity(db, "sketch")
            db.execute("INSERT INTO sketch VALUES(?,?,?,?,?,?,?)",
                       (owner, entry, latest+1, content, int(bool(archived)), int(bool(checkpoint)), self.clock()))
            self.log(db, actor, "sketch.write", entry)
            return latest+1

    def read_sketch(self, actor, owner, entry, *, revision=None):
        self.private(actor, owner)
        identifier(entry)
        with self.connect() as db:
            row = db.execute("SELECT * FROM sketch WHERE owner=? AND entry=?" +
                (" AND revision=?" if revision is not None else " ORDER BY revision DESC LIMIT 1"),
                (owner, entry, revision) if revision is not None else (owner, entry)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["note"] = json.loads(result.pop("content"))
        return result

    def search_sketch(self, actor, owner, query="", *, limit=50, include_archived=False):
        self.private(actor, owner)
        if not isinstance(query, str) or len(query) > 200 or SECRET.search(query):
            raise ValueError("invalid search")
        with self.connect() as db:
            rows = db.execute("""SELECT s.entry,s.revision FROM sketch s WHERE s.owner=?
              AND s.revision=(SELECT max(x.revision) FROM sketch x WHERE x.owner=s.owner AND x.entry=s.entry)
              AND (? OR s.archived=0) AND instr(lower(s.content),lower(?))>0
              ORDER BY s.created DESC LIMIT ?""", (owner, bool(include_archived), query, max(1,min(int(limit),200)))).fetchall()
        return [self.read_sketch(actor, owner, row["entry"], revision=row["revision"]) for row in rows]

    def subscribe(self, actor, board):
        self.principal(actor); self.board(board)
        with self.transaction() as db:
            inserted = db.execute("INSERT OR IGNORE INTO subscriptions VALUES(?,?)", (actor, board)).rowcount
            if inserted:
                self.log(db, actor, "board.subscribe", board)
        return bool(inserted)

    def post(self, actor, board, key, note, *, thread="main"):
        self.principal(actor); self.board(board); identifier(key); identifier(thread)
        content = structured_note(note)
        digest = hashlib.sha256((thread+"\n"+content).encode()).hexdigest()
        with self.transaction() as db:
            existing = db.execute("SELECT * FROM messages WHERE author=? AND board=? AND key=?", (actor, board, key)).fetchone()
            if existing:
                if existing["digest"] != digest:
                    raise Conflict("idempotency key conflicts with original message")
                return existing["id"]
            self.capacity(db, "messages")
            message = uuid.uuid4().hex
            db.execute("INSERT INTO messages(id,board,author,key,thread,content,digest,created) VALUES(?,?,?,?,?,?,?,?)",
                       (message, board, actor, key, thread, content, digest, self.clock()))
            subscribers = [r[0] for r in db.execute("SELECT principal FROM subscriptions WHERE board=?", (board,))]
            if db.execute("SELECT count(*) FROM deliveries").fetchone()[0] + len(subscribers) > self.max_records*22:
                raise ValueError("delivery capacity reached")
            db.executemany("INSERT INTO deliveries(message,principal) VALUES(?,?)", [(message, p) for p in subscribers])
            self.log(db, actor, "board.post", message)
            return message

    def messages(self, actor, board, *, thread=None, limit=50, include_archived=False):
        self.principal(actor); self.board(board)
        if thread is not None: identifier(thread)
        with self.connect() as db:
            rows = db.execute("SELECT * FROM messages WHERE board=? AND (? OR archived=0) AND (? IS NULL OR thread=?) ORDER BY created,id LIMIT ?",
                              (board,bool(include_archived),thread,thread,max(1,min(int(limit),200)))).fetchall()
        return [dict(dict(row), content=json.loads(row["content"])) for row in rows]

    def pending(self, actor, *, limit=50):
        self.principal(actor)
        with self.connect() as db:
            rows = db.execute("SELECT m.* FROM deliveries d JOIN messages m ON m.id=d.message WHERE d.principal=? AND d.acked IS NULL ORDER BY m.created,m.id LIMIT ?",
                              (actor,max(1,min(int(limit),200)))).fetchall()
        return [dict(dict(row), content=json.loads(row["content"])) for row in rows]

    def acknowledge(self, actor, message):
        self.principal(actor); identifier(message)
        with self.transaction() as db:
            row = db.execute("SELECT acked FROM deliveries WHERE principal=? AND message=?", (actor,message)).fetchone()
            if row is None: raise PermissionError("delivery belongs to another principal")
            if row["acked"] is None:
                db.execute("UPDATE deliveries SET acked=? WHERE principal=? AND message=?", (self.clock(),actor,message))
                self.log(db,actor,"board.ack",message)

    def archive_message(self, actor, message):
        self.principal(actor); identifier(message)
        with self.transaction() as db:
            row = db.execute("SELECT author,archived FROM messages WHERE id=?", (message,)).fetchone()
            if row is None or row["author"] != actor: raise PermissionError("author-only archival")
            if not row["archived"]:
                db.execute("UPDATE messages SET archived=1 WHERE id=?", (message,))
                self.log(db,actor,"board.archive",message)

    def assign(self, actor, task, assigned, note):
        self.delegation(actor, assigned); identifier(task)
        content = structured_note(note)
        with self.transaction() as db:
            old = db.execute("SELECT creator,assigned,note FROM tasks WHERE id=?", (task,)).fetchone()
            if old:
                if tuple(old) != (actor,assigned,content): raise Conflict("task identity conflict")
                return task
            self.capacity(db,"tasks")
            self.capacity(db,"task_events")
            db.execute("INSERT INTO tasks VALUES(?,?,?,'READY',1,?,0,NULL,NULL,?,0)", (task,actor,assigned,content,self.clock()))
            db.execute("INSERT INTO task_events VALUES(?,1,?,'READY',?,?)", (task,actor,content,self.clock()))
            self.log(db,actor,"task.assign",task)
        return task

    def task(self, actor, task):
        self.principal(actor); identifier(task)
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
        if row is None: return None
        if actor not in (row["creator"],row["assigned"]): raise PermissionError("task participant required")
        result=dict(row); result["note"]=json.loads(result.pop("note")); return result

    def claim(self, actor, task, *, lease_seconds=60):
        self.principal(actor); identifier(task)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600: raise ValueError("invalid lease")
        with self.transaction() as db:
            row=db.execute("SELECT * FROM tasks WHERE id=?",(task,)).fetchone()
            if row is None or row["assigned"] != actor: raise PermissionError("assigned principal required")
            if row["state"] == "RUNNING" and row["lease_until"] > self.clock(): raise Conflict("lease active")
            if row["state"] not in ("READY","HANDOFF","RETRY","RUNNING"): raise Conflict("task not claimable")
            if row["retry_at"] > self.clock(): raise Conflict("retry backoff active")
            if row["attempts"] >= self.max_attempts:
                self.capacity(db,"task_events")
                db.execute("UPDATE tasks SET state='BLOCKED',lease_token=NULL,lease_until=NULL,revision=revision+1,updated=? WHERE id=?",(self.clock(),task))
                db.execute("INSERT INTO task_events VALUES(?,?,?,'BLOCKED',?,?)",(task,row['revision']+1,actor,row['note'],self.clock()))
                self.log(db,actor,"task.exhausted",task)
                return None
            token=uuid.uuid4().hex
            self.capacity(db,"task_events")
            db.execute("UPDATE tasks SET state='RUNNING',attempts=attempts+1,revision=revision+1,lease_token=?,lease_until=?,updated=?,retry_at=0 WHERE id=?",(token,self.clock()+lease_seconds,self.clock(),task))
            db.execute("INSERT INTO task_events VALUES(?,?,?,'RUNNING',?,?)", (task,row["revision"]+1,actor,row["note"],self.clock()))
            self.log(db,actor,"task.claim",task); return token

    def transition(self, actor, task, token, state, note, *, handoff_to=None):
        self.principal(actor); identifier(task)
        if state not in ("DONE","RETRY","BLOCKED","HANDOFF"): raise ValueError("invalid state")
        content=structured_note(note)
        if handoff_to is not None:
            self.principal(handoff_to)
            if state != "HANDOFF": raise ValueError("handoff state required")
        with self.transaction() as db:
            row=db.execute("SELECT * FROM tasks WHERE id=?",(task,)).fetchone()
            if row is None or row["assigned"]!=actor: raise PermissionError("assigned principal required")
            if row["state"]!="RUNNING" or row["lease_token"]!=token or row["lease_until"]<=self.clock(): raise Conflict("invalid/expired lease")
            if handoff_to is not None and handoff_to != actor:
                permitted = (actor == 'prime' or
                    handoff_to in agent_record(actor).get('allowed_delegation_targets', []) or
                    handoff_to in agent_record(actor).get('escalation_relationships', []) or
                    (handoff_to == 'prime' and row['creator'] == 'prime'))
                if not permitted:
                    raise PermissionError("registered handoff or escalation edge required")
                if db.execute("SELECT 1 FROM task_events WHERE task=? AND principal=? AND state='RUNNING' LIMIT 1",(task,handoff_to)).fetchone():
                    raise Conflict("circular handoff to prior running participant")
            if state=="RETRY" and row["attempts"]>=self.max_attempts: state="BLOCKED"
            self.capacity(db,"task_events")
            retry_at=self.clock()+min(3600,15*2**(row['attempts']-1)) if state=="RETRY" else 0
            db.execute("UPDATE tasks SET state=?,assigned=?,note=?,revision=revision+1,lease_token=NULL,lease_until=NULL,updated=?,retry_at=? WHERE id=?",(state,handoff_to or actor,content,self.clock(),retry_at,task))
            db.execute("INSERT INTO task_events VALUES(?,?,?,?,?,?)",(task,row["revision"]+1,actor,state,content,self.clock()))
            self.log(db,actor,"task."+state.lower(),task)

    def shutdown(self, actor):
        """Release only this worker's leases; no task silently completes."""
        self.principal(actor)
        with self.transaction() as db:
            rows=db.execute("SELECT * FROM tasks WHERE assigned=? AND state='RUNNING'",(actor,)).fetchall()
            tasks=[r['id'] for r in rows]
            for row in rows:
                task=row['id']; self.capacity(db,"task_events")
                db.execute("UPDATE tasks SET state='HANDOFF',revision=revision+1,lease_token=NULL,lease_until=NULL,updated=? WHERE id=?",(self.clock(),task))
                db.execute("INSERT INTO task_events VALUES(?,?,?,'HANDOFF',?,?)",(task,row['revision']+1,actor,row['note'],self.clock()))
                self.log(db,actor,"task.shutdown_handoff",task)
        return tasks

    def task_history(self, actor, task, *, limit=100):
        if self.task(actor,task) is None: return []
        with self.connect() as db:
            rows=db.execute("SELECT * FROM task_events WHERE task=? ORDER BY revision LIMIT ?",(task,max(1,min(int(limit),200)))).fetchall()
        return [dict(dict(r),note=json.loads(r['note'])) for r in rows]

    def audit(self, actor, *, limit=50):
        """Only this principal's metadata; note contents never enter audit."""
        self.principal(actor)
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM audit WHERE principal=? ORDER BY seq DESC LIMIT ?",(actor,max(1,min(int(limit),200))))]
