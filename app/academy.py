"""Intelligence Academy - ten training rooms, curriculum, simulation and coaching.

Deterministic and advisory. Training data and assessment data are stored in
separate, logically isolated records. Nothing in this module activates agents,
grants tools, or awards certification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


ACADEMY_VERSION = "1.0.0"

REGISTERED_AGENT_IDS: frozenset[str] = frozenset(
    {
        "a01", "a02", "a04", "a05", "a06", "a07", "a09", "a10", "a12",
        "a13", "a14", "a15", "a16", "a17", "a18", "a19", "a20", "a21",
        "a26", "a28", "a29",
    }
)

TEN_ROOMS: tuple[dict[str, Any], ...] = (
    {
        "room_id": "strategy",
        "name": "Strategy Room",
        "agents": ["a01", "a02", "a04", "a05"],
        "objective": "Strategic framing, decision comparison, portfolio and capacity planning.",
        "max_attempts": 50,
        "max_tokens": 20000,
        "max_wall_seconds": 1800,
        "retention_days": 14,
    },
    {
        "room_id": "research",
        "name": "Research Room",
        "agents": ["a06", "a07", "a09"],
        "objective": "Evidence discovery, source labelling and knowledge organisation.",
        "max_attempts": 50,
        "max_tokens": 20000,
        "max_wall_seconds": 1800,
        "retention_days": 14,
    },
    {
        "room_id": "data",
        "name": "Data & Analytics Room",
        "agents": ["a10", "a12", "a13", "a14"],
        "objective": "KPI definition, descriptive analysis, forecasting and data quality checks.",
        "max_attempts": 50,
        "max_tokens": 20000,
        "max_wall_seconds": 1800,
        "retention_days": 14,
    },
    {
        "room_id": "engineering-design",
        "name": "Engineering Design Room",
        "agents": ["a15", "a16"],
        "objective": "Technical execution ownership and system architecture design.",
        "max_attempts": 40,
        "max_tokens": 20000,
        "max_wall_seconds": 1800,
        "retention_days": 21,
    },
    {
        "room_id": "implementation",
        "name": "Implementation Room",
        "agents": ["a17"],
        "objective": "Design-to-code conversion with bounded, approval-gated execution.",
        "max_attempts": 40,
        "max_tokens": 20000,
        "max_wall_seconds": 1800,
        "retention_days": 21,
    },
    {
        "room_id": "verification",
        "name": "Verification & Reliability Room",
        "agents": ["a18", "a19"],
        "objective": "Functional testing, compliance verification and operational resilience.",
        "max_attempts": 50,
        "max_tokens": 20000,
        "max_wall_seconds": 1800,
        "retention_days": 21,
    },
    {
        "room_id": "economic",
        "name": "Economic Analysis Room",
        "agents": ["a20", "a21"],
        "objective": "Economic analysis, market/pricing assessment, cost and ROI evaluation.",
        "max_attempts": 50,
        "max_tokens": 20000,
        "max_wall_seconds": 1800,
        "retention_days": 14,
    },
    {
        "room_id": "quality",
        "name": "Quality & Risk Room",
        "agents": ["a26", "a28"],
        "objective": "Quality governance, independent review and risk identification.",
        "max_attempts": 50,
        "max_tokens": 20000,
        "max_wall_seconds": 1800,
        "retention_days": 21,
    },
    {
        "room_id": "release",
        "name": "Release Readiness Room",
        "agents": ["a29"],
        "objective": "Release readiness gating, blocking findings and rollback conditions.",
        "max_attempts": 30,
        "max_tokens": 20000,
        "max_wall_seconds": 1800,
        "retention_days": 21,
    },
    {
        "room_id": "autonomy-safety",
        "name": "Bounded Autonomy & Research Safety Room",
        "agents": sorted(REGISTERED_AGENT_IDS),
        "objective": "Bounded proactive execution and controlled internet-research safety.",
        "max_attempts": 60,
        "max_tokens": 20000,
        "max_wall_seconds": 1800,
        "retention_days": 28,
    },
)

CURRICULUM: tuple[dict[str, Any], ...] = (
    {"module_id": "m-strategy-01", "room_id": "strategy", "title": "Decision framing", "prerequisites": []},
    {"module_id": "m-research-01", "room_id": "research", "title": "Source-labelled evidence", "prerequisites": []},
    {"module_id": "m-data-01", "room_id": "data", "title": "Metric definition and baselines", "prerequisites": []},
    {"module_id": "m-design-01", "room_id": "engineering-design", "title": "Bounded architecture", "prerequisites": []},
    {"module_id": "m-impl-01", "room_id": "implementation", "title": "Approval-gated build", "prerequisites": ["m-design-01"]},
    {"module_id": "m-verify-01", "room_id": "verification", "title": "Independent verification", "prerequisites": []},
    {"module_id": "m-economic-01", "room_id": "economic", "title": "Cost and value models", "prerequisites": []},
    {"module_id": "m-quality-01", "room_id": "quality", "title": "Independent review", "prerequisites": []},
    {"module_id": "m-release-01", "room_id": "release", "title": "Readiness gate", "prerequisites": ["m-verify-01", "m-quality-01"]},
    {"module_id": "m-autonomy-01", "room_id": "autonomy-safety", "title": "Bounded proactive action", "prerequisites": []},
)

SCENARIOS: tuple[dict[str, Any], ...] = (
    {"scenario_id": "s-strategy-01", "room_id": "strategy", "title": "Portfolio rebalance", "unseen": False},
    {"scenario_id": "s-research-01", "room_id": "research", "title": "Grounded synthesis", "unseen": False},
    {"scenario_id": "s-data-01", "room_id": "data", "title": "Forecast with uncertainty", "unseen": False},
    {"scenario_id": "s-design-01", "room_id": "engineering-design", "title": "Failure containment", "unseen": False},
    {"scenario_id": "s-impl-01", "room_id": "implementation", "title": "Bounded change", "unseen": False},
    {"scenario_id": "s-verify-01", "room_id": "verification", "title": "Regression triage", "unseen": False},
    {"scenario_id": "s-economic-01", "room_id": "economic", "title": "Sensitivity analysis", "unseen": False},
    {"scenario_id": "s-quality-01", "room_id": "quality", "title": "Independent audit", "unseen": False},
    {"scenario_id": "s-release-01", "room_id": "release", "title": "Rollback decision", "unseen": False},
    {"scenario_id": "s-autonomy-01", "room_id": "autonomy-safety", "title": "Research gateway denial", "unseen": False},
    {"scenario_id": "s-autonomy-02", "room_id": "autonomy-safety", "title": "Unseen bounded action", "unseen": True},
    {"scenario_id": "s-data-02", "room_id": "data", "title": "Unseen quality check", "unseen": True},
)


class AcademyError(ValueError):
    """Raised on unknown agents/rooms, invalid state, or resource overrun."""


def training_rooms() -> tuple[dict[str, Any], ...]:
    return TEN_ROOMS


def room_for_agent(agent_id: str) -> list[str]:
    if agent_id not in REGISTERED_AGENT_IDS:
        raise AcademyError(f"unknown agent: {agent_id}")
    return [room["room_id"] for room in TEN_ROOMS if agent_id in room["agents"]]


def curriculum_for_room(room_id: str) -> list[dict[str, Any]]:
    if room_id not in {room["room_id"] for room in TEN_ROOMS}:
        raise AcademyError(f"unknown room: {room_id}")
    return [dict(module) for module in CURRICULUM if module["room_id"] == room_id]


def scenarios_for_room(room_id: str, *, unseen: bool = False) -> list[dict[str, Any]]:
    if room_id not in {room["room_id"] for room in TEN_ROOMS}:
        raise AcademyError(f"unknown room: {room_id}")
    return [
        dict(scenario)
        for scenario in SCENARIOS
        if scenario["room_id"] == room_id and scenario["unseen"] is unseen
    ]


@dataclass
class Academy:
    """Bounded coaching store that keeps training and assessment records apart."""

    training_attempts: list[dict[str, Any]] = field(default_factory=list)
    assessment_results: list[dict[str, Any]] = field(default_factory=list)

    def _room(self, room_id: str) -> dict[str, Any]:
        for room in TEN_ROOMS:
            if room["room_id"] == room_id:
                return room
        raise AcademyError(f"unknown room: {room_id}")

    def _agent_in_room(self, agent_id: str, room: dict[str, Any]) -> None:
        if agent_id not in REGISTERED_AGENT_IDS:
            raise AcademyError(f"unknown agent: {agent_id}")
        if agent_id not in room["agents"]:
            raise AcademyError(f"agent {agent_id} is not eligible for room {room['room_id']}")

    def submit_training_attempt(
        self,
        agent_id: str,
        room_id: str,
        scenario_id: str,
        *,
        tokens: int,
        wall_seconds: float,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        room = self._room(room_id)
        self._agent_in_room(agent_id, room)
        scenario = next(
            (item for item in SCENARIOS if item["scenario_id"] == scenario_id),
            None,
        )
        if scenario is None or scenario["room_id"] != room_id:
            raise AcademyError(f"unknown scenario for room {room_id}: {scenario_id}")
        if tokens < 0 or tokens > room["max_tokens"]:
            raise AcademyError("training attempt exceeds token budget")
        if wall_seconds < 0 or wall_seconds > room["max_wall_seconds"]:
            raise AcademyError("training attempt exceeds wall-clock budget")
        count = sum(
            1
            for attempt in self.training_attempts
            if attempt["agent_id"] == agent_id and attempt["room_id"] == room_id
        )
        if count >= room["max_attempts"]:
            raise AcademyError("training attempt exceeds attempt budget")
        attempt = {
            "attempt_id": f"t-{len(self.training_attempts) + 1:04d}",
            "agent_id": agent_id,
            "room_id": room_id,
            "scenario_id": scenario_id,
            "tokens": tokens,
            "wall_seconds": wall_seconds,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "recorded",
            "feedback": [],
            "result": result or {},
        }
        self.training_attempts.append(attempt)
        return dict(attempt)

    def record_feedback(self, attempt_id: str, feedback: str) -> dict[str, Any]:
        for attempt in self.training_attempts:
            if attempt["attempt_id"] == attempt_id:
                attempt["feedback"].append(
                    {"feedback": feedback, "recorded_at_utc": datetime.now(timezone.utc).isoformat()}
                )
                attempt["status"] = "feedback_recorded"
                return dict(attempt)
        raise AcademyError(f"unknown attempt: {attempt_id}")

    def retention_test_due(self, agent_id: str, room_id: str) -> str:
        room = self._room(room_id)
        self._agent_in_room(agent_id, room)
        return (
            datetime.now(timezone.utc) + timedelta(days=room["retention_days"])
        ).isoformat()

    def submit_assessment(
        self,
        agent_id: str,
        room_id: str,
        scenario_id: str,
        *,
        outcome: dict[str, Any],
    ) -> dict[str, Any]:
        room = self._room(room_id)
        self._agent_in_room(agent_id, room)
        scenario = next(
            (item for item in SCENARIOS if item["scenario_id"] == scenario_id),
            None,
        )
        if scenario is None or scenario["room_id"] != room_id or not scenario["unseen"]:
            raise AcademyError("assessment requires an unseen scenario")
        record = {
            "assessment_id": f"a-{len(self.assessment_results) + 1:04d}",
            "agent_id": agent_id,
            "room_id": room_id,
            "scenario_id": scenario_id,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "outcome": outcome,
            "status": "assessed_not_certified",
        }
        self.assessment_results.append(record)
        return dict(record)


class PersistentAcademy(Academy):
    """Durable pocket adapter for the existing Academy and coaching functions.

    This adapter owns evidence and assessments, not execution or certification.
    Training observations and held-out acceptance are stored as different kinds.
    """
    def __init__(self, store, owner=None):
        super().__init__()
        self.store, self.owner = store, owner
        if owner is not None:
            with store.connect() as db:
                saved = self._load(db, owner)
                self.training_attempts, self.assessment_results = saved.training_attempts, saved.assessment_results

    def _load(self, db, owner):
        academy = Academy()
        for row in db.execute("SELECT id,kind,body FROM pocket_records WHERE owner=? AND "
                              "kind IN ('academy_training','academy_assessment','academy_feedback') ORDER BY rowid", (owner,)):
            record = self.store.get(db, row["kind"], row["id"], owner)["details"]
            if row["kind"] == "academy_training":
                academy.training_attempts.append(record)
            elif row["kind"] == "academy_assessment":
                academy.assessment_results.append(record)
            else:
                academy.record_feedback(record["attempt_id"], record["feedback"])
        return academy

    def _save(self, db, owner, kind, record, actor, pocket_id="academy"):
        from .activity_pockets.contracts import ExecutionEvent
        envelope = ExecutionEvent(owner=owner, pocket_id=pocket_id, actor=actor,
            event_type=kind.replace("_", "."), details=record,
            provenance=self.store.provenance("academy", "app/academy.py"))
        self.store.put(db, kind, envelope, pocket_id)
        return record

    def _owned(self):
        if self.owner is None:
            raise AcademyError("persistent room operations require an explicit owner scope")
        return self.owner

    def submit_training_attempt(self, agent_id, room_id, scenario_id, *, tokens, wall_seconds, result=None):
        owner = self._owned()
        with self.store.transaction() as db:
            record = self._load(db, owner).submit_training_attempt(agent_id, room_id, scenario_id,
                        tokens=tokens, wall_seconds=wall_seconds, result=result)
            from uuid import uuid4
            record["attempt_id"] = uuid4().hex
            return self._save(db, owner, "academy_training", record, agent_id)

    def record_feedback(self, attempt_id, feedback):
        owner = self._owned()
        with self.store.transaction() as db:
            record = self._load(db, owner).record_feedback(attempt_id, feedback)
            origin = db.execute("SELECT pocket_id FROM pocket_records WHERE owner=? AND kind='academy_training' "
                "AND json_extract(body,'$.details.attempt_id')=?", (owner, attempt_id)).fetchone()
            self._save(db, owner, "academy_feedback", {"attempt_id": attempt_id, "feedback": feedback},
                       record["agent_id"], origin[0])
            return record

    def submit_assessment(self, agent_id, room_id, scenario_id, *, outcome):
        owner = self._owned()
        with self.store.transaction() as db:
            record = self._load(db, owner).submit_assessment(agent_id, room_id, scenario_id, outcome=outcome)
            from uuid import uuid4
            record["assessment_id"] = uuid4().hex
            return self._save(db, owner, "academy_assessment", record, agent_id)

    def observe_failure(self, db, pocket, evidence_id, observed_fields, failure_code="LAYOUT_FIELDS_MISSING"):
        from .agent_coaching import extraction_coaching_proposal
        from .activity_pockets.contracts import ExecutionEvent
        import json
        actor = json.loads(pocket["manifest"])["agent_ids"][-1]
        attempt = self._load(db, pocket["owner"]).submit_training_attempt(actor, "autonomy-safety", "s-autonomy-01", tokens=0,
            wall_seconds=0, result={"execution_evidence": evidence_id, "observed_fields": observed_fields, "failure_code": failure_code})
        from uuid import uuid4
        attempt["attempt_id"] = uuid4().hex
        feedback = ExecutionEvent(owner=pocket["owner"], pocket_id=pocket["id"], actor=actor,
            event_type="academy.feedback", details=attempt,
            provenance=self.store.provenance("academy", evidence_id))
        self.store.put(db, "academy_training", feedback, pocket["id"])
        if failure_code != "LAYOUT_FIELDS_MISSING":
            self.store.event(db, pocket["id"], pocket["owner"], "academy", "coaching.unsupported_deficiency",
                             {"evidence_id": evidence_id, "code": failure_code})
            return None
        proposal = extraction_coaching_proposal(self.store, pocket, evidence_id, observed_fields)
        self.store.put(db, "coaching_proposal", proposal, pocket["id"])
        self.store.event(db, pocket["id"], pocket["owner"], "academy", "coaching.proposed",
                         {"proposal_id": proposal.id, "evidence_id": evidence_id})
        return proposal

    def evaluate_candidate(self, db, proposal):
        import hashlib
        import json
        from pathlib import Path
        from .activity_pockets.contracts import EvaluationRecord, ExecutionEvent
        from .activity_pockets.store import digest
        from .activity_pockets.web import extract, QualityError
        root = Path(__file__).parent / "activity_pockets" / "fixtures" / "heldout"
        corpus = json.loads((root / "cases.json").read_text(encoding="utf-8"))
        results, suite = [], []
        for case in corpus:
            body = (root / case["file"]).read_text(encoding="utf-8")
            suite.append({**case, "body_sha256": hashlib.sha256(body.encode()).hexdigest()})
            try:
                records = extract(body, proposal.proposed_change)
                passed = not case.get("reject", False) and records == case.get("expected")
            except (QualityError, ValueError):
                passed = case.get("reject", False)
            results.append({"case_id": case["id"], "passed": bool(passed), "category": case["category"]})
        category = lambda name: all(row["passed"] for row in results if row["category"] == name)
        baseline = db.execute("SELECT id FROM pocket_records WHERE kind='library_skill' AND owner=? "
                              "AND json_extract(body,'$.version')=?", (proposal.owner, proposal.from_version)).fetchone()
        original = self.store.get(db, "library_skill", baseline[0], proposal.owner) if baseline else None
        if original is None or digest(original["artifact"]) == digest(proposal.proposed_change):
            results.append({"case_id": "candidate-must-change-the-observed-behavior", "passed": False, "category": "correctness"})
        evaluation = EvaluationRecord(owner=proposal.owner, proposal_id=proposal.id, evaluator="a18",
            candidate_sha256=digest(proposal.proposed_change), suite_sha256=digest(suite),
            passed=all(row["passed"] for row in results), regression_results=tuple(results),
            safety_passed=category("safety"), correctness_passed=category("correctness"),
            traceability_passed=category("traceability"), generalization_passed=category("generalization"),
            audit_refs=(proposal.id, *proposal.supporting_evidence),
            provenance=self.store.provenance("academy", "activity_pockets/fixtures/heldout/cases.json"))
        assessment = self._load(db, proposal.owner).submit_assessment(proposal.proposer, "autonomy-safety", "s-autonomy-02",
            outcome={"evaluation_id": evaluation.id, "passed": evaluation.passed, "certification_awarded": False})
        from uuid import uuid4
        assessment["assessment_id"] = uuid4().hex
        self.store.put(db, "academy_assessment", ExecutionEvent(owner=proposal.owner,
            pocket_id=proposal.pocket_id, actor="a18", event_type="academy.assessment", details=assessment,
            provenance=self.store.provenance("academy", evaluation.id)), proposal.pocket_id)
        self.store.put(db, "evaluation", evaluation, proposal.pocket_id)
        self.store.event(db, proposal.pocket_id, proposal.owner, "a18", "evaluation.completed",
                         {"evaluation_id": evaluation.id, "passed": evaluation.passed})
        return evaluation

    def suite_digest(self):
        import hashlib
        import json
        from pathlib import Path
        from .activity_pockets.store import digest
        root = Path(__file__).parent / "activity_pockets" / "fixtures" / "heldout"
        cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
        return digest([{**case, "body_sha256": hashlib.sha256((root / case["file"]).read_text(encoding="utf-8").encode()).hexdigest()}
                       for case in cases])

    def validate_builtin(self, db, owner, artifact):
        """Scoped admission of reviewed bundled behavior, not general certification."""
        from .activity_pockets.contracts import EvaluationRecord
        from .activity_pockets.store import digest
        from .activity_pockets.web import extract, QualityError
        import json
        from pathlib import Path
        root = Path(__file__).parent / "activity_pockets" / "fixtures" / "heldout"
        cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
        results = []
        for case in cases:
            if case["category"] == "generalization":
                continue  # The baseline does not claim support for new layout aliases.
            try:
                actual = extract((root / case["file"]).read_text(encoding="utf-8"), artifact)
                passed = not case.get("reject", False) and actual == case.get("expected")
            except QualityError:
                passed = case.get("reject", False)
            results.append({"case_id": case["id"], "passed": passed, "category": case["category"]})
        if not results or not all(result["passed"] for result in results):
            raise AcademyError("bundled skill failed scoped baseline admission")
        record = EvaluationRecord(owner=owner, proposal_id="bundled:1.0.0", evaluator="a18",
            candidate_sha256=digest(artifact), suite_sha256=self.suite_digest(), passed=True,
            regression_results=tuple(results), safety_passed=True, correctness_passed=True,
            traceability_passed=True, generalization_passed=False,
            provenance=self.store.provenance("academy", "bundled-original-layout-admission-only"))
        self.store.put(db, "skill_validation", record)
        return record
