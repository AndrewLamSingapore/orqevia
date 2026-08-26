import unittest

from app.portal_integration import build_experiment_spec, route_candidate, validate_experiment_candidate, validate_experiment_spec


def candidate(**overrides):
    value = {
        "schema_version": "1.0",
        "candidate_id": "PTL-EXP-AQUA-001",
        "source": "the-portal",
        "title": "Earlier aquarium risk detection",
        "question": "Can inexpensive continuous signals reveal aquarium risk earlier than periodic testing alone?",
        "hypothesis": "Sensor fusion can reveal developing risk earlier.",
        "node_ids": ["PTL-2026-AQUA"],
        "concepts": ["aquarium", "sensor", "ecology"],
        "provenance": ["VELYQUA physical hypothesis baseline"],
        "evidence_boundary": "Hypothesis is not scientifically validated.",
        "status": "proposed",
    }
    value.update(overrides)
    return value


class PortalIntegrationTests(unittest.TestCase):
    def test_valid_candidate_round_trip(self):
        c = validate_experiment_candidate(candidate())
        spec = validate_experiment_spec(build_experiment_spec(c))
        self.assertEqual(spec["candidate_id"], c["candidate_id"])
        self.assertTrue(spec["experiment_id"].startswith("PRM-EXP-"))
        self.assertEqual(spec["target_system"], "velyqua")
        self.assertEqual(spec["approval_state"], "verified")
        self.assertNotEqual(spec["approval_state"], "approved")

    def test_missing_provenance_stays_draft(self):
        spec = build_experiment_spec(candidate(provenance=[]))
        self.assertEqual(spec["approval_state"], "draft")
        self.assertEqual(spec["verification"]["verdict"], "not_run")
        self.assertTrue(spec["evidence_requirements"][0].startswith("EVIDENCE_REQUIRED"))

    def test_rejects_wrong_source(self):
        with self.assertRaises(ValueError):
            validate_experiment_candidate(candidate(source="other"))

    def test_rejects_unknown_fields(self):
        with self.assertRaises(ValueError):
            validate_experiment_candidate(candidate(authority="execute"))

    def test_specialist_routing_is_bounded(self):
        route = route_candidate(candidate())
        self.assertIn(route["specialist"], {"strategy", "research", "data", "engineering", "quality", "economic"})

    def test_deterministic_experiment_id(self):
        one = build_experiment_spec(candidate())
        two = build_experiment_spec(candidate())
        self.assertEqual(one["experiment_id"], two["experiment_id"])


if __name__ == "__main__":
    unittest.main()
