import copy
import hashlib
import json
from pathlib import Path
import pytest
from scripts.check_canonical_state import component_hash_matches, validate_state

ROOT=Path(__file__).resolve().parents[1]

def records():
    return tuple(json.loads((ROOT/p).read_text()) for p in (
        'governance/operational-manifest.json','system.manifest.json','config/agent_registry.json'))

def test_truthful_stale_source_can_be_published():
    assert validate_state(*records())

def test_nested_current_cannot_override_stale():
    m,p,r=records();m['alignment_state']['overall']='CURRENT'
    with pytest.raises(AssertionError):validate_state(m,p,r)

def test_old_pass_cannot_masquerade_as_current_release():
    m,p,r=records();m['release_gate']['current_result']='PASSED'
    with pytest.raises(AssertionError):validate_state(m,p,r)

def test_dell_acceptance_does_not_prove_abex_deployment():
    m,p,r=records();m['status']='CURRENT';m['alignment_state']['overall']='CURRENT'
    m['verification']['stale_reasons']=[];m['dell_runtime']['accepted']=True
    with pytest.raises(AssertionError):validate_state(m,p,r)

def test_component_manifest_cannot_select_another_release():
    m,p,r=records();p['ecosystem_release_id']='another-current-version'
    with pytest.raises(AssertionError):validate_state(m,p,r)

def test_component_hash_accepts_checkout_eol_conversion(tmp_path):
    component=tmp_path/'component.json'
    component.write_bytes(b'{\r\n  "ok": true\r\n}\r\n')
    canonical=b'{\n  "ok": true\n}\n'
    assert component_hash_matches(component,hashlib.sha256(canonical).hexdigest())

def test_component_hash_rejects_content_change(tmp_path):
    component=tmp_path/'component.json'
    component.write_bytes(b'{\r\n  "ok": false\r\n}\r\n')
    canonical=b'{\n  "ok": true\n}\n'
    assert not component_hash_matches(component,hashlib.sha256(canonical).hexdigest())
