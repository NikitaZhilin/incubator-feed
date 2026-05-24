# Telegram-бот для инкубации и учета кормов

Бот помогает вести партии инкубации, получать напоминания, смотреть календарь работ, учитывать несколько кормов, пополнения, списания и историю остатков.

## Возможности

- Инкубационные партии для кур, гусей, перепелов, обычных и мускусных уток.
- Несколько активных партий одновременно.
- Редактирование партии, завершение вывода и возврат партии из истории.
- Ежедневные напоминания по инкубации без дублей через `notification_log`.
- Учет кормов: несколько запасов, пополнение, списание, редактирование, архивирование, история операций.
- Группы птицы для кормов: группа задает понятное имя и количество птиц, корм можно привязать к группе.
- Расчет остатка, расхода в день и примерной даты окончания корма.
- Настройки пользователя: часовой пояс, время уведомлений, типы уведомлений, единицы, название хозяйства.
- `/admin` для разрешенных Telegram ID: статистика, последние регистрации, ошибки, рассылка, CSV-экспорт.
- Миграции SQLite через `schema_migrations`.
- Docker Compose и systemd-шаблоны для production.
- Резервное копирование и восстановление SQLite.

## Быстрый старт для разработки

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.dev.example .env
```

В `.env` укажите токен:

```text
BOT_TOKEN=123456:botfather_token
ENVIRONMENT=dev
DATABASE_PATH=data/incubator_dev.db
```

Запуск:

```powershell
python main.py
```

Smoke-start без Telegram polling:

```powershell
python -B scripts\smoke_start.py
```

## Конфигурация

Все переменные описаны в `.env.example`, `.env.dev.example` и `.env.prod.example`.

- `BOT_TOKEN` - токен Telegram-бота.
- `BOT_TIMEZONE` - часовой пояс по умолчанию.
- `DATABASE_PATH` - путь к SQLite.
- `LOG_FILE` и `LOG_LEVEL` - файл и уровень логирования.
- `ADMIN_IDS` - Telegram ID администраторов через запятую.
- `ENVIRONMENT` - `dev` или `prod`.
- `BACKUP_DIR` - каталог резервных копий.
- `REMINDER_INTERVAL_SECONDS` - частота reminder loop.
- `MIN_FREE_DISK_MB` - минимальный свободный объем для проверки диска.

`.env`, `.env.dev`, `.env.prod`, БД, логи и бэкапы не должны попадать в Git.

Production-режим читает токен только из `BOT_TOKEN`. Legacy-файлы `id` и `id.txt` поддерживаются только для локального `dev`.

Рецепты смесей в MVP хранятся в версионированном JSON-контенте `app/content/incubation.json`. Таблицы `feed_recipes` и `feed_recipe_items` зарезервированы миграциями для будущего переноса рецептов в БД, но текущая бизнес-логика читает JSON.

## Команды пользователя

Подробно: [docs/USER_COMMANDS.md](D:\проекты qwen\tg_bot_inkubator\docs\USER_COMMANDS.md)

Основные команды: `/start`, `/help`, `/new`, `/batches`, `/today`, `/history`, `/stats`, `/calendar`, `/care`, `/feed`, `/settings`, `/remind 09:00`, `/remind off`, `/timezone Europe/Moscow`, `/farm Название`, `/cancel`. Группы птицы доступны в разделе `Корма`.

## Миграции

```powershell
python -B scripts\migrate.py
```

Новая БД создается миграциями с нуля. Существующая БД обновляется без удаления пользовательских данных.

## Backup / Restore

```powershell
python -B scripts\backup.py
python -B scripts\restore.py backups\incubator_YYYYMMDDTHHMMSSZ.db --target data\incubator_restore.db
```

Подробно: [docs/BACKUP_RESTORE.md](D:\проекты qwen\tg_bot_inkubator\docs\BACKUP_RESTORE.md)

## Production

Рекомендуемый вариант:

```bash
cp .env.prod.example .env.prod
docker compose up -d --build
```

Альтернатива без Docker: systemd-шаблоны в `deploy/systemd`.

Подробно: [docs/SERVER_SETUP.md](D:\проекты qwen\tg_bot_inkubator\docs\SERVER_SETUP.md) и [docs/OPERATIONS.md](D:\проекты qwen\tg_bot_inkubator\docs\OPERATIONS.md).

## Тесты

```powershell
pip install -r requirements-dev.txt
python -B -m pytest -q
```

## Документы

- [Server setup](D:\проекты qwen\tg_bot_inkubator\docs\SERVER_SETUP.md)
- [Operations](D:\проекты qwen\tg_bot_inkubator\docs\OPERATIONS.md)
- [Backup/Restore](D:\проекты qwen\tg_bot_inkubator\docs\BACKUP_RESTORE.md)
- [User commands](D:\проекты qwen\tg_bot_inkubator\docs\USER_COMMANDS.md)
- [Architecture notes](D:\проекты qwen\tg_bot_inkubator\docs\ARCHITECTURE_NOTES.md)
- [Privacy Policy](D:\проекты qwen\tg_bot_inkubator\docs\PRIVACY_POLICY.md)
- [Terms and Disclaimer](D:\проекты qwen\tg_bot_inkubator\docs\TERMS_DISCLAIMER.md)
- [Changelog](D:\проекты qwen\tg_bot_inkubator\docs\CHANGELOG.md)
