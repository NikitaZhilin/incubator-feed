param(
    [Parameter(Mandatory = $true)]
    [string]$SshTarget,

    [int]$Port = 22,

    [string]$DeployPath = "/opt/incubator-feed",

    [string]$RepoUrl = "https://github.com/NikitaZhilin/incubator-feed.git",

    [string]$Branch = "main",

    [string]$EnvFile = ".env.prod"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw "ssh was not found in PATH."
}

if (-not (Get-Command scp -ErrorAction SilentlyContinue)) {
    throw "scp was not found in PATH."
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Production env file was not found: $EnvFile. Create it from .env.prod.example and keep it out of Git."
}

if ([string]::IsNullOrWhiteSpace($DeployPath) -or $DeployPath -eq "/" -or $DeployPath -eq "/opt") {
    throw "Refusing unsafe DeployPath: $DeployPath"
}

function ConvertTo-ShellSingleQuoted {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "'\''") + "'"
}

$quotedDeployPath = ConvertTo-ShellSingleQuoted $DeployPath
$quotedRepoUrl = ConvertTo-ShellSingleQuoted $RepoUrl
$quotedBranch = ConvertTo-ShellSingleQuoted $Branch

$prepareCommand = @"
set -e
DEPLOY_PATH=$quotedDeployPath
REPO_URL=$quotedRepoUrl
BRANCH=$quotedBranch
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required on the VPS." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required on the VPS." >&2
  exit 1
fi
if [ -d "`$DEPLOY_PATH/.git" ]; then
  git -C "`$DEPLOY_PATH" fetch origin "`$BRANCH"
  git -C "`$DEPLOY_PATH" checkout "`$BRANCH"
  git -C "`$DEPLOY_PATH" reset --hard "origin/`$BRANCH"
else
  mkdir -p "`$(dirname "`$DEPLOY_PATH")"
  git clone --branch "`$BRANCH" "`$REPO_URL" "`$DEPLOY_PATH"
fi
mkdir -p "`$DEPLOY_PATH/data" "`$DEPLOY_PATH/logs" "`$DEPLOY_PATH/backups"
"@

ssh -p $Port $SshTarget $prepareCommand
scp -P $Port $EnvFile "$SshTarget`:$DeployPath/.env.prod"

$runCommand = @"
set -e
cd $quotedDeployPath
docker compose build
docker compose run --rm bot python -B scripts/migrate.py
docker compose up -d bot
docker compose ps
docker compose logs --tail=80 bot
"@

ssh -p $Port $SshTarget $runCommand
