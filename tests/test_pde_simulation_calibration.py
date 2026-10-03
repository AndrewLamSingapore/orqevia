from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.pde import DecisionProblem, Evidence, EvidenceKind
from app.pde.calibration import ForecastLedger
from app.pde.simulation import simulate_decision, verify_analytic_with_simulation


SOURCE = Evidence("fixture:fair-coin", datetime(2026, 10, 2, tzinfo=timezone.utc), EvidenceKind.ASSUMED)


class SimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.problem = DecisionProblem("Fair coin", {"heads": "0.5", "tails": "0.5"}, {"bet": {"heads": 1, "tails": -1}}, (SOURCE,))

    def test_seed_reproducibility(self) -> None:
        self.assertEqual(simulate_decision(self.problem, samples=1000, seed=7), simulate_decision(self.problem, samples=1000, seed=7))

    def test_analytic_cross_check(self) -> None:
        result = verify_analytic_with_simulation(self.problem, samples=10000, seed=4)
        self.assertEqual(result["status"], "AGREE")
        self.assertEqual(result["comparisons"]["bet"]["analytic"], 0)

    def test_resource_bound(self) -> None:
        with self.assertRaises(ValueError):
            simulate_decision(self.problem, samples=10_000_000)
        extreme = DecisionProblem("huge", {"a": 1}, {"x": {"a": "1e400"}}, (SOURCE,))
        with self.assertRaises(ValueError):
            simulate_decision(extreme, samples=100)


class CalibrationTests(unittest.TestCase):
    def test_known_brier_and_leakage_guard(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = ForecastLedger(Path(directory) / "forecast.sqlite")
            issued = datetime(2026, 10, 1, tzinfo=timezone.utc)
            ledger.record_forecast("f1", "Coin is heads", "0.75", issued, "fixture")
            self.assertEqual(ledger.scores()["status"], "INSUFFICIENT_EVIDENCE")
            with self.assertRaises(ValueError):
                ledger.record_outcome("f1", True, issued)
            ledger.record_outcome("f1", True, issued + timedelta(days=1))
            reopened = ForecastLedger(Path(directory) / "forecast.sqlite")
            self.assertEqual(reopened.scores()["brier_score"], 0.0625)
            self.assertEqual(reopened.scores()["count"], 1)
            self.assertFalse(reopened.scores()["calibrated"])
            with self.assertRaises(ValueError):
                reopened.record_outcome("f1", False, issued + timedelta(days=2))


if __name__ == "__main__":
    unittest.main()
