import json,subprocess,sys
from pathlib import Path


def test_independent_aef_controls_verifier_passes():
    root=Path(__file__).resolve().parents[1]
    completed=subprocess.run([sys.executable,str(root/'scripts'/'verify_aef_controls.py')],cwd=root,
        text=True,capture_output=True,check=False)
    assert completed.returncode==0,completed.stderr
    result=json.loads(completed.stdout)
    assert result['status']=='PASS' and result['passed']==result['total']==5
    assert result['production_touched'] is False
