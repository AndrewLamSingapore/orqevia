"""Run the real PowerShell guard with synthetic inventory, never native processes."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("scenario", ["process", "listener", "unavailable", "clear"])
def test_preflight_requires_successful_clear_inventory(tmp_path, scenario):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell, "PowerShell is required for the Windows/Ubuntu preflight gate"
    guard = Path(__file__).resolve().parents[1] / "scripts/native-inference-preflight.ps1"
    fixture = tmp_path / "preflight-test.ps1"
    fixture.write_text("""
param([string]$Guard, [string]$Scenario)
. $Guard
function Get-Process {
    [CmdletBinding()] param()
    if ($Scenario -eq 'unavailable') { throw 'synthetic inventory failure' }
    if ($Scenario -eq 'process') { [pscustomobject]@{ProcessName='ollama';Id=13544} }
}
function Get-NetTCPConnection {
    [CmdletBinding()] param([string]$State)
    if ($Scenario -eq 'listener') { [pscustomobject]@{LocalPort=11434;OwningProcess=999} }
}
try { Assert-NativeInferenceIsolated; exit 0 } catch { Write-Output $_.Exception.Message; exit 7 }
""", encoding="utf-8")
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(fixture),
                             "-Guard", str(guard), "-Scenario", scenario], capture_output=True, text=True, timeout=30)
    assert result.returncode == (0 if scenario == "clear" else 7), result.stdout + result.stderr
    if scenario != "clear":
        assert "HOLD:" in result.stdout
