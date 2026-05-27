param(
    [int]$Port = 8080,
    [string]$Url = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$LocalUrl = "http://127.0.0.1:$Port"

if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    throw "ngrok is not installed or not available in PATH."
}

$env:WEB_ENABLED = "true"
$env:WEB_HOST = "127.0.0.1"
$env:WEB_PORT = [string]$Port

Write-Host "Starting web service on $LocalUrl ..."
$webProcess = Start-Process `
    -FilePath "python" `
    -ArgumentList @("-B", "scripts\web_app.py") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -PassThru

try {
    Start-Sleep -Seconds 3
    try {
        Invoke-RestMethod -Uri "$LocalUrl/health" -TimeoutSec 5 | Out-Null
    }
    catch {
        throw "Web service did not answer on $LocalUrl. Check WEB_ENABLED, dependencies and logs."
    }

    if ($Url.Trim()) {
        Write-Host "Starting ngrok tunnel with reserved URL $Url ..."
        & ngrok http --url=$Url $LocalUrl
    }
    else {
        Write-Host "Starting ngrok tunnel. Copy the public https URL into WEB_PUBLIC_URL."
        & ngrok http $LocalUrl
    }
}
finally {
    if ($webProcess -and -not $webProcess.HasExited) {
        Stop-Process -Id $webProcess.Id -Force
    }
}
