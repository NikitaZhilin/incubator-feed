# План реализации агента "Птицевод-практик"

Дата: 2026-07-09

Связанный документ: `docs/POULTRY_ADVISOR_AGENT.md`.

## 1. Цель реализации

Нужно добавить в существующий Telegram-бот отдельный экспертный слой "Птицевод-практик". Этот слой не заменяет текущие разделы `Корма`, `Яйца`, `Инкубация`, `Поголовье и стада`, а собирает их данные в практические рекомендации:

- что сделать сегодня;
- хватает ли корма и когда нужен замес;
- почему просела яйценоскость;
- что важно по активной инкубации;
- какие симптомы требуют безопасной реакции и обращения к ветеринару.

Главная инженерная идея: **сначала детерминированный советник на существующих данных и правилах, потом, при необходимости, свободный AI-слой для формулировки вопросов**.

## 2. Текущее состояние проекта

В проекте уже есть большая часть учетной и расчетной базы.

| Область | Уже есть | Файлы | Как использовать в агенте |
| --- | --- | --- | --- |
| Склад и смесь | Остатки, покупки, замесы, расчет доступных замесов, история операций | `app/services/stock.py`, `app/storage/repositories/stock.py` | Блок "Корма и замес", предупреждения о дефиците, даты следующего замеса |
| Стада и поголовье | Группы птицы, стада, назначение готовой смеси стаду | `app/services/feeds.py`, `app/storage/repositories/feeds.py` | Расход корма, количество несушек/петухов/цыплят, проверка неполных данных |
| Яйца | Сбор, история, статистика 7/30 дней, исключенные несушки, погода | `app/services/eggs.py`, `app/handlers/eggs.py` | Анализ "мало яиц", подсказки по недостающим данным |
| Инкубация | Партии, статусы, рекомендации по дням, уход после вывода | `app/services/incubation.py`, `app/services/guides.py` | Блок "Инкубация сегодня" и задачи в плане на день |
| Ежедневная сводка | Сбор яиц, вода, корм, остаток смеси, последний замес | `app/services/reminders.py` | Добавить краткий блок советника без дублирования |
| Контент | Инкубационный контент и disclaimer | `app/content/incubation.json`, `app/domain.py` | Не смешивать новый контент с инкубационным; добавить отдельный JSON |
| Меню и настройки | Кнопки разделов и `notify_*` флаги | `app/keyboards/menu.py`, `app/handlers/settings.py`, `app/storage/repositories/users.py` | Добавить раздел "Птицевод" по тому же паттерну |
| Тесты | Сервисы, миграции, helpers, reminder runner, web | `tests/*` | Добавить unit-тесты советника и проверки меню/settings |

## 3. Что является новым

Новые части:

- сервис `PoultryAdvisorService`;
- отдельная база знаний `poultry_advisor.json`;
- Telegram-раздел `Птицевод`;
- безопасный сценарий "Проблема с птицей";
- единый сценарий "План на сегодня";
- краткий блок рекомендаций в ежедневной сводке;
- тесты для экспертных сценариев.

Не нужно на первом этапе:

- новая крупная БД-модель для рекомендаций;
- LLM-интеграция;
- свободный медицинский чат;
- назначение лекарств;
- платные функции;
- отдельный web-раздел.

## 4. Архитектурный принцип

Поток выполнения:

```text
Telegram callback
  -> app/handlers/poultry_advisor.py
  -> PoultryAdvisorService
  -> существующие сервисы: EggService, StockService, FeedService, IncubationService
  -> app/content/poultry_advisor.json
  -> готовый текст + keyboard
```

Сервис советника не должен напрямую отправлять сообщения в Telegram. Он должен возвращать готовый текст или структурированный результат. Это позволит тестировать логику без Telegram.

## 5. Новые файлы

Обязательные:

- `app/services/poultry_advisor.py`
- `app/handlers/poultry_advisor.py`
- `app/keyboards/poultry_advisor.py`
- `app/content/poultry_advisor.json`
- `tests/test_poultry_advisor.py`
- `tests/test_poultry_advisor_content.py`
- `tests/test_poultry_advisor_keyboards.py`

Вероятные:

- `app/storage/migrations/014_poultry_advisor_settings.py`
- обновление `app/storage/migrations/__init__.py`
- обновление `app/storage/repositories/users.py`
- обновление `app/keyboards/menu.py`
- обновление `app/keyboards/__init__.py`, если проект начнет экспортировать клавиатуры явно;
- обновление `app/handlers/__init__.py`
- обновление `app/handlers/settings.py`
- обновление `app/main.py`
- обновление `app/services/reminders.py`
- обновление `tests/test_handlers_helpers.py`
- обновление `tests/test_migrations_and_content.py`
- обновление `tests/test_reminder_runner.py`

Документация:

- обновить `docs/USER_COMMANDS.md`;
- обновить `docs/ROADMAP.md`;
- обновить `README.md`, если раздел будет включен в публичное описание;
- при релизе обновить `docs/CHANGELOG.md`.

