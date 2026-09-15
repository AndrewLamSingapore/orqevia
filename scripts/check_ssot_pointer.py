"""Validate the reference contract without claiming remote/runtime freshness."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=json.loads((root/'SSOT.json').read_text())
assert p['canonical_repository']=='AndrewLamSingapore/prime'
assert p['canonical_branch']=='main'
assert p['canonical_path']=='governance/operational-manifest.json'
assert p['canonical_url']=='https://github.com/AndrewLamSingapore/prime/blob/main/governance/operational-manifest.json'
assert p['copy_policy'].startswith('REFERENCE_ONLY')
assert p['canonical_url'] in (root/'AGENTS.md').read_text()
assert p['canonical_url'] in (root/'README.md').read_text()
print('SSOT pointer: PASS; runtime freshness is independently assessed')
