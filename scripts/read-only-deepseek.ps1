<#
.SYNOPSIS
    READ ONLY DeepSeek handoff: ask DeepSeek to read repository content and answer
    questions, explain bugs, review changes or propose patches.

.DESCRIPTION
    This helper is deliberately read-only and cannot modify anything:

      * it only reads files inside -RepoPath;
      * it refuses secret-like paths (.env, keys, tokens, credential stores, the
        Codex config that holds the API key);
      * it never writes, moves or deletes files;
      * it never runs git commit/push, never runs a shell command from the model,
        and never turns model output into an action;
      * it sends text to the DeepSeek API using the existing persistent Codex
        DeepSeek configuration, and never prints the API key.

    The API key is read from the existing Codex config at
    $env:USERPROFILE\.codex\config.toml ([model_providers.deepseek]). No key is
    stored in this script or in the repository.

.EXAMPLE
    .\scripts\read-only-deepseek.ps1 -Question "Explain what scripts/check_status_authority.py does."

.EXAMPLE
    .\scripts\read-only-deepseek.ps1 -Path scripts/check_canonical_state.py,STATUS.md -Question "Review these two files for contradictions."

.EXAMPLE
    .\scripts\read-only-deepseek.ps1 -Question "anything" -DryRun
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Question,
    [string]$RepoPath = (Get-Location).Path,
    [string[]]$Path = @(),
    [int]$MaxFiles = 8,
    [int]$MaxCharsPerFile = 6000,
    [string]$Model = 'deepseek-flash',
    [string]$ConfigPath = (Join-Path $env:USERPROFILE '.codex\config.toml'),
    [int]$TimeoutSeconds = 180,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoPath = (Resolve-Path -LiteralPath $RepoPath).Path

function Get-DeepSeekEndpoint {
    param([string]$ConfigFile)
    if (-not (Test-Path -LiteralPath $ConfigFile)) { throw "Codex config not found: $ConfigFile" }
    $text = Get-Content -LiteralPath $ConfigFile -Raw
    $section = [regex]::Match($text, '(?ms)^\[model_providers\.deepseek\]\s*(.*?)(?=^\[|\z)')
    if (-not $section.Success) { throw "No [model_providers.deepseek] section in $ConfigFile" }
    $body = $section.Groups[1].Value
    $base = [regex]::Match($body, 'base_url\s*=\s*"([^"]+)"')
    $token = [regex]::Match($body, 'experimental_bearer_token\s*=\s*"([^"]+)"')
    if (-not $base.Success) { throw 'No base_url in the deepseek provider section.' }
    if (-not $token.Success) { throw 'No experimental_bearer_token in the deepseek provider section.' }
    [pscustomobject]@{
        BaseUrl = $base.Groups[1].Value.TrimEnd('/')
        Token   = $token.Groups[1].Value
    }
}

function Test-SecretLikePath {
    param([string]$RelativePath)
    if ($RelativePath -match '(?i)(^|[\\/])\.git([\\/]|$)') { return $true }
    $leaf = Split-Path -Leaf $RelativePath
    if ($leaf -match '(?i)^\.env($|\.)|(?i)\.(pem|key|pfx|p12)$|(?i)^id_(rsa|ed25519)|(?i)credential|(?i)secret|(?i)auth\.json|(?i)hosts\.yml|(?i)config\.toml$') { return $true }
    return $false
}

function Get-RepoFileText {
    param([string]$FullPath)
    try {
        # -Encoding UTF8 is required: Windows PowerShell defaults to the ANSI code
        # page, which would corrupt UTF-8 repository content before it is sent.
        return (Get-Content -LiteralPath $FullPath -Raw -Encoding UTF8 -ErrorAction Stop)
    } catch {
        return "<unreadable or binary file: $([IO.Path]::GetFileName($FullPath))>"
    }
}

$targets = [System.Collections.Generic.List[string]]::new()
if ($Path.Count -gt 0) {
    foreach ($p in $Path) { $targets.Add($p) }
} else {
    foreach ($candidate in @('STATUS.md', 'README.md', 'AGENTS.md')) {
        if (Test-Path -LiteralPath (Join-Path $RepoPath $candidate)) { $targets.Add($candidate) }
    }
    if ($targets.Count -eq 0) { throw 'No default status/README files found. Use -Path to name the files to review.' }
}

