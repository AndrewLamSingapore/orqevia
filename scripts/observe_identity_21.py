"""Run or collect bounded installed-source identity probes, retaining Docker receipts."""
import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'tick', 'collect'))
    parser.add_argument('--expected-revision', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--container', default='prime-epoch-20260919-prime-1')
    args = parser.parse_args()
    source = Path(__file__).with_name('identity_probe_21_runtime.py').read_text(encoding='utf-8')
    docker = 'C:/Program Files/Docker/Docker/resources/bin/docker.exe'

    def identity():
        result = subprocess.run([docker, 'inspect', args.container, '--format', '{{.Id}} {{.Image}}'],
                                capture_output=True, text=True, check=True, timeout=15)
        instance, image = result.stdout.strip().split()
        return {'container_id': instance, 'image_id': image}

    before = identity()
    result = subprocess.run([docker, 'exec', args.container, 'python', '-B', '-c', source, args.mode,
                             '--expected-revision', args.expected_revision],
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr[:2000])
    report = json.loads(result.stdout)
    report['probe_runner_sha256'] = hashlib.sha256(source.encode()).hexdigest()
    after = identity()
    report['runtime_container'] = after
    report['runtime_identity_stable'] = before == after
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = args.output_dir/('IDENTITY-PROBE-21-'+stamp+'.json')
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    if before != after:
        raise RuntimeError('runtime identity changed during observation; original receipt retained')
    print(json.dumps({key: value for key, value in report.items() if key not in ('results', 'planned_jobs')}, ensure_ascii=False))
    print(json.dumps({'receipt': str(path), 'failures': [row for row in report['results'] if row['passed'] is False]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
