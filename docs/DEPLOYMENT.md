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
WEB_PUBLIC_URL=public web URL, for example https://your-domain.ngrok-free.app
WEB_LINK_TOKEN=long random token for link-based web access
NGROK_AUTHTOKEN=ngrok account token, used to create/update WEB_PUBLIC_URL automatically
```

Optional repository variable:

```text
DEPLOY_PATH=/opt/incubator-feed
```

The workflow updates the project on the VPS, writes `.env.prod` from GitHub
Secrets, runs migrations, rebuilds the Docker image, and starts the bot as a
Docker container with `--restart unless-stopped`.

Regular deploys are silent for users. Version, GitHub, documentation and changelog links are
available in Telegram under `Настройки -> О боте`. A release notice is sent only
when it is explicitly enabled. `medium` sends a short "bot was updated and
restarted" message with the main menu; `major` and `critical` also include
release notes. The notice is deduplicated in `notification_log` by release
version, so re-running or restarting the same version does not send the same
update twice.

Administrators can still receive a short technical startup notice. This is
controlled separately by `ADMIN_STARTUP_NOTICE_MODE` and is sent only to
`ADMIN_IDS`; regular users never receive it. The default production mode is
`once_per_deploy`, so an admin sees that the deployed commit started, without
the long user-facing release text.

For a manual GitHub Actions run you can fill:

```text
release_version=0.1.42-beta
release_notes=Добавлен раздел Яйца; Добавлен прогноз яйценоскости
```

The current GitHub Actions workflow does not expose `release_importance` as an
input. It is suitable for updating the code, version and `О боте` notes. For a
user-visible notice, use `scripts/deploy-vps.ps1 -AnnounceRelease` or run
`scripts/notify_release.py` from the VPS/container after deploy.

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
  -ReleaseNotes "Добавлен раздел Яйца; Добавлен прогноз яйценоскости"
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
    --notes "Добавлен раздел Яйца; Добавлен прогноз яйценоскости"
```

## What reaches users after deploy

Regular push to `main` deploys code to the VPS but should not distract users.
The bot updates `Настройки -> О боте` with version, GitHub/documentation/changelog links,
deploy time and release notes. The documentation link is controlled by `DOCS_URL`.

Use a user-visible release notice only for changes that users should see
immediately:

- `medium` - short "bot was updated and restarted" message plus main menu;
- `major` - detailed release notes plus main menu;
- `critical` - urgent detailed notice plus main menu.

Minor changes should stay available only inside `Настройки -> О боте`.

## Admin startup notice

Use this for a compact confirmation that the deployed bot has actually started:

```text
ADMIN_STARTUP_NOTICE_MODE=once_per_deploy
```

Modes:

- `off` - do not send technical startup notices;
- `once_per_deploy` - send one short notice to each admin for each deployed commit;
- `always` - send the short notice on every bot start.

The message contains only the useful operational facts: bot restarted, version,
startup time and that the message is admin-only. It does not include detailed
release notes or internal flags.

## Server requirements

The VPS must have:

- SSH access from GitHub Actions or this workstation;
- Git;
- Docker.

Runtime state is stored on the VPS in `data/`, `logs/`, and `backups/`.
The deploy starts two Docker containers: `incubator-feed-bot` for Telegram
polling and `incubator-feed-web` for the web interface. The web container is
bound to `127.0.0.1:8080`; expose it through ngrok, Caddy, Nginx, or another
reverse proxy, then put that public address into `WEB_PUBLIC_URL`.
If `NGROK_AUTHTOKEN` is configured in GitHub Actions secrets, the deploy also
starts `incubator-feed-ngrok`, reads its generated HTTPS URL and writes it to
`WEB_PUBLIC_URL` in `.env.prod` before starting the Telegram bot.
With HTTPS `WEB_PUBLIC_URL`, the bot shows separate `Открыть сайт` and
`Открыть Mini App` buttons and configures the Telegram menu button to open the
Mini App on startup. After changing `WEB_PUBLIC_URL`, restart the bot container
so Telegram receives the new menu button URL.

## VPS auto deploy fallback

GitHub Actions remains the primary deployment path. If pushes from a local
tooling environment do not trigger Actions, the VPS can also poll `origin/main`
and deploy only when a new commit appears.

Install the fallback timer on the VPS after the project has been cloned to
`/opt/incubator-feed`:

```bash
cd /opt/incubator-feed
chmod +x scripts/server-auto-deploy.sh
cp deploy/systemd/incubator-feed-auto-deploy.service /etc/systemd/system/
cp deploy/systemd/incubator-feed-auto-deploy.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now incubator-feed-auto-deploy.timer
```

Check it with:

```bash
systemctl list-timers incubator-feed-auto-deploy.timer
journalctl -u incubator-feed-auto-deploy.service -n 100 --no-pager
```
