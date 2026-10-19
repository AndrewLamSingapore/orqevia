import os
import tempfile
import unittest

_TMP = tempfile.TemporaryDirectory()
os.environ["ORQEVIA_DATA_DIR"] = _TMP.name

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import portal_api
app = FastAPI(); app.include_router(portal_api.router)


PAYLOAD = {
    "candidate": {
        "schema_version": "1.0",
        "candidate_id": "PTL-EXP-API-001",
        "source": "the-portal",
        "title": "Aquarium sensor experiment",
        "question": "Can continuous signals improve early warning?",
        "hypothesis": "Sensor fusion may improve early warning.",
        "node_ids": ["PTL-A"],
        "concepts": ["aquarium", "sensor"],
        "provenance": ["source-supported baseline"],
        "evidence_boundary": "No physical outcome has yet been demonstrated.",
        "status": "proposed"
    }
}


class PortalApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_ingest_get_and_idempotency(self):
        first = self.client.post("/api/integrations/portal/experiments", json=PAYLOAD)
        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        self.assertFalse(body["idempotent"])
        self.assertEqual(body["experiment_spec"]["target_system"], "velyqua")
        self.assertNotEqual(body["experiment_spec"]["approval_state"], "approved")

        second = self.client.post("/api/integrations/portal/experiments", json=PAYLOAD)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["idempotent"])

        fetched = self.client.get("/api/integrations/portal/experiments/PTL-EXP-API-001")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["experiment_spec"]["experiment_id"], body["experiment_spec"]["experiment_id"])

    def test_rejects_untrusted_source(self):
        bad = {"candidate": dict(PAYLOAD["candidate"], source="other")}
        response = self.client.post("/api/integrations/portal/experiments", json=bad)
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