## 6. Данные и контент

### 6.1. Новый JSON-контент

Файл: `app/content/poultry_advisor.json`.

Рекомендуемая структура:

```json
{
  "version": "2026.07-mvp",
  "persona": {
    "name": "Птицевод-практик",
    "short_description": "Практический помощник по уходу за курами"
  },
  "disclaimer": "Советы справочные и не заменяют ветеринарный осмотр.",
  "red_flags": [
    {
      "code": "mass_mortality",
      "title": "Массовый падеж",
      "safe_action": "Изолируйте больных птиц, обеспечьте воду и обратитесь к ветеринару."
    }
  ],
  "daily_care": {
    "base": [
      "Проверить воду утром и вечером.",
      "Проверить корм и чистоту кормушек.",
      "Осмотреть птицу: активность, дыхание, гребень, помет."
    ],
    "eggs": [
      "Записать сбор яиц за день."
    ]
  },
  "seasonal_care": {
    "cold": [],
    "heat": [],
    "wet": [],
    "short_day": []
  },
  "feeding": {
    "missing_assignment": "Стаду не назначена готовая смесь, поэтому расход не считается.",
    "low_mix_days_threshold": 2,
    "warning_mix_days_threshold": 7
  },
  "eggs": {
    "drop_percent_threshold": 20,
    "minimum_recorded_days": 3
  },
  "health_questions": [
    "Одна птица или несколько?",
    "Птица пьет воду?",
    "Есть ли тяжелое дыхание, кровь, судороги или сильная слабость?"
  ]
}
```

### 6.2. Требования к контенту

- JSON должен валидироваться тестом.
- Версия контента обязательна.
- Красные флаги должны иметь `code`, `title`, `safe_action`.
- Нельзя хранить лекарственные схемы и дозировки.
- Тексты должны быть короткими, потому что Telegram-сообщение должно читаться быстро.
- Контент советника не нужно добавлять в `app/domain.py` глобальной константой, если это приведет к лишней связанности. Лучше сделать локальный loader в `app/services/poultry_advisor.py` или отдельную небольшую функцию.

## 7. Настройки и миграция

### 7.1. Зачем нужна настройка

Сейчас крупные разделы можно включать и выключать в настройках. Чтобы `Птицевод` вел себя так же, нужно добавить флаг:

```text
notify_poultry_advisor INTEGER NOT NULL DEFAULT 1
```

Несмотря на префикс `notify_`, в текущем проекте эти поля управляют и уведомлениями, и видимостью разделов. Лучше сохранить существующий стиль, чем вводить вторую систему feature flags.

### 7.2. Миграция

Файл:

```text
app/storage/migrations/014_poultry_advisor_settings.py
```

Содержание миграции:

- добавить колонку `notify_poultry_advisor` в `users`;
- default `1`;
- использовать существующий helper `add_column_if_missing`, как в других миграциях.

Обновить:

- `app/storage/migrations/__init__.py` - добавить `014_poultry_advisor_settings`;
- `tests/test_migrations_and_content.py` - проверить наличие колонки.

### 7.3. UserRepository

Файл:

```text
app/storage/repositories/users.py
```

Изменения:

- добавить поле в SELECT для `get_settings`;
- добавить поле в SELECT для `list_users_with_settings`;
- добавить default `notify_poultry_advisor=True`;
- добавить поле в список разрешенных обновлений;
- корректно читать старые строки, если миграция еще не применена в тестовой заготовке.

### 7.4. Settings UI

Файлы:

- `app/handlers/settings.py`
- `app/keyboards/menu.py`

Изменения:

- добавить `notify_poultry_advisor` в allow-list `settings:toggle:*`;
- добавить строку в `_format_sections`;
- добавить кнопку в `settings_sections_keyboard`;
- использовать `_enabled(settings, "notify_poultry_advisor")` для показа кнопки "Птицевод" в главном меню.

Тесты:

- `test_settings_sections_keyboard_contains_poultry_advisor_toggle`;
- `test_main_menu_hides_poultry_advisor_when_disabled`;
- `test_user_settings_default_enables_poultry_advisor`.

## 8. Сервис советника

Файл:

```text
app/services/poultry_advisor.py
```

### 8.1. Конструктор

Рекомендуемый конструктор:

```python
class PoultryAdvisorService:
    def __init__(
        self,
        *,
        incubation_service: IncubationService,
        feed_service: FeedService,
        egg_service: EggService,
        stock_service: StockService,
        content: dict | None = None,
        timezone_name: str = "Europe/Moscow",
    ) -> None:
        ...
```

Причина:

- агент агрегирует уже существующие сервисы;
- не нужен прямой доступ к SQLite;
- тесты смогут передавать fake services или temp DB.

### 8.2. Результат работы сервиса

На первом этапе достаточно возвращать строки:

