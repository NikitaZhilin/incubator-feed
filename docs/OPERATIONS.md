# Operations

## Logs

Бот пишет логи в `LOG_FILE`. В приложении включена ротация: 2 MB на файл, 5 архивов.

Docker:

```bash
docker compose logs -f --tail=100 bot
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
9. `Настройки -> О боте`: версия, последний запуск, последний деплой, GitHub, документация и changelog.
10. Главное меню: `✅ Покормил` (кружки, отмена), `🥚 Собрал яйца` (кнопка с числом), `📤 Продал / отдал`, `🗓 Уход` (`✅`, `⏰ +3 дн.`).
11. `Корма -> 💰 Себестоимость`, `Поголовье и стада -> ➖ Падёж / выбыло` и отмена, `🏷 Роль`, `📅 Год вывода`.
12. `Птицевод`: `💡 Свет зимой`, `🐔 Возраст стада и замена`, `Мало яиц`.
13. `Настройки -> 📥 Выгрузить всё в Excel` и `/backup` (администратор).

Автоматически это делает CI: `tests/test_all_buttons.py` нажимает все кнопки бота на заполненной базе, `tests/test_all_web_buttons.py` открывает все ссылки и отправляет все формы сайта. Итог виден в аннотациях проверки `test` на GitHub.

## Disk monitoring

```bash
python -B scripts/check_disk.py
```

Команда завершится с ошибкой, если свободного места меньше `MIN_FREE_DISK_MB`.

## Process monitoring and failure notification

Внутри приложения критическая ошибка polling пишется в `critical_errors` и отправляется `ADMIN_IDS`.

Для падений вне Python-процесса используйте внешний механизм:

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
`https://incubator.example.ru`. Telegram-бот показывает web-кнопку в главном
меню, настройках и разделе `О боте` всегда. Если `WEB_PUBLIC_URL` задан,
показывается `🌐 Открыть сайт`; если URL начинается с `https://`, дополнительно
показывается `📱 Открыть Mini App` через Telegram `web_app`. При HTTPS бот на
старте также настраивает компактный Telegram menu button `АПП`. Если вместе с
`WEB_PUBLIC_URL` задан `WEB_LINK_TOKEN`, ссылки открываются с
`?auth=<WEB_LINK_TOKEN>`. `WEB_ADMIN_TOKEN` в Telegram-ссылки не подставляется.

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

Публичный адрес без токена: `GET /health`.

Остальные адреса требуют `?auth=<WEB_LINK_TOKEN>` (так открывают кнопки бота) или заголовок `Authorization: Bearer <WEB_ADMIN_TOKEN>` / `X-Web-Token: <WEB_ADMIN_TOKEN>`. Если не задан ни один токен, страницы возвращают `503`. Формы отправляют `POST` и после действия перенаправляют обратно с сообщением `notice` или `error`.

Страницы (`GET`):

- `/` — сводка, «✅ Покормил» с отменой, плитки хозяйства;
- `/feeds` — корма и склад, «Кормление моей смесью», себестоимость и цены покупок;
- `/mix`, `/mix/confirm` — смесь и подтверждение замеса;
- `/livestock` — поголовье, стада, цыплята → взрослые, падёж и выбраковка, календарь ухода;
- `/eggs`, `/eggs/multi-day` — яйца, сбор за несколько дней (предпросмотр), продажа и раздача;
- `/incubation` — партии, история, итоги инкубации, справочник;
- `/charts?days=30|90` — графики яиц, расхода смеси и продаж;
- `/advisor` — птицевод: план, итоги недели, свет зимой, возраст стада и др.;
- `/help?topic=...` — FAQ (те же тексты, что в боте);
- `/about` — версия, настройки хозяйства и разделов, выгрузка в Excel;
- `/export.xlsx` — файл со всеми данными;
- JSON: `/feeds/data`, `/mix/data`, `/livestock/data`, `/eggs/data`, `/incubation/data`, `/about/data`, `/summary`, `/status`, `/version`.

Действия (`POST`):

- кормление: `/feeding`, `/feeding/{id}/undo`, `/feeding/mix`;
- склад и смесь: `/stock/purchases` (с необязательной `price_rub`), `/stock/items/{id}/adjust`, `/feeds/mixes`, `/feeds/mixes/already-fed`, `/ledger/purchases/{id}/price`;
- поголовье и стада: `/bird-groups`, `/bird-groups/{id}`, `/bird-groups/{id}/archive`, `/bird-groups/{id}/grow`, `/flocks`, `/flocks/{id}`, `/flocks/{id}/archive`, `/flock-feed-assignments`, `/feeding-assignments`;
- потери: `/ledger/losses`, `/ledger/losses/{id}/undo`;
- уход: `/care/{id}/done|snooze|toggle|interval`;
- яйца: `/eggs/entries`, `/eggs/entries/{id}`, `/eggs/entries/{id}/delete`, `/eggs/multi-day`, `/eggs/exclusions`, `/eggs/exclusions/{id}/finish`, `/eggs/weather/refresh`, `/ledger/eggs-out`, `/ledger/eggs-out/{id}/undo`;
- инкубация: `/incubation/batches`, `/incubation/batches/{id}/edit`, `/incubation/batches/{id}/complete`, `/incubation/batches/{id}/reopen`;
- настройки: `/settings/profile`, `/settings/sections`, `/settings/weather`.

## Rollback

1. Остановить сервис.
2. Вернуть предыдущий коммит.
3. Восстановить БД из бэкапа, если новая версия успела изменить данные некорректно.
4. Запустить `smoke_start.py`.
5. Запустить сервис и проверить логи.

## Backups

Копия базы делается раз в сутки и раз в неделю отправляется администраторам в Telegram (`.db.gz`). Свежая копия — `/backup`. Подробно: [BACKUP_RESTORE.md](BACKUP_RESTORE.md).

## Admin failure notification

Если polling падает с критической ошибкой, бот пишет запись в `critical_errors` и пытается отправить сообщение всем `ADMIN_IDS`.
