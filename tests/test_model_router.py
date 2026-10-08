"""Synthetic policy/callback tests only; no credentials, models or production."""
from dataclasses import replace
from decimal import Decimal
import threading
import time

import pytest

from app.model_router import (Mode, ExecutionBudget, ModelOutput, RouterRejected,
                              build_plan, execute_plan)
from app.tier_router import Backend, Tier
from app.provider_runtime import ProviderFailure


TEXT = 'Classify public synthetic example.'
LOCALS = (Backend('fast', 'gemma3:1b', Tier.NANO, 'local'),
          Backend('deep', 'gemma3:4b', Tier.MINI, 'local'))
IDENTITIES = {'fast': 'google/gemma-3-1b-it', 'deep': 'google/gemma-3-4b-it',
              'hf': 'Qwen/fixture-different-model'}


def budget(**changes):
    return ExecutionBudget(**({'max_calls': 3, 'max_parallel': 1,
        'max_elapsed_seconds': 1, 'per_call_seconds': .5,
        'max_call_cost_usd': Decimal('.001'), 'max_total_cost_usd': Decimal('.003')} | changes))


def catalog(**changes):
    return {'id': 'hf', 'model': 'Qwen/fixture-different-model:fixture',
            'provider_kind': 'huggingface', 'location': 'cloud', 'enabled': True,
            'endpoint': 'https://router.huggingface.co/v1/chat/completions',
            'qualification_status': 'QUALIFIED', 'tier': 'MINI', 'secret_ref': 'file:HF_TOKEN',
            'input_usd_million': '1', 'output_usd_million': '1',
            'context_tokens': 4096, 'output_tokens': 64, 'max_retries': 0,
            'allowed_task_classes': ['classification']} | changes


def job(**changes):
    return {'id': 'public-synthetic-job', 'agent': 'a20', 'prompt': TEXT,
            'allow_cloud': 1, 'data_classification': 'CLOUD_PERMITTED',
            'preferred_provider': 'hf', 'estimated_cost_usd': '.001',
            'max_cost_usd': '.001', 'timeout_seconds': 20,
            'task_class': 'classification', 'max_retries': 0} | changes


def plan(mode=Mode.AUTO, **changes):
    return build_plan(mode, **({'local_backends': LOCALS, 'catalog': [catalog()],
        'minimum_tier': Tier.NANO, 'classification': 'CLOUD_PERMITTED', 'text': TEXT,
        'budget': budget(), 'underlying_model_ids': IDENTITIES, 'cloud_jobs': {'hf': job()},
        'provider_authorized': True, 'disclosure_authorized': True,
        'cost_authorized': True} | changes))


def result(call, text='synthetic answer', **changes):
    return ModelOutput(**({'provider_id': call.provider_id, 'model': call.model,
        'underlying_model_id': call.underlying_model_id, 'text': text,
        'evidence_ref': 'public-fixture-reference', 'input_tokens': 2, 'output_tokens': 1,
        'cost_usd': Decimal('.000003') if call.location == 'cloud' else None} | changes))


@pytest.mark.parametrize('mode,primary,ids', [
    (Mode.AUTO, None, ['fast']), (Mode.PRIMARY, 'hf', ['hf']),
    (Mode.CLOUD, None, ['hf']), (Mode.LOCAL, None, ['fast']),
    (Mode.VERIFY, 'fast', ['fast', 'deep']),
    (Mode.CONSENSUS, None, ['fast', 'deep', 'hf']),
    (Mode.FANOUT, None, ['fast', 'deep', 'hf'])])
def test_modes_are_plans_not_authority(mode, primary, ids):
    chosen = plan(mode, primary_id=primary)
    assert [c.provider_id for c in chosen.calls] == ids
    assert chosen.receipt()['verified'] is False
    assert chosen.receipt()['grants_execution_authority'] is False
    assert 'secret_ref' not in str(chosen.receipt()) and TEXT not in str(chosen)


