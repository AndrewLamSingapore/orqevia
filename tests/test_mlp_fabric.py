"""Small numerical proof of the governed local MLP candidate path."""
import copy
import tempfile
import unittest
from pathlib import Path

from app.mlp_fabric import (
    MLPConfig, MLPCapabilityFabric, approve_candidate, load_artifact,
    save_artifact, train_candidate, validate_artifact,
)


class MLPCapabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.regression_rows = [{"x": float(i) / 10} for i in range(-30, 30)]
        cls.regression_labels = [row["x"] ** 2 for row in cls.regression_rows]
        cls.classification_rows = [
            {"x": float(i) / 10, "y": float(j) / 10}
            for i in range(-5, 6) if i for j in range(-5, 6) if j
        ]
        cls.classification_labels = [float(row["x"] * row["y"] > 0)
                                     for row in cls.classification_rows]

    def test_regression_training_evaluation_and_agent_inference(self):
        config = MLPConfig("regression", ("x",), hidden_layers=(8,), activation="relu",
                           seed=12, epochs=250)
        candidate = train_candidate(config, self.regression_rows, self.regression_labels,
                                    dataset_reference="fixture:quadratic-v1")
        self.assertEqual(candidate["approval_state"], "CANDIDATE")
        self.assertLess(candidate["evaluation_result"]["test"]["mae"], 0.25)
        self.assertLess(candidate["evaluation_result"]["test"]["mae"],
                        candidate["evaluation_result"]["baseline_test"]["mae"])
        second = train_candidate(config, self.regression_rows, self.regression_labels,
                                 dataset_reference="fixture:quadratic-v1")
        self.assertEqual(candidate["model_artifact_hash"], second["model_artifact_hash"])
        fabric = MLPCapabilityFabric()
        with self.assertRaises(ValueError):
            fabric.register(candidate)
        approved = approve_candidate(candidate, reviewer="fixture-reviewer",
                                     rationale="Synthetic fixture exceeded linear baseline")
        with tempfile.TemporaryDirectory() as temp:
            artifact_path = Path(temp) / "model.json"
            save_artifact(artifact_path, approved)
            loaded = load_artifact(artifact_path)
            model_id = fabric.register(loaded)
        self.assertTrue(fabric.discover("ml.mlp.regression"))
        self.assertFalse(fabric.discover("ml.mlp.classification"))
        self.assertNotEqual(fabric.discover("ml.mlp.train"), fabric.discover("ml.mlp.inference"))
        certification = {"agent_id": "a12", "capability_id": "responsibility.a12",
                         "level": "L7", "trust_state": "L7-CURRENT", "health": "HEALTHY"}
        output = fabric.infer_for_agent("a12", model_id, [{"x": 0.5}], trace_id="fixture-1",
                                        certification=certification, authority_allowed=True,
                                        runtime_healthy=True)
        self.assertAlmostEqual(output["output"][0], 0.25, delta=0.2)
        self.assertEqual(output["agent_route_state"], "READY")
        self.assertEqual(output["artifact_hash"], candidate["model_artifact_hash"])
        self.assertEqual(fabric.health(model_id)["inferences"], 1)
        revalidation = fabric.evaluate(model_id, [{"x": 0.5}], [0.25])
        self.assertEqual(revalidation["quality_decision"], "REVIEW_REQUIRED")
        self.assertLess(revalidation["metrics"]["mae"], 0.2)
        with self.assertRaises(PermissionError):
            fabric.infer_for_agent("a12", model_id, [{"x": 0.5}], trace_id="fixture-2",
                                   certification=certification, authority_allowed=False,
                                   runtime_healthy=True)

    def test_classification_and_input_contract(self):
        candidate = train_candidate(MLPConfig("classification", ("x", "y"), hidden_layers=(8,),
                                              seed=8, epochs=250), self.classification_rows,
                                    self.classification_labels, dataset_reference="fixture:xor-v1")
        self.assertGreaterEqual(candidate["evaluation_result"]["test"]["accuracy"], 0.8)
        self.assertGreater(candidate["evaluation_result"]["test"]["accuracy"],
                           candidate["evaluation_result"]["baseline_test"]["accuracy"])
        approved = approve_candidate(candidate, reviewer="fixture-reviewer", rationale="Synthetic case")
        fabric = MLPCapabilityFabric()
        model_id = fabric.register(approved)
        with self.assertRaises(ValueError):
            fabric.register(approved)
        output = fabric.infer(model_id, [{"x": 0.4, "y": 0.4}, {"x": -0.4, "y": 0.4}], trace_id="class-1")
        self.assertGreater(output["output"][0], 0.5)
        self.assertLess(output["output"][1], 0.5)
        for invalid in ([{"x": 1}], [{"x": 1, "y": None}], [{"x": float("nan"), "y": 2}],
                        [{"x": 1, "y": 2, "z": 3}]):
            with self.assertRaises(ValueError):
                fabric.infer(model_id, invalid, trace_id="invalid")
        self.assertEqual(fabric.health(model_id)["input_validation_failures"], 4)
        self.assertEqual(fabric.health(model_id)["last_failure"]["kind"], "ValueError")

    def test_artifact_identity_and_untrusted_format_rejection(self):
        candidate = train_candidate(MLPConfig("regression", ("x",), epochs=5),
                                    self.regression_rows, self.regression_labels,
                                    dataset_reference="fixture:linear-v1")
        for mutation in (lambda a: a["weights"][0]["weights"][0].append(10),
                         lambda a: a.update(model_id="anonymous"),
                         lambda a: a.update(framework="pickle")):
            bad = copy.deepcopy(candidate)
            mutation(bad)
            with self.assertRaises(ValueError):
                validate_artifact(bad)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "invalid.json"
            path.write_text('{"schema_version":"1.0","model_type":"MLP"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_artifact(path)
        with self.assertRaises(ValueError):
            train_candidate(MLPConfig("regression", ("x",), hidden_layers=(64, 64, 64),
                                      epochs=2000), self.regression_rows,
                            self.regression_labels, dataset_reference="fixture:budget")


if __name__ == "__main__":
    unittest.main()
