"""Read local queue evidence and record a reproducible shadow-only PIF report.

This command does not initialize or mutate the queue, dispatch inference,
contact a provider, or promote a model into an operational execution route.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pif.history import QUEUE_ABSORBING, QUEUE_EDGES, QUEUE_STATES, read_compute_history
from app.pif.service import PIFService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--agent")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--tenant", default="owner")
    args = parser.parse_args(argv)
    queue_path, registry_path, output_path = (p.resolve() for p in (args.queue, args.registry, args.output))
    if queue_path in {registry_path, output_path} or registry_path == output_path:
        parser.error("queue, registry and output must be distinct files")
    if output_path.exists():
        parser.error("preserve existing evidence; choose a new output file")
    svc = PIFService(registry_path, enabled=True, tenant_id=args.tenant)
    histories, diagnostics = read_compute_history(queue_path, agent=args.agent, since=args.since, until=args.until)
    fit = svc.fit_history(
        histories,
        states=QUEUE_STATES,
        absorbing_states=QUEUE_ABSORBING,
        allowed_edges=QUEUE_EDGES,
        source_revision=args.source_revision,
        evidence_source="COMPUTE_EVENT_LEDGER_READ_ONLY",
    )
    predictions = {state: svc.forecast_state(state, steps=2) for state in ("queued", "held", "running")}
    report = {
        "schema": "orqevia.pif.shadow-report.v1",
        "source_revision": args.source_revision,
        "source_diagnostics": diagnostics,
        "fit": fit,
        "predictions": predictions,
        "production_quality_validated": False,
        "deployment_claim": "NONE",
        "grants_execution_authority": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "fit_status": fit["status"],
                "source_status": diagnostics["status"],
                "output": str(output_path),
                "production_quality_validated": False,
            }
        )
    )
    return 0 if diagnostics["status"] == "OBSERVED" and fit["status"] in {"SHADOW", "INSUFFICIENT_DATA"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
