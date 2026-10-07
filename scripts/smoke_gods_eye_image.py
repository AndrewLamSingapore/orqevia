"""Tiny packaged-engine/HTTP smoke: synthetic tmpfs data, no lifespan or model.

Run only in the disposable CI image with network disabled and no credentials.
Operator authentication is synthetic; this does not prove an enrolled Owner,
live HF, real agent work, deployment acceptance, or L7 certification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

SYNTHETIC_OPERATOR = 'ci-gods-eye-synthetic-operator-not-owner'
TASK = '01234567-89ab-4cde-8f01-23456789abcd'
RESULT = 'result:' + TASK + ':a20'
PUBLIC_RESULT_DIGEST = hashlib.sha256(b'isolated public CI fixture').hexdigest()


class SmokeFailure(RuntimeError):
    """Only fixed public failure codes may leave this smoke boundary."""


def require(condition, code):
    if condition is not True:
        raise SmokeFailure(code)


def validate_revision(expected, configured):
    require(type(expected) is str and re.fullmatch('[0-9a-f]{40}', expected) is not None,
            'EXPECTED_SOURCE_INVALID')
    require(configured == expected, 'IMAGE_SOURCE_MISMATCH')


def synthetic_projection(registry, revision):
    """The fixture is declared synthetic, not an executed task or attestation."""
    return {'source_revision': revision,
        'agents': [{key: row[key] for key in ('id', 'name', 'role', 'version')} |
                   {'capabilities': list(row['capability_requirements'])}
                   for row in registry['agents']],
        'results': [{'id': RESULT, 'task_id': TASK, 'agent_id': 'a20',
            'source_revision': revision, 'environment': 'CI', 'integrity': 'VALID',
            'currentness': 'CURRENT', 'verification': 'UNVERIFIED',
            'evidence_ref': 'objective:' + TASK + ':r0',
            'result_sha256': PUBLIC_RESULT_DIGEST}],
        'metrics': [{'metric_id': 'ci-public-count', 'agent_id': 'a20',
            'result_ids': [RESULT], 'name': 'observed_task_count', 'value': 1,
            'unit': 'count'}]}


def validate_formal(summary, overview, why, proof, dependencies, registry, revision):
    ids = {row['id'] for row in registry['agents']}
    require(len(ids) == 21 and {'a26', 'a28', 'a29'} <= ids and 'a03' not in ids,
            'PERMANENT_POPULATION_MISMATCH')
    require(summary.get('status') == 'READY' and summary.get('source_revision') == revision
            and type(summary.get('permanent_agent_count')) is int and summary['permanent_agent_count'] == 21
            and summary.get('rdf') == 'PASS'
            and summary.get('shacl') == 'PASS_ACCEPTED_PROJECTION'
            and summary.get('reasoning') == 'PASS_FIXED_OWL2_RL_SUBSET'
            and type(summary.get('accepted_results')) is int and summary['accepted_results'] == 1
            and type(summary.get('accepted_metrics')) is int and summary['accepted_metrics'] == 1
            and summary.get('l7_awarded') is False
            and summary.get('production_acceptance') == 'UNVERIFIED', 'FORMAL_ENGINE_RESULT_INVALID')
    require({row['id'] for row in overview.get('agents', [])} == ids,
            'FORMAL_QUERY_POPULATION_MISMATCH')
    require(why.get('agent_id') == 'a20' and why.get('l7_awarded') is False
            and why.get('verified_capabilities') == [], 'FORMAL_WHY_UPLIFT')
    require(proof.get('status') == 'READY' and proof.get('result_id') == RESULT
            and len(proof.get('rows', [])) == 1
            and proof['rows'][0].get('digest') == PUBLIC_RESULT_DIGEST
            and proof['rows'][0].get('verification') == 'UNVERIFIED', 'FORMAL_PROOF_BINDING_INVALID')
    require(dependencies.get('status') == 'READY'
            and dependencies.get('result_id') == RESULT
            and dependencies.get('rows') == [{'metric_id': 'ci-public-count', 'agent_id': 'a20'}],
            'FORMAL_DEPENDENCY_BINDING_INVALID')


def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def validate_snapshot(snapshot, registry, expected):
    agents, certification = snapshot.get('agents'), snapshot.get('certification')
    ids = {row['id'] for row in registry['agents']}
    require(snapshot.get('schema_version') == 'jarvis.gods-eye.v1'
            and snapshot.get('source_revision') == expected
            and snapshot.get('access_scope') == 'LOOPBACK_OPERATOR_NOT_PWA_IDENTITY_PROOF'
            and snapshot.get('registry', {}).get('agent_ids') == sorted(ids)
            and type(agents) is list and len(agents) == 21
            and all(type(row) is dict and row.get('l7_status') == 'UNKNOWN' for row in agents)
            and {row.get('agent_id') for row in agents} == ids
            and type(certification) is dict and 'l7_count' in certification
            and certification['l7_count'] is None
            and snapshot.get('semantics', {}).get('status') == 'READY', 'SNAPSHOT_BINDING_INVALID')


def validate_read_only(before, root):
    after = inventory(root)
    require(all(after.get(name) == digest for name, digest in before.items()),
            'READ_ROUTE_CHANGED_DOMAIN_BYTES')
    require(set(after) - set(before) <= {'queue.db-shm', 'queue.db-wal'},
            'READ_ROUTE_CREATED_DOMAIN_STATE')
    for name, size in (('queue.db-shm', 32768), ('queue.db-wal', 0)):
        path = root / name
        require(not path.exists() or path.stat().st_size == size, 'UNEXPECTED_SQLITE_COORDINATION')


def run(expected):
    validate_revision(expected, os.getenv('PRIME_RUNTIME_REVISION'))
    require(not any(os.getenv(name) for name in ('HF_TOKEN', 'PRIME_HF_TOKEN_FILE',
            'CLOUDFLARE_TUNNEL_TOKEN', 'PRIME_PROVIDER_CATALOG')), 'NON_SYNTHETIC_ENVIRONMENT_DENIED')
    require(Path('/app/app/production_entry.py').is_file(), 'PACKAGED_APPLICATION_MISSING')
    sys.path.insert(0, '/app')
    from app.agent_registry import load_agent_registry
    from app.semantic_fabric import _engines, build_semantics, query_semantics
    registry = load_agent_registry()
    _engines()  # Missing or wrong-version real engines fail; never skip.
    projection = synthetic_projection(registry, expected)
    formal = build_semantics(projection)
    overview = query_semantics(projection, 'overview')
    why = query_semantics(projection, 'why', 'a20')
    proof = query_semantics(projection, 'prove_it', RESULT)
    dependencies = query_semantics(projection, 'depends_on', RESULT)
    validate_formal(formal, overview, why, proof, dependencies, registry, expected)
    from fastapi.testclient import TestClient
    with tempfile.TemporaryDirectory(prefix='prime-ci-gods-eye-') as directory:
        data = Path(directory)
        os.environ.update(PRIME_DATA_DIR=str(data), PRIME_COMPUTE_QUEUE_DB=str(data / 'queue.db'),
            PRIME_SPINE_TOKEN=SYNTHETIC_OPERATOR, PRIME_REGISTRY_V1_ENABLED='1',
            PRIME_AGENT_CERT_AZURE_ES256_ENABLED='0', PRIME_OWNER_TRUSTED_PEERS='')
        from app import production_entry as entry
        from app.action_records import close_ledgers
        before = inventory(data)  # Imports may initialize only isolated fixture DBs.
        client = TestClient(entry.app, base_url='http://127.0.0.1:8000',
                            client=('127.0.0.1', 45001))
        # No context manager: application lifespan/workers must never start.
        try:
            gates = {}
            for path, marker in (('/control/gods-eye', b'God'),
                    ('/control/gods-eye.js', b'gods-eye'), ('/control/gods-eye.css', b'body')):
                response = client.get(path)
                require(response.status_code == 200 and marker.lower() in response.content.lower(),
                        'PACKAGED_ASSET_MISSING')
                require(response.headers.get('cache-control') == 'no-store', 'ASSET_CACHE_GUARD_MISSING')
            response = client.get('/control/api/gods-eye')
            require(response.status_code == 200, 'SNAPSHOT_READ_FAILED')
            snapshot = response.json()
            validate_snapshot(snapshot, registry, expected)
            require(SYNTHETIC_OPERATOR not in response.text, 'OPERATOR_SECRET_EXPORTED')
            require(client.get('/control/api/agent-capabilities').status_code == 401,
                    'PRIVATE_CERTIFICATION_BEARER_GUARD_MISSING')
            for endpoint in ('/control/api/gods-eye/why?agent_id=a20',
                             '/control/api/gods-eye/dependencies?subject=' + RESULT):
                result = client.get(endpoint)
                require(result.status_code == 200 and result.json().get('l7_awarded') is False,
                        'PACKAGED_TYPED_QUERY_FAILED')
            gates['packaged_assets_and_formal_routes'] = True
            for headers in ({'Host': 'attacker.invalid'}, {'Origin': 'http://attacker.invalid'},
                            {'Sec-Fetch-Site': 'cross-site'}):
                require(client.get('/control/api/gods-eye', headers=headers).status_code == 403,
                        'UNTRUSTED_TRANSPORT_ACCEPTED')
            remote = TestClient(entry.app, base_url='http://127.0.0.1:8000', client=('192.0.2.1', 45002))
            try:
                require(remote.get('/control/api/gods-eye', headers={'X-Forwarded-For': '127.0.0.1'}).status_code == 403,
                        'FORWARDED_PEER_ACCEPTED')
            finally:
                remote.close()
            require(client.post('/control/api/gods-eye', headers={'Origin': 'http://127.0.0.1:8000'},
                    json={'dispatch': True}).status_code in (404, 405), 'READ_ROUTE_MUTATION_ACCEPTED')
            os.environ.pop('PRIME_SPINE_TOKEN')
            require(client.get('/control/api/gods-eye').status_code == 503, 'UNCONFIGURED_AUTH_ACCEPTED')
            gates['operator_transport_and_read_only_denials'] = True
            validate_read_only(before, data)
            gates['unchanged_isolated_domain_bytes'] = True
        finally:
            client.close()
            close_ledgers()
    return {'status': 'PASS_PACKAGED_ISOLATED_FORMAL_AND_READ_ONLY_ROUTE_SMOKE',
        'source_revision': expected, 'scope': 'DISPOSABLE_CI_IMAGE_SYNTHETIC_TMPFS_NO_LIFESPAN',
        'formal_engine_versions': formal['engines'], 'permanent_agent_count': 21,
        'checks': gates, 'network_probe_performed': False, 'model_calls': 0,
        'owner_identity_verified': False, 'l7_certification_verified': False,
        'production_acceptance': 'UNVERIFIED'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-source', required=True)
    expected = parser.parse_args().expected_source
    try:
        result = run(expected)
        code = 0
    except SmokeFailure as error:
        result, code = {'status': 'FAIL_CLOSED', 'code': str(error)}, 1
    except Exception:
        result, code = {'status': 'FAIL_CLOSED', 'code': 'PACKAGED_SMOKE_FAILED'}, 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
