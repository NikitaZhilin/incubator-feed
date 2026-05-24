# Architecture Notes

## Notification settings

Единый источник пользовательских настроек уведомлений - таблица `users`:

- `timezone`;
- `notification_time`;
- `notify_incubation`;
- `notify_feed`;
- `notify_post_hatch_care`;
- `notify_service`;
- `is_active`.

Таблица `reminder_settings` сохранена для совместимости с существующими БД. Миграция `006_sync_user_notification_settings` переносит старые `hour/minute/is_enabled` в `users.notification_time` и `users.notify_incubation`. Команда `/remind` обновляет обе модели, но reminder runner читает фактические настройки из `users`.

## Feed recipes

MVP использует JSON-источник `app/content/incubation.json`, раздел `feed_recipes`. Таблицы `feed_recipes` и `feed_recipe_items` уже созданы миграцией как зарезервированная структура для будущего переноса рецептов в БД. Текущие тесты проверяют JSON-контент как источник рецепта.
