# Architecture Notes

## Runtime layout

Проект построен вокруг aiogram handlers, сервисного слоя и SQLite repositories:

- `app/handlers/*` - Telegram-сценарии и FSM;
- `app/keyboards/*` - inline-клавиатуры;
- `app/services/*` - бизнес-логика инкубации, кормов, склада, яиц, напоминаний, релизных уведомлений и админки;
- `app/storage/repositories/*` - доступ к SQLite;
- `app/storage/migrations/*` - последовательные миграции через `schema_migrations`;
- `app/domain.py` - dataclass-модели домена;
- `app/content/incubation.json` - версионированный справочный контент инкубации и рецепт смеси;
- `app/content/help/*.md` - файловые инструкции для кнопок `FAQ`, индексируются в `app/services/help_content.py`;
- `app/web/*` - сайт на FastAPI: `main.py` (основные страницы), `parity.py` (функции, повторяющие бота), `ledger_pages.py` (потери, продажи, цены), `farm_tools.py` (уход, цыплята, Excel, итоги инкубации), `charts.py` (графики).

В `app/main.py` создаются repositories и services, затем services передаются в aiogram dispatcher через dependency injection (`dispatcher["feeding_service"]`, `["ledger_service"]`, `["care_service"]` и т. д.). Роутеры подключаются в `app/handlers/__init__.py`; `fallback` всегда последний.

Сайт не импортирует aiogram и создаёт сервисы сам на каждый запрос (`feeding_service_for`, `ledger_service_for`), поэтому бот и сайт считают одинаково.

## Модули по функциям

| Функция | Сервис | Хранилище | Бот | Сайт |
| --- | --- | --- | --- | --- |
| «✅ Покормил», моя смесь, дни запаса, «Пора докупить» | `services/feeding.py` (`FeedingService.record`, `pace`, `pace_lines`, `buy_reminder_stage`) | `feeding_events`, `feeding_event_items`, `feeding_settings`; списание — `stock_transactions` | `handlers/feeding.py` | `parity.fed_block`, `feeding_mix_form`, `pace_tile` |
| Потери, продажи яиц, цены, себестоимость | `services/ledger.py` (`LedgerService`) | `bird_losses`, `egg_outflows`, `stock_transactions.price_rub` | `handlers/ledger.py` | `web/ledger_pages.py` |
| Итоги недели | `services/weekly_report.py` | — | `report:week` в `handlers/ledger.py` | блок на `/advisor` |
| Падение яйценоскости, свет, подросшие цыплята | `services/insights.py` | — | `handlers/farm_tools.py`, `PoultryAdvisorService` | `/advisor`, `/livestock` |
| Календарь ухода | `services/care.py` (`CareService`) | `care_tasks` | `handlers/farm_tools.py` | `web/farm_tools.care_block` |
| Сбор яиц в одно нажатие, заметка к сбору, возраст стада, итоги и причины потерь инкубации | `services/farm_overview.py` | `batch_losses` | `handlers/quick.py`, `handlers/incubation.py` | `/advisor`, `/incubation`, `POST /incubation/losses` |
| «Не несутся»: группа, «Снова несутся?» | `EggService.create_exclusion`, `stale_exclusions`, `extend_exclusion` | `hen_laying_exclusions` | `handlers/eggs.py` | `/eggs` |
| Хранение яиц: места, партии по дате, раскладка сбора, списание с самых старых | `services/egg_storage.py` (`EggStorage`, создаётся внутри `EggService` и `LedgerService`) | `egg_places`, `egg_lots`, `egg_takes` | `handlers/egg_storage.py`, «откуда» в `handlers/ledger.py` | блок на `/eggs`, `/storage/*` |
| Выгрузка в Excel | `services/export.py` (openpyxl) | все таблицы пользователя | `export:xlsx` | `/export.xlsx` |
| Копии базы | `services/backups.py` (`DailyBackupLoop`) | файлы в `BACKUP_DIR` | `/backup`, `admin:backup` | — |
| Напоминания и сводка | `services/reminders.py` (`ReminderRunner`) | `notification_log` | — | — |

Все автоматические сообщения перечислены в [NOTIFICATIONS.md](NOTIFICATIONS.md).

## Notification settings

Единый источник пользовательских настроек уведомлений - таблица `users`:

- `timezone`;
- `notification_time`;
- `notify_incubation`;
- `notify_feed`;
- `notify_eggs`;
- `notify_post_hatch_care`;
- `notify_poultry_advisor`;
- `notify_daily_summary`;
- `notify_feeding`;
- `notify_service`;
- `is_active`.

Таблица `reminder_settings` сохранена для совместимости с существующими БД. Миграция `006_sync_user_notification_settings` переносит старые `hour/minute/is_enabled` в `users.notification_time` и `users.notify_incubation`. Команда `/remind` обновляет обе модели, но reminder runner читает фактические настройки из `users`.

## Feed recipes

