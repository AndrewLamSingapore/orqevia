import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from app.public_trace_publisher import PublicTracePublisher


class DummyAuthority:
    def public_snapshot(self, limit=100):
        return {
            "ok": True,
            "state": "verified_events",
            "generated_at": "2026-09-04T01:00:00Z",
            "summary": {
                "registered_agents": 29,
                "active_agents": 1,
                "executions_today": 3,
                "denied_handoffs_today": 1,
                "average_latency_ms": 12.5,
                "active_window_seconds": 300,
            },
            "events": [
                {
                    "trace_id": "trace-1",
                    "timestamp": "2026-09-04T01:00:00Z",
                    "agent_id": "A19",
                    "stage": "verification",
                    "status": "completed",
                    "sequence": 4,
                }
            ],
            "boundary": "sanitized runtime authority metadata only",
        }


class FakeResponse:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def all_keys(value):
    keys = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            keys.update(all_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(all_keys(child))
    return keys


class PublicTracePublisherTests(unittest.TestCase):
    def test_disabled_without_secret(self):
        publisher = PublicTracePublisher(DummyAuthority(), url="https://relay.example", secret="")
        self.assertFalse(publisher.enabled)
        self.assertEqual(publisher.publish_once()["state"], "disabled")

    def test_disabled_without_explicit_publisher_identity(self):
        with patch.dict(os.environ, {"PRIME_PUBLIC_TRACE_PUBLISHER_ID": ""}):
            publisher = PublicTracePublisher(DummyAuthority(), url="https://relay.example", secret="s" * 48)
        self.assertFalse(publisher.enabled)
        self.assertEqual(publisher.publish_once()["state"], "disabled")

    def test_signed_payload_contains_only_public_snapshot(self):
        captured = {}
        secret = "s" * 48

        def opener(request, timeout=20):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse({"ok": True, "accepted_events": 1})

        publisher = PublicTracePublisher(
            DummyAuthority(),
            url="https://relay.example/trace",
            secret=secret,
            publisher_id="prime-dell-1",
            opener=opener,
            clock=lambda: 1_788_484_800,
        )
        result = publisher.publish_once()
        self.assertEqual(result["accepted_events"], 1)

        request = captured["request"]
        body = request.data
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["events"][0]["agent_id"], "A19")
        forbidden_keys = {
            "prompt", "credentials", "endpoint", "result", "answer", "rationale",
            "claim_text", "evidence_text", "filesystem_path", "tool_secrets", "internal_instructions",
        }
        self.assertFalse(forbidden_keys.intersection(all_keys(payload)))
        self.assertNotIn(secret, body.decode("utf-8"))

        timestamp = request.get_header("X-jarvis-timestamp")
        expected = hmac.new(
            secret.encode("utf-8"),
            timestamp.encode("ascii") + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(request.get_header("X-jarvis-signature"), expected)
        self.assertEqual(request.get_header("X-jarvis-publisher"), "prime-dell-1")


if __name__ == "__main__":
    unittest.main()
