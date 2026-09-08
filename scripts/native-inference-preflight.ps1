# Read-only startup guard. Absence at preflight is not continuous host isolation.
function Assert-NativeInferenceIsolated {
    try {
        $nativeInferenceProcesses = @(Get-Process -ErrorAction Stop | Where-Object { $_.ProcessName -like 'ollama*' })
        $nativeInferenceListeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object {
            $_.LocalPort -eq 11434 -or $_.OwningProcess -in @($nativeInferenceProcesses | ForEach-Object { $_.Id })
        })
    } catch {
        throw 'HOLD: native inference inventory is unavailable; startup is prohibited.'
    }
    if ($nativeInferenceProcesses.Count -or $nativeInferenceListeners.Count) {
        throw 'HOLD: independent native inference process/listener exists; startup is prohibited. No process was stopped.'
    }
}
