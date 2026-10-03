"""Known-answer tests independent of PDE's implementation."""

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from app.pde import DecisionProblem, Evidence, EvidenceKind, InsufficientEvidence, evaluate_decision, update_binary_belief


SOURCE = Evidence("fixture:independent-hand-calculation", datetime(2026, 10, 2, tzinfo=timezone.utc), EvidenceKind.ASSUMED)


class DecisionCoreTests(unittest.TestCase):
    def test_bayes_medical_screening_known_answer(self) -> None:
        # 1% prevalence, 90% sensitivity, 9% false-positive => 0.009 / 0.0981.
        self.assertEqual(update_binary_belief("0.01", "0.9", "0.09"), Decimal("0.009") / Decimal("0.0981"))

    def test_zero_probability_event_fails(self) -> None:
        with self.assertRaises(InsufficientEvidence):
            update_binary_belief("0.5", 0, 0)

    def test_most_likely_is_not_best_action(self) -> None:
        problem = DecisionProblem(
            "Choose a hedge",
            {"calm": "0.9", "loss": "0.1"},
            {"unhedged": {"calm": 10, "loss": -100}, "hedged": {"calm": 0, "loss": 0}},
            (SOURCE,),
        )
        result = evaluate_decision(problem)
        self.assertEqual(result["most_likely_state"], "calm")
        self.assertEqual(result["recommended_action"], "hedged")
        self.assertEqual(Decimal(result["actions"]["unhedged"]["expected_utility"]), Decimal(-1))
        self.assertEqual(Decimal(result["expected_value_of_perfect_information"]), Decimal(9))
        self.assertEqual(result["authority"], "RECOMMEND_ONLY")

    def test_missing_evidence_does_not_invent_probability(self) -> None:
        problem = DecisionProblem("What is the chance?", {}, {"act": {}}, ())
        with self.assertRaisesRegex(InsufficientEvidence, "INSUFFICIENT_EVIDENCE"):
            evaluate_decision(problem)

    def test_model_text_cannot_be_evidence(self) -> None:
        with self.assertRaises(InsufficientEvidence):
            Evidence("JARVIS said so", datetime.now(timezone.utc), EvidenceKind.MODEL_CONTENT)
        with self.assertRaises(ValueError):
            Evidence("JARVIS said so", datetime.now(timezone.utc), "OBSERVED")

    def test_bad_probability_and_mismatched_states_fail(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_decision(DecisionProblem("bad", {"a": "0.6", "b": "0.3"}, {"x": {"a": 1, "b": 2}}, (SOURCE,)))
        with self.assertRaises(ValueError):
            evaluate_decision(DecisionProblem("bad", {"a": 1}, {"x": {"b": 1}}, (SOURCE,)))

    def test_receipt_reproducible(self) -> None:
        problem = DecisionProblem("repeat", {"a": "0.4", "b": "0.6"}, {"x": {"a": 1, "b": 2}}, (SOURCE,))
        self.assertEqual(evaluate_decision(problem)["receipt"]["input_sha256"], evaluate_decision(problem)["receipt"]["input_sha256"])

    def test_extreme_decimal_does_not_overflow_analytic_path(self) -> None:
        problem = DecisionProblem("large utility", {"a": 1}, {"x": {"a": "1e400"}}, (SOURCE,))
        self.assertEqual(Decimal(evaluate_decision(problem)["actions"]["x"]["expected_utility"]), Decimal("1E+400"))


if __name__ == "__main__":
    unittest.main()
