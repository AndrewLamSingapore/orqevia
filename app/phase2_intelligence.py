"""Phase 2 unified intelligence kernel for isolated candidate qualification.

The kernel is deliberately authority-neutral.  It persists objective continuity,
scoped context, hypotheses, effects, lessons and shadow predictions, but never
executes a tool, changes a role, deploys code or mutates Golden production.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class ObjectiveState(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EpistemicClass(str, Enum):
    OBSERVED = "OBSERVED"
    MEASURED = "MEASURED"
    RETRIEVED = "RETRIEVED"
    CALCULATED = "CALCULATED"
    INFERRED = "INFERRED"
    FORECAST = "FORECAST"
    SCENARIO = "SCENARIO"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


TERMINAL = frozenset({ObjectiveState.COMPLETED, ObjectiveState.CANCELLED})
ROLES = frozenset({"OWNER", "MEMBER", "APPLICATION", "SYSTEM"})
TOKEN = re.compile(r"[a-z0-9_\-\u3400-\u9fff]{2,}", re.I)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def utc(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def require_text(value: Any, field: str, maximum: int = 20_000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be nonempty text of at most {maximum} characters")
    return value.strip()


@dataclass(frozen=True)
class AuthorityEnvelope:
    actor_id: str
    role: str
    permissions: frozenset[str]
    expires_at: float

    def validate(self, permission: str, *, now: float) -> None:
        if self.role not in ROLES or self.expires_at <= now or permission not in self.permissions:
            raise PermissionError("authority denied")


@dataclass(frozen=True)
class CompiledContext:
    objective_id: str
    records: tuple[dict[str, Any], ...]
    contradictions: tuple[dict[str, Any], ...]
    missing: tuple[str, ...]
    digest: str


class Phase2Kernel:
    """One candidate state machine; callers own actual execution authority."""

    def __init__(self, path: str | Path, *, clock=time.time, evidence_verifier=None):
        self.path = str(path)
        self.clock = clock
        self._evidence_verifier = evidence_verifier or (lambda attestation, expected: False)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("pragma foreign_keys=on")
        db.execute("pragma busy_timeout=10000")
        return db

    def _init(self) -> None:
        with closing(self.connect()) as db, db:
            db.executescript(
                """
                create table if not exists phase2_objectives(
                  objective_id text primary key, owner_id text not null, owner_role text not null,
                  objective_version integer not null, objective text not null,
                  success_criteria_json text not null, constraints_json text not null,
                  authority_json text not null, state text not null, checkpoint_json text not null,
                  next_action text not null, created_at real not null, updated_at real not null,
                  completed_at real, record_sha256 text not null
                );
                create table if not exists phase2_events(
                  event_id text primary key, objective_id text not null references phase2_objectives(objective_id),
                  event_type text not null, details_json text not null, created_at real not null,
                  previous_digest text, event_digest text not null
                );
                create table if not exists phase2_event_anchors(
                  objective_id text primary key references phase2_objectives(objective_id),
                  event_count integer not null, head_digest text not null, anchor_sha256 text not null
                );
                create table if not exists phase2_attempts(
                  attempt_id text primary key, objective_id text not null references phase2_objectives(objective_id),
                  fingerprint text not null, evidence_digest text not null, outcome text not null,
                  created_at real not null
                );
                create table if not exists phase2_effects(
                  operation_id text primary key, objective_id text not null references phase2_objectives(objective_id),
                  effect_digest text not null, verified integer not null, receipt_json text not null,
                  created_at real not null, record_sha256 text not null
                );
                create table if not exists phase2_evidence(
                  evidence_id text primary key, objective_id text not null references phase2_objectives(objective_id),
                  evidence_type text not null, source text not null, provenance text not null,
                  verified integer not null, payload_digest text not null, attestation_id text,
                  created_at real not null,
                  record_sha256 text not null
                );
                create table if not exists phase2_attestation_uses(
                  attestation_id text primary key, evidence_id text unique not null,
                  objective_id text not null, used_at real not null
                );
                create table if not exists phase2_evidence_effect_uses(
                  evidence_id text primary key, operation_id text unique not null
                );
                create table if not exists phase2_context(
                  context_id text primary key, context_key text not null, scope text not null, scope_id text not null,
                  epistemic_class text not null, temporal_state text not null, value_json text not null,
                  source text not null, source_version text not null, source_authority text not null,
                  verification_ref text, observed_at real, ingested_at real not null,
                  supersedes_id text, content_sha256 text not null
                );
                create index if not exists phase2_context_lookup on phase2_context(scope,scope_id,context_key);
                create table if not exists phase2_hypotheses(
                  hypothesis_id text primary key, objective_id text not null references phase2_objectives(objective_id),
                  proposition text not null, status text not null, support_json text not null,
                  contradiction_json text not null, test_json text not null, updated_at real not null
                );
                create table if not exists phase2_lessons(
                  lesson_id text primary key, lesson text not null, status text not null,
                  source_experience_json text not null, applicability_json text not null,
                  verification_json text not null, supersedes_id text, created_at real not null
                );
                create table if not exists phase2_predictions(
                  prediction_id text primary key, objective_id text not null references phase2_objectives(objective_id),
                  as_of real not null, target text not null, horizon_end real not null, method text not null,
                  evidence_json text not null, feature_snapshot_json text not null, forecast_json text not null,
                  uncertainty_json text not null, assumptions_json text not null, scenario text not null,
                  baseline_json text not null, calibration_version text not null, status text not null,
                  generation text not null, created_at real not null, record_sha256 text not null,
                  outcome_json text, outcome_observed_at real, score_json text
                );
                """
            )
            effect_columns={row[1] for row in db.execute("pragma table_info(phase2_effects)")}
            if "record_sha256" not in effect_columns:
                db.execute("alter table phase2_effects add column record_sha256 text")
            evidence_columns={row[1] for row in db.execute("pragma table_info(phase2_evidence)")}
            if "attestation_id" not in evidence_columns:
                db.execute("alter table phase2_evidence add column attestation_id text")
            db.execute("create unique index if not exists phase2_evidence_attestation on phase2_evidence(attestation_id) where attestation_id is not null")

    @staticmethod
    def _objective_hash(row: dict[str, Any]) -> str:
        protected = {key: row.get(key) for key in (
            "objective_id", "owner_id", "owner_role", "objective_version", "objective",
            "success_criteria_json", "constraints_json", "authority_json", "state",
            "checkpoint_json", "next_action", "created_at", "updated_at", "completed_at",
        )}
        return digest(protected)

    def _event(self, db: sqlite3.Connection, objective_id: str, event_type: str, details: Any, now: float) -> None:
        prior = db.execute("select event_digest from phase2_events where objective_id=? order by rowid desc limit 1", (objective_id,)).fetchone()
        previous_digest = prior[0] if prior else None
        event_id, details_json = str(uuid.uuid4()), canonical(details)
        protected = {"event_id": event_id, "objective_id": objective_id, "event_type": event_type,
                     "details_json": details_json, "created_at": now, "previous_digest": previous_digest}
        db.execute("insert into phase2_events values(?,?,?,?,?,?,?)", (event_id, objective_id,
                   event_type, details_json, now, previous_digest, digest(protected)))
        head=digest(protected)
        prior_anchor=db.execute("select event_count from phase2_event_anchors where objective_id=?",(objective_id,)).fetchone()
        count=(prior_anchor[0] if prior_anchor else 0)+1
        anchor=digest({"objective_id":objective_id,"event_count":count,"head_digest":head})
        db.execute("insert into phase2_event_anchors values(?,?,?,?) on conflict(objective_id) do update set event_count=excluded.event_count,head_digest=excluded.head_digest,anchor_sha256=excluded.anchor_sha256",
                   (objective_id,count,head,anchor))

    def create_objective(self, *, objective: str, success_criteria: list[str], constraints: list[str],
                         authority: AuthorityEnvelope, now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("objective.create", now=moment)
        text = require_text(objective, "objective")
        criteria = [require_text(item, "success criterion", 1000) for item in success_criteria]
        if not criteria:
            raise ValueError("at least one success criterion is required")
        if len(set(criteria)) != len(criteria):
            raise ValueError("success criteria must be unique")
        oid = str(uuid.uuid4())
        checkpoint = {"facts": [], "unknowns": [], "problem_graph": {}, "plan": [],
                      "completed_work": [], "failed_approaches": [], "artifacts": [],
                      "dependencies": [], "verification": [], "next_admissible_action": "COMPILE_CONTEXT"}
        row = {
            "objective_id": oid, "owner_id": authority.actor_id, "owner_role": authority.role,
            "objective_version": 1, "objective": text, "success_criteria_json": canonical(criteria),
            "constraints_json": canonical(constraints),
            "authority_json": canonical({"actor_id": authority.actor_id, "role": authority.role,
                                          "permissions": sorted(authority.permissions), "expires_at": authority.expires_at}),
            "state": ObjectiveState.ACTIVE.value, "checkpoint_json": canonical(checkpoint),
            "next_action": "COMPILE_CONTEXT", "created_at": moment, "updated_at": moment,
            "completed_at": None,
        }
        row["record_sha256"] = self._objective_hash(row)
        with closing(self.connect()) as db, db:
            db.execute("insert into phase2_objectives values(:objective_id,:owner_id,:owner_role,:objective_version,:objective,:success_criteria_json,:constraints_json,:authority_json,:state,:checkpoint_json,:next_action,:created_at,:updated_at,:completed_at,:record_sha256)", row)
            self._event(db, oid, "OBJECTIVE_CREATED", {"version": 1}, moment)
        return self.get_objective(oid, authority=authority, now=moment)

    def get_objective(self, objective_id: str, *, authority: AuthorityEnvelope, now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("objective.read", now=moment)
        with closing(self.connect()) as db:
            row = db.execute("select * from phase2_objectives where objective_id=?", (objective_id,)).fetchone()
        if row is None:
            raise KeyError(objective_id)
        value = dict(row)
        if value["record_sha256"] != self._objective_hash(value):
            raise ValueError("objective integrity mismatch")
        if authority.role != "SYSTEM" and (value["owner_id"] != authority.actor_id or value["owner_role"] != authority.role):
            raise PermissionError("cross-user objective access denied")
        for key in ("success_criteria_json", "constraints_json", "authority_json", "checkpoint_json"):
            value[key[:-5]] = json.loads(value.pop(key))
        return value

    def checkpoint(self, objective_id: str, *, authority: AuthorityEnvelope, expected_version: int,
                   updates: dict[str, Any], next_action: str, now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("objective.update", now=moment)
        current = self.get_objective(objective_id, authority=authority, now=moment)
        if current["state"] != ObjectiveState.ACTIVE.value or current["objective_version"] != expected_version:
            raise ValueError("stale or non-active objective checkpoint")
        allowed = set(current["checkpoint"])
        if set(updates) - allowed:
            raise ValueError("unknown checkpoint field")
        checkpoint = {**current["checkpoint"], **updates}
        new_version = expected_version + 1
        raw = {
            **{key: current[key] for key in ("objective_id", "owner_id", "owner_role", "objective", "created_at")},
            "objective_version": new_version,
            "success_criteria_json": canonical(current["success_criteria"]),
            "constraints_json": canonical(current["constraints"]),
            "authority_json": canonical(current["authority"]),
            "state": current["state"], "checkpoint_json": canonical(checkpoint),
            "next_action": require_text(next_action, "next action", 200), "updated_at": moment,
            "completed_at": current["completed_at"],
        }
        raw["record_sha256"] = self._objective_hash(raw)
        with closing(self.connect()) as db, db:
            changed = db.execute("""update phase2_objectives set objective_version=?,checkpoint_json=?,next_action=?,updated_at=?,record_sha256=?
                where objective_id=? and objective_version=? and state='ACTIVE'""",
                (new_version, raw["checkpoint_json"], raw["next_action"], moment, raw["record_sha256"], objective_id, expected_version)).rowcount
            if changed != 1:
                raise ValueError("concurrent objective update")
            self._event(db, objective_id, "CHECKPOINT", {"version": new_version, "next_action": next_action}, moment)
        return self.get_objective(objective_id, authority=authority, now=moment)

    def control(self, objective_id: str, action: str, *, authority: AuthorityEnvelope,
                now: float | None = None, verification_refs: dict[str, str] | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("objective.control", now=moment)
        current = self.get_objective(objective_id, authority=authority, now=moment)
        action = action.upper()
        transitions = {
            "PAUSE": ({ObjectiveState.ACTIVE}, ObjectiveState.PAUSED),
            "RESUME": ({ObjectiveState.PAUSED, ObjectiveState.BLOCKED}, ObjectiveState.ACTIVE),
            "CANCEL": ({ObjectiveState.ACTIVE, ObjectiveState.PAUSED, ObjectiveState.BLOCKED}, ObjectiveState.CANCELLED),
            "STOP": ({ObjectiveState.ACTIVE, ObjectiveState.PAUSED, ObjectiveState.BLOCKED}, ObjectiveState.CANCELLED),
            "COMPLETE": ({ObjectiveState.ACTIVE}, ObjectiveState.COMPLETED),
        }
        if action not in transitions:
            raise ValueError("unknown control action")
        allowed, target = transitions[action]
        if ObjectiveState(current["state"]) not in allowed:
            raise ValueError("invalid objective transition")
        refs = dict(verification_refs or {})
        if target is ObjectiveState.COMPLETED:
            criteria = current["success_criteria"]
            if set(refs) != set(criteria):
                raise ValueError("completion requires evidence for every success criterion")
            if len(set(refs.values())) != len(criteria):
                raise ValueError("each success criterion requires distinct evidence")
            with closing(self.connect()) as db:
                rows = db.execute(
                    f"select * from phase2_evidence where objective_id=? and verified=1 and evidence_id in ({','.join('?' for _ in refs)})",
                    (objective_id, *refs.values()),
                ).fetchall() if refs else []
            valid_ids=set()
            for row in rows:
                value=dict(row); expected=value.pop("record_sha256")
                if digest(value)==expected: valid_ids.add(row["evidence_id"])
            if valid_ids != set(refs.values()):
                raise ValueError("completion evidence is unverified or belongs to another objective")
            current["checkpoint"]["verification"] = [
                {"criterion": criterion, "evidence_id": refs[criterion]} for criterion in criteria
            ]
        raw = {
            **{key: current[key] for key in ("objective_id", "owner_id", "owner_role", "objective_version", "objective", "created_at")},
            "success_criteria_json": canonical(current["success_criteria"]), "constraints_json": canonical(current["constraints"]),
            "authority_json": canonical(current["authority"]), "state": target.value,
            "checkpoint_json": canonical(current["checkpoint"]),
            "next_action": "NONE" if target in TERMINAL else "REVALIDATE_AND_CONTINUE",
            "updated_at": moment, "completed_at": moment if target in TERMINAL else None,
        }
        raw["record_sha256"] = self._objective_hash(raw)
        with closing(self.connect()) as db, db:
            db.execute("update phase2_objectives set state=?,checkpoint_json=?,next_action=?,updated_at=?,completed_at=?,record_sha256=? where objective_id=?",
                       (raw["state"], raw["checkpoint_json"], raw["next_action"], moment,
                        raw["completed_at"], raw["record_sha256"], objective_id))
            self._event(db, objective_id, action, {"verification_refs": refs}, moment)
        return self.get_objective(objective_id, authority=authority, now=moment)

    def record_attempt(self, objective_id: str, *, authority: AuthorityEnvelope, strategy: Any,
                       evidence: Any, outcome: str, now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("objective.update", now=moment)
        current = self.get_objective(objective_id, authority=authority, now=moment)
        if current["state"] != ObjectiveState.ACTIVE.value:
            raise ValueError("attempt denied for non-active objective")
        fingerprint, evidence_digest = digest(strategy), digest(evidence)
        with closing(self.connect()) as db, db:
            repeats = db.execute("select count(*) from phase2_attempts where objective_id=? and fingerprint=? and evidence_digest=?",
                                 (objective_id, fingerprint, evidence_digest)).fetchone()[0]
            db.execute("insert into phase2_attempts values(?,?,?,?,?,?)", (str(uuid.uuid4()), objective_id,
                       fingerprint, evidence_digest, require_text(outcome, "outcome", 2000), moment))
            self._event(db, objective_id, "ATTEMPT", {"fingerprint": fingerprint, "repeat": repeats + 1}, moment)
        return {"repeat_count": repeats + 1, "disposition": "REPLAN" if repeats >= 1 else "CONTINUE",
                "reason": "materially_equivalent_attempt_without_new_evidence" if repeats >= 1 else "new_information"}

    def record_effect(self, objective_id: str, *, authority: AuthorityEnvelope, operation_id: str,
                      effect: Any, verified: bool, receipt: Any, now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("effect.record", now=moment)
        current = self.get_objective(objective_id, authority=authority, now=moment)
        if current["state"] != ObjectiveState.ACTIVE.value:
            raise ValueError("effect denied for non-active objective")
        if verified:
            evidence_id = receipt.get("evidence_id") if isinstance(receipt, dict) else None
            with closing(self.connect()) as probe:
                evidence = probe.execute("select * from phase2_evidence where evidence_id=? and objective_id=? and verified=1",
                                         (evidence_id, objective_id)).fetchone()
                prior_effect = probe.execute(
                    "select * from phase2_effects where json_extract(receipt_json,'$.evidence_id')=?",
                    (evidence_id,)).fetchone()
            evidence_value=dict(evidence) if evidence else None
            evidence_hash=evidence_value.pop("record_sha256",None) if evidence_value else None
            if evidence is None or digest(evidence_value)!=evidence_hash or evidence["payload_digest"] != digest(effect):
                raise ValueError("verified effect requires bound verified evidence")
            if prior_effect:
                prior_value=dict(prior_effect); prior_hash=prior_value.pop("record_sha256",None)
                if digest(prior_value)!=prior_hash:
                    raise ValueError("effect integrity mismatch")
            if prior_effect and prior_effect["operation_id"] != operation_id:
                raise ValueError("verified effect evidence replay denied")
        with closing(self.connect()) as db, db:
            existing = db.execute("select * from phase2_effects where operation_id=?", (operation_id,)).fetchone()
            if existing:
                existing_value=dict(existing); existing_hash=existing_value.pop("record_sha256",None)
                if digest(existing_value)!=existing_hash:
                    raise ValueError("effect integrity mismatch")
                if existing["objective_id"] != objective_id or existing["effect_digest"] != digest(effect):
                    raise ValueError("idempotency key collision")
                return {**dict(existing), "duplicate": True}
            if verified:
                try:
                    db.execute("insert into phase2_evidence_effect_uses values(?,?)",(evidence_id,operation_id))
                except sqlite3.IntegrityError as error:
                    raise ValueError("verified effect evidence replay denied") from error
            row={"operation_id":operation_id,"objective_id":objective_id,"effect_digest":digest(effect),
                 "verified":int(bool(verified)),"receipt_json":canonical(receipt),"created_at":moment}
            row["record_sha256"]=digest(row)
            db.execute("insert into phase2_effects(operation_id,objective_id,effect_digest,verified,receipt_json,created_at,record_sha256) values(:operation_id,:objective_id,:effect_digest,:verified,:receipt_json,:created_at,:record_sha256)",row)
        return {"operation_id": operation_id, "verified": bool(verified), "duplicate": False}

    def record_evidence(self, objective_id: str, *, authority: AuthorityEnvelope, evidence_type: str,
                        source: str, provenance: str, payload: Any, verification: dict[str, Any] | None,
                        evidence_id: str | None = None, now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("objective.update", now=moment)
        current = self.get_objective(objective_id, authority=authority, now=moment)
        if current["state"] != ObjectiveState.ACTIVE.value:
            raise ValueError("evidence denied for non-active objective")
        eid = evidence_id or str(uuid.uuid4())
        verification = dict(verification or {})
        attestation_id=verification.get("attestation_id")
        expires_at=verification.get("expires_at")
        body={"attestation_id":attestation_id,"expires_at":expires_at,"objective_id":objective_id,
              "source":source,"provenance":provenance,"payload_digest":digest(payload)}
        verified=(bool(verification) and isinstance(attestation_id,str) and bool(attestation_id.strip()) and
                  isinstance(expires_at,(int,float)) and expires_at>=moment and
                  self._evidence_verifier(verification,body) is True)
        if verification and not verified: raise ValueError("evidence verification is not governed")
        if verified:
            with closing(self.connect()) as probe:
                if probe.execute("select evidence_id from phase2_evidence where attestation_id=?",(attestation_id,)).fetchone():
                    raise ValueError("evidence attestation replay denied")
        row={"evidence_id":eid,"objective_id":objective_id,
             "evidence_type":require_text(evidence_type,"evidence type",100),
             "source":require_text(source,"evidence source",500),
             "provenance":require_text(provenance,"evidence provenance",1000),
             "verified":int(verified),"payload_digest":digest(payload),"attestation_id":attestation_id if verified else None,"created_at":moment}
        row["record_sha256"]=digest(row)
        with closing(self.connect()) as db, db:
            if verified:
                try:
                    db.execute("insert into phase2_attestation_uses values(?,?,?,?)",(verification["attestation_id"],eid,objective_id,moment))
                except sqlite3.IntegrityError as error:
                    raise ValueError("evidence attestation replay denied") from error
            db.execute("insert into phase2_evidence(evidence_id,objective_id,evidence_type,source,provenance,verified,payload_digest,attestation_id,created_at,record_sha256) values(:evidence_id,:objective_id,:evidence_type,:source,:provenance,:verified,:payload_digest,:attestation_id,:created_at,:record_sha256)",row)
            self._event(db, objective_id, "EVIDENCE_RECORDED", {"evidence_id":eid,"verified":bool(verified)}, moment)
        return {"evidence_id":eid,"verified":bool(verified),"payload_digest":row["payload_digest"],"record_sha256":row["record_sha256"]}

    def ingest_context(self, *, authority: AuthorityEnvelope, context_key: str, scope: str, scope_id: str, epistemic_class: str,
                       temporal_state: str, value: Any, source: str, source_version: str,
                       source_authority: str, verification_ref: str | None = None,
                       observed_at: float | None = None, supersedes_id: str | None = None,
                       now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("context.write", now=moment)
        EpistemicClass(epistemic_class)
        if scope not in {"OWNER_PRIVATE", "MEMBER_PRIVATE", "APPLICATION", "SYSTEM", "GLOBAL"}:
            raise ValueError("invalid context scope")
        if scope == "OWNER_PRIVATE" and (authority.role != "OWNER" or scope_id != authority.actor_id):
            raise PermissionError("owner-private context scope denied")
        if scope == "MEMBER_PRIVATE" and (authority.role != "MEMBER" or scope_id != authority.actor_id):
            raise PermissionError("member-private context scope denied")
        if scope in {"SYSTEM", "GLOBAL"} and authority.role != "SYSTEM":
            raise PermissionError("system context scope denied")
        if epistemic_class in {"OBSERVED", "MEASURED", "RETRIEVED", "CALCULATED"} and not verification_ref:
            raise ValueError("authoritative context class requires verification reference")
        if source_authority in {"MODEL", "MODEL_OUTPUT"} and epistemic_class in {"OBSERVED", "MEASURED", "RETRIEVED", "CALCULATED"}:
            raise ValueError("model content cannot become authoritative context")
        cid = str(uuid.uuid4())
        content_hash = digest({"key": context_key, "scope":scope, "scope_id":scope_id,
                               "epistemic_class":epistemic_class,"temporal_state":temporal_state,
                               "value": value, "source": source, "version": source_version,
                               "authority": source_authority,"verification_ref":verification_ref,
                               "observed_at":observed_at})
        with closing(self.connect()) as db, db:
            if supersedes_id:
                previous = db.execute("select context_id,scope,scope_id from phase2_context where context_id=?", (supersedes_id,)).fetchone()
                if previous is None or previous["scope"] != scope or previous["scope_id"] != scope_id:
                    raise ValueError("invalid context supersession")
            db.execute("insert into phase2_context values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (cid,
                require_text(context_key, "context key", 300), scope, require_text(scope_id, "scope id", 300),
                epistemic_class, temporal_state, canonical(value), require_text(source, "source", 1000),
                require_text(source_version, "source version", 300), require_text(source_authority, "source authority", 100),
                verification_ref, observed_at, moment, supersedes_id, content_hash))
        return {"context_id": cid, "content_sha256": content_hash, "authoritative": source_authority not in {"MODEL", "MODEL_OUTPUT"}}

    @staticmethod
    def _scope_allowed(row: sqlite3.Row, authority: AuthorityEnvelope) -> bool:
        scope = row["scope"]
        return scope in {"SYSTEM", "GLOBAL"} or (scope == "OWNER_PRIVATE" and authority.role == "OWNER" and row["scope_id"] == authority.actor_id) or (scope == "MEMBER_PRIVATE" and authority.role == "MEMBER" and row["scope_id"] == authority.actor_id) or (scope == "APPLICATION" and authority.role == "APPLICATION" and row["scope_id"] == authority.actor_id)

    def compile_context(self, objective_id: str, *, authority: AuthorityEnvelope, now: float | None = None,
                        max_items: int = 24, max_age_seconds: float = 86_400) -> CompiledContext:
        moment = self.clock() if now is None else float(now)
        objective = self.get_objective(objective_id, authority=authority, now=moment)
        words = set(TOKEN.findall(objective["objective"].casefold()))
        with closing(self.connect()) as db:
            rows = db.execute("select * from phase2_context order by ingested_at desc").fetchall()
        eligible = []
        for row in rows:
            expected = digest({"key": row["context_key"], "scope":row["scope"], "scope_id":row["scope_id"],
                               "epistemic_class":row["epistemic_class"],"temporal_state":row["temporal_state"],
                               "value": json.loads(row["value_json"]), "source": row["source"],
                               "version": row["source_version"], "authority": row["source_authority"],
                               "verification_ref":row["verification_ref"],"observed_at":row["observed_at"]})
            if expected != row["content_sha256"]:
                raise ValueError("context integrity mismatch")
            if self._scope_allowed(row, authority):
                eligible.append(row)
        superseded = {row["supersedes_id"] for row in eligible if row["supersedes_id"]}
        eligible = [row for row in eligible if row["context_id"] not in superseded and row["temporal_state"] not in {"SUPERSEDED", "RETIRED"}]
        def rank(row: sqlite3.Row) -> tuple[int, int, float]:
            content = row["context_key"] + " " + row["value_json"]
            relevance = len(words & set(TOKEN.findall(content.casefold())))
            verified = 1 if row["verification_ref"] else 0
            return relevance, verified, row["observed_at"] or row["ingested_at"]
        chosen = sorted(eligible, key=rank, reverse=True)[:max_items]
        records = []
        missing = []
        for row in chosen:
            value = dict(row)
            value["value"] = json.loads(value.pop("value_json"))
            value["retrieved_content_is_data"] = True
            value["grants_authority"] = False
            records.append(value)
            observed = value["observed_at"]
            if value["temporal_state"] == "CURRENT" and (observed is None or observed > moment or moment - observed > max_age_seconds):
                missing.append("freshness")
        by_key: dict[str, list[dict[str, Any]]] = {}
        for row in records:
            if row["temporal_state"] == "CURRENT":
                by_key.setdefault(row["context_key"], []).append(row)
        contradictions = []
        for key, values in by_key.items():
            unique = {canonical(row["value"]) for row in values}
            if len(unique) > 1:
                contradictions.append({"context_key": key, "context_ids": sorted(row["context_id"] for row in values),
                                       "status": "UNRESOLVED"})
        if not records:
            missing.append("relevant_context")
        if contradictions:
            missing.append("contradiction_resolution")
        payload = {"objective_id": objective_id, "records": records, "contradictions": contradictions,
                   "missing": sorted(set(missing))}
        return CompiledContext(objective_id, tuple(records), tuple(contradictions), tuple(payload["missing"]), digest(payload))

    def add_hypothesis(self, objective_id: str, *, authority: AuthorityEnvelope, proposition: str,
                       test: dict[str, Any], now: float | None = None) -> str:
        moment = self.clock() if now is None else float(now)
        authority.validate("objective.update", now=moment)
        self.get_objective(objective_id, authority=authority, now=moment)
        hid = str(uuid.uuid4())
        with closing(self.connect()) as db, db:
            db.execute("insert into phase2_hypotheses values(?,?,?,?,?,?,?,?)", (hid, objective_id,
                       require_text(proposition, "hypothesis", 4000), "OPEN", "[]", "[]", canonical(test), moment))
        return hid

    def evaluate_hypothesis(self, hypothesis_id: str, *, support: list[str], contradictions: list[str],
                            authority: AuthorityEnvelope, now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("objective.update", now=moment)
        with closing(self.connect()) as db, db:
            row = db.execute("select * from phase2_hypotheses where hypothesis_id=?", (hypothesis_id,)).fetchone()
            if row is None:
                raise KeyError(hypothesis_id)
            self.get_objective(row["objective_id"], authority=authority, now=moment)
            status = "REJECTED" if contradictions else "SUPPORTED" if support else "UNKNOWN"
            db.execute("update phase2_hypotheses set status=?,support_json=?,contradiction_json=?,updated_at=? where hypothesis_id=?",
                       (status, canonical(support), canonical(contradictions), moment, hypothesis_id))
        return {"hypothesis_id": hypothesis_id, "status": status, "support": support, "contradictions": contradictions}

    def qualify_lesson(self, *, authority: AuthorityEnvelope, lesson: str, outcomes: list[dict[str, Any]], applicability: list[str],
                       counterexamples_checked: bool, supersedes_id: str | None = None,
                       now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("lesson.qualify", now=moment)
        reasons = []
        if len(outcomes) < 3: reasons.append("insufficient_repetition")
        if not outcomes or not all(item.get("verified") and item.get("provenance") for item in outcomes): reasons.append("unverified_outcome")
        if not applicability: reasons.append("missing_applicability")
        if not counterexamples_checked: reasons.append("counterexamples_not_checked")
        status = "QUALIFIED" if not reasons else "HYPOTHESIS"
        lid = str(uuid.uuid4())
        with closing(self.connect()) as db, db:
            db.execute("insert into phase2_lessons values(?,?,?,?,?,?,?,?)", (lid, require_text(lesson, "lesson", 4000),
                       status, canonical(outcomes), canonical(applicability), canonical({"reasons": reasons}),
                       supersedes_id, moment))
        return {"lesson_id": lid, "status": status, "reasons": reasons, "grants_authority": False}

    def create_prediction(self, objective_id: str, *, authority: AuthorityEnvelope, as_of: float,
                          target: str, horizon_end: float, method: str, evidence: list[dict[str, Any]],
                          feature_snapshot: dict[str, Any], forecast: dict[str, Any], uncertainty: dict[str, Any],
                          assumptions: list[str], scenario: str, baseline: dict[str, Any], calibration_version: str,
                          generation: str = "PHASE2_CANDIDATE", now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("prediction.create", now=moment)
        self.get_objective(objective_id, authority=authority, now=moment)
        if horizon_end <= as_of:
            raise ValueError("prediction horizon must follow as-of time")
        if any(not item.get("evidence_id") or item.get("observed_at", math.inf) > as_of for item in evidence):
            raise ValueError("future-data leakage or unbound evidence")
        if not baseline:
            raise ValueError("prediction requires a simple baseline")
        pid = str(uuid.uuid4())
        row = {"prediction_id": pid, "objective_id": objective_id, "as_of": float(as_of),
               "target": require_text(target, "target", 1000), "horizon_end": float(horizon_end),
               "method": require_text(method, "method", 300), "evidence_json": canonical(evidence),
               "feature_snapshot_json": canonical(feature_snapshot), "forecast_json": canonical(forecast),
               "uncertainty_json": canonical(uncertainty), "assumptions_json": canonical(assumptions),
               "scenario": require_text(scenario, "scenario", 100), "baseline_json": canonical(baseline),
               "calibration_version": require_text(calibration_version, "calibration version", 100),
               "status": "SHADOW_OPEN", "generation": generation, "created_at": moment}
        row["record_sha256"] = digest(row)
        with closing(self.connect()) as db, db:
            db.execute("""insert into phase2_predictions(prediction_id,objective_id,as_of,target,horizon_end,method,evidence_json,
                feature_snapshot_json,forecast_json,uncertainty_json,assumptions_json,scenario,baseline_json,
                calibration_version,status,generation,created_at,record_sha256) values(:prediction_id,:objective_id,:as_of,
                :target,:horizon_end,:method,:evidence_json,:feature_snapshot_json,:forecast_json,:uncertainty_json,
                :assumptions_json,:scenario,:baseline_json,:calibration_version,:status,:generation,:created_at,:record_sha256)""", row)
        return {"prediction_id": pid, "status": "SHADOW_OPEN", "record_sha256": row["record_sha256"],
                "grants_authority": False}

    def resolve_prediction(self, prediction_id: str, *, outcome: dict[str, Any], observed_at: float,
                           score: dict[str, Any], authority: AuthorityEnvelope, now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        authority.validate("prediction.resolve", now=moment)
        with closing(self.connect()) as db, db:
            row = db.execute("select * from phase2_predictions where prediction_id=?", (prediction_id,)).fetchone()
            if row is None: raise KeyError(prediction_id)
            self.get_objective(row["objective_id"], authority=authority, now=moment)
            protected = {key: row[key] for key in (
                "prediction_id", "objective_id", "as_of", "target", "horizon_end", "method",
                "evidence_json", "feature_snapshot_json", "forecast_json", "uncertainty_json",
                "assumptions_json", "scenario", "baseline_json", "calibration_version", "status",
                "generation", "created_at",
            )}
            if digest(protected) != row["record_sha256"]:
                raise ValueError("prediction integrity mismatch")
            if row["status"] != "SHADOW_OPEN" or observed_at < row["horizon_end"]:
                raise ValueError("prediction is immutable or horizon has not resolved")
            db.execute("update phase2_predictions set status='SHADOW_RESOLVED',outcome_json=?,outcome_observed_at=?,score_json=? where prediction_id=?",
                       (canonical(outcome), observed_at, canonical(score), prediction_id))
        return {"prediction_id": prediction_id, "status": "SHADOW_RESOLVED", "outcome": outcome, "score": score}

    def snapshot(self, objective_id: str, *, authority: AuthorityEnvelope, now: float | None = None) -> dict[str, Any]:
        moment = self.clock() if now is None else float(now)
        objective = self.get_objective(objective_id, authority=authority, now=moment)
        with closing(self.connect()) as db:
            events = [dict(row) for row in db.execute("select * from phase2_events where objective_id=? order by rowid", (objective_id,))]
            effects = [dict(row) for row in db.execute("select * from phase2_effects where objective_id=? order by created_at,operation_id", (objective_id,))]
            evidence = [dict(row) for row in db.execute("select * from phase2_evidence where objective_id=? order by created_at,evidence_id", (objective_id,))]
            predictions = [dict(row) for row in db.execute("select prediction_id,status,record_sha256 from phase2_predictions where objective_id=? order by created_at,prediction_id", (objective_id,))]
            anchor_row = db.execute("select * from phase2_event_anchors where objective_id=?",(objective_id,)).fetchone()
        previous = None
        for event in events:
            protected = {key: event[key] for key in ("event_id", "objective_id", "event_type", "details_json", "created_at", "previous_digest")}
            if event["previous_digest"] != previous or event["event_digest"] != digest(protected):
                raise ValueError("objective event integrity mismatch")
            previous = event["event_digest"]
        for effect in effects:
            protected=dict(effect); expected=protected.pop("record_sha256",None)
            if digest(protected)!=expected:
                raise ValueError("effect integrity mismatch")
        anchor=dict(anchor_row) if anchor_row else None
        expected_anchor=digest({"objective_id":objective_id,"event_count":len(events),"head_digest":previous})
        if not anchor or anchor["event_count"]!=len(events) or anchor["head_digest"]!=previous or anchor["anchor_sha256"]!=expected_anchor:
            raise ValueError("objective event anchor mismatch")
        value = {"schema_version": "jarvis.phase2.objective-snapshot.v1", "objective": objective,
                 "events": events, "effects": effects, "evidence": evidence, "predictions": predictions,
                 "snapshot_at": utc(moment), "authority": "SYSTEM_RECORD"}
        value["snapshot_sha256"] = digest(value)
        return value
