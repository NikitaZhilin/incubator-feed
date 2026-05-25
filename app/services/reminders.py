import asyncio
import contextlib
import logging
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError

from app.services.incubation import IncubationService
from app.services.guides import post_hatch_care
from app.services.feeds import FeedService
from app.storage.repositories.notifications import NotificationRepository


logger = logging.getLogger(__name__)


class ReminderRunner:
    def __init__(
        self,
        *,
        bot: Bot,
        incubation_service: IncubationService,
        feed_service: FeedService | None = None,
        notifications: NotificationRepository | None = None,
        timezone: str,
        interval_seconds: int = 60,
    ) -> None:
        self.bot = bot
        self.incubation_service = incubation_service
        self.feed_service = feed_service
        self.notifications = notifications
        self.timezone = ZoneInfo(timezone)
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        while True:
            try:
                await self._send_due_reminders()
            except Exception:
                logger.exception("Reminder loop failed")
            await asyncio.sleep(self.interval_seconds)

    async def _send_due_reminders(self, now_utc: datetime | None = None) -> None:
        now = now_utc or datetime.now(timezone.utc)
        await self._send_incubation_reminders(now)
        await self._send_post_hatch_reminders(now)
        await self._send_feed_reminders(now)

    async def _send_incubation_reminders(self, now: datetime) -> None:
        due_by_user = defaultdict(list)
        for item in self.incubation_service.list_due_incubation_notifications(now):
            if self.notifications and self.notifications.was_sent(item.event_key):
                continue
            due_by_user[item.user_id].append(item)

        for user_id, items in due_by_user.items():
            if not items:
                continue
            lines = ["Ежедневное напоминание по инкубации:"]
            for item in items:
                status = item.status
                lines.append("")
                lines.append(f"{status.batch.title}: день {status.day}, {status.stage}")
                lines.extend(f"- {item}" for item in status.recommendations[:5])

            try:
                if self.notifications:
                    for item in items:
                        self.notifications.record_attempt(
                            user_id=user_id,
                            batch_id=item.status.batch.id,
                            type="incubation",
                            event_key=item.event_key,
                            scheduled_for=item.local_now,
                        )
                await self.bot.send_message(user_id, "\n".join(lines))
            except Exception as exc:
                logger.exception("Failed to send incubation reminder to user %s", user_id)
                error_code = classify_telegram_error(exc)
                if self.notifications:
                    for item in items:
                        self.notifications.mark_failed(
                            item.event_key,
                            error_code=error_code,
                            error_message=str(exc),
                        )
                if error_code in {"blocked", "deactivated"}:
                    self.incubation_service.mark_user_inactive(user_id, error_code)
                continue
            if self.notifications:
                for item in items:
                    self.notifications.mark_sent(item.event_key, item.local_now)
            self.incubation_service.mark_reminder_sent(user_id, items[0].local_now.date())

    async def _send_post_hatch_reminders(self, now: datetime) -> None:
        for item in self.incubation_service.list_due_post_hatch_notifications(now):
            if self.notifications and self.notifications.was_sent(item.event_key):
                continue
            status = item.status
            try:
                if self.notifications:
                    self.notifications.record_attempt(
                        user_id=item.user_id,
                        batch_id=status.batch.id,
                        type="post_hatch_care",
                        event_key=item.event_key,
                        scheduled_for=item.local_now,
                    )
                await self.bot.send_message(
                    item.user_id,
                    f"Памятка по уходу после вывода для партии #{status.batch.id} "
                    f"{status.batch.title}:\n\n"
                    f"{post_hatch_care(status.profile.title)}",
                )
            except Exception as exc:
                logger.exception("Failed to send post-hatch reminder for batch %s", status.batch.id)
                error_code = classify_telegram_error(exc)
                if self.notifications:
                    self.notifications.mark_failed(
                        item.event_key,
                        error_code=error_code,
                        error_message=str(exc),
                    )
                if error_code in {"blocked", "deactivated"}:
                    self.incubation_service.mark_user_inactive(item.user_id, error_code)
                continue
            if self.notifications:
                self.notifications.mark_sent(item.event_key, item.local_now)

    async def _send_feed_reminders(self, now: datetime) -> None:
        if self.feed_service is None:
            return

        for estimate in self.feed_service.list_due_purchase_reminders(now):
            feed = estimate.feed
            user_settings = self.incubation_service.get_user_settings(feed.user_id)
            if not _settings_allow_notification(user_settings, "notify_feed", now):
                continue
            local_now = _local_now_for_settings(user_settings, now)
            event_key = f"feed:feed_{feed.id}:low_stock:{local_now.date().isoformat()}"
            if self.notifications and self.notifications.was_sent(event_key):
                self.feed_service.mark_purchase_reminded(feed.id, now)
                continue
            try:
                if self.notifications:
                    self.notifications.record_attempt(
                        user_id=feed.user_id,
                        feed_id=feed.id,
                        type="feed",
                        event_key=event_key,
                        scheduled_for=local_now,
                    )
                await self.bot.send_message(
                    feed.user_id,
                    "Напоминание о покупке корма:\n\n"
                    f"{feed.name}\n"
                    f"Расчетный остаток: {estimate.remaining_kg:.1f} кг\n"
                    f"Порог покупки: {feed.low_threshold_kg:g} кг\n"
                    f"Расход: {estimate.daily_usage_kg:.2f} кг/день "
                    f"на {feed.hen_count} кур и {feed.rooster_count} петухов.",
                )
            except Exception as exc:
                logger.exception("Failed to send feed reminder for feed %s", feed.id)
                error_code = classify_telegram_error(exc)
                if self.notifications:
                    self.notifications.mark_failed(
                        event_key,
                        error_code=error_code,
                        error_message=str(exc),
                    )
                if error_code in {"blocked", "deactivated"}:
                    self.incubation_service.mark_user_inactive(feed.user_id, error_code)
                    self.feed_service.mark_purchase_reminded(feed.id, now)
                continue
            if self.notifications:
                self.notifications.mark_sent(event_key, local_now)
            self.feed_service.mark_purchase_reminded(feed.id, now)


def classify_telegram_error(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, TelegramForbiddenError):
        return "blocked"
    if isinstance(exc, TelegramBadRequest) and (
        "chat not found" in text
        or "user is deactivated" in text
        or "bot was blocked" in text
        or "forbidden" in text
    ):
        return "deactivated"
    if isinstance(exc, TelegramNetworkError):
        return "network"
    return "telegram_error"


def _settings_allow_notification(settings: dict, flag: str, now_utc: datetime) -> bool:
    if not settings:
        return True
    if not settings.get("is_active", True) or not settings.get(flag, False):
        return False
    local_now = _local_now_for_settings(settings, now_utc)
    try:
        hour, minute = (int(part) for part in str(settings.get("notification_time", "09:00")).split(":", 1))
    except ValueError:
        hour, minute = 9, 0
    return (local_now.hour, local_now.minute) >= (hour, minute)


def _local_now_for_settings(settings: dict, now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    try:
        user_timezone = ZoneInfo(str(settings.get("timezone", "Europe/Moscow")))
    except Exception:
        user_timezone = ZoneInfo("Europe/Moscow")
    return now_utc.astimezone(user_timezone)
