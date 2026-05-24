$ErrorActionPreference = "Stop"

param(
    [string]$TaskName = "Egg Incubation Telegram Bot"
)

$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $Task) {
    Write-Output "Autostart task not found: $TaskName"
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "Autostart task removed: $TaskName"
