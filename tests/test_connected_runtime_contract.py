import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConnectedRuntimeContractTests(unittest.TestCase):
    def test_compose_keeps_prime_local_and_tunnel_opt_in(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn(
            "${ORQEVIA_BIND_ADDRESS:-127.0.0.1}:${ORQEVIA_PORT:-8000}:8000",
            compose,
        )
        self.assertIn('profiles: ["tunnel"]', compose)
        self.assertIn("integration-gateway:", compose)
        self.assertIn("cloudflared:", compose)
        self.assertIn(
            "TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:-}",
            compose,
        )
        self.assertIn(
            "ORQEVIA_INTEGRATION_TOKEN: ${ORQEVIA_INTEGRATION_TOKEN:-}",
            compose,
        )

    def test_gateway_exposes_only_health_and_authenticated_integrations(self) -> None:
        caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")

        self.assertIn("path /health", caddyfile)
        self.assertIn("path /api/integrations/*", caddyfile)
        self.assertIn(
            'header Authorization "Bearer {$ORQEVIA_INTEGRATION_TOKEN}"',
            caddyfile,
        )
        self.assertIn('respond "Unauthorized" 401', caddyfile)
        self.assertIn('respond "Not Found" 404', caddyfile)
        self.assertEqual(caddyfile.count("reverse_proxy backend:8000"), 1)

    def test_bootstrap_preserves_recovered_secrets_and_requires_explicit_new_epoch(self) -> None:
        script = (
            ROOT / "scripts" / "bootstrap_connected_loop.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("RandomNumberGenerator", script)
        self.assertIn("[switch]$InitializeNewTrustEpoch", script)
        self.assertIn("will not create replacement state", script)
        self.assertIn("this is not recovered historical state", script)
        self.assertIn("Existing non-empty application tokens were preserved.", script)
        self.assertIn("ORQEVIA_INTEGRATION_TOKEN", script)
        self.assertIn("PORTAL_RESULT_TOKEN", script)
        self.assertIn("PORTAL_ORQEVIA_TOKEN", script)
        self.assertIn("CLOUDFLARE_TUNNEL_TOKEN", script)
        self.assertIn(
            "docker compose --profile tunnel config --quiet",
            script,
        )
        self.assertNotIn("Get-Content .env", script)

    def test_permanent_coaching_controller_has_no_container_sandbox_limits(self) -> None:
        compose = (ROOT / "deploy" / "agent-coaching.compose.yml").read_text(
            encoding="utf-8"
        )
        for restriction in (
            "read_only:",
            "network_mode: none",
            "cap_drop:",
            "security_opt:",
            "mem_limit:",
            "cpus:",
            "pids_limit:",
        ):
            self.assertNotIn(restriction, compose)
        self.assertIn("restart: always", compose)
        self.assertIn("name: ${ORQEVIA_EPOCH_NETWORK:-orqevia-epoch-20261016_default}", compose)


if __name__ == "__main__":
    unittest.main()
