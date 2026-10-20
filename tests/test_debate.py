import pytest

from app.debate import DebateStore, Position, resolve_debate


def position(agent, proposition, *, evidence=True, confidence=0.8, objections=()):
    return Position(
        agent_id=agent,
        proposition=proposition,
        evidence_refs=("evidence://case-1",) if evidence else (),
        confidence=confidence,
        objections=tuple(objections),
    )


def test_consensus_resolution_preserves_minority():
    result = resolve_debate(
        "Which option should be selected?",
        [
            position("a01", "Choose option A"),
            position("a02", "Choose option A"),
            position("a04", "Choose option B"),
        ],
    )
    assert result["decision"] == "RESOLVED"
    assert result["selected_proposition"] == "Choose option A"
    assert result["consensus_share"] == pytest.approx(0.6667, abs=0.001)
    assert [item["agent_id"] for item in result["minority_positions"]] == ["a04"]
    assert result["evidence_refs"] == ["evidence://case-1"]


def test_disagreement_escalates_and_missing_evidence_is_not_promoted():
    result = resolve_debate(
        "Is the release safe?",
        [
            position("a01", "Yes", evidence=False),
            position("a02", "Yes", confidence=0.9),
        ],
    )
    assert result["decision"] == "NEEDS_EVIDENCE"
    assert "missing_evidence:a01" in result["reasons"]
    assert result["escalation"]["required"] is False

    escalated = resolve_debate(
        "Is the release safe?",
        [
            position("a01", "Yes"),
            position("a02", "No"),
        ],
    )
    assert escalated["decision"] == "ESCALATE"
    assert escalated["escalation"] == {
        "required": True,
        "target": "owner_or_independent_review",
    }


def test_judge_must_be_independent_and_retained(tmp_path):
    with pytest.raises(ValueError):
        resolve_debate(
            "Decision?",
            [position("a26", "A"), position("a02", "B")],
            judge_agent="a26",
        )
    store = DebateStore(tmp_path / "debates.db")
    result = resolve_debate(
        "Decision?",
        [position("a01", "A"), position("a02", "A")],
        judge_agent="a26",
    )
    store.record(result)
    assert store.get(result["debate_id"])["decision"] == "RESOLVED"
    assert store.list()[0]["debate_id"] == result["debate_id"]
