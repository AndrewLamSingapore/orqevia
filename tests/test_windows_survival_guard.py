from pathlib import Path
import os
import shutil
import subprocess

import pytest


def test_docker_engine_probe_is_bounded_and_kills_hung_child():
    probe = (
        Path(__file__).parents[1]
        / "deploy"
        / "windows"
        / "docker-engine-probe.ps1"
    ).read_text(encoding="utf-8")

    assert "WaitForExit($TimeoutMilliseconds)" in probe
    assert "$process.Kill()" in probe
    assert "return $false" in probe
    assert "docker info" not in probe.lower()


def test_post_boot_evidence_is_atomic_and_fail_closed():
    writer = (
        Path(__file__).parents[1]
        / "deploy"
        / "windows"
        / "atomic-evidence.ps1"
    ).read_text(encoding="utf-8")

    assert "ConvertTo-Json" in writer and "-ErrorAction Stop" in writer
    assert "Set-Content -LiteralPath $temporary" in writer
    assert "Move-Item -LiteralPath $temporary -Destination $Path" in writer
    assert "Evidence result file was not committed" in writer


def test_startup_package_uses_its_installed_probe_not_a_runtime_checkout():
    package = Path(__file__).parents[1] / "deploy" / "windows"
    guard = (package / "Start-ABEX-Survival.ps1").read_text(encoding="utf-8")
    assert (package / "docker-engine-probe.ps1").is_file()
    assert 'Join-Path $PSScriptRoot "docker-engine-probe.ps1"' in guard
    assert "runtime\\prime-epoch" not in guard


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell installation contract")
@pytest.mark.parametrize("include_probe", [True, False])
def test_relocated_startup_package_is_noop_or_fails_before_recovery(tmp_path, include_probe):
    package = Path(__file__).parents[1] / "deploy" / "windows"
    installed = tmp_path / "installed operations"
    installed.mkdir()
    shutil.copy2(package / "Start-ABEX-Survival.ps1", installed)
    if include_probe:
        # A positive sentinel proves the sibling fixture was loaded from the
        # installation, rather than silently using a repository/Docker runtime.
        (installed / "docker-engine-probe.ps1").write_text(
            "function Test-DockerEngine { Write-Output $true }\n", encoding="utf-8"
        )
    log_root = tmp_path / "logs"
    guard_path = str(installed / "Start-ABEX-Survival.ps1").replace("'", "''")
    log_path = str(log_root).replace("'", "''")
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "function Start-Process { throw 'MUTATION_FORBIDDEN' }; "
        "function Stop-Process { throw 'MUTATION_FORBIDDEN' }; "
        "function Rename-Item { throw 'MUTATION_FORBIDDEN' }; "
        f"& '{guard_path}' -LogRoot '{log_path}'; exit $LASTEXITCODE"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", command],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == (0 if include_probe else 2), result.stderr
    receipt = (log_root / "latest.log").read_text()
    assert ("OK Docker engine was already healthy" if include_probe else
            "FAIL bounded Docker probe module is missing") in receipt
    assert "START Docker Desktop requested" not in receipt
    assert "PRESERVED ephemeral socket directory" not in receipt
