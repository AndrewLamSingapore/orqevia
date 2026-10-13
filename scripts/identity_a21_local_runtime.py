"""One independent local A21 identity probe; retain the earlier cloud timeout."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import urllib.request

from app.agent_dispatch_api import AgentRequest, inference_prompt
from app.jarvis_response_contract import validate_user_facing_answer
from app.settings import SETTINGS
from app.tier_router import Tier


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def local_request(original):
    request = AgentRequest.model_validate({**original['request'], 'data_classification': 'LOCAL_ONLY',
        'minimum_tier': 'NANO', 'preferred_provider': 'ollama-fast', 'max_cost_usd': 0})
    # Keep the exact prior source prompt while selecting the existing local model.
    prompt = inference_prompt(request, Tier.MINI)
    if prompt != original['prompt']:
        raise ValueError('original installed identity prompt changed')
    return request, prompt


def run(mode, revision):
    if not re.fullmatch(r'[a-f0-9]{40}', revision) or os.getenv('PRIME_RUNTIME_REVISION') != revision:
        raise ValueError('exact installed runtime revision required')
    root = Path(os.getenv('PRIME_DATA_DIR', '/data'))
    prior = root/'identity-probes'/revision
    planned = json.loads((prior/'plan.json').read_text())
    original = next(item for item in planned['jobs'] if item['agent'] == 'a21')
    submitted = json.loads((prior/'submitted.json').read_text())
    request, prompt = local_request(original)
    db = sqlite3.connect((root/'compute-queue.db').resolve().as_uri()+'?mode=ro', uri=True, timeout=.2)
    db.row_factory = sqlite3.Row
    try:
        failed = dict(db.execute('SELECT * FROM compute_jobs WHERE id=?', (submitted['a21'],)).fetchone())
        if failed['status'] != 'failed' or failed['error'] != 'TASK_TIMEOUT' or failed['prompt'] != prompt:
            raise ValueError('retained actual cloud timeout required')
        record_path = prior/'a21-independent-local.json'
        if mode == 'tick' and not record_path.exists():
            if db.execute("SELECT 1 FROM compute_jobs WHERE status IN "
                "('queued','running','held','awaiting_approval') OR cloud_inflight=1 LIMIT 1").fetchone():
                raise ValueError('queue must be idle before independent local probe')
            body = {'agent': 'a21', 'prompt': prompt, 'priority': 'normal', 'model_role': 'fast',
                'model': SETTINGS.fast_model, 'preferred_provider': 'ollama-fast', 'timeout_seconds': 60,
                'max_retries': 0, 'max_cost_usd': 0, 'allow_cloud': False, 'external_execution': False,
                'data_classification': 'LOCAL_ONLY', 'task_class': 'planning', 'response_format': 'text',
                'idempotency_key': 'identity-a21-independent-local:'+revision+':v1'}
            headers = {'Authorization': 'Bearer '+os.environ['PRIME_SPINE_TOKEN'], 'Content-Type': 'application/json'}
            job = json.load(urllib.request.urlopen(urllib.request.Request(
                'http://127.0.0.1:8000/api/compute-queue/jobs', data=canonical(body), headers=headers), timeout=15))
            record = {'job_id': job['id'], 'original_failed_cloud_job_id': failed['id'],
                'runtime_source_revision': revision, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                'model': SETTINGS.fast_model, 'provider': 'ollama-fast', 'request': request.transport_dump()}
            temporary = record_path.with_suffix('.next.json'); temporary.write_bytes(canonical(record)); temporary.replace(record_path)
        report = {'scope': 'INDEPENDENT_LOCAL_A21_IDENTITY_PROBE_NOT_CLOUD_REPLAY_OR_NORMAL_OR_FULL_ACCEPTANCE',
            'runtime_source_revision': revision, 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
            'identity_denominator': 1, 'identity_pass_count': 0, 'identity_fail_count': 0,
            'completed_count': 0, 'jobs_submitted': int(record_path.exists()), 'known_cost_usd': '0',
            'unknown_cost_count': 0, 'hf_spend_usd': 0, 'max_retries': 0, 'state': 'IN_PROGRESS',
            'original_failed_cloud_job_id': failed['id'], 'results': [], 'full_role_accepted_count': 0,
            'normal_role_criteria_changed': False}
        if record_path.exists():
            record = json.loads(record_path.read_text())
            actual = dict(db.execute('SELECT * FROM compute_jobs WHERE id=?', (record['job_id'],)).fetchone())
            bound = (actual['agent'] == 'a21' and actual['prompt'] == prompt and actual['model'] == record['model']
                and actual['preferred_provider'] == 'ollama-fast' and actual['allow_cloud'] == 0
                and actual['external_execution'] == 0 and actual['data_classification'] == 'LOCAL_ONLY'
                and actual['max_cost_usd'] == 0 and actual['max_retries'] == 0 and actual['response_format'] == 'text')
            if actual['status'] == 'completed':
                bound = bound and actual['provider'] == 'ollama-fast' and actual['attempts'] == 1
            passed = None
            errors = []
            if actual['status'] == 'completed' and bound:
                errors = validate_user_facing_answer(original['request']['objective'], actual['result']); passed = not errors
            elif actual['status'] in ('failed', 'cancelled', 'budget_blocked') or not bound:
                passed = False; errors = ['execution_not_completed_or_unbound']
            result = {'agent': 'a21', 'job_id': actual['id'], 'execution_bound': bound, 'passed': passed,
                'errors': errors, 'status': actual['status'], 'model': actual['model'], 'provider': actual['provider'],
                'completed_at': actual['completed_at'], 'actual_cost_usd': actual['actual_cost_usd']}
            report['results'] = [result]
            report.update(identity_pass_count=int(passed is True), identity_fail_count=int(passed is False),
                completed_count=int(passed is not None), state='DONE' if passed is not None else 'IN_PROGRESS')
            if passed is not None:
                receipt = {**record, 'assessment': result, 'queue_receipt': actual,
                    'input_request_utf8_base64': base64.b64encode(canonical(record['request'])).decode(),
                    'prompt_utf8_base64': base64.b64encode(prompt.encode()).decode(),
                    'output_utf8_base64': base64.b64encode((actual['result'] or '').encode()).decode(),
                    'output_sha256': hashlib.sha256((actual['result'] or '').encode()).hexdigest(),
                    'postprocessing': False, 'certification_awarded': False}
                path = prior/(actual['id']+'-local-terminal.json')
                if path.exists() and path.read_bytes() != canonical(receipt):
                    raise ValueError('retained local identity evidence changed')
                if not path.exists():
                    temporary = path.with_suffix('.next.json'); temporary.write_bytes(canonical(receipt)); temporary.replace(path)
        return report
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'tick', 'collect'))
    parser.add_argument('--expected-revision', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.mode, args.expected_revision), ensure_ascii=False))


if __name__ == '__main__':
    main()
