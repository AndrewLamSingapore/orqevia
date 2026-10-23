"""Focused release identity and executable secret-free checkpoint regression."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_image_includes_stale_shell_recovery_assets():
    source = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    copies = [line for line in source.splitlines() if line.startswith("COPY ") and "./app/pwa_static/" in line]
    for asset in ("reset.html", "reset.mjs"):
        assert any("clients/pwa/" + asset in line.split()[1:-1] for line in copies)


def test_publish_image_uses_canonical_namespace_and_exact_revision():
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish-image.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["publish"]["steps"]
    metadata = next(step for step in steps if step.get("id") == "meta")
    build = next(step for step in steps if "docker/build-push-action@" in step.get("uses", ""))
    assert metadata["with"]["images"] == "ghcr.io/andrewlamsingapore/orqevia"
    assert "ORQEVIA_RUNTIME_REVISION=${{ github.sha }}" in build["with"]["build-args"].splitlines()
    assert build["with"]["provenance"] == "mode=max" and build["with"]["sbom"] is True


def test_checkpoint_and_volume_lookup_never_request_credentials(tmp_path):
    # Parse trusted function definitions only. Never dot-source the operator's
    # top-level start/update switch, never call Docker, never read .env.
    program = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$source=Join-Path (Get-Location) 'scripts/orqevia.ps1'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Operator PowerShell parse failed'}
$names=@('Get-ContainerRows','Get-SafeContainerInventory','Save-Checkpoint','Get-VolumeForContainer')
foreach($name in $names){
 $function=$ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
 if($function.Count -ne 1){throw 'Reviewed function missing'}
 Invoke-Expression $function[0].Extent.Text
}
$script:calls=@()
$script:Checkpoint=$null
$script:messages=@()
function Write-Step([string]$Message) { $script:messages+=,$Message }
# Redirect only the checkpoint base path into pytest's scratch directory.
# The actual Save-Checkpoint implementation is executed unchanged.
function Join-Path {
 param([string]$Path,[string]$ChildPath)
 if($ChildPath -eq 'ORQEVIA\checkpoints'){return $env:ORQEVIA_CHECKPOINT_FIXTURE}
 Microsoft.PowerShell.Management\Join-Path -Path $Path -ChildPath $ChildPath
}
function Invoke-Docker {
 param([string[]]$Arguments,[switch]$AllowFailure)
 $script:calls+=,@($Arguments)
 if(($Arguments -join ' ') -eq 'ps -a --format {{json .}}') {
  return '{"ID":"fixture-container","Names":"orqevia-fixture","Status":"Up","Ports":"","Labels":"com.docker.compose.project=fixture,com.docker.compose.service=backend,unknown=fixture-credential-must-not-be-requested","Command":"fixture-credential-must-not-be-requested"}'
 }
 if(($Arguments -join ' ') -eq 'volume ls'){return 'fixture-data'}
 if(($Arguments -join ' ') -eq 'network ls'){return 'fixture-network'}
 if($Arguments.Count -ne 4 -or $Arguments[0] -ne 'inspect' -or $Arguments[1] -ne '--format'){throw 'Unrestricted Docker inspect attempted'}
 switch -Exact ($Arguments[2]) {
  '{{.Id}}|{{.Name}}|{{.Image}}|{{.State.Status}}' {return ('fixture-container|/orqevia-fixture|sha256:'+('a'*64)+'|running')}
  '{{range .Mounts}}{{.Type}}|{{.Name}}|{{.Destination}}|{{.RW}}{{println}}{{end}}' {return @('volume|fixture-data|/data|true','bind||/run/secrets/provider|false')}
  '{{range .Mounts}}{{.Name}}|{{.Destination}}{{println}}{{end}}' {return @('fixture-data|/data','|/run/secrets/provider')}
  default {throw 'Unapproved inspect projection'}
 }
}
$rows=@(Get-SafeContainerInventory -ContainerIds @('fixture-container'))
if($rows.Count -ne 1 -or $rows[0].Mounts.Count -ne 2){throw 'Checkpoint lost recovery identity'}
if((Get-VolumeForContainer 'fixture-container' '/data') -ne 'fixture-data'){throw 'Data-volume discovery failed'}
if((Get-VolumeForContainer 'fixture-container' '/absent') -ne ''){throw 'Unknown volume became present'}
$json=ConvertTo-Json -InputObject $rows -Depth 6
foreach($forbidden in @('Config','Env','Cmd','Args','Labels','Source','fixture-credential-must-not-be-requested')){
 if($json -match ('"'+$forbidden+'"')){throw 'Unsafe checkpoint field'}
}
if($rows[0].PSObject.Properties.Name.Count -ne 5){throw 'Checkpoint allowlist expanded'}
$checkpoint=Save-Checkpoint
if($checkpoint -ne (Save-Checkpoint)){throw 'Checkpoint was not idempotent'}
$files=@(Get-ChildItem -LiteralPath $checkpoint -File)
if($files.Count -ne 4){throw 'Unexpected checkpoint output files'}
foreach($file in $files){
 $text=Get-Content -LiteralPath $file.FullName -Raw
 if($text -match 'fixture-credential-must-not-be-requested|"Command"|"Config"|"Env"|"Args"'){throw 'Checkpoint leaked credentials'}
}
if(($script:messages -join ' ') -match 'fixture-credential-must-not-be-requested'){throw 'Checkpoint log leaked credentials'}
Write-Output $json
"""
    powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Executable checkpoint fixture requires PowerShell")
    environment = dict(os.environ, ORQEVIA_CHECKPOINT_FIXTURE=str(tmp_path))
    result = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", program],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    assert set(inventory[0]) == {"Id", "Name", "ImageId", "Status", "Mounts"}
    assert inventory[0]["Mounts"][0]["Name"] == "fixture-data"


def test_checkpoint_does_not_store_raw_process_or_compose_configuration():
    source = (ROOT / "scripts/orqevia.ps1").read_text(encoding="utf-8")
    checkpoint = source.split("function Save-Checkpoint {", 1)[1].split("function Get-VolumeForContainer", 1)[0]
    assert '"containers.sanitized.json"' in checkpoint
    assert '"containers.inspect.json"' not in checkpoint
    assert '"ps", "-a", "--no-trunc"' not in checkpoint
    assert '"config"' not in checkpoint
