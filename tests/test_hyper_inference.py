"""Tests for the ORQEVIA Hyper-Inference Fabric.

Runs under both ``python -m unittest tests.test_hyper_inference`` and pytest.
All assertions are deterministic and advisory-only; no external service,
network call, tool or consequential action is exercised.
"""
from __future__ import annotations

import unittest

from app.hyper_inference.channels import CHANNEL_SPECS, run_channel
from app.hyper_inference.academy_exercises import (
    SECTION77_EXERCISES,
    academy_qualification,
    run_section77_exercises,
)
from app.hyper_inference.engines import ENGINE_SPECS, InferenceEngineRegistry, run_engine
from app.hyper_inference.matrices import (
    CapabilityMatrix,
    CausalModel,
    KnowledgeGraph,
    ProvenanceLedger,
    RelationalMatrix,
    VectorStore,
)
from app.hyper_inference.proxies import (
    ModelProxyRegistry,
    ProviderSpec,
    ProxyError,
    ToolProxyRegistry,
    ToolSpec,
)
from app.hyper_inference.router import AdaptiveInferenceRouter, build_capability_matrix


class EngineRegistryTests(unittest.TestCase):
    def test_twelve_reasoning_families_are_registered(self):
        families = {spec["family"] for spec in ENGINE_SPECS.values()}
        self.assertEqual(len(ENGINE_SPECS), 12)
        self.assertEqual(
            families,
            {
                "deductive", "inductive", "abductive", "causal", "bayesian",
                "probabilistic", "analogical", "counterfactual", "temporal",
                "spatial", "constraint", "meta",
            },
        )

    def test_registry_fails_closed_on_unknown_engine(self):
        registry = InferenceEngineRegistry()
        with self.assertRaises(KeyError):
            registry.spec("reasoning.nonexistent")

    def test_deductive_modus_ponens_and_tollens(self):
        ponens = run_engine("reasoning.deductive", {
            "antecedent": "P", "consequent": "Q", "antecedent_true": True,
            "rule": "modus_ponens",
        })
        self.assertTrue(ponens.conclusion["valid"])
        self.assertEqual(ponens.conclusion["conclusion"], "Q")
        tollens = run_engine("reasoning.deductive", {
            "antecedent": "P", "consequent": "Q", "consequent_true": False,
            "rule": "modus_tollens",
        })
        self.assertTrue(tollens.conclusion["valid"])

    def test_inductive_marks_uncertainty(self):
        result = run_engine("reasoning.inductive", {
            "proposition": "all swans are white",
            "observations": [
                {"supports": True, "group": "a"},
                {"supports": True, "group": "b"},
                {"supports": False, "group": "c"},
            ],
            "minimum": 3,
        })
        self.assertIn("counterexamples_present", result.uncertainties)
        self.assertEqual(result.conclusion["support"], 2)

    def test_abductive_ranks_and_marks_underdetermination(self):
        result = run_engine("reasoning.abductive", {
            "observations": ["power on", "fan quiet", "screen black"],
            "hypotheses": [
                {"id": "h1", "proposition": "display cable loose", "prior": 0.6, "explains": [0, 2]},
                {"id": "h2", "proposition": "motherboard failure", "prior": 0.4, "explains": [0]},
            ],
        })
        self.assertEqual(result.conclusion["best_explanation"]["id"], "h1")

    def test_bayesian_posterior_updates(self):
        result = run_engine("reasoning.bayesian", {
            "prior": 0.01, "likelihood_positive": 0.9,
            "likelihood_negative": 0.1, "evidence_observed": True,
        })
        self.assertAlmostEqual(result.conclusion["posterior"], 0.0833, places=4)

    def test_constraint_solver_finds_and_rejects(self):
        satisfiable = run_engine("reasoning.constraint", {
            "variables": ["x", "y"],
            "domains": {"x": [1, 2], "y": [2, 3]},
            "constraints": [{"vars": ["x", "y"], "type": "lt"}],
        })
        self.assertTrue(satisfiable.conclusion["satisfiable"])
        unsat = run_engine("reasoning.constraint", {
            "variables": ["x", "y"],
            "domains": {"x": [1], "y": [1]},
            "constraints": [{"vars": ["x", "y"], "type": "neq"}],
        })
        self.assertFalse(unsat.conclusion["satisfiable"])

    def test_causal_relation_classification(self):
        result = run_engine("reasoning.causal", {
            "model": {"nodes": ["A", "B", "C"], "edges": [["A", "B"], ["B", "C"]]},
            "claim": {"cause": "A", "effect": "C"},
        })
        self.assertEqual(result.conclusion["relation"], "indirect")


