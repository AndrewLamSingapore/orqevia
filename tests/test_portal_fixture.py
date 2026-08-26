import json
import unittest
from pathlib import Path

from app.portal_integration import build_experiment_spec, validate_experiment_candidate, validate_experiment_spec


class RealPortalFixtureTests(unittest.TestCase):
    def test_aquarium_candidate_emits_valid_velyqua_spec(self):
        payload = json.loads(Path("contracts/examples/portal-aquarium-candidate.json").read_text())
        candidate = validate_experiment_candidate(payload)
        spec = validate_experiment_spec(build_experiment_spec(candidate))
        self.assertEqual(spec["target_system"], "velyqua")
        self.assertEqual(spec["approval_state"], "verified")
        self.assertEqual(spec["verification"]["verdict"], "pass")
        self.assertIn("Human approval is required before execution outside PRIME.", spec["safety_constraints"])


if __name__ == "__main__":
    unittest.main()
