from __future__ import annotations

import tempfile
import unittest

from app.compute_ledger import ComputeLedger
from app.model_gateway import ModelGateway
from app.routing_policy import RoutingPolicy


class ComputationalUpliftTests(unittest.TestCase):
    def test_frontier_requires_complete_configuration(self):
        gateway = ModelGateway(ledger=ComputeLedger(path=tempfile.mktemp(suffix=".db")))
        # Default development configuration must fail closed unless every frontier
        # component is explicitly supplied by the owner environment.
        if not (gateway.frontier_url and gateway.frontier_key and gateway.frontier_model):
            self.assertFalse(gateway.frontier_available)

    def test_routing_holds_weak_result_without_frontier(self):
        decision = RoutingPolicy().decide(local_confidence="partial", frontier_allowed=True,
                                          frontier_available=False, consequential=False)
        self.assertEqual(decision.selected_stage, "confidence_hold")

    def test_consequential_work_keeps_approval_gate(self):
        decision = RoutingPolicy().decide(local_confidence="strong", consequential=True)
        self.assertTrue(decision.approval_required)

    def test_compute_ledger_persists_success_metadata(self):
        path = tempfile.mktemp(suffix=".db")
        ledger = ComputeLedger(path=path)
        ledger.record(task_id="t1", stage="local_ai", provider="test", model="m", latency_ms=5,
                      success=True, input_units=10, output_units=3)
        rows = ledger.recent()
        self.assertEqual(rows[0]["task_id"], "t1")
        self.assertTrue(rows[0]["success"])


if __name__ == "__main__":
    unittest.main()
