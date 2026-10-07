#!/usr/bin/env python3
"""Bounded HTTP benchmark of PRIME's current deterministic production path.

This measures API/objective/artifact correctness and latency in the disposable
CI container. It does not measure model inference or ABEX hardware performance.
"""

import argparse
import hashlib
import json
import statistics
import time
import urllib.request


def request(base, path, *, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {'Origin': base, 'Content-Type': 'application/json'} if data else {}
    req = urllib.request.Request(base + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, response.read()


def run(base, cases):
    timings = []
    for index in range(cases):
        context = f'production-endpoint-case-{index:04d}'
        started = time.perf_counter()
        status, raw = request(base, '/control/api/objectives', body={
            'objective': 'Hash supplied text',
            'context': context,
            'capability': 'responsibility.a02',
            'deterministic_operation': 'sha256',
        })
        assert status == 202, f'case {index}: objective HTTP {status}'
        task_id = json.loads(raw)['id']
        status, raw = request(base, '/control/api/objectives/' + task_id)
        assert status == 200, f'case {index}: read HTTP {status}'
        objective = json.loads(raw)
        assert objective['state'] == 'COMPLETED', f'case {index}: {objective["state"]}'
        dispatch = objective['steps'][0]['dispatch']
        assert dispatch['model_calls'] == 0
        artifact_id = dispatch['artifact']['artifact_id']
        status, raw = request(base, '/control/api/artifacts/' + artifact_id)
        assert status == 200 and hashlib.sha256(context.encode()).hexdigest().encode() in raw, \
            f'case {index}: artifact mismatch'
        timings.append((time.perf_counter() - started) * 1000)
    ordered = sorted(timings)
    return {'entrypoint': 'app.production_entry:app', 'kind': 'deterministic_objective_artifact_http',
            'cases': cases, 'passed': cases, 'model_calls': 0,
            'latency_ms': {'median': round(statistics.median(ordered), 2),
                           'p95': round(ordered[int(0.95 * (cases - 1))], 2),
                           'max': round(ordered[-1], 2)},
            'scope': 'disposable off-host Docker; not model or ABEX production latency'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--cases', type=int, default=50)
    args = parser.parse_args()
    if not 1 <= args.cases <= 100:
        parser.error('cases must be between 1 and 100')
    print(json.dumps(run(args.base_url.rstrip('/'), args.cases), sort_keys=True))
