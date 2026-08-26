import unittest
from app.portal_integration import build_experiment_spec

BASE={"schema_version":"1.0","candidate_id":"PTL-EXP-TARGET-1","source":"the-portal","title":"Target","question":"Where?","hypothesis":None,"node_ids":[],"provenance":["fixture"],"evidence_boundary":"Fixture.","status":"proposed"}
class TargetTests(unittest.TestCase):
    def test_aquarium_targets_velyqua(self): self.assertEqual(build_experiment_spec(dict(BASE,concepts=["aquarium"]))["target_system"],"velyqua")
    def test_unrelated_candidate_has_no_target(self): self.assertIsNone(build_experiment_spec(dict(BASE,candidate_id="PTL-EXP-TARGET-2",concepts=["history"]))["target_system"])
if __name__=="__main__": unittest.main()
