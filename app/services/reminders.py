import asyncio
import contextlib
import logging
from collections import defaultdict
from datetime import datetime, timezone as datetime_timezone
from math import floor
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from app.keyboards.menu import (
    buy_reminder_keyboard,
    daily_summary_keyboard,
    egg_drop_keyboard,
    feeding_reminder_keyboard,
    grown_chicks_keyboard,
)
from app.services.eggs import EggService
from app.services.incubation import IncubationService
from app.services.guides import post_hatch_care
from app.services.feeding import (
    FeedingService,
    buy_reminder_stage,
    format_buy_reminder,
    format_feeding_status,
    pace_lines,
)
from app.services.feeds import FeedService
from app.services.poultry_advisor import PoultryAdvisorService
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
        poultry_advisor_service: PoultryAdvisorService | None = None,
        feeding_service: FeedingService | None = None,
        ledger_service=None,
        care_service=None,
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
        self.feeding_service = feeding_service
        self.ledger_service = ledger_service
        self.care_service = care_service
        self.stock_service = stock_service
        self.poultry_advisor_service = poultry_advisor_service
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
        await self._send_feeding_reminders(now)
        await self._send_buy_reminders(now)
        await self._send_weekly_reports(now)
        await self._send_egg_drop_alerts(now)
        await self._send_grown_chick_alerts(now)
        await self._send_care_reminders(now)

    async def _send_incubation_reminders(self, now: datetime) -> None:
        due_by_user = defaultdict(list)
        for item in self.incubation_service.list_due_incubation_notifications(now):
            if self.notifications and not self.notifications.can_attempt(item.event_key, now=now):
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
                await respect_rate_limit(exc)
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
            if self.notifications and not self.notifications.can_attempt(item.event_key, now=now):
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
                await respect_rate_limit(exc)
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
            if self.notifications and not self.notifications.can_attempt(event_key, now=now):
                continue
            try:
                message = self.build_daily_summary_message(
                    user_id=user_id,
                    local_now=local_now,
                    now=now,
                    settings=settings,
                )
                if self.notifications:
                    self.notifications.record_attempt(
                        user_id=user_id,
                        type="daily_summary",
                        event_key=event_key,
                        scheduled_for=local_now,
                    )
                await self.bot.send_message(user_id, message, reply_markup=daily_summary_keyboard())
            except Exception as exc:
                logger.exception("Failed to send daily summary to user %s", user_id)
                error_code = classify_telegram_error(exc)
                await respect_rate_limit(exc)
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
            if self.notifications and not self.notifications.can_attempt(event_key, now=now):
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
                await respect_rate_limit(exc)
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

    def _feeding_summary_line(self, user_id: int, now: datetime) -> str:
        if self.feeding_service is None:
            return "- Дать корм."
        try:
            status = format_feeding_status(self.feeding_service, user_id, now=now)
        except Exception:
            logger.exception("Failed to read feeding status for user %s", user_id)
            return "- Дать корм."
        if "не отмечено" in status:
            return "- Дать корм и нажать «✅ Покормил»."
        return f"- {status}"

    async def _send_feeding_reminders(self, now: datetime) -> None:
        """Evening nudge for people who use «Покормил» and have not marked today."""
        if self.feeding_service is None or self.users is None:
            return
        for settings in self.users.list_users_with_settings():
            user_id = int(settings["user_id"])
            if not settings.get("is_active", True) or not settings.get("notify_feeding", True):
                continue
            if not settings.get("notify_feed", True):
                continue
            if not self.feeding_service.needs_evening_reminder(user_id, now=now):
                continue
            local_now = _local_now_for_settings(settings, now)
            event_key = f"feeding_reminder:user_{user_id}:{local_now.date().isoformat()}"
            if self.notifications and not self.notifications.can_attempt(event_key, now=now):
                continue
            try:
                if self.notifications:
                    self.notifications.record_attempt(
                        user_id=user_id,
                        type="feeding",
                        event_key=event_key,
                        scheduled_for=local_now,
                    )
                await self.bot.send_message(
                    user_id,
                    "🌾 Сегодня ещё не отмечено кормление.\n"
                    "Если уже покормили, нажмите «✅ Покормил».",
                    reply_markup=feeding_reminder_keyboard(),
                )
            except Exception as exc:
                logger.exception("Failed to send feeding reminder to user %s", user_id)
                error_code = classify_telegram_error(exc)
                await respect_rate_limit(exc)
                if self.notifications:
                    self.notifications.mark_failed(event_key, error_code=error_code, error_message=str(exc))
                if error_code in {"blocked", "deactivated"}:
                    self.incubation_service.mark_user_inactive(user_id, error_code)
                continue
            if self.notifications:
                self.notifications.mark_sent(event_key, local_now)

    async def _send_simple(self, *, user_id: int, event_key: str, kind: str, local_now, text: str, markup, now) -> None:
        """Send one deduplicated notification with the usual retry/blocked handling."""
        if self.notifications and not self.notifications.can_attempt(event_key, now=now):
            return
        try:
            if self.notifications:
                self.notifications.record_attempt(
                    user_id=user_id, type=kind, event_key=event_key, scheduled_for=local_now
                )
            await self.bot.send_message(user_id, text, reply_markup=markup)
        except Exception as exc:
            logger.exception("Failed to send %s to user %s", kind, user_id)
            error_code = classify_telegram_error(exc)
            await respect_rate_limit(exc)
            if self.notifications:
                self.notifications.mark_failed(event_key, error_code=error_code, error_message=str(exc))
            if error_code in {"blocked", "deactivated"}:
                self.incubation_service.mark_user_inactive(user_id, error_code)
            return
        if self.notifications:
            self.notifications.mark_sent(event_key, local_now)

    async def _send_egg_drop_alerts(self, now: datetime) -> None:
        """Laying fell for 3 days: tell the owner once a week with likely causes."""
        if self.users is None or self.poultry_advisor_service is None:
            return
        for settings in self.users.list_users_with_settings():
            user_id = int(settings["user_id"])
            if not _settings_allow_notification(settings, "notify_eggs", now):
                continue
            local_now = _local_now_for_settings(settings, now)
            today = local_now.date()
            year, week, _ = today.isocalendar()
            event_key = f"egg_drop:user_{user_id}:{year}-W{week:02d}"
            if self.notifications and self.notifications.was_sent(event_key):
                continue
            drop = self.poultry_advisor_service.detect_egg_drop(user_id, today=today)
            if drop is None:
                continue
            try:
                text = self.poultry_advisor_service.build_egg_drop_alert(user_id, drop, today=today)
            except Exception:
                logger.exception("Failed to build egg drop alert for user %s", user_id)
                continue
            await self._send_simple(
                user_id=user_id, event_key=event_key, kind="egg_drop", local_now=local_now,
                text=text, markup=egg_drop_keyboard(), now=now,
            )

    async def _send_care_reminders(self, now: datetime) -> None:
        """Care calendar: due tasks in one message, repeated every few days until done."""
        if self.users is None or self.care_service is None:
            return
        from app.handlers.farm_tools import care_reminder_keyboard
        from app.services.care import format_care_reminder

        for settings in self.users.list_users_with_settings():
            user_id = int(settings["user_id"])
            if not _settings_allow_notification(settings, "notify_poultry_advisor", now):
                continue
            local_now = _local_now_for_settings(settings, now)
            today = local_now.date()
            try:
                due = self.care_service.due_for_reminder(user_id, today=today)
            except Exception:
                logger.exception("Failed to read care tasks for user %s", user_id)
                continue
            if not due:
                continue
            event_key = f"care:user_{user_id}:{today.isoformat()}"
            await self._send_simple(
                user_id=user_id,
                event_key=event_key,
                kind="care",
                local_now=local_now,
                text=format_care_reminder(due, today),
                markup=care_reminder_keyboard(due),
                now=now,
            )
            if self.notifications is None or self.notifications.was_sent(event_key):
                self.care_service.mark_reminded(user_id, [task.id for task in due], today=today)

    async def _send_grown_chick_alerts(self, now: datetime) -> None:
        """Chicks reached 16 weeks: offer once per group to move them to adults."""
        if self.users is None or self.feed_service is None:
            return
        from app.services.insights import chick_age_text, grown_chick_groups

        for settings in self.users.list_users_with_settings():
            user_id = int(settings["user_id"])
            if not _settings_allow_notification(settings, "notify_feed", now):
                continue
            local_now = _local_now_for_settings(settings, now)
            try:
                groups = grown_chick_groups(self.feed_service.list_bird_groups(user_id), today=local_now.date())
            except Exception:
                logger.exception("Failed to check chick groups for user %s", user_id)
                continue
            for group in groups:
                await self._send_simple(
                    user_id=user_id,
                    event_key=f"chicks_grown:group_{group.id}",
                    kind="chicks_grown",
                    local_now=local_now,
                    text=(
                        f"🐓 Цыплята «{group.name}» подросли: им уже {chick_age_text(group, local_now.date())}.\n\n"
                        "Пора перевести их во взрослых и разделить на несушек и петухов — тогда яйца "
                        "и норма корма будут считаться правильно."
                    ),
                    markup=grown_chicks_keyboard(group.id),
                    now=now,
                )

    async def _send_weekly_reports(self, now: datetime) -> None:
        """Sunday evening: the week's eggs, feed, money and what runs out soon."""
        if self.users is None or self.egg_service is None:
            return
        from app.services.weekly_report import WEEKLY_REPORT_HOUR, WEEKLY_REPORT_WEEKDAY, build_weekly_report

        for settings in self.users.list_users_with_settings():
            user_id = int(settings["user_id"])
            if not settings.get("is_active", True) or not settings.get("notify_daily_summary", True):
                continue
            local_now = _local_now_for_settings(settings, now)
            if local_now.weekday() != WEEKLY_REPORT_WEEKDAY or local_now.hour < WEEKLY_REPORT_HOUR:
                continue
            event_key = f"weekly_report:user_{user_id}:{local_now.date().isoformat()}"
            if self.notifications and not self.notifications.can_attempt(event_key, now=now):
                continue
            try:
                text = build_weekly_report(
                    user_id=user_id,
                    today=local_now.date(),
                    eggs=self.egg_service.eggs,
                    feeding_service=self.feeding_service,
                    ledger_service=self.ledger_service,
                )
                if self.notifications:
                    self.notifications.record_attempt(
                        user_id=user_id, type="weekly_report", event_key=event_key, scheduled_for=local_now
                    )
                await self.bot.send_message(user_id, text, reply_markup=daily_summary_keyboard())
            except Exception as exc:
                logger.exception("Failed to send weekly report to user %s", user_id)
                error_code = classify_telegram_error(exc)
                await respect_rate_limit(exc)
                if self.notifications:
                    self.notifications.mark_failed(event_key, error_code=error_code, error_message=str(exc))
                if error_code in {"blocked", "deactivated"}:
                    self.incubation_service.mark_user_inactive(user_id, error_code)
                continue
            if self.notifications:
                self.notifications.mark_sent(event_key, local_now)

    async def _send_buy_reminders(self, now: datetime) -> None:
        """Warn ahead that an ingredient of the home mix runs out, by the real feeding pace.

        Each ingredient is reminded once at 5 days left and once more at 2 days left;
        a new purchase of that ingredient starts the count over.
        """
        if self.feeding_service is None or self.users is None or self.stock_service is None:
            return
        for settings in self.users.list_users_with_settings():
            user_id = int(settings["user_id"])
            if not _settings_allow_notification(settings, "notify_feed", now):
                continue
            local_now = _local_now_for_settings(settings, now)
            pace = self._feed_pace(user_id, local_now)
            if pace is None:
                continue
            due: list[tuple[str, object]] = []
            for item in pace.ingredients:
                stage = buy_reminder_stage(item)
                if stage is None or item.stock_item_id is None:
                    continue
                purchase = self.stock_service.stock.last_purchase_id(item.stock_item_id, user_id)
                key = f"buy_ingredient:user_{user_id}:item_{item.stock_item_id}:p{purchase}:d{stage}"
                if self.notifications and not self.notifications.can_attempt(key, now=now):
                    continue
                if self.notifications and stage > 2 and self.notifications.was_sent(
                    f"buy_ingredient:user_{user_id}:item_{item.stock_item_id}:p{purchase}:d2"
                ):
                    continue
                due.append((key, item))
            if not due:
                continue
            try:
                if self.notifications:
                    for key, _ in due:
                        self.notifications.record_attempt(
                            user_id=user_id, type="feed", event_key=key, scheduled_for=local_now
                        )
                await self.bot.send_message(
                    user_id,
                    format_buy_reminder([item for _, item in due], pace, local_now.date()),
                    reply_markup=buy_reminder_keyboard(),
                )
            except Exception as exc:
                logger.exception("Failed to send buy reminder to user %s", user_id)
                error_code = classify_telegram_error(exc)
                await respect_rate_limit(exc)
                if self.notifications:
                    for key, _ in due:
                        self.notifications.mark_failed(key, error_code=error_code, error_message=str(exc))
                if error_code in {"blocked", "deactivated"}:
                    self.incubation_service.mark_user_inactive(user_id, error_code)
                continue
            if self.notifications:
                for key, _ in due:
                    self.notifications.mark_sent(key, local_now)

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
                    "daily_summary_time": "per-user notification_time",
                },
            )
        except Exception:
            logger.exception("Failed to write reminder_runner heartbeat")

    def build_daily_summary_message(
        self,
        *,
        user_id: int,
        local_now: datetime,
        now: datetime,
        settings: dict | None = None,
    ) -> str:
        lines = [
            f"Ежедневная сводка хозяйства на {local_now.date().isoformat()}:",
            "",
            "Напоминания:",
            "- Собрать яйца и записать результат.",
            "- Проверить и заменить воду.",
            self._feeding_summary_line(user_id, now),
            "",
        ]

        sections = settings or {}
        if self.egg_service is not None and sections.get("notify_eggs", True):
            stats = self.egg_service.stats(user_id, today=local_now.date())
            lines.extend(
                [
                    "Яйца:",
                    f"- Сегодня записано: {stats.today_eggs} шт.",
                    f"- За 7 дней: {stats.week_eggs} шт.; среднее: {stats.week_average:.1f} шт./день.",
                    "",
                ]
            )

        pace = self._feed_pace(user_id, local_now)
        if sections.get("notify_feed", True) and pace is not None:
            lines.append("Корм (своя смесь):")
            lines.extend(pace_lines(pace))
        elif sections.get("notify_feed", True):
            lines.append("Готовая смесь:")
            lines.extend(
                self._finished_mix_summary_lines(
                    user_id=user_id,
                    now=now,
                    local_now=local_now,
                )
            )
            lines.extend(self._low_ingredient_lines(user_id=user_id, now=now))
        if self.poultry_advisor_service is not None:
            advice_lines = self.poultry_advisor_service.build_daily_summary_advice_lines(
                user_id,
                local_now=local_now,
                now_utc=now,
                settings=settings,
            )
            if advice_lines:
                lines.extend(["", "Совет птицевода:"])
                lines.extend(f"- {line}" for line in advice_lines)
        return "\n".join(lines)

    def _feed_pace(self, user_id: int, local_now: datetime):
        if self.feeding_service is None:
            return None
        try:
            return self.feeding_service.pace(user_id, today=local_now.date())
        except Exception:
            logger.exception("Failed to compute feed pace for user %s", user_id)
            return None

    def _low_ingredient_lines(self, *, user_id: int, now: datetime) -> list[str]:
        if self.stock_service is None:
            return []
        try:
            low = self.stock_service.low_mix_ingredients(user_id=user_id, now=now)
        except Exception:
            logger.exception("Failed to check low ingredients for user %s", user_id)
            return []
        if not low:
            return []
        parts = [
            f"{name} — {'нет на замес' if mixes == 0 else f'хватит на {mixes} замес(а)'}"
            for name, mixes in low[:5]
        ]
        return ["- Заканчиваются ингредиенты: " + "; ".join(parts) + "."]

    def _finished_mix_summary_lines(
        self,
        *,
        user_id: int,
        now: datetime,
        local_now: datetime,
    ) -> list[str]:
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
        last_mix = self.stock_service.last_mix_output(user_id)
        lines = [
            f"- Последний замес: {_format_local_datetime(last_mix.created_at, local_now) if last_mix else 'не найден'}.",
            f"- Остаток: {_format_kg(remaining_kg)}.",
            f"- Расход: {_format_kg(daily_usage_kg)}/день.",
            f"- Хватит: {_format_days(days_left)}.",
        ]
        if remaining_kg <= 0:
            exhausted_at = self._finished_mix_exhausted_at(estimates=estimates, now=now)
            if exhausted_at is not None:
                lines.append(
                    "- По расчету смесь закончилась "
                    f"{_format_local_datetime(exhausted_at, local_now)} "
                    f"({_format_days_ago(exhausted_at, local_now)} назад)."
                )

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

    def _finished_mix_exhausted_at(self, *, estimates, now: datetime) -> datetime | None:
        if self.stock_service is None:
            return None
        exhausted_dates = [
            exhausted_at
            for estimate in estimates
            if estimate.remaining_kg <= 0
            for exhausted_at in [self.stock_service.estimate_item_exhausted_at(estimate.item, now=now)]
            if exhausted_at is not None
        ]
        return max(exhausted_dates) if exhausted_dates else None