```python
def build_today_plan(...) -> str
def build_feed_advice(...) -> str
def build_mix_timing_advice(...) -> str
def build_egg_drop_advice(...) -> str
def build_incubation_today_advice(...) -> str
def build_health_red_flags_advice(...) -> str
def build_daily_summary_advice_lines(...) -> list[str]
```

Если ответы начнут усложняться, можно добавить dataclass:

```python
@dataclass(frozen=True)
class AdvisorResponse:
    title: str
    lines: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
```

Для MVP проще начать со строк и списков строк, чтобы не усложнять форматирование.

### 8.3. Общие правила форматирования

- Сообщение должно быть коротким, но полезным.
- В начале - вывод.
- Затем - 3-7 действий.
- Если данных не хватает, явно писать, каких именно.
- Не использовать HTML, если не требуется.
- Не добавлять длинные лекции.
- Не использовать медицинские диагнозы.
- В рекомендациях с риском добавлять безопасное действие.

## 9. Сценарий "План на сегодня"

Метод:

```python
build_today_plan(user_id: int, *, local_now: datetime, now_utc: datetime | None = None) -> str
```

### 9.1. Источники данных

- `EggService.stats(user_id, today=local_now.date())`
- `StockService.list_estimates(user_id, now=now_utc)`
- `StockService.best_available_mix_plan(user_id=user_id, now=now_utc)`
- `StockService.list_flock_reports(user_id, now=now_utc)`
- `IncubationService.get_user_statuses(user_id)`
- `IncubationService.get_user_settings(user_id)`
- `poultry_advisor.json`

### 9.2. Алгоритм

1. Начать с заголовка:

   ```text
   План птицевода на 2026-07-09:
   ```

2. Добавить базовые ежедневные задачи из `daily_care.base`:

   - вода;
   - корм;
   - осмотр птицы;
   - подстилка/сухость.

3. Добавить задачу по яйцам:

   - если `today_eggs == 0`, написать "Записать сбор яиц за день";
   - если записи уже есть, написать "Яйца сегодня уже записаны: N шт.".

4. Добавить блок смеси:

   - найти все `StockEstimate`, где `item.kind == "finished_mix"`;
   - посчитать суммарный остаток;
   - посчитать суммарный дневной расход;
   - если расход не назначен, написать, что стадам нужно назначить смесь;
   - если `days_left <= 2`, отметить как срочно;
   - если `days_left <= 7`, предупредить;
   - если смеси нет, написать, что нужно сделать замес или добавить готовую смесь.

5. Добавить блок возможного замеса:

   - вызвать `best_available_mix_plan`;
   - если `max_mix_count >= 1`, показать, сколько замесов можно сделать;
   - если `max_mix_count < 1`, показать до 5 недостающих ингредиентов.

6. Добавить блок инкубации:

   - получить активные статусы;
   - для каждой партии взять первые 1-2 рекомендации;
   - ограничить блок 3 активными партиями, чтобы сообщение не распухало.

7. Добавить предупреждения по неполным данным:

   - нет несушек, но пользователь ведет яйца;
   - есть стада без назначенной смеси;
   - есть готовая смесь, но нет расхода;
   - нет записей яиц за последние дни.

### 9.3. Критерии приемки

- Если данных нет, пользователь получает понятный стартовый план.
- Если есть стадо и смесь, показывается срок запаса.
- Если есть активная инкубация, в плане есть сегодняшняя задача.
- Сообщение помещается в один Telegram message.
- Сервис тестируется без Telegram.

### 9.4. Тесты

- `test_today_plan_without_data_explains_first_steps`
- `test_today_plan_includes_egg_recording_task`
- `test_today_plan_warns_when_finished_mix_low`
- `test_today_plan_includes_possible_mix_count`
- `test_today_plan_includes_incubation_recommendation`
- `test_today_plan_reports_missing_flock_feed_assignment`

## 10. Сценарий "Корма и замес"

Методы:

```python
build_feed_advice(user_id: int, *, now_utc: datetime | None = None) -> str
build_mix_timing_advice(user_id: int, *, now_utc: datetime | None = None) -> str
```

### 10.1. Что должен отвечать сценарий

Ответ должен покрывать:

- сколько готовой смеси осталось;
- какой дневной расход;
- на сколько дней хватит;
- сколько замесов можно сделать по складу;
- какой ингредиент ограничивает следующий замес;
- что купить в первую очередь.

### 10.2. Источники данных

- `StockService.list_estimates`;
- `StockService.list_flock_reports`;
- `StockService.best_available_mix_plan`;
- `StockService.last_mix_output`;
- `StockService.estimate_item_exhausted_at`.

### 10.3. Алгоритм для "Сколько купить корма"

1. Получить отчеты по стадам.
2. Если стад нет:

   ```text
   Я не могу посчитать закупку: сначала создайте стадо и назначьте ему готовую смесь.
   ```

