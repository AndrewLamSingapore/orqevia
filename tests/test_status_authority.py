import json
import shutil
from pathlib import Path

import pytest

from scripts.check_status_authority import validate_status_authority
from scripts.generate_resume_checkpoint import generate


ROOT = Path(__file__).parents[1]
COPY_FILES = (
    'STATUS.md', 'AGENTS.md', 'README.md', 'governance/README.md',
    'governance/CHANNEL_CONTRACT.md', 'governance/operational-manifest.json',
    'governance/JARVIS_Resume_Checkpoint.generated.md',
    'governance/golden-gen2-manifest.json',
    'docs/JARVIS-PRIME-PHASE2-UNIFIED-INTELLIGENCE-ARCHITECTURE.md',
)


@pytest.fixture
def authority_copy(tmp_path):
    for name in COPY_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    return tmp_path


def test_status_is_scoped_to_portfolio_claims():
    validate_status_authority()


def test_universal_master_claim_is_rejected(authority_copy):
    path = authority_copy / 'STATUS.md'
    path.write_text(path.read_text(encoding='utf-8') +
                    '\nThis file replaces and supersedes every previous SSOT document.\n',
                    encoding='utf-8')
    with pytest.raises(AssertionError):
        validate_status_authority(authority_copy)


def test_product_ownership_contract_is_required(authority_copy):
    path = authority_copy / 'STATUS.md'
    path.write_text(path.read_text(encoding='utf-8').replace(
        'Each product owns its source, configuration, contracts, and domain records in its repository.',
        ''), encoding='utf-8')
    with pytest.raises(AssertionError):
        validate_status_authority(authority_copy)


def test_channel_must_name_domain_ownership(authority_copy):
    path = authority_copy / 'governance/CHANNEL_CONTRACT.md'
    path.write_text(path.read_text(encoding='utf-8').replace(
        'each product repository owns its own source',
        'PRIME owns every product source'), encoding='utf-8')
    with pytest.raises(AssertionError):
        validate_status_authority(authority_copy)


def test_resume_must_not_present_dated_acceptance_as_current(authority_copy):
    path = authority_copy / 'governance/JARVIS_Resume_Checkpoint.generated.md'
    path.write_text(path.read_text(encoding='utf-8').replace(
        'This dated mirror does not establish current deployment',
        'This mirror establishes current deployment'), encoding='utf-8')
    with pytest.raises(AssertionError):
        validate_status_authority(authority_copy)


def test_retired_pointer_is_rejected(authority_copy):
    (authority_copy / 'SSOT.json').write_text('{}', encoding='utf-8')
    with pytest.raises(AssertionError, match='retired SSOT.json'):
        validate_status_authority(authority_copy)


@pytest.mark.parametrize('name', [
    'AGENTS.md', 'README.md', 'governance/README.md',
    'governance/CHANNEL_CONTRACT.md', 'governance/JARVIS_Resume_Checkpoint.generated.md',
])
def test_stale_component_reference_is_rejected(authority_copy, name):
    path = authority_copy / name
    path.write_text(path.read_text(encoding='utf-8').replace('/blob/main/',
                    '/blob/old-candidate/'), encoding='utf-8')
    with pytest.raises(AssertionError, match='PRIME component reference'):
        validate_status_authority(authority_copy)


def test_manifest_cannot_select_a_competing_branch(authority_copy):
    path = authority_copy / 'governance/operational-manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['canonical_machine_source']['branch'] = 'old-candidate'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(AssertionError):
        validate_status_authority(authority_copy)


def test_manifest_cannot_select_a_competing_status_authority(authority_copy):
    path = authority_copy / 'governance/operational-manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['status_authority'] = 'https://example.invalid/other.md'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(AssertionError):
        validate_status_authority(authority_copy)


def test_resume_canonical_link_is_derived_from_manifest():
    manifest = json.loads((ROOT / 'governance/operational-manifest.json').read_text(encoding='utf-8'))
    manifest['canonical_machine_source']['branch'] = 'isolated-fixture'
    text = generate(manifest)
    assert '/blob/isolated-fixture/governance/operational-manifest.json' in text
    assert 'Resolve PRIME isolated-fixture ' in text
    assert 'SSOT.json' not in text
    assert 'This manifest records prior independent PRIME runtime acceptance' in text
    assert 'This dated mirror does not establish current deployment' in text
