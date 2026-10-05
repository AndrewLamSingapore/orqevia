"""Bounded, local MLP candidates and governed numerical inference.

Artifacts are data-only JSON. Training produces a candidate; approval and
registration are separate operations. No runtime request trains a model.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .agent_capability_route import select_agent_capability_route
from .agent_registry import canonical_agent_id


CAPABILITIES = frozenset({
    "ml.mlp.classification", "ml.mlp.regression", "ml.mlp.inference",
    "ml.mlp.train", "ml.mlp.evaluate",
})
MAX_ARTIFACT_BYTES = 2_000_000
MAX_TRAIN_MULTIPLIES = 2_000_000
MAX_INFER_MULTIPLIES = 2_000_000
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate model artifact field")
        result[key] = value
    return result


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("features and labels must be finite numbers")
    return float(value)


def _utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _verified(callback: Callable[[dict[str, Any]], bool] | None,
              receipt: dict[str, Any]) -> bool:
    if callback is None or not callable(callback):
        return False
    try:
        return callback(receipt) is True
    except Exception:
        return False


@dataclass(frozen=True)
class MLPConfig:
    task: str
    features: tuple[str, ...]
    hidden_layers: tuple[int, ...] = (8,)
    activation: str = "tanh"
    seed: int = 1
    epochs: int = 250
    learning_rate: float = 0.03
    output_dimensions: int = 1

    def validate(self) -> None:
        if self.task not in {"classification", "regression"}:
            raise ValueError("unsupported MLP task")
        if not self.features or len(self.features) > 64 or len(set(self.features)) != len(self.features):
            raise ValueError("features must be unique and bounded")
        if any(not isinstance(f, str) or not f or len(f) > 100 for f in self.features):
            raise ValueError("invalid feature name")
        if not self.hidden_layers or len(self.hidden_layers) > 3 or any(
            type(n) is not int or n < 1 or n > 64 for n in self.hidden_layers
        ):
            raise ValueError("hidden layers must contain 1-3 bounded dimensions")
        if self.activation not in {"tanh", "relu"}:
            raise ValueError("unsupported activation")
        if type(self.seed) is not int or type(self.epochs) is not int or self.epochs < 1 or self.epochs > 2000:
            raise ValueError("invalid training configuration")
        if not 0 < _number(self.learning_rate) <= 1:
            raise ValueError("invalid learning rate")
        if type(self.output_dimensions) is not int or self.output_dimensions != 1:
            raise ValueError("v1 supports one numerical or binary output")


def _matrix(rows: Any, features: tuple[str, ...]) -> list[list[float]]:
    if not isinstance(rows, list) or not rows or len(rows) > 10_000:
        raise ValueError("rows must be a nonempty bounded list")
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(features):
            raise ValueError("feature names or ordering contract mismatch")
        result.append([_number(row[name]) for name in features])
    return result


def _labels(values: Any, task: str, count: int) -> list[float]:
    if not isinstance(values, list) or len(values) != count:
        raise ValueError("label count mismatch")
    labels = [_number(value) for value in values]
    if task == "classification" and any(value not in {0.0, 1.0} for value in labels):
        raise ValueError("binary labels must be 0 or 1")
    return labels


def _preprocess_fit(rows: list[list[float]]) -> dict[str, list[float]]:
    means = [sum(col) / len(col) for col in zip(*rows)]
    scales = [max(math.sqrt(sum((row[j] - means[j]) ** 2 for row in rows) / len(rows)), 1e-12)
              for j in range(len(means))]
    return {"mean": means, "scale": scales, "encoding": "numeric_only", "missing": "reject"}


def _transform(row: list[float], prep: dict[str, Any]) -> list[float]:
    return [(value - mean) / scale for value, mean, scale in zip(row, prep["mean"], prep["scale"])]


def _activate(value: float, name: str) -> float:
    return math.tanh(value) if name == "tanh" else max(0.0, value)


def _derivative(output: float, name: str) -> float:
    return 1 - output * output if name == "tanh" else float(output > 0)


def _sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-max(-40, min(40, value))))


def _forward(x: list[float], layers: list[dict[str, Any]], task: str, activation: str) -> list[list[float]]:
    activations = [x]
    for index, layer in enumerate(layers):
        outputs = [sum(weight * input_value for weight, input_value in zip(weights, activations[-1])) + bias
                   for weights, bias in zip(layer["weights"], layer["biases"])]
        if index == len(layers) - 1:
            outputs = [_sigmoid(value) for value in outputs] if task == "classification" else outputs
        else:
            outputs = [_activate(value, activation) for value in outputs]
        activations.append(outputs)
    return activations


def _metrics(task: str, actual: list[float], predicted: list[float]) -> dict[str, Any]:
    if task == "regression":
        errors = [a - p for a, p in zip(actual, predicted)]
        mse = sum(e * e for e in errors) / len(errors)
        mean = sum(actual) / len(actual)
        total = sum((a - mean) ** 2 for a in actual)
        return {"mae": sum(abs(e) for e in errors) / len(errors), "mse": mse,
                "rmse": math.sqrt(mse), "r2": 1 - sum(e * e for e in errors) / total if total else None}
    labels = [int(p >= 0.5) for p in predicted]
    tp = sum(a == 1 and p == 1 for a, p in zip(actual, labels))
    tn = sum(a == 0 and p == 0 for a, p in zip(actual, labels))
    fp = sum(a == 0 and p == 1 for a, p in zip(actual, labels))
    fn = sum(a == 1 and p == 0 for a, p in zip(actual, labels))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"accuracy": (tp + tn) / len(actual), "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "confusion_matrix": [[tn, fp], [fn, tp]]}


def _linear_baseline(task: str, x: list[list[float]], y: list[float],
                     train_ids: list[int], test_ids: list[int], prep: dict[str, Any]) -> list[float]:
    """Train a linear/logistic comparator on the same training partition."""
    weights = [0.0] * len(x[0])
    bias = 0.0
    for _ in range(200):
        for i in train_ids:
            values = _transform(x[i], prep)
            score = sum(weight * value for weight, value in zip(weights, values)) + bias
            prediction = _sigmoid(score) if task == "classification" else score
            error = max(-100.0, min(100.0, prediction - y[i]))
            for j, value in enumerate(values):
                weights[j] -= 0.01 * error * value
            bias -= 0.01 * error
    output = []
    for i in test_ids:
        score = sum(weight * value for weight, value in zip(weights, _transform(x[i], prep))) + bias
        output.append(_sigmoid(score) if task == "classification" else score)
    return output


def train_candidate(config: MLPConfig, rows: list[dict[str, float]], labels: list[float],
                    *, dataset_reference: str, version: str = "1.0.0") -> dict[str, Any]:
    """Train on a fixed split; fit preprocessing only on the training partition."""
    config.validate()
    x = _matrix(rows, config.features)
    y = _labels(labels, config.task, len(x))
    if (len(x) < 20 or len(x) > 10_000 or not isinstance(dataset_reference, str) or
            not dataset_reference.strip() or len(dataset_reference) > 256 or
            not isinstance(version, str) or not _VERSION.fullmatch(version)):
        raise ValueError("training requires 20-10000 attributable rows")
    indices = list(range(len(x)))
    rng = random.Random(config.seed)
    rng.shuffle(indices)
    train_end, validation_end = int(.6 * len(x)), int(.8 * len(x))
    train_ids, validation_ids, test_ids = indices[:train_end], indices[train_end:validation_end], indices[validation_end:]
    if config.task == "classification" and len({y[i] for i in train_ids}) != 2:
        raise ValueError("training partition requires both classes")
    prep = _preprocess_fit([x[i] for i in train_ids])
    widths = [len(config.features), *config.hidden_layers, config.output_dimensions]
    parameter_count = sum(widths[k] * widths[k + 1] for k in range(len(widths) - 1))
    if len(train_ids) * config.epochs * parameter_count > MAX_TRAIN_MULTIPLIES:
        raise ValueError("training compute budget exceeded")
    layers = [{"weights": [[rng.uniform(-1, 1) / math.sqrt(widths[k]) for _ in range(widths[k])]
                           for _ in range(widths[k + 1])], "biases": [0.0] * widths[k + 1]}
              for k in range(len(widths) - 1)]
    for _ in range(config.epochs):
        for i in train_ids:
            activations = _forward(_transform(x[i], prep), layers, config.task, config.activation)
            delta = [activations[-1][0] - y[i]]
            if config.task == "regression":
                delta[0] = max(-100, min(100, delta[0]))
            for k in range(len(layers) - 1, -1, -1):
                layer = layers[k]
                previous = activations[k]
                next_delta = ([sum(layer["weights"][j][h] * delta[j] for j in range(len(delta))) *
                               _derivative(previous[h], config.activation) for h in range(len(previous))]
                              if k else [])
                for j, weights in enumerate(layer["weights"]):
                    for h in range(len(weights)):
                        weights[h] -= config.learning_rate * delta[j] * previous[h]
                    layer["biases"][j] -= config.learning_rate * delta[j]
                delta = next_delta
    predictions = {name: [_forward(_transform(x[i], prep), layers, config.task, config.activation)[-1][0]
                          for i in ids]
                   for name, ids in (("validation", validation_ids), ("test", test_ids))}
    evaluation = {name: _metrics(config.task, [y[i] for i in ids], predictions[name])
                  for name, ids in (("validation", validation_ids), ("test", test_ids))}
    baseline = _linear_baseline(config.task, x, y, train_ids, test_ids, prep)
    evaluation["baseline_test"] = {"type": "logistic" if config.task == "classification" else "linear",
                                   **_metrics(config.task, [y[i] for i in test_ids], baseline)}
    dataset_hash = _digest({"rows": rows, "labels": labels})
    body = {
        "schema_version": "1.0", "model_type": "MLP", "version": version, "task": config.task,
        "input_schema": {"features": list(config.features), "types": ["float"] * len(config.features)},
        "output_schema": {"type": "binary_probability" if config.task == "classification" else "float", "dimensions": 1},
        "architecture": {"hidden_layers": list(config.hidden_layers), "activation": config.activation,
                         "output_dimensions": config.output_dimensions},
        "training_configuration": {"seed": config.seed, "epochs": config.epochs,
                                   "learning_rate": config.learning_rate, "split": [0.6, 0.2, 0.2]},
        "dataset_reference": dataset_reference, "dataset_hash": dataset_hash,
        "preprocessing": prep, "weights": layers, "framework": "prime-stdlib-mlp-v1",
        "evaluation_result": evaluation,
    }
    artifact_hash = _digest(body)
    return {**body, "model_id": "mlp-" + artifact_hash[:20], "model_artifact_hash": artifact_hash,
            "created_at": datetime.now(timezone.utc).isoformat(), "approval_state": "CANDIDATE",
            "health": "UNVERIFIED", "provenance": {"origin": "local_training", "split_seed": config.seed,
                                                  "training_rows": len(train_ids), "validation_rows": len(validation_ids),
                                                  "test_rows": len(test_ids)}}


def validate_artifact(artifact: dict[str, Any]) -> None:
    if not isinstance(artifact, dict) or artifact.get("schema_version") != "1.0" or artifact.get("model_type") != "MLP":
        raise ValueError("unsupported model artifact")
    if artifact.get("approval_state") not in {"CANDIDATE", "APPROVED"}:
        raise ValueError("invalid approval state")
    body_keys = ("schema_version", "model_type", "version", "task", "input_schema", "output_schema",
                 "architecture", "training_configuration", "dataset_reference", "dataset_hash",
                 "preprocessing", "weights", "framework", "evaluation_result")
    try:
        required = set(body_keys) | {"model_id", "model_artifact_hash", "created_at",
                                     "approval_state", "health", "provenance"}
        allowed = required | ({"approval"} if artifact["approval_state"] == "APPROVED" else set())
        if set(artifact) != allowed:
            raise ValueError("unexpected or missing artifact metadata")
        body = {key: artifact[key] for key in body_keys}
        if not isinstance(body["version"], str) or not _VERSION.fullmatch(body["version"]):
            raise ValueError("invalid model version")
        if (not isinstance(body["dataset_reference"], str) or
                not 1 <= len(body["dataset_reference"].strip()) <= 256 or
                not isinstance(body["dataset_hash"], str) or not _SHA256.fullmatch(body["dataset_hash"])):
            raise ValueError("invalid dataset provenance")
        if (not isinstance(body["input_schema"], dict) or
                not isinstance(body["input_schema"].get("features"), list) or
                not isinstance(body["architecture"], dict) or
                not isinstance(body["architecture"].get("hidden_layers"), list) or
                not isinstance(body["training_configuration"], dict)):
            raise ValueError("invalid model schema")
        config = MLPConfig(task=body["task"], features=tuple(body["input_schema"]["features"]),
                           hidden_layers=tuple(body["architecture"]["hidden_layers"]),
                           activation=body["architecture"]["activation"],
                           seed=body["training_configuration"]["seed"],
                           epochs=body["training_configuration"]["epochs"],
                           learning_rate=body["training_configuration"]["learning_rate"],
                           output_dimensions=body["architecture"]["output_dimensions"])
        config.validate()
        if (body["training_configuration"]["split"] != [0.6, 0.2, 0.2] or
                set(body["training_configuration"]) != {"seed", "epochs", "learning_rate", "split"}):
            raise ValueError("invalid training split")
        if set(body["input_schema"]) != {"features", "types"} or set(body["output_schema"]) != {"type", "dimensions"}:
            raise ValueError("invalid data schema")
        if set(body["architecture"]) != {"hidden_layers", "activation", "output_dimensions"}:
            raise ValueError("invalid architecture schema")
        if (body["framework"] != "prime-stdlib-mlp-v1" or
                type(body["output_schema"]["dimensions"]) is not int or
                body["output_schema"]["dimensions"] != 1):
            raise ValueError("unsupported model format")
        expected_output = "binary_probability" if config.task == "classification" else "float"
        if body["output_schema"].get("type") != expected_output:
            raise ValueError("output semantics mismatch")
        if body["input_schema"]["types"] != ["float"] * len(config.features):
            raise ValueError("invalid input schema")
        widths = [len(config.features), *config.hidden_layers, 1]
        if len(body["weights"]) != len(widths) - 1:
            raise ValueError("layer count mismatch")
        for k, layer in enumerate(body["weights"]):
            if (not isinstance(layer, dict) or set(layer) != {"weights", "biases"} or
                    len(layer["weights"]) != widths[k + 1] or len(layer["biases"]) != widths[k + 1]):
                raise ValueError("layer shape mismatch")
            for vector in layer["weights"]:
                if len(vector) != widths[k]:
                    raise ValueError("weight shape mismatch")
                for value in vector:
                    _number(value)
            for value in layer["biases"]:
                _number(value)
        prep = body["preprocessing"]
        if (set(prep) != {"mean", "scale", "encoding", "missing"} or
                prep["encoding"] != "numeric_only" or prep["missing"] != "reject" or
                len(prep["mean"]) != widths[0] or len(prep["scale"]) != widths[0]):
            raise ValueError("invalid preprocessing")
        for value in prep["mean"]:
            _number(value)
        for value in prep["scale"]:
            if _number(value) <= 0:
                raise ValueError("invalid scale")
        digest = _digest(body)
        if not isinstance(artifact["model_artifact_hash"], str) or not _SHA256.fullmatch(artifact["model_artifact_hash"]):
            raise ValueError("invalid artifact hash")
        if artifact["model_artifact_hash"] != digest or artifact["model_id"] != "mlp-" + digest[:20]:
            raise ValueError("model identity mismatch")
        evaluation = artifact["evaluation_result"]
        if not isinstance(evaluation, dict) or set(evaluation) != {"validation", "test", "baseline_test"}:
            raise ValueError("missing provenance or evaluation")
        metric_names = ({"accuracy", "precision", "recall", "f1", "confusion_matrix"}
                        if config.task == "classification" else {"mae", "mse", "rmse", "r2"})
        for name in ("validation", "test", "baseline_test"):
            metrics = evaluation[name]
            if not isinstance(metrics, dict) or not metric_names.issubset(metrics):
                raise ValueError("invalid evaluation metrics")
            for key in metric_names - {"confusion_matrix", "r2"}:
                _number(metrics[key])
                if config.task == "classification" and not 0 <= metrics[key] <= 1:
                    raise ValueError("classification metric outside range")
            if config.task == "regression" and metrics["r2"] is not None:
                _number(metrics["r2"])
            if config.task == "classification":
                matrix = metrics["confusion_matrix"]
                if (not isinstance(matrix, list) or len(matrix) != 2 or
                        any(not isinstance(row, list) or len(row) != 2 or
                            any(type(count) is not int or count < 0 for count in row)
                            for row in matrix)):
                    raise ValueError("invalid confusion matrix")
        expected_baseline = "logistic" if config.task == "classification" else "linear"
        if evaluation["baseline_test"].get("type") != expected_baseline:
            raise ValueError("incorrect baseline")
        provenance = artifact.get("provenance")
        counts = [provenance.get(key) for key in ("training_rows", "validation_rows", "test_rows")] if isinstance(provenance, dict) else []
        if (not _utc_timestamp(artifact.get("created_at")) or
                not isinstance(provenance, dict) or provenance.get("origin") != "local_training" or
                provenance.get("split_seed") != config.seed or
                len(counts) != 3 or any(type(count) is not int or count <= 0 for count in counts) or
                not 20 <= sum(counts) <= 10_000 or
                counts[0] != int(0.6 * sum(counts)) or
                counts[0] + counts[1] != int(0.8 * sum(counts)) or
                artifact.get("health") != ("HEALTHY" if artifact["approval_state"] == "APPROVED" else "UNVERIFIED")):
            raise ValueError("missing model metadata")
        if artifact["approval_state"] == "APPROVED":
            approval = artifact.get("approval")
            if (not isinstance(approval, dict) or
                    set(approval) != {"reviewer", "requesting_agent_id", "rationale", "approved_at",
                                      "model_id", "model_artifact_hash", "receipt"} or
                    not isinstance(approval["reviewer"], str) or not approval["reviewer"].strip() or
                    not isinstance(approval["requesting_agent_id"], str) or
                    approval["reviewer"] == approval["requesting_agent_id"] or
                    not isinstance(approval["rationale"], str) or not approval["rationale"].strip() or
                    not _utc_timestamp(approval["approved_at"]) or
                    approval["model_id"] != artifact["model_id"] or
                    approval["model_artifact_hash"] != digest or
                    not isinstance(approval["receipt"], dict) or not approval["receipt"]):
                raise ValueError("approved model lacks review evidence")
    except (KeyError, TypeError, IndexError, OverflowError) as exc:
        raise ValueError("invalid model artifact") from exc


def save_artifact(path: Path, artifact: dict[str, Any]) -> None:
    validate_artifact(artifact)
    if path.exists():
        raise FileExistsError("model artifact already exists")
    payload = _canonical(artifact)
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise ValueError("model artifact exceeds size limit")
    with path.open("xb") as stream:
        stream.write(payload)


def load_artifact(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("model artifact exceeds size limit")
    artifact = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)
    validate_artifact(artifact)
    return artifact


def approve_candidate(artifact: dict[str, Any], *, reviewer: str, requesting_agent_id: str,
                      rationale: str, receipt: dict[str, Any],
                      verify_approval: Callable[[dict[str, Any]], bool] | None = None) -> dict[str, Any]:
    """Require an independently verified approval receipt; a name grants nothing."""
    validate_artifact(artifact)
    if (artifact["approval_state"] != "CANDIDATE" or not isinstance(reviewer, str) or
            not isinstance(requesting_agent_id, str) or not reviewer.strip() or
            reviewer == requesting_agent_id or not isinstance(rationale, str) or
            not rationale.strip() or not isinstance(receipt, dict) or not receipt):
        raise ValueError("explicit candidate review is required")
    approval = {"reviewer": reviewer, "requesting_agent_id": requesting_agent_id,
                "rationale": rationale, "approved_at": datetime.now(timezone.utc).isoformat(),
                "model_id": artifact["model_id"],
                "model_artifact_hash": artifact["model_artifact_hash"], "receipt": receipt}
    if not _verified(verify_approval, approval):
        raise PermissionError("independent model approval could not be verified")
    approved = {**artifact, "approval_state": "APPROVED", "health": "HEALTHY", "approval": approval}
    validate_artifact(approved)
    return approved


class MLPCapabilityFabric:
    """Model registry, discovery, bounded inference, and input-free health state."""

    def __init__(self, *, verify_approval: Callable[[dict[str, Any]], bool] | None = None,
                 verify_capability_decision: Callable[[dict[str, Any]], bool] | None = None) -> None:
        self.verify_approval = verify_approval
        self.verify_capability_decision = verify_capability_decision
        self.models: dict[str, dict[str, Any]] = {}
        self.stats: dict[str, dict[str, Any]] = {}

    def register(self, artifact: dict[str, Any]) -> str:
        validate_artifact(artifact)
        if artifact["approval_state"] != "APPROVED" or not artifact.get("approval"):
            raise ValueError("only reviewed models may be registered")
        if not _verified(self.verify_approval, artifact["approval"]):
            raise PermissionError("independent model approval could not be verified")
        model_id = artifact["model_id"]
        if model_id in self.models:
            raise ValueError("model identity already registered")
        self.models[model_id] = json.loads(_canonical(artifact))
        self.stats[model_id] = {"inferences": 0, "failures": 0, "input_validation_failures": 0,
                                "last_latency_ms": None, "last_verified": None, "last_failure": None}
        return model_id

    def discover(self, capability: str) -> list[dict[str, str]]:
        if capability not in CAPABILITIES:
            return []
        if capability in {"ml.mlp.train", "ml.mlp.evaluate"}:
            return [{"capability": capability, "execution": "separate_local_pipeline"}]
        return [{"model_id": model_id, "version": model["version"], "task": model["task"],
                 "capability": capability, "location": "local"}
                for model_id, model in self.models.items()
                if capability in {"ml.mlp.inference", "ml.mlp." + model["task"]}]

    def infer(self, model_id: str, rows: list[dict[str, float]], *, trace_id: str) -> dict[str, Any]:
        if model_id not in self.models:
            raise ValueError("model is not registered")
        if not trace_id or len(trace_id) > 128:
            raise ValueError("trace ID required")
        model = self.models[model_id]
        stat = self.stats[model_id]
        started = time.perf_counter()
        try:
            x = _matrix(rows, tuple(model["input_schema"]["features"]))
            if len(x) > 1000:
                raise ValueError("inference batch exceeds 1000 rows")
            widths = [len(model["input_schema"]["features"]),
                      *model["architecture"]["hidden_layers"], 1]
            if len(x) * sum(widths[k] * widths[k + 1] for k in range(len(widths) - 1)) > MAX_INFER_MULTIPLIES:
                raise ValueError("inference compute budget exceeded")
            results = [_forward(_transform(row, model["preprocessing"]), model["weights"],
                                model["task"], model["architecture"]["activation"])[-1][0] for row in x]
            if any(not math.isfinite(value) for value in results):
                raise ArithmeticError("non-finite MLP output")
            stat["inferences"] += 1
            stat["last_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            stat["last_verified"] = datetime.now(timezone.utc).isoformat()
            return {"trace_id": trace_id, "model_id": model_id, "model_version": model["version"],
                    "task": model["task"], "output": results, "device": "cpu",
                    "latency_ms": stat["last_latency_ms"], "artifact_hash": model["model_artifact_hash"],
                    "provenance": {"dataset_hash": model["dataset_hash"], "approval": model["approval"]}}
        except Exception as exc:
            stat["failures"] += 1
            if isinstance(exc, ValueError):
                stat["input_validation_failures"] += 1
            stat["last_failure"] = {"kind": type(exc).__name__,
                                    "at": datetime.now(timezone.utc).isoformat()}
            raise

    def evaluate(self, model_id: str, rows: list[dict[str, float]], labels: list[float]) -> dict[str, Any]:
        """Revalidate quality on new labeled data without changing the artifact."""
        model = self.models[model_id]
        actual = _labels(labels, model["task"], len(rows))
        result = self.infer(model_id, rows, trace_id="revalidation")
        return {"model_id": model_id, "model_version": model["version"],
                "metrics": _metrics(model["task"], actual, result["output"]),
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "training_dataset_hash": model["dataset_hash"],
                "quality_decision": "REVIEW_REQUIRED"}

    def infer_for_agent(self, agent_id: str, model_id: str, rows: list[dict[str, float]], *, trace_id: str,
                        certification: dict[str, Any], capability_decision: dict[str, Any],
                        runtime_healthy: bool) -> dict[str, Any]:
        agent = canonical_agent_id(agent_id)
        model = self.models.get(model_id)
        if model is None:
            raise ValueError("model is not registered")
        mlp_capability = "ml.mlp." + model["task"]
        if (not isinstance(capability_decision, dict) or
                capability_decision.get("capability") != mlp_capability or
                capability_decision.get("agent_id") != agent or
                capability_decision.get("model_id") != model_id or
                capability_decision.get("model_artifact_hash") != model["model_artifact_hash"] or
                capability_decision.get("trace_id") != trace_id or
                not capability_decision.get("decision_id") or
                not _verified(self.verify_capability_decision, capability_decision)):
            raise PermissionError("MLP capability authority decision is unavailable or invalid")
        capability = "responsibility." + agent
        route = select_agent_capability_route(capability, certification, authority_allowed=True,
                                              runtime_healthy=runtime_healthy, tools_available=True,
                                              model_available=True)
        if route.state != "READY" or route.agent_id != agent:
            raise PermissionError("agent capability is not certified and authorized")
        result = self.infer(model_id, rows, trace_id=trace_id)
        return {**result, "agent_id": agent, "agent_capability": capability,
                "mlp_capability": mlp_capability, "authority_decision_id": capability_decision["decision_id"],
                "agent_route_state": route.state, "requires_independent_verification": True}

    def health(self, model_id: str) -> dict[str, Any]:
        model = self.models[model_id]
        return {"model_loaded": True, "model_id": model_id, "model_version": model["version"],
                "inference_available": True, "health": model["health"], "device": "cpu",
                **self.stats[model_id]}
