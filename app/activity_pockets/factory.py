"""Durable pocket coordination over existing Library, Academy, Tools and executor."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
from uuid import uuid4

from ..academy import PersistentAcademy
from ..agent_registry import AgentLibrary, RegistryError
from ..connector_sdk import ConnectorRegistry, Sink
from ..workflow_engine import Task, execute
from .contracts import (PocketManifest, ExecutionEvent, CoachingProposal, SkillManifest,
                        PromotionDecision, RecoveryRecord, ToolManifest)
from .store import canonical, digest
from .web import HTTPSFetcher, QualityError, RetrievalError, extract


TERMINAL = frozenset({"COMPLETED", "CANCELLED", "FAILED", "BUDGET_EXHAUSTED", "RETIRED"})


@dataclass(frozen=True)
class Principal:
    owner: str
    actor: str
    role: str = "MEMBER"


class Factory:
    def __init__(self, store, qualifications, sources=(), *, fetcher=None, clock=time.time):
        self.store, self.clock = store, clock
        self.library = AgentLibrary(store, qualifications)
        self.academy = PersistentAcademy(store)
        self.sources = {source.id: source for source in sources}
        if len(self.sources) != len(sources):
            raise ValueError("duplicate trusted source identity")
        self.fetcher = fetcher or HTTPSFetcher()

    @staticmethod
    def _stopped(db, owner):
        row = db.execute("SELECT stopped FROM pocket_control WHERE owner=?", (owner,)).fetchone()
        return bool(row and row[0])

    def _row(self, db, pocket_id, principal):
        row = db.execute("SELECT * FROM pockets WHERE id=? AND owner=?", (pocket_id, principal.owner)).fetchone()
        if row is None:
            raise KeyError("pocket unavailable in this ownership scope")
        return dict(row)

    def _scope(self, manifest, principal):
        if manifest.owner != principal.owner:
            raise PermissionError("pocket owner must match authenticated owner")
        for source_id in manifest.source_ids:
            source = self.sources.get(source_id)
            if source is None or principal.owner not in source.owners:
                raise PermissionError("source unavailable to this owner")
        for agent in manifest.agent_ids:
            try:
                definition = self.library.manifest(agent, principal.owner)
            except RegistryError:
                raise PermissionError("canonical specialist unavailable") from None
            if not set(manifest.permitted_operations) <= set(definition.tool_ids):
                raise PermissionError("tool scope exceeds canonical agent eligibility")

    def _qualified(self, db, manifest):
        for agent in manifest.agent_ids:
            _, evidence = self.library.qualified(agent, manifest.owner,
                now=datetime.fromtimestamp(self.clock(), timezone.utc))
            self.store.put(db, "qualification", evidence, manifest.id)

    def create(self, manifest, principal, idempotency_key):
        manifest = PocketManifest.model_validate(manifest)
        self._scope(manifest, principal)
        self._key(idempotency_key)
        supplied = manifest.model_fields_set
        request = manifest.model_dump(mode="json")
        for field in ("id", "created_at", "not_before"):
            if field not in supplied:
                request.pop(field, None)
        request_digest = digest(request)
        with self.store.transaction() as db:
            prior = db.execute("SELECT * FROM pockets WHERE owner=? AND idempotency_key=?",
                               (principal.owner, idempotency_key)).fetchone()
            if prior:
                if prior["request_digest"] != request_digest:
                    raise ValueError("idempotency key already binds a different manifest")
                return self._snapshot(db, dict(prior))
            self.library.ensure_builtin(db, principal.owner)
            skill = self.library.skill(db, principal.owner, manifest.skill_version)
            self._admit_skill(db, skill)
            if (not set(manifest.agent_ids) <= set(skill.agent_ids)
                    or set(skill.tool_ids) != set(manifest.permitted_operations)):
                raise PermissionError("pinned skill and permitted team/tool scope differ")
            self._qualified(db, manifest)
            now = self.clock()
            db.execute("INSERT INTO pockets(id,owner,manifest,state,version,due,updated,idempotency_key,request_digest) "
                       "VALUES(?,?,?,'READY',?,?,?,?,?)", (manifest.id, manifest.owner, canonical(manifest),
                       manifest.skill_version, max(now, manifest.not_before.timestamp()), now, idempotency_key, request_digest))
            self.store.event(db, manifest.id, manifest.owner, principal.actor, "pocket.created",
                             {"manifest_sha256": digest(manifest), "skill_version": manifest.skill_version})
            return self._snapshot(db, self._row(db, manifest.id, principal))

    @staticmethod
    def _key(value):
        if not isinstance(value, str) or not 1 <= len(value) <= 128 or not value.strip():
            raise ValueError("bounded idempotency key required")

    def _snapshot(self, db, row):
        row = {key: value for key, value in row.items() if key not in {"lease", "lease_until", "idempotency_key", "request_digest"}}
        row["manifest"] = json.loads(row["manifest"])
        row["outputs"] = self.store.records(db, "output", row["owner"], row["id"])
        row["coaching_proposals"] = self.store.records(db, "coaching_proposal", row["owner"], row["id"])
        row["evaluations"] = self.store.records(db, "evaluation", row["owner"], row["id"])
        row["decisions"] = self.store.records(db, "promotion", row["owner"], row["id"])
        row["recovery"] = self.store.records(db, "recovery", row["owner"], row["id"])
        row["qualification_evidence"] = self.store.records(db, "qualification", row["owner"], row["id"])
        row["verification_scope"] = self.store.origin
        return row

    def get(self, pocket_id, principal):
        with self.store.connect() as db:
            return self._snapshot(db, self._row(db, pocket_id, principal))

    def list(self, principal):
        with self.store.connect() as db:
            return [self._snapshot(db, dict(row)) for row in db.execute(
                "SELECT * FROM pockets WHERE owner=? ORDER BY updated DESC LIMIT 100", (principal.owner,))]

    def events(self, pocket_id, principal):
        with self.store.connect() as db:
            self._row(db, pocket_id, principal)
            return [{"sequence": row["sequence"], "sha256": row["sha256"],
                     "previous_sha256": row["previous_sha256"], "event": json.loads(row["body"])}
                    for row in db.execute("SELECT * FROM pocket_events WHERE pocket_id=? AND owner=? ORDER BY sequence",
                                          (pocket_id, principal.owner))]

    def transition(self, pocket_id, principal, action):
        with self.store.transaction() as db:
            row = self._row(db, pocket_id, principal)
            allowed = {"pause": ({"READY", "RUNNING"}, "PAUSED"),
                       "resume": ({"PAUSED"}, "READY"),
                       "cancel": ({"READY", "RUNNING", "PAUSED"}, "CANCELLED"),
                       "retire": (TERMINAL - {"RETIRED"}, "RETIRED")}
            if action not in allowed or row["state"] not in allowed[action][0]:
                raise ValueError("invalid lifecycle transition")
            if action == "resume":
                manifest = PocketManifest.model_validate_json(row["manifest"])
                self._scope(manifest, principal)
                self._qualified(db, manifest)
                if row["reason"] == "QUALITY_FAILURE":
                    raise PermissionError("quality pause requires a validated owner promotion or rollback")
            state = allowed[action][1]
            db.execute("UPDATE pockets SET state=?,reason=?,updated=? WHERE id=?",
                       (state, "OWNER_" + action.upper(), self.clock(), pocket_id))
            self.store.event(db, pocket_id, row["owner"], principal.actor, "pocket." + action)
        return self.get(pocket_id, principal)

    def _pages(self, manifest):
        return [(self.sources[source_id], url) for source_id in manifest.source_ids for url in self.sources[source_id].urls]

    def _exhausted(self, row, budget):
        return (row["attempts"] >= budget.max_attempts or row["bytes"] >= budget.max_bytes
                or row["records"] >= budget.max_records or row["seconds"] >= budget.max_wall_seconds
                or row["cost"] > budget.max_cost_usd)

    def _admit_skill(self, db, skill):
        if skill.skill_id != "web.structured-extraction":
            raise PermissionError("this pocket requires the declared extraction skill")
        if skill.version == "1.0.0":
            self.library.ensure_builtin(db, skill.owner)
        candidates = db.execute("SELECT kind,id FROM pocket_records WHERE owner=? AND kind IN ('skill_validation','evaluation') "
            "AND json_extract(body,'$.candidate_sha256')=?", (skill.owner, digest(skill.artifact))).fetchall()
        for candidate in candidates:
            record = self.store.get(db, candidate["kind"], candidate["id"], skill.owner)
            if (record["passed"] and record["provenance"]["source_revision"] == self.store.revision
                    and record["suite_sha256"] == self.academy.suite_digest()):
                return
        raise PermissionError("skill requires current independent scoped validation")

    def run_one(self, pocket_id, principal, idempotency_key):
        self._key(idempotency_key)
        with self.store.transaction() as db:
            row = self._row(db, pocket_id, principal)
            prior = db.execute("SELECT status,report FROM pocket_runs WHERE pocket_id=? AND idempotency_key=?",
                               (pocket_id, idempotency_key)).fetchone()
            if prior:
                return json.loads(prior["report"])
            if self._stopped(db, principal.owner):
                return {"status": "EMERGENCY_STOPPED"}
            if row["state"] != "READY" or row["lease"] or row["due"] > self.clock():
                return {"status": row["state"], "reason": "NOT_DUE_OR_ALREADY_CLAIMED"}
            manifest = PocketManifest.model_validate_json(row["manifest"])
            if not self.store.verify_events(db):
                raise PermissionError("audit evidence integrity failed")
            try:
                self._scope(manifest, principal)
                self._qualified(db, manifest)
            except PermissionError:
                db.execute("UPDATE pockets SET state='PAUSED',reason='QUALIFICATION_OR_SCOPE_REQUIRED' WHERE id=?", (pocket_id,))
                self.store.event(db, pocket_id, row["owner"], "factory-worker", "execution.denied")
                return {"status": "PAUSED", "reason": "QUALIFICATION_OR_SCOPE_REQUIRED"}
            if self._exhausted(row, manifest.budget):
                db.execute("UPDATE pockets SET state='BUDGET_EXHAUSTED',reason='RESOURCE_BUDGET' WHERE id=?", (pocket_id,))
                self.store.event(db, pocket_id, row["owner"], "factory-worker", "budget.exhausted")
                return {"status": "BUDGET_EXHAUSTED"}
            pages = self._pages(manifest)
            if row["cursor"] >= len(pages):
                db.execute("UPDATE pockets SET state='COMPLETED',reason='' WHERE id=?", (pocket_id,))
                self.store.event(db, pocket_id, principal.owner, "factory-worker", "pocket.completed",
                                 {"reason": "All sources already processed; original output versions retained."})
                return {"status": "COMPLETED"}
            source, url = pages[row["cursor"]]
            slot = db.execute("SELECT * FROM source_access WHERE source_id=?", (source.origin,)).fetchone()
            next_at = max(slot["next_at"], slot["lease_until"] or 0) if slot else 0
            if next_at > self.clock():
                db.execute("UPDATE pockets SET due=? WHERE id=?", (next_at, pocket_id))
                return {"status": "SOURCE_NOT_DUE", "next_at": next_at}
            skill = self.library.skill(db, row["owner"], row["version"])
            try:
                self._admit_skill(db, skill)
            except PermissionError:
                db.execute("UPDATE pockets SET state='PAUSED',reason='SKILL_REVALIDATION_REQUIRED' WHERE id=?", (pocket_id,))
                self.store.event(db, pocket_id, principal.owner, "factory-worker", "skill.revalidation_required")
                return {"status": "PAUSED", "reason": "SKILL_REVALIDATION_REQUIRED"}
            lease, run_id, now = uuid4().hex, uuid4().hex, self.clock()
            wall = min(20, manifest.budget.max_wall_seconds - row["seconds"])
            reserved_bytes = min(1_000_000, manifest.budget.max_bytes - row["bytes"])
            robots_cache = json.loads(slot["robots_cache"]) if slot and slot["robots_cache"] else None
            db.execute("INSERT INTO source_access VALUES(?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
                       "next_at=excluded.next_at,lease=excluded.lease,lease_until=excluded.lease_until",
                       (source.origin, now + source.min_interval_seconds, lease, now + wall + 5,
                        canonical(robots_cache) if robots_cache else None))
            report = {"status": "RUNNING", "run_id": run_id}
            db.execute("INSERT INTO pocket_runs VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id, pocket_id, row["owner"],
                       idempotency_key, lease, now, "RUNNING", canonical(report), reserved_bytes, wall))
            db.execute("UPDATE pockets SET state='RUNNING',attempts=attempts+1,lease=?,lease_until=?,updated=? WHERE id=?",
                       (lease, now + wall + 5, now, pocket_id))
            self.store.event(db, pocket_id, row["owner"], principal.actor, "execution.started",
                             {"run_id": run_id, "cursor": row["cursor"], "version": skill.version})

        outcome = {"bytes": 0, "retryable": False, "retry_after": 0, "observed_fields": []}
        catalog = ConnectorRegistry()

        def save_robots(value):
            with self.store.transaction() as db:
                db.execute("UPDATE source_access SET robots_cache=? WHERE source_id=? AND lease=?",
                           (canonical(value) if value else None, source.origin, lease))

        def retrieve(payload):
            if payload != {"source_id": source.id, "url": url}:
                raise PermissionError("tool input is outside this pocket's frozen task")
            try:
                receipt = self.fetcher.fetch(source, url, max_bytes=reserved_bytes,
                                             wall_seconds=wall, robots_cache=robots_cache,
                                             save_robots=save_robots, clock=self.clock)
                outcome.update(bytes=receipt["bytes"], receipt=receipt)
                return receipt
            except RetrievalError as exc:
                outcome.update(bytes=exc.bytes_read, error=str(exc), retryable=exc.retryable, retry_after=exc.retry_after)
                raise

        catalog.register_tool("provided_context.read", "1.0.0", Sink("pocket-source", "provided_context.read", "R0",
            "authorized HTTPS source read", True, "LOCAL_ONLY", "provided_context.read"), retrieve)

        def read_task(task, inputs, dependencies):
            # Explicit pocket-level intersection remains enforced in open-access mode.
            if "provided_context.read" not in manifest.permitted_operations:
                raise PermissionError("pocket tool permission denied")
            return catalog.execute_for_agent("provided_context.read", "1.0.0", {"source_id": source.id, "url": url},
                                             task_id=run_id, agent_id=manifest.agent_ids[0])

        def parse_task(task, inputs, dependencies):
            try:
                records = extract(dependencies[run_id + ":retrieve"]["result"]["body"], skill.artifact)
                if len(records) > manifest.budget.max_records - row["records"]:
                    outcome["error"] = "RECORD_BUDGET_EXHAUSTED"
                    raise ValueError("record budget exhausted")
                return records
            except QualityError as exc:
                outcome.update(error=str(exc), quality_failure=True, observed_fields=exc.observed_fields)
                raise

        started = time.monotonic()
        try:
            workflow = execute((Task(run_id + ":retrieve", (), manifest.agent_ids[0], "provided_context.read"),
                                Task(run_id + ":extract", (run_id + ":retrieve",), manifest.agent_ids[-1], "structured.extract")),
                               {"provided_context.read": read_task, "structured.extract": parse_task}, {}, workers=1)
        except Exception as exc:
            workflow = {"status": "FAILED", "tasks": {}}
            outcome["error"] = type(exc).__name__
        seconds = time.monotonic() - started
        with self.store.transaction() as db:
            current = self._row(db, pocket_id, principal)
            stopped = self._stopped(db, principal.owner)
            if current["lease"] != lease:
                self.store.event(db, pocket_id, row["owner"], "factory-worker", "execution.stale_result_discarded", {"run_id": run_id})
                return {"status": "STALE_RESULT_DISCARDED", "run_id": run_id}
            count, state, reason = 0, "READY", ""
            if current["state"] != "RUNNING" or stopped:
                state = current["state"] if current["state"] != "RUNNING" else "PAUSED"
                reason = current["reason"] if not stopped else "EMERGENCY_STOPPED"
                report = {"status": "RESULT_DISCARDED", "run_id": run_id}
            elif workflow["status"] == "COMPLETED" and seconds <= wall:
                records = workflow["tasks"][run_id + ":extract"]["result"]
                count = len(records)
                receipt = outcome["receipt"]
                output = ExecutionEvent(owner=row["owner"], pocket_id=pocket_id, actor=manifest.agent_ids[0],
                    event_type="extraction.output", details={"records": records, "source_url": url,
                    "source_id": source.id, "source_sha256": receipt["sha256"], "run_id": run_id,
                    "skill_version": skill.version, "skill_sha256": digest(skill.artifact),
                    "bytes": outcome["bytes"], "seconds": seconds, "cost_usd": 0},
                    provenance=self.store.provenance("factory", run_id))
                self.store.put(db, "output", output, pocket_id)
                cursor = row["cursor"] + 1
                state = "COMPLETED" if cursor == len(self._pages(manifest)) else "READY"
                db.execute("UPDATE pockets SET cursor=?,failures=0 WHERE id=?", (cursor, pocket_id))
                report = {"status": state, "run_id": run_id, "output_id": output.id, "records": count}
            else:
                reason = outcome.get("error", "TIME_BUDGET_EXHAUSTED" if seconds > wall else "TOOL_FAILURE")
                failures = current["failures"] + 1
                state = "PAUSED" if outcome.get("quality_failure") else (
                    "READY" if outcome["retryable"] and failures <= manifest.budget.max_retries else "FAILED")
                if "BUDGET_EXHAUSTED" in reason:
                    state = "BUDGET_EXHAUSTED"
                evidence_id = self.store.event(db, pocket_id, row["owner"], manifest.agent_ids[0], "execution.failed",
                    {"run_id": run_id, "code": reason, "bytes": outcome["bytes"], "seconds": seconds})
                if outcome.get("quality_failure"):
                    self.academy.observe_failure(db, current, evidence_id, outcome["observed_fields"], reason)
                    reason = "QUALITY_FAILURE"
                db.execute("UPDATE pockets SET failures=? WHERE id=?", (failures, pocket_id))
                report = {"status": state, "run_id": run_id, "reason": reason}
            next_at = self.clock() + max(source.min_interval_seconds,
                outcome.get("receipt", {}).get("next_interval_seconds", 0), outcome["retry_after"])
            db.execute("UPDATE source_access SET next_at=?,lease=NULL,lease_until=NULL WHERE source_id=? AND lease=?",
                       (next_at, source.origin, lease))
            db.execute("UPDATE pockets SET state=?,reason=?,bytes=bytes+?,records=records+?,seconds=seconds+?,"
                       "due=?,updated=?,lease=NULL,lease_until=NULL WHERE id=?",
                       (state, reason, outcome["bytes"], count, seconds, next_at, self.clock(), pocket_id))
            db.execute("UPDATE pocket_runs SET status=?,report=? WHERE id=?", (report["status"], canonical(report), run_id))
            self.store.event(db, pocket_id, row["owner"], "factory-worker", "execution.finished", report)
        return report

    def evaluate_pending(self):
        with self.store.transaction() as db:
            row = db.execute("SELECT p.id,p.owner,p.body FROM pocket_records p LEFT JOIN pocket_control c ON c.owner=p.owner "
                "WHERE p.kind='coaching_proposal' AND COALESCE(c.stopped,0)=0 AND NOT EXISTS "
                "(SELECT 1 FROM pocket_records e WHERE e.kind='evaluation' AND e.owner=p.owner "
                "AND json_extract(e.body,'$.proposal_id')=p.id) ORDER BY p.rowid LIMIT 1").fetchone()
            if row is None:
                return None
            if not self.store.verify_events(db):
                raise ValueError("cannot evaluate against damaged audit evidence")
            proposal = CoachingProposal.model_validate(self.store.get(db, "coaching_proposal", row["id"], row["owner"]))
            return self.academy.evaluate_candidate(db, proposal).model_dump(mode="json")

    def promote(self, pocket_id, principal, proposal_id, evaluation_id, reason):
        try:
            return self._promote(pocket_id, principal, proposal_id, evaluation_id, reason)
        except (PermissionError, ValueError, KeyError) as exc:
            with self.store.transaction() as db:
                owned = db.execute("SELECT 1 FROM pockets WHERE id=? AND owner=?", (pocket_id, principal.owner)).fetchone()
                if owned and self.store.verify_events(db):
                    self.store.event(db, pocket_id, principal.owner, principal.actor, "promotion.denied",
                        {"proposal_id": proposal_id, "evaluation_id": evaluation_id, "reason_code": type(exc).__name__})
            raise

    def _promote(self, pocket_id, principal, proposal_id, evaluation_id, reason):
        if principal.role != "OWNER" or principal.actor in {"a07", "a18", "academy", "factory-worker"}:
            raise PermissionError("independent authenticated owner promotion required")
        with self.store.transaction() as db:
            pocket = self._row(db, pocket_id, principal)
            if not self.store.verify_events(db):
                raise PermissionError("audit integrity must be restored before promotion")
            proposal = CoachingProposal.model_validate(self.store.get(db, "coaching_proposal", proposal_id, principal.owner, pocket_id))
            evaluation = self.store.get(db, "evaluation", evaluation_id, principal.owner, pocket_id)
            if any(item["proposal_id"] == proposal_id for item in self.store.records(db, "promotion", principal.owner, pocket_id)):
                raise ValueError("proposal already has a promotion decision")
            if (pocket["lease"] or pocket["state"] != "PAUSED" or pocket["reason"] != "QUALITY_FAILURE"
                    or pocket["version"] != proposal.from_version or evaluation["proposal_id"] != proposal_id
                    or evaluation["candidate_sha256"] != digest(proposal.proposed_change)
                    or evaluation["provenance"]["source_revision"] != self.store.revision
                    or proposal.provenance.source_revision != self.store.revision
                    or evaluation["suite_sha256"] != self.academy.suite_digest()
                    or evaluation["evaluator"] in {proposal.proposer, principal.actor}
                    or not all(evaluation[key] for key in ("passed", "safety_passed", "correctness_passed",
                                                           "traceability_passed", "generalization_passed"))):
                raise PermissionError("promotion lacks bound independent passing acceptance")
            previous = self.library.skill(db, principal.owner, pocket["version"])
            promoted = SkillManifest(owner=principal.owner, version=proposal.to_version,
                agent_ids=previous.agent_ids, tool_ids=previous.tool_ids, permissions=previous.permissions,
                artifact=proposal.proposed_change, audit_refs=(proposal_id, evaluation_id),
                provenance=self.store.provenance("library", evaluation_id))
            self.library.publish(db, promoted)
            decision = PromotionDecision(owner=principal.owner, pocket_id=pocket_id, proposal_id=proposal_id,
                evaluation_id=evaluation_id, approver=principal.actor, approved=True, reason=reason,
                candidate_sha256=digest(proposal.proposed_change), previous_version=previous.version,
                promoted_version=promoted.version, audit_refs=(proposal_id, evaluation_id),
                provenance=self.store.provenance("factory", "authenticated-owner-decision"))
            self.store.put(db, "promotion", decision, pocket_id)
            db.execute("UPDATE pockets SET version=?,state='READY',reason='',due=?,updated=? WHERE id=?",
                       (promoted.version, self.clock(), self.clock(), pocket_id))
            self.store.event(db, pocket_id, principal.owner, principal.actor, "promotion.approved", {"decision_id": decision.id})
        return self.get(pocket_id, principal)

    def rollback(self, pocket_id, principal, decision_id, reason):
        if principal.role != "OWNER":
            raise PermissionError("owner rollback required")
        with self.store.transaction() as db:
            pocket = self._row(db, pocket_id, principal)
            decision = self.store.get(db, "promotion", decision_id, principal.owner, pocket_id)
            if pocket["lease"] or pocket["version"] != decision["promoted_version"] or pocket["state"] == "RETIRED":
                raise ValueError("rollback requires the promoted version without active execution")
            self.library.skill(db, principal.owner, decision["previous_version"])
            recovery = RecoveryRecord(owner=principal.owner, pocket_id=pocket_id, operation="rollback",
                previous_state=pocket["state"], restored_state="PAUSED", reason=reason, evidence_refs=(decision_id,),
                provenance=self.store.provenance("factory", decision_id))
            self.store.put(db, "recovery", recovery, pocket_id)
            db.execute("UPDATE pockets SET version=?,state='PAUSED',reason='ROLLED_BACK',updated=? WHERE id=?",
                       (decision["previous_version"], self.clock(), pocket_id))
            self.store.event(db, pocket_id, principal.owner, principal.actor, "promotion.rolled_back", {"recovery_id": recovery.id})
        return self.get(pocket_id, principal)

    def revalidate(self, pocket_id, principal):
        if principal.role != "OWNER":
            raise PermissionError("owner revalidation of pinned artifacts required")
        with self.store.transaction() as db:
            pocket = self._row(db, pocket_id, principal)
            if pocket["lease"] or pocket["state"] == "RETIRED":
                raise ValueError("revalidation requires inactive, retained state")
            skill = self.library.skill(db, principal.owner, pocket["version"])
            if skill.version == "1.0.0":
                self.library.ensure_builtin(db, principal.owner)
            else:
                decision = db.execute("SELECT id FROM pocket_records WHERE kind='promotion' AND owner=? "
                    "AND json_extract(body,'$.promoted_version')=? AND json_extract(body,'$.candidate_sha256')=?",
                    (principal.owner, skill.version, digest(skill.artifact))).fetchone()
                if decision is None or not self.store.get(db, "promotion", decision[0], principal.owner)["approved"]:
                    raise PermissionError("only previously owner-approved artifacts may be revalidated")
                original = CoachingProposal.model_validate(self.store.get(db, "coaching_proposal", skill.audit_refs[0], principal.owner))
                proposal = original.model_copy(update={"id": uuid4().hex, "pocket_id": pocket_id,
                    "provenance": self.store.provenance("academy", "revalidation:" + original.id)})
                self.store.put(db, "skill_revalidation", proposal, pocket_id)
                evaluation = self.academy.evaluate_candidate(db, proposal)
                if not evaluation.passed:
                    db.execute("UPDATE pockets SET state='PAUSED',reason='SKILL_REVALIDATION_FAILED' WHERE id=?", (pocket_id,))
                    return {"status": "PAUSED", "reason": "SKILL_REVALIDATION_FAILED", "evaluation_id": evaluation.id}
            self._admit_skill(db, skill)
            if pocket["reason"] == "SKILL_REVALIDATION_REQUIRED":
                db.execute("UPDATE pockets SET state='READY',reason='',due=? WHERE id=?", (self.clock(), pocket_id))
            self.store.event(db, pocket_id, principal.owner, principal.actor, "skill.revalidated", {"version": skill.version})
        return self.get(pocket_id, principal)

    def recover(self):
        recovered = []
        with self.store.transaction() as db:
            for row in db.execute("SELECT * FROM pockets WHERE lease IS NOT NULL AND lease_until<=?", (self.clock(),)).fetchall():
                row = dict(row)
                manifest = PocketManifest.model_validate_json(row["manifest"])
                run = db.execute("SELECT * FROM pocket_runs WHERE lease=? AND pocket_id=?", (row["lease"], row["id"])).fetchone()
                # A powered-off night is not execution. Charge only the bounded
                # attempt reservation, even when the next boot is many hours later.
                elapsed = min(max(0, self.clock() - run["started"]), run["reserved_seconds"],
                              manifest.budget.max_wall_seconds - row["seconds"])
                state = "READY" if row["state"] == "RUNNING" else row["state"]
                if row["state"] == "RUNNING":
                    if (row["attempts"] >= manifest.budget.max_attempts or row["seconds"] + elapsed >= manifest.budget.max_wall_seconds
                            or row["bytes"] + run["reserved_bytes"] >= manifest.budget.max_bytes):
                        state = "BUDGET_EXHAUSTED"
                    elif row["failures"] >= manifest.budget.max_retries:
                        state = "FAILED"
                recovery = RecoveryRecord(owner=row["owner"], pocket_id=row["id"], operation="lease-recovery",
                    previous_state=row["state"], restored_state=state, reason="Expired execution lease; prior result fenced.",
                    evidence_refs=(run["id"],), provenance=self.store.provenance("factory", run["id"]))
                self.store.put(db, "recovery", recovery, row["id"])
                db.execute("UPDATE pocket_runs SET status='INTERRUPTED',report=? WHERE id=?",
                           (canonical({"status": "INTERRUPTED", "run_id": run["id"]}), run["id"]))
                reason = "LEASE_RECOVERED" if row["state"] == "RUNNING" else row["reason"]
                db.execute("UPDATE pockets SET state=?,reason=?,seconds=seconds+?,bytes=bytes+?,failures=failures+1,"
                           "lease=NULL,lease_until=NULL,due=?,updated=? WHERE id=?",
                           (state, reason, elapsed, run["reserved_bytes"], self.clock(), self.clock(), row["id"]))
                db.execute("UPDATE source_access SET lease=NULL,lease_until=NULL WHERE lease=?", (row["lease"],))
                self.store.event(db, row["id"], row["owner"], "factory-worker", "execution.recovered", {"recovery_id": recovery.id})
                recovered.append(row["id"])
        return recovered

    def emergency_stop(self, principal, stopped=True):
        if principal.role != "OWNER":
            raise PermissionError("owner emergency control required")
        with self.store.transaction() as db:
            db.execute("INSERT INTO pocket_control VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET stopped=excluded.stopped",
                       (principal.owner, int(stopped)))
            self.store.event(db, "factory", principal.owner, principal.actor, "emergency.stop" if stopped else "emergency.clear")

    def tick(self):
        self.recover()
        evaluated = self.evaluate_pending()
        if evaluated:
            return {"status": "EVALUATED", "evaluation": evaluated}
        with self.store.connect() as db:
            row = db.execute("SELECT p.id,p.owner FROM pockets p LEFT JOIN pocket_control c ON c.owner=p.owner "
                             "WHERE p.state='READY' AND p.lease IS NULL AND p.due<=? AND COALESCE(c.stopped,0)=0 ORDER BY p.due,p.updated LIMIT 1",
                             (self.clock(),)).fetchone()
        if row:
            try:
                return self.run_one(row["id"], Principal(row["owner"], "factory-worker", "WORKER"), uuid4().hex)
            except (ValueError, KeyError, PermissionError) as exc:
                with self.store.transaction() as db:
                    db.execute("UPDATE pockets SET state='PAUSED',reason='DEPENDENCY_OR_EVIDENCE_REQUIRED',updated=? WHERE id=?",
                               (self.clock(), row["id"]))
                return {"status": "PAUSED", "pocket_id": row["id"], "error_type": type(exc).__name__,
                        "reason": "DEPENDENCY_OR_EVIDENCE_REQUIRED"}
        return {"status": "IDLE"}

    def health(self, principal):
        with self.store.connect() as db:
            worker = db.execute("SELECT observed,state FROM pocket_worker WHERE id=1").fetchone()
            worker_value = dict(worker) if worker else {"state": "NOT_OBSERVED", "observed": None}
            age = self.clock() - worker["observed"] if worker else None
            worker_value["availability"] = "UNKNOWN" if age is None or age < 0 else "STALE" if age > 60 else "OBSERVED"
            counts = {row[0]: row[1] for row in db.execute("SELECT state,COUNT(*) FROM pockets WHERE owner=? GROUP BY state", (principal.owner,))}
            return {"component": "activity-pocket-factory", "source_revision": self.store.revision,
                    "verification_scope": self.store.origin, "orchestration_required": False,
                    "audit_chain_valid": self.store.verify_events(db), "pocket_states": counts,
                    "emergency_stopped": self._stopped(db, principal.owner),
                    "owner_scope": principal.owner,
                    "configuration": "CONFIGURED" if self.sources else "NO_AUTHORIZED_SOURCES",
                    "worker": worker_value,
                    "sources": [source.public() for source in self.sources.values() if principal.owner in source.owners],
                    "coaching_authority": "app.academy.PersistentAcademy",
                    "qualification_authority": "app.agent_certification.AgentCertificationRegistry",
                    "production_ready": False}

    def coverage(self, principal):
        from ..coaching_observation import coaching_snapshot
        from ..agent_capability_observatory import project_capability_observatory
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        coaching = coaching_snapshot(self.store.path.parent, now=self.clock())
        coached = {row["agent_id"]: row for row in coaching["agents"]}
        qualification = project_capability_observatory(self.library.qualifications, now=now)
        with self.store.connect() as db:
            rows = []
            for projection in qualification:
                agent = projection["agent_id"]
                feedback = db.execute("SELECT COUNT(*) FROM pocket_records WHERE owner=? AND kind='academy_training' "
                    "AND json_extract(body,'$.actor')=?", (principal.owner, agent)).fetchone()[0]
                rows.append({"agent_id": agent, "qualification": projection, "pocket_feedback_records": feedback,
                             "internal_coaching": coached.get(agent), "fleet_coaching": "INTERNAL_EVIDENCE_ONLY"})
            return {"agents": rows, "registered_count": len(rows),
                    "all_agents_coached": None if coaching["status"] != "OBSERVED" else (coaching["status"] == "OBSERVED"
                        and coaching["cohort_source_revision"] == self.store.revision
                        and coaching["completed_count"] == 21 and coaching["acceptance_pass_count"] == 21),
                    "coaching_snapshot": coaching,
                    "cohort_source_matches_current": coaching["cohort_source_revision"] == self.store.revision,
                    "scope": self.store.origin,
                    "worker": {"kind": "deterministic-executor", "coaching": "NOT_AN_AGENT",
                               "diagnostics": "durable attempts, failure evidence, fenced lease recovery"}}

    def purge_expired_outputs(self):
        purged = []
        with self.store.transaction() as db:
            for raw in db.execute("SELECT * FROM pockets WHERE state='RETIRED'").fetchall():
                row = dict(raw)
                manifest = PocketManifest.model_validate_json(row["manifest"])
                if row["reason"] == "RETENTION_PURGED" or row["updated"] + manifest.retention_days * 86400 > self.clock():
                    continue
                db.execute("DELETE FROM pocket_records WHERE owner=? AND pocket_id=? AND kind IN ('output','academy_training','academy_feedback')",
                           (row["owner"], row["id"]))
                sanitized = manifest.model_copy(update={"objective": "Purged under the declared pocket retention policy."})
                db.execute("UPDATE pockets SET manifest=?,reason='RETENTION_PURGED' WHERE id=?", (canonical(sanitized), row["id"]))
                record = RecoveryRecord(owner=row["owner"], pocket_id=row["id"], operation="retention-purge",
                    previous_state="RETIRED", restored_state="RETIRED", reason="Declared output retention expired.",
                    evidence_refs=(digest(manifest),), provenance=self.store.provenance("factory", row["id"]))
                self.store.put(db, "recovery", record, row["id"])
                self.store.event(db, row["id"], row["owner"], "factory-worker", "retention.purged", {"recovery_id": record.id})
                purged.append(row["id"])
        return purged

    def tool_manifest(self, principal):
        return ToolManifest(owner=principal.owner, tool_id="provided_context.read", version="1.0.0",
            permissions=("provided_context.read",), input_contract={"source_id": "trusted source ID", "url": "exact allowed HTTPS URL"},
            output_contract={"body": "UTF-8 HTML", "sha256": "SHA256", "bytes": "integer", "source_url": "HTTPS URL"},
            provenance=self.store.provenance("tools", "app/connector_sdk.py")).model_dump(mode="json")
