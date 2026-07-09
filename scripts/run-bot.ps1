$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$PidFile = Join-Path $ProjectRoot "bot.pid"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Python = if ($env:BOT_PYTHON) {
    $env:BOT_PYTHON
} elseif (Test-Path $VenvPython) {
    $VenvPython
} else {
    "python"
}

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
$Process.WaitForExit()
$ExitCode = $Process.ExitCode

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
exit $ExitCode
