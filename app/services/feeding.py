"""«Покормил»: a one-tap feeding log with the usual mix.

The owner does not weigh every feed. One tap records that the birds were fed;
how much mix that is comes from the flock's norm (the same norms the bot and
the site show: hens 120 g, roosters 150 g, mixed 120 g, chicks by age, plus the
group's reserve). The warehouse is not touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.feeds import FeedService
from app.services.stock import DEFAULT_ADULT_DAILY_G, DEFAULT_HEN_DAILY_G, DEFAULT_ROOSTER_DAILY_G
from app.storage.repositories.feeding import FeedingEvent, FeedingRepository
from app.storage.repositories.feeds import FeedRepository


# A second tap within this time is treated as the same feeding (double tap).
DUPLICATE_WINDOW = timedelta(minutes=2)
# Evening reminder when nothing was marked during the day.
FEEDING_REMINDER_TIME = time(19, 0)


@dataclass(frozen=True)
class FeedingNorm:
    bird_count: int
    daily_kg: float


@dataclass(frozen=True)
class FeedingResult:
    event: FeedingEvent
    duplicate: bool
    feedings_today: int


@dataclass(frozen=True)
class FeedingWeek:
    fed_days: int
    days: int
    estimated_kg: float


class FeedingService:
    def __init__(
        self,
        feeding: FeedingRepository,
        feeds: FeedRepository,
        *,
        timezone_name: str = "Europe/Moscow",
    ) -> None:
        self.feeding = feeding
        self.feeds = feeds
        self.timezone_name = timezone_name

    # --- norms -----------------------------------------------------------

    def daily_norm(self, user_id: int, *, on_date: date | None = None) -> FeedingNorm:
        current = on_date or self.local_now().date()
        birds = 0
        grams = 0.0
        for group in self.feeds.list_bird_groups(user_id):
            if not group.is_active or group.bird_count <= 0:
                continue
            if group.group_kind == "chicks" and group.hatched_at is not None:
                per_bird = FeedService.chick_daily_g(max((current - group.hatched_at).days, 0))
            elif group.role == "hens":
                per_bird = DEFAULT_HEN_DAILY_G
            elif group.role == "roosters":
                per_bird = DEFAULT_ROOSTER_DAILY_G
            else:
                per_bird = DEFAULT_ADULT_DAILY_G
            reserve = 1 + max(group.reserve_percent or 0, 0) / 100
            birds += group.bird_count
            grams += group.bird_count * per_bird * reserve
        return FeedingNorm(bird_count=birds, daily_kg=round(grams / 1000, 3))

    # --- actions ---------------------------------------------------------

    def record(self, user_id: int, *, now: datetime | None = None) -> FeedingResult:
        moment = self._utc(now)
        local_date = self._local(moment).date()
        last = self.feeding.last(user_id)
        if last is not None and timedelta(0) <= moment - last.fed_at < DUPLICATE_WINDOW:
            return FeedingResult(last, True, len(self.events_on(user_id, local_date)))
        norm = self.daily_norm(user_id, on_date=local_date)
        event = self.feeding.add(
            user_id=user_id,
            fed_at=moment,
            fed_date=local_date,
            bird_count=norm.bird_count,
            daily_norm_kg=norm.daily_kg,
        )
        return FeedingResult(event, False, len(self.events_on(user_id, local_date)))

    def undo(self, user_id: int, event_id: int) -> bool:
        return self.feeding.delete(event_id, user_id)

    # --- reading ---------------------------------------------------------

    def events_on(self, user_id: int, day: date) -> list[FeedingEvent]:
        return self.feeding.between(user_id, start_date=day, end_date=day)

    def today(self, user_id: int, *, now: datetime | None = None) -> list[FeedingEvent]:
        return self.events_on(user_id, self._local(self._utc(now)).date())

    def week(self, user_id: int, *, today: date | None = None, days: int = 7) -> FeedingWeek:
        current = today or self.local_now().date()
        events = self.feeding.between(
            user_id, start_date=current - timedelta(days=days - 1), end_date=current
        )
        norm_by_day: dict[date, float] = {}
        for event in events:
            norm_by_day[event.fed_date] = max(norm_by_day.get(event.fed_date, 0.0), event.daily_norm_kg)
        return FeedingWeek(
            fed_days=len(norm_by_day),
            days=days,
            estimated_kg=round(sum(norm_by_day.values()), 2),
        )

    def needs_evening_reminder(self, user_id: int, *, now: datetime | None = None) -> bool:
        """Remind only people who use the button, only after 19:00, only if nothing today."""
        local = self._local(self._utc(now))
        if local.time() < FEEDING_REMINDER_TIME:
            return False
        if not self.feeding.has_any(user_id):
            return False
        return not self.events_on(user_id, local.date())

    def format_time(self, event: FeedingEvent) -> str:
        return self._local(event.fed_at).strftime("%H:%M")

    # --- time helpers ----------------------------------------------------

    def local_now(self) -> datetime:
        return self._local(datetime.now(timezone.utc))

    def _zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("Europe/Moscow")

    def _local(self, moment: datetime) -> datetime:
        return moment.astimezone(self._zone())

    @staticmethod
    def _utc(now: datetime | None) -> datetime:
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)


def format_feeding_status(service: FeedingService, user_id: int, *, now: datetime | None = None) -> str:
    """One line for menus and the daily summary."""
    events = service.today(user_id, now=now)
    if not events:
        return "Кормление сегодня: ещё не отмечено."
    times = ", ".join(service.format_time(event) for event in events)
    return f"Кормление сегодня: ✅ {times}."
