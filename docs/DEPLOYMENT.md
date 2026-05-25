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

After a successful deploy the workflow writes release metadata to `.env.prod`,
then the main bot process sends a release notice to active users who have
service notifications enabled. The notice is deduplicated in `notification_log`
by release version, so re-running or restarting the same version does not send
the same update twice.

For a manual GitHub Actions run you can fill:

```text
release_version=0.1.42-beta
release_notes=Добавлена ссылка на web-версию; Web-ключ теперь удобно копируется
```

The main bot process sends this notice on startup. It opens the main menu with
a reply keyboard and includes the MVP testing warning. The version should be a
numeric beta version, for example `0.1.42-beta`. If the process restarts several
times with the same version, users still receive the notice only once because
delivery is recorded in `notification_log`.

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

Pass release text when the deploy should explicitly announce a user-visible
change:

```powershell
.\scripts\deploy-vps.ps1 `
  -SshTarget deploy@YOUR_SERVER_IP `
  -ReleaseVersion 0.1.42-beta `
  -ReleaseNotes "Добавлена ссылка на web-версию; Web-ключ теперь удобно копируется"
```

Use `-SkipReleaseNotice` only for purely technical redeploys that should stay
silent.

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
