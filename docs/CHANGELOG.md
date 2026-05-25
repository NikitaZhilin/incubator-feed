# Changelog

## 2026-05-25

- Добавлены миграции SQLite через `schema_migrations`.
- Добавлены `notification_log`, `analytics_events`, `critical_errors`.
- Добавлены настройки пользователя и пометка неактивных пользователей.
- Добавлены группы птицы, история операций кормов, архивирование кормов и таблицы рецептов.
- Reminder loop пишет журнал уведомлений, не дублирует отправленные события и обрабатывает Telegram blocked/deactivated/network errors.
- Контент инкубации, ухода, disclaimer и рецепт смеси вынесены в JSON с версией.
- Добавлены `/settings`, `/timezone`, `/farm`, `/units`, `/disclaimer`.
- Добавлена `/admin`-статистика, CSV-экспорт и сервисная рассылка с подтверждением.
- Добавлены Docker Compose, systemd-шаблоны, scripts для migrate/backup/restore/check_disk/smoke_start.
- Обновлена документация и тесты.
- Пользовательские `timezone` и `notification_time` стали фактическим источником времени уведомлений.
- Инкубационные уведомления логируются по каждой партии с `batch_id` и event key вида `incubation:batch_ID:day_N:DATE`.
- Добавлены post-hatch-care reminders с дедупликацией через `notification_log`.
- Feed reminders учитывают `is_active` и `notify_feed`.
- Добавлен пользовательский сценарий групп птицы в разделе кормов.
- Добавлен внешний скрипт `notify_admin_failure.py` и systemd `OnFailure` unit.
- Production больше не читает токен из `id/id.txt`.
- Добавлено уведомление пользователей о новой бета-версии после деплоя: сообщение отправляется основным процессом бота при старте, открывает главное меню и дедуплицируется через `notification_log`.
- В расчете кормов добавлены отдельные количества и нормы расхода для кур/несушек и петухов.
