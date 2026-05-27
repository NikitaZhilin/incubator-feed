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

## Read-only status probe

Бот пишет heartbeat в SQLite для двух обязательных runtime-сервисов:

- `polling_bot` - основной Telegram polling;
- `reminder_runner` - фоновый runner напоминаний.

Проверить состояние без изменения БД:

```bash
python -B scripts/status_probe.py
```

Скрипт открывает SQLite в read-only режиме и печатает JSON в stdout. Exit code:

- `0` - общий статус `ok`;
- `1` - общий статус `degraded` или `down`;
- `2` - база недоступна или probe не смог выполниться.

Сервис считается `down`, если heartbeat отсутствует или старше 120 секунд.
`degraded` выставляется при свежем heartbeat со статусом `degraded`, `last_error`
или накопленных `critical_errors`.

## Web service

Web-интерфейс запускается отдельным процессом и не встроен в Telegram polling.
По умолчанию он должен слушать только `127.0.0.1`.

Минимальная конфигурация:

```env
WEB_ENABLED=true
WEB_HOST=127.0.0.1
WEB_PORT=8080
WEB_PUBLIC_URL=
WEB_ADMIN_TOKEN=replace_with_strong_token
WEB_LINK_TOKEN=
```

`WEB_PUBLIC_URL` - внешний адрес web-сервиса, например
`https://incubator.example.ru`. Если он задан, Telegram-бот показывает кнопку
`🌐 Открыть сайт` в главном меню, настройках и разделе `О боте`. Если вместе с
ним задан `WEB_LINK_TOKEN`, кнопка открывает ссылку с `?auth=<WEB_LINK_TOKEN>`.
`WEB_ADMIN_TOKEN` в Telegram-ссылки не подставляется.

Запуск:

```bash
python -B scripts/web_app.py
```

Быстрый тест через ngrok:

```powershell
.\scripts\start-ngrok-web.ps1
```

Скрипт запускает локальный web на `127.0.0.1:8080` и открывает ngrok-туннель.
Если в ngrok задан постоянный dev domain, его можно передать явно:

```powershell
.\scripts\start-ngrok-web.ps1 -Url https://your-domain.ngrok-free.app
```

Для активного Telegram-бота после получения ngrok URL нужно прописать его в
`WEB_PUBLIC_URL` и перезапустить bot-процесс.

Публичный endpoint:

- `GET /health`

Закрытые endpoints требуют `Authorization: Bearer <WEB_ADMIN_TOKEN>` или
`X-Web-Token: <WEB_ADMIN_TOKEN>`:

- `GET /` - HTML-сводка;
- `GET /feeds` - HTML-страница кормов и склада;
- `GET /feeds/data` - JSON для страницы кормов и склада;
- `POST /stock/purchases` - добавление покупки на склад;
- `GET /mix` - HTML-страница формулы смеси, доступных замесов и истории готовой смеси;
- `GET /mix/data` - JSON для страницы смеси;
- `GET /mix/confirm` - HTML-подтверждение замеса перед списанием ингредиентов;
- `POST /feeds/mixes` - создание замеса, списание ингредиентов и добавление готовой смеси;
- `GET /livestock` - HTML-страница поголовья, стад, состава стад и назначенной смеси;
- `GET /livestock/data` - JSON для страницы поголовья и стад;
- `POST /bird-groups` - добавление группы поголовья;
- `PATCH /bird-groups/{id}` - редактирование группы поголовья;
- `POST /flocks` - создание стада из групп поголовья;
- `PATCH /flocks/{id}` - редактирование стада и его состава;
- `POST /flock-feed-assignments` - назначение готовой смеси стаду;
- `GET /eggs` - HTML-страница учета яиц, прогноза, исключений несушек и погоды;
- `GET /eggs/data` - JSON для страницы яиц;
- `POST /eggs/entries` - добавление записи сбора яиц за сегодня или вчера;
- `POST /settings/weather` - изменение города погоды;
- `GET /incubation` - HTML-страница активных и завершенных партий инкубации;
- `GET /incubation/data` - JSON для страницы инкубации;
- `GET /about` - HTML-страница версии, деплоя, ссылок, настроек и runtime-статуса;
- `GET /about/data` - JSON для страницы `О боте`;
- `GET /status` - JSON-статус на базе read-only status probe;
- `GET /summary` - JSON-сводка хозяйства: яйца, корма, стада, инкубация;
- `GET /version` - версия, окружение, commit и ссылки;
- `PATCH /settings/sections` - включение и выключение разделов Telegram-бота.

Если не задан ни `WEB_ADMIN_TOKEN`, ни `WEB_LINK_TOKEN`, обычные закрытые
web-страницы возвращают `503`.
Для обычных web-страниц заготовлена авторизация по ссылке: если задан
`WEB_LINK_TOKEN`, страницы `/`, `/feeds`, `/feeds/data`, `/mix`, `/mix/data`,
`/summary`, `/status`, `/livestock`, `/livestock/data`, `/bird-groups`, `/flocks`, `/flock-feed-assignments`, `/eggs`, `/eggs/data`,
`/settings/weather`, `/settings/sections`, `/incubation`, `/incubation/data`, `/about`, `/about/data` и `/version` можно открыть с `?auth=<WEB_LINK_TOKEN>`.

## Rollback

1. Остановить сервис.
2. Вернуть предыдущий коммит.
3. Восстановить БД из бэкапа, если новая версия успела изменить данные некорректно.
4. Запустить `smoke_start.py`.
5. Запустить сервис и проверить логи.

## Admin failure notification

Если polling падает с критической ошибкой, бот пишет запись в `critical_errors` и пытается отправить сообщение всем `ADMIN_IDS`.
