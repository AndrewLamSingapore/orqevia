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
    release=value['canonical_release']
    lines=['# JARVIS / PRIME — Current Resume Checkpoint','',
        '> Generated mirror of the sole operational SSOT. Read current PRIME main before resuming.', '',
        '- Canonical source: https://github.com/AndrewLamSingapore/prime/blob/main/governance/operational-manifest.json',
        f"- Selected architecture release: `{release['id']}`",
        f"- Operational status: **{value['status']}**",
        f"- Source observation: `{value['as_of_utc']}`",
        '- Architecture: ABEX PRIME; Dell/PWA/voice clients; 21 agents; direct observed bounded work.',
        '- This applies to ChatGPT, Codex, Sol and Astra. Model memory and old chats are not current authority.',
        '- Source publication does not prove deployment. Historical Dell observations do not prove ABEX identity.',
        '', '## Source observations and deployment evidence', '',
        '| System | Recorded source | Last recorded release | Last recorded runtime | Evidence state |',
        '|---|---|---|---|---|']
    for name in value['scope']['active_systems']:
        system=value['systems'][name]
        lines.append(f"| {name} | `{short(system.get('source_head_sha'))}` | `{short(system.get('release_sha'))}` | `{short(system.get('runtime_sha'))}` | {system['state']} |")
    lines += ['', 'PRIME SHA/image compatibility fields above describe historical Dell evidence only. Current ABEX runtime: '+value['abex_runtime']['state']+'.',
        '', '## Current priorities', '']
    lines += [f'- {item}' for item in value['next_actions']]
    lines += ['', '## Unresolved evidence', '']
    lines += ['- '+reason for reason in value['verification']['stale_reasons']]
    lines += ['', '## Resume contract', '',
        'Resolve PRIME main and read governance/CHANNEL_CONTRACT.md at that same commit. Only governance/operational-manifest.json selects current architecture and operational state. system.manifest.json is a subordinate product manifest. Repository SSOT.json files are references. This is the only current human resume mirror; earlier exports and installer bundles are superseded.', '']
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
        print("Generated checkpoint: CONSISTENT (runtime freshness is separate)")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
