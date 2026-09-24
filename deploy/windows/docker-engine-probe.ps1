function Test-DockerEngine(
    [int]$TimeoutMilliseconds = 8000,
    [string]$DockerExe = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
) {
    # Docker CLI can wait indefinitely when Desktop has not created its named
    # pipe. Startup recovery must remain bounded even in that failure mode.
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $DockerExe
    $startInfo.Arguments = 'info --format "{{.ServerVersion}}"'
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { return $false }
        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            $process.Kill()
            $process.WaitForExit()
            return $false
        }
        return $process.ExitCode -eq 0
    } catch {
        return $false
    } finally {
        $process.Dispose()
    }
}
