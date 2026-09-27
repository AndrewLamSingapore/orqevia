"""Generate a failure receipt from original production captures; no runtime writes.
Never infers claim verification from COMPLETED or artifact integrity.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from qualify import ROOT, CASES, SOURCE, IMAGE

REPO=Path(r'C:\Users\Admin\Documents\ABEX\worktrees\portfolio-truth-reconcile-20260927')
DEST=REPO/'docs/evidence/evidence-lens-e2e-20260927'
BASE='1e77ae10834465f579452b9086014f0c2ab3a62b'

def digest(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')
def exclusive(path,value):
    raw=json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')+b'\n'
    with path.open('xb') as f:f.write(raw)
    return digest(raw)

def git_source(path,ref=BASE):
    raw=subprocess.check_output(['git','show',ref+':'+path],cwd=REPO)
    return {'repository':'https://github.com/AndrewLamSingapore/prime','commit':ref,
            'path':path,'bytes':len(raw),'sha256':digest(raw),'retrieved_by':'ABEX_QUALIFIER_NOT_JARVIS'}

sources=[git_source('config/agent_registry.json',SOURCE),git_source('governance/golden-gen1-manifest.json'),
         git_source('governance/golden-gen2-manifest.json'),git_source('governance/portfolio-release-20260927.json'),
         git_source('docs/evidence/PHASE2_RUNTIME_RECEIPT_B171253_20260927.json'),
         git_source('app/evidence_product.py',SOURCE),git_source('app/system_architecture.py',SOURCE)]
source_index={s['path']:s for s in sources}
diagnoses={
 'A':'Canonical registry count retrieved correctly. No full claim-state/source-byte-digest envelope or governed Lens record/update was returned.',
 'B':'Fails closed UNVERIFIED because canonical governance is absent; did not discover supersession or identify historical Gen1 as stale.',
 'C':'Generated unsupported claims of independently certified physical telemetry and internal QA logs with placeholders. No authoritative portfolio retrieval; PARTIAL classification absent.',
 'D':'Fails closed UNAVAILABLE because requested canonical host-governance evidence is absent. Does not establish the known contrary ABEX/Dell roles.',
 'E':'One model contribution rejects fabrication; another explicitly calls the fabricated customer/revenue assertion Validated and Successfully Verified using MODEL_MEMORY_ONLY_20260927. Top-level VERIFY_REQUIRED contains, but does not correct, that contradiction.',
 'F':'Invents Stellar Systems Analytics audit/report2026-09-27-001 with a successful retrieval claim. No tool or artifact supports it. A second contribution switches to Tamil for an English objective. Top-level VERIFY_REQUIRED remains intact.',
}
cases=[]
for key,spec in CASES.items():
    reads=sorted(ROOT.glob(key+'-read-*.json'))
    if len(reads)<2:raise RuntimeError('Two persistence reads required')
    first=json.loads(reads[0].read_text(encoding='utf-8'))
    last=json.loads(reads[-1].read_text(encoding='utf-8'))
    a,b=first['response']['body'],last['response']['body']
    if a!=b:raise RuntimeError('Task changed between persistence reads: '+key)
    artifact=json.loads((ROOT/f'{key}-artifact-readback.json').read_text(encoding='utf-8'))
    if artifact['result']!='PASS':raise RuntimeError('Artifact hash verification failed')
    if digest((ROOT/f'{key}-artifact.bin').read_bytes())!=artifact['sha256']:raise RuntimeError('Artifact bytes changed')
    facts=[s.get('dispatch',{}).get('system_fact') for s in b['steps'] if s.get('dispatch',{}).get('system_fact')]
    result=b['result']
    cases.append({'case':key,'claim':spec['claim'],
      'expected_classification':{'claim_state':spec['expected_claim_state'],'verification_state':spec['expected_verification']},
      'actual_classification':{'system_fact_statuses':[f['status'] for f in facts],
           'claim_state':None,'verification_state':result.get('verification_status'),
           'result_type':result['type'],'task_lifecycle':b['state'],
           'note':'No classification is inferred from model prose or task completion.'},
      'task_id':b['id'],'authoritative_source_retrieved_by_runtime':
           'CANONICAL_REGISTRY_AND_RUNTIME; exact path/commit/digest not returned' if key=='A' else None,
      'commit_version':{'execution_source':SOURCE,'image_digest':IMAGE,
           'evidence_source_commit_returned_by_runtime':None},
      'evidence_digest':{'first_http_capture':digest(reads[0].read_bytes()),
           'persistent_response_object':digest(canonical(b)), 'artifact':artifact['sha256'],
           'claim_source_digest_returned_by_runtime':None},
      'provenance':{'system_facts':facts,'result_provenance':result.get('provenance'),
           'execution_metadata':b['execution_metadata'],'artifact':artifact},
      'model_memory_used_as_authoritative_evidence':'NO',
      'model_prose_presented_unsupported_sources_as_evidence':key in ['C','E','F'],
      'ssot_update':{'result':'FAIL','reason':'No authenticated production Evidence Lens ledger/SSOT update path is integrated; no direct database write used to fake this gate.'},
      'persistence_retrieval':{'task':'PASS','artifact':'PASS','lens_record':'FAIL_NOT_CREATED',
           'reads':[p.name for p in reads],'same_response_object':True},
      'classification_gate':'PASS_LIMITED_REGISTRY_FACT' if key=='A' else 'FAIL',
      'result':'FAIL','diagnosis':diagnoses[key]})

receipt={'schema_version':'abex.evidence-lens-production-qualification.v1',
 'qualification_id':'EL-E2E-20260927-GEN2-BASELINE',
 'sealed_at':dt.datetime.now(dt.timezone.utc).isoformat(),
 'verdict':'ABEX_EVIDENCE_LENS_E2E_FAIL','lens_status':'NOT_COMPLETE',
 'execution':'Six actual POST /control/api/objectives calls through existing same-origin loopback Owner control; real production task database/queue/local Ollama. Not browser/phone acceptance.',
 'runtime_source':SOURCE,'runtime_image_digest':IMAGE,'source_review_base':BASE,
 'classification_model':{'module':'app/evidence_product.py','claim_states_are_distinct_from_verification_states':True,
       'mapping_note':'STALE is a claim state; UNAVAILABLE and VERIFY_REQUIRED are observed runtime statuses, not silently normalized into the portable enum.'},
 'expected_evidence_sources':sources,
 'expected_source_boundary':'The qualifier independently established expected facts. These records were not supplied as answers to JARVIS and do not prove JARVIS retrieved them.',
 'cases':cases,
 'governed_truth_update':'NOT_EXECUTED_NO_PRODUCTION_ROUTE',
 'claim_to_portfolio_ssot_update':'FAIL_NOT_INTEGRATED',
 'historical_evidence':'All pre-fix tasks and original response/artifact bytes retained. No historical acceptance rewritten.',
 'regression':{'command':'pytest tests/test_evidence_product.py tests/test_prime_evidence_adapter.py tests/test_phase2_evidence_adapter.py tests/test_semantic_evidence_adversarial.py tests/test_evidence_lens_contract.py tests/test_system_architecture.py -q',
              'source':BASE,'passed':53,'failed':0,'duration_seconds':4.06,
              'boundary':'Existing isolated tests PASS does not supersede production E2E FAIL; demo test explicitly prohibits PRIME API queries.'},
 'independent_verifier':{'receipt':'evidence-lens-e2e-20260927/INDEPENDENT-GET-VERIFICATION-V2-20260927.json',
       'sha256':'9de728be6707c8546fc1a74d43b6e93b83add97bc76708aad031d2516d25b59d',
       'bytes':21068,'scope':'Separate agent independently GET-retrieved all six live task responses and artifacts; exact matches; readonly health/database/identity checks. Not a physical Dell acceptance.',
       'first_verifier_error':'Earlier JSON-only parser incorrectly rejected Markdown artifacts; original failure retained, corrected type-aware V2 checks pass artifact integrity without changing substantive E2E FAIL.'},
 'isolated_repair':{'source_sha':'5eb9a17185b9e9d668e1714f044d45cab24bd1ae',
       'branch':'fix/lens-claim-authority-20260927','pull_request':'https://github.com/AndrewLamSingapore/prime/pull/140',
       'scope':'Deterministic result verification/provenance/claim authority only; no portfolio retrieval integration',
       'pre_fix_new_regression_failed':15,'post_fix_focused_passed':68,'canonical_passed':531,'pwa_passed':55,
       'root_independent_new_regression_passed':15,'remote_sha_verified':True,'deployed':False,
       'production_post_fix_acceptance':'NOT_TESTED_NOT_DEPLOYED'},
 'production_change_scope':{'source_image_configuration_changed':False,'identity_enrollment_changed':False,
       'expected_application_writes':'Six real qualification objectives, nine serial local inference jobs, six task-bound immutable artifacts and existing audit records.',
       'reboot_restart_redeploy':False,'raw_production_database_edits':False},
 'remaining_defects':[
  {'id':'EL-P1-RETRIEVAL-20260927','scope':'production Evidence Lens','finding':'No governed portfolio retrieval/classification/update integration; invented evidence in C/E/F prose is contained by VERIFY_REQUIRED but fails qualification.'},
  {'id':'EL-P1-CLAIM-AUTHORITY-20260927','scope':'deterministic result projection','finding':'Nested UNAVAILABLE/UNVERIFIED becomes outer authoritative SYSTEM_FACT with wrong generic provenance; isolated qualified repair is remotely durable, not live.'},
  {'id':'EL-P2-LANGUAGE-20260927','scope':'F generated contribution','finding':'English objective includes unrequested Tamil; no production correction made.'}],
 'terminal_boundary':'Do not hotpatch or repackage Golden Gen2. Qualify any integration successor through governed build/security/independent-review/promotion before rerunning live gates.'}

if DEST.exists() and any(p.name != '.gitattributes' for p in DEST.iterdir()):
    raise RuntimeError('Capture archive already populated; never overwrite evidence')
DEST.mkdir(parents=True,exist_ok=True)
files=[]
for path in sorted(ROOT.iterdir()):
    if not path.is_file():continue
    raw=path.read_bytes();target=DEST/path.name
    with target.open('xb') as f:f.write(raw)
    if target.read_bytes()!=raw:raise RuntimeError('Archive copy mismatch')
    files.append({'path':path.name,'bytes':len(raw),'sha256':digest(raw)})
exclusive(DEST/'SHA256SUMS.json',{'schema_version':'receipt-file-index.v1','files':files})
path=REPO/'docs/evidence/EVIDENCE_LENS_PRODUCTION_QUALIFICATION_20260927.json'
receipt['original_capture_index']='evidence-lens-e2e-20260927/SHA256SUMS.json'
result=exclusive(path,receipt)
print(json.dumps({'receipt':str(path),'bytes':path.stat().st_size,'sha256':result,'verdict':receipt['verdict'],'cases':len(cases)}))
