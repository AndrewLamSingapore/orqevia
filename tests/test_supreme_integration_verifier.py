import json
import subprocess
import sys
from pathlib import Path


def test_independent_supreme_integration_verifier():
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run([sys.executable, str(root / "scripts" / "verify_supreme_integration.py")], cwd=root, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr or completed.stdout
    receipt = json.loads(completed.stdout)
    assert receipt["passed"] == receipt["total"] == 5

