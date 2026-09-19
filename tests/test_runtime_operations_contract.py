import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeOperationsContractTests(unittest.TestCase):
    def test_compose_is_one_stable_local_project(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("name: ${COMPOSE_PROJECT_NAME:-prime}", compose)
        self.assertIn('${PRIME_BIND_ADDRESS:-127.0.0.1}', compose)
        self.assertIn('com.lamjarvis.managed: "true"', compose)
        self.assertIn("${PRIME_DATA_VOLUME:-prime-data}", compose)
        self.assertIn("${OLLAMA_DATA_VOLUME:-prime-ollama-data}", compose)
        self.assertEqual(compose.count("external: true"), 2)

    def test_windows_operator_preserves_data_and_checks_every_surface(self):
        script = (ROOT / "scripts" / "jarvis.ps1").read_text(encoding="utf-8")
        self.assertIn("Save-Checkpoint", script)
        self.assertIn("Adopt-PersistentVolumes", script)
        self.assertIn("Assert-PersistentVolumes", script)
        self.assertIn("Assert-NoConflictingCoreContainers", script)
        self.assertIn("will not create a blank replacement", script)
        self.assertNotIn('volume", "rm"', script)
        self.assertNotIn('Invoke-Docker -Arguments @("rm"', script)
        for path in ("/health", "/control", "/api/control-surface/manifest", "/api/status"):
            self.assertIn(path, script)

    def test_public_gateway_never_exposes_control_surface(self):
        script = (ROOT / "scripts" / "jarvis.ps1").read_text(encoding="utf-8")
        self.assertIn('foreach ($path in @("/control", "/api/status", "/api/control-surface/manifest"))', script)
        self.assertIn("HTTP 404", script)

    def test_one_click_menu_covers_lifecycle(self):
        menu = (ROOT / "JARVIS.cmd").read_text(encoding="utf-8")
        for action in ("start", "status", "doctor", "repair", "open", "stop"):
            self.assertIn(f"-Action {action}", menu)

    def test_recovery_sensitive_helpers_fail_closed(self):
        bootstrap = (ROOT / "scripts" / "bootstrap_connected_loop.ps1").read_text(encoding="utf-8")
        trace = (ROOT / "scripts" / "enable-public-trace.ps1").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("InitializeNewTrustEpoch", bootstrap)
        self.assertIn("will not create replacement state", bootstrap)
        self.assertNotIn("RotateTokens", bootstrap)
        self.assertIn("ApplyRestart", trace)
        self.assertIn("source secret file was preserved", trace)
        self.assertNotIn("Remove-Item", trace)
        self.assertNotIn(":latest", compose)


if __name__ == "__main__":
    unittest.main()
