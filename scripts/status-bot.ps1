$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot "bot.pid"

if (-not (Test-Path $PidFile)) {
    Write-Output "Bot status: unknown/not started by scripts. bot.pid not found."
    exit 1
}

$PidValue = [int](Get-Content -Raw -LiteralPath $PidFile)
$Process = Get-Process -Id $PidValue -ErrorAction SilentlyContinue

if ($Process) {
    Write-Output "Bot status: running. PID: $PidValue"
    exit 0
}

Write-Output "Bot status: stopped. Stale PID: $PidValue"
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
exit 1
