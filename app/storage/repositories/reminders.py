from datetime import date
import sqlite3

from app.domain import ReminderSettings
from app.storage.database import Database


class ReminderRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, user_id: int) -> ReminderSettings:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT user_id, is_enabled, hour, minute, last_sent_date
                FROM reminder_settings
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row:
            return self._from_row(row)
        return ReminderSettings(user_id=user_id, is_enabled=False, hour=9, minute=0)

    def exists(self, user_id: int) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM reminder_settings WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return row is not None

    def upsert(
        self,
        *,
        user_id: int,
        is_enabled: bool,
        hour: int,
        minute: int,
        last_sent_date: date | None = None,
    ) -> ReminderSettings:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO reminder_settings
                    (user_id, is_enabled, hour, minute, last_sent_date)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    is_enabled = excluded.is_enabled,
                    hour = excluded.hour,
                    minute = excluded.minute,
                    last_sent_date = COALESCE(
                        excluded.last_sent_date,
                        reminder_settings.last_sent_date
                    )
                """,
                (
                    user_id,
                    int(is_enabled),
                    hour,
                    minute,
                    last_sent_date.isoformat() if last_sent_date else None,
                ),
            )
        return self.get(user_id)

    def mark_sent(self, user_id: int, sent_date: date) -> None:
        current = self.get(user_id)
        self.upsert(
            user_id=user_id,
            is_enabled=current.is_enabled,
            hour=current.hour,
            minute=current.minute,
            last_sent_date=sent_date,
        )

    def list_enabled(self) -> list[ReminderSettings]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id, is_enabled, hour, minute, last_sent_date
                FROM reminder_settings
                WHERE is_enabled = 1
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_known_users(self) -> list[int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT user_id
                FROM reminder_settings
                """
            ).fetchall()
        return [int(row["user_id"]) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ReminderSettings:
        last_sent_date = row["last_sent_date"]
        return ReminderSettings(
            user_id=int(row["user_id"]),
            is_enabled=bool(row["is_enabled"]),
            hour=int(row["hour"]),
            minute=int(row["minute"]),
            last_sent_date=date.fromisoformat(str(last_sent_date)) if last_sent_date else None,
        )
