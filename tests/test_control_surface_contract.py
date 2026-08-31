import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ControlSurfaceContractTests(unittest.TestCase):
    def test_six_canonical_views_are_present(self):
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        for view in ("overview", "conversation", "evidence", "memory", "system", "actions", "audit"):
            self.assertIn(f'id="{view}"', html)
            self.assertIn(f'data-view="{view}"', html)

    def test_p0_has_no_mutating_controls(self):
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        for forbidden in (
            "/approve",
            "/reject",
            "/toggle",
            "/verified-cycle",
            "/orchestration/cycle",
            "/org/cycle",
        ):
            self.assertNotIn(forbidden, html)
        self.assertIn("remember:false", html)
        self.assertNotIn("/api/cognitive/consolidate", html)
        self.assertNotIn("/api/cognitive/episodes',{method:'POST'", html)

    def test_router_declares_read_only_boundaries(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/control"', source)
        self.assertIn('"mode": "read-only"', source)
        self.assertIn('"autonomous_actions": False', source)
        self.assertIn('"velyqua_dependency": False', source)
        self.assertIn('"memory_write": False', source)
        self.assertIn('"runtime_mutation": False', source)
        self.assertIn('"off_host": "unavailable"', source)

    def test_every_view_has_a_real_read_path_or_health_contract(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        for path in (
            "/health",
            "/api/status",
            "/api/phase3/artifacts",
            "/api/cognitive/memory/search",
            "/api/actions",
            "/api/spine/events",
        ):
            self.assertIn(path, source)

    def test_p0_acceptance_contract_covers_every_view(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        self.assertIn('@router.get("/api/control-surface/acceptance")', source)
        self.assertIn("request.app.routes", source)
        for view in ("overview", "conversation", "evidence", "memory", "system", "actions", "audit"):
            self.assertIn(f'"view": "{view}"', source)
        self.assertIn('id="acceptance"', html)
        self.assertIn("/api/control-surface/acceptance", html)
        self.assertIn('"no_actuation": True', source)

    def test_trusted_local_access_requires_no_sign_in(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        self.assertIn('"mode": "trusted-local"', source)
        self.assertIn('"sign_in_required": False', source)
        self.assertIn('LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}', source)
        self.assertIn("Cross-origin Control Surface access is denied", source)
        for path in (
            "/api/control-surface/trusted/episodes",
            "/api/control-surface/trusted/memory/search",
            "/api/control-surface/trusted/events",
            "/api/control-surface/trusted/meta-review",
            "/api/control-surface/trusted/plan",
        ):
            self.assertIn(path, source)
            self.assertIn(path, html)
        self.assertIn("Trusted local access", html)
        self.assertNotIn("prime-control-token", html)
        self.assertNotIn('id="applyToken"', html)

    def test_audit_explorer_and_memory_layers_are_explicit(self):
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        self.assertIn("Audit Explorer", html)
        self.assertIn('id="auditQuery"', html)
        self.assertIn("Session, episodic, durable and evidence layers remain separate", html)

    def test_p2_owner_workspace_is_read_only_and_complete(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        self.assertIn('"owner_workspace"', source)
        self.assertIn('"server_side_writes": False', source)
        for feature in (
            'id="overview"',
            'id="overviewMetrics"',
            'id="guidance"',
            'id="workspaceQuery"',
            'id="evidenceQuery"',
            'id="exportReport"',
            "jarvis-owner-report-",
        ):
            self.assertIn(feature, html)
        self.assertIn("Search memory, projects and verified evidence", html)
        self.assertIn("Audit Explorer timeline", html)


if __name__ == "__main__":
    unittest.main()
