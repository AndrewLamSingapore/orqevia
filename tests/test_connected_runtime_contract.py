import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConnectedRuntimeContractTests(unittest.TestCase):
    def test_compose_keeps_prime_local_and_tunnel_opt_in(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("127.0.0.1:8000:8000", compose)
        self.assertIn('profiles: ["tunnel"]', compose)
        self.assertIn("integration-gateway:", compose)
        self.assertIn("cloudflared:", compose)
        self.assertIn(
            "TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:-}",
            compose,
        )
        self.assertIn(
            "PRIME_INTEGRATION_TOKEN: ${PRIME_INTEGRATION_TOKEN:-}",
            compose,
        )

    def test_gateway_exposes_only_health_and_authenticated_integrations(self) -> None:
        caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")

        self.assertIn("path /health", caddyfile)
        self.assertIn("path /api/integrations/*", caddyfile)
        self.assertIn(
            'header Authorization "Bearer {$PRIME_INTEGRATION_TOKEN}"',
            caddyfile,
        )
        self.assertIn('respond "Unauthorized" 401', caddyfile)
        self.assertIn('respond "Not Found" 404', caddyfile)
        self.assertEqual(caddyfile.count("reverse_proxy prime:8000"), 2)

    def test_bootstrap_generates_local_secrets_without_printing_them(self) -> None:
        script = (
            ROOT / "scripts" / "bootstrap_connected_loop.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("RandomNumberGenerator", script)
        self.assertIn("PRIME_INTEGRATION_TOKEN", script)
        self.assertIn("PORTAL_RESULT_TOKEN", script)
        self.assertIn("PORTAL_PRIME_TOKEN", script)
        self.assertIn("CLOUDFLARE_TUNNEL_TOKEN", script)
        self.assertIn(
            "docker compose --profile tunnel config --quiet",
            script,
        )
        self.assertNotIn("Get-Content .env", script)


if __name__ == "__main__":
    unittest.main()
