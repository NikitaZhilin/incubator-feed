# Файловые инструкции бота

Бот показывает короткие инструкции через callback `faq:<topic>`. Текст каждой инструкции хранится отдельным markdown-файлом в `app/content/help/`, а не в Telegram-обработчике.

## Как это работает

- Индекс тем находится в `app/services/help_content.py`.
- Для каждой темы задан `title`, кнопка возврата и имя файла.
- `app/handlers/common.py` вызывает `format_help_topic(topic_key)`.
- Файл читается из `app/content/help/<filename>` в UTF-8.
- Если тема добавлена в индекс, но файл отсутствует или пустой, тесты должны это поймать.

## Текущие темы

| Callback | Файл | Что описывает |
| --- | --- | --- |
| `faq:main` | `main.md` | главное меню |
| `faq:poultry_advisor` | `poultry_advisor.md` | раздел `Птицевод` |
| `faq:incubation` | `incubation.md` | инкубация |
| `faq:feeds` | `feeds.md` | корма |
| `faq:stock` | `stock.md` | склад |
| `faq:mix` | `mix.md` | смесь и режимы замеса |
| `faq:stock_history` | `stock_history.md` | история склада |
| `faq:livestock` | `livestock.md` | поголовье и стада |
| `faq:bird_groups` | `bird_groups.md` | группы поголовья |
| `faq:flocks` | `flocks.md` | стада |
| `faq:flock_card` | `flock_card.md` | карточка стада |
| `faq:feed_card` | `feed_card.md` | старая карточка корма |
| `faq:feed_history` | `feed_history.md` | история старой карточки корма |
| `faq:feed_stats` | `feed_stats.md` | расчеты кормов |
| `faq:eggs` | `eggs.md` | яйца |
| `faq:egg_history` | `egg_history.md` | история яиц |
| `faq:egg_exclusions` | `egg_exclusions.md` | временно не несущиеся куры |
| `faq:egg_weather` | `egg_weather.md` | город и погода |
| `faq:settings` | `settings.md` | настройки |
| `faq:settings_sections` | `settings_sections.md` | разделы и уведомления |

## Как добавить инструкцию

1. Добавить markdown-файл в `app/content/help/`.
2. Добавить тему в `HELP_TOPICS` в `app/services/help_content.py`.
3. Добавить кнопку `FAQ` или callback `faq:<topic>` в нужную клавиатуру.
4. Обновить эту таблицу.
5. Запустить `python -B -m pytest tests/test_handlers_helpers.py -q`.

## Правила текста

- Писать коротко и практически: что делает экран, что нажать, что изменится в данных.
- Не дублировать длинное ТЗ. Для подробностей использовать документы из `docs/`.
- Не обещать функцию, если ее нет в текущем коде.
- Если сценарий меняет склад, яйца или партии, явно писать, когда данные реально сохраняются.
