import json
from pathlib import Path

import pytest

from app import secret_refs
from app.compute_catalog import load_catalog
from app.provider_runtime import HuggingFaceProvider


def test_fixed_hf_file_reference_reads_only_mount(monkeypatch, tmp_path):
    mounted = tmp_path / 'hf_token'
    mounted.write_text('fixtureonly', encoding='ascii')
    monkeypatch.setattr(secret_refs, 'HF_TOKEN_FILE', str(mounted))
    assert secret_refs.resolve_secret('file:HF_TOKEN') == 'fixtureonly'
    assert HuggingFaceProvider('file:HF_TOKEN').health()['readiness'] == 'READY'
    for reference in ('file:../hf_token', f'file:{mounted}', 'file:OTHER_TOKEN'):
        with pytest.raises(secret_refs.SecretUnavailable):
            secret_refs.resolve_secret(reference)


@pytest.mark.parametrize('contents', ('', 'fixtureonly\n', 'fixture only', 'x' * 4097, 'fixturé'))
def test_hf_file_rejects_invalid_bytes_without_disclosure(monkeypatch, tmp_path, contents):
    mounted = tmp_path / 'hf_token'
    mounted.write_text(contents, encoding='utf-8')
    monkeypatch.setattr(secret_refs, 'HF_TOKEN_FILE', str(mounted))
    with pytest.raises(secret_refs.SecretUnavailable) as failure:
        secret_refs.resolve_secret('file:HF_TOKEN')
    assert 'fixture' not in str(failure.value) and str(mounted) not in str(failure.value)


def test_hf_file_rejects_missing_directory_and_symlink(monkeypatch, tmp_path):
    mounted = tmp_path / 'hf_token'
    monkeypatch.setattr(secret_refs, 'HF_TOKEN_FILE', str(mounted))
    with pytest.raises(secret_refs.SecretUnavailable):
        secret_refs.resolve_secret('file:HF_TOKEN')
    mounted.mkdir()
    with pytest.raises(secret_refs.SecretUnavailable):
        secret_refs.resolve_secret('file:HF_TOKEN')
    mounted.rmdir()
    target = tmp_path / 'target'
    target.write_text('fixtureonly', encoding='ascii')
    try:
        mounted.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip('Host does not allow test symlinks')
    with pytest.raises(secret_refs.SecretUnavailable):
        secret_refs.resolve_secret('file:HF_TOKEN')


def test_hf_example_remains_disabled_with_file_reference():
    path = Path(__file__).resolve().parents[1] / 'config' / 'provider-catalog.huggingface.example.json'
    raw = json.loads(path.read_text(encoding='utf-8'))
    entry = load_catalog(path)[0]
    assert raw['status'] == 'HUGGING_FACE_CANDIDATE_NOT_QUALIFIED'
    assert entry['enabled'] is False and entry['secret_ref'] == 'file:HF_TOKEN'


def test_hf_file_reference_cannot_be_routed_to_other_provider(tmp_path):
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps({'models': [{
        'id': 'not-hf', 'provider_kind': 'chat_completions', 'enabled': True,
        'location': 'cloud', 'tier': 'MINI', 'model': 'fixture-model',
        'endpoint': 'https://other.invalid/v1/chat/completions',
        'secret_ref': 'file:HF_TOKEN', 'context_tokens': 4096, 'output_tokens': 64,
    }]}))
    with pytest.raises(ValueError, match='Hugging Face secret'):
        load_catalog(catalog)
