import os, tempfile, unittest
_TMP=tempfile.TemporaryDirectory(); os.environ["ORQEVIA_DATA_DIR"]=_TMP.name
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import portal_api
app = FastAPI(); app.include_router(portal_api.router)

class CandidateStateTests(unittest.TestCase):
    def test_rejected_candidate_cannot_enter_runtime(self):
        payload={"candidate":{"schema_version":"1.0","candidate_id":"PTL-EXP-REJECT-1","source":"the-portal","title":"Rejected","question":"No execution?","hypothesis":None,"node_ids":[],"concepts":[],"provenance":[],"evidence_boundary":"Rejected upstream.","status":"rejected"}}
        response=TestClient(app).post("/api/integrations/portal/experiments",json=payload)
        self.assertEqual(response.status_code,422)

if __name__=="__main__": unittest.main()
