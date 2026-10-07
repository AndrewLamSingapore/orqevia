"""Synthetic read-only projection tests, not live certification evidence."""
from datetime import datetime, timezone
import json
from uuid import uuid4

import pytest

from app.agent_registry import load_agent_registry
from app.gods_eye_api import project_snapshot, semantic_projection, _readonly


def inputs():
    identity = str(uuid4())
    registry = load_agent_registry()
    return dict(runtime={'source_revision': 'a' * 40, 'image_digest': 'sha256:' + 'b' * 64},
        certification_rows=[{'agent_id': a['id'], 'level': 'L0', 'trust_state': 'UNPROVEN', 'missing': {}} for a in registry['agents']],
        jobs=[{'id': str(uuid4()), 'agent': 'a20', 'status': 'completed', 'prompt': 'PRIVATE_PROMPT', 'result': 'PRIVATE_RESULT'}],
        objectives=[{'id': identity, 'revision': 0, 'state': 'COMPLETED', 'result': {'text': 'PRIVATE_MODEL_TEXT'},
            'execution_metadata': {'task_id': identity, 'runtime': {'source_revision': 'a' * 40},
                'agent_execution': [{'selected_agent_id': 'a20', 'registry_binding': 'VERIFIED'}]}}],
        lens={identity: {'task_id': identity, 'record_id': f'objective:{identity}:r0', 'integrity': 'VALID',
            'currentness': 'CURRENT', 'verification': 'VERIFIED', 'observed': {'result_digest': {'algorithm': 'sha256', 'value': 'c' * 64}}}},
        now=datetime(2026, 10, 7, tzinfo=timezone.utc))


def test_actual_registry_not_fabricated_contiguous_ids():
    result = project_snapshot(**inputs())
    assert len(result['agents']) == 21
    assert {a['agent_id'] for a in result['agents']} == {a['id'] for a in load_agent_registry()['agents']}
    assert 'a26' in result['registry']['authoritative_ids']
    assert 'a03' not in result['registry']['authoritative_ids']


def test_whitelist_and_no_task_completion_or_chain_to_l7_uplift():
    result = project_snapshot(**inputs())
    raw = json.dumps(result)
    for secret in ('PRIVATE_PROMPT', 'PRIVATE_RESULT', 'PRIVATE_MODEL_TEXT'):
        assert secret not in raw
    assert result['certification']['l7_count'] == 0
    assert all(a['l7_status'] == 'NOT_L7' for a in result['agents'])
    assert result['results'][0]['integrity'] == 'VALID'
    assert result['results'][0]['verification'] == 'UNVERIFIED'
    assert result['runtime']['verification'] == 'UNVERIFIED'
    assert result['metrics'][0]['name'] == 'observed_task_count'
    assert 'correctness' in result['observatory']['unmeasured']


def test_foreign_evidence_binding_and_unknown_agent_do_not_become_proof():
    args = inputs()
    task = args['objectives'][0]['id']
    args['lens'][task]['task_id'] = str(uuid4())
    result = project_snapshot(**args)
    assert result['results'][0]['integrity'] == 'UNKNOWN'
    assert result['results'][0]['evidence_ref'] is None
    args['objectives'][0]['execution_metadata']['agent_execution'][0]['selected_agent_id'] = 'a99'
    result = project_snapshot(**args)
    assert not result['results'] and not result['metrics']


@pytest.mark.parametrize('field,value', [('agent_execution', None), ('agent_execution', 'secret'), ('runtime', 'secret')])
def test_malformed_metadata_never_crashes_or_exports(field, value):
    args = inputs()
    args['objectives'][0]['execution_metadata'][field] = value
    result = project_snapshot(**args)
    assert 'secret' not in json.dumps(result)


def test_semantics_receives_only_typed_domain_projection():
    result = project_snapshot(**inputs())
    projection = semantic_projection(result)
    assert set(projection) == {'source_revision', 'agents', 'results', 'metrics'}
    assert 'l7_status' not in json.dumps(projection)
    assert all('quality' not in row for row in projection['agents'])
    assert projection['results'][0]['verification'] == 'UNVERIFIED'


def test_no_registered_jobs_does_not_claim_agent_idle_or_healthy():
    args = inputs()
    args.update(jobs=[], objectives=[], lens={}, certification_rows=[])
    result = project_snapshot(**args)
    assert result['certification']['l7_count'] is None
    assert all(a['live_state'] == 'UNKNOWN' and a['quality'] == 'UNKNOWN' for a in result['agents'])
    assert result['memory']['status'] == 'UNAVAILABLE'


def test_missing_or_hostile_hf_observation_does_not_grant_live_health_or_l7():
    args = inputs()
    result = project_snapshot(**args)
    profile = result['hugging_face']
    assert profile['registration_status'] == 'UNKNOWN'
    assert profile['model_calls'] == 0 and profile['permanent_agent_count'] == 21
    assert all(row['last_dated_success'] is None for row in profile['agents'])
    args['hf_observation'] = {'schema_version': 'future', 'token': 'PRIVATE_HF_SENTINEL', 'l7_count': 21}
    result = project_snapshot(**args)
    assert result['hugging_face']['observation_status'] == 'INVALID_DOMAIN_OBSERVATION'
    assert 'PRIVATE_HF_SENTINEL' not in json.dumps(result)
    assert result['certification']['l7_count'] == 0


def test_missing_read_only_store_is_not_created(tmp_path):
    target = tmp_path / 'never-created.db'
    with pytest.raises(FileNotFoundError):
        _readonly(target)
    assert not target.exists()


def test_graph_and_projection_budget_bound_result_population():
    args = inputs()
    args['objectives'][0]['execution_metadata']['agent_execution'] = [
        {'selected_agent_id': a['id'], 'registry_binding': 'VERIFIED'} for a in load_agent_registry()['agents']]
    args['objectives'] = [dict(args['objectives'][0], id=str(uuid4())) for _ in range(100)]
    for row in args['objectives']:
        row['execution_metadata'] = {**row['execution_metadata'], 'task_id': row['id']}
    result = project_snapshot(**args)
    assert len(result['tasks']) <= 12 and len(result['results']) <= 48
