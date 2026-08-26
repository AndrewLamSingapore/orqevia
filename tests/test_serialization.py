import json, unittest
from app.portal_integration import build_experiment_spec, serialize_record
class SerializationTests(unittest.TestCase):
    def test_record_serializes(self):
        c={"schema_version":"1.0","candidate_id":"PTL-EXP-SER-1","source":"the-portal","title":"S","question":"Q?","hypothesis":None,"node_ids":[],"concepts":[],"provenance":[],"evidence_boundary":"B","status":"proposed"}
        decoded=json.loads(serialize_record(c,build_experiment_spec(c)))
        self.assertEqual(decoded["candidate"]["candidate_id"],"PTL-EXP-SER-1")
if __name__=="__main__": unittest.main()
