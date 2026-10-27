"""Independent arithmetic, learner isolation and failure-sensitive assessment."""

from fractions import Fraction
import json
import math

import pytest

from app.agent_registry import registered_agent_ids
from app.probability_curriculum import (
    LESSONS,
    assessment_request,
    catalog,
    exercise,
    learning_path,
    review_assessment,
)


def test_all_fourteen_topics_have_lessons_and_all_canonical_agents_have_paths():
    assert len(LESSONS) == 14
    assert len({key for key, _, _ in LESSONS}) == 14
    for agent in registered_agent_ids(include_orchestrator=False):
        path = learning_path(agent)
        assert path["topic_ids"] == [key for key, _, _ in LESSONS]
        assert path["training_separate_from_assessment"]
        assert not path["certification_awarded"]
    assert catalog()["production_prediction_authority"] is False


@pytest.mark.parametrize("phase", ["baseline", "practice", "acceptance"])
@pytest.mark.parametrize("seed", [1001, 1002, 1014, 54321])
def test_native_pif_oracles_agree_with_independent_closed_form_arithmetic(seed, phase):
    facts, expected = exercise("a13", seed, phase)
    variant = {"baseline": 0, "practice": 1, "acceptance": 2}[phase]
    n = facts["counting"]["n"]
    assert expected["counting"] == n * (n - 1) // 2
    assert Fraction(expected["axioms"]) == (
        Fraction(facts["axioms"]["p_a"]) + Fraction(facts["axioms"]["p_b"]) - Fraction(facts["axioms"]["p_a_and_b"])
    )
    p = Fraction(facts["markov"]["transition_matrix"][0][1])
    q = Fraction(facts["markov"]["transition_matrix"][1][0])
    assert Fraction(expected["markov"]) == (1 - p) * p + p * (1 - q)
    assert Fraction(expected["long_run"][0]) == 2 + variant
    assert Fraction(expected["long_run"][1]) == p / (p + q)
    likelihood = [Fraction(v) for v in facts["hidden_state"]["p_signal_given_state"]]
    assert Fraction(expected["hidden_state"]) == likelihood[0] / sum(likelihood)
    predicted = Fraction(facts["scoring"]["probability"])
    outcome = facts["scoring"]["outcome"]
    assert Fraction(expected["scoring"]["brier"]) == (predicted - outcome) ** 2
    assert math.isclose(expected["scoring"]["log_loss"], -math.log(float(predicted if outcome else 1 - predicted)))


def test_practice_and_unseen_assessment_have_different_inputs_without_an_answer_key():
    contexts = []
    for phase in ["baseline", "practice", "acceptance"]:
        req = assessment_request("a19", 1234, phase)
        context = json.loads(req["context"])
        assert "answers" not in context and "expected" not in context
        assert req["response_schema"]["additionalProperties"] is False
        assert set(req["response_schema"]["required"]) == {key for key, _, _ in LESSONS}
        assert ("lesson_methods" in context) == (phase != "baseline")
        contexts.append(context["questions"])
    for key in ["counting", "markov", "long_run", "hidden_state", "scoring"]:
        assert len({json.dumps(c[key], sort_keys=True) for c in contexts}) == 3


def test_every_agent_has_a_discriminating_independent_assessor():
    for agent in registered_agent_ids(include_orchestrator=False):
        _, expected = exercise(agent, 1901, "acceptance")
        assert review_assessment(agent, 1901, "acceptance", json.dumps(expected)) == (True, [])
        for key, answer in expected.items():
            bad = dict(expected)
            bad[key] = "incorrect" if type(answer) is not str else False
            passed, errors = review_assessment(agent, 1901, "acceptance", json.dumps(bad))
            assert not passed and key in errors


@pytest.mark.parametrize("response", ["{}", '{"x":1,"x":2}', '{"x":NaN}', "not json", "x" * 16001])
def test_invalid_or_forged_answers_are_rejected(response):
    assert not review_assessment("a12", 1001, "acceptance", response)[0]


def test_booleans_are_not_accepted_as_numeric_scores_and_calibration_is_not_awarded():
    _, answer = exercise("a12", 1001, "acceptance")
    answer["counting"] = True
    assert not review_assessment("a12", 1001, "acceptance", json.dumps(answer))[0]
    _, answer = exercise("a12", 1001, "acceptance")
    answer["scoring"]["log_loss"] = True
    assert not review_assessment("a12", 1001, "acceptance", json.dumps(answer))[0]
    _, answer = exercise("a12", 1001, "acceptance")
    answer["scoring"]["calibration_established"] = True
    assert not review_assessment("a12", 1001, "acceptance", json.dumps(answer))[0]


def test_rational_equivalence_is_allowed_without_coercing_numeric_or_boolean_types():
    _, answer = exercise("a12", 1001, "acceptance")
    rational = Fraction(answer["conditional"])
    answer["conditional"] = f"{rational.numerator * 2}/{rational.denominator * 2}"
    assert review_assessment("a12", 1001, "acceptance", json.dumps(answer))[0]
    answer["conditional"] = float(rational)
    assert not review_assessment("a12", 1001, "acceptance", json.dumps(answer))[0]
