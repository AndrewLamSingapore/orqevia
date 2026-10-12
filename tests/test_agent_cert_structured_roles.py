"""Version separation retains original policy bytes and semantic acceptance."""
import hashlib
import json
from pathlib import Path

import pytest

from app.agent_cert_response_contracts import REGISTERED_ROLE_IDS
from app.agent_cert_role_review import canonical_role_spec, review_role_output
from app.agent_cert_structured_roles import CASE_VERSION, structured_role_case
from app.agent_cert_transport import case_transport_identity


@pytest.mark.parametrize('agent', sorted(REGISTERED_ROLE_IDS))
def test_new_contract_is_explicit_and_cannot_rebind_legacy_policy(agent):
    old = canonical_role_spec(agent, f'responsibility.{agent}')
    old_bytes = json.dumps(old, sort_keys=True)
    new = structured_role_case(agent)
    assert new['case_version'] == CASE_VERSION
    assert 'response_schema' in new['request']
    assert 'response_schema' not in old['request']
    assert new['request']['context'] == old['request']['context']
    assert new['expected_discriminants'] == old['expected_discriminants']
    assert new['independent_review'] == old['independent_review']
    assert new['certification'] == 'UNVERIFIED'
    assert new['request']['data_classification'] == 'LOCAL_ONLY'
    assert new['request']['max_cost_usd'] == 0
    assert json.dumps(canonical_role_spec(agent, f'responsibility.{agent}'), sort_keys=True) == old_bytes
    with pytest.raises(ValueError, match='modified'):
        case_transport_identity(new)


def test_original_a19_signed_v2_pin_remains_exact():
    spec = canonical_role_spec('a19', 'responsibility.a19')
    raw = json.dumps(spec, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    archive = Path(__file__).resolve().parents[1] / 'governance/agent-cert-historical-admissions/a19-role-normal-20261007.json'
    policy = json.loads(archive.read_bytes())['cases'][0]['cloud_policy']
    assert policy['canonical_spec_sha256'] == 'd4ecfa3e97d0ec7b842dffac2b64fd431c40b45f98c9951d18b09ee3a724e929'
    assert hashlib.sha256(raw).hexdigest() == policy['canonical_spec_sha256']


def test_structured_shape_does_not_pass_incorrect_a19_time():
    structured_role_case('a19')
    response = json.dumps({'initial_check_pass': False, 'retry_check_pass': True,
        'continuous_health_proven': False, 'restart_authorized': False,
        'latest_check_time': '10:00Z', 'next_read_only_check': 'sample_trend'})
    assert review_role_output('a19', 'responsibility.a19', response) == (False, ('latest_check_time',))