3. Для каждого стада показать:

   - название стада;
   - дневной расход;
   - сколько дней осталось готовой смеси;
   - сколько дней получится с учетом возможного замеса.

4. Получить лучший план замеса.
5. Если замес невозможен:

   - вывести недостающие ингредиенты;
   - отсортировать по `missing_kg` по убыванию или оставить порядок рецепта.

6. Если замес возможен:

   - показать количество возможных замесов;
   - показать примерный выход в кг.

### 10.4. Алгоритм для "Когда делать замес"

1. Найти остаток готовой смеси.
2. Найти дневной расход.
3. Если расход равен 0, попросить назначить смесь стаду.
4. Если остаток равен 0, написать "замес нужен сейчас".
5. Если `days_left <= 2`, написать "сделать замес сегодня/завтра".
6. Если `days_left > 2`, показать дату ориентировочного исчерпания:

   ```text
   При текущем расходе смесь закончится примерно 2026-07-12.
   ```

7. Добавить подсказку, возможен ли замес по складу.

### 10.5. Тесты

- `test_feed_advice_requires_flock_when_no_flocks`
- `test_feed_advice_lists_missing_ingredients`
- `test_feed_advice_shows_possible_mix_count`
- `test_mix_timing_says_now_when_no_finished_mix_left`
- `test_mix_timing_uses_daily_usage_for_days_left`

## 11. Сценарий "Мало яиц"

Метод:

```python
build_egg_drop_advice(user_id: int, *, today: date | None = None) -> str
```

### 11.1. Источники данных

- `EggService.stats`;
- `EggService.history(days=30)`;
- `EggService.total_laying_hens`;
- `EggService.list_open_exclusions`;
- `EggService.get_daily_weather`.

### 11.2. Алгоритм

1. Получить статистику.
2. Если нет несушек:

   ```text
   В поголовье нет групп с ролью "несушки". Добавьте несушек, иначе я не смогу оценить яйценоскость.
   ```

3. Если записей меньше 3 дней:

   ```text
   Данных пока мало. Записывайте яйца хотя бы 3-7 дней, тогда сравнение будет полезнее.
   ```

4. Сравнить среднее за 7 дней и среднее за 30 дней.
5. Если падение больше порога из контента, отметить просадку:

   ```text
   За 7 дней среднее ниже месячного примерно на N%.
   ```

6. Проверить исключения:

   - наседки;
   - линька;
   - болезнь/восстановление;
   - уход за цыплятами.

7. Проверить погоду:

   - если есть `weather_note`, включить короткое объяснение;
   - не делать погоду единственной причиной.

8. Дать список проверок:

   - световой день;
   - вода;
   - белок и кальций;
   - ракушка/минералы;
   - стресс;
   - сырость;
   - паразиты/самочувствие без диагноза.

### 11.3. Ответ не должен

- обещать точный возврат яйценоскости;
- назначать препараты;
- говорить, что причина точно найдена;
- игнорировать нехватку данных.

### 11.4. Тесты

- `test_egg_drop_requires_hens`
- `test_egg_drop_requires_enough_history`
- `test_egg_drop_detects_week_vs_month_drop`
- `test_egg_drop_mentions_active_exclusions`
- `test_egg_drop_mentions_weather_note_without_overclaiming`

## 12. Сценарий "Инкубация сегодня"

Метод:

```python
build_incubation_today_advice(user_id: int, *, today: date | None = None) -> str
```

### 12.1. Источники данных

- `IncubationService.get_user_statuses`;
- `BatchStatus.recommendations`;
- `BatchStatus.stage`;
- `BatchStatus.days_left`;
- `app/content/incubation.json`.

### 12.2. Алгоритм

1. Получить активные партии.
2. Если партий нет, предложить создать партию или открыть режимы.
3. Для каждой партии:

   - название;
   - день инкубации;
   - стадия;
   - дней до вывода;
   - первые 3 рекомендации.

4. Для партий в lockdown/перед выводом усилить важность:

   - не переворачивать после нужного дня;
   - следить за влажностью;
   - не открывать инкубатор без необходимости.

5. После вывода направлять в существующий уход после вывода.

### 12.3. Тесты

- `test_incubation_today_without_batches_explains_next_step`
- `test_incubation_today_includes_batch_day_and_stage`
- `test_incubation_today_limits_recommendations`
- `test_incubation_today_highlights_lockdown`

## 13. Сценарий "Проблема с птицей"

Этот сценарий должен быть максимально безопасным.

### 13.1. MVP-подход

Не делать свободную диагностику. Сделать короткий triage через кнопки и безопасный текст.

Кнопки:

- "Есть красные флаги"
- "Нет красных флагов"
- "Что считается красным флагом"
- "Назад"

### 13.2. Красные флаги

Использовать список из `poultry_advisor.json`:

- массовый падеж;
- кровь;
- судороги;
- тяжелое дыхание;
- посинение гребня;
- резкий отказ от воды или корма у нескольких птиц;
- сильная вялость у нескольких птиц;
- подозрение на инфекцию.

