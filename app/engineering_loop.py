"""Bounded build/verifier-call loop with immutable local candidate evidence."""
from pathlib import Path
import time
import uuid
from .action_records import ActionRecord,DirectExecutor,action_ledger
from .engineering_continuity import Journal, ContinuityError, digest, encode, fingerprint


def _govern_verification(result, candidate_sha256: str) -> dict:
    """Normalize verifier output and reject assertion-only success.

    A boolean supplied by a verifier is a claim, not independent evidence.  An
    structurally valid receipt binds the preserved candidate digest to claims
    of executed checks and a verifier role distinct from the Builder. This validates
    receipt shape only: it does not authenticate the verifier process or resolve
    evidence references, and cannot independently accept production.
    """
    violations=[]
    if not isinstance(result,dict):
        result={};violations.append('malformed_verifier_result')
    if result.get('verifier')!='a18':violations.append('independent_verifier_identity_missing')
    if result.get('independent') is not True:violations.append('independence_not_attested')
    if result.get('candidate_sha256')!=candidate_sha256:violations.append('candidate_digest_mismatch')
    checks=result.get('checks')
    if not isinstance(checks,list) or not checks:
        violations.append('executed_checks_missing');checks=[]
    else:
        for index,check in enumerate(checks):
            if not isinstance(check,dict):
                violations.append(f'check_{index}_malformed');continue
            if not isinstance(check.get('name'),str) or not check['name'].strip():
                violations.append(f'check_{index}_name_missing')
            if check.get('status')!='PASS':violations.append(f'check_{index}_not_passed')
            if not isinstance(check.get('evidence_ref'),str) or not check['evidence_ref'].strip():
                violations.append(f'check_{index}_evidence_missing')
    claimed_accept=result.get('passed') is True or result.get('verdict')=='ACCEPT'
    accepted=claimed_accept and not violations and result.get('passed') is True and result.get('verdict')=='ACCEPT'
    if not claimed_accept and not violations:violations.append('verifier_rejected_candidate')
    return {
        'passed':accepted,
        'verdict':'ACCEPT' if accepted else 'REJECT',
        'verifier':'a18',
        'independent':bool(result.get('independent') is True),
        'candidate_sha256':candidate_sha256,
        'checks':checks,
        'violations':violations,
        'independent_verification':False,
        'verification_scope':'CALLABLE_RECEIPT_VALIDATION_ONLY',
    }


def build_verify(*, root: Path, objective: str, builder, verifier, max_attempts: int=3,
                 model: str | None=None, backend: str | None=None,
                 execution_fingerprint: str | None=None) -> dict:
    """Run in a caller-owned isolated root, retaining bounded resumable evidence.

    The optional fingerprint must bind the trusted caller's callback/config
    versions, not a model claim. It is mandatory for later resumption. No
    scheduler or production permission is created by this helper.
    """
    fingerprint(execution_fingerprint)
    if not isinstance(objective,str):raise ValueError('objective must be text')
    if type(max_attempts) is not int:raise ValueError('max_attempts must be an integer')
    if any(value is not None and not isinstance(value,str) for value in (model,backend)):
        raise ValueError('model and backend must be text or None')
    task_id=uuid.uuid4().hex
    journal=Journal(root,task_id,create=True)
    with journal.locked():
        journal.append({'phase':'READY_BUILD','objective':objective,
            'objective_sha256':digest(objective.encode('utf-8')),
            'execution_fingerprint':execution_fingerprint,
            'max_attempts':max(1,min(5,max_attempts)),'model':model,'backend':backend})
        return _continue(journal,builder,verifier)


def resume_build_verify(*, root: Path, task_id: str, execution_fingerprint: str,
                        builder, verifier) -> dict:
    """Resume only proven callback boundaries; never replay an ambiguous effect.

    A surviving lock requires explicit reconciliation outside this helper. A
    disappeared process is not itself evidence that its callback had no effect.
    """
    journal=Journal(root,task_id)
    with journal.locked():
        journal.load(execution_fingerprint)
        return _continue(journal,builder,verifier)


