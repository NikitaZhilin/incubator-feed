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

## Server requirements

The VPS must have:

- SSH access from GitHub Actions or this workstation;
- Git;
- Docker.

Runtime state is stored on the VPS in `data/`, `logs/`, and `backups/`.
