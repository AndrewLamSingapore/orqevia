import os
import tempfile
import unittest

from fastapi.testclient import TestClient

_TMP = tempfile.TemporaryDirectory()
os.environ["PRIME_DATA_DIR"] = _TMP.name
os.environ["PRIME_SPINE_DB"] = os.path.join(_TMP.name, "spine.db")
os.environ["PRIME_HARNESS_DB"] = os.path.join(_TMP.name, "harness.db")
os.environ["PRIME_COMPUTE_QUEUE_DB"] = os.path.join(_TMP.name, "queue.db")
os.environ["PRIME_SPINE_TOKEN"] = "test-owner-token"
os.environ["PRIME_HARNESS_PILOT_ENABLED"] = "1"
os.environ["PRIME_QUEUE_CONCURRENCY"] = "1"

from app import compute_queue_api, harness_api, spine_api
from app.entry import app
from app.job_queue import JobQueue, QueuePolicy
from app.spine import SpineStore, StableSpine


class HarnessApiTests(unittest.TestCase):
    def setUp(self):
        self.case = tempfile.TemporaryDirectory()
        os.environ["PRIME_HARNESS_DB"] = os.path.join(self.case.name, "harness.db")
        harness_api._runtime_cache = None
        harness_api._runtime_fingerprint = None
        spine_api.spine = StableSpine(SpineStore(os.path.join(self.case.name, "spine.db")))
        compute_queue_api.queue = JobQueue(
            os.path.join(self.case.name, "queue.db"),
            QueuePolicy(global_concurrency=1),
        )
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-owner-token"}

    def tearDown(self):
        self.case.cleanup()

    def test_pilot_dispatch_traverses_spine_harness_and_local_queue(self):
        response = self.client.post(
            "/api/harness/pilot/dispatch",
            headers=self.headers,
            json={
                "actor_id": "a14",
                "prompt": "Check this dataset for duplicate identifiers.",
                "priority": "high",
                "model_role": "fast",
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body["job"]["agent"], "a14")
        self.assertEqual(body["job"]["status"], "queued")
        self.assertEqual(body["harness"]["status"], "QUEUED")
        self.assertFalse(body["cloud_allowed"])
        status = self.client.get("/api/harness/status", headers=self.headers).json()
        self.assertTrue(status["ready"])
        self.assertEqual(status["local_concurrency"], 1)
        self.assertFalse(status["acceptance_ready"])
        self.assertEqual(status["counts"], {"authorized": 1, "queued": 1, "started": 0,
                         "completed": 0, "verified": 0, "uncertain": 0, "legacy_consumed": 0, "revoked": 0})

    def test_non_pilot_actor_is_denied(self):
        response = self.client.post(
            "/api/harness/pilot/dispatch",
            headers=self.headers,
            json={"actor_id": "a17", "prompt": "Write code."},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(compute_queue_api.queue.list(), [])

    def test_duplicate_spine_idempotency_key_is_denied(self):
        payload = {
            "actor_id": "a16",
            "prompt": "Review this architecture.",
            "idempotency_key": "same-request",
        }
        first = self.client.post("/api/harness/pilot/dispatch", headers=self.headers, json=payload)
        second = self.client.post("/api/harness/pilot/dispatch", headers=self.headers, json=payload)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 409, second.text)
        self.assertEqual(len(compute_queue_api.queue.list()), 1)

    def test_owner_token_and_enabled_runtime_are_required(self):
        self.assertEqual(self.client.get("/api/harness/status").status_code, 401)
        os.environ["PRIME_HARNESS_PILOT_ENABLED"] = "0"
        try:
            self.assertEqual(
                self.client.get("/api/harness/status", headers=self.headers).status_code,
                503,
            )
        finally:
            os.environ["PRIME_HARNESS_PILOT_ENABLED"] = "1"

    def test_direct_queue_route_cannot_bypass_harness_for_pilot(self):
        response = self.client.post(
            "/api/compute-queue/jobs",
            headers=self.headers,
            json={"agent": "a21", "prompt": "Estimate cost."},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(compute_queue_api.queue.list(), [])


if __name__ == "__main__":
    unittest.main()