$bundle = [System.Collections.Generic.List[string]]::new()
$sizes = [System.Collections.Generic.List[string]]::new()
foreach ($rel in $targets | Select-Object -First $MaxFiles) {
    if (Test-SecretLikePath -RelativePath $rel) {
        Write-Warning "Refused secret-like path: $rel"
        continue
    }
    $full = [IO.Path]::GetFullPath((Join-Path $RepoPath $rel))
    if (-not $full.StartsWith($RepoPath, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Warning "Refused path outside the repository: $rel"
        continue
    }
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        Write-Warning "Not a file: $rel"
        continue
    }
    $content = Get-RepoFileText -FullPath $full
    if ($content.Length -gt $MaxCharsPerFile) { $content = $content.Substring(0, $MaxCharsPerFile) + "`n[truncated]" }
    $bundle.Add("----- FILE: $rel -----`n$content")
    $sizes.Add("$rel ($($content.Length) chars)")
}

if ($bundle.Count -eq 0) { throw 'Nothing to send: every candidate path was refused or missing.' }

$systemPrompt = @'
You are operating in READ-ONLY REVIEW MODE for Lam's JARVIS/PRIME repositories.
Your reply is advisory text for a human. You have no ability to act.

Hard constraints on you:
- Do not modify, create, move or delete files. Do not claim that you have.
- Do not run commands, do not commit, do not push, do not open network sessions.
- Do not request or reveal secrets, API keys, tokens or credentials.
- Do not propose destructive or irreversible operations.

You may: read the supplied content, inspect and analyse code, explain bugs,
review diffs or designs, propose patches as text/diff for a human to apply, and
answer architecture questions. Clearly separate what the supplied source shows
from what you are inferring, and say when evidence is missing.
'@

$userPrompt = @"
REPOSITORY: $RepoPath

QUESTION:
$Question

SUPPLIED READ-ONLY CONTENT ($($bundle.Count) file(s): $($sizes -join ', ')):

$($bundle -join "`n`n")
"@

if ($DryRun) {
    Write-Host 'READ-ONLY DeepSeek handoff - DRY RUN (no API call made)'
    Write-Host "Endpoint  : (resolved from $ConfigPath)"
    Write-Host "Model     : $Model"
    Write-Host "Repo      : $RepoPath"
    Write-Host "Files     : $($sizes -join ', ')"
    Write-Host "Prompt    : $($userPrompt.Length) chars"
    return
}

$cfg = Get-DeepSeekEndpoint -ConfigFile $ConfigPath
$body = @{
    model       = $Model
    messages    = @(
        @{ role = 'system'; content = $systemPrompt },
        @{ role = 'user'; content = $userPrompt }
    )
    stream      = $false
} | ConvertTo-Json -Depth 6

# Windows PowerShell encodes string bodies as Latin-1, which turns UTF-8 characters
# (for example the em dash in STATUS.md) into invalid code points and the API rejects
# the request with HTTP 400. Send explicit UTF-8 bytes instead.
$payload = [System.Text.Encoding]::UTF8.GetBytes($body)

# Note: no temperature/top_p/max_tokens are sent. The configured DeepSeek model is
# a reasoning model on this endpoint and rejects sampling parameters with HTTP 400,
# and a small max_tokens can consume the whole budget as reasoning tokens and return
# an empty answer.

Write-Host "READ-ONLY DeepSeek handoff -> $($cfg.BaseUrl) model=$Model files=$($bundle.Count)" -ForegroundColor Cyan
try {
    $response = Invoke-RestMethod -Uri "$($cfg.BaseUrl)/chat/completions" -Method Post `
        -Headers @{ Authorization = "Bearer $($cfg.Token)" } `
        -ContentType 'application/json; charset=utf-8' -Body $payload -TimeoutSec $TimeoutSeconds
} catch {
    Write-Error "DeepSeek request failed: $($_.Exception.Message) $($_.ErrorDetails.Message)"
    return
}

Write-Host ''
$answer = $response.choices[0].message.content
if ([string]::IsNullOrWhiteSpace($answer) -and $response.choices[0].message.reasoning_content) {
    Write-Warning 'Model returned reasoning only (no final answer text). Showing reasoning content.'
    $answer = $response.choices[0].message.reasoning_content
}
Write-Host $answer
Write-Host ''
Write-Host "--- read-only review complete | model=$($response.model) | tokens(in/out)=$($response.usage.prompt_tokens)/$($response.usage.completion_tokens) ---" -ForegroundColor DarkGray
