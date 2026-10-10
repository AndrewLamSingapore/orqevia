"""Bounded existing-loopback custody; no live challenge or L7 assertion."""
from dataclasses import dataclass
from datetime import datetime,timezone
import json
import time
import uuid
import re

from app import agent_cert_fresh_input as fresh
from app.agent_cert_role_review import canonical_case_spec
from .agent_cert_operator_io import AgentCertOperatorIO
from .collect_agent_cert_event import collect_event_case

REVIEW_SCHEMA = fresh.REVIEW_SCHEMA


@dataclass(frozen=True)
class FreshInputCollection:
    summary: dict
    execution_bytes: bytes
    review_bytes: bytes
    original_replies: tuple


def collect_fresh_input(case,*,owner_token,expected_source_revision,expected_runtime_image,
    expected_registry_sha256,reviewer_code_revision,review_run_id,supply_after_initialization,
    connection_factory,timer_factory,monotonic=time.monotonic,nonce_factory=lambda:str(uuid.uuid4())):
    """One initializer then exactly four original tasks, no retry/fallback.

    The callback is invoked only after actual initialization has completed.
    It supplies labelled SOURCE_TEST_CUSTODIAN input, never a prior answer.
    """
    fresh.require(case in fresh.CASES and callable(supply_after_initialization),'EXECUTION_INPUT_CUSTODIAN_REQUIRED')
    spec = canonical_case_spec('a19','responsibility.a19','baseline:initialization')
    operator = AgentCertOperatorIO(owner_token=owner_token,spec=spec,
        expected_source_revision=expected_source_revision,expected_runtime_image=expected_runtime_image,
        connection_factory=connection_factory,timer_factory=timer_factory,monotonic=monotonic,
        total_timeout_seconds=30,request_timeout_seconds=2)
    execution = {};review = {};state = 'INCOMPLETE';reason = None
    try:
        initialized = collect_event_case(spec,io=operator.io(),read_subject_actions=operator.read_subject_actions,
            expected_source_revision=expected_source_revision,expected_runtime_image=expected_runtime_image,
            expected_registry_sha256=expected_registry_sha256,reviewer_code_revision=reviewer_code_revision,
            review_run_id=review_run_id+'-initialization',timeout_seconds=30,nonce_factory=nonce_factory)
        fresh.require(initialized.summary['state'] == 'UNSIGNED_EVENT_EVIDENCE','EXECUTION_INPUT_ORIGINAL_INITIALIZATION_FAILED')
        initialization = json.loads(initialized.execution_bytes)
        operator.activate_execution_input(case,initialization)
        fresh.require(operator._execution_input['registry'] == expected_registry_sha256,
            'EXECUTION_INPUT_EXPECTED_REGISTRY_MISMATCH')
        supplied = supply_after_initialization(json.loads(fresh.canonical(initialization)))
        fresh.payload(case,supplied)
        execution = dict(case_spec=fresh.canonical_case(case),runtime=initialization['runtime'],initialization=initialization)
        for stage in fresh.STAGES:
            proof = operator.execution_input_stage(supplied_payload=supplied if stage == 'custodian' else None,
                nonce=nonce_factory())
            execution[stage] = proof
        primary = fresh.canonical(execution)
        join = fresh.validate_execution(execution,source_revision=expected_source_revision,
            runtime_image_id=expected_runtime_image,registry_sha256=expected_registry_sha256,now=datetime.now(timezone.utc))
        review = dict(schema_version=REVIEW_SCHEMA,execution_sha256=fresh.sha(primary),
            case=case,registry_sha256=expected_registry_sha256,reviewer_code_revision=reviewer_code_revision,
            review_run_id=review_run_id,oracle_id=fresh.ORACLE_ID,oracle_pass=True,
            subject_agent_id='a19',subject_capability_id='responsibility.a19',reviewer_agent_id='a26',
            reviewer_capability_id='responsibility.a26',subject_domain_join=join,
            reviewer_execution=execution['comparison'],model_calls=0,certification='UNVERIFIED',
            service_confirmation='NOT_PERFORMED',live_unfamiliarity='NOT_PROVEN')
        state = 'UNSIGNED_EVENT_EVIDENCE'
    except Exception as error:
        # Preserve original responses and partial original chain; never the
        # credential, headers, arbitrary exception text or a replay suggestion.
        message = str(error)
        reason = message if re.fullmatch('[A-Z][A-Z0-9_]{0,95}',message) else type(error).__name__
    return FreshInputCollection(dict(state=state,case=case,reason=reason,model_calls=0,
        signed=False,live_unfamiliarity='NOT_PROVEN',service_confirmation='NOT_PERFORMED'),
        fresh.canonical(execution),fresh.canonical(review),operator.original_replies())
