"""Validate the reference contract without claiming remote/runtime freshness."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def validate_pointer(root: Path = ROOT) -> None:
    p = json.loads((root / 'SSOT.json').read_text(encoding='utf-8'))
    assert p['canonical_repository'] == 'AndrewLamSingapore/prime'
    assert p['canonical_branch'] == 'main'
    assert p['canonical_path'] == 'governance/operational-manifest.json'
    assert p['canonical_url'] == 'https://github.com/AndrewLamSingapore/prime/blob/main/governance/operational-manifest.json'
    assert p['copy_policy'].startswith('REFERENCE_ONLY')
    for name in ('AGENTS.md', 'README.md', 'governance/README.md',
                 'governance/CHANNEL_CONTRACT.md',
                 'governance/JARVIS_Resume_Checkpoint.generated.md'):
        assert p['canonical_url'] in (root / name).read_text(encoding='utf-8'), \
            f'{name} must select the same canonical source as SSOT.json'
    # STATUS.md is the status authority; this remains a component pointer only.
    assert p.get('status_authority') == 'https://github.com/AndrewLamSingapore/prime/blob/main/STATUS.md', \
        'SSOT.json must point at the canonical STATUS.md'
    manifest = json.loads((root / p['canonical_path']).read_text(encoding='utf-8'))
    assert manifest['canonical_machine_source'] == {
        'repository': p['canonical_repository'],
        'branch': p['canonical_branch'],
        'path': p['canonical_path'],
    }, 'operational manifest and SSOT.json canonical sources differ'
    assert manifest['status_authority'] == p['status_authority']
    assert p['golden_architecture'] == 'docs/JARVIS-PRIME-PHASE2-UNIFIED-INTELLIGENCE-ARCHITECTURE.md'
    assert p['golden_manifest'] == 'governance/golden-gen2-manifest.json'
    assert p['active_golden_generation'] == 2
    for banned in ('status', 'current_status', 'verification', 'verified'):
        assert banned not in p, f'{banned} belongs in STATUS.md, not in a component pointer'


if __name__ == '__main__':
    validate_pointer()
    print('SSOT pointer: PASS; runtime freshness is independently assessed')
