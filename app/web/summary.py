from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.eggs import EXCLUSION_REASON_LABELS
from app.services.feed_recipes import (
    DEFAULT_GRAIN_BASE,
    list_grain_base_options,
    load_chicken_mix_recipe,
)
from app.services.feeds import FeedService
from app.services.incubation import IncubationService
from app.services.stock import (
    DEFAULT_ADULT_DAILY_G,
    DEFAULT_HEN_DAILY_G,
    DEFAULT_ROOSTER_DAILY_G,
    STOCK_KIND_LABELS,
    StockService,
)
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
            today=today,
        )
        payload["incubation"] = _incubation_summary(
            incubation_service,
            user_id=selected_user_id,
            today=today,
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


def build_web_mix(
    db_path: Path,
    *,
    user_id: int | None = None,
    now: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> dict:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    summary = build_web_summary(
        db_path,
        user_id=user_id,
        now=current,
        timezone_name=timezone_name,
    )
    selected_user_id = summary.get("selected_user_id")
    if selected_user_id is None or summary.get("db", {}).get("status") != "ok":
        return {
            "generated_at": summary.get("generated_at"),
            "selected_user_id": selected_user_id,
            "db": summary.get("db"),
            "feeds": summary.get("feeds"),
            "mix": None,
            "history": [],
        }

    database = ReadOnlyDatabase(db_path)
    feeds_repository = FeedRepository(database)
    stock_repository = StockRepository(database)
    stock_service = StockService(stock_repository, feeds_repository)
    best_plan = stock_service.best_available_mix_plan(user_id=int(selected_user_id), now=current)
    one_cycle_plan = stock_service.plan_mix(
        user_id=int(selected_user_id),
        mix_count=1,
        grain_base=best_plan.grain_base_code,
        now=current,
    )
    possible_mix_count = int(best_plan.max_mix_count)
    recipe_items = load_chicken_mix_recipe(grain_base=best_plan.grain_base_code)
    recipe_by_name = {item.name: item for item in recipe_items}
    total_parts = sum(item.parts for item in recipe_items)
    variants = [
        _mix_plan_option_payload(
            stock_service.plan_mix(
                user_id=int(selected_user_id),
                mix_count=1,
                grain_base=option.code,
                now=current,
            )
        )
        for option in list_grain_base_options()
    ]
    history = []
    for transaction in stock_service.list_history(int(selected_user_id), limit=60):
        if transaction.type != "mix_output":
            continue
        item = stock_repository.get_item(transaction.stock_item_id, int(selected_user_id))
        history.append(
            {
                "id": transaction.id,
                "mix_id": transaction.related_mix_id,
                "item_name": item.name if item else "",
                "amount_kg": round(transaction.amount_kg, 3),
                "balance_after_kg": round(transaction.balance_after_kg, 3),
                "note": transaction.note,
                "created_at": transaction.created_at.isoformat(),
            }
        )
        if len(history) >= 20:
            break

    ingredients = []
    for ingredient in one_cycle_plan.ingredients:
        recipe_item = recipe_by_name.get(ingredient.name)
        ingredients.append(
            {
                "name": ingredient.name,
                "group": recipe_item.group if recipe_item else "",
                "parts": ingredient.parts,
                "required_kg": round(ingredient.required_kg, 3),
                "available_kg": round(ingredient.available_kg, 3),
                "missing_kg": round(ingredient.missing_kg, 3),
                "stock_item_id": ingredient.stock_item_id,
                "is_enough": ingredient.missing_kg <= 0,
            }
        )

    limiting_ingredient = _mix_limit_ingredient(best_plan)
    return {
        "generated_at": summary.get("generated_at"),
        "selected_user_id": selected_user_id,
        "db": summary.get("db"),
        "feeds": summary.get("feeds"),
        "mix": {
            "title": one_cycle_plan.title,
            "recipe_code": one_cycle_plan.recipe_code,
            "recipe_version": one_cycle_plan.recipe_version,
            "grain_base_code": one_cycle_plan.grain_base_code,
            "grain_base_label": one_cycle_plan.grain_base_label,
            "one_cycle_parts": round(total_parts, 3),
            "one_cycle_kg": round(one_cycle_plan.output_kg, 3),
            "possible_mix_count": possible_mix_count,
            "possible_output_kg": round(best_plan.output_kg * possible_mix_count, 3),
            "limiting_ingredient": limiting_ingredient.name if limiting_ingredient else None,
            "missing_ingredients": [
                ingredient.name for ingredient in best_plan.ingredients if ingredient.missing_kg > 0
            ],
            "ingredients": ingredients,
            "grain_base_options": variants,
            "quick_mix_counts": list(range(1, min(possible_mix_count, 10) + 1)),
        },
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


def build_web_incubation(
    db_path: Path,
    *,
    user_id: int | None = None,
    now: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> dict:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    summary = build_web_summary(
        db_path,
        user_id=user_id,
        now=current,
        timezone_name=timezone_name,
    )
    selected_user_id = summary.get("selected_user_id")
    if selected_user_id is None or summary.get("db", {}).get("status") != "ok":
        return {
            "generated_at": summary.get("generated_at"),
            "selected_user_id": selected_user_id,
            "db": summary.get("db"),
            "incubation": summary.get("incubation"),
            "active_batches": [],
            "completed_batches": [],
        }

    settings = summary.get("settings") or {}
    today = _local_date(current, str(settings.get("timezone") or timezone_name))
    database = ReadOnlyDatabase(db_path)
    incubation_service = IncubationService(BatchRepository(database))
    active_batches = [
        _incubation_status_payload(incubation_service.get_status(batch, today=today))
        for batch in incubation_service.list_active(int(selected_user_id))
    ]
    completed_batches = [
        _completed_batch_payload(
            incubation_service.get_status(batch, today=batch.completed_at or today)
        )
        for batch in incubation_service.list_completed(int(selected_user_id), limit=20)
    ]
    return {
        "generated_at": summary.get("generated_at"),
        "selected_user_id": selected_user_id,
        "db": summary.get("db"),
        "incubation": summary.get("incubation"),
        "active_batches": active_batches,
        "completed_batches": completed_batches,
    }


def build_web_livestock(
    db_path: Path,
    *,
    user_id: int | None = None,
    now: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> dict:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    summary = build_web_summary(
        db_path,
        user_id=user_id,
        now=current,
        timezone_name=timezone_name,
    )
    selected_user_id = summary.get("selected_user_id")
    if selected_user_id is None or summary.get("db", {}).get("status") != "ok":
        return {
            "generated_at": summary.get("generated_at"),
            "selected_user_id": selected_user_id,
            "db": summary.get("db"),
            "feeds": summary.get("feeds"),
            "bird_groups": [],
            "flocks": [],
        }

    database = ReadOnlyDatabase(db_path)
    feeds_repository = FeedRepository(database)
    stock_repository = StockRepository(database)
    feed_service = FeedService(feeds_repository)
    stock_service = StockService(stock_repository, feeds_repository)
    groups = [
        {
            "id": group.id,
            "name": group.name,
            "bird_count": group.bird_count,
            "species": group.species,
            "species_label": _species_label(group.species),
            "group_kind": group.group_kind,
            "group_kind_label": _bird_group_kind_label(group.group_kind),
            "role": group.role,
            "role_label": _bird_role_label(group.role),
            "hatched_at": group.hatched_at.isoformat() if group.hatched_at else None,
            "joined_at": group.joined_at.isoformat() if group.joined_at else None,
            "reserve_percent": round(group.reserve_percent, 1),
        }
        for group in feed_service.list_bird_groups(int(selected_user_id))
    ]
    flocks = []
    for report in stock_service.list_flock_reports(int(selected_user_id), now=current):
        flocks.append(
            {
                "id": report.flock.id,
                "name": report.flock.name,
                "birds_total": sum(member.bird_count for member in report.members),
                "members_count": len(report.members),
                "daily_usage_kg": round(report.daily_usage_kg, 3),
                "members": [
                    {
                        "id": member.id,
                        "bird_group_id": member.bird_group_id,
                        "bird_group_name": member.bird_group_name,
                        "bird_count": member.bird_count,
                        "group_kind": member.group_kind,
                        "group_kind_label": _bird_group_kind_label(member.group_kind),
                        "role": member.role,
                        "role_label": _bird_role_label(member.role),
                        "hatched_at": member.hatched_at.isoformat() if member.hatched_at else None,
                        "joined_at": member.group_joined_at.isoformat()
                        if member.group_joined_at
                        else None,
                    }
                    for member in report.members
                ],
                "assignments": [
                    {
                        "feed_name": usage.assignment.stock_item_name,
                        "share_percent": round(usage.assignment.share_percent, 1),
                        "daily_usage_kg": round(usage.daily_usage_kg, 3),
                        "remaining_kg": round(usage.remaining_kg, 3),
                        "days_left": usage.days_left,
                        "total_days_left": usage.total_days_left,
                        "producible_mix_count": usage.producible_mix_count,
                        "producible_mix_kg": round(usage.producible_mix_kg, 3),
                        "grain_base_label": usage.grain_base_label,
                        "limiting_ingredient": usage.limiting_ingredient_name,
                        "missing_ingredients": list(usage.missing_ingredient_names),
                    }
                    for usage in report.assignments
                ],
            }
        )
    return {
        "generated_at": summary.get("generated_at"),
        "selected_user_id": selected_user_id,
        "db": summary.get("db"),
        "feeds": summary.get("feeds"),
        "bird_groups": groups,
        "flocks": flocks,
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
    today,
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
            _stock_item_payload(stock_service, estimate, today=today)
            for estimate in estimates
        ],
        "ready_mix": {
            "remaining_kg": round(ready_mix_kg, 3),
            "daily_usage_kg": round(daily_mix_usage_kg, 3),
            "days_left": ready_mix_days_left,
            "ends_at": _date_after_days(today, ready_mix_days_left),
            "purchase_by": _purchase_by_date(today, ready_mix_days_left),
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
        "feeding_norms": _feeding_norms_payload(),
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
                        "ends_at": _date_after_days(today, usage.days_left),
                        "purchase_by": _purchase_by_date(today, usage.days_left),
                        "total_days_left": usage.total_days_left,
                        "total_ends_at": _date_after_days(today, usage.total_days_left),
                        "total_purchase_by": _purchase_by_date(today, usage.total_days_left),
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


def _stock_item_payload(stock_service: StockService, estimate, *, today) -> dict:
    last = stock_service.stock.last_transaction(estimate.item.id, estimate.item.user_id)
    return {
        "id": estimate.item.id,
        "name": estimate.item.name,
        "kind": estimate.item.kind,
        "kind_label": STOCK_KIND_LABELS.get(estimate.item.kind, estimate.item.kind),
        "remaining_kg": round(estimate.remaining_kg, 3),
        "daily_usage_kg": round(estimate.daily_usage_kg, 3),
        "days_left": estimate.days_left,
        "ends_at": _date_after_days(today, estimate.days_left),
        "purchase_by": _purchase_by_date(today, estimate.days_left),
        "last_transaction": (
            {
                "id": last.id,
                "type": last.type,
                "type_label": _stock_transaction_label(last.type),
                "amount_kg": round(last.amount_kg, 3),
                "balance_after_kg": round(last.balance_after_kg, 3),
                "note": last.note,
                "created_at": last.created_at.isoformat(),
            }
            if last is not None
            else None
        ),
    }


def _feeding_norms_payload() -> dict:
    return {
        "formula": (
            "Расход = количество птиц * норма грамм/день * доля рациона * "
            "(1 + запас_процентов / 100) / 1000."
        ),
        "adults": [
            {
                "role": "hens",
                "label": "Курица/несушка",
                "daily_g": DEFAULT_HEN_DAILY_G,
            },
            {
                "role": "roosters",
                "label": "Петух",
                "daily_g": DEFAULT_ROOSTER_DAILY_G,
            },
            {
                "role": "mixed",
                "label": "Взрослая смешанная птица",
                "daily_g": DEFAULT_ADULT_DAILY_G,
            },
        ],
        "chicks": [
            {
                "from_day": start_day,
                "to_day": end_day,
                "daily_g": daily_g,
            }
            for start_day, end_day, daily_g in FeedService.chick_daily_schedule()
        ],
        "notes": [
            "Возраст цыпленка считается от даты вывода.",
            "После даты подсадки отдельный расход цыплячьего корма останавливается.",
            "В назначении смеси можно изменить нормы и запас, если фактический рацион отличается.",
        ],
    }


def _date_after_days(today, days_left: int | None) -> str | None:
    if days_left is None:
        return None
    return (today + timedelta(days=max(int(days_left), 0))).isoformat()


def _purchase_by_date(today, days_left: int | None, *, lead_days: int = 7) -> str | None:
    if days_left is None:
        return None
    return (today + timedelta(days=max(int(days_left) - lead_days, 0))).isoformat()


def _incubation_summary(
    incubation: IncubationService,
    *,
    user_id: int,
    today: date,
) -> dict:
    statuses = incubation.get_user_statuses(user_id, today=today)
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


def _incubation_status_payload(status) -> dict:
    batch = status.batch
    return {
        "id": batch.id,
        "title": batch.title,
        "species": batch.species,
        "species_label": status.profile.title,
        "eggs_count": batch.eggs_count,
        "start_date": batch.start_date.isoformat(),
        "day": status.day,
        "stage": status.stage,
        "hatch_date": status.hatch_date.isoformat(),
        "days_left": status.days_left,
        "temperature": (
            status.profile.temperature_lockdown
            if status.day >= status.profile.lockdown_from_day
            else status.profile.temperature_main
        ),
        "humidity": (
            status.profile.humidity_lockdown
            if status.day >= status.profile.lockdown_from_day
            else status.profile.humidity_main
        ),
        "turn_until_day": status.profile.turn_until_day,
        "lockdown_from_day": status.profile.lockdown_from_day,
        "candle_days": list(status.profile.candle_days),
        "recommendations": list(status.recommendations),
        "note": batch.note,
    }


def _completed_batch_payload(status) -> dict:
    batch = status.batch
    hatch_rate = None
    if batch.hatched_count is not None and batch.eggs_count:
        hatch_rate = round(batch.hatched_count / batch.eggs_count * 100, 1)
    payload = _incubation_status_payload(status)
    payload.update(
        {
            "hatched_count": batch.hatched_count,
            "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
            "hatch_rate": hatch_rate,
        }
    )
    return payload


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


def _mix_plan_option_payload(plan) -> dict:
    limiting_ingredient = _mix_limit_ingredient(plan)
    return {
        "code": plan.grain_base_code,
        "label": plan.grain_base_label,
        "possible_mix_count": int(plan.max_mix_count),
        "one_cycle_kg": round(plan.output_kg, 3),
        "limiting_ingredient": limiting_ingredient.name if limiting_ingredient else None,
        "missing_ingredients": [
            ingredient.name for ingredient in plan.ingredients if ingredient.missing_kg > 0
        ],
    }


def _stock_transaction_label(value: str) -> str:
    return {
        "purchase": "покупка",
        "manual_adjustment": "фактический остаток",
        "mix_input": "ингредиент в замес",
        "mix_output": "готовая смесь",
        "write_off": "списание",
    }.get(value, value)


def _species_label(value: str | None) -> str:
    return {
        "chicken": "куры",
        "goose": "гуси",
        "duck": "утки",
        "muscovy_duck": "мускусные утки",
        "quail": "перепела",
    }.get(value or "", value or "не указан")


def _bird_group_kind_label(value: str) -> str:
    return {
        "adult": "взрослая группа",
        "chicks": "цыплята",
    }.get(value, value)


def _bird_role_label(value: str) -> str:
    return {
        "hens": "куры/несушки",
        "roosters": "петухи",
        "chicks": "цыплята",
        "mixed": "смешанная группа",
    }.get(value, value)


def _local_date(current: datetime, timezone_name: str):
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        local_timezone = ZoneInfo("Europe/Moscow")
    return current.astimezone(local_timezone).date()
