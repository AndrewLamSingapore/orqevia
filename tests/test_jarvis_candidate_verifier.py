import importlib.util
import copy
import json
import shutil
from pathlib import Path

import pytest


def test_independent_jarvis_candidate_verifier():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_jarvis_candidate.py"
    spec = importlib.util.spec_from_file_location("verify_jarvis_candidate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    result = module.verify()
    assert result["passed"] == result["total"] == 7
    assert result["production_touched"] is False
    assert result["physical_phone_tested"] is False


@pytest.mark.parametrize('mutation', ['empty', 'duplicate', 'foreign', 'size', 'name', 'scope', 'missing_asset'])
def test_install_identity_gate_rejects_missing_or_changed_boundary(mutation, tmp_path):
    from scripts.verify_jarvis_candidate import canonical_pwa_branding
    original = Path(__file__).resolve().parents[1] / 'clients/pwa'
    manifest = json.loads((original / 'manifest.webmanifest').read_text(encoding='utf-8'))
    (tmp_path / 'icons').mkdir()
    for icon in manifest['icons']:
        name = Path(icon['src']).name
        shutil.copyfile(original / 'icons' / name, tmp_path / 'icons' / name)
    (tmp_path / 'manifest.webmanifest').write_text(json.dumps(manifest), encoding='utf-8')
    assert canonical_pwa_branding(tmp_path) is True
    changed = copy.deepcopy(manifest)
    if mutation == 'empty': changed['icons'] = []
    elif mutation == 'duplicate': changed['icons'] = [changed['icons'][0]] * 2
    elif mutation == 'foreign': changed['icons'][0]['src'] = 'https://foreign.invalid/orqevia-v1-192.png'
    elif mutation == 'size': changed['icons'][0]['sizes'] = '1x1'
    elif mutation == 'name': changed['name'] = 'Unapproved identity'
    elif mutation == 'scope': changed['scope'] = '/'
    else: (tmp_path / 'icons' / Path(changed['icons'][0]['src']).name).unlink()
    (tmp_path / 'manifest.webmanifest').write_text(json.dumps(changed), encoding='utf-8')
    assert canonical_pwa_branding(tmp_path) is False
