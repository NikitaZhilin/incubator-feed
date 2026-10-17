# Backup and Restore

## Backup

Автоматически:

- Бот сам делает проверенную копию базы раз в сутки (проверка каждый час, `DailyBackupLoop`), хранит 7 последних в `BACKUP_DIR` (на VPS: `/opt/incubator-feed/backups/prod`). Если копия не создалась, администраторы получают сообщение в Telegram.
- Раз в неделю последняя копия, сжатая в `.db.gz`, отправляется в Telegram всем `ADMIN_IDS` — так копия хранится и вне сервера. Отметка об отправке — файл `.last_telegram_copy` в `BACKUP_DIR`; если отправить не удалось, повтор через час.
- `/backup` (или кнопка `📦 Прислать копию базы` в `/admin`) делает свежую проверенную копию и присылает её сразу.
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

## Restore

Если копия пришла из Telegram, сначала распакуйте её:

```bash
gunzip incubator_YYYYMMDDTHHMMSSZ.db.gz
```

Дальше так же, как с копией с сервера:

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