MVP использует JSON-источник `app/content/incubation.json`, раздел `feed_recipes`. Таблицы `feed_recipes` и `feed_recipe_items` уже созданы миграцией как зарезервированная структура для будущего переноса рецептов в БД. Текущие тесты проверяют JSON-контент как источник рецепта.

## Feed, stock, livestock and flocks

В проекте исторически есть две модели кормов:

- `feed_stocks` и `feed_transactions` - старая карточка корма с ручным остатком, пополнением, списанием, историей и привязкой к поголовью;
- `stock_items`, `stock_transactions`, `mix_productions`, `feeding_assignments`, `flock_feed_assignments` - складовая модель, где покупки и замесы являются операциями склада.

Актуальный пользовательский путь идет через склад:

- кнопка `Добавить корм` ведет в `stock:purchase`;
- `Смесь` считает доступные замесы по складу;
- ингредиенты списываются со склада, готовая `Смесь для кур` добавляется на склад;
- пользователь сначала выбирает режим записи: `Сделать новый замес сейчас` или `Записать прошлый замес как уже скормленный`; дальше выбираются зерновая основа и количество. Текущий замес открывает чеклист, уже скормленный сразу ведет к выбору даты и записывает прошлый замес без чеклиста;
- стадо получает готовую смесь как основной корм;
- `Корма -> Расчеты` считает дни запаса по готовой смеси и по ингредиентам, которые позволяют произвести новые замесы.

Старые карточки `feed_stocks` остаются для совместимости, истории и тестов. Это одно из мест, где нужна дальнейшая консолидация модели.

Для замесов задним числом миграция `015_stock_mix_already_fed` добавляет `mix_productions.mode`, `mix_productions.produced_at` и `stock_transactions.occurred_at`. `StockService.produce_mix(already_fed=True)` создает `mix_input`, `mix_output` и дополнительное списание готовой смеси, поэтому текущий остаток готовой смеси не увеличивается. `StockService.last_mix_output()` игнорирует `already_fed`, чтобы ежедневная сводка не принимала исторически съеденный замес за свежий запас.

## Ingredient matching

Складовые названия нормализуются в `StockService`: бот сопоставляет пользовательские названия с ингредиентами рецепта. Например:

- `кукуруза дробленая` считается кукурузой;
- `зерносмесь` может заменить пшеницу в зерновой основе;
- `комбикорм щигровский` считается коммерческим комбикормом.

Выбор пшеница/зерносмесь делается по текущим остаткам склада и максимальному числу полных замесов. Цена ингредиента на выбор основы не влияет; она используется только в себестоимости.

## Feeding by cups

`FeedingService.record(cups=...)` переводит кружки в килограммы по составу «Моей смеси» (`feeding_settings.mix_json`, плотность каждого ингредиента в кг/л) и объёму кружки. Для ингредиентов, найденных на складе (`StockService._find_stock_item_by_names`, готовая смесь исключается), создаётся `write_off`, отмена отметки возвращает `manual_adjustment`. Списание помечается моментом записи, а не временем кормления, иначе оно попало бы раньше покупки.

Если владелец взвесил кружку (`feeding_settings.cup_kg`, миграция `021_refinements`), `split_cups` масштабирует все ингредиенты так, чтобы кружка весила ровно столько. Смена объёма кружки или состава сбрасывает вес.

`FeedingService.pace()` возвращает фактический расход: если за 14 дней были отметки с кружками, средний расход в день считается за фактические дни с первой отметки (не больше 7), и по каждому ингредиенту — дни до конца остатка. Если `pace()` не `None`, сводка, «Птицевод» и главная страница сайта показывают дни запаса вместо «готовой смеси» и не требуют назначенных стадам смесей.

## Ledger: losses, eggs out, prices

- `LedgerService.record_loss` уменьшает `bird_groups.bird_count` через `FeedService.update_bird_group` (с фиксацией расхода склада); если выбыли все, группа архивируется. `undo_loss` возвращает количество или возвращает группу из архива.
- `egg_outflows` — продажа/раздача/съели/в инкубатор. Остаток дома считается с первой записи: собрано (`egg_entries`) минус ушло.
- `price_rub` в `stock_transactions` — цена за всю покупку. Цена за кг по ингредиенту — сумма цен трёх последних покупок, делённая на их вес. Стоимость корма считается по `feeding_event_items`.

## Egg storage

Хранение включается, когда у пользователя есть хоть одно место (`egg_places`). `EggService.record_today` после записи сбора вызывает `EggStorage.put`: места перебираются по `priority`, каждое заполняется до `capacity`, остаток ложится в последнее. Правка и удаление записи сбора убирают яйца этой записи (`egg_lots.entry_id`), затем самые новые. `LedgerService.record_outflow` вызывает `take` — самые старые партии из выбранного места или из всех — и пишет `egg_takes`, чтобы `undo_outflow` вернул яйца с прежней датой. Пересчёт при недостаче убирает самые старые, при излишке добавляет партию с выбранным возрастом.

## Care calendar

