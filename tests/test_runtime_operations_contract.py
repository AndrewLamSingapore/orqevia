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
        self.assertIn("Ensure-PersistentVolumes", script)
        self.assertIn("Stop-LegacyCoreContainers", script)
        self.assertIn("volume data is retained", script)
        self.assertNotIn('volume", "rm"', script)
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


if __name__ == "__main__":
    unittest.main()
