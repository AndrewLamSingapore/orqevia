"""Bounded build/independent verification loop with immutable candidate evidence."""
import hashlib
import json
from pathlib import Path
import time
import uuid
from .action_records import ActionRecord,DirectExecutor,action_ledger


def _govern_verification(result, candidate_sha256: str) -> dict:
    """Normalize verifier output and reject assertion-only success.

    A boolean supplied by a verifier is a claim, not independent evidence.  An
    accepted receipt binds the preserved candidate digest to named executed
    checks and identifies the verifier role independently from the Builder.
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
    }


def build_verify(*, root: Path, objective: str, builder, verifier, max_attempts: int=3,
                 model: str | None=None, backend: str | None=None) -> dict:
    started=time.perf_counter()
    task_id=uuid.uuid4().hex
    directory=Path(root)/task_id
    directory.mkdir(parents=True)
    feedback=None
    attempts=[]
    for attempt in range(1,max(1,min(5,max_attempts))+1):
        executor=DirectExecutor(action_ledger())
        build_started=time.perf_counter()
        candidate=executor.execute(ActionRecord(task_id,'a17','engineering.build','builder',classification='R1'),lambda:builder(objective,feedback))
        build_seconds=time.perf_counter()-build_started
        raw=candidate.encode('utf-8')
        path=directory/f'candidate-{attempt}.wat'
        with path.open('xb') as stream:stream.write(raw)
        digest=hashlib.sha256(raw).hexdigest()
        # Verifier receives a preserved candidate, never a Builder PASS claim.
        verify_started=time.perf_counter()
        raw_result=executor.execute(ActionRecord(task_id,'a18','engineering.verify','verifier',classification='R1',target=path.name),lambda:verifier(path))
        verify_seconds=time.perf_counter()-verify_started
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Candidate changed during independent verification')
        result=_govern_verification(raw_result,digest)
        record={'attempt':attempt,'builder':'a17','verifier':'a18','candidate':path.name,
                'sha256':digest,'verification':result,
                'observation':{'model':model,'backend':backend,'builder_seconds':build_seconds,
                    'verifier_seconds':verify_seconds,'repair_cycles':attempt-1,
                    'human_interventions':0,'input_tokens':None,'output_tokens':None,'cost_usd':None,
                    'handoff_accuracy':None,'context_preservation':None,'role_adherence':None,
                    'tool_selection_precision':None,'schema_payload_adherence':None,
                    'provider_retries':None,'redundant_work':None,
                    'artifact_sha256_verified':True,'final_artifact_validation':result.get('passed') is True}}
        with (directory/f'verification-{attempt}.json').open('x') as stream:json.dump(record,stream,indent=2)
        attempts.append(record)
        if result.get('passed') is True:
            outcome={'task_id':task_id,'state':'VERIFIED_CANDIDATE','attempts':attempts,
                     'seconds':time.perf_counter()-started,'routine_human_interventions':0}
            break
        feedback=result
    else:
        outcome={'task_id':task_id,'state':'VALIDATION_FAILED','attempts':attempts,
                 'seconds':time.perf_counter()-started,'routine_human_interventions':0}
    with (directory/'result.json').open('x') as stream:json.dump(outcome,stream,indent=2)
    return outcome
