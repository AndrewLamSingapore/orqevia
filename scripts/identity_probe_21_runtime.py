"""Bounded public synthetic identity probes using the installed dispatch contract."""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import urllib.request

from app.agent_dispatch_api import AgentRequest, inference_prompt
from app.agent_registry import registered_agent_ids
from app.jarvis_response_contract import validate_user_facing_answer
from app.product_identity import PRODUCT_NAME
from app.tier_router import Tier

VERSION = 'orqevia.public-identity-21.v1'
OBJECTIVE = 'What is your name? Introduce yourself in one brief sentence. Reply in English.'
CAP = .005
SCOPE = 'PUBLIC_SYNTHETIC_IDENTITY_PROBES_NOT_NORMAL_ROLE_ASSESSMENT_OR_FULL_ACCEPTANCE_OR_AZURE_L7'
MODELS = {
    'hf-qwen-normal-deepinfra': 'Qwen/Qwen3-235B-A22B-Instruct-2507:deepinfra',
    'hf-a01-gptoss-groq-third': 'openai/gpt-oss-120b:groq',
    'hf-a19-gptoss-groq-chronology': 'openai/gpt-oss-120b:groq',
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def build_requests():
    """Preparation is source coverage only; no provider call or expected reply."""
    jobs = []
    for actor in sorted(registered_agent_ids(include_orchestrator=False)):
        provider = ('hf-a01-gptoss-groq-third' if actor == 'a01' else
                    'hf-a19-gptoss-groq-chronology' if actor == 'a19' else 'hf-qwen-normal-deepinfra')
        request = AgentRequest(capability='responsibility.'+actor, objective=OBJECTIVE, context='',
            minimum_tier='MINI', task_class='planning', data_classification='CLOUD_PERMITTED',
            max_cost_usd=CAP, preferred_provider=provider)
        prompt = inference_prompt(request, Tier.MINI)
        jobs.append({'agent': actor, 'model': MODELS[provider], 'provider': provider,
            'request': request.transport_dump(), 'request_sha256': hashlib.sha256(canonical(request.transport_dump())).hexdigest(),
            'prompt': prompt, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()})
    assert len(jobs) == 21 and len({job['agent'] for job in jobs}) == 21
    return jobs


@contextmanager
def ownership(root):
    import fcntl
    with (root/'probe.lock').open('a+b') as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('identity probe already running') from None
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_new_or_same(path, value):
    raw = canonical(value)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('retained identity evidence changed')
        return
    temporary = path.with_suffix('.next.json')
    temporary.write_bytes(raw)
    temporary.replace(path)


def queue_body(planned, revision):
    return {'agent': planned['agent'], 'prompt': planned['prompt'], 'priority': 'normal', 'model_role': 'deep',
        'model': planned['model'], 'preferred_provider': planned['provider'], 'timeout_seconds': 60,
        'max_retries': 0, 'max_cost_usd': CAP, 'ram_mb': 0, 'vram_mb': 0, 'allow_cloud': True,
        'external_execution': False, 'data_classification': 'CLOUD_PERMITTED', 'task_class': 'planning',
        'response_format': 'text', 'idempotency_key': VERSION+':'+revision+':'+planned['agent']}


def assess(planned, job):
    bound = (job['agent'] == planned['agent'] and job['prompt'] == planned['prompt']
        and job['model'] == planned['model'] and job['preferred_provider'] == planned['provider']
        and job['allow_cloud'] == 1 and job['external_execution'] == 0
        and job['data_classification'] == 'CLOUD_PERMITTED' and 0 < job['max_cost_usd'] <= CAP
        and job['max_retries'] == 0 and job['response_format'] == 'text')
    if job['status'] == 'completed':
        bound = bound and job['provider'] == planned['provider'] and job['attempts'] == 1
    errors = ['execution_not_completed_or_unbound']
    passed = None
    if job['status'] == 'completed' and bound:
        errors = validate_user_facing_answer(OBJECTIVE, job['result'])
        passed = not errors
    elif job['status'] in ('failed', 'cancelled', 'budget_blocked') or not bound:
        passed = False
    return {'agent': planned['agent'], 'execution_bound': bound, 'passed': passed, 'errors': errors if passed is not None else [],
        'status': job['status'], 'model': job['model'], 'provider': job['provider'],
        'actual_cost_usd': job['actual_cost_usd'], 'started_at': job['started_at'], 'completed_at': job['completed_at']}


def run(mode, revision):
    if not re.fullmatch(r'[a-f0-9]{40}', revision) or os.getenv('PRIME_RUNTIME_REVISION') != revision:
        raise ValueError('exact installed runtime revision required')
    if PRODUCT_NAME != 'ORQEVIA · 奥启维亚':
        raise ValueError('current product identity is not installed')
    data_root = Path(os.getenv('PRIME_DATA_DIR', '/data'))
    root = data_root/'identity-probes'/revision
    root.mkdir(parents=True, exist_ok=True)
    source_root = Path(__import__('app.agent_dispatch_api', fromlist=['__file__']).__file__).parent
    source_hashes = {name: hashlib.sha256((source_root/name).read_bytes()).hexdigest() for name in
        ('agent_dispatch_api.py', 'product_identity.py', 'jarvis_response_contract.py', 'agent_registry.py')}
    planned = {'schema_version': VERSION, 'runtime_source_revision': revision, 'source_sha256': source_hashes,
        'objective': OBJECTIVE, 'scope': SCOPE, 'maximum_jobs': 21, 'maximum_cost_usd': .105, 'max_retries': 0,
        'jobs': build_requests()}
    with ownership(root):
        write_new_or_same(root/'plan.json', planned)
        manifest_path = root/'submitted.json'
        submitted = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        if (type(submitted) is not dict or not set(submitted).issubset({job['agent'] for job in planned['jobs']})
                or len(set(submitted.values())) != len(submitted)):
            raise ValueError('submitted identity manifest is invalid')
        db = sqlite3.connect((data_root/'compute-queue.db').resolve().as_uri()+'?mode=ro', uri=True, timeout=.2)
        db.row_factory = sqlite3.Row
        try:
            if mode == 'tick':
                from app.compute_catalog import load_catalog
                entries = {entry['id']: entry for entry in load_catalog()}
                for job in planned['jobs']:
                    entry = entries[job['provider']]
                    binding = {'agent': job['agent'], 'prompt_sha256': job['prompt_sha256']}
                    if not entry.get('enabled') or entry['model'] != job['model'] or binding not in entry['allowed_prompt_bindings']:
                        raise ValueError('exact identity prompt/provider binding is not admitted')
                active = db.execute("SELECT COUNT(*) FROM compute_jobs WHERE status IN "
                    "('queued','running','held','awaiting_approval') OR cloud_inflight=1").fetchone()[0]
                if not submitted and active:
                    raise ValueError('queue must be idle before identity wave begins')
                for job in planned['jobs']:
                    if job['agent'] in submitted or active >= 2:
                        continue
                    body = queue_body(job, revision)
                    headers = {'Authorization': 'Bearer '+os.environ['PRIME_SPINE_TOKEN'], 'Content-Type': 'application/json'}
                    response = json.load(urllib.request.urlopen(urllib.request.Request(
                        'http://127.0.0.1:8000/api/compute-queue/jobs', data=canonical(body), headers=headers), timeout=15))
                    submitted[job['agent']] = response['id']
                    temporary = manifest_path.with_suffix('.next.json')
                    temporary.write_bytes(canonical(submitted)); temporary.replace(manifest_path)
                    active += 1
            results = []
            for job in planned['jobs']:
                if job['agent'] not in submitted:
                    continue
                actual = dict(db.execute('SELECT * FROM compute_jobs WHERE id=?', (submitted[job['agent']],)).fetchone())
                result = assess(job, actual)
                result['job_id'] = actual['id']
                results.append(result)
                if result['passed'] is not None:
                    receipt = {'schema_version': VERSION, 'runtime_source_revision': revision, 'source_sha256': source_hashes,
                        'scope': SCOPE, 'input_request_utf8_base64': base64.b64encode(canonical(job['request'])).decode(),
                        'prompt_utf8_base64': base64.b64encode(actual['prompt'].encode()).decode(),
                        'output_utf8_base64': base64.b64encode((actual['result'] or '').encode()).decode(),
                        'output_sha256': hashlib.sha256((actual['result'] or '').encode()).hexdigest(),
                        'request_sha256': job['request_sha256'], 'prompt_sha256': job['prompt_sha256'],
                        'queue_receipt': actual, 'assessment': result, 'postprocessing': False,
                        'certification_awarded': False}
                    write_new_or_same(root/(actual['id']+'-terminal.json'), receipt)
        finally:
            db.close()
        summary = {'schema_version': VERSION, 'runtime_source_revision': revision, 'scope': SCOPE,
            'observed_at_utc': datetime.now(timezone.utc).isoformat(), 'identity_denominator': 21,
            'jobs_submitted': len(submitted), 'completed_count': sum(row['passed'] is not None for row in results),
            'identity_pass_count': sum(row['passed'] is True for row in results),
            'identity_fail_count': sum(row['passed'] is False for row in results), 'results': results,
            'normal_role_criteria_changed': False, 'full_role_accepted_count': 0,
            'unknown_cost_count': sum(row['passed'] is None or row['actual_cost_usd'] is None for row in results),
            'known_cost_usd': str(sum((Decimal(str(row['actual_cost_usd'])) for row in results
                                     if row['passed'] is not None and row['actual_cost_usd'] is not None), Decimal(0)))}
        summary['state'] = 'DONE' if summary['completed_count'] == 21 else 'IN_PROGRESS'
        if mode == 'prepare':
            summary['planned_jobs'] = planned['jobs']
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'tick', 'collect'))
    parser.add_argument('--expected-revision', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.mode, args.expected_revision), ensure_ascii=False))


if __name__ == '__main__':
    main()