@pytest.mark.parametrize('classification', ['LOCAL_ONLY', 'SENSITIVE', 'RESTRICTED'])
def test_private_class_never_cloud(classification):
    with pytest.raises(RouterRejected, match='MODEL_UNAVAILABLE'):
        plan(Mode.CLOUD, classification=classification)
    assert plan(classification=classification).calls[0].location == 'local'


@pytest.mark.parametrize('missing', ['provider_authorized', 'disclosure_authorized', 'cost_authorized'])
def test_each_cloud_authorization_is_required(missing):
    with pytest.raises(RouterRejected, match='MODEL_UNAVAILABLE'):
        plan(Mode.CLOUD, **{missing: False})


@pytest.mark.parametrize('text', ['password=PRIVATE_SENTINEL', 'Bearer PRIVATE_SENTINEL'])
def test_cloud_metadata_alone_cannot_disclose_secrets(text):
    with pytest.raises(RouterRejected):
        plan(Mode.CLOUD, text=text, cloud_jobs={'hf': job(prompt=text)})


@pytest.mark.parametrize('change', [{'task_class': 'planning'}, {'preferred_provider': 'other'},
    {'prompt': 'mutated'}, {'estimated_cost_usd': '0'}, {'max_cost_usd': '0'},
    {'timeout_seconds': True}, {'max_retries': True}, {'max_retries': 1}, {'allow_cloud': 1.0}])
def test_current_persisted_job_admission_not_bare_qualified_flag(change):
    with pytest.raises(RouterRejected, match='MODEL_UNAVAILABLE'):
        plan(Mode.CLOUD, cloud_jobs={'hf': job(**change)})


@pytest.mark.parametrize('change', [{'qualification_status': 'UNQUALIFIED'}, {'input_usd_million': None},
    {'enabled': 'true'}, {'max_retries': True}, {'max_retries': 1}, {'token': 'PRIVATE_SENTINEL'},
    {'endpoint': 'https://unapproved.invalid'}, {'secret_ref': 'env:UNRELATED_TOKEN'},
    {'model': 'Qwen/unpinned-fixture'}])
def test_disabled_unpriced_or_secret_catalog_does_not_admit(change):
    with pytest.raises(RouterRejected, match='MODEL_UNAVAILABLE'):
        plan(Mode.CLOUD, catalog=[catalog(**change)])


def test_requirement_is_never_lowered_and_local_saturation_preserved():
    with pytest.raises(RouterRejected):
        plan(minimum_tier=Tier.FLAGSHIP)
    with pytest.raises(RouterRejected):
        plan(Mode.LOCAL, local_saturated=True)
    assert plan(local_saturated=True).calls[0].provider_id == 'hf'


@pytest.mark.parametrize('mode', [Mode.VERIFY, Mode.CONSENSUS, Mode.FANOUT])
def test_unknown_or_alias_independence_is_rejected(mode):
    for identities in ({}, {'fast': 'same-actual-model', 'deep': 'same-actual-model', 'hf': 'same-actual-model'}):
        with pytest.raises(RouterRejected, match='DISTINCT_MODELS_UNAVAILABLE'):
            plan(mode, primary_id='fast' if mode == Mode.VERIFY else None,
                 underlying_model_ids=identities)


def test_explicit_alias_selection_is_rejected_not_counted_as_models():
    aliases = LOCALS + (Backend('fast-alias', 'gemma3:1b', Tier.NANO, 'local'),)
    with pytest.raises(RouterRejected, match='DISTINCT_MODELS_UNAVAILABLE'):
        plan(Mode.FANOUT, local_backends=aliases, selected_ids=('fast', 'fast-alias'),
             underlying_model_ids=IDENTITIES | {'fast-alias': IDENTITIES['fast']})


