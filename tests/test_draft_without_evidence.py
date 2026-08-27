import unittest
from app.portal_integration import build_experiment_spec

class DraftTests(unittest.TestCase):
    def test_no_provenance_means_draft(self):
        c={"schema_version":"1.0","candidate_id":"PTL-EXP-DRAFT-1","source":"the-portal","title":"Draft","question":"Test?","hypothesis":None,"node_ids":[],"concepts":[],"provenance":[],"evidence_boundary":"No evidence attached.","status":"proposed"}
        s=build_experiment_spec(c)
        self.assertEqual(s["approval_state"],"draft")
        self.assertNotEqual(s["approval_state"],"approved")

if __name__=="__main__": unittest.main()
