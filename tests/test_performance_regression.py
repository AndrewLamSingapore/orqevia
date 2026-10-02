"""Offline regression checks for benchmark receipt comparison."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmarks.performance_regression import EvidenceError, compare


class PerformanceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.before = {"model": "gemma3:4b", "timing": {"first_token_ms": [100, 102, 98, 101, 99], "tokens_per_s": 10}}
        self.after = {"model": "gemma3:4b", "timing": {"first_token_ms": [103, 104, 101, 102, 100], "tokens_per_s": 9.5}}
        self.policy = {"schema_version": 1, "comparability": ["model"], "metrics": [
            {"path": "timing.first_token_ms", "direction": "lower", "aggregate": "median", "min_samples": 5, "relative_tolerance": 0.05},
            {"path": "timing.tokens_per_s", "direction": "higher", "relative_tolerance": 0.05},
        ]}

    def test_within_noise_envelope(self):
        receipt = compare(self.before, self.after, self.policy)
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["metrics"][0]["before_samples"], 5)

    def test_real_regression_fails(self):
        self.after["timing"]["first_token_ms"] = [115] * 5
        receipt = compare(self.before, self.after, self.policy)
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["metrics"][0]["passed"])

    def test_missing_null_boolean_and_nonfinite_fail_closed(self):
        for value in (None, True, float("inf"), "unknown"):
            with self.subTest(value=value):
                self.after["timing"]["tokens_per_s"] = value
                with self.assertRaises(EvidenceError):
                    compare(self.before, self.after, self.policy)
        del self.after["timing"]["tokens_per_s"]
        with self.assertRaises(EvidenceError):
            compare(self.before, self.after, self.policy)

    def test_mismatched_model_is_incomparable(self):
        self.after["model"] = "another-model"
        with self.assertRaisesRegex(EvidenceError, "incomparable"):
            compare(self.before, self.after, self.policy)

    def test_sample_floor_and_p95(self):
        self.policy["metrics"] = [{"path": "timing.first_token_ms", "direction": "lower", "aggregate": "p95", "min_samples": 5}]
        receipt = compare(self.before, self.after, self.policy)
        self.assertEqual(receipt["metrics"][0]["before"], 102)
        self.after["timing"]["first_token_ms"] = [100, 101]
        with self.assertRaisesRegex(EvidenceError, "requires 5"):
            compare(self.before, self.after, self.policy)

    def test_absolute_tolerance_at_zero_and_negative_values(self):
        before = {"delta": 0, "score": -10}
        after = {"delta": 0.2, "score": -10.4}
        policy = {"schema_version": 1, "metrics": [
            {"path": "delta", "direction": "lower", "absolute_tolerance": 0.25},
            {"path": "score", "direction": "higher", "relative_tolerance": 0.05},
        ]}
        self.assertTrue(compare(before, after, policy)["passed"])

    def test_rejects_invalid_policy(self):
        for change in ({"metrics": []}, {"schema_version": 2}, {"metrics": [{"path": "x", "direction": "bad"}]}):
            with self.subTest(change=change):
                with self.assertRaises(EvidenceError):
                    compare(self.before, self.after, {**self.policy, **change})

    def test_cli_exit_codes(self):
        script = Path(__file__).resolve().parents[1] / "benchmarks" / "performance_regression.py"
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("before.json", "after.json", "policy.json")]
            for path, document in zip(paths, (self.before, self.after, self.policy)):
                path.write_text(json.dumps(document), encoding="utf-8")
            command = [sys.executable, str(script), *(str(path) for path in paths)]
            self.assertEqual(subprocess.run(command, capture_output=True, text=True).returncode, 0)
            self.after["timing"]["tokens_per_s"] = 8
            paths[1].write_text(json.dumps(self.after), encoding="utf-8")
            self.assertEqual(subprocess.run(command, capture_output=True, text=True).returncode, 1)
            self.after["timing"]["tokens_per_s"] = None
            paths[1].write_text(json.dumps(self.after), encoding="utf-8")
            self.assertEqual(subprocess.run(command, capture_output=True, text=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
