from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_compose_keeps_prime_local_and_tunnel_opt_in() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "127.0.0.1:8000:8000" in compose
    assert 'profiles: ["tunnel"]' in compose
    assert "integration-gateway:" in compose
    assert "cloudflared:" in compose
    assert "TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:-}" in compose
    assert "PRIME_INTEGRATION_TOKEN: ${PRIME_INTEGRATION_TOKEN:-}" in compose


def test_gateway_exposes_only_health_and_authenticated_integrations() -> None:
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")

    assert "path /health" in caddyfile
    assert "path /api/integrations/*" in caddyfile
    assert 'header Authorization "Bearer {$PRIME_INTEGRATION_TOKEN}"' in caddyfile
    assert 'respond "Unauthorized" 401' in caddyfile
    assert 'respond "Not Found" 404' in caddyfile
    assert caddyfile.count("reverse_proxy prime:8000") == 2


def test_bootstrap_generates_local_secrets_without_printing_them() -> None:
    script = (ROOT / "scripts" / "bootstrap_connected_loop.ps1").read_text(
        encoding="utf-8"
    )

    assert "RandomNumberGenerator" in script
    assert "PRIME_INTEGRATION_TOKEN" in script
    assert "PORTAL_RESULT_TOKEN" in script
    assert "CLOUDFLARE_TUNNEL_TOKEN" in script
    assert "docker compose --profile tunnel config --quiet" in script
    assert "Get-Content .env" not in script
