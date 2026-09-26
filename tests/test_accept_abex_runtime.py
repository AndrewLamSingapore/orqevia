import copy, json
from pathlib import Path
import pytest
from scripts.accept_abex_runtime import ARTIFACT_SHA, RECEIPT_SHA, SOURCE_SHA, transition, validate_documents

ROOT=Path(__file__).resolve().parents[1]

def test_exact_documents_bind_independent_verification_to_receipt():
    artifact,receipt=validate_documents(ROOT/'docs/evidence/DELL-ABEX-CORRECTED-INDEPENDENT-VERIFICATION-20260926.json',ROOT/'docs/evidence/ABEX_RUNTIME_RECEIPT_17FAD78_20260926.json')
    assert artifact['receipt_hash_digest']==RECEIPT_SHA
    assert receipt['runtime']['source_sha']==SOURCE_SHA

def test_acceptance_transition_is_bounded_and_exactly_once():
    manifest=json.loads((ROOT/'governance/operational-manifest.json').read_text())
    manifest['abex_runtime']['state']='UNVERIFIED'
    artifact=json.loads((ROOT/'docs/evidence/DELL-ABEX-CORRECTED-INDEPENDENT-VERIFICATION-20260926.json').read_text())
    result=transition(copy.deepcopy(manifest),artifact,{'source_sha':SOURCE_SHA},'2026-09-26T07:30:00Z')
    assert result['abex_runtime']['state']=='VERIFIED'
    assert result['abex_runtime']['receipt']['independent_artifact_sha256']==ARTIFACT_SHA
    assert result['status']=='STALE'
    assert result['qualified_local_prime_baseline']['state']=='FROZEN'
    assert result['local_prime_commissioning']['state']=='CLOSED'
    assert result['dell_runtime']['verified_at_utc']=='2026-09-26T07:25:32Z'
    with pytest.raises(AssertionError): transition(result,artifact,{},'2026-09-26T07:31:00Z')

def test_mutated_artifact_is_rejected(tmp_path):
    source=ROOT/'docs/evidence/DELL-ABEX-CORRECTED-INDEPENDENT-VERIFICATION-20260926.json'
    bad=tmp_path/source.name
    bad.write_bytes(source.read_bytes()+b' ')
    with pytest.raises(AssertionError): validate_documents(bad,ROOT/'docs/evidence/ABEX_RUNTIME_RECEIPT_17FAD78_20260926.json')
