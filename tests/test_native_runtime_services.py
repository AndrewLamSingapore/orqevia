"""Event observation must not create unused reasoning/authority services."""

import json
import os
from pathlib import Path
import subprocess
import sys


def test_event_observation_is_independent_of_cognitive_control_plane(tmp_path):
    program = """
import builtins
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import os

original = builtins.__import__
forbidden = {'cognitive_orchestrator', 'agent_runtime', 'model_gateway', 'compute_ledger', 'multi_specialist'}
def guarded(name, *args, **kwargs):
    if name.rsplit('.', 1)[-1] in forbidden:
        raise AssertionError('Observation imported an unrelated reasoning or authority service')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from app import runtime
assert runtime._services == {}
with ThreadPoolExecutor(max_workers=4) as pool:
    identities = list(pool.map(lambda _: id(runtime.events), range(12)))
assert len(set(identities)) == 1
assert set(runtime._services) == {'events', 'memory'}
print(json.dumps({'files': sorted(p.name for p in Path(os.environ['ORQEVIA_DATA_DIR']).glob('*.db'))}))
"""
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("ORQEVIA_", "PRIME_"))}
    environment.update(ORQEVIA_DATA_DIR=str(tmp_path), ORQEVIA_OPEN_ACCESS="0")
    result = subprocess.run(
        [sys.executable, "-B", "-c", program],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["files"] == ["orqevia-memory.db", "portfolio-events.db"]