### 13.3. Ответ при красных флагах

Должен быть примерно таким:

```text
Это ситуация риска.

Что сделать сейчас:
1. Изолировать больную птицу от стада.
2. Дать доступ к чистой воде.
3. Проверить тепло, сухость и вентиляцию.
4. Убрать подозрительный корм.
5. Связаться с ветеринаром.

Я не назначаю лекарства и дозировки по переписке.
```

### 13.4. Ответ без красных флагов

Дать наблюдательный чек-лист:

- вода;
- корм;
- подстилка;
- температура;
- поведение;
- помет;
- наличие травм;
- не смешивать слабую птицу с агрессивной группой.

### 13.5. FSM

Для MVP можно обойтись без сложного FSM:

- callback `advisor:health` показывает меню;
- callback `advisor:health:red_flags` показывает срочный безопасный ответ;
- callback `advisor:health:no_red_flags` показывает чек-лист наблюдения;
- свободный ввод симптомов не нужен в MVP.

Если все же добавлять ввод текста, нужен `HealthProblemFlow.description`, но ответ должен быть осторожным и не диагностическим.

### 13.6. Тесты

- `test_health_red_flags_response_recommends_vet`
- `test_health_red_flags_response_does_not_include_medicine_dosage`
- `test_health_no_red_flags_gives_observation_checklist`

## 14. Telegram-интерфейс

### 14.1. Клавиатуры

Файл:

```text
app/keyboards/poultry_advisor.py
```

Клавиатуры:

```python
advisor_menu_keyboard()
advisor_back_keyboard()
advisor_health_keyboard()
advisor_feed_keyboard()
```

Главное меню раздела:

- `План на сегодня` -> `advisor:today`
- `Корма и замес` -> `advisor:feed`
- `Мало яиц` -> `advisor:eggs_drop`
- `Инкубация сегодня` -> `advisor:incubation_today`
- `Проблема с птицей` -> `advisor:health`
- `Назад` -> `menu:home`

### 14.2. Главное меню

Файл:

```text
app/keyboards/menu.py
```

Добавить кнопку в `main_menu_keyboard`:

```python
if _enabled(settings, "notify_poultry_advisor"):
    feature_row.append(InlineKeyboardButton(text="🐔 Птицевод", callback_data="advisor:menu"))
```

Порядок кнопок лучше сделать:

1. `Корма`
2. `Инкубация`
3. `Яйца`
4. `Птицевод`

Если ряд становится слишком широким, перенести `Птицевод` отдельной строкой под основными разделами. Для Telegram это может быть удобнее, чем четыре кнопки в одной строке.

### 14.3. Handler

Файл:

```text
app/handlers/poultry_advisor.py
```

Callbacks:

- `advisor:menu`
- `advisor:today`
- `advisor:feed`
- `advisor:mix_timing`
- `advisor:eggs_drop`
- `advisor:incubation_today`
- `advisor:health`
- `advisor:health:red_flags`
- `advisor:health:no_red_flags`

Каждый handler:

- очищает FSM state;
- вызывает `PoultryAdvisorService`;
- отправляет текст;
- прикладывает подходящую клавиатуру;
- отвечает на callback.

### 14.4. Регистрация router

Файл:

```text
app/handlers/__init__.py
```

Добавить:

```python
from app.handlers.poultry_advisor import router as poultry_advisor_router
...
dispatcher.include_router(poultry_advisor_router)
```

Порядок регистрации:

- после `settings_router` и `admin_router`;
- до или после доменных разделов не критично, потому что callback namespace отдельный: `advisor:*`.

## 15. Инициализация сервиса

Файл:

```text
app/main.py
```

Добавить импорт:

```python
from app.services.poultry_advisor import PoultryAdvisorService
```

Создать сервис после существующих сервисов:

```python
poultry_advisor_service = PoultryAdvisorService(
    incubation_service=incubation_service,
    feed_service=feed_service,
    egg_service=egg_service,
    stock_service=stock_service,
    timezone_name=config.timezone,
)
```

Положить в dispatcher:

```python
dispatcher["poultry_advisor_service"] = poultry_advisor_service
```

Для `ReminderRunner` либо:

- передать `poultry_advisor_service` как optional dependency;
- либо не трогать ежедневную сводку в первом PR и добавить интеграцию отдельным этапом.

Рекомендация: сначала внедрить раздел меню, потом отдельным маленьким изменением добавить сводку. Так проще проверять.

## 16. Ежедневная сводка

Файл:

```text
app/services/reminders.py
```

### 16.1. Цель

Добавить в существующую сводку 1-3 строки советника. Не создавать отдельную рассылку.

### 16.2. Подход

Добавить optional dependency:

```python
poultry_advisor_service: PoultryAdvisorService | None = None
```

В `build_daily_summary_message` после блока "Готовая смесь" добавить:

