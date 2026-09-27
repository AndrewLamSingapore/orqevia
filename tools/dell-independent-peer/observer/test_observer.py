import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import observer

A = "a" * 40
B = "b" * 40
C = "c" * 40
REF = "refs/heads/fix/phase2-read-aloud"
HOST = {"manufacturer": "Dell Inc.", "model": "test", "name": "fixture", "uuid": "fixture-uuid"}


class ObserverChecks(unittest.TestCase):
    def test_full_shas_and_annotated_tag_peeling(self):
        refs = observer.parse_git_refs(A + "\t" + REF + "\n" +
             B + "\trefs/tags/candidate-1\n" + C + "\trefs/tags/candidate-1^{}\n")
        self.assertEqual(refs[REF]["source_sha"], A)
        self.assertEqual(refs["refs/tags/candidate-1"]["source_sha"], C)
        self.assertEqual(refs["refs/tags/candidate-1"]["ref_object_sha"], B)

    def test_abbreviated_or_conflicting_refs_block(self):
        for raw in ("abc\t" + REF, A + "\t" + REF + "\n" + B + "\t" + REF, ""):
            with self.subTest(raw=raw), self.assertRaises(observer.Blocked):
                observer.parse_git_refs(raw)

    def test_classification_has_no_approval_semantics(self):
        self.assertEqual(observer.classify(observer.CANONICAL_REF), "CANONICAL_BRANCH_OBSERVATION")
        self.assertEqual(observer.classify("refs/heads/fix/audio"), "CANDIDATE_REF_OBSERVATION")
        self.assertIsNone(observer.classify("refs/heads/unrelated"))

    def test_history_baseline_noop_change_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = observer.parse_git_refs(A + "\t" + REF)
            one = observer.observe(root, first, "mock", "host")
            self.assertEqual(len(one), 1)
            first_bytes = Path(one[0][0]).read_bytes()
            record = json.loads(first_bytes)
            self.assertEqual(record["event"], "BASELINE_OBSERVATION")
            self.assertFalse(record["frozen_candidate"])
            self.assertEqual(record["promotion_verification"], "BLOCKED")
            self.assertEqual(hashlib.sha256(first_bytes).hexdigest(), one[0][1])
            self.assertEqual(observer.observe(root, first, "mock", "host"), [])
            second = observer.observe(root, observer.parse_git_refs(B + "\t" + REF), "mock", "host")
            changed = json.loads(Path(second[0][0]).read_text())
            self.assertEqual(changed["previous_source_sha"], A)
            self.assertEqual(changed["source_sha"], B)
            deleted = observer.observe(root, {}, "mock", "host")
            removal = json.loads(Path(deleted[0][0]).read_text())
            self.assertEqual(removal["event"], "REF_DELETED")
            self.assertEqual(removal["source_sha"], B)
            self.assertEqual(Path(one[0][0]).read_bytes(), first_bytes)

    def test_prior_fail_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = observer.append_record(tmp, {"result": "FAIL", "source_sha": A})
            before = Path(path).read_bytes()
            observer.observe(tmp, observer.parse_git_refs(B + "\t" + REF), "mock", "host")
            self.assertEqual(Path(path).read_bytes(), before)

    def test_corrupt_baseline_blocks_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.json"
            path.write_text("BROKEN")
            with self.assertRaises(observer.Blocked):
                observer.observe(tmp, observer.parse_git_refs(A + "\t" + REF), "mock", "host")
            self.assertEqual(path.read_text(), "BROKEN")

    def test_evidence_failure_does_not_advance_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            observer.observe(tmp, observer.parse_git_refs(A + "\t" + REF), "mock", "host")
            path = Path(tmp) / "baseline.json"
            before = path.read_bytes()
            with mock.patch.object(observer, "append_record", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    observer.observe(tmp, observer.parse_git_refs(B + "\t" + REF), "mock", "host")
            self.assertEqual(path.read_bytes(), before)

    def test_single_instance_lock_blocks_reentry_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            with observer.single_instance(tmp):
                with self.assertRaises(observer.Blocked):
                    with observer.single_instance(tmp):
                        self.fail("second observer entered")
            with observer.single_instance(tmp):
                pass

    def test_host_binding_is_observational_and_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            fingerprint = observer.bind_host(tmp, HOST)
            self.assertEqual(fingerprint, observer.require_binding(tmp, HOST))
            with self.assertRaises(observer.Blocked):
                observer.require_binding(tmp, dict(HOST, name="different"))
            self.assertEqual(json.loads((Path(tmp) / "host-binding.json").read_text())["host"], HOST)

    def test_linux_is_blocked_without_creating_state(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(observer.sys, "platform", "linux"):
            root = Path(tmp) / "must-not-exist"
            with contextlib.redirect_stdout(io.StringIO()):
                result = observer.main(["--bind-host", "--state-dir", str(root)])
            self.assertEqual(result, 2)
            self.assertFalse(root.exists())

    def test_malformed_host_binding_blocks_without_replacement(self):
        for value in ([], "invalid", 4):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "host-binding.json"
                before = json.dumps(value)
                path.write_text(before)
                with self.assertRaisesRegex(observer.Blocked, "HOST_BINDING_UNREADABLE"):
                    observer.require_binding(tmp, HOST)
                self.assertEqual(path.read_text(), before)

    def test_timeout_and_stderr_never_expose_credentials(self):
        with self.assertRaisesRegex(observer.Blocked, "TIMED_OUT") as error:
            observer.run_command([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.05)
        self.assertNotIn("SECRET", str(error.exception))
        with mock.patch.object(observer.subprocess, "Popen", wraps=subprocess.Popen) as run:
            with self.assertRaises(observer.Blocked) as error:
                observer.run_command([sys.executable, "-c", "import sys; sys.stderr.write('SECRET'); sys.exit(1)"])
            self.assertNotIn("SECRET", str(error.exception))
            self.assertIs(run.call_args.kwargs["shell"], False)
            self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_stdout_budget_stops_large_output(self):
        with mock.patch.object(observer, "MAX_OUTPUT", 128):
            with self.assertRaisesRegex(observer.Blocked, "OUTPUT_LIMIT"):
                observer.run_command([sys.executable, "-c", "import sys; sys.stdout.write('x' * 65536)"])

    def test_remote_failure_is_preserved_and_does_not_advance_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            observer.bind_host(tmp, HOST)
            observer.observe(tmp, observer.parse_git_refs(A + "\t" + REF), "mock", "host")
            baseline = (Path(tmp) / "baseline.json").read_bytes()
            with mock.patch.object(observer, "host_identity", return_value=HOST), \
                 mock.patch.object(observer, "read_refs", side_effect=observer.Blocked("TEST_REMOTE_UNAVAILABLE")), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(observer.main(["--once", "--state-dir", tmp]), 2)
            self.assertEqual((Path(tmp) / "baseline.json").read_bytes(), baseline)
            status = json.loads((Path(tmp) / "status.json").read_text())
            self.assertEqual(status["event"], "OBSERVER_BLOCKED")
            self.assertEqual(status["status"], "BLOCKED")
            self.assertEqual(status["diagnostic_code"], "TEST_REMOTE_UNAVAILABLE")
            self.assertEqual(status["last_successful_observation_utc"], json.loads(baseline)["observed_at_utc"])

    def test_git_auth_failure_uses_existing_gh_read_only_fallback(self):
        def which(name):
            return "/fixture/" + name
        responses = [observer.Blocked("AUTH_UNAVAILABLE"),
                     json.dumps([[{"name": "fix/audio", "commit": {"sha": A}}]]), "[[]]"]
        with mock.patch.object(observer.shutil, "which", side_effect=which), \
             mock.patch.object(observer, "run_command", side_effect=responses) as run:
            refs, transport = observer.read_refs()
        self.assertEqual(transport, "github_cli_api")
        self.assertEqual(refs["refs/heads/fix/audio"]["source_sha"], A)
        self.assertTrue(all("--method" not in call.args[0] for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
