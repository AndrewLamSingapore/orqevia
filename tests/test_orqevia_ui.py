"""Tests for the read-only ORQEVIA unified interface surface."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.orqevia.ui import app, READ_ONLY_PATHS, STATIC_DIR


LOGO = STATIC_DIR / "assets" / "orqevia" / "generated-original.png"
EXPECTED_LOGO_SHA256 = "b3bdd53cc38b24c8be2896f1174b4d5f083be20f94f2042770224c72e2501844"


def test_manifest_has_required_views_and_boundaries():
    client = TestClient(app)
    res = client.get("/api/orqevia/manifest")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "ORQEVIA · 奥启维亚"
    expected_views = {
        "home", "intelligence", "ideas", "architecture", "build", "test",
        "deploy", "present", "evidence", "agents", "gods-eye", "settings",
    }
    assert set(data["views"]) == expected_views
    boundaries = data["boundaries"]
    assert boundaries["production_deploy"] is False
    assert boundaries["live_pwa_change"] is False
    assert boundaries["public_website_change"] is False
    assert boundaries["sensitive_operations_require_human_approval"] is True


def test_index_is_served_and_declares_responsive_and_language():
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert '<html lang="en">' in html
    assert 'name="viewport"' in html
    assert "ORQEVIA" in html and "奥启维亚" in html
    # Unified navigation must be present.
    for view in ("Intelligence", "Ideas", "Architecture", "Build", "Test", "Deploy", "Present", "Evidence", "Agents", "Settings"):
        assert view in html


def test_approved_logo_is_the_original_binary():
    assert LOGO.is_file(), "approved ORQEVIA logo asset is missing"
    digest = hashlib.sha256(LOGO.read_bytes()).hexdigest()
    assert digest == EXPECTED_LOGO_SHA256
    header = LOGO.read_bytes()[:8]
    assert header == b"\x89PNG\r\n\x1a\n", "logo is not a valid PNG"


def test_proxy_allowlist_rejects_unknown_and_mutating_paths():
    client = TestClient(app)
    for path in ("api/chat", "api/actions", "internal/secrets", "..%2F..%2Fetc"):
        res = client.get("/api/orqevia/proxy/" + path)
        assert res.status_code == 403


def test_proxy_returns_unreachable_when_upstream_is_down(monkeypatch):
    # Point the proxy at an unused port so the httpx call fails quickly.
    from app.orqevia import ui
    monkeypatch.setattr(ui, "UPSTREAM", "http://127.0.0.1:1")
    monkeypatch.setattr(ui, "TIMEOUT", 0.5)
    client = TestClient(app)
    res = client.get("/api/orqevia/proxy/health")
    assert res.status_code == 502
    assert res.json()["connected"] is False


def test_read_only_paths_are_exactly_as_expected():
    assert READ_ONLY_PATHS == {
        "health",
        "api/status",
        "api/agents",
        "api/control-surface/manifest",
    }


def test_gods_eye_is_embedded_in_unified_navigation():
    client = TestClient(app)
    html = client.get("/").text
    assert 'data-view="gods-eye"' in html
    assert 'id="view-gods-eye"' in html
    assert 'src="/gods-eye/"' in html


def test_gods_eye_client_assets_are_served():
    client = TestClient(app)
    index = client.get("/gods-eye/")
    assert index.status_code == 200
    assert "GOD'S EYE" in index.text
    css = client.get("/gods-eye/gods-eye.css")
    assert css.status_code == 200
    js = client.get("/gods-eye/gods-eye.js")
    assert js.status_code == 200
    # The embedded client must read through ORQEVIA's own read-only endpoints.
    assert "/api/orqevia/gods-eye" in js.text


def test_gods_eye_snapshot_fails_safe_to_unavailable():
    client = TestClient(app)
    res = client.get("/api/orqevia/gods-eye")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "UNAVAILABLE"
    assert body["source"] == "ORQEVIA_READ_ONLY_SURFACE"


def test_gods_eye_drilldown_endpoints_fail_safe():
    client = TestClient(app)
    for path in (
        "/api/orqevia/gods-eye/why?agent_id=a01",
        "/api/orqevia/gods-eye/dependencies?subject=a01",
        "/api/orqevia/gods-eye/proof?task_id=00000000-0000-0000-0000-000000000000",
    ):
        res = client.get(path)
        assert res.status_code == 503
        assert res.json()["status"] == "UNAVAILABLE"
