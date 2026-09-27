import json
import shutil
from pathlib import Path

import pytest

from scripts.check_ssot_pointer import validate_pointer
from scripts.generate_resume_checkpoint import generate


ROOT = Path(__file__).parents[1]


@pytest.fixture
def pointer_copy(tmp_path):
    for name in (
        'SSOT.json', 'AGENTS.md', 'README.md', 'governance/README.md',
        'governance/CHANNEL_CONTRACT.md', 'governance/operational-manifest.json',
        'governance/JARVIS_Resume_Checkpoint.generated.md',
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    return tmp_path


def test_current_pointer_documents_and_manifest_agree():
    validate_pointer()


@pytest.mark.parametrize('name', [
    'AGENTS.md', 'README.md', 'governance/README.md',
    'governance/CHANNEL_CONTRACT.md', 'governance/JARVIS_Resume_Checkpoint.generated.md',
])
def test_stale_current_document_pointer_is_rejected(pointer_copy, name):
    path = pointer_copy / name
    path.write_text(path.read_text(encoding='utf-8').replace('/blob/main/',
                    '/blob/feat/supreme-integration-20260925/'), encoding='utf-8')
    with pytest.raises(AssertionError, match='same canonical source'):
        validate_pointer(pointer_copy)


def test_manifest_cannot_select_a_competing_branch(pointer_copy):
    path = pointer_copy / 'governance/operational-manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    manifest['canonical_machine_source']['branch'] = 'old-candidate'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(AssertionError, match='canonical sources differ'):
        validate_pointer(pointer_copy)


def test_resume_canonical_link_is_derived_from_the_manifest():
    manifest = json.loads((ROOT / 'governance/operational-manifest.json').read_text(encoding='utf-8'))
    manifest['canonical_machine_source']['branch'] = 'isolated-fixture'
    text = generate(manifest)
    assert '/blob/isolated-fixture/governance/operational-manifest.json' in text
    assert 'Resolve PRIME isolated-fixture ' in text
    assert 'feat/supreme-integration-20260925' not in text