```text

Совет птицевода:
- ...
```

Только если `build_daily_summary_advice_lines` вернул непустой список.

### 16.3. Что включать

В сводку можно включать только важное:

- смеси осталось 0-2 дня;
- не назначена смесь стаду;
- нет записей яиц сегодня;
- активная инкубация требует действия сегодня;
- есть неполные данные, мешающие расчету.

Не включать:

- длинные сезонные лекции;
- полный анализ яйценоскости;
- медицинский сценарий;
- больше 3 строк.

### 16.4. Настройки

Если добавлен `notify_poultry_advisor`, дневной блок советника должен уважать этот флаг:

- если выключен, блок не показывать;
- при отсутствии поля считать включенным для обратной совместимости.

### 16.5. Тесты

- `test_daily_summary_includes_poultry_advisor_critical_lines`
- `test_daily_summary_omits_poultry_advisor_when_no_actionable_lines`
- `test_daily_summary_respects_disabled_poultry_advisor_setting`

## 17. FAQ и справка

Текущая справка бота вынесена из обработчиков в отдельные markdown-файлы:

```text
app/services/help_content.py
app/content/help/poultry_advisor.md
```

`app/services/help_content.py` хранит реестр тем, заголовки и кнопки возврата.
Текст раздела `Птицевод` редактируется в `app/content/help/poultry_advisor.md`.

Содержание:

- раздел не заменяет учет;
- он собирает данные из кормов, яиц и инкубации;
- для расчетов нужны стада, смесь, несушки и записи яиц;
- медицинские вопросы не являются диагнозом.

Кнопка FAQ в `advisor_menu_keyboard` ведет на тему `poultry_advisor`.

Тест:

- `test_faq_topics_are_backed_by_markdown_files`.

## 18. Тестовая стратегия

### 18.1. Unit-тесты сервиса

Файл:

```text
tests/test_poultry_advisor.py
```

Лучший подход - использовать временную SQLite БД, как в существующих тестах:

- `Database(temp_path).initialize()`;
- `UserRepository`;
- `FeedRepository`;
- `StockRepository`;
- `EggRepository`;
- `BatchRepository`;
- `ReminderRepository`;
- сервисы поверх репозиториев.

Так тесты будут проверять реальные связи между сервисами.

### 18.2. Content tests

Файл:

```text
tests/test_poultry_advisor_content.py
```

Проверки:

- JSON читается;
- есть `version`;
- есть `disclaimer`;
- есть `red_flags`;
- у каждого red flag есть `code`, `title`, `safe_action`;
- нет запрещенных слов/паттернов для дозировок, например `мг/кг`, `антибиотик`, если они не находятся в безопасном disclaimer-контексте.

### 18.3. Keyboard tests

Файл:

```text
tests/test_poultry_advisor_keyboards.py
```

Проверки:

- меню содержит все MVP-кнопки;
- callback namespace начинается с `advisor:`;
- есть возврат в главное меню;
- есть FAQ.

### 18.4. Handler helper tests

Если форматирование вынесено в helper-функции, добавить в `tests/test_handlers_helpers.py`.

Проверки:

- главное меню показывает `Птицевод`, когда флаг включен;
- главное меню скрывает `Птицевод`, когда флаг выключен;
- настройки показывают toggle.

### 18.5. Migration tests

Файл:

```text
tests/test_migrations_and_content.py
```

Добавить:

- колонка `notify_poultry_advisor` появляется на чистой БД;
- legacy БД мигрирует без потери пользователя;
- default равен `1`.

### 18.6. Reminder tests

Файл:

```text
tests/test_reminder_runner.py
```

Добавить тесты только после интеграции советника в сводку.

## 19. Порядок реализации по PR/коммитам

### PR 1. Контент, миграция и настройки

Файлы:

- `app/content/poultry_advisor.json`
- `app/storage/migrations/014_poultry_advisor_settings.py`
- `app/storage/migrations/__init__.py`
- `app/storage/repositories/users.py`
- `app/keyboards/menu.py`
- `app/keyboards/poultry_advisor.py`
- `app/handlers/settings.py`
- `tests/test_migrations_and_content.py`
- `tests/test_handlers_helpers.py`
- `tests/test_poultry_advisor_content.py`
- `tests/test_poultry_advisor_keyboards.py`

Задачи:

1. Добавить JSON-контент.
2. Добавить миграцию.
3. Расширить user settings.
4. Добавить кнопку `Птицевод` в главное меню.
5. Добавить клавиатуру раздела.
6. Добавить toggle в настройки.
7. Покрыть тестами.

Критерий готовности:

- тесты миграции проходят;
- главное меню и настройки знают о разделе;
- сам раздел еще может показывать заглушку.

### PR 2. Сервис и сценарий "План на сегодня"

Файлы:

- `app/services/poultry_advisor.py`
- `app/handlers/poultry_advisor.py`
- `app/handlers/__init__.py`
- `app/main.py`
- `tests/test_poultry_advisor.py`

