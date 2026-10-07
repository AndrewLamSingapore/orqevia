"""Pure source/projection checks, with synthetic data and no external execution."""
import copy
import hashlib
import json

import pytest

from app.agent_registry import load_agent_registry
from app.hf_operational_profile import project_hf_operational_profile


TASK = '687845ae-6032-4355-a5e2-f124c8b22e07'
JOB = 'ee56994f-6078-4368-8247-7a89bc690073'
MODEL = 'google/gemma-3-4b-it:deepinfra'


def bind_digest(attempt):
    unsigned = {key: value for key, value in attempt.items() if key != 'evidence_sha256'}
    attempt['evidence_sha256'] = hashlib.sha256(json.dumps(unsigned, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def fixture_observation(fallback=False):
    rows = []
    for pid in (['hf-primary', 'hf-alternate'] if fallback else ['hf-primary']):
        rows.append({'provider_id': pid, 'model': MODEL, 'enabled': True,
            'catalog_qualification': 'DECLARED_NOT_INDEPENDENTLY_VERIFIED',
            'declared_qualification': 'QUALIFIED', 'provider_health': 'UNMEASURED',
            'network_probe_performed': False, 'readiness': 'READY',
            'circuit': {'provider_id': pid, 'scope': 'PROCESS_LOCAL_ADMISSION_NOT_PROVIDER_HEALTH',
                'replay_authorized': False, 'circuit_state': 'CLOSED'}})
    attempt = {'attempt_id': 'a' * 32, 'queue_job_id': JOB, 'agent_id': 'a20',
        'requested_provider': 'hf-primary', 'requested_model': MODEL,
        'selected_provider': 'hf-alternate' if fallback else 'hf-primary', 'selected_model': MODEL,
        'tier': 'NANO', 'success': True, 'failure_code': None,
        'fallback_route': [{'provider': 'hf-primary', 'code': 'CAPACITY'}] if fallback else [],
        'error_classifications': ['CAPACITY'] if fallback else [],
        'retries': 0, 'total_tokens': 145, 'cached_tokens': 0, 'cost_usd': .00000745,
        'elapsed_seconds': .7, 'job_started_at': '2026-10-07T04:59:58Z',
        'job_completed_at': '2026-10-07T04:59:59Z'}
    bind_digest(attempt)
    return {'schema_version': 'jarvis.hf-observation.v1',
        'inspection_at': '2026-10-07T05:00:02Z',
        'inspection_scope': 'READ_ONLY_DOMAIN_PROJECTION_NOT_PROVIDER_PROBE_OR_CERTIFICATION',
        'verification': 'UNVERIFIED', 'provider_health': 'UNMEASURED',
        'network_probe_performed': False, 'registration_status': 'CONFIGURED', 'providers': rows,
        'objective_evidence': {'objective_id': TASK, 'revision': 2,
            'record_id': f'objective:{TASK}:r2', 'source': 'PRIME_OBJECTIVE_STORE',
            'status': 'OBSERVED', 'integrity': 'VALID', 'currentness': 'CURRENT',
            'verification': 'UNVERIFIED', 'independent_signature': 'UNVERIFIED',
            'currentness_basis': 'OBJECTIVE_SNAPSHOT_EQUALITY_NOT_TIME_FRESHNESS',
            'time_freshness': 'UNKNOWN', 'runtime_binding': 'UNVERIFIED',
            'production_acceptance': 'UNVERIFIED', 'captured_at': '2026-10-07T05:00:00Z',
            'hf_attempts': [attempt]}}


def agent(profile, identity='a20'):
    return next(row for row in profile['agents'] if row['agent_id'] == identity)


def test_actual_21_population_allows_optional_advisory_text_not_required_hf():
    profile = project_hf_operational_profile()
    actual = [row['id'] for row in load_agent_registry()['agents']]
    assert profile['permanent_agent_count'] == 21
    assert profile['authoritative_agent_ids'] == actual
    assert {'a26', 'a28', 'a29'} <= set(actual)
    assert 'a03' not in actual
    assert all(row['applicability'] == 'OPTIONAL' for row in profile['agents'])
    assert all(row['authorization'] == 'NOT_GRANTED_BY_PROFILE' for row in profile['agents'])
    assert all(row['last_dated_success'] is None for row in profile['agents'])
    assert profile['registration_status'] == 'UNKNOWN'
    assert profile['providers'] == []
    assert profile['network_probe_performed'] is False and profile['model_calls'] == 0


def test_readiness_qualification_and_dated_execution_do_not_become_health_role_quality_or_l7():
    profile = project_hf_operational_profile(fixture_observation())
    provider = profile['providers'][0]
    assert provider['configured'] is True and provider['readiness'] == 'READY'
    assert provider['declared_qualification'] == 'QUALIFIED'
    assert provider['qualification_verification'] == 'UNVERIFIED'
    assert provider['provider_health'] == 'UNMEASURED'
    row = agent(profile)
    assert row['last_dated_success']['evidence_ref'] == f'objective:{TASK}:r2'
    assert row['last_dated_success']['selected_provider_configuration'] == 'DECLARED_HF_ENTRY'
    assert row['role_quality'] == 'UNKNOWN'
    assert row['l7_status'] == 'NOT_ASSESSED_BY_THIS_PROFILE'
    assert row['independent_attestation'] == 'UNVERIFIED'
    assert row['failover_observation'] == 'UNKNOWN'
    assert agent(profile, 'a18')['last_dated_success'] is None


def test_stale_dated_work_is_retained_without_new_current_provider_claim():
    observation = fixture_observation()
    observation['objective_evidence']['currentness'] = 'STALE'
    profile = project_hf_operational_profile(observation)
    assert agent(profile)['last_dated_success']['currentness'] == 'STALE'
    assert profile['persisted_lens_evidence']['time_freshness'] == 'UNKNOWN'
    assert agent(profile)['provider_health'] == 'UNMEASURED'


def test_validated_failover_is_dated_unverified_not_outage_certification():
    profile = project_hf_operational_profile(fixture_observation(fallback=True))
    assert agent(profile)['failover_observation'] == 'OBSERVED_DATED_UNVERIFIED'
    assert agent(profile)['last_dated_success']['selected_provider'] == 'hf-alternate'
    assert agent(profile)['role_quality'] == 'UNKNOWN'


def test_non_hf_alternate_is_not_invented_as_configured_or_healthy():
    observation = fixture_observation(fallback=True)
    observation['providers'].pop()
    row = observation['objective_evidence']['hf_attempts'][0]
    row['selected_provider'] = 'separately-qualified-provider'
    row['selected_model'] = 'public-small-model'
    bind_digest(row)
    profile = project_hf_operational_profile(observation)
    assert agent(profile)['failover_observation'] == 'OBSERVED_DATED_UNVERIFIED'
    assert agent(profile)['last_dated_success']['selected_provider_configuration'] == 'UNKNOWN_NOT_IN_HF_PROVIDER_PROJECTION'
    assert [provider['provider_id'] for provider in profile['providers']] == ['hf-primary']


@pytest.mark.parametrize('mutation', ['digest', 'wrong-agent', 'wrong-job', 'wrong-route', 'no-route',
    'extra-private-field', 'success-string', 'cost-bool', 'tokens-bool', 'retries-none',
    'bad-date', 'reversed-date', 'future-completion', 'duplicate-attempt', 'signature-upgrade',
    'wrong-record', 'capture-after-inspection', 'health-pass', 'registration-flags-only'])
def test_invalid_or_flags_only_observation_never_proves_execution(mutation):
    observation = fixture_observation(fallback=True)
    evidence = observation['objective_evidence']
    row = evidence['hf_attempts'][0]
    if mutation == 'digest': row['evidence_sha256'] = '0' * 64
    elif mutation == 'wrong-agent': row['agent_id'] = 'a99'
    elif mutation == 'wrong-job': row['queue_job_id'] = '../private'
    elif mutation == 'wrong-route': row['selected_provider'] = 'https://private.invalid'
    elif mutation == 'no-route': row['fallback_route'] = []
    elif mutation == 'extra-private-field': row['raw_prompt'] = 'PRIVATE_SENTINEL'
    elif mutation == 'success-string': row['success'] = 'true'
    elif mutation == 'cost-bool': row['cost_usd'] = False
    elif mutation == 'tokens-bool': row['total_tokens'] = True
    elif mutation == 'retries-none': row['retries'] = None
    elif mutation == 'bad-date': row['job_completed_at'] = 'PRIVATE_SENTINEL'
    elif mutation == 'reversed-date': row['job_completed_at'] = '2026-10-07T04:00:00Z'
    elif mutation == 'future-completion': row['job_completed_at'] = '2026-10-07T05:30:00Z'
    elif mutation == 'duplicate-attempt': evidence['hf_attempts'].append(copy.deepcopy(row))
    elif mutation == 'signature-upgrade': evidence['verification'] = 'VERIFIED'
    elif mutation == 'wrong-record': evidence['record_id'] = f'objective:{JOB}:r2'
    elif mutation == 'capture-after-inspection': evidence['captured_at'] = '2026-10-07T05:10:00Z'
    elif mutation == 'health-pass': observation['provider_health'] = 'PASS'
    else:
        observation['providers'] = []
    if mutation != 'digest': bind_digest(row)
    profile = project_hf_operational_profile(observation)
    assert profile['observation_status'] == 'INVALID_DOMAIN_OBSERVATION'
    assert all(item['last_dated_success'] is None for item in profile['agents'])
    assert profile['persisted_lens_evidence'] is None
    assert 'PRIVATE_SENTINEL' not in json.dumps(profile)


def test_private_unknown_fields_are_never_reexported():
    observation = fixture_observation()
    observation['secret'] = 'PRIVATE_SENTINEL'
    observation['providers'][0]['endpoint'] = 'https://PRIVATE_SENTINEL'
    observation['providers'][0]['secret_ref'] = 'PRIVATE_SENTINEL'
    observation['objective_evidence']['private'] = 'PRIVATE_SENTINEL'
    profile = project_hf_operational_profile(observation)
    assert profile['observation_status'] == 'OBSERVED_DOMAIN_METADATA_UNVERIFIED'
    assert 'PRIVATE_SENTINEL' not in json.dumps(profile)


@pytest.mark.parametrize('evidence', [None, {'status': 'MISSING'}, {'status': 'INVALID'}])
def test_missing_evidence_remains_unknown_not_zero_quality(evidence):
    observation = fixture_observation()
    observation['objective_evidence'] = evidence
    profile = project_hf_operational_profile(observation)
    assert all(row['last_dated_success'] is None and row['role_quality'] == 'UNKNOWN' for row in profile['agents'])
    assert all(row['failover_observation'] == 'UNKNOWN' for row in profile['agents'])


def test_no_registration_is_not_an_agent_hf_requirement_blocker():
    observation = fixture_observation()
    observation.update(registration_status='NOT_CONFIGURED', providers=[])
    observation.pop('objective_evidence')
    profile = project_hf_operational_profile(observation)
    assert profile['registration_status'] == 'NOT_CONFIGURED'
    assert all(row['applicability'] == 'OPTIONAL' for row in profile['agents'])
