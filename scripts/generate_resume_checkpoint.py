#!/usr/bin/env python3
"""Generate the human resume checkpoint from the canonical machine manifest."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "governance" / "operational-manifest.json"
DEFAULT_OUTPUT = ROOT / "governance" / "JARVIS_Resume_Checkpoint.generated.md"


def short(value: Any) -> str:
    return "—" if value is None else str(value)[:12]


def generate(value: dict[str, Any]) -> str:
    verification = value["verification"]
    lines = [
        "# JARVIS / PRIME Resume Checkpoint",
        "",
        "> Generated from `governance/operational-manifest.json`. Do not maintain this file manually.",
        "",
        f"- Effective status: **{value['status']}**",
        f"- Manifest observation: `{value['as_of_utc']}`",
        f"- Verification time: `{verification['verified_at_utc']}`",
        f"- Freshness window: `{verification['stale_after_hours']} hours`",
        "",
        "## System facts",
        "",
        "| System | Source head | Release | Runtime | Verified | State |",
        "|---|---|---|---|---|---|",
    ]
    for system_id in value["scope"]["active_systems"]:
        system = value["systems"][system_id]
        lines.append(
            f"| {system_id} | `{short(system.get('source_head_sha'))}` | "
            f"`{short(system.get('release_sha'))}` | `{short(system.get('runtime_sha'))}` | "
            f"`{system.get('verified_at_utc')}` | {system.get('state', 'recorded')} |"
        )
    shared = value["shared_contract"]
    lines.extend([
        "",
        "## Shared contract",
        "",
        f"- Version: `{shared['version']}`",
        f"- Publication commit: `{shared['source_sha']}`",
        f"- Canonical file: `{shared['repository']}/{shared['path']}`",
        "",
        "## Branch classification",
        "",
        f"- Snapshot: `{value['github_hygiene']['branch_inventory']['snapshot_at_utc']}`",
        f"- Total non-main branches: `{value['github_hygiene']['branch_inventory']['total_non_main_branches']}`",
    ])
    for name, count in value["github_hygiene"]["branch_inventory"]["classification_counts"].items():
        lines.append(f"- {name}: `{count}`")
    dell = value["dell_runtime"]
    lines.extend([
        "",
        "## Dell acceptance gate",
        "",
        f"- Command: `{dell['command']}`",
        f"- Accepted: `{str(dell['accepted']).lower()}`",
        f"- Last observed runtime: `{dell['runtime_sha']}`",
        f"- Last status capture: `{dell['verified_at_utc']}`",
        f"- Post-update status: `{str(dell['post_update_status']).lower()}`",
        f"- Result: {dell['result']}",
    ])
    reasons = verification.get("stale_reasons", [])
    lines.extend(["", "## Current blockers", ""])
    if reasons:
        lines.extend(f"- `{reason}`" for reason in reasons)
    else:
        lines.append("- None.")
    lines.extend([
        "",
        "## Resume rule",
        "",
        "Re-run the live verifier before relying on this checkpoint. A manifest older than 24 hours is STALE. "
        "PRIME may be declared aligned only after a post-update Dell `JARVIS.cmd status` acceptance check.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    value = json.loads(args.manifest.read_text(encoding="utf-8"))
    expected = generate(value)
    if args.check:
        actual = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if actual != expected:
            print(f"Generated checkpoint drift: {args.output}", file=sys.stderr)
            return 1
        print("Generated checkpoint: CURRENT")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
