from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.eggs import EXCLUSION_REASON_LABELS
from app.services.feed_recipes import DEFAULT_GRAIN_BASE
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.stock import STOCK_KIND_LABELS, StockService
from app.storage.repositories.batches import BatchRepository
from app.storage.repositories.eggs import EggRepository
from app.storage.repositories.feeds import FeedRepository
from app.storage.repositories.stock import StockRepository
from app.storage.repositories.users import UserRepository


@dataclass(frozen=True)
class WebSummaryBuilder:
    db_path: Path
    timezone_name: str = "Europe/Moscow"

    def build(self, *, user_id: int | None = None, now: datetime | None = None) -> dict:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        payload = _empty_payload(current)
        if not self.db_path.exists():
            payload["db"] = {
                "status": "error",
                "path": str(self.db_path),
                "last_error": "Database not found.",
            }
            return payload
        database = ReadOnlyDatabase(self.db_path)
        users = UserRepository(database)
        known_users = users.list_known_users()
        active_users = users.list_active_users()
        selected_user_id = _select_user_id(user_id, known_users, active_users)

        payload["db"] = {"status": "ok", "path": str(self.db_path), "last_error": None}
        payload["selected_user_id"] = selected_user_id
        payload["users"] = {
            "total": len(known_users),
            "active": len(active_users),
            "known_ids": known_users,
            "active_ids": active_users,
        }
        if selected_user_id is None:
            return payload

        feeds_repository = FeedRepository(database)
        stock_repository = StockRepository(database)
        eggs_repository = EggRepository(database)
        feed_service = FeedService(feeds_repository)
        stock_service = StockService(stock_repository, feeds_repository)
        incubation_service = IncubationService(BatchRepository(database))
        user_settings = users.get_settings(selected_user_id)
        today = _local_date(current, str(user_settings.get("timezone") or self.timezone_name))

        payload["settings"] = _settings(user_settings)
        payload["eggs"] = _eggs_summary(
            eggs_repository,
            feeds_repository,
            user_id=selected_user_id,
            today=today,
        )
        payload["feeds"] = _feeds_summary(
            feed_service,
            stock_service,
            user_id=selected_user_id,
            now=current,
        )
        payload["incubation"] = _incubation_summary(
            incubation_service,
            user_id=selected_user_id,
        )
        return payload