Задачи:

1. Создать `PoultryAdvisorService`.
2. Реализовать loader контента.
3. Реализовать `build_today_plan`.
4. Реализовать callback `advisor:menu`.
5. Реализовать callback `advisor:today`.
6. Зарегистрировать router.
7. Подключить service в dispatcher.
8. Добавить тесты для пустого и заполненного хозяйства.

Критерий готовности:

- пользователь открывает `Птицевод -> План на сегодня`;
- ответ использует яйца, смесь и инкубацию, если они есть;
- без данных ответ не падает и объясняет первый шаг.

### PR 3. Сценарии кормов и замеса

Файлы:

- `app/services/poultry_advisor.py`
- `app/handlers/poultry_advisor.py`
- `app/keyboards/poultry_advisor.py`
- `tests/test_poultry_advisor.py`

Задачи:

1. Реализовать `build_feed_advice`.
2. Реализовать `build_mix_timing_advice`.
3. Добавить callbacks `advisor:feed` и `advisor:mix_timing`.
4. Добавить кнопки внутри раздела кормов.
5. Проверить edge cases:
   - нет стад;
   - есть стадо без смеси;
   - есть смесь без расхода;
   - замес невозможен;
   - замес возможен.

Критерий готовности:

- бот говорит, когда нужен замес;
- бот показывает, чего не хватает для замеса;
- бот не дублирует полный UX раздела `Корма`, а дает управленческий вывод.

### PR 4. Сценарий "Мало яиц"

Файлы:

- `app/services/poultry_advisor.py`
- `app/handlers/poultry_advisor.py`
- `tests/test_poultry_advisor.py`

Задачи:

1. Реализовать `build_egg_drop_advice`.
2. Добавить callback `advisor:eggs_drop`.
3. Добавить проверку нехватки данных.
4. Добавить сравнение 7/30 дней.
5. Добавить учет временно не несущихся кур.
6. Добавить осторожную погодную подсказку.

Критерий готовности:

- пользователь видит не просто статистику, а список вероятных проверок;
- при нехватке данных бот говорит, что именно нужно заполнить;
- нет медицинских диагнозов.

### PR 5. Сценарий "Инкубация сегодня"

Файлы:

- `app/services/poultry_advisor.py`
- `app/handlers/poultry_advisor.py`
- `tests/test_poultry_advisor.py`

Задачи:

1. Реализовать `build_incubation_today_advice`.
2. Добавить callback `advisor:incubation_today`.
3. Ограничить количество партий в одном сообщении.
4. Добавить акценты на lockdown и вывод.

Критерий готовности:

- активные партии попадают в советника;
- пользователь видит сегодняшнюю задачу по каждой важной партии;
- нет конфликта с существующим разделом `Инкубация`.

### PR 6. Сценарий "Проблема с птицей"

Файлы:

- `app/services/poultry_advisor.py`
- `app/handlers/poultry_advisor.py`
- `app/keyboards/poultry_advisor.py`
- `tests/test_poultry_advisor.py`

Задачи:

1. Реализовать safe health responses.
2. Добавить callbacks:
   - `advisor:health`;
   - `advisor:health:red_flags`;
   - `advisor:health:no_red_flags`.
3. Добавить проверку, что нет лекарственных дозировок.
4. Добавить disclaimer.

Критерий готовности:

- при рисках бот направляет к безопасным действиям;
- бот не ставит диагноз;
- бот не назначает лекарства.

### PR 7. Ежедневная сводка

Файлы:

- `app/services/reminders.py`
- `app/main.py`
- `tests/test_reminder_runner.py`

Задачи:

1. Передать `PoultryAdvisorService` в `ReminderRunner`.
2. Реализовать `build_daily_summary_advice_lines`.
3. Добавить блок "Совет птицевода" в daily summary.
4. Ограничить блок 3 строками.
5. Уважать `notify_poultry_advisor`.

Критерий готовности:

- сводка остается короткой;
- советник появляется только при полезном действии;
- нет отдельной рассылки.

### PR 8. Документация и приемка

Файлы:

- `README.md`
- `docs/USER_COMMANDS.md`
- `docs/ROADMAP.md`
- `docs/CHANGELOG.md`

Задачи:

1. Описать раздел `Птицевод`.
2. Добавить пользовательские сценарии.
3. Обновить roadmap: перенести реализованные пункты.
4. Добавить release note.
5. Пройти ручной checklist.

Критерий готовности:

- пользователь понимает, что делает раздел;
- разработчик видит, какие сценарии уже реализованы;
- документация не обещает LLM-чат, если его нет.

## 20. Ручная приемка

Проверять на чистой dev-БД и на БД с тестовыми данными.

### 20.1. Чистая БД

Шаги:

