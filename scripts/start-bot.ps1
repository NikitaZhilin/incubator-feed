$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot "bot.pid"
$Python = if ($env:BOT_PYTHON) { $env:BOT_PYTHON } else { "python" }

if (Test-Path $PidFile) {
    $ExistingPid = [int](Get-Content -Raw -LiteralPath $PidFile)
    $Existing = Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue
    if ($Existing) {
        Write-Output "Bot is already running. PID: $ExistingPid"
        exit 0
    }
}

$Process = Start-Process `
    -FilePath $Python `
    -ArgumentList @("main.py") `
    -WindowStyle Hidden `
    -WorkingDirectory $ProjectRoot `
    -PassThru

$Process.Id | Out-File -Encoding ascii -FilePath $PidFile
Start-Sleep -Seconds 2
$Process.Refresh()
if ($Process.HasExited) {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Write-Output "Bot failed to stay running. Exit code: $($Process.ExitCode)"
    exit $Process.ExitCode
}
Write-Output "Bot started. PID: $($Process.Id)"
