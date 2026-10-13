# Backup and Restore

## Backup

Автоматически:

- Бот сам делает проверенную копию базы раз в сутки (проверка каждый час, `DailyBackupLoop`), хранит 7 последних в `BACKUP_DIR` (на VPS: `/opt/incubator-feed/backups/prod`). Если копия не создалась, администраторы получают сообщение в Telegram.
- Деплой через GitHub Actions перед миграциями делает отдельную копию в `BACKUP_DIR/pre-deploy` (хранятся 5 последних).

Ручной бэкап:

```bash
python -B scripts/backup.py
python -B scripts/backup.py --label manual --keep 10
```

Скрипт использует SQLite backup API, проверяет `PRAGMA integrity_check` и хранит несколько последних копий.

Docker:

```bash
docker compose run --rm backup
```

systemd timer:

```bash
systemctl list-timers | grep tg-bot-inkubator-backup
```

## Restore

1. Остановите бота.
2. Проверьте резервную копию и восстановите в отдельный файл:

```bash
python -B scripts/restore.py backups/incubator_YYYYMMDDTHHMMSSZ.db --target data/incubator_restore.db
```

3. Запустите smoke-test на восстановленной БД:

```bash
DATABASE_PATH=data/incubator_restore.db python -B scripts/smoke_start.py
```

4. Если проверка успешна, замените production-БД восстановленной копией и запустите сервис.

Никогда не коммитьте файлы из `data/` и `backups/`.
