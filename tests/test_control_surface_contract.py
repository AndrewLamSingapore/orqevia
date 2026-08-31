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

    def test_router_declares_read_only_boundaries(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/control"', source)
        self.assertIn('"mode": "read-only"', source)
        self.assertIn('"autonomous_actions": False', source)
        self.assertIn('"velyqua_dependency": False', source)


if __name__ == "__main__":
    unittest.main()
