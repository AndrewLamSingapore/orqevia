"""Independent observer failure regressions, using simulated host/network only."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("reviewed_observer", ROOT / "observer/observer.py")
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


class ObserverReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = {"manufacturer": "Dell Inc.", "model": "SYNTHETIC", "name": "FIXTURE", "uuid": "FIXTURE-ONLY"}

    def test_malformed_host_binding_fails_closed_without_uncaught_exception(self):
        (self.root / "host-binding.json").write_text("[]\n")
        with self.assertRaises(observer.Blocked):
            observer.bind_host(self.root, self.host)

    def test_remote_outage_updates_status_and_preserves_error_event(self):
        observer.bind_host(self.root, self.host)
        observer.atomic_json(self.root / "status.json", {
            "observed_at_utc": "2000-01-01T00:00:00+00:00", "status": "OBSERVATION_COMPLETE",
            "new_records": 0, "verification": "NOT_RUN", "promotion_verification": "BLOCKED",
        })
        with mock.patch.object(observer, "host_identity", return_value=self.host), \
             mock.patch.object(observer, "read_refs", side_effect=observer.Blocked("SYNTHETIC_REMOTE_OUTAGE")), \
             contextlib.redirect_stdout(io.StringIO()):
            result = observer.main(["--once", "--state-dir", str(self.root)])
        self.assertEqual(result, 2)
        status = json.loads((self.root / "status.json").read_text())
        self.assertEqual(status["status"], "BLOCKED")
        events = list((self.root / "inbox").glob("*.json"))
        self.assertTrue(events, "remote failure must have a durable, fresh evidence artifact")
        self.assertTrue(any("SYNTHETIC_REMOTE_OUTAGE" in path.read_text() for path in events))


if __name__ == "__main__":
    unittest.main(verbosity=2)
