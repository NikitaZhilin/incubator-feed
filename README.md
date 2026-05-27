# Telegram-бот для инкубации, кормов и учета яиц

Telegram-бот помогает вести небольшое птицеводческое хозяйство: инкубационные партии, склад кормов, замесы смеси, поголовье, стада и ежедневный учет яиц.

Проект сейчас находится в beta/test-режиме. Данные хранятся в SQLite, схема обновляется миграциями, production-деплой работает через GitHub Actions или ручной VPS-деплой.

## Возможности

- Инкубационные партии для кур, гусей, перепелов, обычных и мускусных уток.
- Календарь работ, план на сегодня, режимы инкубации и уход после вывода.
- Завершение вывода, история партий и возврат завершенной партии в активные.
- Ежедневные напоминания без дублей через `notification_log`.
- Склад кормов: покупки, фактические остатки, история операций и расчетные остатки.
- Замес смеси: расчет доступных замесов по складу, выбор пшеницы или зерносмеси, списание ингредиентов и добавление готовой смеси.
- Словарь сопоставления складских названий: например, дробленая кукуруза считается кукурузой, зерносмесь может заменять пшеницу, коммерческий комбикорм определяется по названию.
- Поголовье: отдельные группы птиц, включая несушек, петухов и цыплят с датой вывода и подсадки.
- Стада: набор групп поголовья, которые едят одну готовую смесь.
- Расчеты по кормам: дневной расход стада, сколько хватит готовой смеси, сколько еще можно произвести из складских ингредиентов, ориентировочные даты закупок.
- Учет яиц: ежедневный сбор, история, прогноз по последним 7/30 дням, исключение несушек, которые временно не несутся, погодная поправка через Open-Meteo.
- Web-кабинет: сводка, корма и склад, смесь, поголовье и стада, яйца, инкубация, статус сервисов и версия; базовые write-сценарии позволяют добавить сбор яиц, покупку на склад, создать замес с подтверждением, добавить и отредактировать поголовье, создать и отредактировать стадо, назначить смесь стаду и изменить часть настроек.
- Настройки: хозяйство, часовой пояс, время уведомлений, включение и выключение разделов, экран `О боте` с версией, ссылками и временем запуска/деплоя.
- Админские команды: статистика, последние регистрации, ошибки, сервисная рассылка, CSV-экспорт.
- Миграции SQLite через `schema_migrations`.
- Docker Compose, systemd-шаблоны, VPS deploy scripts, backup/restore и smoke-start.

## Структура меню

- `🌾 Корма`
  - `🧮 Смесь`
  - `📦 Склад`
  - `🐔 Поголовье и стада`
  - `📊 Расчеты`
- `🥚 Инкубация`
  - партии, календарь, план, история, статистика, режимы, уход после вывода
- `🥚 Яйца`
  - добавить яйца, расчеты, история, временно не несущиеся куры, город и погода
- `⚙️ Настройки`
  - хозяйство, часовой пояс, уведомления, разделы, `О боте`

Если раздел выключен в настройках, его кнопка пропадает из главного меню.

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
- `RELEASE_VERSION` - текущая beta-версия, например `0.1.42-beta`.
- `RELEASE_NOTES` - краткое описание изменений для экрана `О боте` и важных release notice.
- `RELEASE_NOTICE_ENABLED` и `RELEASE_IMPORTANCE` - явное включение release notice. `minor` не отправляет сообщение пользователям, `medium` отправляет короткое сообщение о перезапуске, `major` и `critical` добавляют подробности.
- `RELEASE_CHANNEL`, `GITHUB_URL`, `CHANGELOG_URL` - данные для `Настройки -> О боте`.
- `RELEASE_DEPLOYED_AT`, `RELEASE_COMMIT` - служебные поля деплоя, заполняются deploy-процессом.

Погода для раздела `Яйца` загружается из Open-Meteo по названию города, с fallback на `wttr.in`, если основной источник не ответил. Отдельный API key не нужен. Открытие раздела использует сохраненные погодные данные; сетевое обновление запускается только вручную.