class ChannelRegistryTests(unittest.TestCase):
    def test_ten_channels_are_registered(self):
        self.assertEqual(len(CHANNEL_SPECS), 10)

    def test_parallel_hypotheses_ranks(self):
        result = run_channel("channel.parallel-hypotheses", {
            "objective": "diagnose black screen",
            "observations": ["power on", "screen black"],
            "hypotheses": [
                {"id": "h1", "proposition": "cable", "prior": 0.7, "explains": [0, 1]},
                {"id": "h2", "proposition": "panel", "prior": 0.3, "explains": [1]},
            ],
        })
        self.assertTrue(result.ok)
        self.assertEqual(result.result["ranked_hypotheses"][0]["id"], "h1")

    def test_multi_agent_debate_flags_unexplained_observations(self):
        result = run_channel("channel.multi-agent-debate", {
            "objective": "diagnose black screen",
            "observations": ["power on", "screen black"],
            "hypotheses": [
                {"id": "h1", "proposition": "cable", "prior": 0.7, "explains": [1]},
            ],
        })
        self.assertEqual(result.result["disposition"], "CONTESTED")
        self.assertTrue(result.contradictions)

    def test_verifier_guided_checks_constraints(self):
        result = run_channel("channel.verifier-guided", {
            "objective": "assign",
            "candidate": {"proposition": "x<y", "confidence": 0.9},
            "constraints": {
                "variables": ["x", "y"],
                "domains": {"x": [1, 2], "y": [2, 3]},
                "constraints": [{"vars": ["x", "y"], "type": "lt"}],
            },
        })
        self.assertTrue(result.ok)

    def test_graph_search_finds_shortest_path(self):
        result = run_channel("channel.graph-search", {
            "graph": {"A": ["B", "C"], "B": ["D"], "C": ["D"]},
            "start": "A", "goal": "D",
        })
        self.assertEqual(result.result["path"], ["A", "B", "D"])


class ProxyRegistryTests(unittest.TestCase):
    def test_model_route_and_receipt(self):
        proxy = ModelProxyRegistry()
        route = proxy.route(
            required_capabilities={"logical_validity"},
            agent_permissions={"reason.advisory"},
        )
        receipt = proxy.invoke(
            agent_id="a01", prompt="test", route=route,
            agent_permissions={"reason.advisory"},
        )
        self.assertEqual(receipt.status, "completed")
        self.assertEqual(receipt.provider_id, "local-deterministic")

    def test_model_route_denies_unauthorized_agent(self):
        proxy = ModelProxyRegistry()
        with self.assertRaises(ProxyError):
            proxy.route(required_capabilities={"logical_validity"}, agent_permissions=set())

    def test_model_fallback_prefers_alternate_provider(self):
        proxy = ModelProxyRegistry()
        route = proxy.route(
            required_capabilities={"logical_validity"},
            agent_permissions={"reason.advisory", "frontier.read"},
            preferred_provider="mock-frontier",
        )
        self.assertEqual(route["provider_id"], "mock-frontier")
        fallback = proxy.fallback(
            route,
            required_capabilities={"logical_validity"},
            agent_permissions={"reason.advisory", "frontier.read"},
        )
        self.assertEqual(fallback["provider_id"], "local-deterministic")

    def test_tool_discovery_and_access_control(self):
        registry = ToolProxyRegistry([
            ToolSpec("calc", ("compute",), ("reason.advisory",), cost=0.01),
            ToolSpec("write", ("mutation",), ("consequential.write",), cost=1.0),
        ])
        self.assertEqual(
            registry.discover(capabilities={"compute"}, agent_permissions={"reason.advisory"}),
            ["calc"],
        )
        with self.assertRaises(ProxyError):
            registry.match("write", agent_permissions={"reason.advisory"})


