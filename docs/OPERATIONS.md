# Operations

## Logs

Бот пишет логи в `LOG_FILE`. В приложении включена ротация: 2 MB на файл, 5 архивов.

Docker:

```bash
docker compose logs -f --tail=100 bot
```

systemd:

```bash
journalctl -u tg-bot-inkubator.service -f
```

## Deploy checklist

1. Проверить `git status`.
2. Создать бэкап.
3. Забрать новую версию.
4. Установить зависимости или пересобрать Docker image.
5. Запустить миграции: `python -B scripts/migrate.py`.
6. Запустить тесты или `python -B scripts/smoke_start.py`.
7. Перезапустить сервис.
8. Проверить статус сервиса.
9. Проверить последние логи.
10. Для обычного деплоя проверить, что release notice не отправлялся; для важного релиза отправить retry вручную: `python -B scripts/notify_release.py --version 0.1.42-beta --notes "Кратко об изменениях"`.
11. Отправить `/start` боту.
12. Проверить свежий бэкап.

## Manual smoke checklist

После заметных изменений пройти в Telegram:

1. `/start` и главное меню.
2. `Корма -> Склад`: список ингредиентов, покупка, история.
3. `Корма -> Смесь`: расчет доступных замесов, план и подтверждение создания.
4. `Корма -> Поголовье и стада`: создать/открыть поголовье и стадо, назначить смесь.
5. `Корма -> Расчеты`: проверить расход стада, готовую смесь, потенциальные замесы и даты закупок.
6. `Инкубация`: активные партии, план на сегодня, календарь, уход после вывода.
7. `Яйца`: добавить сбор, открыть расчеты, историю, добавить и завершить исключение несушки.
8. `Настройки -> Разделы и уведомления`: выключить/включить раздел и проверить главное меню.
9. `Настройки -> О боте`: версия, последний запуск, последний деплой, GitHub и changelog.

## Disk monitoring

```bash
python -B scripts/check_disk.py
```

Команда завершится с ошибкой, если свободного места меньше `MIN_FREE_DISK_MB`.

## Process monitoring and failure notification

Внутри приложения критическая ошибка polling пишется в `critical_errors` и отправляется `ADMIN_IDS`.

Для падений вне Python-процесса используйте внешний механизм:

- systemd: `tg-bot-inkubator.service` содержит `OnFailure=tg-bot-inkubator-failure@%n.service`; failure-unit запускает `scripts/notify_admin_failure.py`.
- Docker: Compose настроен на `restart: unless-stopped` и healthcheck. Для Telegram-уведомлений о падении контейнера можно запускать с хоста:

```bash
python -B scripts/notify_admin_failure.py docker-healthcheck-failed
```

Скрипт использует только `BOT_TOKEN` и `ADMIN_IDS` из окружения или `.env.prod`.

## Rollback

1. Остановить сервис.
2. Вернуть предыдущий коммит.
3. Восстановить БД из бэкапа, если новая версия успела изменить данные некорректно.
4. Запустить `smoke_start.py`.
5. Запустить сервис и проверить логи.

## Admin failure notification

Если polling падает с критической ошибкой, бот пишет запись в `critical_errors` и пытается отправить сообщение всем `ADMIN_IDS`.
