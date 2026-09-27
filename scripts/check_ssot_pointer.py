"""Validate the reference contract without claiming remote/runtime freshness."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=json.loads((root/'SSOT.json').read_text())
assert p['canonical_repository']=='AndrewLamSingapore/prime'
assert p['canonical_branch']=='feat/supreme-integration-20260925'
assert p['canonical_path']=='governance/operational-manifest.json'
assert p['canonical_url']=='https://github.com/AndrewLamSingapore/prime/blob/feat/supreme-integration-20260925/governance/operational-manifest.json'
assert p['copy_policy'].startswith('REFERENCE_ONLY')
assert p['canonical_url'] in (root/'AGENTS.md').read_text()
assert p['canonical_url'] in (root/'README.md').read_text()
# STATUS.md is the single status authority; this file is a component pointer only.
assert p.get('status_authority', '').endswith('prime/blob/feat/supreme-integration-20260925/STATUS.md'), \
    'SSOT.json must point at the canonical STATUS.md'
assert p['golden_architecture']=='docs/JARVIS-PRIME-PHASE2-UNIFIED-INTELLIGENCE-ARCHITECTURE.md'
assert p['golden_manifest']=='governance/golden-gen2-manifest.json'
assert p['active_golden_generation']==2
for banned in ('status', 'current_status', 'verification', 'verified'):
    assert banned not in p, f'{banned} belongs in STATUS.md, not in a component pointer'

print('SSOT pointer: PASS; runtime freshness is independently assessed')
