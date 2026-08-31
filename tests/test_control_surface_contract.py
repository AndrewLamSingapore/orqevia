import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ControlSurfaceContractTests(unittest.TestCase):
    def test_six_canonical_views_are_present(self):
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        for view in ("conversation", "evidence", "memory", "system", "actions", "audit"):
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
        for view in ("conversation", "evidence", "memory", "system", "actions", "audit"):
            self.assertIn(f'"view": "{view}"', source)
        self.assertIn('id="acceptance"', html)
        self.assertIn("/api/control-surface/acceptance", html)
        self.assertIn('"no_actuation": True', source)

    def test_audit_explorer_and_memory_layers_are_explicit(self):
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        self.assertIn("Audit Explorer", html)
        self.assertIn('id="auditQuery"', html)
        self.assertIn("Session, episodic, durable and evidence layers remain separate", html)


if __name__ == "__main__":
    unittest.main()
