# Exercise only the selected operator functions with mocked services.
$ErrorActionPreference = "Stop"
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot "jarvis.ps1"), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw "Operator parse failed." }
foreach ($name in @("Submit-Intent", "Restart-Jarvis", "Save-Checkpoint")) {
    $node = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true)
    . ([scriptblock]::Create($node.Extent.Text))
}
$LocalBase = "http://127.0.0.1:8000"
$TimeoutSeconds = 30
$Intent = "calculate 2+2"
$script:posts = 0
$script:mode = "exact"
function Get-EnvValue { return "fixture-token" }
function Write-Host {}
function Start-Sleep {}
function Invoke-RestMethod {
    param($Method, $Uri, $Headers, $ContentType, $Body, $TimeoutSec)
    if ($Headers.Authorization -ne "Bearer fixture-token") { throw "Missing owner authentication." }
    if ($Method -eq "Post") {
        $script:posts++
        $request = [Text.Encoding]::UTF8.GetString($Body) | ConvertFrom-Json
        if (-not $request.idempotency_key -or $request.idempotency_key -ne $request.correlation_id) { throw "Missing request identity." }
        if ($script:mode -eq "timeout") { throw "Simulated lost response." }
        if ($script:mode -eq "exact") { return [pscustomobject]@{result="4"} }
        return [pscustomobject]@{job=[pscustomobject]@{id="fixture-work"}}
    }
    return [pscustomobject]@{status="completed";result="advisory"}
}
Submit-Intent
if ($script:posts -ne 1) { throw "Expected one request." }
$script:mode = "queued"
Submit-Intent
if ($script:posts -ne 2) { throw "Polling resubmitted work." }
$script:mode = "timeout"
$rejected = $false
try { Submit-Intent } catch { $rejected = $true }
if (-not $rejected -or $script:posts -ne 3) { throw "Ambiguous response must not retry." }

$script:state = "SAFE_STOP"
$script:pending = 0
$script:starts = 0
$script:stops = 0
function Get-Json { return [pscustomobject]@{state=$script:state;work_available=$true;work=[pscustomobject]@{queued=$script:pending}} }
function Assert-NativeInferenceIsolated {}
function Assert-Docker {}
function Get-ComposeArgs { param($ArgsList) return $ArgsList }
function Invoke-Docker { $script:stops++ }
function Start-Jarvis { $script:starts++ }
$rejected = $false
try { Restart-Jarvis } catch { $rejected = $true }
if (-not $rejected -or $script:starts -or $script:stops) { throw "Unsafe state restarted." }
$script:state = "HEALTHY"
$script:pending = 1
$rejected = $false
try { Restart-Jarvis } catch { $rejected = $true }
if (-not $rejected -or $script:starts -or $script:stops) { throw "Pending work restarted." }
$script:pending = 0
Restart-Jarvis
if ($script:starts -ne 1 -or $script:stops -ne 1) { throw "Idle restart did not use existing operator." }
Write-Output "PASS: exact result, queued result, authenticated single submission, ambiguous-response no-retry, guarded restart."

# Mock filesystem writes as well as Docker; this fixture creates no checkpoint.
$script:Checkpoint = $null
$script:saved = @{}
function New-Item { param($ItemType, [switch]$Force, $Path) }
function Write-Step {}
function Set-Content {
    param([Parameter(Position=0)]$Path, [Parameter(ValueFromPipeline=$true)]$Value)
    process { $script:saved[$Path] = @($script:saved[$Path]) + $Value }
}
function Get-ContainerRows { param([switch]$All) return [pscustomobject]@{Id="fixture-container"} }
function Invoke-Docker {
    param([string[]]$Arguments, [switch]$AllowFailure)
    if ($Arguments[0] -eq "inspect") {
        if ($Arguments.Count -ne 4 -or $Arguments[1] -ne "--format" -or
            $Arguments[2] -ne '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},"mounts":{{json .Mounts}}}') {
            throw "Checkpoint inspection could expose secret configuration."
        }
        return '{"id":"fixture","image":"sha256:fixture","mounts":[]}'
    }
    if ($Arguments[0] -eq "ps" -and ($Arguments -notcontains "--format" -or
        $Arguments[-1] -ne '{{.ID}} {{.Image}} {{.Status}} {{.Names}}')) {
        throw "Checkpoint listing could expose command arguments."
    }
    return "fixture inventory"
}
Save-Checkpoint | Out-Null
if ($script:saved.Count -ne 4 -or -not ($script:saved.Keys | Where-Object { $_ -like '*containers.recovery.jsonl' })) {
    throw "Sanitized recovery inventory was not saved."
}
Write-Output "PASS: recovery inventory excludes container environment and command arguments."
