from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from pathlib import Path


@dataclass(frozen=True)
class IncubationProfile:
    code: str
    title: str
    hatch_days: int
    temperature_main: str
    temperature_lockdown: str
    humidity_main: str
    humidity_lockdown: str
    turn_until_day: int
    lockdown_from_day: int
    candle_days: tuple[int, ...]
    cooling_from_day: int | None = None
    note: str = ""


@dataclass(frozen=True)
class IncubationBatch:
    id: int
    user_id: int
    species: str
    eggs_count: int
    start_date: date
    title: str
    is_active: bool = True
    hatched_count: int | None = None
    completed_at: date | None = None
    note: str = ""


@dataclass(frozen=True)
class BatchStatus:
    batch: IncubationBatch
    profile: IncubationProfile
    day: int
    hatch_date: date
    days_left: int
    stage: str
    recommendations: tuple[str, ...]


@dataclass(frozen=True)
class ReminderSettings:
    user_id: int
    is_enabled: bool
    hour: int
    minute: int
    last_sent_date: date | None = None


@dataclass(frozen=True)
class FeedStock:
    id: int
    user_id: int
    name: str
    amount_kg: float
    bird_count: int
    daily_per_bird_g: float
    low_threshold_kg: float
    created_at: datetime
    updated_at: datetime | None = None
    purchase_reminded_at: datetime | None = None
    bird_group_id: int | None = None
    bird_group_name: str | None = None
    is_archived: bool = False


@dataclass(frozen=True)
class BirdGroup:
    id: int
    user_id: int
    name: str
    bird_count: int
    species: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class FeedTransaction:
    id: int
    feed_id: int
    user_id: int
    type: str
    amount_kg: float
    balance_after_kg: float
    note: str
    created_at: datetime


@dataclass(frozen=True)
class FeedEstimate:
    feed: FeedStock
    remaining_kg: float
    daily_usage_kg: float
    days_left: int | None
    threshold_days_left: int | None
    buy_remind_at: datetime | None


def content_path() -> Path:
    return Path(__file__).resolve().parent / "content" / "incubation.json"


def load_content() -> dict:
    with content_path().open("r", encoding="utf-8") as file:
        return json.load(file)


CONTENT = load_content()
CONTENT_VERSION = str(CONTENT["version"])
DISCLAIMER_TEXT = str(CONTENT["disclaimer"])


def _load_profiles() -> dict[str, IncubationProfile]:
    profiles: dict[str, IncubationProfile] = {}
    for code, payload in CONTENT["profiles"].items():
        profiles[code] = IncubationProfile(
            code=code,
            title=str(payload["title"]),
            hatch_days=int(payload["hatch_days"]),
            temperature_main=str(payload["temperature_main"]),
            temperature_lockdown=str(payload["temperature_lockdown"]),
            humidity_main=str(payload["humidity_main"]),
            humidity_lockdown=str(payload["humidity_lockdown"]),
            turn_until_day=int(payload["turn_until_day"]),
            lockdown_from_day=int(payload["lockdown_from_day"]),
            candle_days=tuple(int(day) for day in payload["candle_days"]),
            cooling_from_day=(
                int(payload["cooling_from_day"])
                if payload.get("cooling_from_day") is not None
                else None
            ),
            note=str(payload.get("note", "")),
        )
    return profiles


PROFILES: dict[str, IncubationProfile] = _load_profiles()


def get_profile(species: str) -> IncubationProfile:
    try:
        return PROFILES[species]
    except KeyError as exc:
        raise ValueError(f"Unknown species: {species}") from exc


def calculate_hatch_date(start_date: date, profile: IncubationProfile) -> date:
    return start_date + timedelta(days=profile.hatch_days)
