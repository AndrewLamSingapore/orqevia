[CmdletBinding()]
param(
    [string] $ReviewDirectory
)
$ErrorActionPreference = 'Stop'
# Fail closed BEFORE starting Codex or decrypting a credential. A named profile
# and read-only shell do not disable inherited MCP/app/hook/plugin authority.
# No bypass switch or self-attestation marker is accepted.
throw 'BLOCKED: native Codex/DeepSeek launch requires a locally verified effective user/project/managed configuration with inherited mutation-capable MCP, app, hook and plugin paths disabled, plus Windows sandbox validation. Use Start-DeepSeekPacketReview.ps1 for bounded no-tools API review. This launcher never starts Codex or reads a key.'
