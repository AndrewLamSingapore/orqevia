"""Synthetic Linux runner surfaces only; no Docker or model call in tests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.backend_admission import observation
from app.compute_profile import load_compute_profile
from scripts import offhost_ollama_telemetry as collector


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")


class OffhostTelemetryTests(unittest.TestCase):
    def test_effective_scope_includes_vm_docker_and_every_ancestor(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            proc, cg = root / "proc", root / "cg"
            _write(proc / "77/cgroup", "0::/parent/backend\n")
            _write(proc / "meminfo", "MemTotal: 10000000 kB\nMemAvailable: 7000000 kB\n")
            _write(cg / "memory.max", "max\n")
            _write(cg / "memory.current", "1\n")
            _write(cg / "parent/memory.max", str(5 * 1024 * collector.MIB))
            _write(cg / "parent/memory.current", str(2 * 1024 * collector.MIB))
            _write(cg / "parent/backend/memory.max", str(6 * 1024 * collector.MIB))
            _write(cg / "parent/backend/memory.current", str(1 * 1024 * collector.MIB))
            _write(cg / "parent/backend/memory.peak", str(1500 * collector.MIB))
            cap, free, peak = collector._scope(77, 6 * 1024 * collector.MIB,
                                               proc_root=proc, cgroup_root=cg)
            self.assertEqual((cap // collector.MIB, free // collector.MIB,
                              peak // collector.MIB), (5120, 3072, 1500))
            (cg / "memory.max").unlink()
            (cg / "memory.current").unlink()
            self.assertEqual(collector._scope(77, 6 * 1024 * collector.MIB,
                                              proc_root=proc, cgroup_root=cg),
                             (cap, free, peak))
            _write(cg / "memory.max", "max\n")
            with self.assertRaisesRegex(collector.EvidenceError, "scope incomplete"):
                collector._scope(77, 6 * 1024 * collector.MIB,
                                 proc_root=proc, cgroup_root=cg)
            (cg / "memory.max").unlink()
            (cg / "parent/memory.current").unlink()
            with self.assertRaisesRegex(collector.EvidenceError, "scope incomplete"):
                collector._scope(77, 6 * 1024 * collector.MIB,
                                 proc_root=proc, cgroup_root=cg)
            _write(cg / "parent/memory.current", str(2 * 1024 * collector.MIB))
            _write(cg / "parent/backend/memory.max", "max\n")
            with self.assertRaisesRegex(collector.EvidenceError, "scope incomplete"):
                collector._scope(77, 6 * 1024 * collector.MIB,
                                 proc_root=proc, cgroup_root=cg)

    def test_profile_requires_measured_preflight_and_fits_hard_cap(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name) / "profile"
            first = {"instance": "container@start", "boot_id": "boot",
                     "capacity_mib": 6144, "available_mib": 5000,
                     "peak_mib": 150, "hard_cap_mib": 6144}
            second = {**first, "peak_mib": 1200}
            digest = "a" * 64
            with (patch.object(collector, "_runner_only"),
                  patch.object(collector, "_require_loopback_binding"),
                  patch.object(collector, "_backend", side_effect=[first, second]),
                  patch.object(collector, "_model_identity", return_value=("0.34.2", digest)),
                  patch.object(collector, "_api", side_effect=[{"done": True}, {"models": []}]) as api):
                result = collector.prepare("ollama", directory, "http://127.0.0.1:11434")
            self.assertEqual(api.call_args_list[0].args[2]["keep_alive"], 0)
            self.assertEqual(api.call_args_list[1].args[1], "/api/ps")
            profile = json.loads((directory / "profile.json").read_text())
            self.assertEqual(profile["models"][collector.MODEL]["peak_mib"], 1500)
            self.assertEqual(result["reserved_peak_mib"], 1500)
            self.assertEqual(profile["measurement"]["observed_mib"], 1200)
            with patch.dict("os.environ", {
                "PRIME_MEASURED_COMPUTE_PROFILE": str(directory / "profile.json"),
                "PRIME_MEASURED_COMPUTE_PROFILE_SHA256": result["profile_sha256"],
            }):
                load_compute_profile.cache_clear()
                try:
                    self.assertEqual(load_compute_profile()["models"][collector.MODEL]["digest"], digest)
                finally:
                    load_compute_profile.cache_clear()

    def test_failed_calibration_never_publishes_profile(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name) / "profile"
            sample = {"instance": "container@start", "boot_id": "boot",
                      "capacity_mib": 4096, "available_mib": 3000,
                      "peak_mib": 2000, "hard_cap_mib": 4096}
            with (patch.object(collector, "_runner_only"),
                  patch.object(collector, "_require_loopback_binding"),
                  patch.object(collector, "_backend", return_value=sample),
                  patch.object(collector, "_model_identity", return_value=("0.34.2", "a" * 64)),
                  patch.object(collector, "_api", side_effect=[{"done": True}, {"models": []}])):
                with self.assertRaisesRegex(collector.EvidenceError, "lacks enforced memory reserve"):
                    collector.prepare("ollama", directory, "http://127.0.0.1:11434")
            self.assertFalse((directory / "profile.json").exists())

    def test_resident_calibration_model_does_not_publish_profile(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name) / "profile"
            sample = {"instance": "container@start", "boot_id": "boot",
                      "capacity_mib": 6144, "available_mib": 5000,
                      "peak_mib": 1200, "hard_cap_mib": 6144}
            def still_resident(_endpoint, path, _payload=None):
                if path == "/api/ps":
                    return {"models": [{"name": collector.MODEL}]}
                return {"done": True}

            with (patch.object(collector, "_runner_only"),
                  patch.object(collector, "_require_loopback_binding"),
                  patch.object(collector, "_backend", return_value=sample),
                  patch.object(collector, "_model_identity", return_value=("0.34.2", "a" * 64)),
                  patch.object(collector, "_api", side_effect=still_resident) as api,
                  patch.object(collector.time, "sleep")):
                with self.assertRaisesRegex(collector.EvidenceError, "did not unload"):
                    collector.prepare("ollama", directory, "http://127.0.0.1:11434")
            self.assertTrue(any(call.args[1] == "/api/generate" and
                                call.args[2].get("prompt") == "" for call in api.call_args_list))
            self.assertFalse((directory / "profile.json").exists())

    def test_explicit_unload_completes_before_profile(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name) / "profile"
            sample = {"instance": "container@start", "boot_id": "boot",
                      "capacity_mib": 6144, "available_mib": 5000,
                      "peak_mib": 1200, "hard_cap_mib": 6144}
            with (patch.object(collector, "_runner_only"),
                  patch.object(collector, "_require_loopback_binding"),
                  patch.object(collector, "_backend", return_value=sample),
                  patch.object(collector, "_model_identity", return_value=("0.34.2", "a" * 64)),
                  patch.object(collector, "_api", side_effect=[
                      {"done": True}, {"models": [{"name": collector.MODEL}]},
                      {"done": True}, {"models": []}]) as api):
                collector.prepare("ollama", directory, "http://127.0.0.1:11434")
            self.assertEqual(api.call_args_list[2].args[2]["prompt"], "")
            self.assertEqual(api.call_args_list[2].args[2]["keep_alive"], 0)
            self.assertTrue((directory / "profile.json").exists())

    def test_only_exact_ollama_container_loopback_binding_is_accepted(self):
        from types import SimpleNamespace
        good = SimpleNamespace(returncode=0, stdout=json.dumps({
            "11434/tcp": [{"HostIp": "127.0.0.1", "HostPort": "11434"}]}))
        with patch.object(collector.subprocess, "run", return_value=good):
            collector._require_loopback_binding("ollama")
        exposed = SimpleNamespace(returncode=0, stdout=json.dumps({
            "11434/tcp": [{"HostIp": "0.0.0.0", "HostPort": "11434"}]}))
        with patch.object(collector.subprocess, "run", return_value=exposed):
            with self.assertRaisesRegex(collector.EvidenceError, "loopback"):
                collector._require_loopback_binding("ollama")

    def test_atomic_receipt_matches_prime_contract_and_wrong_endpoint_fails(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "backend-memory.json"
            receipt = {"schema": collector.SCHEMA, "endpoint": "http://127.0.0.1:11434",
                       "instance": "container@start", "boot_id": "boot", "scope_complete": True,
                       "capacity_mib": 6144, "available_mib": 4000, "captured_at": 100.0}
            collector._atomic_json(path, receipt)
            with patch.dict("os.environ", {"PRIME_BACKEND_MEMORY_RECEIPT": str(path)}):
                self.assertEqual(observation(receipt["endpoint"], now=100.5)["instance"],
                                 "container@start")
                with self.assertRaisesRegex(PermissionError, "scope mismatch"):
                    observation("http://wrong", now=100.5)
                with self.assertRaisesRegex(PermissionError, "stale"):
                    observation(receipt["endpoint"], now=103.0)


if __name__ == "__main__":
    unittest.main()
