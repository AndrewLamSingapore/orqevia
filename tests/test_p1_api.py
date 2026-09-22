import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

# The composed runtime initializes its SQLite paths at import time. CI runners
# cannot write /data; keep this test isolated without changing production defaults.
_IMPORT_DATA = tempfile.TemporaryDirectory()
os.environ.setdefault("PRIME_DATA_DIR", _IMPORT_DATA.name)

from app import control_surface, spine_api
app = FastAPI(); app.include_router(control_surface.router)
from app.spine import SpineStore, StableSpine


def envelope(key="p1-api"):
    return {
        "tenant_id": "personal", "actor_id": "prime-core", "actor_type": "reasoner",
        "action": "email.send", "parameters": {"draft_id": "draft-1"},
        "context": {"title": "Send reviewed draft", "risk": "external", "source": "owner", "evidence": ["draft-1"], "reversibility": "not reversible", "expected_effect": "message delivered"},
        "correlation_id": "corr-p1-api", "idempotency_key": key, "schema_version": "1.0.0", "timestamp": "2026-08-31T00:00:00Z",
    }


class P1ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.original = spine_api.spine
        spine_api.spine = StableSpine(SpineStore(os.path.join(self.temp.name, "spine.db")))
        self.old_token = os.environ.get("PRIME_SPINE_TOKEN")
        os.environ["PRIME_SPINE_TOKEN"] = "p1-test-token"
        self.client = TestClient(app, base_url="http://127.0.0.1")
        spine_api.spine.evaluate(envelope(), {"source": "local_ai", "reasoning_route": ["local_ai", "confidence_gate"]})

    def tearDown(self):
        self.client.close()
        spine_api.spine = self.original
        if self.old_token is None:
            os.environ.pop("PRIME_SPINE_TOKEN", None)
        else:
            os.environ["PRIME_SPINE_TOKEN"] = self.old_token

    def test_trusted_approval_card_modify_and_audit_trace(self):
        cards = self.client.get("/api/control-surface/trusted/approvals").json()["approvals"]
        self.assertEqual(cards[0]["risk"], "external")
        response = self.client.post("/api/control-surface/trusted/approvals/p1-api", json={"decision": "modify", "note": "remove external recipient", "modifications": {"recipient": None}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["approval"]["status"], "MODIFIED")
        trace = self.client.get("/api/control-surface/trusted/audit-explorer").json()["traces"][0]
        self.assertEqual(trace["approval"]["status"], "MODIFIED")
        self.assertEqual(trace["result"]["execution_status"], "PENDING_APPROVAL")

    def test_cross_origin_decision_is_denied(self):
        response = self.client.post("/api/control-surface/trusted/approvals/p1-api", headers={"Origin": "https://example.com"}, json={"decision": "approve"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
