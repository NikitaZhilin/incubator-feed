#!/usr/bin/env bash
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/opt/incubator-feed}"
REPO_URL="${REPO_URL:-https://github.com/NikitaZhilin/incubator-feed.git}"
BRANCH="${BRANCH:-main}"
IMAGE_NAME="${IMAGE_NAME:-incubator-feed:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-incubator-feed-bot}"
LOCK_DIR="${LOCK_DIR:-/tmp/incubator-feed-auto-deploy.lock}"

if [ -z "$DEPLOY_PATH" ] || [ "$DEPLOY_PATH" = "/" ] || [ "$DEPLOY_PATH" = "/opt" ]; then
  echo "Refusing unsafe DEPLOY_PATH: $DEPLOY_PATH" >&2
  exit 1
fi

if mkdir "$LOCK_DIR" 2>/dev/null; then
  trap 'rmdir "$LOCK_DIR"' EXIT
else
  echo "Auto deploy is already running."
  exit 0
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required." >&2
  exit 1
fi

if [ ! -d "$DEPLOY_PATH/.git" ]; then
  mkdir -p "$(dirname "$DEPLOY_PATH")"
  git clone --branch "$BRANCH" "$REPO_URL" "$DEPLOY_PATH"
fi

cd "$DEPLOY_PATH"
git fetch origin "$BRANCH"

current_commit="$(git rev-parse HEAD 2>/dev/null || true)"
target_commit="$(git rev-parse "origin/$BRANCH")"

if [ "$current_commit" = "$target_commit" ]; then
  echo "Already deployed: ${current_commit:0:12}"
  exit 0
fi

echo "Deploying ${target_commit:0:12} over ${current_commit:0:12}"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

mkdir -p data logs backups
docker build -t "$IMAGE_NAME" .
docker run --rm --env-file .env.prod \
  -v "$DEPLOY_PATH/data:/app/data" \
  -v "$DEPLOY_PATH/logs:/app/logs" \
  -v "$DEPLOY_PATH/backups:/app/backups" \
  "$IMAGE_NAME" python -B scripts/migrate.py

release_deployed_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER_NAME" --restart unless-stopped \
  --env-file "$DEPLOY_PATH/.env.prod" \
  -e RELEASE_NOTICE_ENABLED="${AUTO_DEPLOY_RELEASE_NOTICE_ENABLED:-0}" \
  -e RELEASE_IMPORTANCE="${AUTO_DEPLOY_RELEASE_IMPORTANCE:-minor}" \
  -e RELEASE_COMMIT="${target_commit:0:12}" \
  -e RELEASE_DEPLOYED_AT="$release_deployed_at" \
  -v "$DEPLOY_PATH/data:/app/data" \
  -v "$DEPLOY_PATH/logs:/app/logs" \
  -v "$DEPLOY_PATH/backups:/app/backups" \
  "$IMAGE_NAME" python main.py

docker ps --filter "name=$CONTAINER_NAME"
docker logs --tail=80 "$CONTAINER_NAME"
