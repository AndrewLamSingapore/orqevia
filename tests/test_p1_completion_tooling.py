import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class P1CompletionToolingTests(unittest.TestCase):
    def test_windows_operator_is_powershell_51_safe_and_propagates_failures(self):
        script = (ROOT / "scripts" / "jarvis.ps1").read_text(encoding="utf-8")
        wrapper = (ROOT / "ORQEVIA.cmd").read_text(encoding="utf-8")
        self.assertTrue(script.isascii())
        self.assertIn("EnableDelayedExpansion", wrapper)
        self.assertIn("exit /b !ERRORLEVEL!", wrapper)
        self.assertNotIn("exit /b %ERRORLEVEL%", wrapper)
        self.assertNotIn('Join-Path $Root "app\\control_surface.html"', script)
        self.assertIn('"{{json .}}"', script)
        self.assertNotIn('.Label "com.docker.compose.project"', script)
        self.assertNotIn('{{if eq .Destination', script)
        self.assertIn('$ErrorActionPreference = "Continue"', script)
        self.assertIn('$code = $LASTEXITCODE', script)
        self.assertIn('$ErrorActionPreference = $previousErrorAction', script)

    def test_model_benchmark_is_loopback_only_and_scores_required_dimensions(self):
        source = (ROOT / "scripts" / "benchmark_local_models.py").read_text(encoding="utf-8")
        self.assertIn('host not in {"127.0.0.1", "localhost", "::1"}', source)
        for dimension in ("reasoning", "coding", "retrieval", "latency_seconds", "privacy", "offline_resilience"):
            self.assertIn(dimension, source)
        self.assertIn('host == "ollama"', source)
        self.assertIn('Path("/.dockerenv").exists()', source)
        runner = (ROOT / "BENCHMARK-ORQEVIA.cmd").read_text(encoding="utf-8")
        self.assertIn("docker cp", runner)
        self.assertIn("--allow-docker-internal", runner)
        self.assertIn("local-model-benchmark.json", runner)
        self.assertIn('("PRIME_FAST_MODEL", "PRIME_DEEP_MODEL")', source)
        self.assertIn('"embed" not in model.lower()', source)
        self.assertIn('except (urllib.error.URLError, TimeoutError)', source)

    def test_portal_smoke_is_authenticated_nonphysical_and_reads_back(self):
        source = (ROOT / "scripts" / "smoke_portal_result.py").read_text(encoding="utf-8")
        self.assertIn("PORTAL_RESULT_TOKEN", source)
        self.assertIn("/api/experiment-result", source)
        self.assertIn("/api/graph", source)
        for boundary in ("actuation_authorized", "owner_approval_inferred", "scientific_support_claimed"):
            self.assertIn(boundary, source)
        self.assertIn("--generate-safe-smoke", source)
        self.assertIn('"credential_exposed": False', source)
        runner = (ROOT / "PORTAL-SMOKE-ORQEVIA.cmd").read_text(encoding="utf-8")
        self.assertIn("PORTAL_RESULT_TOKEN", runner)
        self.assertIn("--generate-safe-smoke", runner)
        self.assertIn("portal-smoke-result.json", runner)

    def test_p1_verifier_requires_immutable_image_and_rollback(self):
        source = (ROOT / "scripts" / "verify_p1_runtime.ps1").read_text(encoding="utf-8")
        self.assertIn("ExpectedImageTag", source)
        self.assertIn("label=com.docker.compose.project=prime", source)
        self.assertIn("label=com.docker.compose.service=prime", source)
        self.assertIn("Expected exactly one running canonical PRIME container", source)
        self.assertNotIn('Container = "prime-main-prime-1"', source)
        self.assertNotIn('LegacyRollbackContainer = "prime-github-ready1-prime-1"', source)
        self.assertIn("RollbackImage", source)
        self.assertIn("rollbackCandidates", source)
        self.assertIn("docker image inspect", source)
        self.assertIn('foreach ($volume in @("prime-data"))', source)
        self.assertIn("RollbackImage must be an immutable prime sha-xxxxxxx image reference", source)
        self.assertIn("approval-gated", source)
        self.assertIn("docker restart $Container", source)
        self.assertIn("Compare-Object $mountsBefore $mountsAfter", source)
        self.assertIn('"facts", "memories", "datasets", "artifacts", "pending_approvals"', source)
        self.assertIn("volumes_deleted=$false", source)


if __name__ == "__main__":
    unittest.main()
