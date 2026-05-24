from datetime import date
import sqlite3

from app.domain import IncubationBatch
from app.storage.database import Database


class BatchRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        user_id: int,
        species: str,
        eggs_count: int,
        start_date: date,
        title: str,
        note: str = "",
    ) -> IncubationBatch:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO incubation_batches
                    (user_id, species, eggs_count, start_date, title, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, species, eggs_count, start_date.isoformat(), title, note),
            )
            batch_id = int(cursor.lastrowid)

        return IncubationBatch(
            id=batch_id,
            user_id=user_id,
            species=species,
            eggs_count=eggs_count,
            start_date=start_date,
            title=title,
            note=note,
        )

    def list_active(self, user_id: int) -> list[IncubationBatch]:
        return self._list(
            """
            SELECT id, user_id, species, eggs_count, start_date, title,
                   is_active, hatched_count, completed_at, note
            FROM incubation_batches
            WHERE user_id = ? AND is_active = 1
            ORDER BY start_date DESC, id DESC
            """,
            (user_id,),
        )

    def list_completed(self, user_id: int, limit: int = 20) -> list[IncubationBatch]:
        return self._list(
            """
            SELECT id, user_id, species, eggs_count, start_date, title,
                   is_active, hatched_count, completed_at, note
            FROM incubation_batches
            WHERE user_id = ? AND is_active = 0
            ORDER BY COALESCE(completed_at, start_date) DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )

    def list_all_for_user(self, user_id: int) -> list[IncubationBatch]:
        return self._list(
            """
            SELECT id, user_id, species, eggs_count, start_date, title,
                   is_active, hatched_count, completed_at, note
            FROM incubation_batches
            WHERE user_id = ?
            ORDER BY start_date DESC, id DESC
            """,
            (user_id,),
        )

    def list_active_users(self, on_or_before: date | None = None) -> list[int]:
        date_filter = ""
        params: tuple = ()
        if on_or_before is not None:
            date_filter = "AND start_date <= ?"
            params = (on_or_before.isoformat(),)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT DISTINCT user_id
                FROM incubation_batches
                WHERE is_active = 1
                {date_filter}
                """,
                params,
            ).fetchall()
        return [int(row["user_id"]) for row in rows]

    def list_known_users(self) -> list[int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT user_id
                FROM incubation_batches
                """
            ).fetchall()
        return [int(row["user_id"]) for row in rows]

    def get(self, batch_id: int, user_id: int) -> IncubationBatch | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, species, eggs_count, start_date, title,
                       is_active, hatched_count, completed_at, note
                FROM incubation_batches
                WHERE id = ? AND user_id = ?
                """,
                (batch_id, user_id),
            ).fetchone()
        return self._from_row(row) if row else None

    def update(
        self,
        *,
        batch_id: int,
        user_id: int,
        species: str | None = None,
        eggs_count: int | None = None,
        start_date: date | None = None,
        title: str | None = None,
        note: str | None = None,
    ) -> IncubationBatch | None:
        current = self.get(batch_id, user_id)
        if current is None:
            return None

        next_species = species if species is not None else current.species
        next_eggs_count = eggs_count if eggs_count is not None else current.eggs_count
        next_start_date = start_date if start_date is not None else current.start_date
        next_title = title if title is not None else current.title
        next_note = note if note is not None else current.note

        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE incubation_batches
                SET species = ?, eggs_count = ?, start_date = ?, title = ?, note = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    next_species,
                    next_eggs_count,
                    next_start_date.isoformat(),
                    next_title,
                    next_note,
                    batch_id,
                    user_id,
                ),
            )
        return self.get(batch_id, user_id)

    def complete(
        self,
        *,
        batch_id: int,
        user_id: int,
        hatched_count: int,
        completed_at: date,
    ) -> IncubationBatch | None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE incubation_batches
                SET is_active = 0, hatched_count = ?, completed_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (hatched_count, completed_at.isoformat(), batch_id, user_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(batch_id, user_id)

    def reopen(self, batch_id: int, user_id: int) -> IncubationBatch | None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE incubation_batches
                SET is_active = 1, hatched_count = NULL, completed_at = NULL
                WHERE id = ? AND user_id = ?
                """,
                (batch_id, user_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(batch_id, user_id)

    def _list(self, query: str, params: tuple) -> list[IncubationBatch]:
        with self.database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> IncubationBatch:
        completed_at = row["completed_at"]
        hatched_count = row["hatched_count"]
        return IncubationBatch(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            species=str(row["species"]),
            eggs_count=int(row["eggs_count"]),
            start_date=date.fromisoformat(str(row["start_date"])),
            title=str(row["title"]),
            is_active=bool(row["is_active"]),
            hatched_count=int(hatched_count) if hatched_count is not None else None,
            completed_at=date.fromisoformat(str(completed_at)) if completed_at else None,
            note=str(row["note"] or ""),
        )