class MatrixTests(unittest.TestCase):
    def test_relational_and_vector_retrieval(self):
        table = RelationalMatrix([{"kind": "receipt", "status": "PASS"}])
        self.assertEqual(len(table.query(kind="receipt")), 1)
        vectors = VectorStore({"a": [1.0, 0.0], "b": [0.0, 1.0]})
        self.assertEqual(vectors.search([1.0, 0.1], top_k=1)[0][0], "a")

    def test_knowledge_graph_and_causal_model(self):
        graph = KnowledgeGraph()
        graph.add_edge("A", "B")
        self.assertEqual(graph.path("A", "B"), ["A", "B"])
        causal = CausalModel([("A", "B"), ("B", "C")])
        self.assertTrue(causal.acyclic())
        self.assertEqual(causal.descendants("A"), {"B", "C"})
        causal.add_edge("C", "A")
        self.assertFalse(causal.acyclic())

    def test_provenance_ledger_hash_chain_verifies(self):
        ledger = ProvenanceLedger()
        ledger.add("route", {"engine": "reasoning.deductive"})
        ledger.add("result", {"valid": True})
        self.assertTrue(ledger.verify())


class AdaptiveRouterTests(unittest.TestCase):
    def test_capability_matrix_projects_all_21_agents(self):
        matrix = build_capability_matrix()
        self.assertEqual(len(matrix.agents), 21)
        self.assertTrue(matrix.capable("logical_validity"))

    def test_router_produces_traceable_result(self):
        router = AdaptiveInferenceRouter()
        result = router.route(
            objective="Deduce the conclusion using modus ponens",
            agent_id="a01",
            agent_permissions={"reason.advisory"},
        )
        self.assertEqual(result.task_class, "deduction")
        self.assertEqual(result.required_capabilities, ("logical_validity", "rule_application"))
        self.assertTrue(result.channels_selected)
        self.assertFalse(result.executed_external_action)
        self.assertIn("grounding evidence for objective", result.evidence_requests)
        self.assertFalse(result.escalation["required"])

    def test_router_escalates_on_high_complexity(self):
        router = AdaptiveInferenceRouter()
        result = router.route(
            objective="Forecast the probability of failure",
            agent_id="a13",
            agent_permissions={"reason.advisory"},
            complexity="high",
        )
        self.assertTrue(result.escalation["required"])
        self.assertIn("task_complexity=high", result.escalation["reasons"])
        self.assertIn("independent verification evidence", result.evidence_requests)

    def test_router_detects_contradiction_and_requests_evidence(self):
        router = AdaptiveInferenceRouter()
        result = router.route(
            objective="Diagnose the black screen",
            agent_id="a19",
            agent_permissions={"reason.advisory"},
            hypotheses=[{"id": "h1", "proposition": "cable", "prior": 0.7, "explains": [1]}],
            evidence=[{"proposition": "power on"}, {"proposition": "screen black"}],
            complexity="medium",
        )
        self.assertTrue(result.contradictions)
        self.assertTrue(result.escalation["required"])
        self.assertIn("discriminating evidence for contradictory results", result.evidence_requests)


class AcademyExerciseTests(unittest.TestCase):
    def test_twelve_section77_exercises_are_defined(self):
        self.assertEqual(len(SECTION77_EXERCISES), 12)

    def test_all_exercises_run_traceably_without_side_effects(self):
        outcomes = run_section77_exercises()
        qualification = academy_qualification(outcomes)
        self.assertEqual(qualification["status"], "PASS")
        self.assertTrue(all(row["trace_id"] for row in outcomes if row["status"] == "COMPLETED"))
        self.assertTrue(all(not row["executed_external_action"] for row in outcomes))

    def test_high_complexity_exercises_escalate(self):
        outcomes = run_section77_exercises()
        escalated = {
            row["exercise_id"]
            for row in outcomes
            if row["exercise_id"].startswith(("academy.multi-model-disagreement",
                                              "academy.tool-failure",
                                              "academy.provider-outage"))
            and row["escalation"]
        }
        self.assertEqual(
            escalated,
            {
                "academy.multi-model-disagreement",
                "academy.tool-failure",
                "academy.provider-outage",
            },
        )


if __name__ == "__main__":
    unittest.main()
