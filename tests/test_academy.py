from __future__ import annotations

import pytest

from app.academy import (
    REGISTERED_AGENT_IDS,
    Academy,
    AcademyError,
    curriculum_for_room,
    room_for_agent,
    scenarios_for_room,
    training_rooms,
)


def test_ten_rooms_cover_all_21_agents():
    rooms = training_rooms()
    assert len(rooms) == 10
    covered = set()
    for room in rooms:
        covered.update(room["agents"])
    assert covered == set(REGISTERED_AGENT_IDS)


def test_room_for_agent_unknown_raises():
    with pytest.raises(AcademyError):
        room_for_agent("nope")


def test_curriculum_and_scenarios_exist_per_room():
    for room in training_rooms():
        assert curriculum_for_room(room["room_id"]), room["room_id"]
        assert scenarios_for_room(room["room_id"]), room["room_id"]


def test_training_and_assessment_stores_are_separate():
    academy = Academy()
    academy.submit_training_attempt(
        "a01", "strategy", "s-strategy-01", tokens=10, wall_seconds=5
    )
    academy.submit_assessment(
        "a01", "autonomy-safety", "s-autonomy-02", outcome={"passed": True}
    )
    assert len(academy.training_attempts) == 1
    assert len(academy.assessment_results) == 1


def test_token_budget_enforced():
    academy = Academy()
    with pytest.raises(AcademyError):
        academy.submit_training_attempt(
            "a01", "strategy", "s-strategy-01", tokens=999999, wall_seconds=5
        )


def test_attempt_budget_enforced():
    academy = Academy()
    with pytest.raises(AcademyError):
        for _ in range(51):
            academy.submit_training_attempt(
                "a01", "strategy", "s-strategy-01", tokens=1, wall_seconds=1
            )


def test_assessment_requires_unseen_scenario():
    academy = Academy()
    with pytest.raises(AcademyError):
        academy.submit_assessment(
            "a01", "strategy", "s-strategy-01", outcome={"passed": True}
        )


def test_record_feedback_unknown_raises():
    academy = Academy()
    with pytest.raises(AcademyError):
        academy.record_feedback("missing", "feedback")


def test_retention_test_due():
    academy = Academy()
    due = academy.retention_test_due("a01", "strategy")
    assert due.endswith("+00:00") or "+00:00" in due
