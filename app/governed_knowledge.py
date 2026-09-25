"""Scoped, temporal, provenance-preserving memory and local retrieval primitives."""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class MemoryClass(str, Enum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    EVENT = "EVENT"
    PROCEDURE = "PROCEDURE"
    INFERENCE = "INFERENCE"


class Scope(str, Enum):
    OWNER_PRIVATE = "OWNER_PRIVATE"
    MEMBER_PRIVATE = "MEMBER_PRIVATE"
    HOUSEHOLD_SHARED = "HOUSEHOLD_SHARED"
    APPLICATION = "APPLICATION"
    SYSTEM = "SYSTEM"


class TemporalState(str, Enum):
    CURRENT = "CURRENT"
    HISTORICAL = "HISTORICAL"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class AccessContext:
    actor_type: str
    actor_id: str
    household_id: str | None = None


TOKEN = re.compile(r"[a-z0-9_\-\u3400-\u9fff]{2,}", re.I)
MODEL_AUTHORITIES = frozenset({"MODEL", "MODEL_OUTPUT", "INFERENCE"})
FACT_AUTHORITIES = frozenset({"OWNER", "VERIFIED_POLICY"})
KNOWN_AUTHORITIES = frozenset({"OWNER", "MEMBER", "APPLICATION", "SYSTEM", "RUNTIME", "VERIFIED_POLICY", *MODEL_AUTHORITIES})


def _tokens(value: str) -> set[str]:
    return set(TOKEN.findall(value.lower()))


class GovernedKnowledgeStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init(self) -> None:
        with closing(self.connect()) as db, db:
            db.executescript(
                """
                create table if not exists governed_memory (
                  record_id text primary key,
                  memory_key text not null,
                  memory_class text not null,
                  scope text not null,
                  scope_id text not null,
                  temporal_state text not null,
                  value_json text not null,
                  source text not null,
                  source_version text not null,
                  source_authority text not null,
                  verification_ref text,
                  created_at real not null,
                  supersedes_id text
                );
                create unique index if not exists governed_memory_current
                  on governed_memory(memory_key,memory_class,scope,scope_id)
                  where temporal_state='CURRENT';
                create table if not exists rag_documents (
                  document_id text primary key,
                  scope text not null,
                  scope_id text not null,
                  source text not null,
                  source_version text not null,
                  authority_class text not null,
                  content text not null,
                  content_sha256 text not null,
                  created_at real not null
                );
                """
            )

    @staticmethod
    def _can_access(context: AccessContext, scope: Scope, scope_id: str) -> bool:
        actor = context.actor_type.upper()
        if scope is Scope.SYSTEM:
            return True
        if scope is Scope.OWNER_PRIVATE:
            return actor == "OWNER" and context.actor_id == scope_id
        if scope is Scope.MEMBER_PRIVATE:
            return actor == "MEMBER" and context.actor_id == scope_id
        if scope is Scope.HOUSEHOLD_SHARED:
            return actor in {"OWNER", "MEMBER"} and context.household_id == scope_id
        if scope is Scope.APPLICATION:
            return actor == "APPLICATION" and context.actor_id == scope_id
        return False

    @classmethod
    def _require_access(cls, context: AccessContext, scope: Scope, scope_id: str) -> None:
        if not cls._can_access(context, scope, scope_id):
            raise PermissionError("memory scope is not authorized for this actor")

    @staticmethod
    def _can_write(context: AccessContext, scope: Scope, scope_id: str) -> bool:
        actor = context.actor_type.upper()
        if scope is Scope.SYSTEM:
            return actor == "SYSTEM" and context.actor_id == scope_id
        if scope is Scope.OWNER_PRIVATE:
            return actor == "OWNER" and context.actor_id == scope_id
        if scope is Scope.MEMBER_PRIVATE:
            return actor == "MEMBER" and context.actor_id == scope_id
        if scope is Scope.HOUSEHOLD_SHARED:
            return actor in {"OWNER", "MEMBER"} and context.household_id == scope_id
        if scope is Scope.APPLICATION:
            return actor == "APPLICATION" and context.actor_id == scope_id
        return False

    @classmethod
    def _require_write(cls, context: AccessContext, scope: Scope, scope_id: str) -> None:
        if not cls._can_write(context, scope, scope_id):
            raise PermissionError("memory scope is not writable by this actor")

    def write(
        self,
        *,
        context: AccessContext,
        memory_key: str,
        memory_class: MemoryClass,
        scope: Scope,
        scope_id: str,
        value: dict[str, Any],
        source: str,
        source_version: str,
        source_authority: str,
        verification_ref: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(memory_class, MemoryClass) or not isinstance(scope, Scope):
            raise ValueError("known memory class and scope are required")
        self._require_write(context, scope, scope_id)
        authority = source_authority.strip().upper()
        if not memory_key.strip() or not source.strip() or not source_version.strip():
            raise ValueError("memory key and provenance are required")
        if memory_class is MemoryClass.FACT and (authority not in FACT_AUTHORITIES or not verification_ref):
            raise PermissionError("FACT requires owner/verified-policy authority and verification provenance")
        if memory_class is MemoryClass.PROCEDURE and authority not in FACT_AUTHORITIES:
            raise PermissionError("PROCEDURE requires owner or verified-policy authority")
        if authority not in KNOWN_AUTHORITIES:
            raise ValueError("unknown source authority")
        if memory_class is not MemoryClass.INFERENCE and authority in MODEL_AUTHORITIES:
            raise PermissionError("model output may be stored only as INFERENCE")
        record_id, created = str(uuid.uuid4()), time.time()
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False)
        with closing(self.connect()) as db, db:
            previous = db.execute(
                "select record_id from governed_memory where memory_key=? and memory_class=? and scope=? and scope_id=? and temporal_state='CURRENT'",
                (memory_key.strip(), memory_class.value, scope.value, scope_id),
            ).fetchone()
            if previous:
                db.execute("update governed_memory set temporal_state='SUPERSEDED' where record_id=?", (previous["record_id"],))
            db.execute(
                "insert into governed_memory(record_id,memory_key,memory_class,scope,scope_id,temporal_state,value_json,source,source_version,source_authority,verification_ref,created_at,supersedes_id) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record_id, memory_key.strip(), memory_class.value, scope.value, scope_id,
                    TemporalState.CURRENT.value, payload, source.strip(), source_version.strip(), authority,
                    verification_ref, created, previous["record_id"] if previous else None,
                ),
            )
        return self.get(record_id, context=context)

    def mark_historical(self, record_id: str, *, context: AccessContext) -> dict[str, Any]:
        row = self.get(record_id, context=context)
        scope = Scope(row["scope"])
        self._require_write(context, scope, row["scope_id"])
        if row["temporal_state"] != TemporalState.CURRENT.value:
            raise ValueError("only CURRENT memory can become HISTORICAL")
        with closing(self.connect()) as db, db:
            db.execute(
                "update governed_memory set temporal_state=? where record_id=? and temporal_state=?",
                (TemporalState.HISTORICAL.value, record_id, TemporalState.CURRENT.value),
            )
        return self.get(record_id, context=context)

    def get(self, record_id: str, *, context: AccessContext) -> dict[str, Any]:
        with closing(self.connect()) as db, db:
            row = db.execute("select * from governed_memory where record_id=?", (record_id,)).fetchone()
        if not row:
            raise KeyError(record_id)
        self._require_access(context, Scope(row["scope"]), row["scope_id"])
        result = dict(row)
        result["value"] = json.loads(result.pop("value_json"))
        result["content_is_authority"] = False
        return result

    def search(self, query: str, *, context: AccessContext, include_history: bool = False, limit: int = 20) -> list[dict[str, Any]]:
        wanted = _tokens(query)
        if not wanted:
            return []
        with closing(self.connect()) as db, db:
            rows = db.execute("select * from governed_memory order by created_at desc limit 2000").fetchall()
        ranked = []
        for row in rows:
            scope = Scope(row["scope"])
            if not self._can_access(context, scope, row["scope_id"]):
                continue
            if not include_history and row["temporal_state"] != TemporalState.CURRENT.value:
                continue
            value = json.loads(row["value_json"])
            overlap = len(wanted & _tokens(f"{row['memory_key']} {json.dumps(value, ensure_ascii=False)}"))
            if not overlap:
                continue
            authority_weight = 2 if row["source_authority"] in FACT_AUTHORITIES else 1
            temporal_weight = 2 if row["temporal_state"] == TemporalState.CURRENT.value else 0
            result = dict(row)
            result["value"] = value
            result.pop("value_json")
            result["retrieval_score"] = overlap + authority_weight + temporal_weight
            result["content_is_authority"] = False
            ranked.append(result)
        ranked.sort(key=lambda item: (item["retrieval_score"], item["created_at"]), reverse=True)
        return ranked[: max(1, min(int(limit), 100))]

    def ingest_document(
        self,
        *,
        context: AccessContext,
        scope: Scope,
        scope_id: str,
        source: str,
        source_version: str,
        authority_class: str,
        content: str,
        content_sha256: str,
    ) -> str:
        if not isinstance(scope, Scope):
            raise ValueError("known RAG scope is required")
        self._require_write(context, scope, scope_id)
        if not all((source.strip(), source_version.strip(), authority_class.strip(), content.strip(), content_sha256.strip())):
            raise ValueError("RAG source, version, authority, content and digest are required")
        actual_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if content_sha256.lower() != actual_digest:
            raise ValueError("RAG content digest mismatch")
        document_id = str(uuid.uuid4())
        with closing(self.connect()) as db, db:
            db.execute(
                "insert into rag_documents values(?,?,?,?,?,?,?,?,?)",
                (document_id, scope.value, scope_id, source, source_version, authority_class, content, actual_digest, time.time()),
            )
        return document_id

    def retrieve_documents(self, query: str, *, context: AccessContext, limit: int = 10) -> list[dict[str, Any]]:
        wanted = _tokens(query)
        if not wanted:
            return []
        with closing(self.connect()) as db, db:
            rows = db.execute("select * from rag_documents order by created_at desc limit 2000").fetchall()
        ranked = []
        for row in rows:
            if not self._can_access(context, Scope(row["scope"]), row["scope_id"]):
                continue
            overlap = len(wanted & _tokens(row["content"]))
            if not overlap:
                continue
            item = dict(row)
            item["retrieval_score"] = overlap
            item["content_is_authority"] = False
            item["instructions_may_execute"] = False
            ranked.append(item)
        ranked.sort(key=lambda item: (item["retrieval_score"], item["created_at"]), reverse=True)
        return ranked[: max(1, min(int(limit), 50))]
