"""Run the fixed model-free workflow comparison; never changes production policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evolution_experiments import run_experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="Directory for a new immutable evidence file; no production default."
    )
    args = parser.parse_args()
    result = run_experiment(args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("schema", "run_id", "evidence_scope", "selection", "production_policy_changed")
            }
        )
    )
    if "artifact_path" in result:
        print(json.dumps({"artifact_path": result["artifact_path"]}))


if __name__ == "__main__":
    main()
