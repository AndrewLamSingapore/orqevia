import unittest
from app.portal_integration import build_experiment_spec


class ApprovalInvariantTests(unittest.TestCase):
    def test_even_provenance_bearing_candidate_is_not_auto_approved(self):
        candidate = {
            "schema_version": "1.0", "candidate_id": "PTL-EXP-SAFETY-1", "source": "the-portal",
            "title": "Safety invariant", "question": "Should this execute?", "hypothesis": "Test only.",
            "node_ids": [], "concepts": ["velyqua"], "provenance": ["verified source packet"],
            "evidence_boundary": "Evidence does not grant authority.", "status": "accepted"
        }
        spec = build_experiment_spec(candidate)
        self.assertEqual(spec["approval_state"], "verified")
        self.assertNotEqual(spec["approval_state"], "approved")
        self.assertTrue(any("Human approval" in x for x in spec["safety_constraints"]))


if __name__ == "__main__": unittest.main()
