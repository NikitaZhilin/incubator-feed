# Server Setup

Production-путь проекта: GitHub Actions или ручной Docker-деплой в `/opt/incubator-feed`. Запуск через systemd без Docker больше не поддерживается: шаблоны удалены, а деплой сам отключает старые службы `tg-bot-inkubator*` и `incubator-feed-auto-deploy*`, если они остались на сервере.

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
