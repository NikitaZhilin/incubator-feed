from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.keyboards.menu import main_menu_keyboard
from app.services.reminders import classify_telegram_error
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.users import UserRepository


DEFAULT_TESTING_DISCLAIMER = (
    "⚠️ Бот находится в тестировании. Данные могут быть изменены или утеряны."
)

# Telegram limits a message to 4096 characters; keep the change list well below that.
MAX_NOTES_CHARS = 2500


@dataclass(frozen=True)
class ReleaseNoticeResult:
    sent: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True)
class AdminStartupNoticeResult:
    sent: int = 0
    skipped: int = 0
    failed: int = 0


def build_release_notice(version: str, notes: str = "", *, importance: str = "major") -> str:
    version = version.strip()
    importance = importance.strip().lower()
    if importance == "medium":
        return "\n".join(
            [
                f"Бот обновлен до версии {version} и перезапущен.",
                "Спасибо за терпение, извините за доставленные неудобства.",
                "",
                "Главное меню открыто ниже. Подробности: Настройки -> О боте.",
                "",
                DEFAULT_TESTING_DISCLAIMER,
            ]
        )

    lines = [
        f"Важное обновление бота: {escape(version, quote=False)}.",
    ]
    note_lines = format_notes_list(notes)
    if note_lines:
        lines.extend(["", "Что изменилось:"])
        lines.extend(note_lines)
    lines.extend(
        [
            "",
            "Подробнее: Настройки -> О боте.",
            "Главное меню открыто ниже.",
            "",
            DEFAULT_TESTING_DISCLAIMER,
        ]
    )
    return "\n".join(lines)


def release_event_key(version: str, user_id: int) -> str:
    safe_version = re.sub(r"[^0-9A-Za-z._-]+", "_", version.strip())[:120]
    if not safe_version:
        safe_version = "unknown"
    return f"service:release:{safe_version}:user_{user_id}"


def admin_startup_event_key(version: str, admin_id: int, deployment_id: str = "") -> str:
    safe_deployment = re.sub(r"[^0-9A-Za-z._-]+", "_", (deployment_id or version).strip())[:120]
    if not safe_deployment:
        safe_deployment = "unknown"
    return f"service:admin_startup:{safe_deployment}:admin_{admin_id}"


def build_admin_startup_notice(
    *,
    version: str,
    started_at: datetime,
    timezone_name: str,
    commit: str = "",
    notes: str = "",
    offer_release_notice: bool = False,
) -> str:
    version = version.strip() or "не указана"
    lines = [
        "🔧 Служебное уведомление",
        "",
        "Обновление выкатилось, бот перезапущен и доступен.",
        f"Версия: {escape(version, quote=False)}",
    ]
    if commit.strip():
        lines.append(f"Коммит: {escape(commit.strip()[:12], quote=False)}")
    lines.append(f"Запуск: {_format_notice_time(started_at, timezone_name)}")
    if offer_release_notice:
        note_lines = format_notes_list(notes)
        lines.append("")
        if note_lines:
            lines.append("Что обновлено:")
            lines.extend(note_lines)
        else:
            lines.append("Список изменений не найден: допишите его кнопкой «Изменить текст».")
        lines.extend(
            [
                "",
                "Разослать пользователям уведомление о новой версии?",
                "Перед отправкой будет показан текст сообщения.",
            ]
        )
    lines.extend(["", "Сообщение только для администраторов."])
    return "\n".join(lines)


def build_release_preview(version: str, notes: str, *, recipients: int) -> str:
    return "\n".join(
        [
            "👀 Так пользователи увидят уведомление:",
            "",
            "━━━━━━━━━━",
            build_release_notice(version, notes, importance="major"),
            "━━━━━━━━━━",
            "",
            f"Получателей: {recipients}",
            "Отправить?",
        ]
    )


def format_notes_list(notes: str, *, max_chars: int = MAX_NOTES_CHARS) -> list[str]:
    """Return escaped "- item" lines, trimmed to fit into one Telegram message."""
    items = _normalize_notes(notes)
    lines: list[str] = []
    used = 0
    for index, item in enumerate(items):
        line = f"- {escape(item, quote=False)}"
        if used + len(line) > max_chars:
            lines.append(f"…и ещё {len(items) - index} пункт(ов)")
            break
        lines.append(line)
        used += len(line) + 1
    return lines


