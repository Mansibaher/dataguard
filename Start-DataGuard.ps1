param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot

function Test-DockerEngine {
    $probe = New-Object System.Diagnostics.Process
    $probe.StartInfo.FileName = 'docker.exe'
    $probe.StartInfo.Arguments = 'version --format "{{.Server.Version}}"'
    $probe.StartInfo.UseShellExecute = $false
    $probe.StartInfo.CreateNoWindow = $true
    $probe.StartInfo.RedirectStandardOutput = $true
    $probe.StartInfo.RedirectStandardError = $true
    try {
        [void]$probe.Start()
        if (-not $probe.WaitForExit(4000)) {
            $probe.Kill()
            return $false
        }
        return ($probe.ExitCode -eq 0)
    } catch { return $false } finally { $probe.Dispose() }
}

function Wait-DockerEngine {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerEngine) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

$dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
if (-not (Test-DockerEngine)) {
    Write-Host 'Starting Docker Desktop...'
    $startedAt = Get-Date
    Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
    if (-not (Wait-DockerEngine)) {
        $logPath = Join-Path $env:LOCALAPPDATA 'Docker\log\host\com.docker.backend.exe.log'
        $log = Get-Item -LiteralPath $logPath -ErrorAction SilentlyContinue
        $knownFailure = $log -and $log.LastWriteTime -ge $startedAt -and
            ((Get-Content -LiteralPath $logPath -Tail 250) -match 'backend cancelling with error:.*(Inference manager|Secrets Engine).*The file cannot be accessed')
        if (-not $knownFailure) {
            throw 'Docker did not become ready. Open Docker Desktop to inspect its error; no settings or data were reset.'
        }
        # Only repair the diagnosed runtime-socket failure while the engine is down.
        Write-Host 'Repairing blocked temporary communication folders. Existing folders are preserved as backups.'
        Get-Process -Name 'Docker Desktop','com.docker.backend' -ErrorAction SilentlyContinue | Stop-Process
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
        foreach ($target in @((Join-Path $env:LOCALAPPDATA 'Docker\run'), (Join-Path $env:LOCALAPPDATA 'docker-secrets-engine'))) {
            if (Test-Path -LiteralPath $target) {
                $directory = Get-Item -LiteralPath $target -Force
                if ($directory.FullName -ne [IO.Path]::GetFullPath($target)) { throw 'Unexpected runtime folder path' }
                Rename-Item -LiteralPath $directory.FullName -NewName ($directory.Name + '.backup-' + $stamp)
            }
        }
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        if (-not (Wait-DockerEngine)) { throw 'Docker still could not start. Backups are preserved; no volumes were removed.' }
    }
}

Push-Location $repoRoot
try {
    Write-Host 'Starting DataGuard...'
    docker compose up -d --wait --wait-timeout 90
    if ($LASTEXITCODE -ne 0) { throw 'DataGuard startup failed. Run docker compose logs to inspect the failing service.' }
    $ready = $false
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        try {
            $api = Invoke-RestMethod -Uri 'http://localhost:8001/health' -TimeoutSec 3
            $page = Invoke-WebRequest -Uri 'http://localhost:3000' -UseBasicParsing -TimeoutSec 3
            if ($api.status -eq 'ok' -and $page.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $ready) { throw 'Containers started but the app did not become ready.' }
    Write-Host 'DataGuard is ready: http://localhost:3000'
    if (-not $NoBrowser) { Start-Process 'http://localhost:3000' }
} finally { Pop-Location }
