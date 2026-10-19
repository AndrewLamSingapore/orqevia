import os, tempfile, unittest
_TMP=tempfile.TemporaryDirectory(); os.environ["ORQEVIA_DATA_DIR"]=_TMP.name
from app.entry import app

class RouterTests(unittest.TestCase):
    def test_routes_registered(self):
        paths=set(app.openapi()["paths"])
        self.assertIn("/api/agents/dispatch",paths)
        self.assertIn("/api/agents/objectives",paths)
        self.assertIn("/api/compute-queue/jobs",paths)
        self.assertNotIn("/api/harness/pilot/dispatch",paths)
        self.assertNotIn("/api/integrations/portal/experiments",paths)

if __name__=="__main__": unittest.main()
