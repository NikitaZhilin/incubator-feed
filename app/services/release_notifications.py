from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from app.keyboards.menu import main_menu_keyboard
from app.services.reminders import classify_telegram_error
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.users import UserRepository


DEFAULT_TESTING_DISCLAIMER = (
    "⚠️ Бот находится в тестировании. Данные могут быть изменены или утеряны."
)


@dataclass(frozen=True)
class ReleaseNoticeResult:
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

    note_items = _normalize_notes(notes)
    lines = [
        f"Важное обновление бота: {version}.",
    ]
    if note_items:
        lines.extend(["", "Что изменилось:"])
        lines.extend(f"- {item}" for item in note_items)
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


def _normalize_notes(notes: str) -> list[str]:
    items: list[str] = []
    for raw_line in notes.replace(";", "\n").splitlines():
        item = raw_line.strip().lstrip("-•").strip()
        if item:
            items.append(item)
    return items