`care_tasks` создаются по умолчанию при первом обращении (`ensure_defaults`, `INSERT OR IGNORE` по `(user_id, code)`) со сроком «сегодня». `mark_done` ставит `next_due = today + interval_days`; `due_for_reminder` возвращает просроченные задачи, по которым не напоминали последние 3 дня.

## Eggs

Раздел `Яйца` состоит из:

- `egg_entries` - записи ежедневного сбора;
- `hen_laying_exclusions` - временно не несущиеся куры;
- `weather_settings` - город, координаты и источник погоды;
- `daily_weather` - кеш погоды Open-Meteo: сегодня день/ночь, завтра кратко, дневные агрегаты для погодной поправки.

`EggService` считает только взрослые группы поголовья с `role = hens`. Цыплята, петухи и смешанные группы не участвуют в расчете яйценоскости. Временные исключения уменьшают количество активных несушек.

Сбор за несколько дней реализован без новой таблицы: `EggService.preview_multi_day_distribution()` строит распределение по датам, а `record_multi_day_collection()` создает несколько обычных строк `egg_entries`. Ручной период использует указанные `2..30` дней назад от даты фактического сбора, автоматический режим `Не помню период` берет среднее по дням с записями через `average_daily_total()`, считает период как `ceil(total / average)` и выбирает ближайшие пустые дни через `entry_dates_between()` назад от даты фактического сбора.

В Telegram обычный сбор записывает `Сегодня` или `Вчера` (кнопки с обычным числом — медиана за 14 дней ±1, `farm_overview.usual_egg_counts`), а история позволяет исправить количество и дату записи.

Падение яйценоскости (`insights.detect_egg_drop`) сравнивает 3 последних полных дня с 14 днями до них только по дням с записями: забытая запись не считается падением. Web-слой дополнительно умеет добавить запись за конкретную `entry_date`, отредактировать и удалить ошибочную запись.

Погодный API подключен через `OpenMeteoWeatherClient` без отдельного ключа. Бот геокодирует город через Open-Meteo, сохраняет координаты, загружает дневную температуру, осадки, состояние погоды, разрез `день/ночь` и краткий прогноз на завтра. Если прогноз Open-Meteo не ответил, бот пробует fallback `wttr.in` по координатам.

Открытие `Яйца` и `Город и погода` не должно блокироваться сетевым запросом: экран сначала читает сохраненную погоду из SQLite, при устаревшем кеше запускает обновление в фоне и редактирует уже отправленное сообщение после загрузки. `Расчеты` читают только сохраненную погоду.

Погодная поправка к прогнозу яйценоскости намеренно простая и помечается как ориентировочная: она учитывает уличную температуру и сильные осадки, но не заменяет фактические данные по курятнику, освещению, воде и вентиляции.

## Release notices

Обычный деплой не должен слать пользователям сообщение. Решение принимает администратор: после старта бот присылает ему список изменений (`RELEASE_NOTES`) с кнопками `Разослать пользователям` / `Изменить текст` / `Не рассылать` (`app/handlers/admin.py`, `app/keyboards/admin.py`). Workflow собирает `RELEASE_NOTES` из строк `- ...`, добавленных в `docs/CHANGELOG.md` с прошлого деплоя (коммит прошлого деплоя хранится в `RELEASE_COMMIT` в `.env.prod`). Ниже описан старый автоматический режим, который остался для ручных деплоев. Текущая версия, документация и changelog доступны в `Настройки -> О боте`. Ссылка на документацию задается через `DOCS_URL` и по умолчанию ведет на каталог `docs/` в GitHub-репозитории.

Release notice отправляется только если:

- `RELEASE_NOTICE_ENABLED=1`;
- задана `RELEASE_VERSION`;
- `RELEASE_IMPORTANCE` равен `medium`, `major` или `critical`.

`medium` отправляет короткое сообщение о перезапуске с главным меню. `major` и `critical` включают подробности из `RELEASE_NOTES`. Повтор одной версии дедуплицируется через `notification_log`.

Admin startup notice отделен от пользовательских релизных сообщений. Если
`ADMIN_STARTUP_NOTICE_MODE` не равен `off`, бот при старте отправляет короткое
служебное сообщение только `ADMIN_IDS`: факт перезапуска, версию, commit и время
запуска. Режим `once_per_deploy` дедуплицирует это сообщение по commit/deploy id
через `notification_log`; режим `always` полезен только для отладки перезапусков.

## Service heartbeats

Runtime-статус пишется в таблицу `service_heartbeats`. Обязательные сервисы:

- `polling_bot`;
- `reminder_runner`.

В проекте нет API-сервиса, поэтому `api` heartbeat не используется. Внешний
статус-бот должен читать состояние через `scripts/status_probe.py`: скрипт
открывает SQLite в read-only режиме, не отправляет Telegram-сообщения и не
меняет бизнес-данные.

`polling_bot` пишет heartbeat отдельным фоновым loop. `reminder_runner` пишет
heartbeat после успешного цикла напоминаний; если цикл упал, но runner продолжил
работать, heartbeat становится `degraded` с коротким `last_error`.
