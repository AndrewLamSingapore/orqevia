import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeOperationsContractTests(unittest.TestCase):
    def test_production_dependencies_include_wasm_sandbox_runtime(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        self.assertIn("wasmtime==48.0.0", requirements)

    def test_prime_healthcheck_authenticates_without_embedding_a_secret(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        healthcheck = next(line for line in compose.splitlines() if "urllib.request.Request" in line)
        self.assertIn("os.environ['PRIME_SPINE_TOKEN']", healthcheck)
        self.assertIn("'Authorization': 'Bearer ' +", healthcheck)
        self.assertNotIn("${PRIME_SPINE_TOKEN}", healthcheck)

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

    def test_direct_runtime_enables_registry_dispatch(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("PRIME_REGISTRY_V1_ENABLED: ${PRIME_REGISTRY_V1_ENABLED:-1}", compose)
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("PRIME_REGISTRY_V1_ENABLED=1", example)

    def test_image_starts_canonical_owner_entrypoint_without_proxy_trust(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('"app.production_entry:app"', dockerfile)
        self.assertIn('"--no-proxy-headers"', dockerfile)

    def test_container_owner_peer_is_explicit_not_a_network_wildcard(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("PRIME_OWNER_TRUSTED_PEERS: ${PRIME_OWNER_TRUSTED_PEERS:-}", compose)

    def test_physical_client_runtime_is_https_narrow_and_profile_gated(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('profiles: ["clients"]', compose)
        self.assertIn('app.interface_server:app', compose)
        self.assertIn('"--no-proxy-headers"', compose)
        self.assertIn('"--ssl-keyfile"', compose)
        self.assertIn('${PRIME_INTERFACE_BIND_ADDRESS:-127.0.0.1}', compose)
        self.assertNotIn('app.production_entry:app", "--host", "0.0.0.0", "--port", "8443"', compose)
        self.assertIn('COPY clients/pwa/index.html', dockerfile)
        self.assertIn('PRIME_INTERFACE_RUNTIME_VERSION: ${PRIME_INTERFACE_RUNTIME_VERSION:-UNKNOWN}', compose)
        self.assertIn('PRIME_INTERFACE_CANDIDATE_STATUS: ${PRIME_INTERFACE_CANDIDATE_STATUS:-UNKNOWN}', compose)


if __name__ == "__main__":
    unittest.main()