`.env`, `.env.dev`, `.env.prod`, БД, логи и бэкапы не должны попадать в Git.

Production-режим читает токен только из `BOT_TOKEN`. Legacy-файлы `id` и `id.txt` поддерживаются только для локального `dev`.

## Команды пользователя

Подробно: [docs/USER_COMMANDS.md](docs/USER_COMMANDS.md).

Основные команды: `/start`, `/menu`, `/share`, `/help`, `/version`, `/new`, `/batches`, `/today`, `/history`, `/stats`, `/profiles`, `/calendar`, `/care`, `/feed`, `/settings`, `/remind 09:00`, `/remind off`, `/timezone Europe/Moscow`, `/farm Название`, `/units metric`, `/disclaimer`, `/cancel`.

Большая часть новых сценариев доступна через кнопки главного меню, а не через отдельные команды.

Бот можно открыть с разных Telegram-аккаунтов по ссылке из `/share` или кнопке `Поделиться ботом`. Каждый Telegram-аккаунт работает изолированно: видит только свои партии, корма, склад, поголовье, стада, яйца, настройки и напоминания.

## Миграции

```powershell
python -B scripts\migrate.py
```

Новая БД создается миграциями с нуля. Существующая БД обновляется без удаления пользовательских данных.

Актуальные крупные группы таблиц:

- `incubation_batches`, `reminder_settings`;
- `users`, `notification_log`;
- `feed_stocks`, `feed_transactions`, `bird_groups`;
- `stock_items`, `stock_transactions`, `mix_productions`, `mix_production_items`;
- `flocks`, `flock_members`, `flock_feed_assignments`;
- `egg_entries`, `hen_laying_exclusions`, `weather_settings`, `daily_weather`;
- `analytics_events`, `critical_errors`.

## Backup / Restore

```powershell
python -B scripts\backup.py
python -B scripts\restore.py backups\incubator_YYYYMMDDTHHMMSSZ.db --target data\incubator_restore.db
```

Подробно: [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).

## Production

Основной путь деплоя: GitHub Actions на каждый push в `main`. Workflow запускает тесты, обновляет проект на VPS, применяет миграции, пересобирает Docker image и перезапускает контейнер.

Ручной запуск:

```bash
cp .env.prod.example .env.prod
docker compose up -d --build
```

Обычные деплои молчат для пользователей. Информация о версии доступна в `Настройки -> О боте`. Общее сообщение отправляется только при явном release notice:

- `medium` - короткое сообщение, что бот обновлен и перезапущен;
- `major` и `critical` - сообщение с подробностями изменений;
- повтор для той же версии не дублируется через `notification_log`.

Подробно: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), [docs/SERVER_SETUP.md](docs/SERVER_SETUP.md), [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Тесты

```powershell
pip install -r requirements-dev.txt
python -B -m pytest -q
```

## Web-версия

Web-интерфейс запускается отдельным процессом. Основные страницы преимущественно обзорные, но уже поддерживают базовые рабочие действия: яйца, склад, замес, поголовье, стада, назначение смеси и часть настроек:

```powershell
python -B scripts\web_app.py
```

Доступны защищенные страницы `/`, `/feeds`, `/mix`, `/livestock`, `/eggs`, `/incubation`, `/about`, `/status` и `/version`.
Подробно: [docs/OPERATIONS.md](docs/OPERATIONS.md), [docs/WEB_VERSION_TZ.md](docs/WEB_VERSION_TZ.md).

## Документы

- [User commands](docs/USER_COMMANDS.md)
- [Architecture notes](docs/ARCHITECTURE_NOTES.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Operations](docs/OPERATIONS.md)
- [Server setup](docs/SERVER_SETUP.md)
- [Backup/Restore](docs/BACKUP_RESTORE.md)
- [Roadmap and gaps](docs/ROADMAP.md)
- [Technical spec MVP](docs/TECHNICAL_SPEC_MVP.md)
- [Privacy Policy](docs/PRIVACY_POLICY.md)
- [Terms and Disclaimer](docs/TERMS_DISCLAIMER.md)
- [Changelog](docs/CHANGELOG.md)
