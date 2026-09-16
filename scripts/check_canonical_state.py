"""Reject competing authority and false current-state claims; no runtime mutation."""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def component_hash_matches(path: Path, expected: str) -> bool:
    """Compare text content without treating checkout EOL policy as a mutation."""
    raw = path.read_bytes()
    lf = raw.replace(b'\r\n', b'\n')
    crlf = lf.replace(b'\n', b'\r\n')
    return any(hashlib.sha256(value).hexdigest() == expected for value in (raw, lf, crlf))

def validate_state(manifest, product, registry):
    release = manifest['canonical_release']
    assert release['intended_agent_count'] == len(registry['agents']) == 21
    assert release['product_manifest'] == 'system.manifest.json'
    assert release['architecture'] == 'docs/ARCHITECTURE_V1.md'
    assert product['canonical_operational_source'] == 'governance/operational-manifest.json'
    assert product['authority_scope'] == 'SUBORDINATE_PRODUCT_COMPONENT_MANIFEST'
    assert product['ecosystem_release_id'] == release['id']
    assert manifest['alignment_state']['overall'] == manifest['status']
    assert manifest['systems']['prime']['current_runtime_host'] == 'ABEX'
    if manifest['systems']['prime']['state'] == 'UNVERIFIED':
        assert manifest['systems']['prime']['runtime_sha'] is None
        assert manifest['systems']['prime']['verified_at_utc'] is None
    if manifest['status'] != 'CURRENT':
        assert manifest['release_gate']['current_result'] != 'PASSED'
    else:
        assert not manifest['verification']['stale_reasons']
        abex = manifest['abex_runtime']
        assert abex['state'] == 'VERIFIED' and abex['receipt'] and abex['source_sha']
        assert abex['verified_at_utc']
        assert abex['receipt']['independent_verification'] is True
        assert abex['receipt']['source_sha'] == abex['source_sha']
    return True

def main():
    manifest = json.loads((ROOT/'governance/operational-manifest.json').read_text())
    product = json.loads((ROOT/'system.manifest.json').read_text())
    registry = json.loads((ROOT/'config/agent_registry.json').read_text())
    validate_state(manifest, product, registry)
    sys.path.insert(0, str(ROOT/'scripts'))
    from generate_resume_checkpoint import generate
    assert (ROOT/'governance/JARVIS_Resume_Checkpoint.generated.md').read_text() == generate(manifest)
    assert component_hash_matches(ROOT/'config/agent_registry.json', product['components']['registry']['sha256'])
    print('Canonical source and generated mirror: CONSISTENT; operational state: '+manifest['status'])

if __name__ == '__main__':
    main()

