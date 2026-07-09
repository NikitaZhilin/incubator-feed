from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain import (
    BatchStatus,
    IncubationBatch,
    PROFILES,
    ReminderSettings,
    calculate_hatch_date,
    get_profile,
)
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.reminders import ReminderRepository
from app.storage.repositories.analytics import AnalyticsRepository
from app.storage.repositories.users import UserRepository


@dataclass(frozen=True)
class IncubationStats:
    total_batches: int
    active_batches: int
    completed_batches: int
    total_eggs: int
    total_hatched: int
    hatch_rate: float | None


@dataclass(frozen=True)
class DueBatchNotification:
    user_id: int
    local_now: datetime
    status: BatchStatus
    event_key: str


class IncubationService:
    def __init__(
        self,
        batches: BatchRepository,
        reminders: ReminderRepository | None = None,
        users: UserRepository | None = None,
        analytics: AnalyticsRepository | None = None,
    ) -> None:
        self.batches = batches
        self.reminders = reminders
        self.users = users
        self.analytics = analytics

    def available_species(self) -> list[tuple[str, str]]:
        return [(code, profile.title) for code, profile in PROFILES.items()]

    def create_batch(
        self,
        *,
        user_id: int,
        species: str,
        eggs_count: int,
        start_date: date,
        title: str | None = None,
        note: str = "",
    ) -> IncubationBatch:
        profile = get_profile(species)
        clean_title = (title or f"{profile.title}: {eggs_count} шт.").strip()
        if eggs_count <= 0:
            raise ValueError("Количество яиц должно быть больше нуля")
        batch = self.batches.create(
            user_id=user_id,
            species=species,
            eggs_count=eggs_count,
            start_date=start_date,
            title=clean_title,
            note=note.strip(),
        )
        self.track("batch_created", user_id=user_id, entity_type="batch", entity_id=batch.id)
        return batch

    def list_active(self, user_id: int) -> list[IncubationBatch]:
        return self.batches.list_active(user_id)

    def list_completed(self, user_id: int, limit: int = 20) -> list[IncubationBatch]:
        return self.batches.list_completed(user_id, limit)

    def get_batch(self, batch_id: int, user_id: int) -> IncubationBatch | None:
        return self.batches.get(batch_id, user_id)

    def update_batch(
        self,
        *,
        batch_id: int,
        user_id: int,
        species: str | None = None,
        eggs_count: int | None = None,
        start_date: date | None = None,
        title: str | None = None,
        note: str | None = None,
    ) -> IncubationBatch | None:
        if species is not None:
            get_profile(species)
        if eggs_count is not None and eggs_count <= 0:
            raise ValueError("Количество яиц должно быть больше нуля")
        current = self.batches.get(batch_id, user_id)
        if current is None:
            return None
        if not current.is_active:
            raise ValueError(
                "Партия уже в истории. Для правок сначала верните ее в активные."
            )
        updated = self.batches.update(
            batch_id=batch_id,
            user_id=user_id,
            species=species,
            eggs_count=eggs_count,
            start_date=start_date,
            title=title.strip() if title is not None else None,
            note=note.strip() if note is not None else None,
        )
        if updated is not None:
            self.track("batch_updated", user_id=user_id, entity_type="batch", entity_id=batch_id)
        return updated

    def complete_batch(
        self,
        *,
        batch_id: int,
        user_id: int,
        hatched_count: int,
        completed_at: date,
    ) -> IncubationBatch | None:
        batch = self.batches.get(batch_id, user_id)
        if batch is None:
            return None
        if not batch.is_active:
            raise ValueError("Партия уже завершена и находится в истории")
        if hatched_count < 0:
            raise ValueError("Количество выведенных птенцов не может быть отрицательным")
        if hatched_count > batch.eggs_count:
            raise ValueError("Выведенных птенцов не может быть больше, чем заложенных яиц")
        completed = self.batches.complete(
            batch_id=batch_id,
            user_id=user_id,
            hatched_count=hatched_count,
            completed_at=completed_at,
        )
        if completed is not None:
            self.track("batch_completed", user_id=user_id, entity_type="batch", entity_id=batch_id)
        return completed

    def reopen_batch(self, batch_id: int, user_id: int) -> IncubationBatch | None:
        batch = self.batches.reopen(batch_id, user_id)
        if batch is not None:
            self.track("batch_reopened", user_id=user_id, entity_type="batch", entity_id=batch_id)
        return batch

    def get_status(self, batch: IncubationBatch, today: date | None = None) -> BatchStatus:
        current_date = today or date.today()
        profile = get_profile(batch.species)
        hatch_date = calculate_hatch_date(batch.start_date, profile)
        day = (current_date - batch.start_date).days + 1
        days_left = (hatch_date - current_date).days

        if not batch.is_active:
            stage = "партия завершена"
        elif day <= 0:
            stage = "запланировано"
        elif day >= profile.lockdown_from_day:
            stage = "вывод / финальный этап"
        elif day in profile.candle_days:
            stage = "овоскопирование"
        else:
            stage = "инкубация"

        recommendations = self.get_recommendations(batch, current_date)
        return BatchStatus(
            batch=batch,
            profile=profile,
            day=day,
            hatch_date=hatch_date,
            days_left=days_left,
            stage=stage,
            recommendations=tuple(recommendations),
        )

    def get_recommendations(self, batch: IncubationBatch, today: date) -> list[str]:
        profile = get_profile(batch.species)
        day = (today - batch.start_date).days + 1
        recommendations: list[str] = []

        if not batch.is_active:
            recommendations.append("Партия закрыта и хранится в истории.")
            return recommendations
        if day <= 0:
            recommendations.append(f"Закладка запланирована на {batch.start_date.isoformat()}.")
            recommendations.append("Ежедневные действия начнутся с даты закладки.")
            return recommendations

        if day < profile.lockdown_from_day:
            recommendations.append(f"Температура: {profile.temperature_main}")
            recommendations.append(f"Влажность: {profile.humidity_main}")
            recommendations.append(f"Переворот: до {profile.turn_until_day} дня")
        else:
            recommendations.append(f"Температура: {profile.temperature_lockdown}")
            recommendations.append(f"Влажность: {profile.humidity_lockdown}")
            recommendations.append("Переворот: прекратить")

        if day in profile.candle_days:
            recommendations.append("Сегодня день овоскопирования")
        if profile.cooling_from_day and profile.cooling_from_day <= day < profile.lockdown_from_day:
            recommendations.append("Охлаждение/проветривание: выполнить по режиму водоплавающих")
        if day == profile.lockdown_from_day:
            recommendations.append("Переложить яйца на вывод, убрать лоток переворота")
        if day > profile.hatch_days + 2:
            recommendations.append("Проверьте партию: срок вывода уже прошел")
        if profile.note:
            recommendations.append(profile.note)

        return recommendations

    def get_user_statuses(self, user_id: int, today: date | None = None) -> list[BatchStatus]:
        current_date = today or date.today()
        return [self.get_status(batch, today=current_date) for batch in self.list_active(user_id)]

    def get_stats(self, user_id: int) -> IncubationStats:
        batches = self.batches.list_all_for_user(user_id)
        completed = [batch for batch in batches if not batch.is_active]
        total_eggs = sum(batch.eggs_count for batch in completed)
        total_hatched = sum(batch.hatched_count or 0 for batch in completed)
        hatch_rate = (total_hatched / total_eggs * 100) if total_eggs else None
        return IncubationStats(
            total_batches=len(batches),
            active_batches=sum(1 for batch in batches if batch.is_active),
            completed_batches=len(completed),
            total_eggs=total_eggs,
            total_hatched=total_hatched,
            hatch_rate=hatch_rate,
        )

    def get_reminder_settings(self, user_id: int) -> ReminderSettings:
        if self.users is not None:
            settings = self.users.get_settings(user_id)
            hour, minute = parse_notification_time(settings["notification_time"])
            return ReminderSettings(
                user_id=user_id,
                is_enabled=bool(settings["is_active"] and settings["notify_incubation"]),
                hour=hour,
                minute=minute,
            )
        self._require_reminders()
        return self.reminders.get(user_id)

    def has_reminder_settings(self, user_id: int) -> bool:
        self._require_reminders()
        return self.reminders.exists(user_id)

    def set_reminders(self, user_id: int, enabled: bool, hour: int = 9, minute: int = 0) -> ReminderSettings:
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Время напоминания должно быть в формате ЧЧ:ММ")
        if self.users is not None:
            self.users.update_settings(
                user_id,
                notification_time=f"{hour:02d}:{minute:02d}",
                notify_incubation=enabled,
            )
        if self.reminders is not None:
            self.reminders.upsert(
                user_id=user_id,
                is_enabled=enabled,
                hour=hour,
                minute=minute,
            )
        self.track(
            "notifications_changed",
            user_id=user_id,
            entity_type="user",
            entity_id=user_id,
            payload={"notify_incubation": enabled, "notification_time": f"{hour:02d}:{minute:02d}"},
        )
        return self.get_reminder_settings(user_id)

    def mark_reminder_sent(self, user_id: int, sent_date: date) -> None:
        self._require_reminders()
        self.reminders.mark_sent(user_id, sent_date)

    def list_due_reminder_users(self, now) -> list[int]:
        return sorted({item.user_id for item in self.list_due_incubation_notifications(now)})

    def list_due_incubation_notifications(self, now_utc: datetime) -> list[DueBatchNotification]:
        due: list[DueBatchNotification] = []
        for user_id, settings, local_now in self._iter_users_due_for("notify_incubation", now_utc):
            for batch in self.batches.list_active(user_id):
                if batch.start_date > local_now.date():
                    continue
                status = self.get_status(batch, today=local_now.date())
                event_key = (
                    f"incubation:batch_{batch.id}:day_{status.day}:"
                    f"{local_now.date().isoformat()}"
                )
                due.append(
                    DueBatchNotification(
                        user_id=user_id,
                        local_now=local_now,
                        status=status,
                        event_key=event_key,
                    )
                )
        return due

    def list_due_post_hatch_notifications(self, now_utc: datetime) -> list[DueBatchNotification]:
        due: list[DueBatchNotification] = []
        for user_id, settings, local_now in self._iter_users_due_for("notify_post_hatch_care", now_utc):
            for batch in self.batches.list_all_for_user(user_id):
                status = self.get_status(batch, today=local_now.date())
                if batch.completed_at is not None:
                    due_date = batch.completed_at
                else:
                    due_date = status.hatch_date
                if local_now.date() < due_date:
                    continue
                event_key = f"post_hatch_care:batch_{batch.id}:{due_date.isoformat()}"
                due.append(
                    DueBatchNotification(
                        user_id=user_id,
                        local_now=local_now,
                        status=status,
                        event_key=event_key,
                    )
                )
        return due

    def _iter_users_due_for(
        self,
        notification_flag: str,
        now_utc: datetime,
    ) -> list[tuple[int, dict, datetime]]:
        if self.users is None:
            return self._iter_legacy_due_users(now_utc)
        user_ids = set(self.batches.list_known_users())
        for settings in self.users.list_users_with_settings():
            user_ids.add(int(settings["user_id"]))
        due: list[tuple[int, dict, datetime]] = []
        for user_id in sorted(user_ids):
            settings = self.users.get_settings(user_id)
            if not settings["is_active"] or not settings.get(notification_flag, False):
                continue
            local_now = to_user_local_time(now_utc, settings["timezone"])
            hour, minute = parse_notification_time(settings["notification_time"])
            if (local_now.hour, local_now.minute) >= (hour, minute):
                due.append((user_id, settings, local_now))
        return due

    def _iter_legacy_due_users(self, now) -> list[tuple[int, dict, datetime]]:
        self._require_reminders()
        due: list[tuple[int, dict, datetime]] = []
        active_users = set(self.batches.list_active_users(now.date()))
        for settings in self.reminders.list_enabled():
            if settings.user_id not in active_users:
                continue
            if settings.last_sent_date == now.date():
                continue
            if (now.hour, now.minute) >= (settings.hour, settings.minute):
                due.append(
                    (
                        settings.user_id,
                        {"user_id": settings.user_id, "timezone": "UTC"},
                        now,
                    )
                )
        return due

    def list_known_users(self) -> list[int]:
        users = set(self.batches.list_known_users())
        if self.reminders is not None:
            users.update(self.reminders.list_known_users())
        if self.users is not None:
            users.update(self.users.list_known_users())
        return sorted(users)

    def register_user(
        self,
        *,
        user_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> None:
        if self.users is None:
            return
        meta = self.users.upsert(
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        if meta["existed"] and _is_returning_user(meta):
            self.track("user_returned", user_id=user_id, entity_type="user", entity_id=user_id)

    def get_user_settings(self, user_id: int) -> dict:
        if self.users is None:
            return {}
        return self.users.get_settings(user_id)

    def update_user_settings(self, user_id: int, **fields) -> dict:
        if self.users is None:
            return {}
        settings = self.users.update_settings(user_id, **fields)
        if any(key.startswith("notify_") for key in fields):
            self.track(
                "notifications_changed",
                user_id=user_id,
                entity_type="user",
                entity_id=user_id,
                payload=fields,
            )
        return settings

    def mark_user_inactive(self, user_id: int, reason: str) -> None:
        if self.users is not None:
            self.users.mark_inactive(user_id, reason)

    def track(
        self,
        event_name: str,
        *,
        user_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        payload: dict | None = None,
    ) -> None:
        if self.analytics is not None:
            self.analytics.track(
                event_name,
                user_id=user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=payload,
            )

    def track_scenario_error(
        self,
        *,
        user_id: int | None,
        scenario: str,
        message: str,
        payload: dict | None = None,
    ) -> None:
        details = {"scenario": scenario, "message": message}
        if payload:
            details.update(payload)
        self.track("scenario_error", user_id=user_id, payload=details)

    def _require_reminders(self) -> None:
        if self.reminders is None:
            raise RuntimeError("Reminder repository is not configured")


def parse_notification_time(value: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError("Время уведомления должно быть в формате ЧЧ:ММ") from exc
    return parsed.hour, parsed.minute


def to_user_local_time(now_utc: datetime, timezone_name: str) -> datetime:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=ZoneInfo("UTC"))
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("Europe/Moscow")
    return now_utc.astimezone(timezone)


def _is_returning_user(meta: dict) -> bool:
    if meta.get("was_inactive"):
        return True
    last_seen_raw = meta.get("last_seen_at")
    if not last_seen_raw:
        return False
    try:
        last_seen = datetime.fromisoformat(str(last_seen_raw))
    except ValueError:
        return False
    return last_seen.date() < datetime.utcnow().date()
