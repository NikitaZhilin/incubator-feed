import asyncio
import contextlib
import logging
from collections import defaultdict
from datetime import datetime, timezone as datetime_timezone
from math import floor
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError

from app.services.eggs import EggService
from app.services.incubation import IncubationService
from app.services.guides import post_hatch_care
from app.services.feeds import FeedService
from app.services.stock import StockService
from app.storage.repositories.heartbeats import HeartbeatRepository
from app.storage.repositories.notifications import NotificationRepository
from app.storage.repositories.users import UserRepository


logger = logging.getLogger(__name__)


class ReminderRunner:
    def __init__(
        self,
        *,
        bot: Bot,
        incubation_service: IncubationService,
        feed_service: FeedService | None = None,
        egg_service: EggService | None = None,
        stock_service: StockService | None = None,
        users: UserRepository | None = None,
        notifications: NotificationRepository | None = None,
        heartbeats: HeartbeatRepository | None = None,
        heartbeat_version: str = "",
        started_at: datetime | None = None,
        timezone: str,
        interval_seconds: int = 60,
    ) -> None:
        self.bot = bot
        self.incubation_service = incubation_service
        self.feed_service = feed_service
        self.egg_service = egg_service
        self.stock_service = stock_service
        self.users = users
        self.notifications = notifications
        self.heartbeats = heartbeats
        self.heartbeat_version = heartbeat_version
        self.started_at = started_at or datetime.now(datetime_timezone.utc)
        self.timezone = ZoneInfo(timezone)
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._write_heartbeat(status="ok")
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
                self._write_heartbeat(status="ok")
            except Exception:
                logger.exception("Reminder loop failed")
                self._write_heartbeat(status="degraded", last_error="Reminder loop failed")
            await asyncio.sleep(self.interval_seconds)

    async def _send_due_reminders(self, now_utc: datetime | None = None) -> None:
        now = now_utc or datetime.now(datetime_timezone.utc)
        await self._send_incubation_reminders(now)
        await self._send_post_hatch_reminders(now)
        await self._send_daily_summary_reminders(now)
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

    async def _send_daily_summary_reminders(self, now: datetime) -> None:
        if self.users is None or self.egg_service is None or self.stock_service is None:
            return

        for settings in self.users.list_users_with_settings():
            user_id = int(settings["user_id"])
            if not _settings_allow_daily_summary(settings, now):
                continue
            local_now = _local_now_for_settings(settings, now)
            event_key = f"daily_summary:user_{user_id}:{local_now.date().isoformat()}"
            if self.notifications and self.notifications.was_sent(event_key):
                continue
            try:
                message = self._build_daily_summary_message(
                    user_id=user_id,
                    local_now=local_now,
                    now=now,
                )
                if self.notifications:
                    self.notifications.record_attempt(
                        user_id=user_id,
                        type="daily_summary",
                        event_key=event_key,
                        scheduled_for=local_now,
                    )
                await self.bot.send_message(user_id, message)
            except Exception as exc:
                logger.exception("Failed to send daily summary to user %s", user_id)
                error_code = classify_telegram_error(exc)
                if self.notifications:
                    self.notifications.mark_failed(
                        event_key,
                        error_code=error_code,
                        error_message=str(exc),
                    )
                if error_code in {"blocked", "deactivated"}:
                    self.incubation_service.mark_user_inactive(user_id, error_code)
                continue
            if self.notifications:
                self.notifications.mark_sent(event_key, local_now)

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

    def _write_heartbeat(self, *, status: str, last_error: str | None = None) -> None:
        if self.heartbeats is None:
            return
        try:
            self.heartbeats.upsert(
                service_name="reminder_runner",
                status=status,
                version=self.heartbeat_version,
                started_at=self.started_at,
                last_error=last_error,
                metadata={
                    "interval_seconds": self.interval_seconds,
                    "timezone": str(self.timezone),
                    "daily_summary_time": "12:00",
                },
            )
        except Exception:
            logger.exception("Failed to write reminder_runner heartbeat")

    def _build_daily_summary_message(
        self,
        *,
        user_id: int,
        local_now: datetime,
        now: datetime,
    ) -> str:
        lines = [
            f"Ежедневная сводка хозяйства на {local_now.date().isoformat()}:",
            "",
            "Напоминания:",
            "- Собрать яйца и записать результат.",
            "- Проверить и заменить воду.",
            "- Дать корм.",
            "",
        ]

        if self.egg_service is not None:
            stats = self.egg_service.stats(user_id, today=local_now.date())
            lines.extend(
                [
                    "Яйца:",
                    f"- Сегодня записано: {stats.today_eggs} шт.",
                    f"- За 7 дней: {stats.week_eggs} шт.; среднее: {stats.week_average:.1f} шт./день.",
                    f"- Несушки: {stats.active_hens_count} активных из {stats.total_hens_count}.",
                    "",
                ]
            )

        lines.append("Готовая смесь:")
        lines.extend(self._finished_mix_summary_lines(user_id=user_id, now=now))
        return "\n".join(lines)

    def _finished_mix_summary_lines(self, *, user_id: int, now: datetime) -> list[str]:
        if self.stock_service is None:
            return ["- Склад смеси сейчас не подключен к сводке."]

        estimates = [
            estimate
            for estimate in self.stock_service.list_estimates(user_id, now=now)
            if estimate.item.kind == "finished_mix"
        ]
        remaining_kg = sum(max(estimate.remaining_kg, 0) for estimate in estimates)
        daily_usage_kg = sum(max(estimate.daily_usage_kg, 0) for estimate in estimates)
        days_left = floor(remaining_kg / daily_usage_kg) if daily_usage_kg > 0 else None
        lines = [
            f"- Остаток: {_format_kg(remaining_kg)}.",
            f"- Расход: {_format_kg(daily_usage_kg)}/день.",
            f"- Хватит: {_format_days(days_left)}.",
        ]

        mix_advice = self._mix_advice_line(user_id=user_id, now=now)
        if remaining_kg <= 0:
            lines.append("- Готовой смеси на складе нет: нужно сделать замес или добавить готовую смесь.")
            if mix_advice:
                lines.append(mix_advice)
            return lines
        if days_left is not None and days_left <= 2:
            lines.append(
                f"- Критично: смеси осталось примерно на {days_left} дн.; "
                "нужно сделать новый замес или добавить готовую смесь."
            )
            if mix_advice:
                lines.append(mix_advice)
        elif days_left is None:
            lines.append("- Расход по стадам не назначен, поэтому срок запаса не рассчитан.")
        return lines

    def _mix_advice_line(self, *, user_id: int, now: datetime) -> str:
        if self.stock_service is None:
            return ""
        try:
            plan = self.stock_service.best_available_mix_plan(user_id=user_id, now=now)
        except Exception:
            logger.exception("Failed to calculate mix advice for user %s", user_id)
            return ""
        possible_count = floor(plan.max_mix_count)
        if possible_count > 0:
            return (
                f"- По складу сейчас можно сделать {possible_count} замес(ов), "
                f"получится примерно {_format_kg(plan.output_kg * possible_count)}."
            )
        missing = [item.name for item in plan.ingredients if item.missing_kg > 0]
        if missing:
            return "- Для нового замеса не хватает: " + ", ".join(missing[:5]) + "."
        return ""


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


def _settings_allow_daily_summary(settings: dict, now_utc: datetime) -> bool:
    if not settings or not settings.get("is_active", True):
        return False
    local_now = _local_now_for_settings(settings, now_utc)
    return (local_now.hour, local_now.minute) >= (12, 0)


def _local_now_for_settings(settings: dict, now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=datetime_timezone.utc)
    try:
        user_timezone = ZoneInfo(str(settings.get("timezone", "Europe/Moscow")))
    except Exception:
        user_timezone = ZoneInfo("Europe/Moscow")
    return now_utc.astimezone(user_timezone)


def _format_kg(value: float) -> str:
    return f"{value:.1f} кг"


def _format_days(value: int | None) -> str:
    if value is None:
        return "не рассчитано"
    return f"{value} дн."
