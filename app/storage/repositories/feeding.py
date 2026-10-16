from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json

from app.storage.database import Database


@dataclass(frozen=True)
class FeedingEvent:
    id: int
    user_id: int
    fed_at: datetime
    fed_date: date
    bird_count: int
    daily_norm_kg: float
    note: str
    cups: float | None = None
    mix_kg: float | None = None


@dataclass(frozen=True)
class FeedingEventItem:
    id: int
    event_id: int
    name: str
    kg: float
    stock_item_id: int | None
    stock_transaction_id: int | None


@dataclass(frozen=True)
class FeedingSettings:
    user_id: int
    cup_liters: float = 1.0
    mix: tuple[tuple[str, float], ...] | None = None
    last_cups: float | None = None


class FeedingRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add(
        self,
        *,
        user_id: int,
        fed_at: datetime,
        fed_date: date,
        bird_count: int,
        daily_norm_kg: float,
        note: str = "",
        cups: float | None = None,
        mix_kg: float | None = None,
    ) -> FeedingEvent:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO feeding_events (
                    user_id, fed_at, fed_date, bird_count, daily_norm_kg, note, cups, mix_kg
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    fed_at.astimezone(timezone.utc).isoformat(),
                    fed_date.isoformat(),
                    bird_count,
                    daily_norm_kg,
                    note[:255],
                    cups,
                    mix_kg,
                ),
            )
            event_id = int(cursor.lastrowid)
        event = self.get(event_id, user_id)
        assert event is not None
        return event

    def get(self, event_id: int, user_id: int) -> FeedingEvent | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, fed_at, fed_date, bird_count, daily_norm_kg, note, cups, mix_kg
                FROM feeding_events
                WHERE id = ? AND user_id = ?
                """,
                (event_id, user_id),
            ).fetchone()
        return self._from_row(row) if row else None

    def delete(self, event_id: int, user_id: int) -> bool:
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM feeding_event_items WHERE event_id = ? AND user_id = ?",
                (event_id, user_id),
            )
            cursor = connection.execute(
                "DELETE FROM feeding_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            )
        return cursor.rowcount > 0

    def last(self, user_id: int) -> FeedingEvent | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, fed_at, fed_date, bird_count, daily_norm_kg, note, cups, mix_kg
                FROM feeding_events
                WHERE user_id = ?
                ORDER BY fed_at DESC, id DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def between(self, user_id: int, *, start_date: date, end_date: date) -> list[FeedingEvent]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, fed_at, fed_date, bird_count, daily_norm_kg, note, cups, mix_kg
                FROM feeding_events
                WHERE user_id = ? AND fed_date BETWEEN ? AND ?
                ORDER BY fed_at, id
                """,
                (user_id, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def has_any(self, user_id: int) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM feeding_events WHERE user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
        return row is not None

    # --- items ---------------------------------------------------------

    def add_item(
        self,
        *,
        event_id: int,
        user_id: int,
        name: str,
        kg: float,
        stock_item_id: int | None,
        stock_transaction_id: int | None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO feeding_event_items (
                    event_id, user_id, name, kg, stock_item_id, stock_transaction_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, user_id, name[:120], kg, stock_item_id, stock_transaction_id),
            )

    def items(self, event_id: int, user_id: int) -> list[FeedingEventItem]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, event_id, name, kg, stock_item_id, stock_transaction_id
                FROM feeding_event_items
                WHERE event_id = ? AND user_id = ?
                ORDER BY id
                """,
                (event_id, user_id),
            ).fetchall()
        return [
            FeedingEventItem(
                id=int(row["id"]),
                event_id=int(row["event_id"]),
                name=str(row["name"]),
                kg=float(row["kg"]),
                stock_item_id=int(row["stock_item_id"]) if row["stock_item_id"] is not None else None,
                stock_transaction_id=(
                    int(row["stock_transaction_id"]) if row["stock_transaction_id"] is not None else None
                ),
            )
            for row in rows
        ]

    def item_totals_between(self, user_id: int, *, start_date: date, end_date: date) -> dict[str, float]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT i.name AS name, SUM(i.kg) AS kg
                FROM feeding_event_items AS i
                JOIN feeding_events AS e ON e.id = i.event_id
                WHERE e.user_id = ? AND e.fed_date BETWEEN ? AND ?
                GROUP BY i.name
                """,
                (user_id, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return {str(row["name"]): float(row["kg"] or 0) for row in rows}

    # --- settings ------------------------------------------------------

    def get_settings(self, user_id: int) -> FeedingSettings:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT user_id, cup_liters, mix_json, last_cups FROM feeding_settings WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return FeedingSettings(user_id=user_id)
        mix = None
        if row["mix_json"]:
            try:
                mix = tuple((str(name), float(parts)) for name, parts in json.loads(row["mix_json"]))
            except (ValueError, TypeError):
                mix = None
        return FeedingSettings(
            user_id=user_id,
            cup_liters=float(row["cup_liters"] or 1.0),
            mix=mix,
            last_cups=float(row["last_cups"]) if row["last_cups"] is not None else None,
        )

    def save_settings(
        self,
        user_id: int,
        *,
        cup_liters: float | None = None,
        mix: list[tuple[str, float]] | None = None,
        last_cups: float | None = None,
    ) -> FeedingSettings:
        current = self.get_settings(user_id)
        next_cup = cup_liters if cup_liters is not None else current.cup_liters
        next_mix = mix if mix is not None else (list(current.mix) if current.mix else None)
        next_last = last_cups if last_cups is not None else current.last_cups
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO feeding_settings (user_id, cup_liters, mix_json, last_cups, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    cup_liters = excluded.cup_liters,
                    mix_json = excluded.mix_json,
                    last_cups = excluded.last_cups,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    next_cup,
                    json.dumps(next_mix, ensure_ascii=False) if next_mix is not None else None,
                    next_last,
                ),
            )
        return self.get_settings(user_id)

    @staticmethod
    def _from_row(row) -> FeedingEvent:
        fed_at = datetime.fromisoformat(str(row["fed_at"]))
        if fed_at.tzinfo is None:
            fed_at = fed_at.replace(tzinfo=timezone.utc)
        return FeedingEvent(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            fed_at=fed_at,
            fed_date=date.fromisoformat(str(row["fed_date"])),
            bird_count=int(row["bird_count"]),
            daily_norm_kg=float(row["daily_norm_kg"]),
            note=str(row["note"] or ""),
            cups=float(row["cups"]) if "cups" in row.keys() and row["cups"] is not None else None,
            mix_kg=float(row["mix_kg"]) if "mix_kg" in row.keys() and row["mix_kg"] is not None else None,
        )