def test_same_wire_model_cannot_gain_independence_from_wrong_metadata_labels():
    aliases = LOCALS + (Backend('fast-alias', 'gemma3:1b', Tier.NANO, 'local'),)
    with pytest.raises(RouterRejected, match='DISTINCT_MODELS_UNAVAILABLE'):
        plan(Mode.FANOUT, local_backends=aliases, selected_ids=('fast', 'fast-alias'),
             underlying_model_ids=IDENTITIES | {'fast-alias': 'wrong-distinct-metadata'})
    with pytest.raises(RouterRejected, match='DISTINCT_MODELS_UNAVAILABLE'):
        plan(Mode.FANOUT, catalog=[catalog(), catalog(id='other-serving-provider',
                 model='Qwen/fixture-different-model:other-provider')],
             selected_ids=('hf', 'other-serving-provider'),
             cloud_jobs={'hf': job(), 'other-serving-provider': job(preferred_provider='other-serving-provider')},
             underlying_model_ids=IDENTITIES | {'other-serving-provider': 'wrong-distinct-metadata'})


@pytest.mark.parametrize('change', [{'max_calls': True}, {'max_parallel': True}, {'max_calls': 0},
    {'max_parallel': 4}, {'max_elapsed_seconds': float('nan')}, {'per_call_seconds': True},
    {'max_call_cost_usd': True}, {'max_total_cost_usd': '-1'}])
def test_strict_budget_boundaries(change):
    with pytest.raises(RouterRejected):
        budget(**change)


def test_total_reserved_cost_is_bounded():
    # Two independently admitted cloud routes each reserve .001, not one shared
    # reservation silently used twice.
    second = catalog(id='second', model='Other/distinct-fixture:fixture')
    with pytest.raises(RouterRejected, match='TOTAL_BUDGET_EXCEEDED'):
        plan(Mode.FANOUT, catalog=[catalog(), second], selected_ids=('hf', 'second'),
             cloud_jobs={'hf': job(), 'second': job(preferred_provider='second')},
             underlying_model_ids=IDENTITIES | {'second': 'Other/distinct-fixture'},
             budget=budget(max_total_cost_usd=Decimal('.001')))


def test_primary_missing_cannot_be_replaced_with_consumer_login():
    with pytest.raises(RouterRejected, match='MODEL_UNAVAILABLE'):
        plan(Mode.PRIMARY, primary_id='ChatGPT-consumer-login')


def test_generic_api_uses_existing_https_secret_scope_validation_only():
    generic = catalog(provider_kind='chat_completions', endpoint='https://provider.invalid/v1/chat/completions',
                      secret_ref='env:FIXTURE_API_KEY')
    assert plan(Mode.CLOUD, catalog=[generic]).calls[0].model == generic['model']
    for change in ({'endpoint': 'http://provider.invalid'}, {'endpoint': 'https://user:secret@provider.invalid'},
                   {'endpoint': 'https://provider.invalid?token=private'}, {'secret_ref': 'env:HF_TOKEN'}):
        with pytest.raises(RouterRejected):
            plan(Mode.CLOUD, catalog=[generic | change])


def test_one_shot_outputs_are_separate_not_consensus_truth():
    calls = []
    def invoke(call, text, deadline, cancellation):
        calls.append(call.provider_id)
        assert text == TEXT and deadline > time.monotonic() and not cancellation.is_set()
        return result(call, text='same\r\n' if call.provider_id == 'fast' else 'same\n')
    observed = execute_plan(plan(Mode.CONSENSUS), text=TEXT, authorize=lambda _: True, invoke=invoke)
    assert len(calls) == 3 and len(set(calls)) == 3
    assert len(observed.outputs) == 3
    assert observed.receipt['normalized_outputs_equal'] is True
    assert observed.receipt['verified'] is False and observed.receipt['retries'] == 0
    assert 'same' not in str(observed.receipt) and 'public-fixture-reference' not in str(observed.receipt)


def test_failing_provider_does_not_stop_siblings_or_leak_errors():
    def invoke(call, *_):
        if call.provider_id == 'deep':
            raise RouterRejected('PRIVATE_SENTINEL_CALLBACK_TEXT')
        return result(call)
    observed = execute_plan(plan(Mode.FANOUT), text=TEXT, authorize=lambda _: True, invoke=invoke)
    assert observed.receipt['completed'] == 2
    assert observed.receipt['calls'][1]['error'] == 'CALLBACK_FAILURE'
    assert 'PRIVATE_SENTINEL' not in str(observed.receipt)


