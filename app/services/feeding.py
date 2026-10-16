"""«Покормил»: a quick feeding log with the usual home mix.

The owner gives the usual mix in cups (1 cup = 1 litre by default). The bot
splits the cups by the composition of "my mix" (parts per ingredient, like the
recipe), turns litres into kilograms with each ingredient's bulk density and
writes off the ingredients that exist in the warehouse. Without an amount the
flock's daily norm is used (hens 120 g, roosters 150 g, mixed 120 g, chicks by
age, plus the group's reserve).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain import CONTENT
from app.services.feeds import FeedService
from app.services.stock import (
    DEFAULT_ADULT_DAILY_G,
    DEFAULT_HEN_DAILY_G,
    DEFAULT_ROOSTER_DAILY_G,
    StockService,
    _normalize_stock_name,
)
from app.storage.repositories.feeding import FeedingEvent, FeedingRepository
from app.storage.repositories.feeds import FeedRepository


# A second tap within this time is treated as the same feeding (double tap).
DUPLICATE_WINDOW = timedelta(minutes=2)
# Evening reminder when nothing was marked during the day.
FEEDING_REMINDER_TIME = time(19, 0)
QUICK_CUPS = (3.0, 3.5, 4.0)
# Feeding in cups within this many days means the owner feeds the home mix
# straight from ingredients, so "finished mix" warnings do not apply.
PACE_LOOKBACK_DAYS = 14
PACE_WINDOW_DAYS = 7
PACE_WARNING_DAYS = 7
PACE_URGENT_DAYS = 2
MAX_CUPS = 100
DEFAULT_DENSITY_KG_PER_L = 0.7
# The owner's usual mix: the bot recipe without barley and meat-and-bone meal,
# with the layer grain mix as the grain base. Editable per user.
DEFAULT_MIX = (
    ("Кукуруза", 3.5),
    ("Зерновая смесь для кур несушек", 2.5),
    ("Комбикорм", 1.5),
    ("Ракушка", 0.5),
    ("Рыбная мука", 0.2),
    ("Премикс", 0.1),
)


def _recipe_catalog() -> dict[str, tuple[str, float, tuple[str, ...]]]:
    """normalized name/alias -> (canonical name, density, aliases) from the recipe."""
    recipe = CONTENT["feed_recipes"]["chicken_mix"]
    entries = list(recipe["ingredients"])
    for variant in recipe.get("ingredient_variants", {}).values():
        entries.extend(variant.get("options", []))
    catalog: dict[str, tuple[str, float, tuple[str, ...]]] = {}
    for entry in entries:
        if "density_kg_per_l" not in entry:
            continue
        aliases = tuple(str(alias) for alias in entry.get("aliases", []))
        value = (str(entry["name"]), float(entry["density_kg_per_l"]), aliases)
        for key in (entry["name"], *aliases):
            catalog.setdefault(_normalize_stock_name(str(key)), value)
    return catalog


RECIPE_CATALOG = _recipe_catalog()


@dataclass(frozen=True)
class MixPart:
    name: str
    parts: float
    density_kg_per_l: float
    aliases: tuple[str, ...] = ()


def mix_part(name: str, parts: float) -> MixPart:
    known = RECIPE_CATALOG.get(_normalize_stock_name(name))
    if known is None:
        return MixPart(name=name.strip(), parts=parts, density_kg_per_l=DEFAULT_DENSITY_KG_PER_L)
    canonical, density, aliases = known
    return MixPart(name=canonical, parts=parts, density_kg_per_l=density, aliases=(name.strip(), *aliases))


def parse_mix_text(text: str) -> list[tuple[str, float]]:
    """«Кукуруза 3,5» per line (or separated by ;) -> [(name, parts)]."""
    result: list[tuple[str, float]] = []
    for raw in re.split(r"[\n;]+", text or ""):
        line = raw.strip().strip("-•").strip()
        if not line:
            continue
        match = re.match(r"^(.*?)[\s:=-]+(\d+(?:[.,]\d+)?)\s*(?:кр\w*|ч\w*)?$", line, flags=re.IGNORECASE)
        if not match or not match.group(1).strip():
            raise ValueError(f"Не понял строку «{line}». Пишите так: Кукуруза 3,5")
        parts = float(match.group(2).replace(",", "."))
        if parts <= 0 or parts > 50:
            raise ValueError(f"«{line}»: число кружек должно быть от 0,1 до 50.")
        result.append((match.group(1).strip()[:60], parts))
    if not result:
        raise ValueError("Состав пустой. Пришлите хотя бы один ингредиент, например: Кукуруза 3,5")
    if len(result) > 15:
        raise ValueError("Слишком много ингредиентов: не больше 15.")
    return result


def parse_cups(text: str) -> float:
    cleaned = (text or "").strip().lower().replace(",", ".")
    cleaned = re.sub(r"\s*(кружк\w*|кр\.?)$", "", cleaned).strip()
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise ValueError("Нужно число кружек, например 3,5.") from exc
    if not 0 < value <= MAX_CUPS:
        raise ValueError(f"Число кружек должно быть от 0,5 до {MAX_CUPS}.")
    return round(value, 2)


@dataclass(frozen=True)
class GivenIngredient:
    name: str
    kg: float
    in_stock: bool
    remaining_kg: float | None = None


@dataclass(frozen=True)
class FeedingNorm:
    bird_count: int
    daily_kg: float


@dataclass(frozen=True)
class IngredientPace:
    name: str
    per_day_kg: float
    remaining_kg: float | None
    days_left: int | None


@dataclass(frozen=True)
class FeedPace:
    """How fast the home mix is eaten, from «Покормил» with cups."""

    daily_kg: float
    observed_days: int
    ingredients: tuple[IngredientPace, ...]

    @property
    def soon_out(self) -> tuple[IngredientPace, ...]:
        return tuple(
            item for item in sorted(self.ingredients, key=lambda i: i.days_left if i.days_left is not None else 10**6)
            if item.days_left is not None and item.days_left <= PACE_WARNING_DAYS
        )

    @property
    def not_in_stock(self) -> tuple[IngredientPace, ...]:
        return tuple(item for item in self.ingredients if item.remaining_kg is None)


@dataclass(frozen=True)
class FeedingResult:
    event: FeedingEvent
    duplicate: bool
    feedings_today: int
    ingredients: tuple[GivenIngredient, ...] = ()


@dataclass(frozen=True)
class FeedingWeek:
    fed_days: int
    days: int
    estimated_kg: float
    measured_days: int = 0


class FeedingService:
    def __init__(
        self,
        feeding: FeedingRepository,
        feeds: FeedRepository,
        *,
        stock: StockService | None = None,
        timezone_name: str = "Europe/Moscow",
    ) -> None:
        self.feeding = feeding
        self.feeds = feeds
        self.stock = stock
        self.timezone_name = timezone_name

    # --- my mix ------------------------------------------------------------

    def get_mix(self, user_id: int) -> list[MixPart]:
        saved = self.feeding.get_settings(user_id).mix
        return [mix_part(name, parts) for name, parts in (saved or DEFAULT_MIX)]

    def set_mix(self, user_id: int, parts: list[tuple[str, float]]) -> list[MixPart]:
        if not parts:
            raise ValueError("Состав пустой.")
        self.feeding.save_settings(user_id, mix=[(name, float(value)) for name, value in parts])
        return self.get_mix(user_id)

    def cup_liters(self, user_id: int) -> float:
        return self.feeding.get_settings(user_id).cup_liters

    def set_cup_liters(self, user_id: int, liters: float) -> None:
        if not 0.05 <= liters <= 5:
            raise ValueError("Объём кружки должен быть от 0,05 до 5 литров.")
        self.feeding.save_settings(user_id, cup_liters=liters)

    def last_cups(self, user_id: int) -> float | None:
        return self.feeding.get_settings(user_id).last_cups

    def split_cups(self, user_id: int, cups: float) -> list[tuple[MixPart, float]]:
        """Cups of the ready mix -> kilograms of each ingredient."""
        mix = self.get_mix(user_id)
        total_parts = sum(part.parts for part in mix)
        liters = cups * self.cup_liters(user_id)
        if total_parts <= 0:
            return []
        return [
            (part, round(liters * part.parts / total_parts * part.density_kg_per_l, 3))
            for part in mix
        ]

    def mix_kg_per_cup(self, user_id: int) -> float:
        return round(sum(kg for _, kg in self.split_cups(user_id, 1)), 3)

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

    def record(
        self,
        user_id: int,
        *,
        cups: float | None = None,
        now: datetime | None = None,
    ) -> FeedingResult:
        moment = self._utc(now)
        local_date = self._local(moment).date()
        last = self.feeding.last(user_id)
        if last is not None and timedelta(0) <= moment - last.fed_at < DUPLICATE_WINDOW:
            return FeedingResult(
                last,
                True,
                len(self.events_on(user_id, local_date)),
                self._given_from_items(user_id, last.id),
            )
        if cups is not None and not 0 < cups <= MAX_CUPS:
            raise ValueError(f"Число кружек должно быть от 0,5 до {MAX_CUPS}.")
        norm = self.daily_norm(user_id, on_date=local_date)
        split = self.split_cups(user_id, cups) if cups else []
        event = self.feeding.add(
            user_id=user_id,
            fed_at=moment,
            fed_date=local_date,
            bird_count=norm.bird_count,
            daily_norm_kg=norm.daily_kg,
            cups=cups,
            mix_kg=round(sum(kg for _, kg in split), 3) if split else None,
        )
        given: list[GivenIngredient] = []
        note = f"Покормил {self._local(moment):%d.%m %H:%M}"
        for part, kg in split:
            item = transaction = remaining = None
            if self.stock is not None:
                item, transaction, remaining = self.stock.feeding_write_off(
                    user_id=user_id,
                    names=(part.name, *part.aliases),
                    amount_kg=kg,
                    note=note,
                    now=moment,
                )
            self.feeding.add_item(
                event_id=event.id,
                user_id=user_id,
                name=part.name,
                kg=kg,
                stock_item_id=item.id if transaction is not None else None,
                stock_transaction_id=transaction.id if transaction is not None else None,
            )
            given.append(GivenIngredient(part.name, kg, transaction is not None, remaining))
        if cups:
            self.feeding.save_settings(user_id, last_cups=cups)
        return FeedingResult(event, False, len(self.events_on(user_id, local_date)), tuple(given))

    def undo(self, user_id: int, event_id: int) -> bool:
        event = self.feeding.get(event_id, user_id)
        if event is None:
            return False
        if self.stock is not None:
            for item in self.feeding.items(event_id, user_id):
                if item.stock_item_id is not None and item.stock_transaction_id is not None:
                    self.stock.feeding_restore(
                        user_id=user_id,
                        stock_item_id=item.stock_item_id,
                        amount_kg=item.kg,
                        note=f"Отмена отметки «Покормил» {self.format_time(event)}",
                    )
        return self.feeding.delete(event_id, user_id)

    def _given_from_items(self, user_id: int, event_id: int) -> tuple[GivenIngredient, ...]:
        return tuple(
            GivenIngredient(item.name, item.kg, item.stock_transaction_id is not None)
            for item in self.feeding.items(event_id, user_id)
        )

    def pace(self, user_id: int, *, today: date | None = None) -> FeedPace | None:
        """Daily use of the home mix by ingredient; None if cups were not used recently."""
        current = today or self.local_now().date()
        recent = [
            event
            for event in self.feeding.between(
                user_id, start_date=current - timedelta(days=PACE_LOOKBACK_DAYS - 1), end_date=current
            )
            if event.cups
        ]
        if not recent:
            return None
        first_day = min(event.fed_date for event in recent)
        window = max(1, min(PACE_WINDOW_DAYS, (current - first_day).days + 1))
        start = current - timedelta(days=window - 1)
        in_window = [event for event in recent if event.fed_date >= start]
        totals = self.feeding.item_totals_between(user_id, start_date=start, end_date=current)
        ingredients = []
        for part in self.get_mix(user_id):
            per_day = totals.get(part.name, 0.0) / window
            remaining = days_left = None
            if self.stock is not None:
                item = self.stock._find_stock_item_by_names(user_id=user_id, names=(part.name, *part.aliases))
                if item is not None:
                    remaining = max(self.stock.estimate_item(item).remaining_kg, 0.0)
                    days_left = int(remaining // per_day) if per_day > 0 else None
            ingredients.append(IngredientPace(part.name, round(per_day, 3), remaining, days_left))
        return FeedPace(
            daily_kg=round(sum(event.mix_kg or 0 for event in in_window) / window, 3),
            observed_days=window,
            ingredients=tuple(ingredients),
        )

    def ingredients_week(self, user_id: int, *, today: date | None = None, days: int = 7) -> list[dict]:
        """Ingredient totals over the last days and how long the stock lasts at that pace."""
        current = today or self.local_now().date()
        totals = self.feeding.item_totals_between(
            user_id, start_date=current - timedelta(days=days - 1), end_date=current
        )
        rows = []
        for part in self.get_mix(user_id):
            used = round(totals.get(part.name, 0.0), 3)
            remaining = days_left = None
            if self.stock is not None:
                item = self.stock._find_stock_item_by_names(user_id=user_id, names=(part.name, *part.aliases))
                if item is not None:
                    remaining = round(self.stock.estimate_item(item).remaining_kg, 2)
                    per_day = used / days
                    days_left = int(remaining // per_day) if per_day > 0 else None
            rows.append({"name": part.name, "used_kg": used, "remaining_kg": remaining, "days_left": days_left})
        return rows

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
        # A day with amounts counts what was given; a day of plain taps counts the norm.
        norm_by_day: dict[date, float] = {}
        given_by_day: dict[date, float] = {}
        for event in events:
            norm_by_day[event.fed_date] = max(norm_by_day.get(event.fed_date, 0.0), event.daily_norm_kg)
            if event.mix_kg is not None:
                given_by_day[event.fed_date] = given_by_day.get(event.fed_date, 0.0) + event.mix_kg
        total = sum(given_by_day.get(day, norm) for day, norm in norm_by_day.items())
        return FeedingWeek(
            fed_days=len(norm_by_day),
            days=days,
            estimated_kg=round(total, 2),
            measured_days=len(given_by_day),
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


def format_kg(value: float) -> str:
    if value < 1:
        return f"{value * 1000:.0f} г"
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " кг"


def format_cups(value: float) -> str:
    text = f"{value:g}".replace(".", ",")
    return f"{text} кр."


def pace_lines(pace: FeedPace, *, limit: int = 4) -> list[str]:
    """Summary lines for feeding the home mix straight from ingredients."""
    lines = [
        f"- Кормите своей смесью: около {format_kg(pace.daily_kg)} в день "
        f"(по отметкам «Покормил» за {pace.observed_days} дн.)."
    ]
    soon = pace.soon_out
    if soon:
        marks = [
            ("‼️ " if item.days_left <= PACE_URGENT_DAYS else "") + f"{item.name} — на {item.days_left} дн."
            for item in soon
        ]
        lines.append("- ⚠️ Скоро закончится: " + "; ".join(marks))
    rest = [
        item for item in sorted(pace.ingredients, key=lambda i: i.days_left if i.days_left is not None else 10**6)
        if item.days_left is not None and item not in soon
    ]
    if rest:
        lines.append(
            "- Хватит: " + ", ".join(f"{item.name.lower()} {item.days_left} дн." for item in rest[:limit])
        )
    if pace.not_in_stock:
        lines.append("- Нет на складе (только учёт): " + ", ".join(item.name.lower() for item in pace.not_in_stock) + ".")
    return lines
