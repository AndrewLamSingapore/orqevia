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
    source=value['canonical_machine_source']
    source_url=f"https://github.com/{source['repository']}/blob/{source['branch']}/{source['path']}"
    lines=['# JARVIS / PRIME — Recorded Resume Checkpoint','',
        '> Generated mirror of dated PRIME observations, not a current-status authority. Read STATUS.md for portfolio status claims and each owning repository for product source.', '',
        f'- PRIME component reference: {source_url}',
        f"- Recorded architecture release: `{release['id']}`",
        f"- Manifest snapshot state: **{value['status']}** (dated, not a current runtime verdict)",
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
    runtime = value['abex_runtime']
    if runtime['state'] == 'VERIFIED':
        runtime_summary = f"This manifest records prior independent PRIME runtime acceptance at source `{runtime['source_sha']}` and image `{runtime['observed_image']}`. This dated mirror does not establish current deployment; consult STATUS.md and live receipts. Historical Dell evidence is retained separately."
    else:
        runtime_summary = 'This manifest has no accepted PRIME runtime fields. Consult STATUS.md and live receipts for current deployment. Historical Dell evidence is retained separately. Recorded ABEX state: '+runtime['state']+'.'
    lines += ['', runtime_summary,
        '', '## Priorities recorded in the manifest', '']
    lines += [f'- {item}' for item in value['next_actions']]
    lines += ['', '## Unresolved evidence', '']
    lines += ['- '+reason for reason in value['verification']['stale_reasons']]
    lines += ['', '## Resume contract', '',
        f"Resolve PRIME {source['branch']} and read governance/CHANNEL_CONTRACT.md at that same commit for shared PRIME references. STATUS.md records portfolio status claims; each product repository owns its source, configuration, contracts and domain records. The immutable Golden manifest records generation architecture identity. This mirror and its input operational manifest are dated component and observation references. system.manifest.json binds PRIME components. No parallel portfolio status pointer is maintained. Earlier exports and installer bundles remain historical evidence.", '']
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

