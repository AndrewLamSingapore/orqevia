import json
import unittest
from pathlib import Path

from app.portal_integration import build_experiment_spec


class ContractFileTests(unittest.TestCase):
    def test_emitted_spec_satisfies_repository_contract(self):
        schema = json.loads(Path("contracts/experiment-spec.schema.json").read_text())
        candidate = {
            "schema_version": "1.0", "candidate_id": "PTL-EXP-CONTRACT-1", "source": "the-portal",
            "title": "Contract test", "question": "Does the handoff validate?", "hypothesis": None,
            "node_ids": [], "concepts": [], "provenance": ["fixture"],
            "evidence_boundary": "Fixture only.", "status": "proposed"
        }
        spec = build_experiment_spec(candidate)
        for key in schema["required"]:
            self.assertIn(key, spec)
        self.assertEqual(spec["schema_version"], schema["properties"]["schema_version"]["const"])
        self.assertEqual(spec["source"], schema["properties"]["source"]["const"])
        self.assertIn(spec["approval_state"], schema["properties"]["approval_state"]["enum"])


if __name__ == "__main__":
    unittest.main()