@pytest.mark.parametrize('pre_execution', [False, None, 'true', 1])
def test_ambiguous_or_malformed_provider_completion_retains_uncertainty(pre_execution):
    def invoke(*_):
        raise ProviderFailure('CAPACITY', pre_execution=pre_execution)
    observed = execute_plan(plan(Mode.CLOUD), text=TEXT, authorize=lambda _: True, invoke=invoke)
    assert observed.receipt['uncertain_work'] is True
    assert observed.receipt['calls'][0]['status'] == 'UNCERTAIN'
    assert observed.receipt['calls'][0]['reservation_release_proved'] is False


def test_known_literal_provider_rejection_does_not_replay_or_claim_release():
    calls = []
    def invoke(*_):
        calls.append(1)
        raise ProviderFailure('RATE_LIMIT', pre_execution=True)
    observed = execute_plan(plan(Mode.CLOUD), text=TEXT, authorize=lambda _: True, invoke=invoke)
    assert calls == [1] and observed.receipt['uncertain_work'] is False
    assert observed.receipt['calls'][0]['status'] == 'FAILED'
    assert observed.receipt['calls'][0]['provider_admission_rejected'] is True
    assert observed.receipt['calls'][0]['reservation_release_proved'] is False


def test_unknown_provider_error_is_sanitized_and_never_clean_rejection():
    def invoke(*_):
        raise ProviderFailure('PRIVATE_SENTINEL_ERROR', pre_execution=True)
    observed = execute_plan(plan(Mode.CLOUD), text=TEXT, authorize=lambda _: True, invoke=invoke)
    assert observed.receipt['uncertain_work'] is True
    assert observed.receipt['calls'][0]['error'] == 'UNKNOWN_PROVIDER_FAILURE'
    assert 'PRIVATE_SENTINEL' not in str(observed.receipt)


@pytest.mark.parametrize('authorization', [False, 1, 'true', None])
def test_literal_fresh_authorization_before_every_callback(authorization):
    calls = []
    observed = execute_plan(plan(), text=TEXT, authorize=lambda _: authorization,
        invoke=lambda *args: calls.append(args))
    assert not calls and observed.receipt['completed'] == 0


def test_mutable_catalog_cannot_hot_swap_after_authorization():
    chosen = plan(Mode.CLOUD)
    calls = []
    def authorize(call):
        call.entry['model'] = 'Qwen/another-model:fixture'
        return True
    observed = execute_plan(chosen, text=TEXT, authorize=authorize, invoke=lambda *args: calls.append(args))
    assert not calls and observed.receipt['calls'][0]['error'] == 'PLANNED_BINDING_CHANGED'


@pytest.mark.parametrize('changes,error', [({'model': 'wrong'}, 'RESULT_IDENTITY_MISMATCH'),
    ({'underlying_model_id': None}, 'RESULT_IDENTITY_MISMATCH'),
    ({'output_tokens': True}, 'RESULT_ACCOUNTING_INVALID'),
    ({'cost_usd': Decimal('.000004')}, 'RESULT_ACCOUNTING_INVALID'),
    ({'output_tokens': 65}, 'RESULT_ACCOUNTING_EXCEEDED'),
    ({'cost_usd': Decimal('.1')}, 'RESULT_ACCOUNTING_EXCEEDED')])
def test_wrong_identity_usage_or_cost_preserves_nonaccepted_hash(changes, error):
    observed = execute_plan(plan(Mode.CLOUD), text=TEXT, authorize=lambda _: True,
        invoke=lambda call, *_: result(call, **changes))
    assert observed.receipt['completed'] == 0
    assert observed.receipt['calls'][0]['error'] == error
    assert len(observed.receipt['calls'][0]['observed_result_sha256']) == 64
    assert observed.receipt['calls'][0]['observation_accepted'] is False


def test_unknown_cost_remains_unknown_not_free():
    observed = execute_plan(plan(Mode.CLOUD), text=TEXT, authorize=lambda _: True,
        invoke=lambda call, *_: result(call, cost_usd=None, input_tokens=None, output_tokens=None))
    assert observed.receipt['calls'][0]['cost_usd'] is None
    assert observed.receipt['calls'][0]['accounting'] == 'UNKNOWN'
    assert observed.receipt['verified'] is False


