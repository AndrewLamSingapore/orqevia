import json
import unittest
from pathlib import Path

from app.portal_integration import build_experiment_spec


class ExpectedFixtureTests(unittest.TestCase):
    def test_expected_semantics(self):
        candidate = json.loads(Path("contracts/examples/portal-aquarium-candidate.json").read_text())
        expected = json.loads(Path("contracts/examples/expected-experiment-spec.json").read_text())
        spec = build_experiment_spec(candidate)
        self.assertEqual(spec["candidate_id"], expected["candidate_id"])
        self.assertEqual(spec["source"], expected["source"])
        self.assertEqual(spec["target_system"], expected["target_system"])
        self.assertEqual(spec["approval_state"], expected["approval_state"])
        self.assertEqual(spec["verification"]["verdict"], expected["verification_verdict"])
        self.assertEqual(any("Human approval" in x for x in spec["safety_constraints"]), expected["requires_human_approval"])


if __name__ == "__main__":
    unittest.main()
