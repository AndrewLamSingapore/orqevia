import unittest
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


class RuntimeOperationsContractTests(unittest.TestCase):
    def test_windows_browser_navigation_uses_https_and_preserves_private_backend_checks(self):
        powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
        if powershell is None:
            self.skipTest("Executable operator navigation check requires PowerShell")
        # Execute only the reviewed startup function and open switch clause.
        # All Docker/network/process entrypoints are replaced with local fixture
        # commands; this test never starts a browser, reads .env or changes data.
        program = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) 'scripts/orqevia.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Operator PowerShell parse failed'}
foreach($name in @('LocalBase','PublicWorkbench')){
 $assignment=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq ('$'+$name)},$true))
 if($assignment.Count -ne 1){throw 'Operator default assignment is ambiguous'}
 Invoke-Expression $assignment[0].Extent.Text
}
if($LocalBase -ne 'http://127.0.0.1:8000'){throw 'Private backend transport changed'}
$script:opened=@();$script:messages=@();$NoOpen=$false
function Start-Process {param([string]$FilePath) $script:opened+=,$FilePath}
function Write-Host {param([string]$Object,[string]$ForegroundColor) $script:messages+=,$Object}
function Assert-Docker {}
function Invoke-Docker {param([string[]]$Arguments,[switch]$AllowFailure)}
function Get-ComposeArgs {param([object[]]$Arguments,[bool]$UseTunnel) return $Arguments}
function Adopt-PersistentVolumes {}
function Assert-PersistentVolumes {}
function Assert-PortAvailable {}
function Assert-NoConflictingCoreContainers {}
function Resolve-TunnelMode {return $false}
function Get-EnvValue {param([string]$Name) return 'synthetic-pinned-image'}
function Write-Step {param([string]$Message)}
function Wait-ForPrime {}
function Test-PrimeContract {param([switch]$Quiet)}
$start=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-OrqeviaStack'},$true))
if($start.Count -ne 1){throw 'Reviewed startup function missing'}
Invoke-Expression $start[0].Extent.Text
Start-OrqeviaStack
$switch=@($ast.FindAll({param($node) $node -is [System.Management.Automation.Language.SwitchStatementAst] -and $node.Condition.Extent.Text -eq '$Action'},$true))
if($switch.Count -ne 1){throw 'Reviewed operator switch missing'}
$open=@($switch[0].Clauses | Where-Object {$_.Item1.Value -eq 'open'})
if($open.Count -ne 1){throw 'Reviewed open action missing'}
Invoke-Expression ('& '+$open[0].Item2.Extent.Text)
$NoOpen=$true
Start-OrqeviaStack
if($script:opened.Count -ne 2){throw 'Browser opt-out or navigation dispatch changed'}
foreach($url in $script:opened){if($url -ne 'https://localhost:8443/pwa/'){throw 'Browser target is not the HTTPS workspace'}}
if(@($script:messages | Where-Object {$_ -eq 'ORQEVIA READY - https://localhost:8443/pwa/'}).Count -ne 2){throw 'Ready output is not the HTTPS workspace'}
ConvertTo-Json -Compress @{opened=$script:opened;private_api=$LocalBase;no_open_preserved=$true}
"""
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", program],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["opened"], ["https://localhost:8443/pwa/"] * 2)
        self.assertTrue(receipt["no_open_preserved"])
        self.assertEqual(receipt["private_api"], "http://127.0.0.1:8000")

    def test_backend_healthcheck_authenticates_without_embedding_a_secret(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        healthcheck = next(line for line in compose.splitlines() if "urllib.request.Request" in line)
        self.assertIn("os.environ['ORQEVIA_SPINE_TOKEN']", healthcheck)
        self.assertIn("'Authorization': 'Bearer ' +", healthcheck)
        self.assertNotIn("${ORQEVIA_SPINE_TOKEN}", healthcheck)

    def test_compose_is_one_stable_local_project(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("name: ${COMPOSE_PROJECT_NAME:-orqevia}", compose)
        self.assertIn('${ORQEVIA_BIND_ADDRESS:-127.0.0.1}', compose)
        self.assertIn('com.orqevia.managed: "true"', compose)
        self.assertIn("${ORQEVIA_DATA_VOLUME:-orqevia-data}", compose)
        self.assertIn("${OLLAMA_DATA_VOLUME:-orqevia-ollama-data}", compose)
        self.assertNotIn("com.lamjarvis", compose)
        self.assertNotIn("prime:local", compose)
        self.assertIn("\n  backend:\n", compose)
        self.assertIn("ORQEVIA-ABEX-HTTPS.mobileconfig", compose)
        self.assertEqual(compose.count("external: true"), 2)

    def test_windows_operator_preserves_data_and_checks_every_surface(self):
        script = (ROOT / "scripts" / "orqevia.ps1").read_text(encoding="utf-8")
        self.assertIn("Save-Checkpoint", script)
        self.assertIn("Adopt-PersistentVolumes", script)
        self.assertIn("Assert-PersistentVolumes", script)
        self.assertIn("Assert-NoConflictingCoreContainers", script)
        self.assertIn("will not create a blank replacement", script)
        self.assertNotIn('volume", "rm"', script)
        self.assertNotIn('Invoke-Docker -Arguments @("rm"', script)
        for path in ("/health", "/control", "/api/control-surface/manifest", "/api/status"):
            self.assertIn(path, script)

    def test_public_gateway_never_exposes_control_surface(self):
        script = (ROOT / "scripts" / "orqevia.ps1").read_text(encoding="utf-8")
        self.assertIn('foreach ($path in @("/control", "/api/status", "/api/control-surface/manifest"))', script)
        self.assertIn("HTTP 404", script)

    def test_one_click_menu_covers_lifecycle(self):
        menu = (ROOT / "ORQEVIA.cmd").read_text(encoding="utf-8")
        for action in ("start", "status", "doctor", "repair", "open", "stop"):
            self.assertIn(f"-Action {action}", menu)

    def test_recovery_sensitive_helpers_fail_closed(self):
        bootstrap = (ROOT / "scripts" / "bootstrap_connected_loop.ps1").read_text(encoding="utf-8")
        trace = (ROOT / "scripts" / "enable-public-trace.ps1").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("InitializeNewTrustEpoch", bootstrap)
        self.assertIn("will not create replacement state", bootstrap)
        self.assertNotIn("RotateTokens", bootstrap)
        self.assertIn("ApplyRestart", trace)
        self.assertIn("source secret file was preserved", trace)
        self.assertNotIn("Remove-Item", trace)
        self.assertNotIn(":latest", compose)

    def test_direct_runtime_enables_registry_dispatch(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("ORQEVIA_REGISTRY_V1_ENABLED: ${ORQEVIA_REGISTRY_V1_ENABLED:-1}", compose)
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("ORQEVIA_REGISTRY_V1_ENABLED=1", example)

    def test_hf_overlay_mounts_only_governed_read_only_inputs_to_backend(self):
        overlay = (ROOT / "docker-compose.huggingface.yml").read_text(encoding="utf-8")
        self.assertIn("ORQEVIA_PROVIDER_CATALOG: /run/orqevia-models/huggingface.json", overlay)
        self.assertIn("ORQEVIA_HF_PROVIDER_CATALOG_FILE:-./config/provider-catalog.huggingface.example.json", overlay)
        self.assertIn("read_only: true", overlay)
        self.assertIn("ORQEVIA_HF_TOKEN_FILE", overlay)
        self.assertNotIn("interface:", overlay)
        self.assertNotIn("HF_TOKEN:", overlay)  # No raw credential environment interpolation.

    def test_survival_probes_and_executor_are_explicitly_wired(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        for name in ("ORQEVIA_SURVIVAL_NETWORK_PROBE_URL", "ORQEVIA_SURVIVAL_CLOUD_PROBE_URL",
                     "ORQEVIA_SURVIVAL_FETCH_ALLOWLIST", "ORQEVIA_SURVIVAL_AUTHORITY_REF"):
            self.assertIn(name + ": ${" + name, compose)

    def test_image_starts_canonical_owner_entrypoint_without_proxy_trust(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('"app.production_entry:app"', dockerfile)
        self.assertIn('"--no-proxy-headers"', dockerfile)
        self.assertGreater(dockerfile.index("ARG ORQEVIA_RUNTIME_REVISION"),
                           dockerfile.index("RUN pip install"))

    def test_container_owner_peer_is_explicit_not_a_network_wildcard(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("ORQEVIA_OWNER_TRUSTED_PEERS: ${ORQEVIA_OWNER_TRUSTED_PEERS:-}", compose)

    def test_owner_account_reaches_pairing_authority_and_client_interface(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        backend, interface = compose.split("  interface:", 1)
        setting = "ORQEVIA_PWA_OWNER_ACCOUNT_ID: ${ORQEVIA_PWA_OWNER_ACCOUNT_ID:-}"
        self.assertIn(setting, backend)
        self.assertIn(setting, interface)
        self.assertEqual(compose.count(setting), 2)

    def test_physical_client_runtime_is_https_narrow_and_profile_gated(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('profiles: ["clients"]', compose)
        self.assertIn('app.interface_server:app', compose)
        self.assertIn('"--no-proxy-headers"', compose)
        self.assertIn('"--ssl-keyfile"', compose)
        self.assertIn('${ORQEVIA_INTERFACE_BIND_ADDRESS:-127.0.0.1}', compose)
        self.assertNotIn('app.production_entry:app", "--host", "0.0.0.0", "--port", "8443"', compose)
        self.assertIn('COPY clients/pwa/index.html', dockerfile)
        self.assertIn('ORQEVIA_INTERFACE_RUNTIME_VERSION: ${ORQEVIA_INTERFACE_RUNTIME_VERSION:-UNKNOWN}', compose)
        self.assertIn('ORQEVIA_INTERFACE_CANDIDATE_STATUS: ${ORQEVIA_INTERFACE_CANDIDATE_STATUS:-UNKNOWN}', compose)

    def test_container_packages_every_required_pwa_startup_asset(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        for asset in ("index.html", "recovery.js", "release.mjs", "app.mjs", "sw.js"):
            self.assertIn(f"clients/pwa/{asset}", dockerfile)


if __name__ == "__main__":
    unittest.main()