def _continue(journal,builder,verifier):
    initial=journal.events[0]
    task_id=journal.task_id
    attempts=[journal.json(event['receipt']) for event in journal.events if event['phase']=='ATTEMPT_RECORDED']
    phase=journal.events[-1]['phase']
    outcome=journal.json('result.json') if phase=='TERMINAL' else None
    if isinstance(outcome,dict) and outcome.get('state')=='VERIFIED_CANDIDATE':
        # Preserve historical bytes. A formerly overclaimed result cannot be
        # silently relabelled, accepted, or replayed by the current helper.
        raise ContinuityError('LEGACY_VERIFIED_STATE_RECONCILIATION_REQUIRED')
    # These records contain caller-supplied verification claims, not authenticated
    # independent execution receipts or production acceptance. Revalidate shape.
    for record in attempts:
        result=record.get('verification')
        if (not isinstance(result,dict) or type(result.get('passed')) is not bool
                or (result['passed'] and _govern_verification(result,record['sha256'])!=result)
                or (not result['passed'] and (result.get('verdict')!='REJECT' or not result.get('violations')))):
            raise ContinuityError('VERIFICATION_RECEIPT_INVALID')
    if phase in {'BUILD_STARTED','VERIFY_STARTED'}:
        raise ContinuityError('INTERRUPTED_CALLBACK_RECONCILIATION_REQUIRED:'+phase)
    if phase=='TERMINAL':
        expected='RECEIPT_STRUCTURALLY_VALID' if attempts[-1]['verification']['passed'] else 'VALIDATION_FAILED'
        if (not isinstance(outcome,dict) or outcome.get('task_id')!=task_id or outcome.get('attempts')!=attempts or outcome.get('state')!=expected
                or outcome.get('production_acceptance') is not False or outcome.get('independent_verification') is not False):
            raise ContinuityError('TERMINAL_RESULT_BINDING_INVALID')
        return outcome
    feedback=attempts[-1]['verification'] if attempts else None
    while not attempts or (not attempts[-1]['verification']['passed'] and len(attempts)<initial['max_attempts']):
        attempt=len(attempts)+1
        executor=DirectExecutor(action_ledger())
        if journal.events[-1]['phase']!='CANDIDATE_PRESERVED':
            journal.append({'phase':'BUILD_STARTED','attempt':attempt})
            build_started=time.perf_counter()
            candidate=executor.execute(ActionRecord(task_id,'a17','engineering.build','builder',classification='R1'),lambda:builder(initial['objective'],feedback))
            build_seconds=time.perf_counter()-build_started
            raw=candidate.encode('utf-8')
            candidate_digest=journal.write(f'candidate-{attempt}.wat',raw)
            journal.append({'phase':'CANDIDATE_PRESERVED','attempt':attempt,'candidate':f'candidate-{attempt}.wat',
                'sha256':candidate_digest,'build_seconds':build_seconds})
        preserved=journal.events[-1]
        path=journal.path(preserved['candidate'])
        candidate_digest=preserved['sha256']
        build_seconds=preserved['build_seconds']
        # Verifier receives a preserved candidate, never a Builder PASS claim.
        journal.append({'phase':'VERIFY_STARTED','attempt':attempt})
        verify_started=time.perf_counter()
        raw_result=executor.execute(ActionRecord(task_id,'a18','engineering.verify','verifier',classification='R1',target=path.name),lambda:verifier(path))
        verify_seconds=time.perf_counter()-verify_started
        if digest(journal.read(path.name))!=candidate_digest:
            raise RuntimeError('Candidate changed during independent verification')
        result=_govern_verification(raw_result,candidate_digest)
        record={'attempt':attempt,'builder':'a17','verifier':'a18','candidate':path.name,
                'sha256':candidate_digest,'verification':result,
                'observation':{'model':initial['model'],'backend':initial['backend'],'builder_seconds':build_seconds,
                    'verifier_seconds':verify_seconds,'repair_cycles':attempt-1,
                    'human_interventions':0,'input_tokens':None,'output_tokens':None,'cost_usd':None,
                    'handoff_accuracy':None,'context_preservation':None,'role_adherence':None,
                    'tool_selection_precision':None,'schema_payload_adherence':None,
                    'provider_retries':None,'redundant_work':None,
                    'artifact_sha256_verified':True,'receipt_structurally_valid':result.get('passed') is True,
                    'final_artifact_validation':None}}
        receipt=f'verification-{attempt}.json'
        receipt_digest=journal.write(receipt,encode(record))
        journal.append({'phase':'ATTEMPT_RECORDED','attempt':attempt,'receipt':receipt,'sha256':receipt_digest})
        attempts.append(record)
        feedback=result
    outcome={'task_id':task_id,'state':'RECEIPT_STRUCTURALLY_VALID' if attempts[-1]['verification']['passed'] else 'VALIDATION_FAILED',
        'attempts':attempts,'seconds':sum(record['observation']['builder_seconds']+record['observation']['verifier_seconds'] for record in attempts),
        'routine_human_interventions':0,'verification_scope':'CALLABLE_RECEIPT_VALIDATION_ONLY',
        'production_acceptance':False,'independent_verification':False}
    result_digest=journal.write('result.json',encode(outcome))
    journal.append({'phase':'TERMINAL','result':'result.json','sha256':result_digest})
    return outcome
