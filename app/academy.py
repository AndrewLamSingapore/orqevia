"""Intelligence Academy - ten training rooms, curriculum, simulation and coaching.

Deterministic and advisory. Training data and assessment data are stored in
separate, logically isolated records. Nothing in this module activates agents,
grants tools, or awards certification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .probability_curriculum import LESSONS as PROBABILITY_LESSONS


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
CURRICULUM += tuple(
    {"module_id": "m-probability-"+topic, "room_id": "autonomy-safety", "title": title,
     "prerequisites": [] if i == 0 else ["m-probability-"+PROBABILITY_LESSONS[i-1][0]],
     "program_id": "probability-foundations", "method": method}
    for i, (topic, title, method) in enumerate(PROBABILITY_LESSONS)
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
SCENARIOS += (
    {"scenario_id": "s-probability-practice", "room_id": "autonomy-safety", "title": "Probability practice", "unseen": False},
    {"scenario_id": "s-probability-acceptance", "room_id": "autonomy-safety", "title": "Unseen probability assessment", "unseen": True},
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
