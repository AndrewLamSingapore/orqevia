"""Offline boundary tests; no credentials or external API calls."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import deepseek_review as review


class ReviewBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.packet = self.root / "packet.txt"
        self.packet.write_text("Synthetic non-sensitive review packet.", encoding="utf-8")
        self.digest = hashlib.sha256(self.packet.read_bytes()).hexdigest()
        self.args = ["--input", str(self.packet), "--input-sha256", self.digest,
                     "--candidate-sha", "a" * 40, "--output-dir", str(self.root / "output")]

    def test_dry_run_never_reads_key_or_builds_network_client(self):
        original_get = review.os.environ.get
        def checked_get(name, default=None):
            if name == "DEEPSEEK_API_KEY":
                raise AssertionError("credential accessed")
            return original_get(name, default)
        with patch.object(review.os.environ, "get", side_effect=checked_get), \
             patch.object(review.urllib.request, "build_opener", side_effect=AssertionError("network")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(review.main(self.args), 0)
        self.assertEqual(json.loads(output.getvalue())["state"], "DRY_RUN")
        self.assertFalse((self.root / "output").exists())

    def test_changed_input_is_blocked_before_network(self):
        self.packet.write_text("tampered", encoding="utf-8")
        with patch.object(review.urllib.request, "build_opener", side_effect=AssertionError("network")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(review.main(self.args + ["--send"]), 2)
        self.assertIn("digest mismatch", output.getvalue())

    def test_redirect_refuses_credential_forwarding(self):
        with self.assertRaises(review.ReviewError):
            review.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://attacker.invalid")

    def test_tool_call_output_cannot_become_review_or_execution(self):
        with self.assertRaises(review.ReviewError):
            review.response_text({"status": "completed", "output": [{"type": "function_call", "name": "promote"}]})

    def test_incomplete_answer_not_accepted(self):
        with self.assertRaises(review.ReviewError):
            review.response_text({"status": "incomplete", "output": [{"type": "message", "content": [{"type": "output_text", "text": "PASS"}]}]})

    def test_malformed_content_not_accepted(self):
        with self.assertRaises(review.ReviewError):
            review.response_text({"status": "completed", "output": [{"type": "message", "content": "bad"}]})

    def test_advice_is_unproven_and_existing_artifacts_are_preserved(self):
        body = json.dumps({"status": "completed", "model": "deepseek-flash", "output": [
            {"type": "reasoning", "text": "not retained"},
            {"type": "message", "content": [{"type": "output_text", "text": "Hypothesis requiring reproduction."}]},
        ]}).encode()
        with patch.dict(review.os.environ, {"DEEPSEEK_API_KEY": "synthetic-test-placeholder"}), \
             patch.object(review.urllib.request, "build_opener") as make_opener, \
             contextlib.redirect_stdout(io.StringIO()):
            make_opener.return_value.open.return_value.__enter__.return_value.read.return_value = body
            self.assertEqual(review.main(self.args + ["--send"]), 0)
            first = next((self.root / "output").glob("*/advisory.txt"))
            original = first.read_bytes()
            self.assertEqual(review.main(self.args + ["--send"]), 0)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(len(list((self.root / "output").iterdir())), 2)
        for receipt in (self.root / "output").glob("*/result.json"):
            data = json.loads(receipt.read_text())
            self.assertEqual(data["classification"], "UNPROVEN")
            self.assertEqual(data["authority"], "ADVISORY_ONLY")
            self.assertFalse(data["candidate_integrity_proven"])


if __name__ == "__main__":
    unittest.main()
