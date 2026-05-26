# Deployment

This project supports two deployment paths:

- automatic GitHub Actions deployment on every push to `main`;
- manual deployment from this workstation with `scripts/deploy-vps.ps1`.

Secrets must never be committed. Keep the Telegram token only in GitHub
Secrets and/or in the VPS `.env.prod` file.

## GitHub repository

Use this remote:

```bash
git remote add origin https://github.com/NikitaZhilin/incubator-feed.git
git branch -M main
git push -u origin main
```

## GitHub Actions secrets

Create these repository secrets in GitHub:

```text
BOT_TOKEN=Telegram bot token
ADMIN_IDS=comma-separated Telegram admin IDs, optional
VPS_HOST=server host or IP
VPS_USER=SSH user, for example root
VPS_PORT=22
VPS_SSH_KEY=private SSH key allowed to connect to the VPS
```

Optional repository variable:

```text
DEPLOY_PATH=/opt/incubator-feed
```

The workflow updates the project on the VPS, writes `.env.prod` from GitHub
Secrets, runs migrations, rebuilds the Docker image, and starts the bot as a
Docker container with `--restart unless-stopped`.

Regular deploys are silent for users. Version, GitHub and changelog links are
available in Telegram under `Настройки -> О боте`. A release notice is sent only
when it is explicitly enabled. `medium` sends a short "bot was updated and
restarted" message with the main menu; `major` and `critical` also include
release notes. The notice is deduplicated in `notification_log` by release
version, so re-running or restarting the same version does not send the same
update twice.

For a manual GitHub Actions run you can fill:

```text
release_version=0.1.42-beta
release_notes=Добавлена ссылка на web-версию; Web-ключ теперь удобно копируется
```

The main bot process sends this notice on startup only when
`RELEASE_NOTICE_ENABLED=1` and `RELEASE_IMPORTANCE` is `medium`, `major`, or
`critical`. The version should be a numeric beta version, for example
`0.1.42-beta`.

## Manual VPS deploy

Create local `.env.prod` from `.env.prod.example` and fill in production values.
The file is ignored by Git.

```powershell
Copy-Item .env.prod.example .env.prod
notepad .env.prod
.\scripts\deploy-vps.ps1 -SshTarget root@YOUR_SERVER_IP
```

Use a non-default port or path if needed:

```powershell
.\scripts\deploy-vps.ps1 `
  -SshTarget deploy@YOUR_SERVER_IP `
  -Port 2222 `
  -DeployPath /opt/incubator-feed
```

Pass `-AnnounceRelease` only when the deploy should explicitly announce a
user-visible change. Use `medium` for a short generic restart notice and `major`
or `critical` for a detailed notice with release notes:

```powershell
.\scripts\deploy-vps.ps1 `
  -SshTarget deploy@YOUR_SERVER_IP `
  -AnnounceRelease `
  -ReleaseVersion 0.1.42-beta `
  -ReleaseImportance major `
  -ReleaseNotes "Добавлена ссылка на web-версию; Web-ключ теперь удобно копируется"
```

Without `-AnnounceRelease`, the deploy stays silent even if it changes the
version. `-SkipReleaseNotice` is kept for compatibility and also forces a silent
deploy.

You can also send or retry the notice from the VPS. The same version will not
be duplicated for users who already received it:

```bash
cd /opt/incubator-feed
docker run --rm --env-file .env.prod \
  -v /opt/incubator-feed/data:/app/data \
  -v /opt/incubator-feed/logs:/app/logs \
  -v /opt/incubator-feed/backups:/app/backups \
  incubator-feed:latest \
  python -B scripts/notify_release.py \
    --version 0.1.42-beta \
    --notes "Добавлена ссылка на web-версию; Web-ключ теперь удобно копируется"
```

## Server requirements

The VPS must have:

- SSH access from GitHub Actions or this workstation;
- Git;
- Docker.

Runtime state is stored on the VPS in `data/`, `logs/`, and `backups/`.
