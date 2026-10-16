"""Things the bot notices on its own: a drop in laying, short winter days, chicks that have grown up."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# --- egg drop -------------------------------------------------------------------

DROP_RECENT_DAYS = 3
DROP_BASELINE_DAYS = 14
DROP_MIN_BASELINE_RECORDED = 7
DROP_MIN_BASELINE_AVG = 3.0
DROP_THRESHOLD = 0.30


@dataclass(frozen=True)
class EggDrop:
    recent_avg: float
    baseline_avg: float
    recent_days: tuple[date, ...]

    @property
    def drop_percent(self) -> float:
        return (1 - self.recent_avg / self.baseline_avg) * 100 if self.baseline_avg else 0.0


def detect_egg_drop(eggs, user_id: int, *, today: date) -> EggDrop | None:
    """Last 3 full days (today is not over yet) against the 14 days before them.

    Only days with a record count: a forgotten entry is not a drop. All three recent
    days must be recorded, and the baseline must have at least a week of records.
    """
    recent_end = today - timedelta(days=1)
    recent_start = recent_end - timedelta(days=DROP_RECENT_DAYS - 1)
    base_end = recent_start - timedelta(days=1)
    base_start = base_end - timedelta(days=DROP_BASELINE_DAYS - 1)
    recent = eggs.daily_totals(user_id, start_date=recent_start, end_date=recent_end)
    baseline = eggs.daily_totals(user_id, start_date=base_start, end_date=base_end)
    if len(recent) < DROP_RECENT_DAYS or len(baseline) < DROP_MIN_BASELINE_RECORDED:
        return None
    recent_avg = sum(recent.values()) / len(recent)
    baseline_avg = sum(baseline.values()) / len(baseline)
    if baseline_avg < DROP_MIN_BASELINE_AVG or recent_avg > baseline_avg * (1 - DROP_THRESHOLD):
        return None
    return EggDrop(recent_avg=recent_avg, baseline_avg=baseline_avg, recent_days=tuple(sorted(recent)))


# --- daylight -------------------------------------------------------------------

# Laying hens need 14-16 hours of light a day; below ~12-13 hours laying drops.
TARGET_LIGHT_HOURS = 15.0
MIN_LIGHT_HOURS = 14.0
MAX_LIGHT_HOURS = 16.0
EARLIEST_LIGHT_ON = 4.5  # do not wake the hens before 04:30
DEFAULT_LATITUDE = 55.75  # Moscow, when the farm city is not set
DEFAULT_LONGITUDE = 37.62


@dataclass(frozen=True)
class Daylight:
    day: date
    hours: float
    sunrise: time | None
    sunset: time | None
    place: str

    @property
    def extra_hours(self) -> float:
        return max(MIN_LIGHT_HOURS - self.hours, 0.0)


def _sun_times(day: date, latitude: float, longitude: float, zone: ZoneInfo) -> tuple[float, time | None, time | None]:
    """Day length and local sunrise/sunset (NOAA approximation, ±2 min)."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (
        0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
    )
    lat = math.radians(latitude)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(lat) * math.cos(decl))) - math.tan(lat) * math.tan(decl)
    if cos_ha >= 1:
        return 0.0, None, None
    if cos_ha <= -1:
        return 24.0, None, None
    ha = math.degrees(math.acos(cos_ha))
    noon_utc_min = 720 - 4 * longitude - eqtime
    base = datetime.combine(day, time(0), tzinfo=timezone.utc)

    def local(minutes: float) -> time:
        return (base + timedelta(minutes=minutes)).astimezone(zone).time().replace(second=0, microsecond=0)

    return 8 * ha / 60, local(noon_utc_min - 4 * ha), local(noon_utc_min + 4 * ha)


def daylight(
    day: date,
    *,
    latitude: float | None,
    longitude: float | None,
    timezone_name: str,
    place: str = "",
) -> Daylight:
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("Europe/Moscow")
    if latitude is None or longitude is None:
        latitude, longitude, place = DEFAULT_LATITUDE, DEFAULT_LONGITUDE, place or "Москва (город хозяйства не задан)"
    hours, sunrise, sunset = _sun_times(day, latitude, longitude, zone)
    return Daylight(day=day, hours=hours, sunrise=sunrise, sunset=sunset, place=place)


def _hm(hours: float) -> str:
    total = round(hours * 60)
    return f"{total // 60} ч {total % 60:02d} мин"


def _shift(value: time, hours: float) -> str:
    moment = datetime.combine(date(2000, 1, 1), value) + timedelta(hours=hours)
    return moment.strftime("%H:%M")


def light_advice_lines(light: Daylight, *, compact: bool = False) -> list[str]:
    head = f"- Световой день: {_hm(light.hours)}"
    if light.sunrise and light.sunset:
        head += f" (восход {light.sunrise.strftime('%H:%M')}, закат {light.sunset.strftime('%H:%M')})"
    head += f", {light.place}." if light.place else "."
    if light.hours >= MIN_LIGHT_HOURS:
        return [head, "- Света хватает, досвечивать не нужно."]
    extra = light.extra_hours
    lines = [
        head,
        f"- Несушкам нужно {MIN_LIGHT_HOURS:g}–{MAX_LIGHT_HOURS:g} ч света, не хватает ≈ {_hm(extra)}: "
        "без досветки яйценоскость зимой падает.",
    ]
    if light.sunrise and light.sunset:
        sunrise_h = light.sunrise.hour + light.sunrise.minute / 60
        morning = min(extra, max(sunrise_h - EARLIEST_LIGHT_ON, 0.0))
        evening = extra - morning
        plan = f"- Например: свет с {_shift(light.sunrise, -morning)} до рассвета"
        if evening > 0.05:
            plan += f" и после заката до {_shift(light.sunset, evening)}"
        if evening > 0.05:
            plan += ". Вечером гасите свет не резко: оставьте слабый свет на 15 минут, чтобы куры успели сесть на насест."
        else:
            plan += ". Досветка утром удобнее всего: вечером куры сами уходят на насест в сумерках."
        lines.append(plan)
    if not compact:
        lines.extend(
            [
                "- Если сейчас не досвечиваете, начните с 1 часа и прибавляйте не больше 30 минут в неделю; "
                "не сокращайте свет, пока куры несутся — резкие перемены вызывают линьку и паузу.",
                f"- Всего света — не больше {MAX_LIGHT_HOURS:g} ч, ночь должна оставаться тёмной. Яркости хватит такой, "
                "чтобы в курятнике можно было читать; удобнее всего лампа тёплого света на таймере.",
            ]
        )
    return lines


# --- chicks that grew up -----------------------------------------------------------

GROWN_CHICK_DAYS = 16 * 7  # from 16 weeks pullets/cockerels eat and live as adults


def grown_chick_groups(groups, *, today: date) -> list:
    return [
        group
        for group in groups
        if group.is_active
        and group.group_kind == "chicks"
        and group.hatched_at is not None
        and (today - group.hatched_at).days >= GROWN_CHICK_DAYS
    ]


def chick_age_text(group, today: date) -> str:
    days = (today - group.hatched_at).days
    return f"{days // 7} нед." if days >= 14 else f"{days} дн."
