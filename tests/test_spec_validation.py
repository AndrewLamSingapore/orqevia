import unittest
from app.portal_integration import validate_experiment_spec

class SpecValidationTests(unittest.TestCase):
    def test_missing_required_rejected(self):
        with self.assertRaises(ValueError): validate_experiment_spec({})
    def test_approved_is_valid_contract_state_but_not_generator_default(self):
        spec={"schema_version":"1.0","experiment_id":"PRM-EXP-X1","candidate_id":"PTL-EXP-X1","source":"prime","objective":"x","method":"y","evidence_requirements":["z"],"approval_state":"approved"}
        self.assertEqual(validate_experiment_spec(spec)["approval_state"],"approved")

if __name__=="__main__": unittest.main()
