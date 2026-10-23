"""Offline bounded reference model, never an application training endpoint.

The declared synthetic quadratic tests numerical integration, not business or
agent competence. The Owner authorized this local fabric activation. A separate
forward-pass implementation checks unseen points before exact model admission.
"""

import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.mlp_fabric import MLPConfig, approve_candidate, save_artifact, train_candidate


def independent_predict(model, x):
    prep = model["preprocessing"]
    # This checker deliberately does not use the fabric forward-pass functions.
    values = [(x - prep["mean"][0]) / prep["scale"][0]]
    for index, layer in enumerate(model["weights"]):
        values = [
            sum(a * b for a, b in zip(weights, values)) + bias
            for weights, bias in zip(layer["weights"], layer["biases"])
        ]
        if index < len(model["weights"]) - 1:
            values = [max(0.0, v) for v in values]
    return values[0]


def main():
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError("Use a new empty artifact directory; admission is never overwritten")
    rows = [{"x": i / 10} for i in range(-30, 30)]
    candidate = train_candidate(
        MLPConfig("regression", ("x",), hidden_layers=(8,), activation="relu", seed=12, epochs=250),
        rows,
        [r["x"] ** 2 for r in rows],
        dataset_reference="declared-synthetic:quadratic-reference-v1",
    )
    points = [-2.95 + i / 10 for i in range(59)]
    errors = [abs(independent_predict(candidate, x) - x * x) for x in points]
    observed = {"points": len(points), "mae": sum(errors) / len(errors), "max_absolute_error": max(errors)}
    assert observed["mae"] < 0.30 and observed["max_absolute_error"] < 0.90
    assert candidate["evaluation_result"]["test"]["mae"] < 0.25
    assert candidate["evaluation_result"]["test"]["mae"] < candidate["evaluation_result"]["baseline_test"]["mae"]
    receipt = {
        "authority": "owner-chat-20261023-production-activation",
        "scope": "BOUNDED_SYNTHETIC_NUMERICAL_REFERENCE_ONLY",
        "model_id": candidate["model_id"],
        "artifact_hash": candidate["model_artifact_hash"],
        "independent_numeric_check": observed,
        "input_domain": [-3.0, 2.9],
        "grants_agent_authority": False,
        "automatic_training": False,
    }

    def verify(approval):
        return (
            approval["receipt"] == receipt
            and approval["model_id"] == receipt["model_id"]
            and approval["model_artifact_hash"] == receipt["artifact_hash"]
            and approval["reviewer"] == "abex-release-numerical-checker"
            and approval["requesting_agent_id"] == "abex-offline-training"
        )

    approved = approve_candidate(
        candidate,
        reviewer="abex-release-numerical-checker",
        requesting_agent_id="abex-offline-training",
        rationale="Owner-authorized local reference deployment; held-out and independent numerical checks passed; no agent certification granted.",
        receipt=receipt,
        verify_approval=verify,
    )
    save_artifact(directory / "quadratic-reference-v1.json", approved)
    sha = hashlib.sha256((directory / "quadratic-reference-v1.json").read_bytes()).hexdigest()
    print(
        json.dumps(
            {
                "artifact_sha256": sha,
                "model_id": approved["model_id"],
                "model_artifact_hash": approved["model_artifact_hash"],
                "review": observed,
                "evaluation": candidate["evaluation_result"],
            }
        )
    )


if __name__ == "__main__":
    main()