MAX_RATE_LIMIT_SLEEP_SECONDS = 60


async def respect_rate_limit(exc: Exception) -> None:
    """Telegram asks to slow down (HTTP 429): wait before the next message."""
    if isinstance(exc, TelegramRetryAfter):
        await asyncio.sleep(min(float(exc.retry_after), MAX_RATE_LIMIT_SLEEP_SECONDS))


def classify_telegram_error(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, TelegramRetryAfter):
        return "rate_limited"
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
    if not settings.get("notify_daily_summary", True):
        return False
    local_now = _local_now_for_settings(settings, now_utc)
    try:
        hour, minute = (int(part) for part in str(settings.get("notification_time", "09:00")).split(":", 1))
    except ValueError:
        hour, minute = 9, 0
    return (local_now.hour, local_now.minute) >= (hour, minute)


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


def _format_local_datetime(value: datetime, local_now: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime_timezone.utc)
    timezone = local_now.tzinfo or ZoneInfo("Europe/Moscow")
    return value.astimezone(timezone).strftime("%Y-%m-%d %H:%M")


def _format_days_ago(value: datetime, local_now: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime_timezone.utc)
    timezone = local_now.tzinfo or ZoneInfo("Europe/Moscow")
    local_value = value.astimezone(timezone)
    days = max((local_now.date() - local_value.date()).days, 0)
    return f"{days} дн."
