$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot "bot.pid"

if (-not (Test-Path $PidFile)) {
    Write-Output "bot.pid not found. Nothing to stop."
    exit 0
}

$PidValue = [int](Get-Content -Raw -LiteralPath $PidFile)
$Process = Get-Process -Id $PidValue -ErrorAction SilentlyContinue

if ($Process) {
    Stop-Process -Id $PidValue -Force
    Write-Output "Bot stopped. PID: $PidValue"
} else {
    Write-Output "Process from bot.pid is not running. PID: $PidValue"
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
