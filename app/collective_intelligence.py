"""Tenant-scoped collective knowledge, questioning, puzzles and gap workflows.

This is an advisory, local SQLite integration. It does not replace the canonical
registry, Stable Spine, authorization service, queue, or execution harness. Agent
content is untrusted data. Only fixed, authenticated service adapters can attest
runtime observations. No contributed record is an execution permission.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .agent_registry import REGISTRY_PATH, load_agent_registry, responsibility_owner

SCHEMA_VERSION = 1
KINDS = frozenset(
    "agents fabrics capabilities agent_capabilities fabric_capabilities dependencies policies evidence models "
    "health_snapshots execution_records knowledge_claims knowledge_contributions knowledge_relationships "
    "knowledge_reviews knowledge_challenges challenge_evidence challenge_resolutions puzzles puzzle_requirements "
    "puzzle_contributions gaps gap_assignments remediation_plans remediation_executions remediation_verifications "
    "lessons_learned registry_versions orchestrators".split()
)
ROLES = frozenset({"OWNER", "AGENT", "VERIFIER", "SYSTEM"})
SEVERITIES = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}", re.I),
    re.compile(r"\b(?:api[_-]?key|password|client[_-]?secret|access[_-]?token)\s*[:=]\s*[\"']?[^\s\"',}]{8,}", re.I),
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
SAFE_ADAPTERS = frozenset({"reindex_notebooks"})
OBSERVATION_ADAPTERS = frozenset({"queue_inference", "fabric_probe", "owner_mlp_reference"})
GAP_NEXT = {
    "DETECTED": {"TRIAGED"},
    "TRIAGED": {"ASSIGNED"},
    "ASSIGNED": {"PLANNED"},
    "PLANNED": {"REMEDIATING"},
    "REMEDIATING": {"VERIFYING"},
    "VERIFYING": {"CLOSED"},
    "REOPENED": {"TRIAGED"},
    "BLOCKED": {"TRIAGED"},
    "AWAITING_APPROVAL": {"TRIAGED"},
    "DEFERRED": {"TRIAGED"},
}
GAP_DISPOSITIONS = frozenset(
    {"BLOCKED", "AWAITING_APPROVAL", "DEFERRED", "ACCEPTED_RISK", "NOT_ACTIONABLE", "DUPLICATE"}
)
CHALLENGE_NEXT = {
    "QUESTIONED": {"INVESTIGATING"},
    "INVESTIGATING": {"EVIDENCE_GATHERING"},
    "EVIDENCE_GATHERING": {"REVIEWING"},
    "REVIEWING": {"RESOLVED"},
    "REOPENED": {"INVESTIGATING"},
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class CollectiveError(RuntimeError):
    """Safe, bounded error suitable for an authenticated API response."""

    code = "invalid"


class CollectiveDenied(CollectiveError):
    code = "denied"


class CollectiveNotFound(CollectiveError):
    code = "not_found"


class CollectiveConflict(CollectiveError):
    code = "conflict"


class CollectiveRateLimited(CollectiveError):
    code = "rate_limited"


@dataclass(frozen=True)
class CollectivePrincipal:
    tenant_id: str
    owner_id: str
    actor_id: str
    agent_id: str | None = None
    execution_id: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        for value in (self.tenant_id, self.owner_id, self.actor_id):
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise CollectiveDenied("invalid trusted principal")
        if not self.roles or not self.roles <= ROLES:
            raise CollectiveDenied("unsupported trusted principal role")
        if "AGENT" in self.roles:
            if self.roles != frozenset({"AGENT"}) or not self.execution_id:
                raise CollectiveDenied("agent requires a bounded authenticated execution")
            known = {agent["agent_id"] for agent in load_agent_registry()["agents"]}
            if self.agent_id not in known or not IDENTIFIER.fullmatch(self.execution_id):
                raise CollectiveDenied("unregistered agent or invalid execution")
            object.__setattr__(self, "actor_id", f"agent:{self.agent_id}:{self.execution_id}")
        elif self.agent_id is not None:
            raise CollectiveDenied("service and owner principals cannot impersonate agents")


class CollectiveStore:
    """Synchronous, bounded store. Instantiate with a server-owned path only.

    Entity views expose normalized identities and versioned JSON documents;
    foreign-key relations and immutable events preserve their provenance. This
    avoids 30 duplications of the same tenant/version/audit machinery while
    retaining independently queryable logical entities and typed relations.
    """

    def __init__(self, path: str | Path, *, clock: Any = time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=8)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=8000")
            with db:
                yield db
        finally:
            db.close()

    def _init_schema(self) -> None:
        with self._lock, self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise CollectiveConflict("registry schema is newer than this service")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS schema_migrations(
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS registry_records(
                    tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL, id TEXT NOT NULL,
                    kind TEXT NOT NULL, state TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
                    creator TEXT NOT NULL, creator_agent TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, body_json TEXT NOT NULL CHECK(json_valid(body_json)),
                    PRIMARY KEY(tenant_id,owner_id,id));
                CREATE INDEX IF NOT EXISTS records_kind ON registry_records(tenant_id,owner_id,kind,state,updated_at);
                CREATE TABLE IF NOT EXISTS registry_relations(
                    tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                    source_id TEXT NOT NULL, target_id TEXT NOT NULL, relation TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(tenant_id,owner_id,source_id,target_id,relation),
                    FOREIGN KEY(tenant_id,owner_id,source_id) REFERENCES registry_records(tenant_id,owner_id,id),
                    FOREIGN KEY(tenant_id,owner_id,target_id) REFERENCES registry_records(tenant_id,owner_id,id));
                CREATE INDEX IF NOT EXISTS relations_target ON registry_relations(tenant_id,owner_id,target_id,relation);
                CREATE TABLE IF NOT EXISTS audit_events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE, actor_id TEXT NOT NULL, agent_id TEXT, execution_id TEXT,
                    operation TEXT NOT NULL, subject_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
                    occurred_epoch REAL NOT NULL, reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
                    body_json TEXT NOT NULL CHECK(json_valid(body_json)), previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS audit_scope ON audit_events(tenant_id,owner_id,sequence);
                CREATE INDEX IF NOT EXISTS audit_rate ON audit_events(tenant_id,owner_id,actor_id,occurred_epoch);
                CREATE TABLE IF NOT EXISTS command_receipts(
                    tenant_id TEXT NOT NULL,owner_id TEXT NOT NULL,actor_id TEXT NOT NULL,key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,response_json TEXT NOT NULL CHECK(json_valid(response_json)),
                    PRIMARY KEY(tenant_id,owner_id,actor_id,key));
                CREATE TABLE IF NOT EXISTS deduplication_keys(
                    tenant_id TEXT NOT NULL,owner_id TEXT NOT NULL,kind TEXT NOT NULL,fingerprint TEXT NOT NULL,
                    subject_id TEXT NOT NULL,PRIMARY KEY(tenant_id,owner_id,kind,fingerprint),
                    FOREIGN KEY(tenant_id,owner_id,subject_id) REFERENCES registry_records(tenant_id,owner_id,id));
                CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
                    BEGIN SELECT RAISE(ABORT,'audit events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
                    BEGIN SELECT RAISE(ABORT,'audit events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS relations_no_update BEFORE UPDATE ON registry_relations
                    BEGIN SELECT RAISE(ABORT,'provenance links are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS relations_no_delete BEFORE DELETE ON registry_relations
                    BEGIN SELECT RAISE(ABORT,'provenance links are immutable'); END;
            """)
            for kind in sorted(KINDS):
                db.execute(f"CREATE VIEW IF NOT EXISTS {kind} AS SELECT * FROM registry_records WHERE kind='{kind}'")
            db.execute(
                "INSERT OR IGNORE INTO schema_migrations VALUES(1,?,?)",
                (self._now(), "Scoped entity/relationship registry and immutable hash-chained events"),
            )
            db.execute("PRAGMA user_version=1")

    def _now(self) -> str:
        return datetime.fromtimestamp(self._clock(), timezone.utc).isoformat()

    @staticmethod
    def _scope(p: CollectivePrincipal) -> tuple[str, str]:
        if not isinstance(p, CollectivePrincipal):
            raise CollectiveDenied("authenticated principal required")
        return p.tenant_id, p.owner_id

    @staticmethod
    def _role(p: CollectivePrincipal, *roles: str) -> None:
        if not p.roles.intersection(roles):
            raise CollectiveDenied("operation is not authorized for this principal")

    @staticmethod
    def _text(value: Any, field_name: str, *, max_length: int = 2000) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > max_length:
            raise CollectiveError(f"{field_name} must be nonempty bounded text")
        return value.strip()

    @staticmethod
    def _fields(data: Mapping[str, Any], allowed: str, required: str = "") -> None:
        if set(data) - set(allowed.split()):
            raise CollectiveError("unsupported payload fields")
        if set(required.split()) - set(data):
            raise CollectiveError("required payload fields are missing")

    def _safe_payload(self, value: Any) -> None:
        try:
            text = canonical_json(value)
        except (ValueError, TypeError, RecursionError) as exc:
            raise CollectiveError("payload must be finite JSON data") from exc
        if len(text.encode("utf-8")) > 32_768:
            raise CollectiveError("payload exceeds 32 KiB")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            raise CollectiveDenied("credentials and private keys cannot be contributed")

        def inspect(item: Any, depth: int = 0) -> None:
            if depth > 12:
                raise CollectiveError("payload nesting exceeds budget")
            if isinstance(item, dict):
                if len(item) > 100:
                    raise CollectiveError("payload field budget exceeded")
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise CollectiveError("JSON object keys must be text")
                    if key.casefold().replace("-", "_") in {
                        "password",
                        "secret",
                        "client_secret",
                        "api_key",
                        "access_token",
                        "refresh_token",
                        "authorization",
                        "private_key",
                    } and child not in (None, "", "[REDACTED]"):
                        raise CollectiveDenied("credentials and private keys cannot be contributed")
                    inspect(child, depth + 1)
            elif isinstance(item, list):
                if len(item) > 100:
                    raise CollectiveError("payload list budget exceeded")
                for child in item:
                    inspect(child, depth + 1)

        inspect(value)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def _get(self, db: sqlite3.Connection, p: CollectivePrincipal, object_id: str, kind: str | None = None) -> dict:
        row = db.execute(
            "SELECT * FROM registry_records WHERE tenant_id=? AND owner_id=? AND id=?",
            (*self._scope(p), object_id),
        ).fetchone()
        if row is None or (kind is not None and row["kind"] != kind):
            raise CollectiveNotFound("record is unavailable in this scope")
        result = dict(row)
        result["data"] = json.loads(result.pop("body_json"))
        return result

    def _create(
        self,
        db: sqlite3.Connection,
        p: CollectivePrincipal,
        kind: str,
        data: dict,
        *,
        state: str = "RECORDED",
        object_id: str | None = None,
    ) -> dict:
        if kind not in KINDS:
            raise CollectiveError("unknown registry kind")
        object_id = object_id or f"{kind}:{uuid.uuid4().hex}"
        now = self._now()
        db.execute(
            "INSERT INTO registry_records VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (*self._scope(p), object_id, kind, state, 1, p.actor_id, p.agent_id, now, now, canonical_json(data)),
        )
        item = self._get(db, p, object_id)
        self._audit(db, p, "record.create", item, reason="Transactional versioned entity creation")
        return item

    def _update(
        self,
        db: sqlite3.Connection,
        p: CollectivePrincipal,
        item: dict,
        data: dict,
        *,
        state: str | None = None,
        expected_version: Any,
    ) -> dict:
        if type(expected_version) is not int or expected_version != item["version"]:
            raise CollectiveConflict("stale record version; refresh before retrying")
        cursor = db.execute(
            "UPDATE registry_records SET body_json=?,state=?,version=version+1,updated_at=? "
            "WHERE tenant_id=? AND owner_id=? AND id=? AND version=?",
            (canonical_json(data), state or item["state"], self._now(), *self._scope(p), item["id"], expected_version),
        )
        if cursor.rowcount != 1:
            raise CollectiveConflict("concurrent update")
        result = self._get(db, p, item["id"])
        self._audit(db, p, "record.update", result, reason="Transactional versioned entity update")
        return result

    def _link(self, db: sqlite3.Connection, p: CollectivePrincipal, source: str, target: str, relation: str) -> None:
        self._get(db, p, source)
        self._get(db, p, target)
        db.execute(
            "INSERT OR IGNORE INTO registry_relations VALUES(?,?,?,?,?,?)",
            (*self._scope(p), source, target, relation, self._now()),
        )

    def _audit(
        self,
        db: sqlite3.Connection,
        p: CollectivePrincipal,
        operation: str,
        subject: dict,
        *,
        reason: str,
        evidence: list[str] | None = None,
    ) -> None:
        prior = db.execute(
            "SELECT event_hash FROM audit_events WHERE tenant_id=? AND owner_id=? ORDER BY sequence DESC LIMIT 1",
            self._scope(p),
        ).fetchone()
        body = {
            "event_id": uuid.uuid4().hex,
            "tenant_id": p.tenant_id,
            "owner_id": p.owner_id,
            "actor_id": p.actor_id,
            "agent_id": p.agent_id,
            "execution_id": p.execution_id,
            "operation": operation,
            "subject_id": subject["id"],
            "occurred_at": self._now(),
            "occurred_epoch": self._clock(),
            "reason": reason,
            "evidence": evidence or [],
            "record": subject,
            "previous_hash": prior[0] if prior else "0" * 64,
        }
        db.execute(
            "INSERT INTO audit_events(tenant_id,owner_id,event_id,actor_id,agent_id,execution_id,operation,subject_id,"
            "occurred_at,occurred_epoch,reason,evidence_json,body_json,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                p.tenant_id,
                p.owner_id,
                body["event_id"],
                p.actor_id,
                p.agent_id,
                p.execution_id,
                operation,
                subject["id"],
                body["occurred_at"],
                body["occurred_epoch"],
                reason,
                canonical_json(body["evidence"]),
                canonical_json(body),
                body["previous_hash"],
                digest(body),
            ),
        )

    def _evidence(
        self, db: sqlite3.Connection, p: CollectivePrincipal, ids: Any, *, required: bool = True
    ) -> list[dict]:
        if not isinstance(ids, list) or len(ids) > 20 or any(not isinstance(x, str) for x in ids):
            raise CollectiveError("evidence_ids must be a bounded list of scoped record identifiers")
        if required and not ids:
            raise CollectiveError("supporting evidence is required")
        return [self._get(db, p, key, "evidence") for key in dict.fromkeys(ids)]

    def _agent(self, db: sqlite3.Connection, p: CollectivePrincipal, agent_id: Any) -> str:
        if not isinstance(agent_id, str):
            raise CollectiveError("canonical accountable agent required")
        self._get(db, p, f"agent:{agent_id}", "agents")
        return agent_id

    def provision(self, p: CollectivePrincipal) -> dict:
        """Mirror the validated canonical source. Never derives runtime health or permission."""
        self._role(p, "OWNER", "SYSTEM")
        registry = load_agent_registry()
        raw = REGISTRY_PATH.read_bytes()
        source_sha = hashlib.sha256(raw).hexdigest()
        with self._transaction() as db:
            board_policy_id = "policy:authorized-board-participation"
            if not db.execute(
                "SELECT 1 FROM registry_records WHERE tenant_id=? AND owner_id=? AND id=?",
                (*self._scope(p), board_policy_id),
            ).fetchone():
                self._create(
                    db,
                    p,
                    "policies",
                    {
                        "name": "Default authorized board participation for all 21 canonical agents",
                        "default_enrolled": True,
                        "required_behaviors": [
                            "READ_AUTHORIZED_RECORDS",
                            "PUBLISH_MEANINGFUL_OUTCOMES",
                            "ACKNOWLEDGE_APPLICABLE_INSTRUCTIONS",
                            "TRACK_ACTIONABLE_GAPS",
                        ],
                        "boards": [
                            "SHARED_COLLECTIVE_BOARD",
                            "OWN_PRIVATE_NOTEBOOK",
                            "AUTHORIZED_PROJECT_BOARDS",
                            "REVIEWED_REPOSITORY_RELAY",
                        ],
                        "access_basis": "EXISTING_AUTHENTICATION_AND_SCOPE",
                        "board_content_is_untrusted": True,
                        "contribution_grants_authority": False,
                        "continuous_model_execution_required": False,
                        "source": "Owner default participation directive 2026-10-23",
                    },
                    object_id=board_policy_id,
                    state="DEFAULT_PARTICIPATION",
                )
            existing = db.execute(
                "SELECT id FROM registry_records WHERE tenant_id=? AND owner_id=? AND id='canonical-registry'",
                self._scope(p),
            ).fetchone()
            if existing:
                current = self._get(db, p, "canonical-registry")
                if current["data"]["source_sha256"] != source_sha:
                    raise CollectiveConflict("canonical source changed; explicit mirror migration is required")
                return {"agents": len(registry["agents"]), "source_sha256": source_sha, "replayed": True}
            root_id = registry["orchestrator"]["id"]
            root = self._create(
                db,
                p,
                "orchestrators",
                {"canonical_id": root_id, "authority": "SOURCE_DEFINITION_ONLY"},
                state="SOURCE_MIRROR",
                object_id=f"orchestrator:{root_id}",
            )
            self._audit(db, p, "registry.seed", root, reason="Validated canonical orchestrator source")
            for agent in registry["agents"]:
                body = {
                    "canonical_id": agent["agent_id"],
                    "name": agent["name"],
                    "purpose": agent["purpose"],
                    "capability_requirements": agent["capability_requirements"],
                    "source": "config/agent_registry.json",
                    "source_sha256": source_sha,
                    "registered": True,
                    "enrolled": True,
                    "source_model": agent["model"],
                    "authority": agent["authority"],
                    "qualification": "UNVERIFIED",
                    "runtime_health": "UNKNOWN",
                    "contribution_ready": True,
                    "questioning_ready": True,
                    "gap_workflow_ready": True,
                    "readiness_basis": "authenticated queue adapter required; no runtime success implied",
                }
                item = self._create(
                    db, p, "agents", body, state="SOURCE_MIRROR", object_id=f"agent:{agent['agent_id']}"
                )
                self._audit(db, p, "registry.seed", item, reason="Validated canonical identity; no privilege transfer")
            for agent in registry["agents"]:
                for capability in agent["capability_requirements"]:
                    capability_id = f"capability:{capability}"
                    self._create(
                        db,
                        p,
                        "capabilities",
                        {"canonical_id": capability, "source_sha256": source_sha},
                        state="SOURCE_MIRROR",
                        object_id=capability_id,
                    )
                    mapping = self._create(
                        db, p, "agent_capabilities", {"agent_id": agent["agent_id"], "capability": capability}
                    )
                    self._link(db, p, mapping["id"], item_id := f"agent:{agent['agent_id']}", "agent")
                    self._link(db, p, mapping["id"], capability_id, "capability")
                    self._audit(db, p, "registry.seed", mapping, reason="Canonical capability mapping")
                parent_id = (
                    f"orchestrator:{root_id}" if agent["reports_to"] == root_id else f"agent:{agent['reports_to']}"
                )
                dependency = self._create(
                    db,
                    p,
                    "dependencies",
                    {"source": item_id, "target": parent_id, "relation": "reports_to", "execution_dependency": False},
                )
                self._link(db, p, dependency["id"], item_id, "source")
                self._link(db, p, dependency["id"], parent_id, "target")
            policy = self._create(
                db,
                p,
                "policies",
                {
                    "name": "Collective knowledge carries no execution authority",
                    "shadow_routing_only": True,
                    "restricted_changes_require_approval": True,
                    "gods_eye_read_only": True,
                    "mandatory_paid_aws_dependency": False,
                    "source": "Owner consolidated directive 2026-10-23",
                },
                object_id="policy:collective-boundary",
                state="ENFORCED_BY_SERVICE",
            )
            self._audit(db, p, "registry.seed", policy, reason="Knowledge and authority boundaries")
            version = self._create(
                db,
                p,
                "registry_versions",
                {
                    "source": "config/agent_registry.json",
                    "source_sha256": source_sha,
                    "schema_version": SCHEMA_VERSION,
                    "canonical_registry_version": registry["registry_version"],
                },
                state="SOURCE_MIRROR",
                object_id="canonical-registry",
            )
            self._audit(db, p, "registry.provision", version, reason="Transactional canonical registry mirror")
        return {"agents": len(registry["agents"]), "source_sha256": source_sha, "replayed": False}

    def query(
        self, p: CollectivePrincipal, kind: str, id: str | None = None, filters: Mapping[str, Any] | None = None
    ) -> dict:
        self._scope(p)
        if kind not in KINDS:
            raise CollectiveError("unknown registry kind")
        filters = dict(filters or {})
        self._fields(filters, "state limit offset")
        limit, offset = filters.get("limit", 100), filters.get("offset", 0)
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or not 0 <= offset <= 10000:
            raise CollectiveError("invalid query bounds")
        with self.connect() as db:
            if id is not None:
                return self._get(db, p, id, kind)
            where = "tenant_id=? AND owner_id=? AND kind=?"
            params: list[Any] = [*self._scope(p), kind]
            if filters.get("state") is not None:
                where += " AND state=?"
                params.append(self._text(filters["state"], "state", max_length=48))
            rows = db.execute(
                f"SELECT id FROM registry_records WHERE {where} ORDER BY created_at,id LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
            count = db.execute(f"SELECT count(*) FROM registry_records WHERE {where}", params).fetchone()[0]
            return {
                "items": [self._get(db, p, row[0]) for row in rows],
                "total": count,
                "limit": limit,
                "offset": offset,
                "authority": "READ_ONLY_ADVISORY",
                "api_version": "1.0",
            }

    def command(self, p: CollectivePrincipal, operation: str, payload: Mapping[str, Any], idempotency_key: str) -> dict:
        self._scope(p)
        if not isinstance(payload, Mapping) or not isinstance(operation, str):
            raise CollectiveError("command requires operation and object payload")
        if (
            not isinstance(idempotency_key, str)
            or not 8 <= len(idempotency_key) <= 128
            or not IDENTIFIER.fullmatch(idempotency_key)
        ):
            raise CollectiveError("bounded idempotency_key required")
        data = dict(payload)
        self._safe_payload(data)
        handler = {
            "evidence.record": self._record_evidence,
            "claim.contribute": self._contribute,
            "claim.review": self._review_claim,
            "claim.correct": self._correct_claim,
            "knowledge.link": self._knowledge_link,
            "challenge.open": self._open_challenge,
            "challenge.transition": self._transition_challenge,
            "challenge.resolve": self._resolve_challenge,
            "challenge.reopen": self._reopen_challenge,
            "gap.detect": self._detect_gap,
            "gap.transition": self._transition_gap,
            "gap.plan": self._plan_gap,
            "gap.execute": self._execute_gap,
            "gap.verify": self._verify_gap,
            "gap.reopen": self._reopen_gap,
            "puzzle.create": self._create_puzzle,
            "puzzle.contribute": self._contribute_puzzle,
            "puzzle.complete": self._complete_puzzle,
            "puzzle.reopen": self._reopen_puzzle,
            "registry.observe": self._observe,
            "lesson.record": self._lesson,
        }.get(operation)
        if handler is None:
            raise CollectiveError("unsupported operation")
        request_sha = digest({"operation": operation, "payload": data})
        with self._transaction() as db:
            receipt = db.execute(
                "SELECT request_sha256,response_json FROM command_receipts WHERE tenant_id=? AND owner_id=? AND actor_id=? AND key=?",
                (*self._scope(p), p.actor_id, idempotency_key),
            ).fetchone()
            if receipt:
                if receipt[0] != request_sha:
                    raise CollectiveConflict("idempotency key reused with different content")
                result = json.loads(receipt[1])
                result["replayed"] = True
                return result
            recent = db.execute(
                "SELECT count(*) FROM audit_events WHERE tenant_id=? AND owner_id=? AND ((agent_id IS NOT NULL AND agent_id=?) OR (agent_id IS NULL AND actor_id=?)) AND occurred_epoch>? AND operation NOT LIKE 'record.%' AND operation NOT LIKE 'registry.%'",
                (*self._scope(p), p.agent_id, p.actor_id, self._clock() - 60),
            ).fetchone()[0]
            if recent >= 120:
                raise CollectiveRateLimited("bounded contribution rate exceeded; retry after cooldown")
            count = db.execute(
                "SELECT count(*) FROM registry_records WHERE tenant_id=? AND owner_id=?", self._scope(p)
            ).fetchone()[0]
            if count >= 10000:
                raise CollectiveRateLimited("registry record budget reached; owner retention review required")
            result = handler(db, p, data)
            result = {"api_version": "1.0", "record": result, "replayed": False, "authority": "NO_EXECUTION_PERMISSION"}
            db.execute(
                "INSERT INTO command_receipts VALUES(?,?,?,?,?,?)",
                (*self._scope(p), p.actor_id, idempotency_key, request_sha, canonical_json(result)),
            )
            return result

    def _record_evidence(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(data, "content source kind environment subject_id execution_id", "content source kind environment")
        kind = data["kind"]
        if kind not in {"OBSERVATION", "EXECUTION", "VERIFICATION", "SOURCE"}:
            raise CollectiveError("unsupported evidence kind")
        self._text(data["source"], "source", max_length=1000)
        self._text(data["environment"], "environment", max_length=200)
        if not isinstance(data["content"], dict):
            raise CollectiveError("evidence content must be an inspectable JSON object")
        attested = kind in {"EXECUTION", "VERIFICATION"}
        if kind == "EXECUTION":
            self._role(p, "SYSTEM")
        elif kind == "VERIFICATION":
            self._role(p, "VERIFIER")
        content = data["content"]
        if kind in {"EXECUTION", "VERIFICATION"}:
            required = {"plan_id", "execution_id", "candidate_revision"}
            if not required <= set(content):
                raise CollectiveError("trusted runtime receipt lacks binding fields")
            for key in required:
                self._text(content[key], key, max_length=160)
        if kind == "EXECUTION":
            if content.get("adapter") not in SAFE_ADAPTERS | OBSERVATION_ADAPTERS or content.get("outcome") not in {
                "SUCCEEDED",
                "FAILED",
            }:
                raise CollectiveDenied(
                    "only fixed runtime observation or low-risk repair adapter receipts are supported"
                )
            if not content.get("scope"):
                raise CollectiveError("execution receipt requires the actual affected scope")
            if content.get("adapter") == "queue_inference":
                self._agent(db, p, content.get("agent_id"))
                if not re.fullmatch(r"[0-9a-f]{64}", str(content.get("result_sha256", ""))):
                    raise CollectiveError("inference receipt requires the independently observed result digest")
        if kind == "VERIFICATION":
            if not re.fullmatch(r"[0-9a-f]{64}", str(content.get("execution_sha256", ""))):
                raise CollectiveError("verification requires exact execution receipt digest")
            checks = content.get("checks")
            if not isinstance(checks, dict) or set(checks) != {"outcome", "regression", "security"}:
                raise CollectiveError("verification requires outcome, regression and security observations")
            if any(type(value) is not bool for value in checks.values()):
                raise CollectiveError("verification checks must be actual boolean observations")
        if data.get("subject_id"):
            self._get(db, p, data["subject_id"])
        body = dict(data)
        body.update(
            {
                "sha256": digest(content),
                "attested": attested,
                "attested_by": p.actor_id if attested else None,
                "trusted_service_role": sorted(p.roles) if attested else [],
                "agent_execution_id": p.execution_id,
                "observed_epoch": self._clock(),
                "untrusted_content": not attested,
            }
        )
        item = self._create(db, p, "evidence", body, state="ATTESTED" if attested else "UNVERIFIED")
        if data.get("subject_id"):
            self._link(db, p, item["id"], data["subject_id"], "subject")
        self._audit(
            db, p, "evidence.record", item, reason="Content-addressed provenance; data does not confer authority"
        )
        return item

    def _contribute(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._role(p, "OWNER", "AGENT", "SYSTEM")
        self._fields(data, "title statement classification evidence_ids subject_id", "title statement evidence_ids")
        title = self._text(data["title"], "title", max_length=200)
        statement = self._text(data["statement"], "statement", max_length=6000)
        classification = data.get("classification", "HYPOTHESIS")
        if classification not in {"HYPOTHESIS", "OBSERVATION", "EVIDENCE_BACKED_CLAIM"}:
            raise CollectiveDenied("contributions cannot self-declare verified facts")
        evidence = self._evidence(db, p, data["evidence_ids"])
        if data.get("subject_id"):
            self._get(db, p, data["subject_id"])
        item = self._create(
            db,
            p,
            "knowledge_claims",
            {
                "title": title,
                "statement": statement,
                "classification": classification,
                "evidence_ids": data["evidence_ids"],
                "subject_id": data.get("subject_id"),
                "environment": evidence[0]["data"]["environment"]
                if len({ev["data"]["environment"] for ev in evidence}) == 1
                else "MIXED_EVIDENCE_ENVIRONMENTS",
                "source_execution_id": p.execution_id,
                "revision": 1,
            },
            state=classification,
        )
        contribution = self._create(
            db,
            p,
            "knowledge_contributions",
            {
                "claim_id": item["id"],
                "agent_id": p.agent_id,
                "execution_id": p.execution_id,
                "evidence_ids": data["evidence_ids"],
            },
        )
        self._link(db, p, contribution["id"], item["id"], "contributes")
        for ev in evidence:
            self._link(db, p, item["id"], ev["id"], "supported_by")
        self._audit(
            db, p, "claim.contribute", item, reason="Attributed untrusted contribution", evidence=data["evidence_ids"]
        )
        self._audit(db, p, "contribution.record", contribution, reason="Authenticated execution attribution")
        return item

    def _independent_evidence(
        self,
        db: sqlite3.Connection,
        p: CollectivePrincipal,
        ids: Any,
        subject: dict,
        *,
        verification_only: bool = False,
    ) -> list[dict]:
        evidence = self._evidence(db, p, ids)
        for item in evidence:
            body = item["data"]
            if not body.get("attested") or item["creator"] == subject["creator"]:
                raise CollectiveDenied("independently attested runtime evidence is required")
            if body.get("subject_id") != subject["id"]:
                raise CollectiveDenied("evidence is not bound to this subject")
            if verification_only and body.get("kind") != "VERIFICATION":
                raise CollectiveDenied("independent verification receipt required")
        return evidence

    def _review_claim(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._role(p, "VERIFIER")
        self._fields(
            data, "id expected_version decision reason evidence_ids", "id expected_version decision reason evidence_ids"
        )
        item = self._get(db, p, data["id"], "knowledge_claims")
        if data["decision"] not in {"VERIFIED_FACT", "DISPUTED", "REJECTED"}:
            raise CollectiveError("unsupported independent review decision")
        self._text(data["reason"], "reason")
        evidence = self._independent_evidence(db, p, data["evidence_ids"], item)
        if data["decision"] == "VERIFIED_FACT" and not any(
            e["data"]["kind"] == "VERIFICATION"
            and e["data"]["content"].get("target_id") == item["id"]
            and e["data"]["content"].get("target_version") == item["version"]
            and e["data"]["content"].get("statement_sha256") == digest(item["data"]["statement"])
            and e["data"]["environment"] == item["data"]["environment"]
            and all(
                e["data"]["content"].get("checks", {}).get(key) is True for key in ("outcome", "regression", "security")
            )
            for e in evidence
        ):
            raise CollectiveDenied("verified fact requires successful independent verification")
        body = {**item["data"], "classification": data["decision"], "review_evidence_ids": data["evidence_ids"]}
        result = self._update(db, p, item, body, state=data["decision"], expected_version=data["expected_version"])
        review = self._create(
            db,
            p,
            "knowledge_reviews",
            {
                "claim_id": item["id"],
                "decision": data["decision"],
                "reason": data["reason"],
                "evidence_ids": data["evidence_ids"],
                "reviewer": p.actor_id,
            },
        )
        self._link(db, p, review["id"], item["id"], "reviews")
        self._audit(db, p, "claim.review", result, reason=data["reason"], evidence=data["evidence_ids"])
        self._invalidate_dependents(db, p, result, data["evidence_ids"], reason="Supporting knowledge review changed")
        return result

    def _correct_claim(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._role(p, "OWNER")
        self._fields(
            data,
            "id expected_version challenge_id statement reason evidence_ids",
            "id expected_version challenge_id statement reason evidence_ids",
        )
        item = self._get(db, p, data["id"], "knowledge_claims")
        challenge = self._get(db, p, data["challenge_id"], "knowledge_challenges")
        if challenge["data"]["target_id"] != item["id"] or challenge["state"] != "REVIEWING":
            raise CollectiveConflict("correction requires a reviewing challenge for the same claim")
        evidence = self._independent_evidence(db, p, data["evidence_ids"], item)
        statement = self._text(data["statement"], "statement", max_length=6000)
        if not any(
            e["data"]["kind"] == "VERIFICATION"
            and e["data"]["content"].get("target_id") == item["id"]
            and e["data"]["content"].get("target_version") == item["version"]
            and e["data"]["content"].get("proposed_statement_sha256") == digest(statement)
            and e["data"]["environment"] == item["data"]["environment"]
            and all(value is True for value in e["data"]["content"]["checks"].values())
            for e in evidence
        ):
            raise CollectiveDenied("correction needs independently verified supporting evidence")
        self._text(data["reason"], "reason")
        body = {
            **item["data"],
            "statement": statement,
            "classification": "EVIDENCE_BACKED_CLAIM",
            "revision": item["data"].get("revision", 1) + 1,
            "prior_statement_sha256": digest(item["data"]["statement"]),
            "correction_challenge_id": challenge["id"],
            "correction_evidence_ids": data["evidence_ids"],
            "owner_approved_by": p.actor_id,
        }
        result = self._update(
            db, p, item, body, state="EVIDENCE_BACKED_CLAIM", expected_version=data["expected_version"]
        )
        self._audit(db, p, "claim.correct", result, reason=data["reason"], evidence=data["evidence_ids"])
        self._invalidate_dependents(
            db, p, result, data["evidence_ids"], reason="Claim corrected; dependent assembly requires revalidation"
        )
        return result

    def _knowledge_link(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(
            data, "source_id target_id relation evidence_ids reason", "source_id target_id relation evidence_ids reason"
        )
        source, target = self._get(db, p, data["source_id"]), self._get(db, p, data["target_id"])
        if data["relation"] not in {"SUPPORTS", "CONTRADICTS", "SUPERSEDES", "DEPENDS_ON", "RELATED_TO"}:
            raise CollectiveError("unsupported knowledge relationship")
        if source["id"] == target["id"]:
            raise CollectiveError("self-referential knowledge loops are not allowed")
        self._text(data["reason"], "reason")
        self._evidence(db, p, data["evidence_ids"])
        item = self._create(
            db,
            p,
            "knowledge_relationships",
            data,
            state="DISPUTED" if data["relation"] == "CONTRADICTS" else "UNVERIFIED",
        )
        self._link(db, p, item["id"], source["id"], "source")
        self._link(db, p, item["id"], target["id"], "target")
        self._audit(db, p, "knowledge.link", item, reason=data["reason"], evidence=data["evidence_ids"])
        if data["relation"] in {"CONTRADICTS", "SUPERSEDES"}:
            self._invalidate_dependents(
                db, p, source, data["evidence_ids"], reason="Conflicting or superseding knowledge supplied"
            )
            self._invalidate_dependents(
                db, p, target, data["evidence_ids"], reason="Conflicting or superseding knowledge supplied"
            )
        return item

    def _dedup(self, db: sqlite3.Connection, p: CollectivePrincipal, kind: str, fingerprint: str) -> dict | None:
        row = db.execute(
            "SELECT subject_id FROM deduplication_keys WHERE tenant_id=? AND owner_id=? AND kind=? AND fingerprint=?",
            (*self._scope(p), kind, fingerprint),
        ).fetchone()
        return self._get(db, p, row[0]) if row else None

    def _dedup_record(self, db: sqlite3.Connection, p: CollectivePrincipal, item: dict, fingerprint: str) -> None:
        db.execute(
            "INSERT INTO deduplication_keys VALUES(?,?,?,?,?)", (*self._scope(p), item["kind"], fingerprint, item["id"])
        )

    @staticmethod
    def _normalized(value: str) -> str:
        return " ".join(value.casefold().split())

    def _open_challenge(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._role(p, "OWNER", "AGENT", "SYSTEM")
        self._fields(
            data,
            "target_id question reason severity reviewer_agent_id evidence_ids actionable gap_title capability",
            "target_id question reason severity evidence_ids",
        )
        target = self._get(db, p, data["target_id"])
        question = self._text(data["question"], "question")
        reason = self._text(data["reason"], "reason")
        if data["severity"] not in SEVERITIES:
            raise CollectiveError("invalid severity")
        evidence = self._evidence(db, p, data["evidence_ids"])
        fingerprint = digest([target["id"], self._normalized(question)])
        duplicate = self._dedup(db, p, "knowledge_challenges", fingerprint)
        if duplicate:
            return {**duplicate, "deduplicated": True}
        recent = db.execute(
            "SELECT count(*) FROM audit_events WHERE tenant_id=? AND owner_id=? AND ((agent_id IS NOT NULL AND agent_id=?) OR (agent_id IS NULL AND actor_id=?)) AND operation='challenge.open' AND occurred_epoch>?",
            (*self._scope(p), p.agent_id, p.actor_id, self._clock() - 3600),
        ).fetchone()[0]
        if recent >= 12:
            raise CollectiveRateLimited(
                "challenge budget reached; meaningful new evidence may be attached after cooldown"
            )
        reviewer = self._agent(db, p, data.get("reviewer_agent_id") or responsibility_owner("responsibility.a27"))
        item = self._create(
            db,
            p,
            "knowledge_challenges",
            {
                "target_id": target["id"],
                "question": question,
                "reason": reason,
                "severity": data["severity"],
                "reviewer_agent_id": reviewer,
                "evidence_ids": [e["id"] for e in evidence],
                "evidence_digests": sorted({e["data"]["sha256"] for e in evidence}),
                "review_cycles": 1,
                "last_reopened_epoch": None,
                "outcome": None,
                "gap_id": None,
            },
            state="QUESTIONED",
        )
        self._link(db, p, item["id"], target["id"], "questions")
        self._dedup_record(db, p, item, fingerprint)
        for ev in evidence:
            row = self._create(
                db, p, "challenge_evidence", {"challenge_id": item["id"], "evidence_id": ev["id"], "stance": "QUESTION"}
            )
            self._link(db, p, row["id"], item["id"], "challenge")
            self._link(db, p, row["id"], ev["id"], "evidence")
        self._audit(db, p, "challenge.open", item, reason=reason, evidence=data["evidence_ids"])
        # A valid question immediately receives accountable investigation ownership.
        item = self._update(db, p, item, item["data"], state="INVESTIGATING", expected_version=item["version"])
        self._audit(
            db,
            p,
            "challenge.investigate",
            item,
            reason="Automatically assigned bounded investigation; no ungoverned execution",
        )
        if data.get("actionable") is True:
            gap = self._detect_gap(
                db,
                p,
                {
                    "title": data.get("gap_title", question[:200]),
                    "description": reason,
                    "owner_agent_id": reviewer,
                    "severity": data["severity"],
                    "environment": "INVESTIGATION_REQUIRED",
                    "evidence_ids": data["evidence_ids"],
                    "capability": data.get("capability"),
                },
            )
            item = self._update(db, p, item, {**item["data"], "gap_id": gap["id"]}, expected_version=item["version"])
            self._link(db, p, item["id"], gap["id"], "identified_gap")
            self._audit(
                db,
                p,
                "challenge.gap_link",
                item,
                reason="Actionable challenge entered owned gap workflow",
                evidence=data["evidence_ids"],
            )
        return item

    def _transition_challenge(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(
            data, "id expected_version state reason evidence_ids", "id expected_version state reason evidence_ids"
        )
        item = self._get(db, p, data["id"], "knowledge_challenges")
        self._reviewer(p, item)
        if data["state"] not in CHALLENGE_NEXT.get(item["state"], set()) or data["state"] == "RESOLVED":
            raise CollectiveConflict("invalid challenge transition; resolution requires evidence review")
        self._text(data["reason"], "reason")
        evidence = self._evidence(db, p, data["evidence_ids"])
        body = {
            **item["data"],
            "evidence_ids": list(dict.fromkeys(item["data"]["evidence_ids"] + data["evidence_ids"])),
            "evidence_digests": sorted(set(item["data"]["evidence_digests"]) | {e["data"]["sha256"] for e in evidence}),
        }
        result = self._update(db, p, item, body, state=data["state"], expected_version=data["expected_version"])
        self._audit(db, p, "challenge.transition", result, reason=data["reason"], evidence=data["evidence_ids"])
        return result

    @staticmethod
    def _reviewer(p: CollectivePrincipal, item: dict) -> None:
        if p.roles.intersection({"OWNER", "SYSTEM", "VERIFIER"}):
            return
        if p.agent_id != item["data"]["reviewer_agent_id"]:
            raise CollectiveDenied("only the assigned investigator can advance this challenge")

    def _resolve_challenge(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(
            data, "id expected_version outcome reason evidence_ids", "id expected_version outcome reason evidence_ids"
        )
        item = self._get(db, p, data["id"], "knowledge_challenges")
        self._reviewer(p, item)
        if item["state"] != "REVIEWING":
            raise CollectiveConflict("challenge must reach evidence review before resolution")
        outcome = data["outcome"]
        if outcome not in {"CONFIRMED", "CORRECTED", "SUPERSEDED", "REJECTED", "INCONCLUSIVE", "AWAITING_APPROVAL"}:
            raise CollectiveError("unsupported challenge outcome")
        self._text(data["reason"], "reason")
        evidence = self._evidence(db, p, data["evidence_ids"])
        if outcome in {"CONFIRMED", "CORRECTED", "SUPERSEDED", "REJECTED"}:
            self._role(p, "OWNER", "VERIFIER")
            target = self._get(db, p, item["data"]["target_id"])
            if not any(
                e["data"].get("attested")
                and e["data"]["kind"] == "VERIFICATION"
                and e["creator"] != item["creator"]
                and e["data"].get("subject_id") in {item["id"], target["id"]}
                and e["data"]["content"].get("target_id") == target["id"]
                and e["data"]["content"].get("target_version") == target["version"]
                and e["data"]["content"].get("challenge_outcome") == outcome
                and (not target["data"].get("environment") or e["data"]["environment"] == target["data"]["environment"])
                and all(value is True for value in e["data"]["content"]["checks"].values())
                for e in evidence
            ):
                raise CollectiveDenied(
                    "conclusive resolution requires independent verification bound to this target, current version and outcome"
                )
        if outcome == "CORRECTED":
            target = self._get(db, p, item["data"]["target_id"])
            if target["kind"] != "knowledge_claims" or target["data"].get("correction_challenge_id") != item["id"]:
                raise CollectiveConflict("no owner-approved correction was applied for this challenge")
        state = "RESOLVED" if outcome not in {"INCONCLUSIVE", "AWAITING_APPROVAL"} else "REVIEWING"
        result = self._update(
            db,
            p,
            item,
            {
                **item["data"],
                "outcome": outcome,
                "resolution_evidence_ids": data["evidence_ids"],
                "resolved_epoch": self._clock(),
            },
            state=state,
            expected_version=data["expected_version"],
        )
        resolution = self._create(
            db,
            p,
            "challenge_resolutions",
            {
                "challenge_id": item["id"],
                "outcome": outcome,
                "reason": data["reason"],
                "evidence_ids": data["evidence_ids"],
            },
            state=outcome,
        )
        self._link(db, p, resolution["id"], item["id"], "resolves")
        self._audit(db, p, "challenge.resolve", result, reason=data["reason"], evidence=data["evidence_ids"])
        return result

    def _materially_new(self, db: sqlite3.Connection, p: CollectivePrincipal, item: dict, ids: Any) -> list[dict]:
        evidence = self._evidence(db, p, ids)
        old = set(item["data"].get("evidence_digests", []))
        if not any(ev["data"]["sha256"] not in old for ev in evidence):
            raise CollectiveConflict("reopening requires materially new evidence content")
        if item["data"].get("review_cycles", 1) >= 3:
            raise CollectiveConflict("bounded review cycles exhausted; independent owner triage is required")
        last = item["data"].get("resolved_epoch", item["data"].get("last_reopened_epoch"))
        if last is not None and self._clock() - last < 1800:
            high_impact = item["data"].get("severity") in {"HIGH", "CRITICAL"}
            if not high_impact or not any(
                ev["data"]["attested"] and ev["data"]["sha256"] not in old for ev in evidence
            ):
                raise CollectiveRateLimited(
                    "reopening cooldown; high-impact independently attested new evidence may override"
                )
        return evidence

    def _reopen_challenge(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(data, "id expected_version reason evidence_ids", "id expected_version reason evidence_ids")
        item = self._get(db, p, data["id"], "knowledge_challenges")
        if item["state"] not in {"RESOLVED", "REVIEWING"} or (
            item["state"] == "REVIEWING" and item["data"].get("outcome") not in {"INCONCLUSIVE", "AWAITING_APPROVAL"}
        ):
            raise CollectiveConflict("only a resolved or explicitly inconclusive challenge can reopen")
        evidence = self._materially_new(db, p, item, data["evidence_ids"])
        result = self._update(
            db,
            p,
            item,
            {
                **item["data"],
                "outcome": "REOPENED",
                "last_reopened_epoch": self._clock(),
                "review_cycles": item["data"]["review_cycles"] + 1,
                "evidence_ids": list(dict.fromkeys(item["data"]["evidence_ids"] + data["evidence_ids"])),
                "evidence_digests": sorted(
                    set(item["data"]["evidence_digests"]) | {ev["data"]["sha256"] for ev in evidence}
                ),
            },
            state="REOPENED",
            expected_version=data["expected_version"],
        )
        self._audit(
            db,
            p,
            "challenge.reopen",
            result,
            reason=self._text(data["reason"], "reason"),
            evidence=data["evidence_ids"],
        )
        return result

    def _detect_gap(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(
            data,
            "title description owner_agent_id capability severity environment evidence_ids",
            "title description severity environment evidence_ids",
        )
        title = self._text(data["title"], "title", max_length=200)
        description = self._text(data["description"], "description", max_length=6000)
        environment = self._text(data["environment"], "environment", max_length=200)
        if data["severity"] not in SEVERITIES:
            raise CollectiveError("invalid severity")
        evidence = self._evidence(db, p, data["evidence_ids"])
        fingerprint = digest([self._normalized(title), environment])
        duplicate = self._dedup(db, p, "gaps", fingerprint)
        if duplicate:
            self._audit(
                db,
                p,
                "gap.duplicate_observation",
                duplicate,
                reason="Additional attributed observation of the same genuine gap; ownership and state preserved",
                evidence=data["evidence_ids"],
            )
            return {**duplicate, "deduplicated": True}
        capability = data.get("capability")
        if capability:
            rows = db.execute(
                "SELECT body_json FROM registry_records WHERE tenant_id=? AND owner_id=? AND kind='agent_capabilities'",
                self._scope(p),
            ).fetchall()
            candidates = [
                json.loads(row[0])["agent_id"] for row in rows if json.loads(row[0])["capability"] == capability
            ]
            if not candidates:
                raise CollectiveError("capability is not defined by the canonical registry")
            owner_agent = data.get("owner_agent_id") or candidates[0]
            if owner_agent not in candidates:
                raise CollectiveDenied("assigned owner does not own the requested canonical capability")
        else:
            owner_agent = data.get("owner_agent_id") or p.agent_id or "a19"
        owner_agent = self._agent(db, p, owner_agent)
        item = self._create(
            db,
            p,
            "gaps",
            {
                "title": title,
                "description": description,
                "severity": data["severity"],
                "environment": environment,
                "owner_agent_id": owner_agent,
                "discovering_agent_id": p.agent_id,
                "capability": capability,
                "evidence_ids": data["evidence_ids"],
                "evidence_digests": sorted({ev["data"]["sha256"] for ev in evidence}),
                "root_cause": None,
                "review_cycles": 1,
                "closure_evidence_id": None,
            },
            state="DETECTED",
        )
        self._dedup_record(db, p, item, fingerprint)
        self._audit(db, p, "gap.detect", item, reason=description, evidence=data["evidence_ids"])
        item = self._update(db, p, item, item["data"], state="TRIAGED", expected_version=item["version"])
        self._audit(
            db,
            p,
            "gap.triage",
            item,
            reason="Severity recorded; capability-based owner or accountable discovering agent selected",
        )
        assignment = self._create(
            db,
            p,
            "gap_assignments",
            {
                "gap_id": item["id"],
                "owner_agent_id": owner_agent,
                "reason": "Canonical capability match"
                if capability
                else "Accountable named owner; supporting expertise may be requested",
            },
        )
        self._link(db, p, assignment["id"], item["id"], "assignment")
        self._link(db, p, assignment["id"], f"agent:{owner_agent}", "owner")
        item = self._update(db, p, item, item["data"], state="ASSIGNED", expected_version=item["version"])
        self._audit(
            db, p, "gap.assign", item, reason=f"Accountable owner {owner_agent}; no execution permission is added"
        )
        return item

    @staticmethod
    def _gap_owner(p: CollectivePrincipal, item: dict) -> None:
        if p.roles.intersection({"OWNER", "SYSTEM", "VERIFIER"}):
            return
        if p.agent_id != item["data"]["owner_agent_id"]:
            raise CollectiveDenied("only the accountable owner may advance this gap")

    def _transition_gap(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(
            data, "id expected_version state reason evidence_ids", "id expected_version state reason evidence_ids"
        )
        item = self._get(db, p, data["id"], "gaps")
        self._gap_owner(p, item)
        state = data["state"]
        if item["state"] == "CLOSED":
            raise CollectiveConflict("closed gap requires the explicit recurrence workflow")
        if state in {"REMEDIATING", "VERIFYING", "CLOSED", "PLANNED", "REOPENED"}:
            raise CollectiveDenied("this transition requires a plan, actual execution or independent verification")
        if state not in GAP_NEXT.get(item["state"], set()) | GAP_DISPOSITIONS:
            raise CollectiveConflict("invalid gap transition")
        if state in {"ACCEPTED_RISK", "NOT_ACTIONABLE", "DUPLICATE"}:
            self._role(p, "OWNER")
        self._evidence(db, p, data["evidence_ids"])
        result = self._update(
            db,
            p,
            item,
            {**item["data"], "disposition_reason": self._text(data["reason"], "reason")},
            state=state,
            expected_version=data["expected_version"],
        )
        self._audit(db, p, "gap.transition", result, reason=data["reason"], evidence=data["evidence_ids"])
        return result

    def _plan_gap(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(
            data,
            "gap_id expected_version objective adapter scope restricted evidence_ids root_cause",
            "gap_id expected_version objective adapter scope restricted evidence_ids",
        )
        item = self._get(db, p, data["gap_id"], "gaps")
        self._gap_owner(p, item)
        if item["state"] not in {"ASSIGNED", "PLANNED", "REOPENED"}:
            raise CollectiveConflict("gap must be assigned before remediation planning")
        if type(data["restricted"]) is not bool or not isinstance(data["scope"], dict):
            raise CollectiveError("plan requires explicit restriction and structured scope")
        self._text(data["objective"], "objective")
        adapter = self._text(data["adapter"], "adapter", max_length=100)
        restricted = (
            data["restricted"] or adapter not in SAFE_ADAPTERS or item["data"]["severity"] in {"HIGH", "CRITICAL"}
        )
        self._evidence(db, p, data["evidence_ids"])
        plan = self._create(
            db,
            p,
            "remediation_plans",
            {
                "gap_id": item["id"],
                "objective": data["objective"],
                "adapter": adapter,
                "scope": data["scope"],
                "restricted": restricted,
                "environment": item["data"]["environment"],
                "evidence_ids": data["evidence_ids"],
                "stop_condition": "one fixed adapter execution, then independent outcome/regression/security verification",
                "execution_budget": 1,
                "authority": "PREPARED_ONLY",
            },
            state="AWAITING_APPROVAL" if restricted else "PREPARED",
        )
        self._link(db, p, plan["id"], item["id"], "plan_for")
        body = {
            **item["data"],
            "plan_id": plan["id"],
            "root_cause": data.get("root_cause"),
            "next_action": "OWNER_APPROVAL_REQUIRED" if restricted else "AUTHORIZED_FIXED_ADAPTER_DISPATCH_REQUIRED",
        }
        result = self._update(
            db,
            p,
            item,
            body,
            state="AWAITING_APPROVAL" if restricted else "PLANNED",
            expected_version=data["expected_version"],
        )
        self._audit(db, p, "gap.plan", result, reason=data["objective"], evidence=data["evidence_ids"])
        self._audit(
            db,
            p,
            "remediation.prepare",
            plan,
            reason="Restricted changes never execute through knowledge contributions"
            if restricted
            else "Prepared bounded fixed adapter; existing authorization still applies",
        )
        return result

    def _execute_gap(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._role(p, "SYSTEM")
        self._fields(data, "gap_id expected_version plan_id evidence_id", "gap_id expected_version plan_id evidence_id")
        item = self._get(db, p, data["gap_id"], "gaps")
        plan = self._get(db, p, data["plan_id"], "remediation_plans")
        ev = self._get(db, p, data["evidence_id"], "evidence")
        if (
            item["state"] != "PLANNED"
            or item["data"].get("plan_id") != plan["id"]
            or plan["data"]["gap_id"] != item["id"]
        ):
            raise CollectiveConflict("execution must bind the current prepared plan")
        if plan["data"]["restricted"] or plan["data"]["adapter"] not in SAFE_ADAPTERS:
            raise CollectiveDenied(
                "restricted remediation remains prepared awaiting separate approval and controlled execution"
            )
        body, receipt = ev["data"], ev["data"]["content"]
        if not body["attested"] or body["kind"] != "EXECUTION" or body.get("subject_id") != item["id"]:
            raise CollectiveDenied("actual trusted adapter execution receipt required")
        if (
            receipt.get("plan_id") != plan["id"]
            or receipt.get("adapter") != plan["data"]["adapter"]
            or receipt.get("scope") != plan["data"]["scope"]
            or body["environment"] != plan["data"]["environment"]
        ):
            raise CollectiveDenied("execution receipt scope, plan, adapter or environment mismatch")
        result = self._update(
            db,
            p,
            item,
            {**item["data"], "execution_evidence_id": ev["id"]},
            state="REMEDIATING",
            expected_version=data["expected_version"],
        )
        self._audit(
            db, p, "gap.remediate", result, reason="Fixed authorized adapter actually executed", evidence=[ev["id"]]
        )
        execution = self._create(
            db,
            p,
            "remediation_executions",
            {
                "gap_id": item["id"],
                "plan_id": plan["id"],
                "evidence_id": ev["id"],
                "execution_id": receipt["execution_id"],
                "outcome": receipt["outcome"],
                "candidate_revision": receipt["candidate_revision"],
                "receipt_sha256": body["sha256"],
            },
            state=receipt["outcome"],
        )
        self._link(db, p, execution["id"], item["id"], "execution_for")
        self._link(db, p, execution["id"], ev["id"], "evidence")
        result = self._update(
            db,
            p,
            result,
            {**result["data"], "remediation_execution_id": execution["id"]},
            state="VERIFYING" if receipt["outcome"] == "SUCCEEDED" else "BLOCKED",
            expected_version=result["version"],
        )
        self._audit(
            db,
            p,
            "gap.execution_result",
            result,
            reason="Independent verification required"
            if receipt["outcome"] == "SUCCEEDED"
            else "Actual repair failed; retained owned and visible",
            evidence=[ev["id"]],
        )
        return result

    def _verify_gap(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._role(p, "VERIFIER")
        self._fields(data, "gap_id expected_version evidence_id", "gap_id expected_version evidence_id")
        item = self._get(db, p, data["gap_id"], "gaps")
        if item["state"] != "VERIFYING":
            raise CollectiveConflict("gap requires a successful actual execution before verification")
        evidence = self._independent_evidence(db, p, [data["evidence_id"]], item, verification_only=True)[0]
        execution = self._get(db, p, item["data"]["execution_evidence_id"], "evidence")
        proof, actual = evidence["data"]["content"], execution["data"]["content"]
        if evidence["creator"] == execution["creator"] or p.actor_id == execution["creator"]:
            raise CollectiveDenied("repair executor cannot serve as independent verifier")
        if (
            proof["execution_sha256"] != execution["data"]["sha256"]
            or proof["execution_id"] != actual["execution_id"]
            or proof["plan_id"] != actual["plan_id"]
            or proof["candidate_revision"] != actual["candidate_revision"]
            or evidence["data"]["environment"] != execution["data"]["environment"]
        ):
            raise CollectiveDenied("verification is not bound to the actual repair and intended environment")
        if not all(value is True for value in proof["checks"].values()):
            raise CollectiveConflict("corrective outcome, regression or security verification failed; gap remains open")
        result = self._update(
            db,
            p,
            item,
            {
                **item["data"],
                "closure_evidence_id": evidence["id"],
                "closed_by": p.actor_id,
                "resolved_epoch": self._clock(),
                "next_action": None,
                "evidence_digests": list(
                    dict.fromkeys(item["data"]["evidence_digests"] + [evidence["data"]["sha256"]])
                ),
            },
            state="CLOSED",
            expected_version=data["expected_version"],
        )
        verification = self._create(
            db,
            p,
            "remediation_verifications",
            {
                "gap_id": item["id"],
                "evidence_id": evidence["id"],
                "execution_evidence_id": execution["id"],
                "verified_by": p.actor_id,
                "checks": proof["checks"],
            },
            state="ACCEPTED",
        )
        self._link(db, p, verification["id"], item["id"], "verified_gap")
        self._link(db, p, verification["id"], evidence["id"], "evidence")
        self._audit(
            db,
            p,
            "gap.verify_close",
            result,
            reason="Actual target updated; independent outcome, regression and security checks accepted",
            evidence=[execution["id"], evidence["id"]],
        )
        lesson = self._create(
            db,
            p,
            "lessons_learned",
            {
                "gap_id": item["id"],
                "summary": item["data"]["title"],
                "root_cause": item["data"].get("root_cause"),
                "evidence_ids": [execution["id"], evidence["id"]],
                "recurrence_rule": "Reopen only on materially new observed failure; preserve this closure receipt",
            },
            state="VERIFIED_REPAIR",
        )
        self._link(db, p, lesson["id"], item["id"], "lesson_from")
        self._audit(
            db, p, "lesson.preserve", lesson, reason="Durable verified repair learning", evidence=[evidence["id"]]
        )
        return result

    def _reopen_gap(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(data, "id expected_version reason evidence_ids", "id expected_version reason evidence_ids")
        item = self._get(db, p, data["id"], "gaps")
        if item["state"] not in {"CLOSED", "ACCEPTED_RISK", "DEFERRED", "NOT_ACTIONABLE"}:
            raise CollectiveConflict("gap is already active")
        evidence = self._materially_new(db, p, item, data["evidence_ids"])
        result = self._update(
            db,
            p,
            item,
            {
                **item["data"],
                "review_cycles": item["data"].get("review_cycles", 1) + 1,
                "evidence_digests": sorted(
                    set(item["data"]["evidence_digests"]) | {ev["data"]["sha256"] for ev in evidence}
                ),
                "last_reopened_epoch": self._clock(),
                "closure_evidence_id": None,
                "next_action": "ACCOUNTABLE_OWNER_TRIAGE",
            },
            state="REOPENED",
            expected_version=data["expected_version"],
        )
        self._audit(
            db, p, "gap.reopen", result, reason=self._text(data["reason"], "reason"), evidence=data["evidence_ids"]
        )
        return result

    def _create_puzzle(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(
            data,
            "title objective requirements assigned_agent_ids completion_condition evidence_ids",
            "title objective requirements assigned_agent_ids completion_condition evidence_ids",
        )
        self._text(data["title"], "title", max_length=200)
        self._text(data["objective"], "objective")
        self._text(data["completion_condition"], "completion_condition")
        self._evidence(db, p, data["evidence_ids"])
        requirements = data["requirements"]
        if not isinstance(requirements, list) or not 1 <= len(requirements) <= 20:
            raise CollectiveError("puzzle requires one to twenty measurable pieces")
        keys = set()
        for requirement in requirements:
            if not isinstance(requirement, dict):
                raise CollectiveError("puzzle requirements must be structured")
            self._fields(requirement, "key description evidence_criteria", "key description evidence_criteria")
            key = self._text(requirement["key"], "requirement key", max_length=80)
            if not IDENTIFIER.fullmatch(key) or key in keys:
                raise CollectiveError("requirement keys must be unique safe identifiers")
            keys.add(key)
            self._text(requirement["description"], "description")
            self._text(requirement["evidence_criteria"], "evidence_criteria")
        if not isinstance(data["assigned_agent_ids"], list) or not 1 <= len(data["assigned_agent_ids"]) <= 21:
            raise CollectiveError("explicit assigned contributors are required")
        contributors = sorted({self._agent(db, p, agent) for agent in data["assigned_agent_ids"]})
        item = self._create(
            db,
            p,
            "puzzles",
            {
                "title": data["title"],
                "objective": data["objective"],
                "assigned_agent_ids": contributors,
                "completion_condition": data["completion_condition"],
                "requirement_keys": sorted(keys),
                "evidence_ids": data["evidence_ids"],
                "review_cycles": 1,
                "evidence_digests": [],
                "missing_requirements": sorted(keys),
                "completion": 0.0,
            },
            state="ACTIVE",
        )
        for requirement in requirements:
            req = self._create(db, p, "puzzle_requirements", {**requirement, "puzzle_id": item["id"]}, state="MISSING")
            self._link(db, p, req["id"], item["id"], "requirement_for")
        self._audit(db, p, "puzzle.create", item, reason=data["objective"], evidence=data["evidence_ids"])
        return item

    def _related(
        self, db: sqlite3.Connection, p: CollectivePrincipal, target: str, relation: str, kind: str
    ) -> list[dict]:
        rows = db.execute(
            "SELECT source_id FROM registry_relations WHERE tenant_id=? AND owner_id=? AND target_id=? AND relation=?",
            (*self._scope(p), target, relation),
        ).fetchall()
        return [self._get(db, p, row[0], kind) for row in rows]

    def _assembly(self, db: sqlite3.Connection, p: CollectivePrincipal, puzzle: dict) -> dict:
        contributions = self._related(db, p, puzzle["id"], "contribution_for", "puzzle_contributions")
        pieces = []
        claims = []
        satisfied = set()
        for contribution in contributions:
            claim = self._get(db, p, contribution["data"]["claim_id"], "knowledge_claims")
            if claim["state"] in {"DISPUTED", "REJECTED", "SUPERSEDED"}:
                continue
            claims.append(claim["id"])
            satisfied.add(contribution["data"]["requirement_key"])
            pieces.append(
                {
                    "contribution_id": contribution["id"],
                    "claim_id": claim["id"],
                    "claim_version": claim["version"],
                    "requirement_key": contribution["data"]["requirement_key"],
                    "evidence_ids": contribution["data"]["evidence_ids"],
                }
            )
        conflicts = []
        rows = db.execute(
            "SELECT id,body_json FROM registry_records WHERE tenant_id=? AND owner_id=? AND kind='knowledge_relationships' AND state='DISPUTED'",
            self._scope(p),
        ).fetchall()
        for row in rows:
            relationship = json.loads(row["body_json"])
            if relationship["relation"] == "CONTRADICTS" and (
                relationship["source_id"] in claims or relationship["target_id"] in claims
            ):
                conflicts.append(row["id"])
        missing = sorted(set(puzzle["data"]["requirement_keys"]) - satisfied)
        return {
            "pieces": sorted(pieces, key=lambda value: value["contribution_id"]),
            "missing_requirements": missing,
            "unresolved_contradictions": sorted(conflicts),
            "completion": (len(satisfied) / len(puzzle["data"]["requirement_keys"])),
        }

    def _contribute_puzzle(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._role(p, "AGENT")
        self._fields(
            data,
            "puzzle_id expected_version requirement_key claim_id evidence_ids",
            "puzzle_id expected_version requirement_key claim_id evidence_ids",
        )
        puzzle = self._get(db, p, data["puzzle_id"], "puzzles")
        if puzzle["state"] != "ACTIVE" or p.agent_id not in puzzle["data"]["assigned_agent_ids"]:
            raise CollectiveDenied("puzzle requires an assigned contributor and active review cycle")
        if data["requirement_key"] not in puzzle["data"]["requirement_keys"]:
            raise CollectiveError("unknown puzzle requirement")
        claim = self._get(db, p, data["claim_id"], "knowledge_claims")
        if claim["creator_agent"] != p.agent_id:
            raise CollectiveDenied("puzzle contribution must reference the authenticated agent's own finding")
        self._evidence(db, p, data["evidence_ids"])
        item = self._create(
            db,
            p,
            "puzzle_contributions",
            {**data, "agent_id": p.agent_id, "execution_id": p.execution_id, "claim_version": claim["version"]},
            state="AWAITING_INDEPENDENT_VALIDATION",
        )
        self._link(db, p, item["id"], puzzle["id"], "contribution_for")
        self._link(db, p, item["id"], claim["id"], "uses_claim")
        assembly = self._assembly(db, p, puzzle)
        result = self._update(
            db,
            p,
            puzzle,
            {**puzzle["data"], **assembly, "assembly_sha256": digest(assembly)},
            expected_version=data["expected_version"],
        )
        self._audit(
            db,
            p,
            "puzzle.contribute",
            result,
            reason="Evidence-backed piece requires independent assembly verification",
            evidence=data["evidence_ids"],
        )
        return result

    def _complete_puzzle(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._role(p, "VERIFIER")
        self._fields(data, "id expected_version evidence_ids reason", "id expected_version evidence_ids reason")
        puzzle = self._get(db, p, data["id"], "puzzles")
        if puzzle["state"] != "ACTIVE":
            raise CollectiveConflict("puzzle must be active")
        assembly = self._assembly(db, p, puzzle)
        if assembly["missing_requirements"] or assembly["unresolved_contradictions"]:
            raise CollectiveConflict("puzzle still has missing or disputed pieces")
        evidence = self._independent_evidence(db, p, data["evidence_ids"], puzzle, verification_only=True)
        if not any(
            ev["data"]["content"]["execution_sha256"] == digest(assembly)
            and ev["data"]["content"]["plan_id"] == puzzle["id"]
            and all(value is True for value in ev["data"]["content"]["checks"].values())
            for ev in evidence
        ):
            raise CollectiveDenied(
                "independent proof must validate the exact assembled pieces and current claim versions"
            )
        result = self._update(
            db,
            p,
            puzzle,
            {
                **puzzle["data"],
                **assembly,
                "assembly_sha256": digest(assembly),
                "completion_evidence_ids": data["evidence_ids"],
                "evidence_digests": [ev["data"]["sha256"] for ev in evidence],
                "resolved_epoch": self._clock(),
            },
            state="COMPLETED",
            expected_version=data["expected_version"],
        )
        self._audit(
            db, p, "puzzle.complete", result, reason=self._text(data["reason"], "reason"), evidence=data["evidence_ids"]
        )
        return result

    def _reopen_puzzle(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(data, "id expected_version reason evidence_ids", "id expected_version reason evidence_ids")
        item = self._get(db, p, data["id"], "puzzles")
        if item["state"] not in {"COMPLETED", "REQUIRES_REVALIDATION"}:
            raise CollectiveConflict("puzzle is already active")
        evidence = self._materially_new(db, p, item, data["evidence_ids"])
        result = self._update(
            db,
            p,
            item,
            {
                **item["data"],
                "review_cycles": item["data"]["review_cycles"] + 1,
                "completion_evidence_ids": [],
                "evidence_digests": sorted(
                    set(item["data"]["evidence_digests"]) | {ev["data"]["sha256"] for ev in evidence}
                ),
            },
            state="ACTIVE",
            expected_version=data["expected_version"],
        )
        self._audit(
            db, p, "puzzle.reopen", result, reason=self._text(data["reason"], "reason"), evidence=data["evidence_ids"]
        )
        return result

    def _invalidate_dependents(
        self, db: sqlite3.Connection, p: CollectivePrincipal, claim: dict, evidence_ids: list[str], *, reason: str
    ) -> None:
        contributions = self._related(db, p, claim["id"], "uses_claim", "puzzle_contributions")
        affected = {contribution["data"]["puzzle_id"] for contribution in contributions}
        for puzzle_id in sorted(affected):
            puzzle = self._get(db, p, puzzle_id, "puzzles")
            if puzzle["state"] == "COMPLETED":
                result = self._update(
                    db,
                    p,
                    puzzle,
                    {**puzzle["data"], "revalidation_reason": reason, "changed_claim_id": claim["id"]},
                    state="REQUIRES_REVALIDATION",
                    expected_version=puzzle["version"],
                )
                self._audit(db, p, "puzzle.invalidate", result, reason=reason, evidence=evidence_ids)

    def _observe(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._role(p, "SYSTEM")
        self._fields(
            data,
            "kind canonical_id definition source_sha256 evidence_ids health integration_verified model_assignment",
            "kind canonical_id definition source_sha256 evidence_ids",
        )
        kind = data["kind"]
        if kind not in {"fabrics", "models", "health_snapshots", "execution_records", "fabric_capabilities"}:
            raise CollectiveDenied(
                "canonical identities, capabilities and policies cannot be overwritten by observation"
            )
        canonical_id = self._text(data["canonical_id"], "canonical_id", max_length=120)
        if not IDENTIFIER.fullmatch(canonical_id) or not re.fullmatch(r"[0-9a-f]{64}", str(data["source_sha256"])):
            raise CollectiveError("source-bound observation identifier and digest required")
        if not isinstance(data["definition"], dict):
            raise CollectiveError("observation definition must be an object")
        evidence = self._evidence(db, p, data["evidence_ids"])
        health = data.get("health", "CONFIGURED")
        if health not in {"CONFIGURED", "OBSERVED", "STALE", "UNAVAILABLE", "UNKNOWN"}:
            raise CollectiveError("invalid observed health state")
        verified = data.get("integration_verified", False)
        if type(verified) is not bool:
            raise CollectiveError("integration_verified must be explicit boolean")
        if (verified or health == "OBSERVED") and not any(
            ev["data"]["attested"]
            and ev["data"]["kind"] == "EXECUTION"
            and ev["data"]["content"].get("outcome") == "SUCCEEDED"
            for ev in evidence
        ):
            raise CollectiveDenied(
                "observed live health or verified integration requires successful trusted runtime execution evidence"
            )
        body = {
            **data,
            "health": health,
            "integration_verified": verified,
            "observed_epoch": self._clock(),
            "authority": "READ_ONLY_OBSERVATION",
            "qualification": "NOT_ESTABLISHED_BY_REGISTRATION",
        }
        object_id = f"{kind}:{canonical_id}"
        try:
            current = self._get(db, p, object_id, kind)
        except CollectiveNotFound:
            item = self._create(db, p, kind, body, state=health, object_id=object_id)
        else:
            item = self._update(db, p, current, body, state=health, expected_version=current["version"])
        self._audit(
            db,
            p,
            "registry.observe",
            item,
            reason="Source-bound independent fabric observation; no new permissions",
            evidence=data["evidence_ids"],
        )
        return item

    def _lesson(self, db: sqlite3.Connection, p: CollectivePrincipal, data: dict) -> dict:
        self._fields(data, "summary evidence_ids related_ids", "summary evidence_ids related_ids")
        self._text(data["summary"], "summary")
        self._evidence(db, p, data["evidence_ids"])
        if not isinstance(data["related_ids"], list) or len(data["related_ids"]) > 20:
            raise CollectiveError("bounded related records required")
        item = self._create(
            db, p, "lessons_learned", {**data, "source_execution_id": p.execution_id}, state="UNVERIFIED"
        )
        for object_id in data["related_ids"]:
            self._link(db, p, item["id"], object_id, "learned_from")
        self._audit(
            db,
            p,
            "lesson.record",
            item,
            reason="Contributed lesson; independent verification remains separate",
            evidence=data["evidence_ids"],
        )
        return item

    def lookup(self, p: CollectivePrincipal, kind: str, identifier: str) -> dict:
        """Exact lookup using canonical names or scoped record identifiers."""
        self._text(identifier, "identifier", max_length=160)
        prefixes = {"agents": "agent", "capabilities": "capability", "policies": "policy"}
        if kind in prefixes and not identifier.startswith(prefixes[kind] + ":"):
            identifier = prefixes[kind] + ":" + identifier
        if kind in {"fabrics", "models"} and not identifier.startswith(kind + ":"):
            identifier = kind + ":" + identifier
        return self.query(p, kind, id=identifier)

    def lookup_agent(self, p: CollectivePrincipal, identifier: str) -> dict:
        return self.lookup(p, "agents", identifier)

    def lookup_fabric(self, p: CollectivePrincipal, identifier: str) -> dict:
        return self.lookup(p, "fabrics", identifier)

    def lookup_capability(self, p: CollectivePrincipal, identifier: str) -> dict:
        return self.lookup(p, "capabilities", identifier)

    def lookup_policy(self, p: CollectivePrincipal, identifier: str) -> dict:
        return self.lookup(p, "policies", identifier)

    def lookup_evidence(self, p: CollectivePrincipal, identifier: str) -> dict:
        return self.lookup(p, "evidence", identifier)

    def lookup_knowledge(self, p: CollectivePrincipal, identifier: str) -> dict:
        return self.lookup(p, "knowledge_claims", identifier)

    def lookup_puzzle(self, p: CollectivePrincipal, identifier: str) -> dict:
        return self.lookup(p, "puzzles", identifier)

    def lookup_gap(self, p: CollectivePrincipal, identifier: str) -> dict:
        return self.lookup(p, "gaps", identifier)

    def lookup_health(self, p: CollectivePrincipal, subject_id: str, *, max_age_seconds: int = 300) -> dict:
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
            raise CollectiveError("health freshness bound must be between one second and one hour")
        with self.connect() as db:
            self._get(db, p, subject_id)
            rows = db.execute(
                "SELECT id,body_json FROM registry_records WHERE tenant_id=? AND owner_id=? AND kind='health_snapshots' ORDER BY updated_at DESC",
                self._scope(p),
            ).fetchall()
            for row in rows:
                body = json.loads(row["body_json"])
                if body.get("definition", {}).get("subject_id") == subject_id:
                    age = max(0, self._clock() - body["observed_epoch"])
                    return {
                        "subject_id": subject_id,
                        "state": "STALE" if age > max_age_seconds else body["health"],
                        "age_seconds": age,
                        "observation": self._get(db, p, row["id"]),
                        "authority": "NO_PERMISSION_GRANT",
                    }
        return {
            "subject_id": subject_id,
            "state": "UNKNOWN",
            "age_seconds": None,
            "observation": None,
            "authority": "NO_PERMISSION_GRANT",
        }

    def lookup_dependencies(self, p: CollectivePrincipal, subject_id: str, *, max_depth: int = 4) -> dict:
        if type(max_depth) is not int or not 1 <= max_depth <= 4:
            raise CollectiveError("dependency traversal depth must be one to four")
        with self.connect() as db:
            self._get(db, p, subject_id)
            rows = db.execute(
                "SELECT id,body_json FROM registry_records WHERE tenant_id=? AND owner_id=? AND kind='dependencies'",
                self._scope(p),
            ).fetchall()
            dependencies = [(row["id"], json.loads(row["body_json"])) for row in rows]
            visited, pending, result = {subject_id}, [(subject_id, 0)], []
            while pending and len(visited) <= 64:
                current, depth = pending.pop(0)
                if depth >= max_depth:
                    continue
                for record_id, body in dependencies:
                    if body["source"] == current:
                        result.append({"id": record_id, **body, "depth": depth + 1})
                        if body["target"] not in visited:
                            visited.add(body["target"])
                            pending.append((body["target"], depth + 1))
            return {
                "subject_id": subject_id,
                "dependencies": result[:64],
                "bounded": True,
                "max_depth": max_depth,
                "authority": "READ_ONLY_ARCHITECTURE",
            }

    def trace_claim_provenance(self, p: CollectivePrincipal, identifier: str) -> dict:
        with self.connect() as db:
            claim = self._get(db, p, identifier, "knowledge_claims")
            links = db.execute(
                "SELECT source_id,target_id,relation FROM registry_relations WHERE tenant_id=? AND owner_id=? AND (source_id=? OR target_id=?) ORDER BY relation LIMIT 200",
                (*self._scope(p), identifier, identifier),
            ).fetchall()
            events = db.execute(
                "SELECT body_json,event_hash FROM audit_events WHERE tenant_id=? AND owner_id=? AND subject_id=? ORDER BY sequence LIMIT 200",
                (*self._scope(p), identifier),
            ).fetchall()
            return {
                "claim": claim,
                "relationships": [dict(row) for row in links],
                "history": [{"event": json.loads(row[0]), "event_hash": row[1]} for row in events],
                "chain_integrity": self.integrity(p)["audit_chain"],
            }

    def find_conflicting_claims(self, p: CollectivePrincipal, identifier: str | None = None) -> dict:
        if identifier:
            self.query(p, "knowledge_claims", id=identifier)
        result = self.query(p, "knowledge_relationships", filters={"state": "DISPUTED", "limit": 200})
        items = [
            item
            for item in result["items"]
            if item["data"]["relation"] == "CONTRADICTS"
            and (identifier is None or identifier in {item["data"]["source_id"], item["data"]["target_id"]})
        ]
        return {
            "items": items,
            "total": len(items),
            "bounded": result["total"] > len(result["items"]),
            "meaning": "Unresolved attributed contradictions; agreement alone is not independent proof",
        }

    def resolve_shadow(
        self,
        p: CollectivePrincipal,
        capability: str,
        *,
        authorization: Mapping[str, bool] | None = None,
        require_certification: bool = False,
    ) -> dict:
        """Read-only candidate explanation; authorization comes from the trusted caller.

        No request body or registry document may supply this permission mapping.
        Even an eligible result cannot dispatch work or replace Stable Spine.
        """
        self.lookup_capability(p, capability)
        agents = self.query(p, "agents", filters={"limit": 100})["items"]
        candidates = []
        for agent in agents:
            if capability not in agent["data"]["capability_requirements"]:
                continue
            agent_id = agent["data"]["canonical_id"]
            health = self.lookup_health(p, agent["id"])
            reasons = []
            if authorization is None or authorization.get(agent_id) is not True:
                reasons.append("MISSING_TRUSTED_AUTHORIZATION")
            if health["state"] != "OBSERVED":
                reasons.append("HEALTH_" + health["state"])
            elif health["observation"]["data"].get("definition", {}).get("healthy") is not True:
                reasons.append("HEALTH_NOT_READY")
            if require_certification:
                reasons.append("CERTIFICATION_NOT_ESTABLISHED_BY_REGISTRY")
            candidates.append(
                {
                    "agent_id": agent_id,
                    "eligible_for_existing_governance_review": not reasons,
                    "reasons": reasons,
                    "health": health["state"],
                    "source_capability_match": True,
                }
            )
        return {
            "capability": capability,
            "mode": "SHADOW_ONLY",
            "candidates": candidates,
            "selected_agent_id": next((item["agent_id"] for item in candidates if not item["reasons"]), None),
            "execution_authorized": False,
            "fallback": None,
            "explanation": "Canonical capability ownership is advisory; trusted policy, fresh health and existing execution gates remain mandatory",
        }

    resolve_task = resolve_shadow
    resolve_execution_path = resolve_shadow
    explain_routing_decision = resolve_shadow
    resolve_fallback = resolve_shadow

    def find_missing_capabilities(self, p: CollectivePrincipal, required: list[str]) -> dict:
        if (
            not isinstance(required, list)
            or len(required) > 100
            or any(not isinstance(value, str) for value in required)
        ):
            raise CollectiveError("bounded capability list required")
        known = {
            item["data"]["canonical_id"] for item in self.query(p, "capabilities", filters={"limit": 200})["items"]
        }
        return {"missing": sorted(set(required) - known), "authority": "CANONICAL_SOURCE_MIRROR"}

    def find_unresolved_dependencies(self, p: CollectivePrincipal) -> dict:
        dependencies = self.query(p, "dependencies", filters={"limit": 200})["items"]
        missing = []
        with self.connect() as db:
            for dependency in dependencies:
                for key in ("source", "target"):
                    try:
                        self._get(db, p, dependency["data"][key])
                    except CollectiveNotFound:
                        missing.append({"dependency_id": dependency["id"], "missing_id": dependency["data"][key]})
        return {"missing": missing, "bounded": len(dependencies) == 200}

    def metrics(self, p: CollectivePrincipal) -> dict:
        started = time.perf_counter()
        with self.connect() as db:
            rows = db.execute(
                "SELECT kind,state,count(*) AS total FROM registry_records WHERE tenant_id=? AND owner_id=? GROUP BY kind,state",
                self._scope(p),
            ).fetchall()
            counts: dict[str, dict[str, int]] = {}
            for row in rows:
                counts.setdefault(row["kind"], {})[row["state"]] = row["total"]
            participation = {}
            for name, operation in (
                ("contributing_agents_with_execution_attribution", "claim.contribute"),
                ("questioning_tested_agents", "challenge.open"),
                ("gap_workflow_tested_agents", "gap.detect"),
            ):
                participation[name] = db.execute(
                    "SELECT count(DISTINCT agent_id) FROM audit_events WHERE tenant_id=? AND owner_id=? AND operation IN (?,?) AND agent_id IS NOT NULL",
                    (
                        *self._scope(p),
                        operation,
                        "gap.duplicate_observation" if operation == "gap.detect" else operation,
                    ),
                ).fetchone()[0]
            claims = db.execute(
                "SELECT creator_agent,body_json FROM registry_records WHERE tenant_id=? AND owner_id=? AND kind='knowledge_claims' AND creator_agent IS NOT NULL",
                self._scope(p),
            ).fetchall()
            contributing = set()
            for row in claims:
                body = json.loads(row["body_json"])
                for evidence_id in body.get("evidence_ids", []):
                    ev = self._get(db, p, evidence_id, "evidence")["data"]
                    receipt = ev["content"]
                    if (
                        ev["attested"]
                        and ev["kind"] == "EXECUTION"
                        and receipt.get("adapter") == "queue_inference"
                        and receipt.get("outcome") == "SUCCEEDED"
                        and receipt.get("agent_id") == row["creator_agent"]
                        and receipt.get("execution_id") == body.get("source_execution_id")
                    ):
                        contributing.add(row["creator_agent"])
            participation["verified_contributing_agents"] = len(contributing)
            fabric_rows = db.execute(
                "SELECT body_json FROM registry_records WHERE tenant_id=? AND owner_id=? AND kind='fabrics'",
                self._scope(p),
            ).fetchall()
            fabric_bodies = [json.loads(row[0]) for row in fabric_rows]
            times = db.execute(
                "SELECT min(updated_at),max(updated_at) FROM registry_records WHERE tenant_id=? AND owner_id=? AND kind='knowledge_claims'",
                self._scope(p),
            ).fetchone()
            events = db.execute(
                "SELECT count(*) FROM audit_events WHERE tenant_id=? AND owner_id=?", self._scope(p)
            ).fetchone()[0]
            reopened = db.execute(
                "SELECT operation,count(*) FROM audit_events WHERE tenant_id=? AND owner_id=? AND operation IN ('challenge.reopen','gap.reopen','puzzle.reopen') GROUP BY operation",
                self._scope(p),
            ).fetchall()
            reopen_counts = dict(reopened)
            corrections = db.execute(
                "SELECT count(*) FROM audit_events WHERE tenant_id=? AND owner_id=? AND operation='claim.correct'",
                self._scope(p),
            ).fetchone()[0]
        total = lambda kind: sum(counts.get(kind, {}).values())
        state = lambda kind, name: counts.get(kind, {}).get(name, 0)
        agents = total("agents")
        integrity = self.integrity(p)
        return {
            "api_version": "1.0",
            "scope": {"tenant_id": p.tenant_id, "owner_id": p.owner_id},
            "agents": {
                "registered": agents,
                "expected": 21,
                "enrolled": agents,
                "contribution_pathway_configured": agents,
                "questioning_pathway_configured": agents,
                "gap_pathway_configured": agents,
                **participation,
                "note": "Configured pathways and actual authenticated participation are separate; no model qualification or certification implied",
            },
            "fabrics": {
                "discovered": len(fabric_bodies),
                "integrated": sum(body["integration_verified"] for body in fabric_bodies),
                "note": "Only trusted observed inventory is counted; source presence alone is not live operation",
            },
            "knowledge": {
                "claims": total("knowledge_claims"),
                "verified_facts": state("knowledge_claims", "VERIFIED_FACT"),
                "corrections_accepted": corrections,
                "oldest_updated_at": times[0],
                "newest_updated_at": times[1],
                "unresolved_contradictions": state("knowledge_relationships", "DISPUTED"),
            },
            "puzzles": {
                "active": state("puzzles", "ACTIVE") + state("puzzles", "REQUIRES_REVALIDATION"),
                "completed": state("puzzles", "COMPLETED"),
                "reopened": reopen_counts.get("puzzle.reopen", 0),
            },
            "challenges": {
                "submitted": total("knowledge_challenges"),
                "open": total("knowledge_challenges") - state("knowledge_challenges", "RESOLVED"),
                "resolved": state("knowledge_challenges", "RESOLVED"),
                "reopened": reopen_counts.get("challenge.reopen", 0),
            },
            "gaps": {
                "detected": total("gaps"),
                "assigned": total("gap_assignments"),
                "open": total("gaps")
                - sum(state("gaps", name) for name in ("CLOSED", "NOT_ACTIONABLE", "DUPLICATE", "ACCEPTED_RISK")),
                "under_remediation": state("gaps", "REMEDIATING") + state("gaps", "VERIFYING"),
                "verified_closed": state("gaps", "CLOSED"),
                "blocked": state("gaps", "BLOCKED"),
                "awaiting_approval": state("gaps", "AWAITING_APPROVAL"),
                "reopened": reopen_counts.get("gap.reopen", 0),
            },
            "registry_health": "PASS" if integrity["pass"] else "FAIL",
            "integrity": integrity,
            "resources": {
                "sqlite_bytes": self.path.stat().st_size,
                "wal_bytes": Path(str(self.path) + "-wal").stat().st_size
                if Path(str(self.path) + "-wal").exists()
                else 0,
                "query_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "audit_events": events,
                "mandatory_aws_cost_usd": 0,
                "aws_cost_basis": "No AWS client, infrastructure provisioning or mandatory paid dependency in this component",
            },
            "observed_at": self._now(),
            "authority": "READ_ONLY_MEASUREMENTS",
        }

    def snapshot(self, p: CollectivePrincipal) -> dict:
        return {
            "api_version": "1.0",
            "observed_at": self._now(),
            "metrics": self.metrics(p),
            "claims": self.query(p, "knowledge_claims", filters={"limit": 100}),
            "challenges": self.query(p, "knowledge_challenges", filters={"limit": 100}),
            "puzzles": self.query(p, "puzzles", filters={"limit": 100}),
            "gaps": self.query(p, "gaps", filters={"limit": 100}),
            "cache_policy": "PRIVATE_NO_STORE",
            "outage_behavior": "Unavailable; cached snapshots are read-only and grant no permissions",
        }

    def audit(self, p: CollectivePrincipal, *, limit: int = 50, before_sequence: int | None = None) -> dict:
        self._scope(p)
        if (
            type(limit) is not int
            or not 1 <= limit <= 200
            or (before_sequence is not None and (type(before_sequence) is not int or before_sequence < 1))
        ):
            raise CollectiveError("invalid audit pagination bounds")
        with self.connect() as db:
            where = "tenant_id=? AND owner_id=?"
            params: list[Any] = [*self._scope(p)]
            if before_sequence is not None:
                where += " AND sequence<?"
                params.append(before_sequence)
            rows = db.execute(
                f"SELECT sequence,body_json,event_hash FROM audit_events WHERE {where} ORDER BY sequence DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return {
                "items": [
                    {"sequence": row["sequence"], "event_hash": row["event_hash"], **json.loads(row["body_json"])}
                    for row in rows
                ],
                "next_before_sequence": rows[-1]["sequence"] if len(rows) == limit else None,
                "authority": "READ_ONLY_AUDIT",
                "api_version": "1.0",
            }

    def integrity(self, p: CollectivePrincipal) -> dict:
        self._scope(p)
        with self.connect() as db:
            quick = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            foreign_keys = not db.execute("PRAGMA foreign_key_check").fetchall()
            rows = db.execute(
                "SELECT body_json,previous_hash,event_hash FROM audit_events WHERE tenant_id=? AND owner_id=? ORDER BY sequence",
                self._scope(p),
            ).fetchall()
            prior, chain = "0" * 64, True
            latest: dict[str, dict] = {}
            for row in rows:
                body = json.loads(row[0])
                if row[1] != prior or body["previous_hash"] != prior or digest(body) != row[2]:
                    chain = False
                    break
                prior = row[2]
                latest[body["subject_id"]] = body["record"]
            materialized = True
            records = db.execute(
                "SELECT id FROM registry_records WHERE tenant_id=? AND owner_id=?", self._scope(p)
            ).fetchall()
            for row in records:
                if latest.get(row[0]) != self._get(db, p, row[0]):
                    materialized = False
                    break
            return {
                "pass": quick and foreign_keys and chain and materialized,
                "sqlite_quick_check": quick,
                "foreign_keys": foreign_keys,
                "audit_chain": chain,
                "events_checked": len(rows),
                "materialized_records_match_audit": materialized,
                "chain_head": prior,
                "scope": "Tenant/owner event chain; SQLite structural checks are database-wide",
                "limitation": "Tamper-evident against partial edits; host administrator can replace the entire database and external anchor is required to detect that",
            }

    def backup(self, destination: str | Path) -> dict:
        """Host-operator API only; never expose caller-controlled filesystem paths."""
        target = Path(destination)
        if target.exists() or target.resolve() == self.path.resolve():
            raise CollectiveConflict("backup destination must be a new host-owned file")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.connect() as source, closing(sqlite3.connect(target)) as output:
            source.backup(output)
            if output.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise CollectiveConflict("backup integrity check failed")
        return {
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "bytes": target.stat().st_size,
            "schema_version": SCHEMA_VERSION,
            "integrity": "PASS",
        }

    @classmethod
    def restore(cls, backup_path: str | Path, destination: str | Path, *, expected_sha256: str) -> CollectiveStore:
        """Restore into a NEW host-owned path; running databases are never overwritten."""
        source, target = Path(backup_path), Path(destination)
        if target.exists() or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise CollectiveConflict("restore requires a new path and the exact approved backup digest")
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256:
            raise CollectiveDenied("backup content does not match approved digest")
        target.parent.mkdir(parents=True, exist_ok=True)
        with (
            closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)) as incoming,
            closing(sqlite3.connect(target)) as outgoing,
        ):
            if incoming.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise CollectiveConflict("backup SQLite integrity failed")
            incoming.backup(outgoing)
        return cls(target)
