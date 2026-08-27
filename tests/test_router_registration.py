import os, tempfile, unittest
_TMP=tempfile.TemporaryDirectory(); os.environ["PRIME_DATA_DIR"]=_TMP.name
from app.entry import app

class RouterTests(unittest.TestCase):
    def test_routes_registered(self):
        paths={r.path for r in app.routes}
        self.assertIn("/api/integrations/portal/experiments",paths)
        self.assertIn("/api/integrations/portal/experiments/{candidate_id}",paths)

if __name__=="__main__": unittest.main()
