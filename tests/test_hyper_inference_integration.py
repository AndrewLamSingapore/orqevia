"""Integration evidence: fabric wiring into cognitive orchestrator, skill router
and UIEF. All assertions are deterministic and advisory-only."""
from __future__ import annotations

import os
import tempfile
import unittest

from app.cognitive_orchestrator import CognitiveOrchestrator
from app.hyper_inference.uief_integration import run_uief_benchmark
from app.memory import MemoryStore
from app.skill_router import select_skill_pack
from app.tier_router import Tier


class _FakePortal:
    def query(self, query: str, limit: int = 8):
        return [{"score": 2, "node": {"title": "artifact", "type": "artifact"}}]


class CognitiveWiringTests(unittest.TestCase):
    def test_plan_exposes_advisory_fabric_without_execution(self):
        directory = tempfile.mkdtemp(prefix="hif-cognitive-")
        engine = CognitiveOrchestrator(
            memory=MemoryStore(os.path.join(directory, "memory.db")),
            portal=_FakePortal(),
        )
        plan = engine.plan(intent="Review the architecture and research improvements",
                           department="research")
        self.assertIsNotNone(plan.fabric_advisory)
        self.assertFalse(plan.fabric_advisory.get("executed_external_action"))
        self.assertIn("channels_selected", plan.fabric_advisory)

    def test_consequential_plan_still_stops_at_proposal(self):
        directory = tempfile.mkdtemp(prefix="hif-cognitive-")
        engine = CognitiveOrchestrator(
            memory=MemoryStore(os.path.join(directory, "memory.db")),
            portal=_FakePortal(),
        )
        plan = engine.plan(intent="Deploy an external production change",
                           department="engineering")
        self.assertTrue(plan.needs_approval)
        self.assertEqual(plan.proposed_action["action"], "external.action.proposal")
        self.assertIsNotNone(plan.fabric_advisory)


class SkillRouterWiringTests(unittest.TestCase):
    def test_skill_pack_includes_advisory_fabric_summary(self):
        pack = select_skill_pack("a17", "planning", Tier.MINI)
        fabric = pack["advisory_fabric"]
        self.assertEqual(fabric["status"], "DRAFT_CANDIDATE")
        self.assertEqual(fabric["authority"], "ADVISORY_ONLY")
        self.assertEqual(len(fabric["engine_families"]), 12)
        self.assertEqual(len(fabric["channel_ids"]), 10)
        self.assertEqual(pack["tool_grants"], [])


class UiefIntegrationTests(unittest.TestCase):
    def test_benchmark_produces_measured_fifteen_dimension_scorecard(self):
        report = run_uief_benchmark()
        scorecard = report["scorecard"]
        self.assertEqual(report["sample_count"], 180)
        self.assertEqual(len(scorecard["dimension_scores"]), 15)
        self.assertEqual(scorecard["status"], "PASS")
        self.assertTrue(scorecard["hard_gates"]["action_safety"])
        self.assertTrue(scorecard["hard_gates"]["security_compliance"])


if __name__ == "__main__":
    unittest.main()
