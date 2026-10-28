from scripts.observe_runtime_compliance import enforcement_matrix, safe_settings


def test_environment_projection_never_exports_secrets_or_unknown_values():
    assert safe_settings(['ORQEVIA_OUTPUT_QUEUE_MODE=direct','API_KEY=private',
                          'PASSWORD=private','UNKNOWN=private','malformed']) == {
        'ORQEVIA_OUTPUT_QUEUE_MODE':'direct'}


def test_direct_runtime_cannot_claim_requested_profile_is_enforced():
    report = enforcement_matrix('ULTRA_ECO', {'ORQEVIA_OUTPUT_QUEUE_MODE':'direct'}, {})
    assert not report['profile_matches']
    assert report['shared_admission'] == 'NOT_ENFORCED'
    assert report['duplicate_requests_prevented'] is None
    assert report['actual_inference_requests'] is None


def test_new_mode_and_schema_are_not_functional_acceptance():
    report = enforcement_matrix('HOME_ECO', {'ORQEVIA_OUTPUT_QUEUE_MODE':'home_eco'},
                                {'lifecycle_columns_present':True})
    assert report['profile_matches']
    assert report['shared_admission'] == 'DEPLOYED_NOT_FUNCTIONALLY_VERIFIED'
    assert report['all_21_agents_functional'] == 'NOT_ESTABLISHED_BY_REGISTRATION_OR_CONTAINER_HEALTH'


def test_database_pause_does_not_claim_full_eco_profile_or_deduplication():
    report=enforcement_matrix('ULTRA_ECO',{'ORQEVIA_OUTPUT_QUEUE_MODE':'direct'},
        {'background_admission':{'paused':1,'generation':0},'background_trigger_present':True,
         'background_starts_since_pause':0})
    assert report['background_admission']=='PAUSED_DATABASE_ENFORCEMENT_PRESENT'
    assert report['new_background_starts_since_pause']==0
    assert not report['profile_matches']
    assert report['duplicate_requests_prevented'] is None
