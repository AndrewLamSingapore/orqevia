"""Check that portfolio status and component authority stay distinct."""
import json
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
    assert manifest['canonical_machine_source'] == {
        'repository': 'AndrewLamSingapore/prime',
        'branch': 'main',
        'path': 'governance/operational-manifest.json',
    }
    for name in ('AGENTS.md', 'README.md', 'governance/README.md',
                 'governance/CHANNEL_CONTRACT.md',
                 'governance/JARVIS_Resume_Checkpoint.generated.md'):
        content = (root / name).read_text(encoding='utf-8')
        assert SOURCE_URL in content, f'{name} must identify the canonical component reference'
        assert 'STATUS.md' in content, f'{name} must identify the status authority'
    for name in ('governance/golden-gen2-manifest.json',
                 'docs/JARVIS-PRIME-PHASE2-UNIFIED-INTELLIGENCE-ARCHITECTURE.md'):
        assert (root / name).is_file(), f'Golden reference missing: {name}'


if __name__ == '__main__':
    validate_status_authority()
    print('STATUS authority: PASS; runtime freshness is independently assessed')
