"""Bounded advisory gateway and proactive-proposal tests; no network or execution."""

import unittest

from app.hyper_inference.bounded_proactive import capability_summary as proactive_summary
from app.hyper_inference.bounded_proactive import propose
from app.hyper_inference.internet_gateway import capability_summary as gateway_summary
from app.hyper_inference.internet_gateway import fetch_text


class InternetGatewayTests(unittest.TestCase):
    def test_gateway_fails_closed_without_allowlist(self):
        result = fetch_text("https://example.com/page")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "ALLOWLIST_DENIED")
        self.assertEqual(result["execution"], "ADVISORY_ONLY")

    def test_gateway_rejects_non_https_and_credentials(self):
        for url in ("http://example.com", "https://user:pass@example.com"):
            result = fetch_text(url)
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "ALLOWLIST_DENIED")

    def test_capability_summaries_are_qualified_and_non_authoritative(self):
        self.assertEqual(gateway_summary()["status"], "QUALIFIED")
        self.assertEqual(gateway_summary()["authority"], "ADVISORY_ONLY")
        self.assertFalse(gateway_summary()["credentials_accepted"])
        self.assertEqual(proactive_summary()["status"], "QUALIFIED")
        self.assertEqual(proactive_summary()["authority"], "PROPOSAL_ONLY")
        self.assertFalse(proactive_summary()["execution_allowed"])


class BoundedProactiveTests(unittest.TestCase):
    def test_proposals_are_bounded_deterministic_and_never_execute(self):
        first = propose("Verify the measured profile", "context")
        second = propose("Verify the measured profile", "context")
        self.assertTrue(first["ok"])
        self.assertEqual(first, second)
        self.assertLessEqual(len(first["proposals"]), 3)
        for item in first["proposals"]:
            self.assertTrue(item["required_approval"])
            self.assertEqual(item["execution"], "FORBIDDEN_WITHOUT_OWNER_APPROVAL")
        self.assertEqual(first["execution"], "FORBIDDEN_WITHOUT_OWNER_APPROVAL")

    def test_invalid_inputs_fail_bounded(self):
        self.assertFalse(propose("", "")["ok"])
        self.assertFalse(propose("objective", limit=9)["ok"])


if __name__ == "__main__":
    unittest.main()
