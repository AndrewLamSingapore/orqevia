"""50 real, model-free production-entrypoint objective/artifact roundtrips.

Runs inside the acceptance container so the loopback-only control boundary is
exercised without granting the Docker gateway owner access.
"""
import hashlib
import json
import statistics
import time
import urllib.request


BASE = 'http://127.0.0.1:8000'
ORIGIN = {'Origin': BASE, 'Content-Type': 'application/json'}


def request(path, method='GET', body=None):
    data = None if body is None else json.dumps(body).encode('utf-8')
    with urllib.request.urlopen(
        urllib.request.Request(BASE + path, data=data, method=method,
                               headers=ORIGIN if body is not None else {}), timeout=10
    ) as response:
        return response.status, response.read(), response.headers


def cases():
    for number in range(20):
        value = f'PRIME endpoint hash case {number:02d}: café/東京/{number * number}'
        yield 'sha256', value, hashlib.sha256(value.encode('utf-8')).hexdigest()
    for number in range(15):
        value = json.dumps({'z': number, 'a': [number, number + 1], 'unicode': 'é'},
                           ensure_ascii=False, separators=(',', ':'))
        expected = json.dumps(json.loads(value), sort_keys=True, indent=2,
                              ensure_ascii=False, allow_nan=False)
        yield 'json_format', value, expected
    for number in range(15):
        value = json.dumps({'case': number, 'valid': True,
                            'nested': {'value': f'item-{number:02d}'}},
                           separators=(',', ':'))
        yield 'json_validate', value, True


def ready():
    status, raw, headers = request('/health')
    assert status == 200 and json.loads(raw) == {'ok': True}
    assert headers['Cache-Control'] == 'no-store'
    status, html, headers = request('/control')
    assert status == 200 and b'PRIME Control' in html
    assert headers['X-Frame-Options'] == 'DENY'


def main():
    ready()
    durations = []
    counts = {'sha256': 0, 'json_format': 0, 'json_validate': 0}
    seen_tasks = set()
    for operation, content, expected in cases():
        started = time.perf_counter()
        body = {'objective': 'Verify deterministic production endpoint',
                'context': content, 'capability': 'responsibility.a02',
                'deterministic_operation': operation}
        status, raw, _ = request('/control/api/objectives', 'POST', body)
        assert status == 202, (operation, status, raw)
        task_id = json.loads(raw)['id']
        assert task_id not in seen_tasks
        seen_tasks.add(task_id)
        status, raw, _ = request('/control/api/objectives/' + task_id)
        task = json.loads(raw)
        assert status == 200 and task['id'] == task_id and task['state'] == 'COMPLETED', task
        dispatch = task['steps'][0]['dispatch']
        assert dispatch['state'] == 'COMPLETED' and dispatch['model_calls'] == 0, dispatch
        artifact = dispatch['artifact']
        assert artifact['task_id'] == task_id and artifact['type'] == 'json', artifact
        assert artifact['validation_state'] == 'STRUCTURE_VALIDATED', artifact
        status, raw, headers = request('/control/api/artifacts/' + artifact['artifact_id'])
        assert status == 200 and headers['Content-Disposition'] == 'attachment'
        assert hashlib.sha256(raw).hexdigest() == artifact['sha256'], artifact
        assert json.loads(raw) == expected, (operation, expected, raw)
        counts[operation] += 1
        durations.append(time.perf_counter() - started)
    ready()
    assert len(seen_tasks) == 50 and counts == {'sha256': 20, 'json_format': 15, 'json_validate': 15}
    print(json.dumps({'entrypoint': 'app.production_entry', 'cases': len(seen_tasks),
                      'passed': len(seen_tasks), 'counts': counts,
                      'p95_seconds': round(sorted(durations)[47], 3),
                      'median_seconds': round(statistics.median(durations), 3)}, sort_keys=True))


if __name__ == '__main__':
    main()
