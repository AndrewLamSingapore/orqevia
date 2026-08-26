import unittest
from app.portal_integration import validate_experiment_candidate

BASE={"schema_version":"1.0","candidate_id":"PTL-EXP-EDGE-1","source":"the-portal","title":"Edge","question":"Valid?","hypothesis":None,"node_ids":[],"concepts":[],"provenance":[],"evidence_boundary":"Boundary.","status":"proposed"}

class CandidateEdgeTests(unittest.TestCase):
    def test_bad_id_rejected(self):
        with self.assertRaises(ValueError): validate_experiment_candidate(dict(BASE,candidate_id="bad"))
    def test_bad_version_rejected(self):
        with self.assertRaises(ValueError): validate_experiment_candidate(dict(BASE,schema_version="2.0"))
    def test_duplicate_concepts_normalized(self):
        result=validate_experiment_candidate(dict(BASE,concepts=["sensor","sensor"]))
        self.assertEqual(result["concepts"],["sensor"])

if __name__=="__main__": unittest.main()
