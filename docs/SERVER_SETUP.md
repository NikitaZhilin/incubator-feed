# Server Setup

Рекомендуемый production-путь проекта сейчас: GitHub Actions или ручной Docker-деплой в `/opt/incubator-feed`. systemd-шаблоны оставлены как альтернативный режим без Docker и используют путь `/opt/tg_bot_inkubator`; если используете другой путь, обновите `WorkingDirectory`, `EnvironmentFile` и `ExecStart` в unit-файлах.

## Docker Compose

1. Установите Docker и Docker Compose.
2. Скопируйте проект на сервер.
3. Создайте production-конфиг:

```bash
cp .env.prod.example .env.prod
nano .env.prod
```

4. Запустите:

```bash
docker compose up -d --build
```

5. Проверьте:

```bash
docker compose ps
docker compose logs --tail=100 bot
docker compose run --rm backup
```

Сервис использует `restart: unless-stopped`, поэтому поднимается после падения и перезагрузки сервера. В `docker-compose.yml` есть healthcheck через `scripts/check_disk.py`; для Telegram-уведомлений о падении контейнера подключите мониторинг хоста или cron-команду из `docs/OPERATIONS.md`.

## systemd

1. Создайте пользователя:

```bash
sudo useradd --system --home /opt/tg_bot_inkubator --shell /usr/sbin/nologin tg-bot
```

2. Разместите проект в `/opt/tg_bot_inkubator`.
3. Создайте `.venv`, установите зависимости и заполните `.env.prod`.
4. Скопируйте unit-файлы:

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tg-bot-inkubator.service
sudo systemctl enable --now tg-bot-inkubator-backup.timer
```

Основной unit содержит `OnFailure=tg-bot-inkubator-failure@%n.service`. Этот unit запускает `scripts/notify_admin_failure.py`, который берет `BOT_TOKEN` и `ADMIN_IDS` только из env-файла и отправляет администраторам Telegram-сообщение о падении процесса.

5. Проверка:

```bash
systemctl status tg-bot-inkubator.service
journalctl -u tg-bot-inkubator.service -n 100 --no-pager
sudo systemctl start tg-bot-inkubator-failure@manual-test.service
```
