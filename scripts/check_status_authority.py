"""Check that portfolio status and component authority stay distinct."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS_URL = 'https://github.com/AndrewLamSingapore/prime/blob/main/STATUS.md'
SOURCE_URL = 'https://github.com/AndrewLamSingapore/prime/blob/main/governance/operational-manifest.json'


def validate_status_authority(root: Path = ROOT) -> None:
    assert not (root / 'SSOT.json').exists(), 'retired SSOT.json must not be maintained'
    status = (root / 'STATUS.md').read_text(encoding='utf-8')
    assert status.startswith('# STATUS.md — Portfolio status record'), 'STATUS.md is missing its scoped heading'
    assert 'STATUS.md records current portfolio status claims and their evidence classification.' in status
    assert 'Each product owns its source, configuration, contracts, and domain records in its repository.' in status
    assert 'replaces and supersedes every previous SSOT document' not in status

    manifest = json.loads((root / 'governance/operational-manifest.json').read_text(encoding='utf-8'))
    assert manifest['status_authority'] == STATUS_URL
    # These fields are current interpretation rules, not historical receipts.
    # Reject known positive universal-ownership statements, including those
    # which mention domains without actually preserving their ownership.
    for field in (manifest['supersession']['rule'],
                  manifest['truth_reconciliation']['authority_boundary']):
        assert 'domain' in field.lower(), 'current manifest rules must preserve domain ownership'
        assert 'manifest alone selects' not in field.lower(), 'manifest cannot own runtime truth'
        assert 'status.md alone owns current status' not in field.lower(), 'status index cannot own operational truth'
        assert not re.search(r'\b(?:single|universal|master|global)(?:[-\s]+\w+){0,4}\s+(?:owns|selects|governs|controls|is authoritative)\b', field, re.I), 'current reference cannot assert universal ownership'
    assert 'Truth must be proven at the relevant authority boundary.' in manifest['truth_reconciliation']['authority_boundary']
    assert manifest['canonical_machine_source'] == {
        'repository': 'AndrewLamSingapore/prime',
        'branch': 'main',
        'path': 'governance/operational-manifest.json',
    }
    for name in ('AGENTS.md', 'README.md', 'governance/README.md',
                 'governance/CHANNEL_CONTRACT.md',
                 'governance/JARVIS_Resume_Checkpoint.generated.md'):
        content = (root / name).read_text(encoding='utf-8')
        assert SOURCE_URL in content, f'{name} must identify the PRIME component reference'
        assert 'STATUS.md' in content, f'{name} must identify the status authority'
    channel = (root / 'governance/CHANNEL_CONTRACT.md').read_text(encoding='utf-8')
    assert 'each product repository owns its own source' in channel
    mirror = (root / 'governance/JARVIS_Resume_Checkpoint.generated.md').read_text(encoding='utf-8')
    assert 'This dated mirror does not establish current deployment' in mirror
    for name in ('governance/golden-gen2-manifest.json',
                 'docs/JARVIS-PRIME-PHASE2-UNIFIED-INTELLIGENCE-ARCHITECTURE.md'):
        assert (root / name).is_file(), f'Golden reference missing: {name}'


if __name__ == '__main__':
    validate_status_authority()
    print('Portfolio status scope: PASS; runtime freshness is independently assessed')
