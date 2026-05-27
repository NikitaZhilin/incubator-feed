param(
    [Parameter(Mandatory = $true)]
    [string]$SshTarget,

    [int]$Port = 22,

    [string]$DeployPath = "/opt/incubator-feed",

    [string]$RepoUrl = "https://github.com/NikitaZhilin/incubator-feed.git",

    [string]$Branch = "main",

    [string]$EnvFile = ".env.prod",

    [string]$ImageName = "incubator-feed:latest",

    [string]$ContainerName = "incubator-feed-bot",

    [string]$WebContainerName = "incubator-feed-web",

    [string]$ReleaseVersion = "",

    [string]$ReleaseNotes = "",

    [string]$ReleaseImportance = "major",

    [switch]$AnnounceRelease,

    [switch]$SkipReleaseNotice
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

$quotedImageName = ConvertTo-ShellSingleQuoted $ImageName
$quotedContainerName = ConvertTo-ShellSingleQuoted $ContainerName
$quotedWebContainerName = ConvertTo-ShellSingleQuoted $WebContainerName

if ($AnnounceRelease -and -not $SkipReleaseNotice) {
    $releaseNoticeEnabled = "1"
    if ([string]::IsNullOrWhiteSpace($ReleaseVersion)) {
        $commitCount = ""
        try {
            $commitCount = (git rev-list --count HEAD 2>$null).Trim()
        } catch {
            $commitCount = ""
        }
        if ([string]::IsNullOrWhiteSpace($commitCount)) {
            $commitCount = (Get-Date -Format 'yyyyMMddHHmm')
        }
        $ReleaseVersion = "0.1.$commitCount-beta"
    }

    if ([string]::IsNullOrWhiteSpace($ReleaseNotes)) {
        try {
            $ReleaseNotes = (git log -1 --pretty=%s 2>$null).Trim()
        } catch {
            $ReleaseNotes = ""
        }
    }
} else {
    $releaseNoticeEnabled = "0"
    $ReleaseVersion = ""
    $ReleaseNotes = ""
    $ReleaseImportance = "minor"
}

$quotedReleaseNoticeEnabled = ConvertTo-ShellSingleQuoted $releaseNoticeEnabled
$quotedReleaseVersion = ConvertTo-ShellSingleQuoted $ReleaseVersion
$quotedReleaseNotes = ConvertTo-ShellSingleQuoted $ReleaseNotes
$quotedReleaseImportance = ConvertTo-ShellSingleQuoted $ReleaseImportance

$runCommand = @"
set -e
cd $quotedDeployPath
IMAGE_NAME=$quotedImageName
CONTAINER_NAME=$quotedContainerName
WEB_CONTAINER_NAME=$quotedWebContainerName
RELEASE_NOTICE_ENABLED=$quotedReleaseNoticeEnabled
RELEASE_VERSION=$quotedReleaseVersion
RELEASE_NOTES=$quotedReleaseNotes
RELEASE_IMPORTANCE=$quotedReleaseImportance
RELEASE_COMMIT=`$(git rev-parse --short=12 HEAD 2>/dev/null || true)
RELEASE_DEPLOYED_AT=`$(date -u +"%Y-%m-%dT%H:%M:%SZ")
docker build -t "`$IMAGE_NAME" .
docker run --rm --env-file .env.prod \
  -v "$DeployPath/data:/app/data" \
  -v "$DeployPath/logs:/app/logs" \
  -v "$DeployPath/backups:/app/backups" \
  "`$IMAGE_NAME" python -B scripts/migrate.py
docker rm -f "`$CONTAINER_NAME" >/dev/null 2>&1 || true
docker rm -f "`$WEB_CONTAINER_NAME" >/dev/null 2>&1 || true
docker network inspect incubator_feed_network >/dev/null 2>&1 || docker network create incubator_feed_network
docker run -d --name "`$CONTAINER_NAME" --restart unless-stopped \
  --network incubator_feed_network \
  --env-file "$DeployPath/.env.prod" \
  -e RELEASE_NOTICE_ENABLED="`$RELEASE_NOTICE_ENABLED" \
  -e RELEASE_VERSION="`$RELEASE_VERSION" \
  -e RELEASE_NOTES="`$RELEASE_NOTES" \
  -e RELEASE_IMPORTANCE="`$RELEASE_IMPORTANCE" \
  -e RELEASE_COMMIT="`$RELEASE_COMMIT" \
  -e RELEASE_DEPLOYED_AT="`$RELEASE_DEPLOYED_AT" \
  -v "$DeployPath/data:/app/data" \
  -v "$DeployPath/logs:/app/logs" \
  -v "$DeployPath/backups:/app/backups" \
  "`$IMAGE_NAME" python main.py
docker run -d --name "`$WEB_CONTAINER_NAME" --restart unless-stopped \
  --network incubator_feed_network \
  --env-file "$DeployPath/.env.prod" \
  -e WEB_ENABLED=true \
  -e WEB_HOST=0.0.0.0 \
  -e WEB_PORT=8080 \
  -p 127.0.0.1:8080:8080 \
  -v "$DeployPath/data:/app/data:ro" \
  "`$IMAGE_NAME" python -B scripts/web_app.py
docker ps --filter "name=`$CONTAINER_NAME"
docker ps --filter "name=`$WEB_CONTAINER_NAME"
docker logs --tail=80 "`$CONTAINER_NAME"
docker logs --tail=50 "`$WEB_CONTAINER_NAME"
"@

ssh -p $Port $SshTarget $runCommand