def build_web_summary(
    db_path: Path,
    *,
    user_id: int | None = None,
    now: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> dict:
    return WebSummaryBuilder(db_path=db_path, timezone_name=timezone_name).build(
        user_id=user_id,
        now=now,
    )


def build_web_feeds(
    db_path: Path,
    *,
    user_id: int | None = None,
    now: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> dict:
    summary = build_web_summary(
        db_path,
        user_id=user_id,
        now=now,
        timezone_name=timezone_name,
    )
    selected_user_id = summary.get("selected_user_id")
    if selected_user_id is None or summary.get("db", {}).get("status") != "ok":
        return {
            "generated_at": summary.get("generated_at"),
            "selected_user_id": selected_user_id,
            "db": summary.get("db"),
            "feeds": summary.get("feeds"),
            "history": [],
        }

    database = ReadOnlyDatabase(db_path)
    feeds_repository = FeedRepository(database)
    stock_repository = StockRepository(database)
    stock_service = StockService(stock_repository, feeds_repository)
    history = []
    for transaction in stock_service.list_history(int(selected_user_id), limit=30):
        item = stock_repository.get_item(transaction.stock_item_id, int(selected_user_id))
        history.append(
            {
                "id": transaction.id,
                "item_name": item.name if item else "",
                "type": transaction.type,
                "type_label": _stock_transaction_label(transaction.type),
                "amount_kg": round(transaction.amount_kg, 3),
                "balance_after_kg": round(transaction.balance_after_kg, 3),
                "note": transaction.note,
                "created_at": transaction.created_at.isoformat(),
            }
        )

    return {
        "generated_at": summary.get("generated_at"),
        "selected_user_id": selected_user_id,
        "db": summary.get("db"),
        "feeds": summary.get("feeds"),
        "history": history,
    }


def build_web_eggs(
    db_path: Path,
    *,
    user_id: int | None = None,
    now: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> dict:
    summary = build_web_summary(
        db_path,
        user_id=user_id,
        now=now,
        timezone_name=timezone_name,
    )
    selected_user_id = summary.get("selected_user_id")
    if selected_user_id is None or summary.get("db", {}).get("status") != "ok":
        return {
            "generated_at": summary.get("generated_at"),
            "selected_user_id": selected_user_id,
            "db": summary.get("db"),
            "eggs": summary.get("eggs"),
            "history": [],
            "open_exclusions": [],
        }

    database = ReadOnlyDatabase(db_path)
    eggs_repository = EggRepository(database)
    history = [
        {
            "id": entry.id,
            "entry_date": entry.entry_date.isoformat(),
            "eggs_count": entry.eggs_count,
            "active_hens_count": entry.active_hens_count,
            "total_hens_count": entry.total_hens_count,
            "excluded_hens_count": entry.excluded_hens_count,
            "note": entry.note,
            "created_at": entry.created_at.isoformat(),
        }
        for entry in eggs_repository.list_entries(int(selected_user_id), limit=30)
    ]
    open_exclusions = [
        {
            "id": item.id,
            "hens_count": item.hens_count,
            "reason": EXCLUSION_REASON_LABELS.get(item.reason, item.reason),
            "started_at": item.started_at.isoformat(),
            "expected_until": item.expected_until.isoformat() if item.expected_until else None,
            "bird_group_name": item.bird_group_name,
            "note": item.note,
        }
        for item in eggs_repository.list_open_exclusions(int(selected_user_id))
    ]
    return {
        "generated_at": summary.get("generated_at"),
        "selected_user_id": selected_user_id,
        "db": summary.get("db"),
        "eggs": summary.get("eggs"),
        "history": history,
        "open_exclusions": open_exclusions,
    }


class ManagedReadOnlyConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class ReadOnlyDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, factory=ManagedReadOnlyConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection


def _empty_payload(current: datetime) -> dict:
    return {
        "generated_at": current.isoformat(),
        "selected_user_id": None,
        "db": {"status": "unknown", "path": "", "last_error": None},
        "users": {
            "total": 0,
            "active": 0,
            "known_ids": [],
            "active_ids": [],
        },
        "eggs": None,
        "feeds": None,
        "incubation": None,
        "settings": None,
    }


def _select_user_id(
    requested_user_id: int | None,
    known_users: list[int],
    active_users: list[int],
) -> int | None:
    if requested_user_id is not None:
        return requested_user_id if requested_user_id in known_users else None
    if active_users:
        return active_users[0]
    return known_users[0] if known_users else None


def _settings(settings: dict) -> dict:
    return {
        "farm_name": settings.get("farm_name") or "",
        "timezone": settings.get("timezone") or "Europe/Moscow",
        "notification_time": settings.get("notification_time") or "09:00",
        "sections": {
            "incubation": bool(settings.get("notify_incubation", True)),
            "feeds": bool(settings.get("notify_feed", True)),
            "eggs": bool(settings.get("notify_eggs", True)),
            "post_hatch_care": bool(settings.get("notify_post_hatch_care", True)),
            "service": bool(settings.get("notify_service", True)),
        },
    }


def _eggs_summary(
    eggs: EggRepository,
    feeds: FeedRepository,
    *,
    user_id: int,
    today,
) -> dict:
    total_hens = sum(
        group.bird_count
        for group in feeds.list_bird_groups(user_id)
        if group.is_active and group.group_kind == "adult" and group.role == "hens"
    )
    active_exclusions = eggs.list_active_exclusions(user_id, on_date=today)
    excluded_hens = min(sum(item.hens_count for item in active_exclusions), total_hens)
    active_hens = max(total_hens - excluded_hens, 0)
    week_start = today - timedelta(days=6)
    month_start = today - timedelta(days=29)
    today_eggs = eggs.sum_between(user_id, start_date=today, end_date=today)
    week_eggs = eggs.sum_between(user_id, start_date=week_start, end_date=today)
    month_eggs = eggs.sum_between(user_id, start_date=month_start, end_date=today)
    weather = eggs.get_daily_weather(user_id=user_id, weather_date=today)
    return {
        "today": today.isoformat(),
        "today_eggs": today_eggs,
        "week_eggs": week_eggs,
        "month_eggs": month_eggs,
        "next_week_forecast": round(week_eggs / 7 * 7),
        "total_hens": total_hens,
        "active_hens": active_hens,
        "excluded_hens": excluded_hens,
        "active_exclusions": [
            {
                "id": item.id,
                "hens_count": item.hens_count,
                "reason": EXCLUSION_REASON_LABELS.get(item.reason, item.reason),
                "started_at": item.started_at.isoformat(),
                "expected_until": item.expected_until.isoformat() if item.expected_until else None,
            }
            for item in active_exclusions
        ],
        "weather": _weather_payload(weather),
    }


def _feeds_summary(
    feed_service: FeedService,
    stock_service: StockService,
    *,
    user_id: int,
    now: datetime,
) -> dict:
    estimates = stock_service.list_estimates(user_id, now=now)
    ready_mix = [
        estimate
        for estimate in estimates
        if estimate.item.kind == "finished_mix"
        and "смесь" in estimate.item.name.strip().lower().replace("ё", "е")
    ]
    ready_mix_kg = sum(item.remaining_kg for item in ready_mix)
    daily_mix_usage_kg = sum(item.daily_usage_kg for item in ready_mix)
    ready_mix_days_left = (
        min((item.days_left for item in ready_mix if item.days_left is not None), default=None)
        if ready_mix
        else None
    )
    try:
        mix_plan = stock_service.best_available_mix_plan(user_id=user_id, now=now)
        possible_mix_count = int(mix_plan.max_mix_count)
        possible_mix_kg = mix_plan.output_kg * possible_mix_count
        limiting_ingredient = _mix_limit_ingredient(mix_plan)
        missing_ingredients = [item.name for item in mix_plan.ingredients if item.missing_kg > 0]
    except Exception:
        mix_plan = None
        possible_mix_count = 0
        possible_mix_kg = 0.0
        limiting_ingredient = None
        missing_ingredients = []

    groups = feed_service.list_bird_groups(user_id)
    flocks = feed_service.list_flocks(user_id)
    flock_reports = stock_service.list_flock_reports(user_id, now=now)
    return {
        "stock_items": [
            {
                "id": estimate.item.id,
                "name": estimate.item.name,
                "kind": estimate.item.kind,
                "kind_label": STOCK_KIND_LABELS.get(estimate.item.kind, estimate.item.kind),
                "remaining_kg": round(estimate.remaining_kg, 3),
                "daily_usage_kg": round(estimate.daily_usage_kg, 3),
                "days_left": estimate.days_left,
            }
            for estimate in estimates
        ],
        "ready_mix": {
            "remaining_kg": round(ready_mix_kg, 3),
            "daily_usage_kg": round(daily_mix_usage_kg, 3),
            "days_left": ready_mix_days_left,
        },
        "possible_mix": {
            "grain_base": mix_plan.grain_base_label if mix_plan else DEFAULT_GRAIN_BASE,
            "mix_count": possible_mix_count,
            "output_kg": round(possible_mix_kg, 3),
            "limiting_ingredient": limiting_ingredient.name if limiting_ingredient else None,
            "missing_ingredients": missing_ingredients,
        },
        "bird_groups": {
            "total": len(groups),
            "birds_total": sum(item.bird_count for item in groups),
            "hens": sum(item.bird_count for item in groups if item.role == "hens"),
            "roosters": sum(item.bird_count for item in groups if item.role == "roosters"),
            "chicks": sum(item.bird_count for item in groups if item.group_kind == "chicks"),
        },
        "flocks": [
            {
                "id": report.flock.id,
                "name": report.flock.name,
                "members_count": len(report.members),
                "birds_total": sum(member.bird_count for member in report.members),
                "daily_usage_kg": round(report.daily_usage_kg, 3),
                "assignments": [
                    {
                        "feed_name": usage.assignment.stock_item_name,
                        "remaining_kg": round(usage.remaining_kg, 3),
                        "days_left": usage.days_left,
                        "total_days_left": usage.total_days_left,
                        "producible_mix_count": usage.producible_mix_count,
                        "producible_mix_kg": round(usage.producible_mix_kg, 3),
                        "limiting_ingredient": usage.limiting_ingredient_name,
                    }
                    for usage in report.assignments
                ],
            }
            for report in flock_reports
        ],
        "flocks_total": len(flocks),
    }


def _incubation_summary(
    incubation: IncubationService,
    *,
    user_id: int,
) -> dict:
    statuses = incubation.get_user_statuses(user_id)
    stats = incubation.get_stats(user_id)
    return {
        "active_batches": stats.active_batches,
        "completed_batches": stats.completed_batches,
        "total_batches": stats.total_batches,
        "hatch_rate": round(stats.hatch_rate, 1) if stats.hatch_rate is not None else None,
        "batches": [
            {
                "id": status.batch.id,
                "title": status.batch.title,
                "species": status.profile.title,
                "eggs_count": status.batch.eggs_count,
                "day": status.day,
                "stage": status.stage,
                "hatch_date": status.hatch_date.isoformat(),
                "days_left": status.days_left,
            }
            for status in statuses
        ],
    }


def _weather_payload(weather) -> dict | None:
    if weather is None:
        return None
    return {
        "city": weather.city,
        "date": weather.weather_date.isoformat(),
        "day": {
            "temperature_min_c": weather.day_temperature_min_c,
            "temperature_max_c": weather.day_temperature_max_c,
            "condition": weather.day_condition,
        },
        "night": {
            "temperature_min_c": weather.night_temperature_min_c,
            "temperature_max_c": weather.night_temperature_max_c,
            "condition": weather.night_condition,
        },
        "tomorrow": {
            "date": weather.tomorrow_date.isoformat() if weather.tomorrow_date else None,
            "temperature_min_c": weather.tomorrow_temperature_min_c,
            "temperature_max_c": weather.tomorrow_temperature_max_c,
            "condition": weather.tomorrow_condition,
        },
        "provider": weather.provider,
    }


def _mix_limit_ingredient(plan):
    candidates = [item for item in plan.ingredients if item.required_kg > 0]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item.available_kg / item.required_kg)


def _stock_transaction_label(value: str) -> str:
    return {
        "purchase": "покупка",
        "manual_adjustment": "фактический остаток",
        "mix_input": "ингредиент в замес",
        "mix_output": "готовая смесь",
        "write_off": "списание",
    }.get(value, value)


def _local_date(current: datetime, timezone_name: str):
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = ZoneInfo("Europe/Moscow")
    return current.astimezone(local_timezone).date()