def count_release_recipients(users: UserRepository) -> int:
    return sum(
        1
        for settings in users.list_users_with_settings()
        if settings.get("is_active", True) and settings.get("notify_service", True)
    )


class ReleaseNotificationService:
    def __init__(
        self,
        *,
        bot,
        users: UserRepository,
        notifications: NotificationRepository,
    ) -> None:
        self.bot = bot
        self.users = users
        self.notifications = notifications

    async def send_release_notice(
        self,
        *,
        version: str,
        notes: str = "",
        importance: str = "major",
        now: datetime | None = None,
    ) -> ReleaseNoticeResult:
        sent = 0
        skipped = 0
        failed = 0
        scheduled_for = now or datetime.now(timezone.utc)
        text = build_release_notice(version, notes, importance=importance)

        for settings in self.users.list_users_with_settings():
            user_id = int(settings["user_id"])
            if not settings.get("is_active", True) or not settings.get("notify_service", True):
                skipped += 1
                continue

            event_key = release_event_key(version, user_id)
            if self.notifications.was_sent(event_key):
                skipped += 1
                continue

            self.notifications.record_attempt(
                user_id=user_id,
                type="service",
                event_key=event_key,
                scheduled_for=scheduled_for,
            )
            try:
                await self.bot.send_message(
                    user_id,
                    text,
                    reply_markup=main_menu_keyboard(settings),
                )
            except Exception as exc:
                error_code = classify_telegram_error(exc)
                self.notifications.mark_failed(
                    event_key,
                    error_code=error_code,
                    error_message=str(exc),
                )
                if error_code in {"blocked", "deactivated"}:
                    self.users.mark_inactive(user_id, error_code)
                failed += 1
                continue

            self.notifications.mark_sent(event_key, scheduled_for)
            sent += 1

        return ReleaseNoticeResult(sent=sent, skipped=skipped, failed=failed)


class AdminStartupNotificationService:
    def __init__(
        self,
        *,
        bot,
        admin_ids: frozenset[int],
        notifications: NotificationRepository,
    ) -> None:
        self.bot = bot
        self.admin_ids = admin_ids
        self.notifications = notifications

    async def send_startup_notice(
        self,
        *,
        version: str,
        started_at: datetime,
        timezone_name: str,
        mode: str = "once_per_deploy",
        deployment_id: str = "",
        commit: str = "",
        notes: str = "",
        reply_markup=None,
        now: datetime | None = None,
    ) -> AdminStartupNoticeResult:
        sent = 0
        skipped = 0
        failed = 0
        mode = mode.strip().lower()
        scheduled_for = now or datetime.now(timezone.utc)
        text = build_admin_startup_notice(
            version=version,
            started_at=started_at,
            timezone_name=timezone_name,
            commit=commit,
            notes=notes,
            offer_release_notice=reply_markup is not None,
        )

        for admin_id in sorted(self.admin_ids):
            event_key = admin_startup_event_key(version, admin_id, deployment_id)
            if mode != "always" and self.notifications.was_sent(event_key):
                skipped += 1
                continue

            self.notifications.record_attempt(
                user_id=admin_id,
                type="service",
                event_key=event_key,
                scheduled_for=scheduled_for,
            )
            try:
                await self.bot.send_message(admin_id, text, reply_markup=reply_markup)
            except Exception as exc:
                error_code = classify_telegram_error(exc)
                self.notifications.mark_failed(
                    event_key,
                    error_code=error_code,
                    error_message=str(exc),
                )
                failed += 1
                continue

            self.notifications.mark_sent(event_key, scheduled_for)
            sent += 1

        return AdminStartupNoticeResult(sent=sent, skipped=skipped, failed=failed)


def _normalize_notes(notes: str) -> list[str]:
    items: list[str] = []
    for raw_line in notes.replace(";", "\n").splitlines():
        item = raw_line.strip().lstrip("-•").strip()
        if item:
            items.append(item)
    return items


def _format_notice_time(value: datetime, timezone_name: str) -> str:
    timezone_label = timezone_name.strip() or "UTC"
    try:
        target_timezone = ZoneInfo(timezone_label)
    except ZoneInfoNotFoundError:
        timezone_label = "UTC"
        target_timezone = timezone.utc

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local_value = value.astimezone(target_timezone)
    return f"{local_value:%d.%m.%Y %H:%M} ({timezone_label})"
