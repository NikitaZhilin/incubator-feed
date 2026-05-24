$ErrorActionPreference = "Stop"

param(
    [string]$TaskName = "Egg Incubation Telegram Bot"
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RunScript = Join-Path $PSScriptRoot "run-bot.ps1"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Telegram bot autostart" `
    -Force | Out-Null

Write-Output "Autostart task installed: $TaskName"
