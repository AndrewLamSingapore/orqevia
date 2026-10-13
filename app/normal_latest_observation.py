"""Read-only replay of pinned latest normal cases, separate from historical waves."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .agent_coaching import digest, effective_prompt
from .agent_cert_role_review import review_role_output
from .agent_registry import agent_record, registered_agent_ids

SCHEMA = 'orqevia.normal-latest-bindings.v1'
MANIFEST_NAME = 'normal-latest-role-observation.json'
SCOPE = 'LATEST_PINNED_NORMAL_CASES_NOT_FULL_ROLE_ACCEPTANCE_OR_AZURE_L7'
ORACLE_FILES = (
    'agent_cert_role_review.py', 'agent_cert_cases.py', 'agent_cert_execution.py',
    'agent_cert_numeric.py', 'agent_cert_rates.py', 'agent_cert_weighted.py',
    'agent_cert_boundary.py', 'agent_cert_a17_boundary.py', 'agent_cert_data_quality.py',
    'agent_cert_portfolio.py', 'agent_cert_cost.py', 'agent_cert_risk.py',
    'agent_cert_release.py', 'agent_cert_role_g1.py', 'agent_cert_role_group_two.py',
)


def oracle_fingerprints():
    root = Path(__file__).resolve().parent
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ORACLE_FILES}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


def _hash(value):
    return type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None


def _timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone required')
    return parsed.astimezone(timezone.utc)


def normal_latest_snapshot(root, *, manifest_path=None):
    """Verify original jobs and unchanged oracles; submit no work and export no answers."""
    unavailable = {
        'status': 'UNAVAILABLE', 'assessment_scope': SCOPE, 'agents': [],
        'normal_pass_count': None, 'normal_fail_count': None, 'normal_denominator': 21,
        'reassessed_count': None, 'full_role_accepted_count': 0,
        'independent_azure_status': 'NOT_ESTABLISHED', 'certification_awarded': False,
        'model_calls': 0, 'last_execution_at': None,
    }
    db = None
    try:
        root = Path(root)
        path = Path(manifest_path) if manifest_path is not None else root/MANIFEST_NAME
        with path.open('rb') as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            return unavailable
        manifest = json.loads(raw, object_pairs_hook=_unique)
        if manifest['schema_version'] != SCHEMA or manifest['oracle_sha256'] != oracle_fingerprints():
            return {**unavailable, 'status': 'UNVERIFIED', 'reason': 'oracle_or_manifest_changed'}
        jobs = manifest['jobs']
        if (type(jobs) is not list or len(jobs) != 21
                or {job['agent'] for job in jobs} != registered_agent_ids(include_orchestrator=False)
                or len({job['job_id'] for job in jobs}) != 21):
            return unavailable
        if (not re.fullmatch(r'[a-f0-9]{40}', manifest['assessment_runtime_revision'])
                or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,128}', manifest['wave'])):
            return unavailable
        now = datetime.now(timezone.utc)
        if _timestamp(manifest['recorded_at']) > now+timedelta(seconds=5):
            return unavailable
        for expected in jobs:
            if (str(uuid.UUID(expected['job_id'])) != expected['job_id']
                    or not all(_hash(expected[key]) for key in ('prompt_sha256', 'request_sha256', 'output_sha256'))
                    or not re.fullmatch(r'[a-zA-Z0-9._:/-]{1,200}', expected['model'])
                    or not re.fullmatch(r'[a-zA-Z0-9._:-]{1,96}', expected['provider'])):
                return unavailable
            if _timestamp(expected['completed_at']) > now+timedelta(seconds=5):
                return unavailable
        db = sqlite3.connect((root/'compute-queue.db').resolve().as_uri()+'?mode=ro', uri=True, timeout=.2)
        db.row_factory = sqlite3.Row
        deadline = time.monotonic()+.5
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        db.execute('BEGIN')
        agents = []
        known_cost = Decimal(0)
        unknown_cost = 0
        for expected in jobs:
            row = db.execute(
                'SELECT agent,prompt,status,model,preferred_provider,provider,max_retries,max_cost_usd,'
                'allow_cloud,external_execution,data_classification,response_format,result,completed_at,actual_cost_usd '
                'FROM compute_jobs WHERE id=? AND length(CAST(prompt AS BLOB))<=65536 '
                'AND (result IS NULL OR length(CAST(result AS BLOB))<=65536)', (expected['job_id'],)).fetchone()
            if row is None:
                return {**unavailable, 'status': 'UNVERIFIED', 'reason': 'pinned_job_missing'}
            request, _ = effective_prompt(expected['agent'], 'baseline', 1001)
            bound = (row['agent'] == expected['agent'] and row['model'] == expected['model']
                and row['preferred_provider'] == row['provider'] == expected['provider']
                and hashlib.sha256(row['prompt'].encode()).hexdigest() == expected['prompt_sha256']
                and digest(request) == expected['request_sha256']
                and hashlib.sha256((row['result'] or '').encode()).hexdigest() == expected['output_sha256']
                and row['completed_at'] == expected['completed_at'] and row['status'] == 'completed'
                and row['max_retries'] == 0 and row['allow_cloud'] == 1 and row['external_execution'] == 0
                and 0 <= row['max_cost_usd'] <= .005 and row['data_classification'] == 'CLOUD_PERMITTED'
                and row['response_format'] == 'strict_json')
            if not bound:
                return {**unavailable, 'status': 'UNVERIFIED', 'reason': 'pinned_job_binding_changed'}
            passed, errors = review_role_output(expected['agent'], 'responsibility.'+expected['agent'], row['result'])
            agents.append({'agent_id': expected['agent'], 'role': agent_record(expected['agent'])['name'],
                'job_id': expected['job_id'], 'model': expected['model'], 'provider': expected['provider'],
                'execution_bound': True, 'latest_pass': passed, 'latest_score': 100 if passed else 0,
                'errors': list(errors), 'completed_at': row['completed_at'],
                'full_role_acceptance_status': 'NOT_ESTABLISHED'})
            cost = row['actual_cost_usd']
            if cost is None:
                unknown_cost += 1
            elif type(cost) in (float, int) and Decimal(str(cost)).is_finite() and cost >= 0:
                known_cost += Decimal(str(cost))
            else:
                return unavailable
        observer_revision = os.getenv('PRIME_RUNTIME_REVISION', os.getenv('PRIME_INTERFACE_RUNTIME_REVISION', 'UNKNOWN'))
        if not re.fullmatch(r'[a-f0-9]{40}', observer_revision):
            observer_revision = 'UNKNOWN'
        return {**unavailable, 'status': 'OBSERVED', 'wave': manifest['wave'], 'agents': agents,
            'normal_pass_count': sum(agent['latest_pass'] for agent in agents),
            'normal_fail_count': sum(not agent['latest_pass'] for agent in agents), 'reassessed_count': len(agents),
            'last_execution_at': max(agents, key=lambda agent: _timestamp(agent['completed_at']))['completed_at'],
            'reconciled_at': datetime.now(timezone.utc).isoformat(), 'manifest_recorded_at': manifest['recorded_at'],
            'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'oracle_sha256': manifest['oracle_sha256'],
            'assessment_runtime_revision': manifest['assessment_runtime_revision'],
            'observer_runtime_revision': observer_revision,
            'known_selected_cost_usd': str(known_cost), 'unknown_selected_cost_count': unknown_cost,
            'score_scale': 'SINGLE_SYNTHETIC_CASE_BINARY_0_OR_100_NOT_ROLE_COMPETENCE'}
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, OverflowError, AttributeError, RecursionError):
        return unavailable
    finally:
        if db is not None:
            db.close()


def main():
    """CLI verification emits sanitized evidence and never enqueues inference."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', default=os.getenv('PRIME_DATA_DIR', '/data'))
    parser.add_argument('--manifest', type=Path, help='Explicit retained binding manifest; default is in data-root')
    args = parser.parse_args()
    report = normal_latest_snapshot(args.data_root, manifest_path=args.manifest)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report['status'] == 'OBSERVED' and report['normal_pass_count'] == 21 else 1


if __name__ == '__main__':
    raise SystemExit(main())
