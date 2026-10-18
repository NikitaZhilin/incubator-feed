"""Where the eggs are at home and how old they are.

Places (fridge door, trays…) hold lots: eggs of one laying day. A new collection
fills places in order of priority up to their capacity (the door first, then
trays). Eggs that leave the house are taken from the oldest lots. A recount sets
the real number in a place; a move shifts eggs between places keeping their age.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.storage.database import Database


DEFAULT_PLACES = (("Дверца холодильника", 24), ("Лотки", None))
TRAY_SIZE = 30
FRESH_DAYS = 7  # for incubation and the best quality
USE_FIRST_DAYS = 21  # fridge eggs: use or sell these first
AGE_CHOICES = {"fresh": ("до недели", 3), "week2": ("1–2 недели", 10), "old": ("старше 2 недель", 18)}
MAX_PLACES = 10


@dataclass(frozen=True)
class Place:
    id: int
    name: str
    capacity: int | None
    priority: int


@dataclass(frozen=True)
class Lot:
    id: int
    place_id: int
    laid_on: date
    count: int


@dataclass(frozen=True)
class PlaceStock:
    place: Place
    lots: tuple[Lot, ...]

    @property
    def total(self) -> int:
        return sum(lot.count for lot in self.lots)

    @property
    def free(self) -> int | None:
        return None if self.place.capacity is None else max(self.place.capacity - self.total, 0)

    def oldest(self) -> date | None:
        return min((lot.laid_on for lot in self.lots), default=None)


def age_text(days: int) -> str:
    if days <= 0:
        return "сегодняшние"
    return f"{days} дн."


class EggStorage:
    def __init__(self, database: Database) -> None:
        self.database = database

    # --- places -----------------------------------------------------------------

    def places(self, user_id: int) -> list[Place]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, capacity, priority FROM egg_places WHERE user_id = ? AND is_active = 1 ORDER BY priority, id",
                (user_id,),
            ).fetchall()
        return [Place(int(r["id"]), str(r["name"]), r["capacity"], int(r["priority"])) for r in rows]

    def enabled(self, user_id: int) -> bool:
        return bool(self.places(user_id))

    def get_place(self, user_id: int, place_id: int) -> Place | None:
        return next((place for place in self.places(user_id) if place.id == place_id), None)

    def setup_default(self, user_id: int) -> list[Place]:
        if not self.places(user_id):
            for name, capacity in DEFAULT_PLACES:
                self.add_place(user_id, name, capacity)
        return self.places(user_id)

    def add_place(self, user_id: int, name: str, capacity: int | None) -> Place:
        clean = (name or "").strip()[:60]
        if len(clean) < 2:
            raise ValueError("Название места — хотя бы 2 буквы, например «Полка в кладовке».")
        if capacity is not None and not 1 <= capacity <= 10_000:
            raise ValueError("Вместимость — от 1 до 10 000 яиц, или оставьте без ограничения.")
        places = self.places(user_id)
        if any(place.name.lower() == clean.lower() for place in places):
            raise ValueError("Такое место уже есть.")
        if len(places) >= MAX_PLACES:
            raise ValueError(f"Мест хранения может быть не больше {MAX_PLACES}.")
        priority = max((place.priority for place in places), default=0) + 1
        with self.database.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO egg_places (user_id, name, capacity, priority) VALUES (?, ?, ?, ?)",
                (user_id, clean, capacity, priority),
            )
            place_id = int(cursor.lastrowid)
        return self.get_place(user_id, place_id)

    def remove_place(self, user_id: int, place_id: int) -> bool:
        stock = next((s for s in self.contents(user_id) if s.place.id == place_id), None)
        if stock is None:
            return False
        if stock.total:
            raise ValueError(f"В «{stock.place.name}» ещё {stock.total} яиц: сначала перенесите их или пересчитайте в 0.")
        with self.database.connect() as connection:
            connection.execute("UPDATE egg_places SET is_active = 0 WHERE id = ? AND user_id = ?", (place_id, user_id))
        return True

    # --- contents -------------------------------------------------------------------

    def contents(self, user_id: int) -> list[PlaceStock]:
        places = self.places(user_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, place_id, laid_on, count FROM egg_lots WHERE user_id = ? AND count > 0 ORDER BY laid_on, id",
                (user_id,),
            ).fetchall()
        lots = [Lot(int(r["id"]), int(r["place_id"]), date.fromisoformat(r["laid_on"]), int(r["count"])) for r in rows]
        return [PlaceStock(place, tuple(lot for lot in lots if lot.place_id == place.id)) for place in places]

    def total(self, user_id: int) -> int:
        return sum(stock.total for stock in self.contents(user_id))

    def older_than(self, user_id: int, *, today: date, days: int) -> int:
        limit = today - timedelta(days=days)
        return sum(lot.count for stock in self.contents(user_id) for lot in stock.lots if lot.laid_on < limit)

    # --- moving eggs ------------------------------------------------------------------

    def _add_lot(self, connection, user_id: int, place_id: int, laid_on: date, count: int, entry_id=None) -> None:
        if count <= 0:
            return
        connection.execute(
            "INSERT INTO egg_lots (user_id, place_id, laid_on, count, entry_id) VALUES (?, ?, ?, ?, ?)",
            (user_id, place_id, laid_on.isoformat(), count, entry_id),
        )

    def put(
        self,
        user_id: int,
        *,
        laid_on: date,
        count: int,
        entry_id: int | None = None,
        place_id: int | None = None,
    ) -> list[tuple[Place, int]]:
        """Place a collection: into the given place, or by priority up to capacity (the last place takes the rest)."""
        if count <= 0:
            return []
        stocks = self.contents(user_id)
        if not stocks:
            return []
        if place_id is not None:
            plan = [(next(s.place for s in stocks if s.place.id == place_id), count)]
        else:
            plan, left = [], count
            for index, stock in enumerate(stocks):
                last = index == len(stocks) - 1
                room = left if (stock.free is None or last) else min(stock.free, left)
                if room > 0:
                    plan.append((stock.place, room))
                    left -= room
                if left <= 0:
                    break
        with self.database.connect() as connection:
            for place, amount in plan:
                self._add_lot(connection, user_id, place.id, laid_on, amount, entry_id)
        return plan

    def _take_from(self, connection, user_id: int, lots: list[Lot], count: int) -> list[tuple[Lot, int]]:
        taken, left = [], count
        for lot in lots:
            if left <= 0:
                break
            amount = min(lot.count, left)
            connection.execute("UPDATE egg_lots SET count = count - ? WHERE id = ? AND user_id = ?", (amount, lot.id, user_id))
            taken.append((lot, amount))
            left -= amount
        return taken

    def take(self, user_id: int, count: int, *, place_id: int | None = None, outflow_id: int | None = None) -> int:
        """Eggs leave the house: oldest first (from one place or from all). Returns how many were in storage."""
        lots = [
            lot
            for stock in self.contents(user_id)
            if place_id is None or stock.place.id == place_id
            for lot in stock.lots
        ]
        lots.sort(key=lambda lot: (lot.laid_on, lot.id))
        with self.database.connect() as connection:
            taken = self._take_from(connection, user_id, lots, count)
            if outflow_id is not None:
                for lot, amount in taken:
                    connection.execute(
                        "INSERT INTO egg_takes (user_id, outflow_id, place_id, laid_on, count) VALUES (?, ?, ?, ?, ?)",
                        (user_id, outflow_id, lot.place_id, lot.laid_on.isoformat(), amount),
                    )
        return sum(amount for _, amount in taken)

    def give_back(self, user_id: int, outflow_id: int) -> int:
        """Undo of an «eggs out» record: the eggs return where they were, with their age."""
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT place_id, laid_on, count FROM egg_takes WHERE user_id = ? AND outflow_id = ?",
                (user_id, outflow_id),
            ).fetchall()
            active = {place.id for place in self.places(user_id)}
            fallback = next(iter(sorted(active)), None)
            for row in rows:
                place_id = int(row["place_id"]) if int(row["place_id"]) in active else fallback
                if place_id is not None:
                    self._add_lot(connection, user_id, place_id, date.fromisoformat(row["laid_on"]), int(row["count"]))
            connection.execute("DELETE FROM egg_takes WHERE user_id = ? AND outflow_id = ?", (user_id, outflow_id))
        return sum(int(row["count"]) for row in rows)

    def remove_entry_eggs(self, user_id: int, entry_id: int, count: int) -> None:
        """A collection was corrected down or deleted: remove its eggs (then the newest) from storage."""
        all_lots = [lot for stock in self.contents(user_id) for lot in stock.lots]
        with self.database.connect() as connection:
            own_ids = {
                int(r["id"])
                for r in connection.execute(
                    "SELECT id FROM egg_lots WHERE user_id = ? AND entry_id = ?", (user_id, entry_id)
                ).fetchall()
            }
            own = [lot for lot in all_lots if lot.id in own_ids]
            others = sorted((lot for lot in all_lots if lot.id not in own_ids), key=lambda l: (l.laid_on, l.id), reverse=True)
            self._take_from(connection, user_id, own + others, count)

    def redate_entry(self, user_id: int, entry_id: int, laid_on: date) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE egg_lots SET laid_on = ? WHERE user_id = ? AND entry_id = ?", (laid_on.isoformat(), user_id, entry_id)
            )

    def recount(self, user_id: int, place_id: int, actual: int, *, today: date, age: str = "fresh") -> int:
        """Set the real number in a place. Fewer: the oldest go; more: added with the given age. Returns the difference."""
        if actual < 0 or actual > 100_000:
            raise ValueError("Нужно число яиц от 0.")
        stock = next((s for s in self.contents(user_id) if s.place.id == place_id), None)
        if stock is None:
            raise ValueError("Место хранения не найдено.")
        diff = actual - stock.total
        with self.database.connect() as connection:
            if diff < 0:
                self._take_from(connection, user_id, list(stock.lots), -diff)
            elif diff > 0:
                days = AGE_CHOICES.get(age, AGE_CHOICES["fresh"])[1]
                self._add_lot(connection, user_id, place_id, today - timedelta(days=days), diff)
        return diff

    def move(self, user_id: int, from_place: int, to_place: int, count: int) -> int:
        if from_place == to_place:
            raise ValueError("Выберите разные места.")
        stocks = {s.place.id: s for s in self.contents(user_id)}
        if from_place not in stocks or to_place not in stocks:
            raise ValueError("Место хранения не найдено.")
        if count <= 0:
            raise ValueError("Нужно число яиц больше нуля.")
        with self.database.connect() as connection:
            taken = self._take_from(connection, user_id, list(stocks[from_place].lots), count)
            for lot, amount in taken:
                self._add_lot(connection, user_id, to_place, lot.laid_on, amount)
        return sum(amount for _, amount in taken)


def storage_lines(storage: EggStorage, user_id: int, *, today: date, detailed: bool = False) -> list[str]:
    stocks = storage.contents(user_id)
    if not stocks:
        return []
    total = sum(s.total for s in stocks)
    lines = [f"🧺 Дома {total} яиц: " + ", ".join(f"{s.place.name.lower()} {s.total}" for s in stocks) + "."]
    if detailed:
        for stock in stocks:
            cap = f" из {stock.place.capacity}" if stock.place.capacity else ""
            oldest = stock.oldest()
            age = f", самые старые — {age_text((today - oldest).days)}" if oldest else ""
            lines.append(f"- {stock.place.name}: {stock.total}{cap}{age}.")
    old = storage.older_than(user_id, today=today, days=USE_FIRST_DAYS)
    if old:
        lines.append(f"⚠️ Старше 3 недель: {old} шт. — продайте или используйте в первую очередь.")
    return lines
