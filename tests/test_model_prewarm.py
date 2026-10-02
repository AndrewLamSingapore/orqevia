"""No-network tests for the optional prewarm candidate."""

import threading
import time
import unittest
from unittest.mock import patch

from app.model_prewarm import _prewarm, start_optional_prewarm
from app.settings import PrimeSettings


def settings():
    return PrimeSettings(
        ollama_base_url="http://ollama:11434", fast_model="gemma3:4b",
        deep_model="gemma3:12b", embedding_model="embeddinggemma:300m",
        multi_specialist_workers=2, keep_alive="30m",
    )


class ModelPrewarmTests(unittest.TestCase):
    def test_disabled_by_default_creates_no_work(self):
        invoked = threading.Event()
        handle = start_optional_prewarm(settings(), {}, probe=lambda *_: invoked.set())
        self.assertEqual(handle.status, "disabled")
        self.assertTrue(handle.done.is_set())
        self.assertFalse(invoked.is_set())

    def test_only_exact_opt_in(self):
        for value in ("true", "yes", "0", " 1 "):
            with self.subTest(value=value):
                handle = start_optional_prewarm(settings(), {"PRIME_PREWARM_ENABLED": value}, probe=lambda *_: self.fail("probe ran"))
                self.assertEqual(handle.status, "disabled")

    def test_nonblocking_success_and_single_probe(self):
        release = threading.Event()
        calls = []

        def probe(config, model, keep_alive, timeout):
            calls.append((model, keep_alive, timeout))
            release.wait(1)

        start = time.monotonic()
        handle = start_optional_prewarm(settings(), {"PRIME_PREWARM_ENABLED": "1"}, probe=probe)
        self.assertLess(time.monotonic() - start, 0.2)
        release.set()
        self.assertTrue(handle.done.wait(2))
        self.assertEqual(handle.status, "completed")
        self.assertEqual(calls, [("gemma3:12b", "30m", 10.0)])

    def test_explicit_selector_can_choose_fast_or_evaluator(self):
        for selector, expected in (("fast", "gemma3:4b"), ("evaluator", "gemma3:12b")):
            with self.subTest(selector=selector):
                calls = []
                handle = start_optional_prewarm(
                    settings(), {"PRIME_PREWARM_ENABLED": "1", "PRIME_PREWARM_MODEL": selector},
                    probe=lambda _settings, model, _keep_alive, _timeout: calls.append(model),
                )
                self.assertTrue(handle.done.wait(2))
                self.assertEqual(handle.status, "completed")
                self.assertEqual(calls, [expected])

    def test_rejects_unconfigured_model_and_unsafe_residence(self):
        for selector, residence in (("gemma3:70b", "30m"), ("deep", "0"), ("deep", "3h")):
            with self.subTest(selector=selector, residence=residence):
                candidate = settings()
                object.__setattr__(candidate, "keep_alive", residence)
                handle = start_optional_prewarm(
                    candidate, {"PRIME_PREWARM_ENABLED": "1", "PRIME_PREWARM_MODEL": selector},
                    probe=lambda *_: self.fail("probe ran"),
                )
                self.assertEqual(handle.status, "failed")
                self.assertEqual(handle.error_type, "InvalidConfiguration")
                self.assertTrue(handle.done.is_set())

    def test_probe_failure_is_not_raised_or_logged(self):
        def probe(*_):
            raise PermissionError("secret-bearing endpoint")

        handle = start_optional_prewarm(settings(), {"PRIME_PREWARM_ENABLED": "1"}, probe=probe)
        self.assertTrue(handle.done.wait(2))
        self.assertEqual(handle.status, "failed")
        self.assertEqual(handle.error_type, "PermissionError")
        self.assertNotIn("endpoint", repr(handle))

    def test_supervisor_timeout_does_not_block_shutdown(self):
        release = threading.Event()
        with patch("app.model_prewarm.MAX_WALL_SECONDS", 0.01):
            handle = start_optional_prewarm(settings(), {"PRIME_PREWARM_ENABLED": "1"}, probe=lambda *_: release.wait(1))
            self.assertTrue(handle.done.wait(1))
        self.assertEqual(handle.status, "timed_out")
        release.set()

    def test_preflight_prevents_absent_model_load(self):
        with patch("app.model_prewarm._json_request", return_value={"models": [{"name": "other:1b"}]}) as request:
            with self.assertRaises(LookupError):
                _prewarm(settings(), "gemma3:12b", "30m", 10)
        self.assertEqual(request.call_count, 1)

    def test_one_installed_selected_model_only_and_configured_keep_alive(self):
        with patch("app.model_prewarm._json_request", side_effect=[
            {"models": [{"name": "gemma3:4b"}, {"name": "gemma3:12b"}]},
            {"done": True, "response": ""},
        ]) as request:
            _prewarm(settings(), "gemma3:12b", "30m", 10)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.args[2], {
            "model": "gemma3:12b", "stream": False, "keep_alive": "30m",
        })
        self.assertEqual(request.call_args.args[1], 10)

    def test_bad_response_does_not_count_as_success(self):
        with patch("app.model_prewarm._json_request", side_effect=[
            {"models": [{"name": "gemma3:12b"}]}, {"done": False},
        ]):
            with self.assertRaises(ValueError):
                _prewarm(settings(), "gemma3:12b", "30m", 10)


if __name__ == "__main__":
    unittest.main()
