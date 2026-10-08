"""Prospective, non-fault startup checks; never crash or touch production."""
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]


def test_only_existing_backend_command_enables_startup_fault_handler():
    text = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    commands = [line[4:] for line in text.splitlines() if line.startswith('CMD ')]
    assert len(commands) == 1
    assert json.loads(commands[0]) == [
        'python', '-X', 'faulthandler', '-m', 'uvicorn', 'app.production_entry:app',
        '--host', '0.0.0.0', '--port', '8000', '--no-proxy-headers',
    ]
    assert 'PYTHONFAULTHANDLER=' not in text
    compose = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
    assert 'command: ["uvicorn", "app.interface_server:app"' in compose
    assert 'faulthandler' not in compose


def test_startup_option_is_enabled_without_dumping_values_or_causing_fault():
    result = subprocess.run([
        sys.executable, '-X', 'faulthandler', '-c',
        'import faulthandler; assert faulthandler.is_enabled(); print("ENABLED_NO_FAULT")',
    ], capture_output=True, timeout=5)
    assert result.returncode == 0
    assert result.stdout.strip() == b'ENABLED_NO_FAULT'
    assert result.stderr == b''
