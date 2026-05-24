# Backup and Restore

## Backup

Ручной бэкап:

```bash
python -B scripts/backup.py
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