def test_local_positive_fee_requires_real_price_and_reservation_not_callback_claim():
    chosen = plan(Mode.FANOUT, catalog=[], selected_ids=('fast', 'deep'),
                  budget=budget(max_total_cost_usd=Decimal('.001')))
    observed = execute_plan(chosen, text=TEXT, authorize=lambda _: True,
                            invoke=lambda call, *_: result(call, cost_usd=Decimal('.001')))
    assert observed.receipt['completed'] == 0
    assert all(c['error'] == 'RESULT_ACCOUNTING_INVALID' for c in observed.receipt['calls'])
    assert all(c['observation_accepted'] is False for c in observed.receipt['calls'])


def test_known_input_over_context_rejects_even_if_output_and_cost_unknown():
    observed = execute_plan(plan(Mode.CLOUD), text=TEXT, authorize=lambda _: True,
        invoke=lambda call, *_: result(call, input_tokens=4097, output_tokens=None, cost_usd=None))
    assert observed.receipt['completed'] == 0
    assert observed.receipt['calls'][0]['error'] == 'RESULT_ACCOUNTING_EXCEEDED'


def test_deadline_after_authorization_prevents_late_dispatch():
    chosen = plan(budget=budget(max_elapsed_seconds=.015, per_call_seconds=.015))
    calls = []
    def authorize(_):
        time.sleep(.03)
        return True
    observed = execute_plan(chosen, text=TEXT, authorize=authorize, invoke=lambda *args: calls.append(args))
    time.sleep(.02)  # Let only the synthetic delayed authorization finish.
    assert not calls
    assert observed.receipt['uncertain_work'] is True


def test_noncooperative_callback_is_uncertain_never_replayed():
    release = threading.Event()
    started = threading.Event()
    calls = []
    def invoke(call, *_):
        calls.append(call.provider_id)
        started.set()
        release.wait(.2)
        return result(call)
    try:
        observed = execute_plan(plan(budget=budget(max_elapsed_seconds=.02, per_call_seconds=.01)),
            text=TEXT, authorize=lambda _: True, invoke=invoke)
        assert started.is_set() and calls == ['fast']
        assert observed.receipt['uncertain_work'] is True and observed.receipt['completed'] == 0
        assert observed.receipt['calls'][0]['reservation_release_proved'] is False
    finally:
        release.set()


def test_parallelism_never_exceeds_policy():
    active = peak = 0
    lock = threading.Lock()
    def invoke(call, *_):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.005)
        with lock:
            active -= 1
        return result(call)
    observed = execute_plan(plan(Mode.FANOUT, budget=budget(max_parallel=2)), text=TEXT,
                            authorize=lambda _: True, invoke=invoke)
    assert observed.receipt['completed'] == 3 and peak == 2


def test_cancelled_or_mutated_request_cannot_start_work():
    calls = []
    with pytest.raises(RouterRejected):
        execute_plan(plan(), text='changed', authorize=lambda _: True, invoke=lambda *args: calls.append(args))
    observed = execute_plan(plan(), text=TEXT, authorize=lambda _: True,
                            invoke=lambda *args: calls.append(args), cancelled=lambda: True)
    assert not calls and observed.receipt['calls'][0]['status'] == 'NOT_STARTED'
    fake = replace(plan(), calls=tuple(plan().calls) * 4)
    with pytest.raises(RouterRejected):
        execute_plan(fake, text=TEXT, authorize=lambda _: True, invoke=lambda *args: calls.append(args))
    chosen = plan()
    fake_call = replace(chosen.calls[0], model='another-unadmitted-local-model')
    observed = execute_plan(replace(chosen, calls=(fake_call,)), text=TEXT, authorize=lambda _: True,
                            invoke=lambda *args: calls.append(args))
    assert not calls and observed.receipt['calls'][0]['error'] == 'PLANNED_BINDING_CHANGED'