1. Запустить бота на новой БД.
2. Открыть главное меню.
3. Убедиться, что есть кнопка `Птицевод`.
4. Открыть `Птицевод -> План на сегодня`.
5. Проверить, что бот не падает и объясняет первые шаги.

Ожидаемо:

- нет traceback;
- нет пустого сообщения;
- есть подсказки создать поголовье/стадо/записать яйца.

### 20.2. БД с кормами и стадами

Данные:

- группа несушек;
- стадо;
- назначенная готовая смесь;
- складские ингредиенты;
- один произведенный замес.

Проверки:

- `План на сегодня` показывает остаток смеси;
- `Корма и замес` показывает срок запаса;
- `Когда замес` дает дату или срочность;
- при нехватке ингредиентов бот перечисляет недостающие.

### 20.3. БД с яйцами

Данные:

- несушки;
- записи яиц за 30 дней;
- искусственная просадка за последние 7 дней;
- одна временно исключенная несушка.

Проверки:

- `Мало яиц` видит просадку;
- упоминает исключение;
- дает список проверок;
- не ставит диагноз.

### 20.4. БД с инкубацией

Данные:

- активная партия кур;
- партия близко к lockdown;
- партия после вывода, если сценарий покрывает уход.

Проверки:

- `Инкубация сегодня` показывает день и задачи;
- lockdown-партия имеет заметный акцент;
- рекомендации не длиннее разумного.

### 20.5. Здоровье птицы

Проверки:

- `Проблема с птицей -> Есть красные флаги` рекомендует изоляцию и ветеринара;
- `Нет красных флагов` дает чек-лист наблюдения;
- нет названий лекарств, дозировок и обещаний лечения.

## 21. Автоматическая проверка

Минимальный набор команд перед завершением каждого PR:

```powershell
python -B -m pytest tests/test_poultry_advisor.py -q
python -B -m pytest tests/test_poultry_advisor_content.py -q
python -B -m pytest tests/test_handlers_helpers.py -q
python -B -m pytest tests/test_migrations_and_content.py -q
python -B scripts\smoke_start.py
```

Перед релизом:

```powershell
python -B -m pytest -q
```

Если локальная среда не готова, сначала проверить `.venv`, зависимости из `requirements.txt` и `requirements-dev.txt`, затем повторить.

## 22. Edge cases

Обязательно учесть:

- у пользователя нет ни одного стада;
- стадо есть, но нет групп;
- группы есть, но нет несушек;
- взрослые куры заведены как `mixed`, а не `hens`;
- стаду не назначена смесь;
- готовая смесь есть, но расход равен 0;
- ингредиенты названы синонимами;
- нет истории яиц;
- история яиц есть только за 1-2 дня;
- погодный сервис не обновлялся;
- много активных партий инкубации;
- пользователь отключил раздел в настройках;
- Telegram callback устарел;
- пользователь заблокировал бота.

## 23. Ошибки и fallback

Сервис советника не должен выбрасывать исключение пользователю из-за частичной проблемы в одном разделе.

Правило:

- если сломался расчет корма, показать остальные блоки и строку "Расчет кормов сейчас недоступен";
- если нет погоды, анализ яиц работает без погоды;
- если нет инкубации, план все равно показывает уход, яйца и корма;
- если нет контента, сервис должен иметь безопасный минимальный fallback или падать на старте smoke test, а не в пользовательском сценарии.

## 24. Нефункциональные требования

- Не замедлять открытие главного меню.
- Не делать сетевых запросов при открытии `Птицевод`, кроме уже существующих явных обновлений погоды.
- Не отправлять новые автоматические сообщения без необходимости.
- Не хранить персональные советы в БД в MVP.
- Не добавлять LLM API key в MVP.
- Не смешивать veterinary disclaimer с обычным ежедневным планом, кроме сценария здоровья.
- Сохранять совместимость с Windows PowerShell и SQLite.

## 25. Definition of Done для MVP

MVP считается завершенным, когда:

- есть кнопка `Птицевод` в главном меню;
- раздел можно отключить в настройках;
- работает `План на сегодня`;
- работает `Корма и замес`;
- работает `Когда замес`;
- работает `Мало яиц`;
- работает `Инкубация сегодня`;
- работает безопасный сценарий `Проблема с птицей`;
- ежедневная сводка содержит короткий блок советника только при полезных предупреждениях;
- все новые сценарии покрыты unit-тестами;
- миграции проходят на чистой и legacy БД;
- `python -B scripts\smoke_start.py` проходит;
- документация обновлена;
- бот не назначает лекарства и не ставит диагнозы.

## 26. Рекомендуемый первый шаг разработки

Начать с PR 1 и PR 2:

1. Добавить `poultry_advisor.json`.
2. Добавить кнопку и настройку раздела.
3. Создать `PoultryAdvisorService`.
4. Реализовать только `План на сегодня`.

Это даст видимый результат быстро и проверит главную архитектурную связку. После этого кормовые, яичные, инкубационные и health-сценарии можно добавлять независимо.
