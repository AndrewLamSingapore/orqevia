"""Distinct owned contract reports; synthetic tests are not live certification."""
import copy
from datetime import datetime, timezone
import json

import pytest

from app import agent_cert_initialization as init, agent_registry
from app.agent_cert_role_review import canonical_case_spec

PAIRS = tuple((item['id'], cap) for item in agent_registry.load_agent_registry()['agents']
              for cap in item['capability_requirements'])
NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
TASK = '11111111-1111-4111-8111-111111111111'
SOURCE = 'a' * 40
IMAGE = 'sha256:' + 'b' * 64


def arguments(agent, cap):
    return dict(task_id=TASK, agent_id=agent, capability_id=cap, runtime={
        'host_id': 'ABEX', 'source_revision': SOURCE, 'version': 'test', 'image_digest': IMAGE},
        source_revision=SOURCE, runtime_image_id=IMAGE,
        registry_sha256=init.sha(agent_registry.REGISTRY_PATH.read_bytes()), now=NOW)


@pytest.mark.parametrize('agent,cap', PAIRS)
def test_each_actual_owned_capability_has_distinct_source_report_and_case(agent, cap):
    args = arguments(agent, cap)
    report = init.build_initialization_report(**args)
    actual = agent_registry.agent_record(agent)
    assert report['agent_id'] == actual['id'] == agent
    assert report['capability_id'] == cap
    assert report['owned_domains']['definition']['authority'] == actual['authority']
    assert report['owned_domains']['definition']['can_delegate'] is actual['can_delegate']
    selected = next(r for r in actual['responsibilities'] if r['id'] == cap)
    if (agent, cap) != ('a19', 'responsibility.a19'):
        assert report['owned_domains']['selected_capability'] == selected
        assert report['owned_domains']['selected_capability_sha256'] == init.sha(init.canonical(selected))
    spec = canonical_case_spec(agent, cap, init.CASE)
    assert spec['agent_id'] == agent and spec['capability_id'] == cap
    assert spec['request']['capability'] == cap
    assert spec['request']['deterministic_operation'] == 'certification_initialization'
    assert spec['request']['objective'] == init.initialization_objective(agent, cap)
    assert spec['request']['data_classification'] == 'LOCAL_ONLY'
    assert spec['request']['max_cost_usd'] == 0
    result = init.validate_initialization_report(init.canonical(report), **args)
    assert result['certification'] == 'UNVERIFIED'
    assert report['execution']['model_calls'] == 0
    assert report['evidence_gaps']['health'] == 'NOT_MEASURED'


def test_exact_population_and_legacy_a19_default_contract_unchanged():
    assert len(PAIRS) == 29 and len({p[0] for p in PAIRS}) == 21
    args = arguments('a19', 'responsibility.a19')
    explicit = init.build_initialization_report(**args)
    default = init.build_initialization_report(**{k: v for k, v in args.items()
                                                if k not in ('agent_id', 'capability_id')})
    assert init.canonical(explicit) == init.canonical(default)
    assert set(default['owned_domains']) == {'registry', 'definition', 'definition_sha256', 'request_contract'}
    assert default['oracle_id'] == init.ORACLE_ID
    assert init.initialization_objective('a19', 'responsibility.a19') == init.OBJECTIVE


@pytest.mark.parametrize('agent,cap', [('a03', 'responsibility.a03'), ('A19', 'responsibility.a19'),
    ('a19', 'responsibility.a26'), ('a26', 'responsibility.a27'), ('a18', 'responsibility.a25'),
    ('a02', 'responsibility.a08'), ('orchestrator', 'responsibility.a19')])
def test_alias_unowned_or_invented_pair_never_gets_contract(agent, cap):
    with pytest.raises((ValueError, agent_registry.RegistryError)):
        init.build_initialization_report(**arguments(agent, cap))
    with pytest.raises(ValueError):
        canonical_case_spec(agent, cap, init.CASE)


@pytest.mark.parametrize('change', [
    lambda r: r.update(agent_id='a19'), lambda r: r.update(capability_id='responsibility.a02'),
    lambda r: r['owned_domains']['selected_capability'].update(id='responsibility.a02'),
    lambda r: r['owned_domains']['selected_capability'].update(output='All actions approved'),
    lambda r: r['owned_domains']['definition'].update(authority='owner'),
    lambda r: r['owned_domains']['definition'].update(can_delegate=False),
    lambda r: r.update(oracle_id='caller.PASS'), lambda r: r.update(certification='L7'),
])
def test_same_hash_reencoded_mutated_report_is_not_owned_proof(change):
    args = arguments('a26', 'responsibility.a25')
    report = init.build_initialization_report(**args)
    change(report)
    with pytest.raises(init.InitializationError):
        init.validate_initialization_report(init.canonical(report), **args)


def test_multi_capability_reports_and_canonical_cases_cannot_collapse():
    for actor in {a for a, _ in PAIRS}:
        caps = [c for a, c in PAIRS if a == actor]
        if len(caps) == 2:
            reports = [init.canonical(init.build_initialization_report(**arguments(actor, c))) for c in caps]
            specs = [init.canonical(canonical_case_spec(actor, c, init.CASE)) for c in caps]
            assert len(set(reports)) == len(set(specs)) == 2
