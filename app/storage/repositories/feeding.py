from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

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
    ) -> FeedingEvent:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO feeding_events (user_id, fed_at, fed_date, bird_count, daily_norm_kg, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    fed_at.astimezone(timezone.utc).isoformat(),
                    fed_date.isoformat(),
                    bird_count,
                    daily_norm_kg,
                    note[:255],
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
                SELECT id, user_id, fed_at, fed_date, bird_count, daily_norm_kg, note
                FROM feeding_events
                WHERE id = ? AND user_id = ?
                """,
                (event_id, user_id),
            ).fetchone()
        return self._from_row(row) if row else None

    def delete(self, event_id: int, user_id: int) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM feeding_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            )
        return cursor.rowcount > 0

    def last(self, user_id: int) -> FeedingEvent | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, fed_at, fed_date, bird_count, daily_norm_kg, note
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
                SELECT id, user_id, fed_at, fed_date, bird_count, daily_norm_kg, note
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
        )
