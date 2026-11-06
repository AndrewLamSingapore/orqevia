import ast
import hashlib
import json
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs/history/frontend-retirement-20261105"


class HistoricalControlSurfaceContractTests(unittest.TestCase):
    def test_seven_canonical_views_are_present(self):
        html = (ARCHIVE / "control_surface.html").read_text(encoding="utf-8")
        for view in ("overview", "conversation", "evidence", "memory", "system", "actions", "audit"):
            self.assertIn(f'id="{view}"', html)
            self.assertIn(f'data-view="{view}"', html)

    def test_p1_has_only_bounded_approval_mutation_controls(self):
        html = (ARCHIVE / "control_surface.html").read_text(encoding="utf-8")
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
        source = (ARCHIVE / "control_surface.py.txt").read_text(encoding="utf-8")
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
        html = (ARCHIVE / "control_surface.html").read_text(encoding="utf-8")
        self.assertIn('@router.get("/api/control-surface/acceptance")', source)
        self.assertIn("request.app.routes", source)
        for view in ("overview", "conversation", "evidence", "memory", "system", "actions", "audit"):
            self.assertIn(f'"view": "{view}"', source)
        self.assertIn('id="acceptance"', html)
        self.assertIn("/api/control-surface/acceptance", html)
        self.assertIn('"no_actuation": True', source)

    def test_trusted_local_access_requires_no_sign_in(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        html = (ARCHIVE / "control_surface.html").read_text(encoding="utf-8")
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
        html = (ARCHIVE / "control_surface.html").read_text(encoding="utf-8")
        self.assertIn("Audit Explorer", html)
        self.assertIn('id="auditQuery"', html)
        self.assertIn("Working, episodic, semantic, procedural and protected", html)
        self.assertIn("Request → evidence → reasoning route → policy → approval → result", html)

    def test_owner_workspace_is_complete_and_non_actuating(self):
        source = (ROOT / "app" / "control_surface.py").read_text(encoding="utf-8")
        html = (ARCHIVE / "control_surface.html").read_text(encoding="utf-8")
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
            "jarvis-owner-report-",
        ):
            self.assertIn(feature, html)
        self.assertIn("Search memory, projects and verified evidence", html)
        self.assertIn("Audit Explorer", html)

    def test_frozen_routing_policy_is_visible_but_non_executing(self):
        source = (ROOT / "app" / "routing_policy.py").read_text(encoding="utf-8")
        html = (ARCHIVE / "control_surface.html").read_text(encoding="utf-8")
        self.assertIn('ROUTING_SEQUENCE = ("deterministic", "local_ai", "confidence_gate", "frontier_ai")', source)
        self.assertIn('"executes_models": False', source)
        self.assertIn('"executes_actions": False', source)
        self.assertIn("decision.selected_stage", html)
        self.assertIn("allow_frontier:false", html)
        self.assertIn("DRAFT — HELD AT CONFIDENCE GATE", html)


class ActiveRendererRetirementTests(unittest.TestCase):
    def test_actual_legacy_handlers_redirect_without_serving_archived_html(self):
        for path, handler, route, destination in (
            ("app/control_surface.py", "control_surface", "/control", "/pwa/?view=console"),
            ("app/orqevia/ui.py", "index", "/", "/pwa/?view=intelligence"),
        ):
            source = ast.parse((ROOT / path).read_text(encoding="utf-8"))
            function = next(
                node
                for node in source.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == handler
            )
            application = FastAPI()
            namespace = {"app": application, "router": application, "RedirectResponse": RedirectResponse}
            exec(compile(ast.Module(body=[function], type_ignores=[]), path, "exec"), namespace)
            response = TestClient(application).get(route, follow_redirects=False)
            self.assertEqual(response.status_code, 307)
            self.assertEqual(response.headers["location"], destination)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.content, b"")

    def test_useful_api_and_security_function_bodies_are_unchanged(self):
        for active, original, exclusions in (
            (
                "app/control_surface.py",
                "control_surface.py.txt",
                {"control_surface", "control_surface_manifest", "control_surface_acceptance"},
            ),
            ("app/orqevia/ui.py", "orqevia/ui.py.txt", {"index", "manifest"}),
        ):

            def functions(path):
                return {
                    node.name: ast.dump(node, include_attributes=False)
                    for node in ast.parse(path.read_text(encoding="utf-8")).body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in exclusions
                }

            self.assertEqual(functions(ROOT / active), functions(ARCHIVE / original))

    def test_archived_bytes_and_rendered_payload_match_custody_manifest(self):
        manifest = json.loads((ARCHIVE / "ARCHIVE-MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "ARCHIVED_NOT_SERVED")
        for entry in manifest["files"]:
            data = (ROOT / entry["archive_path"]).read_bytes()
            self.assertEqual(len(data), entry["bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])
        original = ast.parse((ARCHIVE / "main.py.txt").read_text(encoding="utf-8"))
        payload = next(
            node.value.value
            for node in original.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "HTML" for target in node.targets)
        )
        self.assertEqual((ARCHIVE / "main.html").read_bytes(), payload.encode("utf-8"))
        self.assertFalse((ROOT / "app/control_surface.html").exists())
        for name in ("index.html", "app.js", "styles.css", "manifest.webmanifest"):
            self.assertFalse((ROOT / "app/orqevia/static" / name).exists())
        self.assertFalse((ROOT / "app/main.py").exists())

    def test_legacy_manifest_distinguishes_retired_renderer_from_api_boundaries(self):
        from app.control_surface import control_surface_manifest

        value = control_surface_manifest()
        self.assertEqual(value["renderer"], "RETIRED")
        self.assertEqual(value["canonical_interface"], "/pwa/?view=console")
        self.assertEqual(value["mode"], "legacy-api-adapters")
        self.assertFalse(value["boundaries"]["approval_executes_action"])
        self.assertFalse(value["boundaries"]["runtime_mutation"])
        source = ast.parse((ROOT / "app/orqevia/ui.py").read_text(encoding="utf-8"))
        mounts = [
            node.value.args[0].value
            for node in source.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "mount"
        ]
        self.assertEqual(set(mounts), {"/pwa", "/gods-eye"})


if __name__ == "__main__":
    unittest.main()
