import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ControlSurfaceContractTests(unittest.TestCase):
    def test_seven_canonical_views_are_present(self):
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        for view in ("overview", "conversation", "evidence", "memory", "system", "actions", "audit"):
            self.assertIn(f'id="{view}"', html)
            self.assertIn(f'data-view="{view}"', html)

    def test_p1_has_only_bounded_approval_mutation_controls(self):
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        for forbidden in (
            "/toggle",
            "/verified-cycle",
            "/orchestration/cycle",
            "/org/cycle",
        ):
            self.assertNotIn(forbidden, html)
        self.assertIn("remember:false", html)
        self.assertNotIn("/api/cognitive/consolidate", html)
        self.assertNotIn("/api/cognitive/episodes',{method:'POST'", html)
        self.assertIn("decideApproval", html)
        self.assertIn("This does not execute the action", html)

    def test_router_declares_approval_gated_boundaries(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        self.assertIn('@router.get("/control"', source)
        self.assertIn('"mode": "approval-gated"', source)
        self.assertIn('"autonomous_actions": False', source)
        self.assertIn('"approval_executes_action": False', source)
        self.assertIn('"velyqua_dependency": False', source)
        self.assertIn('"memory_write": False', source)
        self.assertIn('"runtime_mutation": False', source)
        self.assertIn('"off_host": "unavailable"', source)
        self.assertIn('"routing_policy": policy_manifest()', source)

    def test_every_view_has_a_real_read_path_or_health_contract(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        for path in (
            "/health",
            "/api/status",
            "/api/phase3/artifacts",
            "/api/cognitive/memory/search",
            "/api/actions",
            "/api/control-surface/trusted/audit-explorer",
        ):
            self.assertIn(path, source)

    def test_p1_acceptance_contract_covers_every_view(self):
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
            "/api/control-surface/trusted/approvals",
            "/api/control-surface/trusted/audit-explorer",
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
        self.assertIn("Working, episodic, semantic, procedural and protected", html)
        self.assertIn("Request → evidence → reasoning route → policy → approval → result", html)

    def test_owner_workspace_is_complete_and_non_actuating(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        self.assertIn('"owner_workspace"', source)
        self.assertIn('"server_side_writes": "approval-decisions-only"', source)
        self.assertIn('"executes_actions": False', source)
        for feature in (
            'id="overview"',
            'id="overviewMetrics"',
            'id="guidance"',
            'id="workspaceQuery"',
            'id="evidenceQuery"',
            'id="exportReport"',
            "orqevia-owner-report-",
        ):
            self.assertIn(feature, html)
        self.assertIn("Search memory, projects and verified evidence", html)
        self.assertIn("Audit Explorer", html)

    def test_frozen_routing_policy_is_visible_but_non_executing(self):
        source = (ROOT / "app" / "routing_policy.py").read_text(encoding="utf-8")
        html = (ROOT / "app" / "control_surface.html").read_text(encoding="utf-8")
        self.assertIn('ROUTING_SEQUENCE = ("deterministic", "local_ai", "confidence_gate", "frontier_ai")', source)
        self.assertIn('"executes_models": False', source)
        self.assertIn('"executes_actions": False', source)
        self.assertIn("decision.selected_stage", html)
        self.assertIn("allow_frontier:false", html)
        self.assertIn("DRAFT — HELD AT CONFIDENCE GATE", html)


if __name__ == "__main__":
    unittest.main()
