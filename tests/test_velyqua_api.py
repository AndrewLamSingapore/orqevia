import os
import tempfile
import unittest

_TMP = tempfile.TemporaryDirectory()
os.environ["PRIME_DATA_DIR"] = _TMP.name
os.environ["PRIME_INTEGRATION_TOKEN"] = "test-integration-token"
os.environ.pop("PORTAL_RESULT_URL", None)
os.environ.pop("PORTAL_RESULT_TOKEN", None)

from fastapi.testclient import TestClient
from app.entry import app


AUTH = {"Authorization": "Bearer test-integration-token"}
CANDIDATE = {
    "candidate": {
        "schema_version": "1.0",
        "candidate_id": "PTL-EXP-CLOSED-LOOP-001",
        "source": "the-portal",
        "title": "Bounded aquarium observation",
        "question": "Can attributable observations be returned to the graph?",
        "hypothesis": "The protocol can preserve provenance.",
        "node_ids": ["PTL-A"],
        "concepts": ["aquarium", "sensor"],
        "provenance": ["protocol:test-fixture"],
        "evidence_boundary": "This fixture proves protocol flow, not a physical hypothesis.",
        "status": "proposed",
    }
}


class VelyquaApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        response = self.client.post("/api/integrations/portal/experiments", json=CANDIDATE)
        self.assertEqual(response.status_code, 200, response.text)
        self.spec = response.json()["experiment_spec"]

    def event(self, state, operation_id):
        approval = None
        if state in {"approved_for_observation", "collecting_evidence", "completed"}:
            approval = {
                "owner_id": "owner-1",
                "approved_at": "2026-08-28T03:00:00Z",
                "scope": "observation_only",
                "provenance": ["owner-confirmation:ui"],
            }
        execution = {
            "experiment_id": self.spec["experiment_id"],
            "candidate_id": self.spec["candidate_id"],
            "state": state,
            "objective": self.spec["objective"],
            "evidence_requirements": self.spec["evidence_requirements"],
            "owner_approval": approval,
            "created_at": self.spec["created_at"],
        }
        return {
            "event": {
                "schema_version": "1.0",
                "operation_id": operation_id,
                "account_id": "owner-1",
                "aggregate_type": "experiment_execution",
                "aggregate_id": self.spec["experiment_id"],
                "event_type": f"experiment_execution.{state}",
                "payload": execution,
                "occurred_at": "2026-08-28T03:00:00Z",
            }
        }

    def post(self, payload):
        return self.client.post("/api/integrations/velyqua/events", json=payload, headers=AUTH)

    def test_end_to_end_evaluation_and_idempotency(self):
        for state, operation in [
            ("awaiting_owner_approval", "op-awaiting"),
            ("approved_for_observation", "op-approved"),
            ("collecting_evidence", "op-collecting"),
        ]:
            response = self.post(self.event(state, operation))
            self.assertEqual(response.status_code, 200, response.text)

        observation = {
            "schema_version": "1.0",
            "observation_id": "VLY-OBS-CLOSED-LOOP-001",
            "source": "velyqua",
            "experiment_id": self.spec["experiment_id"],
            "tank_id": "tank-1",
            "observed_at": "2026-08-28T03:05:00Z",
            "kind": "sensor",
            "metric": "temperature",
            "value": 27.1,
            "unit": "C",
            "evidence_level": "raw",
            "provenance": ["edge-node:test-probe"],
            "notes": None,
        }
        observation_event = {"event": {
            "schema_version": "1.0",
            "operation_id": "op-observed",
            "account_id": "owner-1",
            "aggregate_type": "observation",
            "aggregate_id": observation["observation_id"],
            "event_type": "observation.recorded",
            "payload": observation,
            "occurred_at": observation["observed_at"],
        }}
        observed = self.post(observation_event)
        self.assertEqual(observed.status_code, 200, observed.text)
        replay = self.post(observation_event)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["idempotent"])

        completed = self.post(self.event("completed", "op-completed"))
        self.assertEqual(completed.status_code, 200, completed.text)
        result = completed.json()["evaluation"]
        self.assertEqual(result["conclusion"], "evidence_collected")
        self.assertEqual(result["evidence_summary"]["observation_count"], 1)
        self.assertFalse(result["safety"]["actuation_authorized"])
        self.assertEqual(completed.json()["portal_delivery"]["status"], "not_configured")

        fetched = self.client.get(
            f"/api/integrations/velyqua/evaluations/{self.spec['experiment_id']}", headers=AUTH
        )
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["result"]["result_id"], result["result_id"])

    def test_rejects_invalid_token(self):
        response = self.client.post(
            "/api/integrations/velyqua/events",
            json=self.event("awaiting_owner_approval", "op-auth"),
            headers={"Authorization": "Bearer wrong"},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
