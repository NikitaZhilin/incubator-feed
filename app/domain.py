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
    hen_count: int = 0
    rooster_count: int = 0
    hen_daily_g: float | None = None
    rooster_daily_g: float | None = None
    updated_at: datetime | None = None
    purchase_reminded_at: datetime | None = None
    bird_group_id: int | None = None
    bird_group_name: str | None = None
    bird_group_kind: str | None = None
    bird_group_hatched_at: date | None = None
    bird_group_joined_at: date | None = None
    bird_group_reserve_percent: float = 0.0
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
    group_kind: str = "adult"
    role: str = "mixed"
    hatched_at: date | None = None
    joined_at: date | None = None
    reserve_percent: float = 0.0


@dataclass(frozen=True)
class Flock:
    id: int
    user_id: int
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class FlockMember:
    id: int
    user_id: int
    flock_id: int
    bird_group_id: int
    is_active: bool
    joined_at: datetime
    left_at: datetime | None = None
    bird_group_name: str | None = None
    bird_count: int = 0
    group_kind: str = "adult"
    role: str = "mixed"
    hatched_at: date | None = None
    group_joined_at: date | None = None
    reserve_percent: float = 0.0


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


@dataclass(frozen=True)
class StockItem:
    id: int
    user_id: int
    name: str
    kind: str
    unit: str
    low_threshold_kg: float
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StockTransaction:
    id: int
    user_id: int
    stock_item_id: int
    type: str
    amount_kg: float
    balance_after_kg: float
    note: str
    related_mix_id: int | None
    created_at: datetime


@dataclass(frozen=True)
class MixProduction:
    id: int
    user_id: int
    recipe_code: str
    recipe_version: str
    mix_count: float
    output_stock_item_id: int
    output_kg: float
    created_at: datetime


@dataclass(frozen=True)
class MixProductionItem:
    id: int
    mix_production_id: int
    ingredient_stock_item_id: int
    ingredient_name: str
    amount_kg: float


@dataclass(frozen=True)
class FeedingAssignment:
    id: int
    user_id: int
    bird_group_id: int
    stock_item_id: int
    is_active: bool
    started_at: datetime
    ended_at: datetime | None = None
    daily_per_bird_g: float = 120.0
    reserve_percent: float = 0.0
    bird_group_name: str | None = None
    stock_item_name: str | None = None


@dataclass(frozen=True)
class FlockFeedAssignment:
    id: int
    user_id: int
    flock_id: int
    stock_item_id: int
    is_active: bool
    share_percent: float
    daily_per_hen_g: float
    daily_per_rooster_g: float
    daily_per_adult_g: float
    reserve_percent: float
    started_at: datetime
    ended_at: datetime | None = None
    flock_name: str | None = None
    stock_item_name: str | None = None


@dataclass(frozen=True)
class StockEstimate:
    item: StockItem
    remaining_kg: float
    daily_usage_kg: float
    days_left: int | None
    last_transaction_at: datetime | None


@dataclass(frozen=True)
class FlockFeedUsage:
    assignment: FlockFeedAssignment
    daily_usage_kg: float
    remaining_kg: float
    days_left: int | None
    producible_mix_count: int = 0
    producible_mix_kg: float = 0.0
    total_days_left: int | None = None
    grain_base_label: str | None = None
    limiting_ingredient_name: str | None = None
    missing_ingredient_names: tuple[str, ...] = ()
    ingredient_forecasts: tuple["FlockIngredientForecast", ...] = ()


@dataclass(frozen=True)
class FlockIngredientForecast:
    name: str
    available_kg: float
    daily_usage_kg: float
    days_left: int | None


@dataclass(frozen=True)
class FlockReport:
    flock: Flock
    members: tuple[FlockMember, ...]
    assignments: tuple[FlockFeedUsage, ...]
    daily_usage_kg: float


@dataclass(frozen=True)
class EggEntry:
    id: int
    user_id: int
    entry_date: date
    eggs_count: int
    active_hens_count: int
    total_hens_count: int
    excluded_hens_count: int
    note: str
    created_at: datetime


@dataclass(frozen=True)
class HenLayingExclusion:
    id: int
    user_id: int
    hens_count: int
    reason: str
    started_at: date
    expected_until: date | None
    is_active: bool
    note: str
    created_at: datetime
    updated_at: datetime
    bird_group_id: int | None = None
    actual_ended_at: date | None = None
    bird_group_name: str | None = None


@dataclass(frozen=True)
class WeatherSettings:
    user_id: int
    city: str
    latitude: float | None
    longitude: float | None
    provider: str
    updated_at: datetime


@dataclass(frozen=True)
class EggStats:
    today: date
    total_hens_count: int
    excluded_hens_count: int
    active_hens_count: int
    today_eggs: int
    week_eggs: int
    week_average: float
    month_eggs: int
    month_average: float
    eggs_per_active_hen: float | None
    next_week_forecast: int
    active_exclusions: tuple[HenLayingExclusion, ...]
    weather_city: str


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
